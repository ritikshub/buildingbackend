#!/usr/bin/env python3
"""
Delivery semantics and idempotent consumers, measured rather than asserted.

Companion to docs/en.md (Phase 6, Lesson 06 - Delivery Semantics & Idempotent
Consumers). The impossibility result behind it is the Two Generals Problem
(Akkoyunlu, Ekanadham & Huber, "Some Constraints and Trade-offs in the Design of
Network Communications", 5th SOSP, 1975; named the Two Generals Paradox by Gray,
"Notes on Data Base Operating Systems", 1978), with the asynchronous-consensus
analogue in Fischer, Lynch & Paterson, "Impossibility of Distributed Consensus
with One Faulty Process", JACM 32(2), 1985.

Everything here runs on a virtual clock with seeded randomness: two runs print
byte-identical output. Standard library only:  python delivery_semantics.py
"""

from __future__ import annotations

import hashlib
import random
import uuid
from dataclasses import dataclass, field

# ─── knobs ───────────────────────────────────────────────────────────────────

SEED = 20260718
TICK_MS = 50
LEASE_MS = 500                  # visibility timeout: how long the broker waits for an ack
MAX_ATTEMPTS = 8                # give up and dead-letter after this many (lesson 08)
HORIZON_MS = 120_000

N_CHARGES = 40
DELIVER_LOSS = 0.12             # forward path:  broker -> consumer
ACK_LOSS = 0.18                 # return path:   consumer -> broker
CONFIRM_LOSS = 0.25             # producer -> broker publish confirms
PUBLISH_ATTEMPTS = 4

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS


def money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def signed(cents: int) -> str:
    return "0" if cents == 0 else f"{'+' if cents > 0 else '-'}{money(abs(cents))}"


# ─── the network: two independent loss probabilities ─────────────────────────

class Channel:
    """A lossy, seeded network.

    The forward path (broker -> consumer) and the return path (consumer ->
    broker) fail *independently*, and that asymmetry is the entire lesson: a
    sender that receives no acknowledgement cannot tell which of the two paths
    ate its packet, and therefore cannot tell whether the work was done.
    """

    def __init__(self, seed: int, deliver_loss: float = DELIVER_LOSS,
                 ack_loss: float = ACK_LOSS) -> None:
        self.rnd = random.Random(seed)
        self.deliver_loss = deliver_loss
        self.ack_loss = ack_loss

    def deliver_ok(self) -> bool:
        return self.rnd.random() >= self.deliver_loss

    def ack_ok(self) -> bool:
        return self.rnd.random() >= self.ack_loss


# ─── the message and the broker (the queue model from lesson 03) ─────────────

@dataclass
class Message:
    message_id: str             # unique per *publish attempt* unless made stable
    dedup_key: str              # the idempotency key the consumer actually uses
    account: str
    amount_cents: int


@dataclass
class Entry:
    """The broker's private bookkeeping for one queued message."""
    msg: Message
    visible_at: int = 0
    attempts: int = 0
    done: bool = False


@dataclass
class DeliveryStats:
    send_attempts: int = 0
    delivered: int = 0          # arrived at the consumer
    deliveries_lost: int = 0    # died on the forward path
    acks_landed: int = 0
    acks_lost: int = 0          # died on the return path -> guaranteed redelivery
    abandoned: int = 0          # hit MAX_ATTEMPTS, would go to a dead-letter queue


