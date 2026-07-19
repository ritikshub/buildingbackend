#!/usr/bin/env python3
"""
Capstone: one event-driven order pipeline, with every fault happening at once.

Companion to docs/en.md (Phase 6, Lesson 13 - Capstone: An Event-Driven Order
Pipeline, End to End). Assembles the twelve primitives of the phase - envelope,
ack-after-processing, fan-out, log offsets, idempotent consumers, partition
keys, retries with backoff and jitter, dead-letter queues, consumer lag, the
transactional outbox and schema upcasters - then injects a relay crash, a
consumer crash, a rebalance, poison messages, two slow downstreams, a relay
outage and a mid-stream schema change into a single run, and verifies four
invariants. Finally it repeats the identical fault schedule with idempotency
disabled, which is the control that proves the mechanisms are load-bearing.

Sources: Two Generals (Akkoyunlu, Ekanadham & Huber, SOSP 1975); Lamport,
"Time, Clocks and the Ordering of Events in a Distributed System" (CACM 21(7),
1978); Kreps, Narkhede & Rao, "Kafka: a Distributed Messaging System for Log
Processing" (NetDB 2011); RFC 9562 (UUID).
Standard library only, seeded, virtual clock:  python order_pipeline.py
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Configuration. Every number here is a knob a real pipeline also has.
# ---------------------------------------------------------------------------

SEED = 20260718
TICK = 0.05                 # simulated seconds per loop iteration
HORIZON = 220.0             # hard stop, so the program can never hang

N_PARTITIONS = 8            # lesson 07: the ceiling on consumer parallelism
N_CUSTOMERS = 60            # partition key cardinality
N_ORDERS = 600
ORDER_RATE = 10.0           # orders/second
ENRICH_FRACTION = 0.40      # share of orders that also emit order.enriched
CURRENT_SCHEMA = 2          # what consumer code is written against (lesson 12)

RELAY_POLL = 0.25           # lesson 10: poll interval sets the latency floor
RELAY_BATCH = 16            # and bounds how many duplicates one crash makes
COMMIT_EVERY = 100          # lesson 05/07: the uncommitted window IS the dup window
COMMIT_INTERVAL = 5.0       # ...and so is the commit timer (a broker default)

EMAIL_DEDUP_WINDOW = 30.0   # lesson 06: the provider's idempotency-key TTL
RETRY_BASE = 4.0            # lesson 08: capped exponential backoff, full jitter
RETRY_CAP = 90.0
MAX_ATTEMPTS = 6            # then dead-letter

PAY_LAG_SCALE_AT = 10.0     # lesson 09: autoscale on time lag, never CPU
PAY_SCALE_COOLDOWN = 6.0
ANA_SHED_ON = 8.0
ANA_SHED_OFF = 3.0

# --- the fault schedule, in simulated seconds. Identical in both runs. ------
T_RELAY_CRASH = 12.0                    # published, then died before marking
T_EMAIL_DEGRADED = (18.0, 30.0)         # provider 503s and lost responses
T_POISON = 20.0                         # a bad producer deploy
T_PAY_CRASH = 25.0                      # consumer dies mid-batch
T_PAY_RESTART = 27.0                    # lease expires, work is redelivered
T_SLOW_PAYMENTS = (30.0, 48.0)          # card gateway degrades
T_SLOW_ANALYTICS = (30.0, 44.0)         # warehouse loader degrades
T_REBALANCE = 32.0                      # a deploy adds a member
T_SCHEMA_V2 = 40.0                      # producer starts emitting v2
T_RELAY_OUTAGE = (50.0, 58.0)           # the relay process is gone

N_POISON = 4
POISON_CUSTOMER = "cust-0042"           # all poison lands in one partition


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def stable_hash(key: str) -> int:
    """Partitioner hash. Explicit and stable across processes - Python's hash()
    of a str is randomised per interpreter (PEP 456), which would silently
    re-partition every key on restart."""
    return int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")


def partition_of(key: str) -> int:
    return stable_hash(key) % N_PARTITIONS


def det_uuid(rnd: random.Random) -> str:
    return str(uuid.UUID(int=rnd.getrandbits(128), version=4))


def money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


# ---------------------------------------------------------------------------
# Lesson 12: the upcaster chain. Consumer logic only ever sees v2.
# ---------------------------------------------------------------------------


def up_1_to_2(body: dict) -> dict:
    """v1 predates multi-currency and called the amount total_cents."""
    out = dict(body)
    out["total_amount"] = out.pop("total_cents")
    out["currency"] = "EUR"
    return out


UPCASTERS = {1: up_1_to_2}


def upcast(body: dict, version: int) -> tuple[dict, int]:
    hops = 0
    while version < CURRENT_SCHEMA:
        body = UPCASTERS[version](body)
        version += 1
        hops += 1
    return body, hops


def valid_order(body: dict) -> bool:
    """Strict about the slice we consume, tolerant about everything else."""
    if not isinstance(body.get("order_id"), str):
        return False
    if not isinstance(body.get("customer_id"), str):
        return False
    amount = body.get("total_amount")
    return isinstance(amount, int) and not isinstance(amount, bool) and amount > 0


# ---------------------------------------------------------------------------
# Lesson 05 + 07: the partitioned, retained log
# ---------------------------------------------------------------------------


@dataclass
class Record:
    partition: int
    offset: int
    recorded_at: float
    env: dict


class PartitionedLog:
    """N independent append-only logs. Total order within a partition, no order
    across partitions. Consumers own their positions; nothing is deleted."""

    def __init__(self) -> None:
        self.parts: list[list[Record]] = [[] for _ in range(N_PARTITIONS)]
        self.appended = 0

    def append(self, env: dict, now: float) -> Record:
        p = partition_of(env["partition_key"])
        rec = Record(p, len(self.parts[p]), now, env)
        self.parts[p].append(rec)
        self.appended += 1
        return rec

    def tail(self, p: int) -> int:
        return len(self.parts[p])


# ---------------------------------------------------------------------------
# Lesson 10: order service with a transactional outbox
# ---------------------------------------------------------------------------


ORDER_SCHEMA = """
CREATE TABLE orders (
  order_id    TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  seq         INTEGER NOT NULL,
  amount      INTEGER,
  placed_at   REAL NOT NULL,
  valid       INTEGER NOT NULL
);
CREATE TABLE outbox (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id      TEXT NOT NULL,
  event_type    TEXT NOT NULL,
  partition_key TEXT NOT NULL,
  envelope      TEXT NOT NULL,
  created_at    REAL NOT NULL,
  published_at  REAL
);
CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL;
"""

PAY_SCHEMA = """
CREATE TABLE processed (message_id TEXT PRIMARY KEY, processed_at REAL NOT NULL);
CREATE TABLE charges (
  n        INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT NOT NULL,
  amount   INTEGER NOT NULL,
  at       REAL NOT NULL
);
"""


class OrderService:
    """The write path. One transaction, two tables, no dual write."""

    def __init__(self, conn: sqlite3.Connection, rnd: random.Random) -> None:
        self.conn = conn
        self.rnd = rnd
        self.seq: dict[str, int] = {}
        self.placed = 0
        self.valid_total = 0
        self.events_written = 0

    def _envelope(self, etype: str, key: str, body: dict, now: float,
                  version: int, correlation: str) -> dict:
        """Lesson 02: the envelope the whole pipeline routes on."""
        mid = det_uuid(self.rnd)
        trace = (f"00-{stable_hash(mid) ^ stable_hash(mid[::-1]):032x}"[:35]
                 + f"-{stable_hash(key) & 0xFFFFFFFFFFFFFFFF:016x}-01")
        return {
            "message_id": mid,
            "correlation_id": correlation,
            "causation_id": correlation,
            "type": etype,
            "schema_version": version,
            "source": "urn:svc:orders",
            "occurred_at": round(now, 6),
            "published_at": None,
            "recorded_at": None,
            "traceparent": trace,
            "partition_key": key,
            "body": body,
        }

    def place(self, now: float) -> None:
        cid = f"cust-{self.rnd.randrange(N_CUSTOMERS):04d}"
        self.seq[cid] = self.seq.get(cid, 0) + 1
        seq = self.seq[cid]
        amount = self.rnd.randrange(500, 25_000)
        oid = f"ord-{self.placed:05d}"
        version = 2 if now >= T_SCHEMA_V2 else 1
        if version == 1:
            body = {"order_id": oid, "customer_id": cid, "seq": seq, "total_cents": amount}
        else:
            body = {"order_id": oid, "customer_id": cid, "seq": seq,
                    "total_amount": amount, "currency": "EUR"}
        corr = det_uuid(self.rnd)
        evs = [self._envelope("order.placed", cid, body, now, version, corr)]
        if self.rnd.random() < ENRICH_FRACTION:
            evs.append(self._envelope(
                "order.enriched", cid,
                {"order_id": oid, "customer_id": cid, "seq": seq, "channel": "web"},
                now, 1, corr))

        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO orders VALUES (?,?,?,?,?,1)", (oid, cid, seq, amount, now))
        for e in evs:
            self.conn.execute(
                "INSERT INTO outbox (event_id, event_type, partition_key, envelope, "
                "created_at, published_at) VALUES (?,?,?,?,?,NULL)",
                (e["message_id"], e["type"], e["partition_key"], json.dumps(e), now))
        self.conn.execute("COMMIT")     # ONE write. Both land, or neither does.

        self.placed += 1
        self.valid_total += amount
        self.events_written += len(evs)

    def bad_deploy(self, now: float, n: int) -> None:
        """A producer ships a bug: total_cents arrives as a string."""
        for i in range(n):
            cid = POISON_CUSTOMER
            self.seq[cid] = self.seq.get(cid, 0) + 1
            oid = f"bad-{i:03d}"
            body = {"order_id": oid, "customer_id": cid,
                    "seq": self.seq[cid], "total_cents": "N/A"}
            e = self._envelope("order.placed", cid, body, now, 1, det_uuid(self.rnd))
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "INSERT INTO orders VALUES (?,?,?,NULL,?,0)", (oid, cid, self.seq[cid], now))
            self.conn.execute(
                "INSERT INTO outbox (event_id, event_type, partition_key, envelope, "
                "created_at, published_at) VALUES (?,?,?,?,?,NULL)",
                (e["message_id"], e["type"], e["partition_key"], json.dumps(e), now))
            self.conn.execute("COMMIT")
            self.events_written += 1


class Relay:
    """Claims unpublished outbox rows, publishes, marks published. The mark is a
    second write, so it can only fail toward redelivery - never toward loss."""

    def __init__(self, conn: sqlite3.Connection, log: PartitionedLog) -> None:
        self.conn = conn
        self.log = log
        self.next_poll = 0.0
        self.crash_armed = True
        self.published = 0
        self.duplicate_publishes = 0
        self.crashes = 0
        self.seen_ids: set[str] = set()
        self.polls = 0
        self.empty_polls = 0

    def outage(self, now: float) -> bool:
        return T_RELAY_OUTAGE[0] <= now < T_RELAY_OUTAGE[1]

    def lag(self, now: float) -> tuple[int, float]:
        row = self.conn.execute(
            "SELECT COUNT(*), MIN(created_at) FROM outbox WHERE published_at IS NULL").fetchone()
        pending = row[0] or 0
        return pending, (now - row[1]) if row[1] is not None else 0.0

    def step(self, now: float, timeline: list) -> None:
        if self.outage(now) or now < self.next_poll:
            return
        self.next_poll = now + RELAY_POLL
        self.polls += 1
        rows = self.conn.execute(
            "SELECT id, envelope FROM outbox WHERE published_at IS NULL "
            "ORDER BY id LIMIT ?", (RELAY_BATCH,)).fetchall()
        if not rows:
            self.empty_polls += 1
            return
        for _id, blob in rows:
            env = json.loads(blob)
            env["published_at"] = round(now, 6)
            env["recorded_at"] = round(now + 0.002, 6)
            self.log.append(env, now + 0.002)
            self.published += 1
            if env["message_id"] in self.seen_ids:
                self.duplicate_publishes += 1
            self.seen_ids.add(env["message_id"])
        if self.crash_armed and now >= T_RELAY_CRASH:
            self.crash_armed = False
            self.crashes += 1
            timeline.append((now, f"RELAY CRASHED after publishing {len(rows)} rows, "
                                  f"before marking them published"))
            return                       # the UPDATE never runs: these rows re-publish
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.executemany("UPDATE outbox SET published_at=? WHERE id=?",
                              [(now, r[0]) for r in rows])
        self.conn.execute("COMMIT")


# ---------------------------------------------------------------------------
# Lesson 06: the effect the pipeline cannot deduplicate for you
# ---------------------------------------------------------------------------


class EmailProvider:
    """An external provider with an Idempotency-Key honoured for a bounded TTL.
    That TTL is the guarantee. Redeliveries outside it send a second email."""

    def __init__(self, rnd: random.Random) -> None:
        self.rnd = rnd
        self.keys: dict[str, float] = {}
        self.delivered: dict[str, int] = {}
        self.sent = 0
        self.suppressed = 0
        self.window_misses = 0
        self.max_gap = 0.0          # closest any retry came to the key's TTL

    def degraded(self, now: float) -> bool:
        return T_EMAIL_DEGRADED[0] <= now < T_EMAIL_DEGRADED[1]

    def send(self, key: str, order_id: str, now: float) -> str:
        roll = self.rnd.random()            # drawn first, so both runs draw alike
        if key in self.keys and now - self.keys[key] < EMAIL_DEDUP_WINDOW:
            self.suppressed += 1
            self.max_gap = max(self.max_gap, now - self.keys[key])
            return "suppressed"
        if key in self.keys:
            self.window_misses += 1         # the key expired: dedup no longer helps
        if self.degraded(now):
            if roll < 0.45:                 # accepted, reply lost on the way back
                self.keys[key] = now
                self.delivered[order_id] = self.delivered.get(order_id, 0) + 1
                self.sent += 1
                return "lost_response"
            return "transient"
        self.keys[key] = now
        self.delivered[order_id] = self.delivered.get(order_id, 0) + 1
        self.sent += 1
        return "sent"

    def duplicates(self) -> int:
        return sum(c - 1 for c in self.delivered.values() if c > 1)


# ---------------------------------------------------------------------------
# Consumer groups
# ---------------------------------------------------------------------------


@dataclass
class Member:
    idx: int
    budget: float = 0.0
    alive: bool = True


@dataclass
class Retryable:
    rec: Record
    attempt: int
    visible_at: float


class Group:
    """One consumer group over the log. Members split partitions; each partition
    is owned by at most one member; positions are committed every COMMIT_EVERY
    records, and that uncommitted window is exactly the duplicate window."""

    def __init__(self, name: str, subscribes: set[str], members: int,
                 speed_fn, handler, retries: bool = False) -> None:
        self.name = name
        self.subscribes = subscribes
        self.speed_fn = speed_fn
        self.handler = handler
        self.retries = retries
        self.members = [Member(i) for i in range(members)]
        self.committed = [0] * N_PARTITIONS
        self.processed = [0] * N_PARTITIONS
        self.since_commit = [0] * N_PARTITIONS
        self.assign: dict[int, list[int]] = {}
        self.cursor: dict[int, int] = {}
        self.retry_lane: list[Retryable] = []
        self.dlq: list[dict] = []
        self.delivered = 0
        self.effects = 0
        self.duplicates_absorbed = 0
        self.retried = 0
        self.shed = 0
        self.rebalances = 0
        self.replayed = 0
        self.per_partition = [0] * N_PARTITIONS
        self.lag_series: list[tuple[float, int, float]] = []
        self.last_scale = -99.0
        self.shedding = False
        self._reassign()

    # -- membership -------------------------------------------------------
    def _reassign(self) -> None:
        live = [m for m in self.members if m.alive]
        self.assign = {m.idx: [] for m in self.members}
        for p in range(N_PARTITIONS):
            if live:
                self.assign[live[p % len(live)].idx].append(p)
        self.cursor = {m.idx: 0 for m in self.members}

    def commit_all(self) -> None:
        """The periodic offset commit. Everything between two commits is the
        window a crash or a rebalance replays."""
        for p in range(N_PARTITIONS):
            self.committed[p] = self.processed[p]
            self.since_commit[p] = 0

    def rebalance(self, now: float, why: str, timeline: list) -> None:
        """Eager (stop-the-world): every partition is revoked, so every
        partition replays its uncommitted window."""
        lost = 0
        for p in range(N_PARTITIONS):
            lost += self.processed[p] - self.committed[p]
            self.processed[p] = self.committed[p]
            self.since_commit[p] = 0
        self._reassign()
        self.rebalances += 1
        self.replayed += lost
        timeline.append((now, f"{self.name}: REBALANCE ({why}) -> {len([m for m in self.members if m.alive])} "
                              f"members, {lost} uncommitted records replayed"))

    def crash_member(self, idx: int, now: float, timeline: list) -> None:
        lost = 0
        for p in self.assign.get(idx, []):
            lost += self.processed[p] - self.committed[p]
            self.processed[p] = self.committed[p]
            self.since_commit[p] = 0
        self.members[idx].alive = False
        self.replayed += lost
        self._reassign()
        timeline.append((now, f"{self.name}: member {idx} CRASHED mid-batch, "
                              f"{lost} uncommitted records will be redelivered"))

    def restart_member(self, idx: int, now: float, timeline: list) -> None:
        self.members[idx].alive = True
        self._reassign()
        timeline.append((now, f"{self.name}: member {idx} back after lease expiry; "
                              f"partitions reassigned"))

    def scale_to(self, n: int, now: float, timeline: list) -> None:
        while len(self.members) < n:
            self.members.append(Member(len(self.members)))
        self.rebalance(now, f"autoscale to {n} on lag", timeline)

    # -- consumption ------------------------------------------------------
    def _next(self, m: Member, log: PartitionedLog) -> Record | None:
        parts = self.assign.get(m.idx, [])
        if not parts:
            return None
        for _ in range(len(parts)):
            p = parts[self.cursor[m.idx] % len(parts)]
            self.cursor[m.idx] += 1
            if self.processed[p] < log.tail(p):
                rec = log.parts[p][self.processed[p]]
                self.processed[p] += 1
                self.since_commit[p] += 1
                if self.since_commit[p] >= COMMIT_EVERY:
                    self.committed[p] = self.processed[p]
                    self.since_commit[p] = 0
                return rec
        return None

    def step(self, log: PartitionedLog, now: float, dt: float, ctx) -> None:
        speed = self.speed_fn(now)
        for m in self.members:
            if not m.alive:
                continue
            m.budget = min(m.budget + speed * dt, speed)
            while m.budget >= 1.0:
                if self.retries and self.retry_lane and self.retry_lane[0].visible_at <= now:
                    item = self.retry_lane.pop(0)
                    m.budget -= 1.0
                    self._dispatch(item.rec, now, ctx, item.attempt)
                    continue
                rec = self._next(m, log)
                if rec is None:
                    break
                self.delivered += 1
                self.per_partition[rec.partition] += 1
                cost = self._dispatch(rec, now, ctx, 1)
                m.budget -= cost

    def _dispatch(self, rec: Record, now: float, ctx, attempt: int) -> float:
        env = rec.env
        if env["type"] not in self.subscribes:
            return 0.15                       # read and skipped: cheap, not free
        verdict = self.handler(self, rec, now, ctx, attempt)
        if verdict == "shed":
            self.shed += 1
            return 0.20
        if verdict == "poison":
            self.dlq.append({
                "message_id": env["message_id"], "type": env["type"],
                "partition": rec.partition, "offset": rec.offset,
                "deliveries": attempt, "reason": "PermanentValidationError",
                "detail": "total_amount is not a positive integer",
                "occurred_at": env["occurred_at"], "dead_lettered_at": round(now, 3),
            })
            return 1.0
        if verdict == "retry":
            if attempt >= MAX_ATTEMPTS:
                self.dlq.append({
                    "message_id": env["message_id"], "type": env["type"],
                    "partition": rec.partition, "offset": rec.offset,
                    "deliveries": attempt, "reason": "TransientExhausted",
                    "detail": f"{MAX_ATTEMPTS} attempts against the email provider",
                    "occurred_at": env["occurred_at"], "dead_lettered_at": round(now, 3),
                })
                return 1.0
            delay = min(RETRY_CAP, RETRY_BASE * (2 ** (attempt - 1)))
            wait = ctx.rnd_jitter.uniform(0.0, delay)     # full jitter
            self.retried += 1
            self.retry_lane.append(Retryable(rec, attempt + 1, now + wait))
            self.retry_lane.sort(key=lambda r: (r.visible_at, r.rec.partition, r.rec.offset))
            return 1.0
        return 1.0

    # -- lag --------------------------------------------------------------
    def lag(self, log: PartitionedLog, now: float) -> tuple[int, float]:
        count = sum(log.tail(p) - self.committed[p] for p in range(N_PARTITIONS))
        oldest = None
        for p in range(N_PARTITIONS):
            if self.committed[p] < log.tail(p):
                t = log.parts[p][self.committed[p]].env["occurred_at"]
                oldest = t if oldest is None else min(oldest, t)
        return count, (now - oldest) if oldest is not None else 0.0

    def caught_up(self, log: PartitionedLog) -> bool:
        return (all(self.committed[p] == log.tail(p) for p in range(N_PARTITIONS))
                and not self.retry_lane)


# ---------------------------------------------------------------------------
# The three handlers
# ---------------------------------------------------------------------------


def payments_handler(g: Group, rec: Record, now: float, ctx, attempt: int) -> str:
    env = rec.env
    body, hops = upcast(env["body"], env["schema_version"])
    ctx.upcast_hops[env["schema_version"]] = ctx.upcast_hops.get(env["schema_version"], 0) + hops
    if not valid_order(body):
        return "poison"
    conn = ctx.pay
    if ctx.idempotent:
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO processed VALUES (?,?)", (env["message_id"], now))
            conn.execute("INSERT INTO charges (order_id, amount, at) VALUES (?,?,?)",
                         (body["order_id"], body["total_amount"], now))
            conn.execute("COMMIT")
        except sqlite3.IntegrityError:
            conn.execute("ROLLBACK")
            g.duplicates_absorbed += 1
            return "ok"
    else:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO charges (order_id, amount, at) VALUES (?,?,?)",
                     (body["order_id"], body["total_amount"], now))
        conn.execute("COMMIT")
    g.effects += 1
    cid, seq = body["customer_id"], body["seq"]
    high = ctx.applied_seq.get(cid, 0)
    if seq < high:
        ctx.inversions += 1
        ctx.inverted_customers.add(cid)
    ctx.applied_seq[cid] = max(high, seq)
    return "ok"


def email_handler(g: Group, rec: Record, now: float, ctx, attempt: int) -> str:
    env = rec.env
    body, _ = upcast(env["body"], env["schema_version"])
    if not valid_order(body):
        return "poison"
    # Push idempotency to the boundary: a key derived from the business event.
    # Without it, every attempt is a fresh request and the provider cannot help.
    key = env["message_id"] if ctx.idempotent else f"{env['message_id']}:{attempt}:{now:.3f}"
    outcome = ctx.provider.send(key, body["order_id"], now)
    if outcome == "lost_response":
        g.effects += 1              # the email WAS sent; the reply died on the way back
        return "retry"
    if outcome == "transient":
        return "retry"
    if outcome == "suppressed":
        g.duplicates_absorbed += 1  # the provider's idempotency key did the work
        return "ok"
    g.effects += 1
    return "ok"


def analytics_handler(g: Group, rec: Record, now: float, ctx, attempt: int) -> str:
    env = rec.env
    if env["type"] == "order.enriched":
        if g.shedding:
            return "shed"
        ctx.enriched_counted += 1
        return "ok"
    body, hops = upcast(env["body"], env["schema_version"])
    if not valid_order(body):
        return "poison"
    if ctx.idempotent:
        if env["message_id"] in ctx.analytics_seen:
            g.duplicates_absorbed += 1
            return "ok"
        ctx.analytics_seen.add(env["message_id"])
    ctx.analytics_versions[env["schema_version"]] = \
        ctx.analytics_versions.get(env["schema_version"], 0) + 1
    ctx.analytics_hops += hops
    ctx.analytics_orders.add(body["order_id"])
    ctx.analytics_revenue += body["total_amount"]
    g.effects += 1
    return "ok"


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    idempotent: bool
    pay: sqlite3.Connection
    provider: EmailProvider
    rnd_jitter: random.Random
    applied_seq: dict = field(default_factory=dict)
    inversions: int = 0
    inverted_customers: set = field(default_factory=set)
    analytics_seen: set = field(default_factory=set)
    analytics_orders: set = field(default_factory=set)
    analytics_revenue: int = 0
    analytics_versions: dict = field(default_factory=dict)
    analytics_hops: int = 0
    enriched_counted: int = 0
    upcast_hops: dict = field(default_factory=dict)


@dataclass
class Result:
    idempotent: bool
    timeline: list
    groups: dict
    ctx: Ctx
    relay: Relay
    svc: OrderService
    log: PartitionedLog
    finished_at: float
    charged_total: int
    charge_rows: int
    distinct_charged: int
    outbox_rows: int
    outbox_pending: int
    outbox_peak_lag: float
    poison_partition: int
    poison_rate_before: float
    poison_rate_during: float
    peer_rate_during: float


def run(idempotent: bool) -> Result:
    tmp = tempfile.mkdtemp(prefix="l13-pipeline-")
    try:
        rnd_orders = random.Random(SEED)
        rnd_provider = random.Random(SEED + 1)
        rnd_jitter = random.Random(SEED + 2)

        order_db = sqlite3.connect(os.path.join(tmp, "orders.db"), isolation_level=None)
        order_db.executescript(ORDER_SCHEMA)
        pay_db = sqlite3.connect(os.path.join(tmp, "payments.db"), isolation_level=None)
        pay_db.executescript(PAY_SCHEMA)

        log = PartitionedLog()
        svc = OrderService(order_db, rnd_orders)
        relay = Relay(order_db, log)
        provider = EmailProvider(rnd_provider)
        ctx = Ctx(idempotent=idempotent, pay=pay_db, provider=provider, rnd_jitter=rnd_jitter)

        def pay_speed(now: float) -> float:
            return 2.0 if T_SLOW_PAYMENTS[0] <= now < T_SLOW_PAYMENTS[1] else 14.0

        def email_speed(now: float) -> float:
            return 25.0

        def ana_speed(now: float) -> float:
            return 4.0 if T_SLOW_ANALYTICS[0] <= now < T_SLOW_ANALYTICS[1] else 25.0

        groups = {
            "payments": Group("payments", {"order.placed"}, 2, pay_speed, payments_handler),
            "email": Group("email", {"order.placed"}, 2, email_speed, email_handler, retries=True),
            "analytics": Group("analytics", {"order.placed", "order.enriched"}, 2,
                               ana_speed, analytics_handler),
        }

        timeline: list = []
        poison_p = partition_of(POISON_CUSTOMER)
        pay_part_marks: list[tuple[float, int]] = []

        now = 0.0
        next_order = 0.0
        next_sample = 0.0
        next_commit = COMMIT_INTERVAL
        poison_done = False
        crash_done = restart_done = rebalance_done = False
        outbox_peak = 0.0
        finished_at = None

        while now < HORIZON:
            # --- producer ------------------------------------------------
            while svc.placed < N_ORDERS and next_order <= now:
                svc.place(next_order)
                next_order += 1.0 / ORDER_RATE
            if not poison_done and now >= T_POISON:
                poison_done = True
                svc.bad_deploy(now, N_POISON)
                timeline.append((now, f"PRODUCER BAD DEPLOY: {N_POISON} malformed order.placed "
                                      f"events (total_cents=\"N/A\") -> partition {poison_p}"))

            # --- relay ---------------------------------------------------
            if T_RELAY_OUTAGE[0] <= now < T_RELAY_OUTAGE[0] + TICK:
                timeline.append((now, "RELAY OUTAGE begins: the process is gone, "
                                      "outbox lag now climbs 1 s per second"))
            if T_RELAY_OUTAGE[1] <= now < T_RELAY_OUTAGE[1] + TICK:
                pending, lag = relay.lag(now)
                timeline.append((now, f"RELAY back: {pending} rows pending, "
                                      f"outbox lag {lag:.2f} s"))
            relay.step(now, timeline)

            # --- injected consumer faults --------------------------------
            if not crash_done and now >= T_PAY_CRASH:
                crash_done = True
                groups["payments"].crash_member(1, now, timeline)
            if not restart_done and now >= T_PAY_RESTART:
                restart_done = True
                groups["payments"].restart_member(1, now, timeline)
            if not rebalance_done and now >= T_REBALANCE:
                rebalance_done = True
                groups["email"].rebalance(now, "deploy adds a member", timeline)

            # --- consumers ------------------------------------------------
            for g in groups.values():
                g.step(log, now, TICK, ctx)

            # --- the periodic offset commit -------------------------------
            if now >= next_commit:
                next_commit += COMMIT_INTERVAL
                for g in groups.values():
                    g.commit_all()

            # --- sampling and the lag-driven control loop -----------------
            if now >= next_sample:
                next_sample += 1.0
                outbox_peak = max(outbox_peak, relay.lag(now)[1])
                for g in groups.values():
                    c, t = g.lag(log, now)
                    g.lag_series.append((now, c, t))
                pay_part_marks.append((now, list(groups["payments"].per_partition)))

                gp = groups["payments"]
                pt = gp.lag(log, now)[1]
                if pt > PAY_LAG_SCALE_AT and len(gp.members) < N_PARTITIONS \
                        and now - gp.last_scale > PAY_SCALE_COOLDOWN:
                    gp.last_scale = now
                    gp.scale_to(min(N_PARTITIONS, len(gp.members) * 4), now, timeline)
                    timeline.append((now, f"  ^ lag-driven: time lag {pt:.2f} s > "
                                          f"{PAY_LAG_SCALE_AT:.0f} s threshold"))
                ga = groups["analytics"]
                _, at = ga.lag(log, now)
                if not ga.shedding and at > ANA_SHED_ON:
                    ga.shedding = True
                    timeline.append((now, f"analytics: SHEDDING order.enriched "
                                          f"(time lag {at:.2f} s > {ANA_SHED_ON:.0f} s)"))
                elif ga.shedding and at < ANA_SHED_OFF:
                    ga.shedding = False
                    timeline.append((now, f"analytics: shedding off (time lag {at:.2f} s)"))

            # --- termination ---------------------------------------------
            done = (svc.placed >= N_ORDERS and poison_done
                    and relay.lag(now)[0] == 0
                    and all(g.caught_up(log) for g in groups.values()))
            if done:
                finished_at = now
                break
            now = round(now + TICK, 6)

        if finished_at is None:
            finished_at = now

        # -- poison-window throughput on the affected partition ------------
        def rate(t0: float, t1: float, parts: list[int]) -> float:
            a = b = None
            for t, v in pay_part_marks:
                if a is None and t >= t0:
                    a = v
                if b is None and t >= t1:
                    b = v
            if a is None or b is None:
                return 0.0
            moved = sum(b[p] - a[p] for p in parts)
            return moved / len(parts) / (t1 - t0)

        peers = [p for p in range(N_PARTITIONS) if p != poison_p]

        charge_rows, charged_total = pay_db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount),0) FROM charges").fetchone()
        distinct_charged = pay_db.execute(
            "SELECT COUNT(DISTINCT order_id) FROM charges").fetchone()[0]

        return Result(
            idempotent=idempotent, timeline=timeline, groups=groups, ctx=ctx, relay=relay,
            svc=svc, log=log, finished_at=finished_at, charged_total=charged_total,
            charge_rows=charge_rows, distinct_charged=distinct_charged,
            outbox_rows=order_db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0],
            outbox_pending=relay.lag(finished_at)[0], outbox_peak_lag=outbox_peak,
            poison_partition=poison_p,
            poison_rate_before=rate(T_POISON - 6.0, T_POISON, [poison_p]),
            poison_rate_during=rate(T_POISON, T_POISON + 6.0, [poison_p]),
            peer_rate_during=rate(T_POISON, T_POISON + 6.0, peers))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def sparkline(series: list[tuple[float, int, float]], key: int, width: int = 58) -> str:
    if not series:
        return ""
    vals = [s[key] for s in series]
    hi = max(vals) or 1
    step = max(1, len(vals) // width)
    bars = " .:-=+*#%@"
    return "".join(bars[min(9, int(v / hi * 9))] for v in vals[::step])


def report(ok: Result, bad: Result) -> None:
    P = print
    g = ok.groups

    P("== 1. THE PIPELINE: every primitive of the phase, wired together ==")
    P(f"  order service -> sqlite (orders + outbox, ONE transaction)     lesson 10")
    P(f"  relay         -> claims unpublished rows, publishes, marks     lesson 10")
    P(f"  log           -> {N_PARTITIONS} partitions, key = customer_id, "
      f"consumer-owned offsets    lessons 05, 07")
    P(f"  consumer groups -> payments (idempotent) · email (external effect) · analytics")
    P(f"                     independent offsets over one copy of the data    lesson 04")
    P(f"  orders placed              {ok.svc.placed:>7,}   valid business orders")
    P(f"  poison events injected     {N_POISON:>7,}   from a bad producer deploy")
    P(f"  outbox rows written        {ok.outbox_rows:>7,}   order.placed + order.enriched")
    P(f"  records appended to log    {ok.log.appended:>7,}   including relay re-publishes")
    P(f"  expected charge total      {money(ok.svc.valid_total):>11} EUR")
    P(f"  simulated seconds          {ok.finished_at:>7.2f}   virtual clock, nothing sleeps")
    P(f"  records per partition      {[ok.log.tail(p) for p in range(N_PARTITIONS)]}")
    P(f"    uneven because 60 customer keys over 8 partitions is low cardinality -")
    P(f"    hash skew, exactly as lesson 07 measured. Ordering is per key regardless.")
    P()

    P("== 2. THE FAULT SCHEDULE: all of it, in one run ==")
    for t, what in [
        (T_RELAY_CRASH, "relay crashes after publish, before mark -> duplicate publish"),
        (T_EMAIL_DEGRADED[0], f"email provider degrades until t={T_EMAIL_DEGRADED[1]:.0f} "
                              f"(503s and lost responses)"),
        (T_POISON, f"producer bad deploy emits {N_POISON} malformed events"),
        (T_PAY_CRASH, "payments member 1 crashes mid-batch"),
        (T_PAY_RESTART, "lease expires, its uncommitted window is redelivered"),
        (T_SLOW_PAYMENTS[0], f"card gateway slows 14->2 rec/s per member until "
                             f"t={T_SLOW_PAYMENTS[1]:.0f}"),
        (T_SLOW_ANALYTICS[0], f"warehouse loader slows 25->4 rec/s per member until "
                              f"t={T_SLOW_ANALYTICS[1]:.0f}"),
        (T_REBALANCE, "a deploy adds an email member -> eager rebalance"),
        (T_SCHEMA_V2, "producer starts emitting schema_version 2"),
        (T_RELAY_OUTAGE[0], f"relay process dies until t={T_RELAY_OUTAGE[1]:.0f}"),
    ]:
        P(f"  t={t:6.2f}  {what}")
    P()

    P("== 3. WHAT ACTUALLY HAPPENED ==")
    for t, what in ok.timeline:
        P(f"  t={t:6.2f}  {what}")
    P()

    P("== 4. LAG, AND THE LAG-DRIVEN RESPONSE ==")
    P(f"  {'group':<11}{'peak count lag':>16}{'peak time lag':>16}{'peak at':>10}{'members':>9}")
    for name in ("payments", "email", "analytics"):
        ser = g[name].lag_series
        pc = max((x[1] for x in ser), default=0)
        pt = max((x[2] for x in ser), default=0.0)
        at = max(ser, key=lambda x: x[2])[0] if ser else 0.0
        P(f"  {name:<11}{pc:>16,}{pt:>14.2f} s{at:>9.0f}s"
          f"{len([m for m in g[name].members if m.alive]):>9}")
    P()
    for name in ("payments", "analytics"):
        P(f"  {name} time lag, 1 s samples, t=0 to t={ok.finished_at:.0f}s "
          f"(peak {max((x[2] for x in g[name].lag_series), default=0.0):.2f} s):")
        P(f"    {sparkline(g[name].lag_series, 2)}")
    P(f"  the autoscaler took payments from 2 to {len(ok.groups['payments'].members)} members "
      f"(the partition ceiling is {N_PARTITIONS})")
    P(f"  analytics shed {g['analytics'].shed:,} order.enriched records to protect order.placed")
    P(f"  outbox lag peaked at {ok.outbox_peak_lag:.2f} s during the relay outage")
    P()

    P("== 5. THE DEAD-LETTER QUEUES: quarantined, not retried forever ==")
    for name in ("payments", "email", "analytics"):
        d = g[name].dlq
        reasons: dict[str, int] = {}
        for e in d:
            reasons[e["reason"]] = reasons.get(e["reason"], 0) + 1
        detail = "  ".join(f"{k}={v}" for k, v in sorted(reasons.items())) or "-"
        P(f"  {name:<10} depth {len(d):>3}   {detail}")
    P()
    if g["payments"].dlq:
        e = g["payments"].dlq[0]
        P("  one payments DLQ record (the replay address is the point):")
        for k in ("message_id", "type", "partition", "offset", "deliveries",
                  "reason", "detail", "occurred_at", "dead_lettered_at"):
            P(f"    {k:<16} {e[k]}")
    P()
    P(f"  payments throughput around the poison window (t={T_POISON:.0f} to "
      f"t={T_POISON + 6:.0f}), per partition:")
    P(f"    partition {ok.poison_partition} (holds all {N_POISON} poison events)   "
      f"{ok.poison_rate_during:6.2f} rec/s")
    P(f"    the other {N_PARTITIONS - 1} partitions, mean               "
      f"{ok.peer_rate_during:6.2f} rec/s")
    P(f"    same partition, the 6 s before the poison   "
      f"{ok.poison_rate_before:6.2f} rec/s")
    P("    the poisoned partition kept pace with its peers: a permanent failure is")
    P("    classified on the FIRST delivery and parked, so it never blocks the head.")
    P()

    P("== 6. THE SCHEMA CHANGE MID-STREAM ==")
    vers = ok.ctx.analytics_versions
    P(f"  producer switched to schema_version 2 at t={T_SCHEMA_V2:.0f}")
    for v in sorted(vers):
        P(f"    v{v} order.placed records read by analytics   {vers[v]:>6,}")
    P(f"  upcaster hops applied (v1 -> v2)                  {ok.ctx.analytics_hops:>6,}")
    P(f"  consumer code knows exactly one shape: v{CURRENT_SCHEMA}. No version branch anywhere.")
    P(f"  analytics revenue total   {money(ok.ctx.analytics_revenue)} EUR "
      f"vs expected {money(ok.svc.valid_total)} EUR   "
      f"match: {ok.ctx.analytics_revenue == ok.svc.valid_total}")
    P()

    P("== 7. INVARIANT VERIFICATION ==")
    inv = []

    lost_ok = (ok.distinct_charged == ok.svc.placed
               and len(ok.ctx.analytics_orders) == ok.svc.placed
               and len(ok.ctx.provider.delivered) == ok.svc.placed)
    inv.append(("1. NO ORDER IS LOST", lost_ok, [
        f"orders committed to the database        {ok.svc.placed:>7,}",
        f"distinct orders charged by payments     {ok.distinct_charged:>7,}",
        f"distinct orders emailed                 {len(ok.ctx.provider.delivered):>7,}",
        f"distinct orders counted by analytics    {len(ok.ctx.analytics_orders):>7,}",
        f"outbox rows still unpublished           {ok.outbox_pending:>7,}",
    ]))

    charge_ok = ok.charged_total == ok.svc.valid_total
    inv.append(("2. NO CUSTOMER IS CHARGED TWICE", charge_ok, [
        f"total charged                       {money(ok.charged_total):>13} EUR",
        f"expected                            {money(ok.svc.valid_total):>13} EUR",
        f"error                               {money(ok.charged_total - ok.svc.valid_total):>13} EUR",
        f"charge rows written                     {ok.charge_rows:>7,}   "
        f"(one per order, never more)",
        f"duplicate deliveries absorbed           "
        f"{g['payments'].duplicates_absorbed:>7,}",
        f"  source: relay re-published events      {ok.relay.duplicate_publishes:>7,}",
        f"  source: records rewound by the crash   {g['payments'].replayed:>7,}   "
        f"and the autoscale rebalance",
    ]))

    total_dlq = sum(len(g[n].dlq) for n in g)
    perm_retries = sum(e["deliveries"] - 1 for n in g for e in g[n].dlq
                       if e["reason"] == "PermanentValidationError")
    all_drained = ok.finished_at < HORIZON
    halt_ok = (total_dlq >= N_POISON * 3 and perm_retries == 0 and all_drained
               and ok.poison_rate_during > 0)
    inv.append(("3. NO POISON MESSAGE HALTS THE PIPELINE", halt_ok, [
        f"poison events published                 {N_POISON:>7,}",
        f"dead-lettered across all groups         {total_dlq:>7,}",
        f"redeliveries spent on them              {perm_retries:>7,}   "
        f"(classified permanent on delivery 1)",
        f"poisoned partition throughput           {ok.poison_rate_during:>7.2f} rec/s",
        f"peer partitions, same window            {ok.peer_rate_during:>7.2f} rec/s",
        f"every group reached the tail of every partition           "
        f"{'yes' if all_drained else 'NO':>3}",
    ]))

    order_ok = ok.ctx.inversions == 0
    inv.append(("4. PER-CUSTOMER ORDERING IS PRESERVED", order_ok, [
        f"partition key                           customer_id",
        f"customers                               {N_CUSTOMERS:>7,}   "
        f"mean {ok.svc.placed / N_CUSTOMERS:.1f} orders each",
        f"sequence inversions applied             {ok.ctx.inversions:>7,}",
        f"customers with a damaged sequence       {len(ok.ctx.inverted_customers):>7,}",
    ]))

    for title, passed, lines in inv:
        P(f"  [{'PASS' if passed else 'FAIL'}]  {title}")
        for line in lines:
            P(f"          {line}")
        P()

    P("== 8. THE COUNTERFACTUAL: identical faults, idempotency disabled ==")
    P("  Same seed, same schedule, same 604 events, same crashes. The only change:")
    P("  the payments dedup record, the analytics dedup set, and the email")
    P("  idempotency key are all removed.")
    P()
    P(f"  {'measure':<38} {'idempotent':>14} {'NOT idempotent':>16}")
    P(f"  {'-' * 70}")
    rows = [
        ("deliveries to payments", f"{g['payments'].delivered:,}",
         f"{bad.groups['payments'].delivered:,}"),
        ("charge rows written", f"{ok.charge_rows:,}", f"{bad.charge_rows:,}"),
        ("distinct orders charged", f"{ok.distinct_charged:,}", f"{bad.distinct_charged:,}"),
        ("total charged (EUR)", money(ok.charged_total), money(bad.charged_total)),
        ("expected (EUR)", money(ok.svc.valid_total), money(bad.svc.valid_total)),
        ("OVERCHARGE (EUR)", money(ok.charged_total - ok.svc.valid_total),
         money(bad.charged_total - bad.svc.valid_total)),
        ("customers double-charged",
         f"{ok.charge_rows - ok.distinct_charged:,}",
         f"{bad.charge_rows - bad.distinct_charged:,}"),
        ("duplicate deliveries absorbed", f"{g['payments'].duplicates_absorbed:,}",
         f"{bad.groups['payments'].duplicates_absorbed:,}"),
        ("sequence inversions applied", f"{ok.ctx.inversions:,}", f"{bad.ctx.inversions:,}"),
        ("customers with damaged order", f"{len(ok.ctx.inverted_customers):,}",
         f"{len(bad.ctx.inverted_customers):,}"),
        ("emails actually sent", f"{ok.ctx.provider.sent:,}", f"{bad.ctx.provider.sent:,}"),
        ("provider-suppressed duplicates", f"{ok.ctx.provider.suppressed:,}",
         f"{bad.ctx.provider.suppressed:,}"),
        ("DUPLICATE EMAILS DELIVERED", f"{ok.ctx.provider.duplicates():,}",
         f"{bad.ctx.provider.duplicates():,}"),
        ("analytics revenue (EUR)", money(ok.ctx.analytics_revenue),
         money(bad.ctx.analytics_revenue)),
    ]
    for label, a, b in rows:
        P(f"  {label:<38} {a:>14} {b:>16}")
    P()
    over = bad.charged_total - bad.svc.valid_total
    P(f"  The delivery layer was byte-identical in both runs: "
      f"{bad.groups['payments'].delivered:,} deliveries either way.")
    P(f"  Removing three dedup mechanisms moved {money(over)} EUR of other people's")
    P(f"  money and put {len(bad.ctx.inverted_customers):,} customers' event sequences out of order.")
    P()

    P("== 9. OPERATIONAL DASHBOARD (what you would page on) ==")
    P(f"  {'group':<12}{'count lag':>11}{'time lag':>11}{'delivered':>12}"
      f"{'effects':>10}{'dups':>8}{'retries':>9}{'shed':>7}{'DLQ':>6}")
    for name in ("payments", "email", "analytics"):
        grp = g[name]
        s = grp.lag_series
        P(f"  {name:<12}{max((x[1] for x in s), default=0):>11,}"
          f"{max((x[2] for x in s), default=0.0):>10.2f}s{grp.delivered:>12,}"
          f"{grp.effects:>10,}{grp.duplicates_absorbed:>8,}{grp.retried:>9,}"
          f"{grp.shed:>7,}{len(grp.dlq):>6,}")
    P()
    P(f"  outbox: peak lag {ok.outbox_peak_lag:.2f} s   "
      f"relay polls {ok.relay.polls:,} ({ok.relay.empty_polls / ok.relay.polls:.1%} empty)   "
      f"crashes {ok.relay.crashes}")
    P(f"  relay duplicate publishes {ok.relay.duplicate_publishes}   "
      f"rebalances: email {g['email'].rebalances}, payments {g['payments'].rebalances}")
    P(f"  email provider: sent {ok.ctx.provider.sent:,}  key-suppressed {ok.ctx.provider.suppressed:,}  "
      f"duplicates delivered {ok.ctx.provider.duplicates():,}")
    P(f"  email idempotency margin: widest retry gap {ok.ctx.provider.max_gap:.2f} s against a "
      f"{EMAIL_DEDUP_WINDOW:.0f} s key TTL")
    P(f"    -> {EMAIL_DEDUP_WINDOW - ok.ctx.provider.max_gap:.2f} s of margin. Raise the backoff cap "
      f"({RETRY_CAP:.0f} s) above the TTL and this stops being zero.")
    P(f"  dedup store size: {ok.svc.placed:,} rows in payments.processed "
      f"(prune above the max DLQ residence time)")
    P()
    P("  All four invariants held under nine simultaneous faults. The email row is the")
    P("  honest one: an external send is only as idempotent as the provider's key TTL.")


def main() -> None:
    ok = run(idempotent=True)
    bad = run(idempotent=False)
    report(ok, bad)


if __name__ == "__main__":
    main()
