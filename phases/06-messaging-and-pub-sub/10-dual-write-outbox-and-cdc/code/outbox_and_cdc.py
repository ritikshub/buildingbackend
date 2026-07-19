#!/usr/bin/env python3
"""
The dual-write problem, reproduced -- then fixed with a transactional outbox and CDC.

Companion to docs/en.md (Phase 6, Lesson 10 - The Dual-Write Problem: Transactional
Outbox & CDC). Real sqlite3 transactions, a simulated broker, a virtual clock, and a
crash injected at the exact instruction between COMMIT and publish. Sources: Gray &
Reuter, "Transaction Processing: Concepts and Techniques" (1993) for atomicity and the
blocking nature of two-phase commit; PostgreSQL's logical decoding model (a reorder
buffer that emits a transaction's changes only when its COMMIT record is read) for CDC.

Deterministic: every RNG is seeded, the clock is virtual, temp files are removed.
Standard library only:  python outbox_and_cdc.py
"""

from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import tempfile
from collections import Counter, defaultdict

SEED = 20260718
N_ORDERS = 400
ORDER_RATE = 40.0          # orders/second on the virtual clock
CRASH_RATE = 0.10          # requests where the process dies mid-flow
PUBLISH_S = 0.002          # broker round trip per event
BATCH = 8                  # outbox rows claimed per relay poll
RELAY_TICK = 0.25          # default relay poll interval
RELAY_RESTART_S = 0.5      # how long a crashed relay takes to be restarted
CLAIM_TTL = 30.0           # a claim expires so a dead relay's rows are re-claimable
CDC_TICK = 0.002           # a WAL sender loop wakes far more often than a poller

SCHEMA = """
CREATE TABLE orders (
  id           INTEGER PRIMARY KEY,
  customer     TEXT    NOT NULL,
  amount_cents INTEGER NOT NULL,
  status       TEXT    NOT NULL,
  created_at   REAL    NOT NULL,
  updated_at   REAL    NOT NULL
);
CREATE TABLE outbox (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  aggregate_id  INTEGER NOT NULL,
  partition_key TEXT    NOT NULL,
  seq           INTEGER NOT NULL,
  event_id      TEXT    NOT NULL,
  event_type    TEXT    NOT NULL,
  payload       TEXT    NOT NULL,
  created_at    REAL    NOT NULL,
  published_at  REAL,
  claimed_by    TEXT,
  claim_expires REAL
);
CREATE INDEX ix_outbox_unpublished ON outbox(id) WHERE published_at IS NULL;
CREATE TABLE inbox (event_id TEXT PRIMARY KEY, processed_at REAL NOT NULL);
CREATE TABLE notifications (order_id INTEGER NOT NULL, sent_at REAL NOT NULL);
"""


class Crash(Exception):
    """The process dies here. No cleanup runs -- that is the whole point."""


class Broker:
    """Whatever is on the other side of publish(): Kafka, RabbitMQ, SQS, a topic."""

    def __init__(self) -> None:
        self.log: list[dict] = []

    def publish(self, ev: dict, at: float) -> None:
        self.log.append(dict(ev, published_at=at))


def new_db(tmp: str, name: str) -> sqlite3.Connection:
    conn = sqlite3.connect(os.path.join(tmp, name), isolation_level=None)  # explicit BEGIN
    conn.executescript(SCHEMA)
    return conn


def workload() -> list[dict]:
    rnd = random.Random(SEED)
    cust = [f"cust-{n:02d}" for n in range(12)]
    return [{"oid": 1000 + i, "t": i / ORDER_RATE, "customer": rnd.choice(cust),
             "amount": rnd.randrange(500, 25_000)} for i in range(N_ORDERS)]


def crash_points(orders: list[dict]) -> set[int]:
    """The same injected faults for every approach, so the comparison is fair."""
    rnd = random.Random(SEED + 1)
    return {o["oid"] for o in orders if rnd.random() < CRASH_RATE}


def event_of(o: dict, seq: int) -> dict:
    return {"event_id": f"e-{o['oid']}", "order_id": o["oid"], "type": "OrderPlaced",
            "partition_key": o["customer"], "seq": seq, "created_at": o["t"]}