class Broker:
    """A queue with leases.

    `redeliver=True`  -> hand the message out, start a lease, and hand it out
                         again if no ack arrives before the lease expires.
                         This is at-least-once.
    `redeliver=False` -> hand the message out and immediately forget it. Nothing
                         is ever retried, so nothing is ever duplicated, and
                         anything the network eats is gone. This is at-most-once.
    """

    def __init__(self, channel: Channel, lease_ms: int = LEASE_MS,
                 redeliver: bool = True) -> None:
        self.channel = channel
        self.lease_ms = lease_ms
        self.redeliver = redeliver
        self.entries: list[Entry] = []
        self.stats = DeliveryStats()

    def publish(self, msg: Message) -> None:
        self.entries.append(Entry(msg))

    def run(self, consumer, horizon_ms: int = HORIZON_MS) -> int:
        now = 0
        while now <= horizon_ms:
            for e in self.entries:
                if e.done or e.visible_at > now:
                    continue
                if e.attempts >= MAX_ATTEMPTS:
                    e.done = True
                    self.stats.abandoned += 1
                    continue

                e.attempts += 1
                self.stats.send_attempts += 1
                if self.redeliver:
                    e.visible_at = now + self.lease_ms   # start the lease
                else:
                    e.done = True                        # auto-ack: forget it now

                if not self.channel.deliver_ok():
                    self.stats.deliveries_lost += 1
                    continue

                self.stats.delivered += 1
                consumer.handle(e.msg, now)

                if not self.redeliver:
                    continue                             # nobody is waiting for an ack

                if self.channel.ack_ok():
                    e.done = True
                    self.stats.acks_landed += 1
                else:
                    self.stats.acks_lost += 1            # the lease will fire again

            if all(e.done for e in self.entries):
                break
            now += TICK_MS
        return now


# ─── the effect: a ledger, and a database that can hold a transaction ────────

class Database:
    """The dedup table and the ledger live in the SAME store.

    That co-location is not an implementation detail — it is the whole reason
    exactly-once *effect* is achievable. One transaction can cover both the
    "I have seen this key" record and the balance change, so they commit
    together or not at all. Move the effect to a third-party HTTP API and this
    property evaporates.
    """

    def __init__(self, ttl_ms: int = 15 * MINUTE_MS) -> None:
        self.balances: dict[str, int] = {}
        self.dedup: dict[str, int] = {}          # key -> recorded_at (virtual ms)
        self.ttl_ms = ttl_ms
        self.expired_total = 0

    # -- housekeeping the store must do or it grows without bound -------------
    def expire(self, now: int) -> int:
        dead = [k for k, t in self.dedup.items() if now - t > self.ttl_ms]
        for k in dead:
            del self.dedup[k]
        self.expired_total += len(dead)
        return len(dead)

    def balance(self, account: str) -> int:
        return self.balances.get(account, 0)

    def total(self) -> int:
        return sum(self.balances.values())

    # -- the effect, unguarded -----------------------------------------------
    def charge(self, account: str, amount: int) -> None:
        self.balances[account] = self.balances.get(account, 0) + amount

    # -- the effect, guarded, atomically --------------------------------------
    def process_once(self, key: str, now: int, account: str, amount: int) -> bool:
        """One transaction:

            BEGIN;
              INSERT INTO processed_messages (key) VALUES (:key);  -- UNIQUE
              UPDATE balances SET cents = cents + :amount WHERE id = :account;
            COMMIT;

        Returns True if the work was done, False if the unique constraint
        rejected the insert — which is precisely "I have already done this".
        There is no window between the check and the act, because there is no
        check: the constraint *is* the check, and the database enforces it.
        """
        self.expire(now)
        if key in self.dedup:                    # <- unique-constraint violation
            return False
        self.dedup[key] = now
        self.charge(account, amount)
        return True


# ─── consumers: three strategies, one workload ───────────────────────────────

@dataclass
class Result:
    strategy: str
    delivered: int = 0
    unique_processed: int = 0
    duplicates: int = 0
    lost: int = 0
    balance: int = 0
    expected: int = 0

    @property
    def correct(self) -> bool:
        return self.balance == self.expected


class AtMostOnceConsumer:
    """Ack first, then work.

    The broker has already forgotten the message by the time the charge runs,
    so anything the forward path eats is gone forever. Never duplicates.
    """
    strategy = "at-most-once"

    def __init__(self, db: Database) -> None:
        self.db = db
        self.processed_ids: list[str] = []

    def handle(self, msg: Message, now: int) -> None:
        self.db.charge(msg.account, msg.amount_cents)
        self.processed_ids.append(msg.dedup_key)


class AtLeastOnceNaiveConsumer:
    """Work first, then ack. Never loses. Duplicates every time an ack dies."""
    strategy = "at-least-once (naive)"

    def __init__(self, db: Database) -> None:
        self.db = db
        self.processed_ids: list[str] = []

    def handle(self, msg: Message, now: int) -> None:
        self.db.charge(msg.account, msg.amount_cents)
        self.processed_ids.append(msg.dedup_key)


class IdempotentConsumer:
    """Work first, then ack — but the work is guarded by an atomic claim.

    Delivery is still at-least-once. Duplicates still arrive. They just stop
    having an effect, which is the only sense in which "exactly-once" is real.
    """
    strategy = "at-least-once + idempotent"

    def __init__(self, db: Database) -> None:
        self.db = db
        self.processed_ids: list[str] = []
        self.suppressed = 0

    def handle(self, msg: Message, now: int) -> None:
        if self.db.process_once(msg.dedup_key, now, msg.account, msg.amount_cents):
            self.processed_ids.append(msg.dedup_key)
        else:
            self.suppressed += 1


# ─── workload ────────────────────────────────────────────────────────────────

def build_charges(n: int = N_CHARGES) -> list[Message]:
    rnd = random.Random(SEED)
    out = []
    for i in range(n):
        order = 1000 + i
        out.append(Message(
            message_id=f"m-{order}",
            dedup_key=f"charge:order-{order}",
            account=f"cust-{rnd.randrange(1, 9):02d}",
            amount_cents=rnd.randrange(5, 400) * 100,
        ))
    return out


def run_strategy(consumer_cls, redeliver: bool, charges: list[Message],
                 db: Database) -> tuple[Result, DeliveryStats, object]:
    broker = Broker(Channel(SEED + 7), redeliver=redeliver)
    for m in charges:
        broker.publish(Message(**m.__dict__))
    consumer = consumer_cls(db)
    broker.run(consumer)

    expected = sum(m.amount_cents for m in charges)
    unique = len(set(consumer.processed_ids))
    res = Result(
        strategy=consumer.strategy,
        delivered=broker.stats.delivered,
        unique_processed=unique,
        duplicates=len(consumer.processed_ids) - unique,
        lost=len(charges) - unique,
        balance=db.total(),
        expected=expected,
    )
    return res, broker.stats, consumer


# ─── section 1: the interleaving, hand-traced ────────────────────────────────

def trace_line(t: int, actor: str, text: str, note: str = "") -> None:
    line = f"    t={t:>4} ms  {actor:<8}  {text}"
    if note:
        line = f"{line:<66}{note}"
    print(line)


def section_interleaving() -> None:
    print("== 1. THE INTERLEAVING: two bugs, and no component malfunctions ==\n")
    amount = 9000

    print("  TRACE A -- ack LAST (at-least-once).  charge:order-1042, 90.00, lease 500 ms")
    trace_line(0, "BROKER", "deliver charge:order-1042 (attempt 1), lease starts")
    trace_line(12, "CONSUMER", "received, begins work")
    trace_line(140, "CONSUMER", f"CHARGED {money(amount)} -> balance {money(amount)}")
    trace_line(141, "CONSUMER", "sends ack")
    trace_line(141, "NETWORK", "*** ack dropped in flight ***", "<- a packet died")
    trace_line(500, "BROKER", "lease expired, no ack seen")
    trace_line(500, "BROKER", "redeliver charge:order-1042 (attempt 2)", "<- correct behaviour")
    trace_line(512, "CONSUMER", "received, begins work")
    trace_line(640, "CONSUMER", f"CHARGED {money(amount)} -> balance {money(2 * amount)}",
               "<- CHARGED TWICE")
    trace_line(641, "CONSUMER", "sends ack")
    trace_line(655, "BROKER", "ack received, message deleted")
    print(f"    result: customer paid {money(2 * amount)} for a {money(amount)} order.")
    print("    Every log line above reads 'success'. The broker followed its contract,")
    print("    the consumer followed its contract, and the customer was charged twice.\n")

    print("  TRACE B -- ack FIRST (at-most-once). The mirror image, same order.")
    trace_line(0, "BROKER", "deliver charge:order-1042 (attempt 1)")
    trace_line(12, "CONSUMER", "received")
    trace_line(13, "CONSUMER", "sends ack BEFORE doing the work")
    trace_line(26, "BROKER", "ack received, message deleted", "<- no copy remains")
    trace_line(30, "CONSUMER", "process crashes (OOM kill, deploy, node reboot)")
    trace_line(30, "CONSUMER", f"CHARGE {money(amount)} never runs")
    trace_line(500, "BROKER", "nothing to redeliver: the queue is empty")
    print(f"    result: customer paid {money(0)} for a {money(amount)} order.")
    print("    Silent. No error, no alert, no dead letter. The money simply never moved.\n")

    print("  The ack is the only lever, and it has two positions:")
    print("    ack BEFORE the work  ->  you may LOSE the effect,      never duplicate it")
    print("    ack AFTER  the work  ->  you may DUPLICATE the effect,  never lose it")
    print("  There is no third position. Choosing where to ack is choosing which bug")
    print("  you get, not whether you get one.")