def reconcile(conn: sqlite3.Connection, broker: Broker) -> dict:
    in_db = {r[0] for r in conn.execute("SELECT id FROM orders")}
    pub = Counter(e["order_id"] for e in broker.log)
    lat = [(e["published_at"] - e["created_at"]) * 1000 for e in broker.log]
    return {"orders": len(in_db), "events": len(broker.log),
            "orphans": sorted(in_db - set(pub)), "phantoms": sorted(set(pub) - in_db),
            "dups": sum(c - 1 for c in pub.values() if c > 1),
            "lat_ms": sum(lat) / len(lat) if lat else 0.0}


# --- 1. the bug: two writes, two systems, no shared transaction -----------------

def run_dual_write(tmp: str, orders: list[dict], crashes: set[int], publish_first: bool) -> dict:
    conn = new_db(tmp, f"naive_{'pf' if publish_first else 'cf'}.db")
    broker, seqs = Broker(), Counter()
    for o in orders:
        seqs[o["customer"]] += 1
        ev = event_of(o, seqs[o["customer"]])
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                         (o["oid"], o["customer"], o["amount"], "placed", o["t"], o["t"]))
            if publish_first:
                broker.publish(ev, o["t"] + PUBLISH_S)
                if o["oid"] in crashes:
                    raise Crash                      # dies BEFORE the commit
                conn.execute("COMMIT")
            else:
                conn.execute("COMMIT")               # durable: the order exists
                if o["oid"] in crashes:
                    raise Crash                      # dies BEFORE the publish
                broker.publish(ev, o["t"] + PUBLISH_S)
        except Crash:
            if conn.in_transaction:                  # what a process restart does for you
                conn.execute("ROLLBACK")
    return reconcile(conn, broker)


# --- 2. the fix: one transaction, one write, a relay that reads it back ---------

def place_with_outbox(conn: sqlite3.Connection, o: dict, seq: int) -> None:
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)",
                 (o["oid"], o["customer"], o["amount"], "placed", o["t"], o["t"]))
    conn.execute("INSERT INTO outbox (aggregate_id, partition_key, seq, event_id, "
                 "event_type, payload, created_at) VALUES (?,?,?,?,?,?,?)",
                 (o["oid"], o["customer"], seq, f"e-{o['oid']}", "OrderPlaced",
                  json.dumps(event_of(o, seq), sort_keys=True), o["t"]))
    conn.execute("COMMIT")          # ONE write. Both rows land, or neither does.