# ─── section 2: the same workload, three strategies ──────────────────────────

def section_three_strategies(charges: list[Message]) -> list[Result]:
    print("\n\n== 2. THE SAME WORKLOAD, THREE STRATEGIES ==\n")
    expected = sum(m.amount_cents for m in charges)
    print(f"  {len(charges)} card charges, one account per customer, {len(set(c.account for c in charges))} customers")
    print(f"  channel: {DELIVER_LOSS:.0%} of deliveries lost, {ACK_LOSS:.0%} of acks lost, "
          f"lease {LEASE_MS} ms, max {MAX_ATTEMPTS} attempts")
    print(f"  expected final balance across all accounts: {money(expected)}\n")

    rows: list[Result] = []
    stats_by: dict[str, DeliveryStats] = {}

    r1, s1, _ = run_strategy(AtMostOnceConsumer, False, charges, Database())
    r2, s2, _ = run_strategy(AtLeastOnceNaiveConsumer, True, charges, Database())
    r3, s3, c3 = run_strategy(IdempotentConsumer, True, charges, Database())
    for r, s in ((r1, s1), (r2, s2), (r3, s3)):
        rows.append(r)
        stats_by[r.strategy] = s

    hdr = (f"  {'strategy':<28}{'sent':>6}{'deliv':>7}{'ack lost':>10}"
           f"{'unique':>8}{'dup':>6}{'lost':>6}")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for r in rows:
        s = stats_by[r.strategy]
        print(f"  {r.strategy:<28}{s.send_attempts:>6}{s.delivered:>7}{s.acks_lost:>10}"
              f"{r.unique_processed:>8}{r.duplicates:>6}{r.lost:>6}")

    print()
    hdr2 = f"  {'strategy':<28}{'final balance':>15}{'expected':>13}{'error':>13}   verdict"
    print(hdr2)
    print("  " + "-" * (len(hdr2) - 2))
    for r in rows:
        delta = r.balance - r.expected
        verdict = "CORRECT" if r.correct else ("OVERCHARGED" if delta > 0 else "UNDERCHARGED")
        print(f"  {r.strategy:<28}{money(r.balance):>15}{money(r.expected):>13}"
              f"{signed(delta):>13}   {verdict}")

    print()
    print(f"  at-most-once   lost {r1.lost} charges worth {money(r1.expected - r1.balance)} "
          f"— money that was owed and never moved.")
    print(f"  at-least-once  double-charged {r2.duplicates} times, {money(r2.balance - r2.expected)} "
          f"of other people's money.")
    print(f"  idempotent     saw the SAME {r3.delivered} deliveries as the naive run "
          f"({'identical' if r2.delivered == r3.delivered else 'DIFFERENT'}),")
    print(f"                 suppressed {c3.suppressed} duplicates, and landed exactly on "
          f"{money(r3.balance)}.")
    print("  Nothing about the delivery layer changed. The consumer changed.")
    return rows


# ─── section 3: the atomicity trap ───────────────────────────────────────────