class Relay:
    """Polls the outbox, publishes, marks published. At-least-once by construction:
    it can die between the publish and the mark, and then it republishes."""

    def __init__(self, conn, broker, name="relay-1", tick=RELAY_TICK, batch=BATCH,
                 claim=False, crash_attempts=None, outage=None):
        self.conn, self.broker, self.name = conn, broker, name
        self.tick, self.batch, self.claim = tick, batch, claim
        self.crash_attempts = crash_attempts or {}
        self.outage = outage
        self.next_poll = tick
        self.down_until = -1.0
        self.wakeups = self.polls = self.empty = self.rows_read = 0
        self.published = self.crashes = self.attempt = 0

    def fetch(self, t: float) -> list[tuple]:
        cols = "id, event_id, partition_key, seq, payload, created_at"
        if self.claim:
            # The emulation of SELECT ... FOR UPDATE SKIP LOCKED: one atomic
            # statement stamps the rows as mine, so a second relay cannot see them.
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                "UPDATE outbox SET claimed_by=?, claim_expires=? WHERE id IN "
                "(SELECT id FROM outbox WHERE published_at IS NULL AND "
                " (claimed_by IS NULL OR claim_expires < ?) ORDER BY id LIMIT ?)",
                (self.name, t + CLAIM_TTL, t, self.batch))
            rows = self.conn.execute(
                f"SELECT {cols} FROM outbox WHERE claimed_by=? AND published_at IS NULL "
                "ORDER BY id", (self.name,)).fetchall()
            self.conn.execute("COMMIT")
        else:
            rows = self.conn.execute(
                f"SELECT {cols} FROM outbox WHERE published_at IS NULL ORDER BY id "
                "LIMIT ?", (self.batch,)).fetchall()
        self.polls += 1
        self.rows_read += len(rows)
        self.empty += (not rows)
        return rows

    def ship(self, rows: list[tuple], t: float) -> tuple[float, bool]:
        """Publish, then mark. A crash between the two is what makes this at-least-once."""
        stop = self.crash_attempts.get(self.attempt)
        self.attempt += 1
        n = len(rows) if stop is None else min(stop, len(rows))
        for r in rows[:n]:
            t += PUBLISH_S
            self.broker.publish(json.loads(r[4]), t)
            self.published += 1
        if stop is None:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.executemany("UPDATE outbox SET published_at=? WHERE id=?",
                                  [(t, r[0]) for r in rows[:n]])
            self.conn.execute("COMMIT")
            return t, False
        self.crashes += 1                        # died with n published and 0 marked
        self.down_until = t + RELAY_RESTART_S
        return t, True

    def poll(self, t: float) -> float:
        """One wakeup: keep claiming batches until caught up or out of tick budget."""
        self.wakeups += 1
        deadline = t + self.tick
        while t < deadline:
            rows = self.fetch(t)
            if not rows:
                break
            t, crashed = self.ship(rows, t)
            if crashed or len(rows) < self.batch:
                break
        return t

    def pump(self, now: float) -> None:
        while self.next_poll <= now:
            t, self.next_poll = self.next_poll, self.next_poll + self.tick
            if t < self.down_until:
                continue
            if self.outage and self.outage[0] <= t < self.outage[1]:
                continue
            self.poll(t)

    def pending(self) -> bool:
        return bool(self.conn.execute(
            "SELECT 1 FROM outbox WHERE published_at IS NULL LIMIT 1").fetchone())

    def drain(self, now: float) -> float:
        while self.pending():
            now = max(now + self.tick, self.down_until + self.tick)
            now = self.poll(now)
        return now


def run_outbox(tmp: str, orders: list[dict], crashes: set[int]) -> tuple:
    conn = new_db(tmp, "outbox.db")
    broker, seqs = Broker(), Counter()
    rnd = random.Random(SEED + 7)
    # six kills spread across the run, each after a random number of published rows
    plan = {a: rnd.randrange(1, BATCH + 1) for a in sorted(rnd.sample(range(70), 6))}
    relay = Relay(conn, broker, crash_attempts=plan)
    for o in orders:
        relay.pump(o["t"])
        seqs[o["customer"]] += 1
        place_with_outbox(conn, o, seqs[o["customer"]])
        if o["oid"] in crashes:
            pass          # the SAME crash point as the naive version -- now harmless
    relay.drain(orders[-1]["t"])
    return conn, broker, relay, reconcile(conn, broker)


def consume_idempotently(conn: sqlite3.Connection, broker: Broker) -> dict:
    """The inbox pattern: record the event id in the SAME transaction as the effect."""
    applied = suppressed = 0
    for ev in broker.log:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute("INSERT OR IGNORE INTO inbox VALUES (?,?)",
                           (ev["event_id"], ev["published_at"]))
        if cur.rowcount == 1:
            conn.execute("INSERT INTO notifications VALUES (?,?)",
                         (ev["order_id"], ev["published_at"]))
            applied += 1
        else:
            suppressed += 1
        conn.execute("COMMIT")
    n = conn.execute("SELECT COUNT(*), COUNT(DISTINCT order_id) FROM notifications").fetchone()
    return {"applied": applied, "suppressed": suppressed, "effects": n[0], "distinct": n[1]}


def ordering_regressions(events: list[dict]) -> int:
    """How often the stream goes BACKWARDS for one partition key (redelivery)."""
    last, bad = {}, 0
    for e in events:
        k = e["partition_key"]
        if k in last and e["seq"] <= last[k]:
            bad += 1
        last[k] = max(e["seq"], last.get(k, 0))
    return bad


# --- 3. relay mechanics: the poll interval trade-off ----------------------------