def section_atomicity_trap() -> None:
    print("\n\n== 3. THE ATOMICITY TRAP: check-then-act is itself a race ==\n")
    amount = 9000
    key = "charge:order-1042"
    print("  Two consumer instances get the same message: instance A is still working")
    print("  when its lease expires, so the broker hands the message to instance B.")
    print("  This is normal, expected, and happens every day at scale.\n")

    # --- the broken version: SELECT, then UPDATE, then INSERT ---------------
    db = Database()
    print("  (a) CHECK-THEN-ACT   SELECT 1 FROM processed; if absent: UPDATE; INSERT")
    steps = [
        ("A", "SELECT 1 FROM processed WHERE key=... -> 0 rows"),
        ("B", "SELECT 1 FROM processed WHERE key=... -> 0 rows   <- both passed the check"),
        ("A", "UPDATE balances SET cents = cents + 9000"),
        ("B", "UPDATE balances SET cents = cents + 9000          <- SECOND CHARGE"),
        ("A", "INSERT INTO processed (key)"),
        ("B", "INSERT INTO processed (key)  (already there)"),
    ]
    a_saw = b_saw = None
    for who, text in steps:
        if text.startswith("SELECT"):
            seen = key in db.dedup
            if who == "A":
                a_saw = seen
            else:
                b_saw = seen
        elif text.startswith("UPDATE"):
            gate = a_saw if who == "A" else b_saw
            if gate is False:
                db.charge("cust-01", amount)
        elif text.startswith("INSERT"):
            db.dedup.setdefault(key, 0)
        print(f"      {who}: {text}")
    broken_balance = db.total()
    print(f"      -> balance {money(broken_balance)}   expected {money(amount)}   "
          f"{'DOUBLE CHARGE' if broken_balance != amount else 'ok'}")
    print("      The dedup store was consulted correctly and still failed, because the")
    print("      gap between the SELECT and the INSERT is a window another worker fits in.\n")

    # --- the correct version: one transaction, unique constraint ------------
    db2 = Database()
    print("  (b) TRANSACTIONAL    BEGIN; INSERT INTO processed (key); UPDATE balances; COMMIT")
    a_ok = db2.process_once(key, 0, "cust-01", amount)
    print(f"      A: BEGIN; INSERT key -> ok; UPDATE +9000; COMMIT      -> applied={a_ok}")
    b_ok = db2.process_once(key, 0, "cust-01", amount)
    print(f"      B: BEGIN; INSERT key -> UNIQUE VIOLATION; ROLLBACK    -> applied={b_ok}")
    fixed_balance = db2.total()
    print(f"      -> balance {money(fixed_balance)}   expected {money(amount)}   "
          f"{'CORRECT' if fixed_balance == amount else 'WRONG'}")
    print("      No check. The unique constraint IS the check, and the database — the one")
    print("      component that can actually serialise two writers — enforces it.\n")
    print(f"  same interleaving, same dedup store, two code shapes: "
          f"{money(broken_balance)} vs {money(fixed_balance)}")


# ─── section 4: the dedup window ─────────────────────────────────────────────

def section_dedup_window() -> list[Result]:
    print("\n\n== 4. THE DEDUP WINDOW: a TTL is a correctness boundary ==\n")
    batch = [Message(f"m-2{i}", f"charge:order-20{i}", f"cust-{i:02d}", (i + 1) * 2500)
             for i in range(5)]
    expected = sum(m.amount_cents for m in batch)
    redrive_at = 6 * HOUR_MS
    print(f"  {len(batch)} charges processed at t=0, then redriven from a dead-letter queue")
    print(f"  at t=+{redrive_at // HOUR_MS}h after an on-call engineer fixed the downstream bug (lesson 08).")
    print(f"  expected balance: {money(expected)}\n")

    rows: list[Result] = []
    hdr = (f"  {'dedup TTL':<14}{'alive at redrive':>18}{'reprocessed':>13}"
           f"{'balance':>12}{'expected':>11}   verdict")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for label, ttl in (("15 minutes", 15 * MINUTE_MS), ("24 hours", 24 * HOUR_MS)):
        db = Database(ttl_ms=ttl)
        con = IdempotentConsumer(db)
        for m in batch:
            con.handle(m, 0)
        db.expire(redrive_at)
        alive = sum(1 for k in db.dedup)
        before = len(con.processed_ids)
        for m in batch:                                   # the DLQ redrive
            con.handle(m, redrive_at)
        reprocessed = len(con.processed_ids) - before
        ok = db.total() == expected
        print(f"  {label:<14}{f'{alive} of {len(batch)}':>18}{reprocessed:>13}"
              f"{money(db.total()):>12}{money(expected):>11}   "
              f"{'CORRECT' if ok else 'DOUBLE CHARGED'}")
        rows.append(Result(strategy=f"idempotent, TTL {label}", delivered=2 * len(batch),
                           unique_processed=len(batch), duplicates=reprocessed,
                           lost=0, balance=db.total(), expected=expected))
    print()
    print("  The idempotency is real; the memory of it is not permanent. A dedup store")
    print("  with a TTL is only correct while redeliveries arrive inside the window, so")
    print("  the window must exceed your worst realistic redelivery delay — and a manual")
    print("  DLQ redrive hours later is exactly that worst case.")
    return rows