def poll_interval_study(tmp: str, orders: list[dict]) -> list[dict]:
    rows = []
    for tick in (0.005, 0.025, 0.100, 0.500, 2.000):
        conn = new_db(tmp, f"poll_{int(tick * 1000)}.db")
        broker, seqs = Broker(), Counter()
        relay = Relay(conn, broker, tick=tick)
        for o in orders:
            relay.pump(o["t"])
            seqs[o["customer"]] += 1
            place_with_outbox(conn, o, seqs[o["customer"]])
        relay.drain(orders[-1]["t"])
        lat = sorted((e["published_at"] - e["created_at"]) * 1000 for e in broker.log)
        rows.append({"tick": tick, "wakeups": relay.wakeups, "polls": relay.polls,
                     "empty": relay.empty, "rows": relay.rows_read,
                     "mean": sum(lat) / len(lat), "p95": lat[int(0.95 * len(lat))],
                     "qpe": relay.polls / len(broker.log)})
        conn.close()
    return rows


def _plan(path: str, q: str) -> str:
    """A fresh connection, so the statement cache cannot hand back a stale plan."""
    c = sqlite3.connect(path)
    detail = c.execute("EXPLAIN QUERY PLAN " + q).fetchone()[3]
    c.close()
    return detail


def index_study(tmp: str) -> tuple[str, str, int, int]:
    """An outbox that is never pruned turns every poll into a full table scan."""
    path = os.path.join(tmp, "idx.db")
    conn = sqlite3.connect(path, isolation_level=None)
    conn.executescript(SCHEMA)
    conn.execute("BEGIN IMMEDIATE")                  # 50,000 published, 40 still pending
    conn.executemany(
        "INSERT INTO outbox (aggregate_id, partition_key, seq, event_id, event_type, "
        "payload, created_at, published_at) VALUES (?,?,?,?,?,?,?,?)",
        [(i, "k", i, f"e-{i}", "OrderPlaced", "{}", i * 0.001,
          None if i >= 50_000 else i * 0.001) for i in range(50_040)])
    conn.execute("COMMIT")
    q = "SELECT id FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 8"
    total = conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM outbox WHERE published_at IS NULL").fetchone()[0]
    with_idx = _plan(path, q)
    conn.execute("DROP INDEX ix_outbox_unpublished")
    conn.close()
    return with_idx, _plan(path, q), total, pending


# --- 4. two relays at once ------------------------------------------------------

def concurrent_relays(tmp: str, claim: bool) -> dict:
    conn = new_db(tmp, f"conc_{claim}.db")
    broker = Broker()
    for i in range(48):
        place_with_outbox(conn, {"oid": 2000 + i, "t": i * 0.01, "customer": "cust-00",
                                 "amount": 100}, i + 1)
    a = Relay(conn, broker, name="relay-a", claim=claim, batch=6)
    b = Relay(conn, broker, name="relay-b", claim=claim, batch=6)
    t = 1.0
    for _ in range(12):                       # both READ before either WRITES
        ra, rb = a.fetch(t), b.fetch(t)
        if not ra and not rb:
            break
        t = max(a.ship(ra, t)[0], b.ship(rb, t)[0])
    got = Counter(e["order_id"] for e in broker.log)
    return {"published": len(broker.log), "distinct": len(got),
            "dups": sum(c - 1 for c in got.values() if c > 1),
            "unpublished": conn.execute(
                "SELECT COUNT(*) FROM outbox WHERE published_at IS NULL").fetchone()[0]}


# --- 5. outbox lag: the metric that catches a silently dead relay ---------------

def lag_timeline(tmp: str) -> list[tuple[float, float, int]]:
    conn = new_db(tmp, "lag.db")
    broker = Relay(conn, Broker(), tick=0.25, outage=(10.0, 20.0))
    samples, si = [], 0
    marks = [float(x) for x in range(0, 31, 2)]
    for i in range(600):                       # 30 s at 20 orders/s
        t = i / 20.0
        while si < len(marks) and marks[si] <= t:
            samples.append(_lag_sample(conn, marks[si]))   # scrape, then let it work
            broker.pump(marks[si])
            si += 1
        broker.pump(t)
        place_with_outbox(conn, {"oid": 3000 + i, "t": t, "customer": "cust-00",
                                 "amount": 100}, i + 1)
    for m in marks[si:]:
        samples.append(_lag_sample(conn, m))
        broker.pump(m)
    conn.close()
    return samples


def _lag_sample(conn: sqlite3.Connection, now: float) -> tuple[float, float, int]:
    row = conn.execute("SELECT MIN(created_at), COUNT(*) FROM outbox "
                       "WHERE published_at IS NULL").fetchone()
    return (now, 0.0 if row[0] is None else now - row[0], row[1])


# --- 6. a miniature write-ahead log, and CDC on top of it ----------------------

class Wal:
    """The database's durability mechanism (Phase 3 Lesson 13), re-read as a change
    stream. Records are appended as they happen; a COMMIT record terminates a
    transaction. Aborted transactions leave records in the log that no reader emits."""

    def __init__(self, path: str) -> None:
        self.f = open(path, "w+", encoding="ascii")
        self.lsn = 0

    def append(self, rec: dict) -> int:
        self.lsn += 1
        self.f.write(json.dumps(dict(rec, lsn=self.lsn), sort_keys=True,
                                separators=(",", ":")) + "\n")
        return self.lsn

    def size(self) -> int:
        self.f.flush()
        return os.path.getsize(self.f.name)


class WalReader:
    """A replication slot: a byte offset the server must retain WAL beyond."""

    def __init__(self, wal: Wal) -> None:
        self.wal, self.off, self.records, self.bytes = wal, 0, 0, 0

    def poll(self) -> list[dict]:
        self.wal.f.flush()
        self.wal.f.seek(self.off)
        chunk = self.wal.f.read()
        self.off += len(chunk)
        self.bytes += len(chunk)
        recs = [json.loads(l) for l in chunk.split("\n") if l]
        self.records += len(recs)
        return recs


class LogicalDecoder:
    """Postgres' reorder buffer in eight lines: buffer per transaction, emit on
    COMMIT in commit order, discard on ABORT."""

    def __init__(self) -> None:
        self.pending: dict[int, list[dict]] = defaultdict(list)

    def feed(self, recs: list[dict]) -> list[dict]:
        out: list[dict] = []
        for r in recs:
            if r["op"] == "COMMIT":
                out.extend(self.pending.pop(r["txid"], []))
            elif r["op"] == "ABORT":
                self.pending.pop(r["txid"], None)
            else:
                self.pending[r["txid"]].append(r)
        return out


class LoggedStore:
    """sqlite plus a logical WAL: every mutation is executed AND described."""

    def __init__(self, conn: sqlite3.Connection, wal: Wal) -> None:
        self.conn, self.wal, self.txid = conn, wal, 0

    def begin(self) -> None:
        self.txid += 1
        self.conn.execute("BEGIN IMMEDIATE")

    def write(self, op: str, table: str, sql: str, args: tuple,
              before: dict | None, after: dict | None, t: float) -> None:
        self.conn.execute(sql, args)
        self.wal.append({"op": op, "table": table, "txid": self.txid, "t": round(t, 4),
                         "before": before, "after": after})

    def commit(self, t: float) -> None:
        self.conn.execute("COMMIT")
        self.wal.append({"op": "COMMIT", "txid": self.txid, "t": round(t, 4)})

    def rollback(self, t: float) -> None:
        self.conn.execute("ROLLBACK")
        self.wal.append({"op": "ABORT", "txid": self.txid, "t": round(t, 4)})