# ─── section 5: producer-side duplicates ─────────────────────────────────────

def stable_event_id(order: int) -> str:
    """Derived from the business event, so every publish attempt agrees on it."""
    return "evt-" + hashlib.sha256(f"charge:order-{order}".encode()).hexdigest()[:16]


def confirm_outcomes(n_events: int) -> list[list[bool]]:
    """Per event, the fate of each publish confirm: True = the confirm was lost.

    Precomputed from the seeded RNG so every id strategy below faces exactly the
    same network, and so the producer-restart point can be chosen deterministically.
    """
    rnd = random.Random(SEED + 31)
    out = []
    for _ in range(n_events):
        seq: list[bool] = []
        for _ in range(PUBLISH_ATTEMPTS):
            lost = rnd.random() < CONFIRM_LOSS
            seq.append(lost)
            if not lost:
                break
        out.append(seq)
    return out


def publish_with_retries(outcomes: list[list[bool]], id_mode: str,
                         restart_at: tuple[int, int] | None = None):
    """Publish each event, retrying whenever the publish confirm is lost.

    The broker STORED every attempt — the confirm is what went missing, so the
    producer is retrying a publish that already succeeded. Each wire record is
    (message_id, dedup_key, producer_id, seq, amount, order).

    `restart_at=(event, attempt)` crashes and restarts the producer process just
    before that attempt: it comes back with a new producer id and a sequence
    number that starts from scratch.
    """
    rnd = random.Random(SEED + 77)
    wire = []
    pid, seq_counter = "pid-A", 0
    for i, fates in enumerate(outcomes):
        order, amount = 3000 + i, (i + 1) * 1000
        seq_counter += 1
        seq = seq_counter
        for a, lost in enumerate(fates):
            if restart_at == (i, a):
                pid, seq_counter = "pid-B", 1     # new session: the sequence resets
                seq = 1
            if id_mode == "uuid":
                mid = key = str(uuid.UUID(int=rnd.getrandbits(128), version=4))
            else:
                mid = key = stable_event_id(order)
            wire.append((mid, key, pid, seq, amount, order))
            if not lost:
                break
    return wire