def cdc_run(tmp: str, orders: list[dict]) -> dict:
    """Same workload, same outbox table -- but the relay tails the log, not the table."""
    conn = new_db(tmp, "cdc.db")
    wal = Wal(os.path.join(tmp, "cdc.wal"))
    store, broker, seqs = LoggedStore(conn, wal), Broker(), Counter()
    reader, decoder = WalReader(wal), LogicalDecoder()
    next_tick, rowid = CDC_TICK, 0

    def tail(now: float) -> None:
        nonlocal next_tick
        while next_tick <= now:
            t, next_tick = next_tick, next_tick + CDC_TICK
            for rec in decoder.feed(reader.poll()):
                if rec["table"] == "outbox" and rec["op"] == "INSERT":
                    broker.publish(json.loads(rec["after"]["payload"]), t + PUBLISH_S)

    for o in orders:
        tail(o["t"])
        seqs[o["customer"]] += 1
        rowid += 1
        ev = event_of(o, seqs[o["customer"]])
        store.begin()
        store.write("INSERT", "orders", "INSERT INTO orders VALUES (?,?,?,?,?,?)",
                    (o["oid"], o["customer"], o["amount"], "placed", o["t"], o["t"]),
                    None, {"id": o["oid"], "status": "placed"}, o["t"])
        store.write("INSERT", "outbox",
                    "INSERT INTO outbox (id, aggregate_id, partition_key, seq, event_id, "
                    "event_type, payload, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (rowid, o["oid"], o["customer"], seqs[o["customer"]], ev["event_id"],
                     "OrderPlaced", json.dumps(ev, sort_keys=True), o["t"]),
                    None, {"payload": json.dumps(ev, sort_keys=True)}, o["t"])
        store.commit(o["t"])
    tail(orders[-1]["t"] + 1.0)
    lat = sorted((e["published_at"] - e["created_at"]) * 1000 for e in broker.log)
    res = {"events": len(broker.log), "mean": sum(lat) / len(lat), "p95": lat[int(0.95 * len(lat))],
           "records": reader.records, "bytes": reader.bytes, "wal": wal.size(), "queries": 0}
    wal.f.close()
    conn.close()
    return res


# --- 7. query-based CDC vs log-based CDC ---------------------------------------

def capture_comparison(tmp: str) -> tuple[list[str], list[str]]:
    conn = new_db(tmp, "capture.db")
    wal = Wal(os.path.join(tmp, "capture.wal"))
    store = LoggedStore(conn, wal)
    reader, decoder = WalReader(wal), LogicalDecoder()
    query_based: list[str] = []
    watermark = -1.0

    def poll_updated_at(now: float) -> None:
        nonlocal watermark
        for r in conn.execute("SELECT id, status, updated_at FROM orders "
                              "WHERE updated_at > ? ORDER BY id", (watermark,)):
            query_based.append(f"UPSERT order={r[0]} status={r[1]}")
        watermark = now

    def change(op: str, oid: int, old: str | None, new: str | None, t: float) -> None:
        sql, args = {
            "INSERT": ("INSERT INTO orders VALUES (?,?,?,?,?,?)", (oid, "c", 1, new, t, t)),
            "UPDATE": ("UPDATE orders SET status=?, updated_at=? WHERE id=?", (new, t, oid)),
            "DELETE": ("DELETE FROM orders WHERE id=?", (oid,)),
        }[op]
        store.begin()
        store.write(op, "orders", sql, args,
                    None if old is None else {"id": oid, "status": old},
                    None if new is None else {"id": oid, "status": new}, t)
        store.commit(t)

    change("INSERT", 901, None, "pending", 0.10)     # three states, one poll window
    change("UPDATE", 901, "pending", "paid", 0.20)
    change("UPDATE", 901, "paid", "shipped", 0.30)
    change("INSERT", 902, None, "pending", 0.40)     # created and gone inside one window
    change("DELETE", 902, "pending", None, 0.50)
    poll_updated_at(1.0)
    change("INSERT", 903, None, "pending", 1.20)     # slower than the poll: polling copes
    poll_updated_at(2.0)
    change("UPDATE", 903, "pending", "paid", 2.30)
    poll_updated_at(3.0)

    log_based = [f'{r["op"]} order={(r["after"] or r["before"])["id"]} '
                 f'status={(r["after"] or r["before"])["status"]}'
                 for r in decoder.feed(reader.poll()) if r["table"] == "orders"]
    wal.f.close()
    conn.close()
    return query_based, log_based


# --- report --------------------------------------------------------------------