def section_producer_duplicates() -> list[Result]:
    print("\n\n== 5. PRODUCER-SIDE DUPLICATES: the copy the consumer never sees coming ==\n")
    n_events = 12
    expected = sum((i + 1) * 1000 for i in range(n_events))
    outcomes = confirm_outcomes(n_events)
    retried = sum(len(f) - 1 for f in outcomes)
    # restart the producer between the lost confirm and the retry of the first
    # event that needed one — the interleaving that defeats sequence dedup.
    first_retry = next(i for i, f in enumerate(outcomes) if len(f) > 1)
    restart_at = (first_retry, 1)

    print(f"  {n_events} business events, {CONFIRM_LOSS:.0%} of publish confirms lost.")
    print("  The broker STORED every publish; only the confirm went missing. The producer")
    print(f"  therefore retries {retried} publishes that had already succeeded. Those duplicates")
    print("  now exist on the broker BEFORE any consumer is involved.")
    print(f"  expected balance: {money(expected)}\n")

    rows: list[Result] = []
    hdr = (f"  {'producer id strategy':<34}{'on wire':>9}{'charged':>9}{'dup':>6}"
           f"{'balance':>12}{'expected':>11}   verdict")
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))

    def consume(wire, broker_seq_dedup: bool):
        db = Database(ttl_ms=24 * HOUR_MS)
        con = IdempotentConsumer(db)
        seen: set[tuple[str, int]] = set()
        on_broker = 0
        for mid, key, pid, seq, amount, order in wire:
            if broker_seq_dedup:
                if (pid, seq) in seen:              # the broker drops the retry
                    continue
                seen.add((pid, seq))
            on_broker += 1
            con.handle(Message(mid, key, f"cust-{order % 8:02d}", amount), 0)
        return db, con, on_broker

    def row(label: str, short: str, wire, broker_seq_dedup: bool) -> Result:
        db, con, on_broker = consume(wire, broker_seq_dedup)
        charged = len(con.processed_ids)
        r = Result(short, on_broker, min(charged, n_events),
                   charged - n_events, 0, db.total(), expected)
        print(f"  {label:<34}{on_broker:>9}{charged:>9}{charged - n_events:>6}"
              f"{money(db.total()):>12}{money(expected):>11}   "
              f"{'CORRECT' if r.correct else 'OVERCHARGED'}")
        return r

    rows.append(row("fresh UUID per publish attempt", "producer: fresh UUID per attempt",
                    publish_with_retries(outcomes, "uuid"), False))
    rows.append(row("broker (producer_id, seq) dedup", "producer: broker (pid, seq) dedup",
                    publish_with_retries(outcomes, "uuid", restart_at), True))
    rows.append(row("stable business-derived id", "producer: stable business id",
                    publish_with_retries(outcomes, "stable"), False))

    over_a = rows[0].balance - expected
    dup_b = rows[1].duplicates
    print()
    print("  A fresh UUID per attempt is not an idempotency key — it is a *transmission*")
    print("  id. It changes on the retry, so every downstream dedup mechanism sees two")
    print(f"  unrelated messages and honours both: {money(rows[0].balance)} charged against "
          f"{money(expected)} owed, {signed(over_a)}.")
    print("  Broker sequence dedup catches retries inside one producer session: it removed")
    print(f"  {retried - dup_b} of the {retried} duplicates. The restart during event {restart_at[0]}'s retry issued a new")
    print(f"  producer id and reset the sequence, so {dup_b} walked straight through. That is")
    print("  Kafka's `enable.idempotence`, and that is its honest scope.")
    print("  Only an id derived from the business event survives retries, restarts and")
    print("  redeploys — because it was never generated at publish time at all.")
    return rows


# ─── section 6: the summary ──────────────────────────────────────────────────

def section_summary(all_rows: list[Result]) -> None:
    print("\n\n== 6. SUMMARY: every strategy, one table ==\n")
    hdr = (f"  {'strategy':<38}{'deliv':>7}{'unique':>8}{'dup':>6}{'lost':>6}"
           f"{'balance':>12}{'expected':>11}")
    print(hdr)
    print("  " + "=" * (len(hdr) - 2))
    for r in all_rows:
        flag = "" if r.correct else "   <-- WRONG"
        print(f"  {r.strategy:<38}{r.delivered:>7}{r.unique_processed:>8}{r.duplicates:>6}"
              f"{r.lost:>6}{money(r.balance):>12}{money(r.expected):>11}{flag}")
    n_ok = sum(1 for r in all_rows if r.correct)
    print()
    print(f"  {n_ok} of {len(all_rows)} configurations produced the correct final balance.")
    print("  Every one of them delivered duplicates. Correctness never came from the")
    print("  delivery layer — it came from making the duplicate harmless.")


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    charges = build_charges()
    section_interleaving()
    rows = section_three_strategies(charges)
    section_atomicity_trap()
    rows += section_dedup_window()
    rows += section_producer_duplicates()
    section_summary(rows)


if __name__ == "__main__":
    main()