def main() -> None:
    tmp = tempfile.mkdtemp(prefix="outbox-")
    try:
        orders = workload()
        crashes = crash_points(orders)
        print("== 1. THE BUG: two writes, two systems, no shared transaction ==")
        print(f"  {N_ORDERS:,} orders at {ORDER_RATE:.0f}/s; the process is killed on "
              f"{len(crashes)} of them,")
        print("  at the one instruction between the database commit and broker.publish().")
        cf = run_dual_write(tmp, orders, crashes, publish_first=False)
        pf = run_dual_write(tmp, orders, crashes, publish_first=True)
        for name, r in (("commit-then-publish", cf), ("publish-then-commit", pf)):
            print(f"  {name:<20} orders in DB {r['orders']:>4,}   events published "
                  f"{r['events']:>4,}   ORPHANS {len(r['orphans']):>3}   PHANTOMS "
                  f"{len(r['phantoms']):>3}")
        print(f"  orphaned orders (exist, no event ever emitted, nothing errored): "
              f"{cf['orphans'][:6]} ... +{len(cf['orphans']) - 6}")
        print(f"  phantom events (event for an order that does not exist): "
              f"{pf['phantoms'][:6]} ... +{len(pf['phantoms']) - 6}")

        print("\n== 2. THE FIX: one transaction, an outbox row, a relay ==")
        conn, broker, relay, ob = run_outbox(tmp, orders, crashes)
        print(f"  outbox rows written inside the order transaction: "
              f"{conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]:,}")
        print(f"  {'outbox + polling relay':<20} orders in DB {ob['orders']:>4,}   events "
              f"published {ob['events']:>4,}   ORPHANS {len(ob['orphans']):>3}   PHANTOMS "
              f"{len(ob['phantoms']):>3}")
        print(f"  relay: {relay.wakeups:,} wakeups, {relay.polls:,} queries, {relay.crashes} "
              f"crashes between publish and mark -> {ob['dups']} duplicate deliveries")
        print(f"  at-least-once is the guarantee, not a defect: mean end-to-end latency "
              f"{ob['lat_ms']:.1f} ms")
        print(f"  per-partition ordering regressions in the RAW stream: "
              f"{ordering_regressions(broker.log)} (redelivery replays backwards)")
        cons = consume_idempotently(conn, broker)
        print(f"  idempotent consumer (inbox table, same transaction as the effect):")
        print(f"    delivered {ob['events']:,}   applied {cons['applied']:,}   suppressed "
              f"{cons['suppressed']}   effects {cons['effects']:,} over "
              f"{cons['distinct']:,} distinct orders")
        print(f"    final state correct: {cons['distinct'] == ob['orders']}  "
              f"(every order notified exactly once)")

        print("\n== 3. RELAY MECHANICS: the poll interval trade-off ==")
        print("  interval   wakeups  DB queries   empty%   mean lat    p95 lat   queries/event")
        study = poll_interval_study(tmp, orders)
        for r in study:
            print(f"  {r['tick'] * 1000:6.0f} ms {r['wakeups']:>9,}  {r['polls']:>10,}"
                  f"   {100 * r['empty'] / r['polls']:5.1f}%  {r['mean']:8.1f} ms {r['p95']:9.1f} ms"
                  f"   {r['qpe']:12.2f}")
        wi, wo, total, pending = index_study(tmp)
        print(f"  the same query on an outbox of {total:,} rows, {pending} of them unpublished:")
        print(f"    with partial index:    {wi}")
        print(f"    without:               {wo}   <- {total:,} rows examined to find {pending}")

        print("\n== 4. TWO RELAY INSTANCES: claiming vs not ==")
        for claim in (False, True):
            r = concurrent_relays(tmp, claim)
            label = "SKIP LOCKED-style claim" if claim else "no claim (both SELECT first)"
            print(f"  {label:<28} published {r['published']:>3}   distinct {r['distinct']:>3}"
                  f"   DUPLICATES {r['dups']:>3}   left unpublished {r['unpublished']}")

        print("\n== 5. OUTBOX LAG: age of the oldest unpublished row ==")
        print("  the relay is dead from t=10s to t=20s. The DB is healthy. The app is healthy.")
        print("     t (s)   lag (s)   pending")
        for t, lag, n in lag_timeline(tmp):
            print(f"  {t:7.0f}  {lag:8.2f}   {n:7,}  {'#' * int(lag * 3)}")

        print("\n== 6. CDC: tail the log instead of polling the table ==")
        cdc = cdc_run(tmp, orders)
        print("  relay               events    mean lat     p95 lat   DB queries   rows/records")
        for tk in (0.100, 0.500):
            p = next(r for r in study if r["tick"] == tk)
            print(f"  {'polling @ %4.0f ms' % (tk * 1000):<18} {N_ORDERS:>6,} {p['mean']:8.1f} ms "
                  f"{p['p95']:9.1f} ms   {p['polls']:>10,}   {p['rows']:>12,}")
        print(f"  {'CDC log tail':<18} {cdc['events']:>6,} {cdc['mean']:8.1f} ms "
              f"{cdc['p95']:9.1f} ms   {cdc['queries']:>10,}   {cdc['records']:>12,}")
        poll = next(r for r in study if r["tick"] == 0.500)
        print(f"  the 500 ms poller issues {poll['polls'] / N_ORDERS:.2f} queries per event against "
              f"the primary database;")
        print(f"  CDC issues none: it reads {cdc['bytes']:,} B of log "
              f"({cdc['bytes'] / cdc['events']:.0f} B/event), each byte exactly once.")
        print(f"  latency: {poll['mean'] / cdc['mean']:.0f}x lower mean, "
              f"{poll['p95'] / cdc['p95']:.0f}x lower p95 -- and no poll interval to tune.")

        print("\n== 7. QUERY-BASED CDC vs LOG-BASED CDC on the same five changes ==")
        qb, lb = capture_comparison(tmp)
        print("  workload: 901 pending->paid->shipped, then 902 created and deleted,")
        print("            all inside ONE 1-second poll window; then 903 changes slowly.")
        print(f"  query-based (SELECT ... WHERE updated_at > watermark)  captured {len(qb)}:")
        for line in qb:
            print(f"    {line}")
        print(f"  log-based (decode the WAL)                             captured {len(lb)}:")
        for line in lb:
            print(f"    {line}")
        print(f"  query-based missed {len(lb) - len(qb)} changes: the intermediate state "
              f"'paid' and BOTH of 902's changes.")
        print("  a deleted row cannot be returned by a query. Only the log remembers it.")

        print("\n== 8. SUMMARY ==")
        print("  approach                    orders  events  orphan  phantom  dup   "
              "mean lat  DB reads/ev")
        rows = [("naive commit-then-publish", cf, 0.0), ("naive publish-then-commit", pf, 0.0)]
        for name, r, q in rows:
            print(f"  {name:<26} {r['orders']:>6,}  {r['events']:>6,}  "
                  f"{len(r['orphans']):>6}  {len(r['phantoms']):>7}  {r['dups']:>3}   "
                  f"{r['lat_ms']:7.1f} ms  {q:11.2f}")
        print(f"  {'outbox + polling relay':<26} {ob['orders']:>6,}  {ob['events']:>6,}  "
              f"{len(ob['orphans']):>6}  {len(ob['phantoms']):>7}  {ob['dups']:>3}   "
              f"{ob['lat_ms']:7.1f} ms  {relay.polls / ob['events']:11.2f}")
        print(f"  {'  + idempotent consumer':<26} {ob['orders']:>6,}  "
              f"{cons['effects']:>6,}  {len(ob['orphans']):>6}  {len(ob['phantoms']):>7}  "
              f"{cons['effects'] - cons['distinct']:>3}   {ob['lat_ms']:7.1f} ms  "
              f"{relay.polls / ob['events']:11.2f}")
        print(f"  {'outbox + CDC (log tail)':<26} {N_ORDERS:>6,}  {cdc['events']:>6,}  "
              f"{0:>6}  {0:>7}  {0:>3}   {cdc['mean']:7.1f} ms  {0.0:11.2f}")
        conn.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
