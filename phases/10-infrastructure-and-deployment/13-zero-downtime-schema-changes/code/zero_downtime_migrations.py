#!/usr/bin/env python3
"""Zero-downtime schema & contract changes — the DEPLOYMENT view of a migration.

Lesson: phases/10-infrastructure-and-deployment/13-zero-downtime-schema-changes/docs/en.md
Sources: PostgreSQL 16 manual, ch. 13.3 "Explicit Locking" (the lock conflict matrix
and the fact that a waiting lock request blocks later ones) and the ALTER TABLE
reference; SQLite 3.35+ ALTER TABLE ... DROP COLUMN.
SQLite is a deterministic stand-in engine. Section 4 MODELS PostgreSQL's lock-queue
semantics explicitly — SQLite's locking model is different, and the prose says so.
Deterministic (random.Random(7)), self-terminating, ~25 s.
"""

from __future__ import annotations

import heapq
import os
import random
import sqlite3
import statistics
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

SEED = 7
BAR = "=" * 78


# --------------------------------------------------------------------------- #
# The fleet: four code versions, one database.                                  #
#                                                                               #
# Every version does the same three things — create an order, read one back,    #
# and copy one into a nightly export table. They differ only in WHICH address   #
# column they write and WHICH key they pull out of the row they read.           #
# Reads go through `SELECT *` then a dict lookup, exactly like every ORM: that  #
# is why a missing column produces None instead of an exception.                #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Version:
    name: str
    writes: Tuple[str, ...]   # address column(s) this version writes
    reads: str                # the key it pulls out of the row dict
    note: str


V1 = Version("v1", ("ship_to",), "ship_to", "old code: ship_to only")
V1D = Version("v1d", ("ship_to", "shipping_address"), "ship_to",
              "dual-write, reads OLD")
V2R = Version("v2r", ("ship_to", "shipping_address"), "shipping_address",
              "dual-write, reads NEW")
V2 = Version("v2", ("shipping_address",), "shipping_address",
             "new code: shipping_address only")


def create_order(conn: sqlite3.Connection, v: Version, oid: int,
                 customer: str, addr: str) -> None:
    cols = ("id", "customer", "total_cents") + v.writes
    vals: Tuple[object, ...] = (oid, customer, 1999) + (addr,) * len(v.writes)
    conn.execute(
        "INSERT INTO orders (%s) VALUES (%s)"
        % (",".join(cols), ",".join("?" * len(cols))), vals)


def read_order(conn: sqlite3.Connection, v: Version,
               oid: int) -> Tuple[Optional[str], bool]:
    """SELECT * then row[key] — the ORM read path. A dropped or renamed column
    is not an error here; it is a KeyError the framework turns into None."""
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if row is None:
        return None, False
    d = {k: row[k] for k in row.keys()}
    return d.get(v.reads), True


def export_order(conn: sqlite3.Connection, v: Version,
                 oid: int) -> Tuple[Optional[str], bool]:
    """The nightly reconciliation job. It PERSISTS what the read gave it."""
    addr, found = read_order(conn, v, oid)
    if not found:
        return None, False
    conn.execute(
        "INSERT INTO order_exports (order_id, customer, address) VALUES (?,?,?)",
        (oid, "cust", addr))
    return addr, True


@dataclass
class Tally:
    requests: int = 0
    errors: int = 0          # 5xx: the write blew up, the order is gone
    bad_reads: int = 0       # served a customer the wrong/blank address, no error
    bad_exports: int = 0     # PERSISTED a wrong/blank address, no error
    err_sample: str = ""


def new_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT,"
                 " total_cents INTEGER, ship_to TEXT)")
    conn.execute("CREATE TABLE order_exports (order_id INTEGER, customer TEXT,"
                 " address TEXT)")
    return conn


def seed_orders(conn: sqlite3.Connection, n: int,
                truth: Dict[int, str]) -> None:
    for oid in range(1, n + 1):
        addr = "%d Legacy Row" % (100 + oid)
        conn.execute("INSERT INTO orders (id, customer, total_cents, ship_to)"
                     " VALUES (?,?,?,?)", (oid, "cust-%d" % (oid % 97), 1999, addr))
        truth[oid] = addr
    conn.commit()


def run_fleet(conn: sqlite3.Connection, versions: Sequence[Version],
              truth: Dict[int, str], ids: List[int], rng: random.Random,
              n: int, next_id: List[int]) -> Tally:
    """One slice of live traffic. Each request lands on a random instance, and
    the instances are running different versions because a rollout is in flight."""
    t = Tally()
    for _ in range(n):
        v = rng.choice(versions)
        roll = rng.random()
        t.requests += 1
        try:
            if roll < 0.45:
                oid = next_id[0]
                next_id[0] += 1
                addr = "%d Example St" % rng.randrange(10, 9999)
                create_order(conn, v, oid, "cust-%d" % (oid % 97), addr)
                conn.commit()
                truth[oid] = addr
                ids.append(oid)
            elif roll < 0.78:
                oid = ids[rng.randrange(len(ids))]
                got, found = read_order(conn, v, oid)
                if found and got != truth[oid]:
                    t.bad_reads += 1
            else:
                oid = ids[rng.randrange(len(ids))]
                got, found = export_order(conn, v, oid)
                conn.commit()
                if found and got != truth[oid]:
                    t.bad_exports += 1
        except sqlite3.Error as exc:
            conn.rollback()
            t.errors += 1
            if not t.err_sample:
                t.err_sample = "%s: %s" % (type(exc).__name__, exc)
    return t


def persisted_corruption(conn: sqlite3.Connection, truth: Dict[int, str]) -> int:
    bad = 0
    for oid, addr in conn.execute(
            "SELECT order_id, address FROM order_exports"):
        if truth.get(oid) is not None and addr != truth[oid]:
            bad += 1
    return bad


def columns(conn: sqlite3.Connection) -> str:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(orders)")]
    return ", ".join(c for c in cols if c in ("ship_to", "shipping_address"))


# --------------------------------------------------------------------------- #
# 1 · The overlap window, as a failure                                          #
# --------------------------------------------------------------------------- #

def section_one() -> Tuple[Tally, int, int]:
    print("\n%s\n== 1 · THE OVERLAP WINDOW: ONE RENAME, TWO VERSIONS, ONE DATABASE ==\n%s"
          % (BAR, BAR))
    rng = random.Random(SEED)
    conn = new_db()
    truth: Dict[int, str] = {}
    seed_orders(conn, 400, truth)
    ids = list(truth)
    next_id = [10_001]

    print("  fleet: 6 instances behind one load balancer, one shared database")
    print("  the migration is the whole change, run at deploy time:")
    print("    ALTER TABLE orders RENAME COLUMN ship_to TO shipping_address;")
    conn.execute("ALTER TABLE orders RENAME COLUMN ship_to TO shipping_address")
    conn.commit()
    print("  that DDL took a few microseconds. Now the rollout begins.\n")

    print("  %-26s %8s %8s %10s %10s" %
          ("rollout stage", "reqs", "5xx", "bad reads", "bad exports"))
    total = Tally()
    stages = [("3 of 6 on v2 (t+0s)", (V1, V1, V1, V2, V2, V2), 700),
              ("5 of 6 on v2 (t+40s)", (V1, V2, V2, V2, V2, V2), 500),
              ("6 of 6 on v2 (t+90s)", (V2,) * 6, 500)]
    for label, fleet, n in stages:
        t = run_fleet(conn, fleet, truth, ids, rng, n, next_id)
        print("  %-26s %8d %8d %10d %10d"
              % (label, t.requests, t.errors, t.bad_reads, t.bad_exports))
        total.requests += t.requests
        total.errors += t.errors
        total.bad_reads += t.bad_reads
        total.bad_exports += t.bad_exports
        if t.err_sample and not total.err_sample:
            total.err_sample = t.err_sample
    print("  %-26s %8d %8d %10d %10d"
          % ("TOTAL", total.requests, total.errors, total.bad_reads,
             total.bad_exports))

    persisted = persisted_corruption(conn, truth)
    exports = conn.execute("SELECT count(*) FROM order_exports").fetchone()[0]
    blank = conn.execute(
        "SELECT count(*) FROM order_exports WHERE address IS NULL").fetchone()[0]
    print()
    print("  the loud half : %d requests raised %s" % (total.errors, total.err_sample))
    print("                  every one of those was a lost order and a 500.")
    print("  the quiet half: %d of %d exported rows have a NULL address"
          % (blank, exports))
    print("                  %d exported rows disagree with what was actually stored."
          % persisted)
    print("                  No exception. No log line. No alert. The read path is")
    print("                  SELECT * then row['ship_to'] — after the rename that key")
    print("                  is simply absent, so the ORM hands the app None.")
    print("  the window closed at t+90s. The 5xxs stopped. The %d corrupt export"
          % persisted)
    print("  rows are still there, and are found by reconciliation the next morning.")
    conn.close()
    return total, persisted, blank


# --------------------------------------------------------------------------- #
# 2 · The same rename, expand / migrate / contract                              #
# --------------------------------------------------------------------------- #

def section_two() -> Tuple[Tally, int]:
    print("\n%s\n== 2 · THE SAME RENAME AS EXPAND / MIGRATE / CONTRACT ==\n%s"
          % (BAR, BAR))
    rng = random.Random(SEED)
    conn = new_db()
    truth: Dict[int, str] = {}
    seed_orders(conn, 400, truth)
    ids = list(truth)
    next_id = [10_001]

    print("  five separately deployable steps. The fleet stays MIXED throughout.")
    print("  %-4s %-30s %-22s %6s %5s %6s %7s" %
          ("step", "action", "fleet", "reqs", "5xx", "bad-rd", "bad-exp"))

    total = Tally()
    backfilled = [0, 0]

    def stage(step: str, action: str, fleet: Sequence[Version],
              n: int, ddl: Optional[Callable[[], None]] = None) -> None:
        if ddl is not None:
            ddl()
        t = run_fleet(conn, fleet, truth, ids, rng, n, next_id)
        mix = "+".join(sorted({v.name for v in fleet}))
        print("  %-4s %-30s %-22s %6d %5d %6d %7d"
              % (step, action, mix, t.requests, t.errors, t.bad_reads,
                 t.bad_exports))
        total.requests += t.requests
        total.errors += t.errors
        total.bad_reads += t.bad_reads
        total.bad_exports += t.bad_exports

    def do_expand() -> None:
        conn.execute("ALTER TABLE orders ADD COLUMN shipping_address TEXT")
        conn.commit()

    def do_backfill() -> None:
        # Keyset pagination, not OFFSET: find the next unbackfilled id, take a
        # bounded window from there, commit, repeat. Never one big UPDATE.
        lo, batches, rows = 0, 0, 0
        while True:
            nxt = conn.execute(
                "SELECT min(id) FROM orders WHERE shipping_address IS NULL"
                " AND id > ?", (lo,)).fetchone()[0]
            if nxt is None:
                break
            cur = conn.execute(
                "UPDATE orders SET shipping_address = ship_to"
                " WHERE shipping_address IS NULL AND id >= ? AND id < ?",
                (nxt, nxt + 100))
            conn.commit()
            rows += cur.rowcount
            batches += 1
            lo = nxt + 99
        backfilled[0], backfilled[1] = rows, batches

    def do_contract() -> None:
        conn.execute("ALTER TABLE orders DROP COLUMN ship_to")
        conn.commit()

    stage("0", "(nothing yet)", (V1,) * 6, 200)
    stage("1", "EXPAND: ADD COLUMN (nullable)", (V1, V1, V1, V1D, V1D, V1D), 300,
          do_expand)
    stage("2", "BACKFILL in batches of 100", (V1D,) * 6, 300, do_backfill)
    stage("3", "MIGRATE: deploy new readers", (V1D, V1D, V1D, V2R, V2R, V2R), 300)
    stage("4", "drop the dual write", (V2R, V2R, V2R, V2, V2, V2), 300)
    stage("5", "CONTRACT: DROP COLUMN ship_to", (V2,) * 6, 300, do_contract)

    print("  %-4s %-30s %-22s %6d %5d %6d %7d"
          % ("", "TOTAL", "", total.requests, total.errors, total.bad_reads,
             total.bad_exports))
    persisted = persisted_corruption(conn, truth)
    exports = conn.execute("SELECT count(*) FROM order_exports").fetchone()[0]
    print()
    print("  backfill: %d legacy rows in %d batches of 100"
          % (backfilled[0], backfilled[1]))
    print("  final schema: orders(%s)" % columns(conn))
    print("  persisted corruption across all %d exported rows: %d"
          % (exports, persisted))
    conn.close()
    return total, persisted


# --------------------------------------------------------------------------- #
# 3 · Backfills: one transaction vs bounded batches                             #
# --------------------------------------------------------------------------- #

ROWS = 1_000_000
BATCH = 20_000


def build_backfill_db(path: str) -> None:
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT,"
                 " ship_to TEXT, shipping_address TEXT)")
    # A real table has indexes, and the backfill has to maintain every one of
    # them. Leaving them out here would flatter the single-transaction run.
    conn.execute("CREATE INDEX ix_orders_shipping ON orders(shipping_address)")
    conn.execute("BEGIN")
    conn.executemany(
        "INSERT INTO orders (id, customer, ship_to) VALUES (?,?,?)",
        ((i, "cust-%d" % (i % 997), "%d Legacy Row, Springfield" % i)
         for i in range(1, ROWS + 1)))
    conn.execute("COMMIT")
    conn.close()


def reader_loop(path: str, stop: threading.Event, out: List[float]) -> None:
    """Ordinary production traffic during the backfill: one small indexed read,
    over and over. timeout=0 disables SQLite's own escalating busy-backoff so
    that what we record is the real block, at 1 ms resolution."""
    conn = sqlite3.connect(path, timeout=0)
    while not stop.is_set():
        t0 = time.perf_counter()
        while True:
            try:
                conn.execute("SELECT count(*) FROM orders WHERE id BETWEEN ? AND ?",
                             (1000, 2000)).fetchone()
                break
            except sqlite3.OperationalError as exc:
                if "lock" not in str(exc) and "busy" not in str(exc):
                    raise
                if stop.is_set():
                    break
                time.sleep(0.001)          # blocked: the writer holds the table
        out.append(time.perf_counter() - t0)
        time.sleep(0.002)
    conn.close()


def measure_backfill(path: str, batch: Optional[int]) -> Dict[str, float]:
    """batch=None -> one transaction over the whole table."""
    stop = threading.Event()
    lat: List[float] = []
    th = threading.Thread(target=reader_loop, args=(path, stop, lat), daemon=True)
    th.start()
    time.sleep(0.15)                      # let the reader establish a baseline
    base = len(lat)

    conn = sqlite3.connect(path, timeout=60.0, isolation_level=None)
    holds: List[float] = []
    rows = 0
    t_start = time.perf_counter()
    if batch is None:
        t0 = time.perf_counter()
        conn.execute("BEGIN EXCLUSIVE")
        cur = conn.execute("UPDATE orders SET shipping_address = ship_to"
                           " WHERE shipping_address IS NULL")
        rows = cur.rowcount
        conn.execute("COMMIT")
        holds.append(time.perf_counter() - t0)
    else:
        lo = 0
        while lo < ROWS:
            t0 = time.perf_counter()
            conn.execute("BEGIN EXCLUSIVE")
            cur = conn.execute(
                "UPDATE orders SET shipping_address = ship_to"
                " WHERE shipping_address IS NULL AND id > ? AND id <= ?",
                (lo, lo + batch))
            rows += cur.rowcount
            conn.execute("COMMIT")
            holds.append(time.perf_counter() - t0)
            lo += batch
            time.sleep(0.005)             # the pause that lets readers through
    total = time.perf_counter() - t_start
    conn.close()
    stop.set()
    th.join()

    during = sorted(lat[base:]) or [0.0]
    idx = min(len(during) - 1, int(0.99 * len(during)))
    return {"total": total, "rows": float(rows), "txns": float(len(holds)),
            "max_hold": max(holds), "reads": float(len(during)),
            "p50": statistics.median(during), "p99": during[idx],
            "max_read": during[-1],
            "over_100ms": float(sum(1 for x in during if x > 0.100))}


def section_three(tmpdir: str) -> Tuple[Dict[str, float], Dict[str, float]]:
    print("\n%s\n== 3 · THE BACKFILL: ONE TRANSACTION VS BOUNDED BATCHES ==\n%s"
          % (BAR, BAR))
    print("  %d rows to backfill, one secondary index to maintain." % ROWS)
    print("  A reader thread runs a small indexed SELECT every 2 ms throughout")
    print("  and records how long each one actually took.\n")
    results = {}
    for label, batch in (("one transaction", None), ("batches of %d" % BATCH, BATCH)):
        path = os.path.join(tmpdir, "backfill-%s.db" % ("one" if batch is None else "batched"))
        build_backfill_db(path)
        results[label] = measure_backfill(path, batch)
        os.remove(path)

    print("  %-20s %7s %6s %10s %7s %10s %10s %10s %7s"
          % ("run", "total", "txns", "max lock", "reads", "read p50",
             "read p99", "read max", ">100ms"))
    for label in ("one transaction", "batches of %d" % BATCH):
        r = results[label]
        print("  %-20s %6.2fs %6d %8.0fms %7d %8.1fms %8.1fms %8.0fms %7d"
              % (label, r["total"], r["txns"], r["max_hold"] * 1000,
                 int(r["reads"]), r["p50"] * 1000, r["p99"] * 1000,
                 r["max_read"] * 1000, int(r["over_100ms"])))

    one = results["one transaction"]
    many = results["batches of %d" % BATCH]
    print()
    print("  both backfilled %d rows." % int(one["rows"]))
    print("  the reader completed %d query in the %.2fs single transaction"
          % (int(one["reads"]), one["total"]))
    print("  and %d in the %.2fs batched run — same traffic, same table."
          % (int(many["reads"]), many["total"]))
    print("  total wall time: %.2fs -> %.2fs (%+.0f%%) — the batched run is %s."
          % (one["total"], many["total"],
             100.0 * (many["total"] / one["total"] - 1),
             "slower" if many["total"] > one["total"] else "faster"))
    print("  longest single lock hold: %.0f ms -> %.0f ms (%.0fx shorter)."
          % (one["max_hold"] * 1000, many["max_hold"] * 1000,
             one["max_hold"] / max(many["max_hold"], 1e-9)))
    print("  worst concurrent read:    %.0f ms -> %.0f ms; reads over 100 ms: %d -> %d."
          % (one["max_read"] * 1000, many["max_read"] * 1000,
             int(one["over_100ms"]), int(many["over_100ms"])))
    print("  that trade — a little more total time for a %.0fx shorter worst case —"
          % (one["max_hold"] / max(many["max_hold"], 1e-9)))
    print("  is the entire argument for batching.")
    return one, many


# --------------------------------------------------------------------------- #
# 4 · The lock queue cascade (PostgreSQL semantics, modelled explicitly)         #
# --------------------------------------------------------------------------- #

SHARE, EXCL = "ACCESS SHARE", "ACCESS EXCLUSIVE"


def conflicts(a: str, b: str) -> bool:
    """PostgreSQL's conflict matrix, restricted to the two modes we use:
    ACCESS SHARE (every SELECT) conflicts only with ACCESS EXCLUSIVE (most DDL)."""
    return EXCL in (a, b)


@dataclass
class Req:
    name: str
    mode: str
    dur: float
    arrived: float
    deadline: Optional[float] = None     # lock_timeout
    attempts: int = 0


@dataclass
class LockQueue:
    """A faithful model of PostgreSQL's lock manager for one table.

    The rule that matters: a request is granted only if it conflicts with
    nothing HELD *and* with nothing already WAITING ahead of it. That second
    clause is the cascade — it is why a queued ALTER TABLE blocks every
    ordinary SELECT that arrives after it.
    """
    held: List[Tuple[float, str, str]] = field(default_factory=list)
    wait: List[Req] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    waits: Dict[str, float] = field(default_factory=dict)
    timeouts: int = 0
    now: float = 0.0

    def grant_pass(self) -> None:
        ahead: List[str] = []
        keep: List[Req] = []
        for r in self.wait:
            ok = (not any(conflicts(r.mode, m) for _, m, _ in self.held)
                  and not any(conflicts(r.mode, m) for m in ahead))
            if ok:
                self.held.append((self.now + r.dur, r.mode, r.name))
                self.waits[r.name] = self.now - r.arrived
                if self.now - r.arrived > 1e-4:
                    self.log.append("  t=%6.3f  %-18s %-16s GRANTED after %5.0f ms wait"
                                    % (self.now, r.name, r.mode,
                                       (self.now - r.arrived) * 1000))
            else:
                ahead.append(r.mode)
                keep.append(r)
        self.wait = keep


def run_lock_scenario(lock_timeout: Optional[float], verbose: bool,
                      rng: random.Random) -> Dict[str, float]:
    q = LockQueue()
    pending: List[Tuple[float, int, Req]] = []
    tie = 0

    def push(t: float, r: Req) -> None:
        nonlocal tie
        tie += 1
        heapq.heappush(pending, (t, tie, r))

    push(0.0, Req("analytics SELECT", SHARE, 3.000, 0.0))
    push(0.5, Req("ALTER TABLE", EXCL, 0.001, 0.5))
    for i in range(1, 67):
        t = 0.06 * i
        push(t, Req("SELECT #%d" % i, SHARE, 0.005, t))

    ddl_done_at = None
    ddl_attempts = 0
    while pending or q.wait or q.held:
        cands = []
        if pending:
            cands.append(pending[0][0])
        if q.held:
            cands.append(min(h[0] for h in q.held))
        if q.wait:
            cands += [r.deadline for r in q.wait if r.deadline is not None]
        if not cands:
            break
        q.now = min(cands)

        for h in list(q.held):
            if h[0] <= q.now + 1e-12:
                q.held.remove(h)
                if h[2] == "ALTER TABLE":
                    ddl_done_at = q.now
                if verbose and h[2] in ("analytics SELECT", "ALTER TABLE"):
                    q.log.append("  t=%6.3f  %-18s %-16s RELEASED"
                                 % (q.now, h[2], h[1]))

        while pending and pending[0][0] <= q.now + 1e-12:
            _, _, r = heapq.heappop(pending)
            r.arrived = q.now
            if lock_timeout is not None and r.mode == EXCL:
                r.deadline = q.now + lock_timeout
                ddl_attempts += 1
            q.wait.append(r)
            if verbose and r.mode == EXCL:
                q.log.append("  t=%6.3f  %-18s %-16s REQUESTED"
                             % (q.now, r.name, r.mode))

        for r in list(q.wait):
            if r.deadline is not None and r.deadline <= q.now + 1e-12:
                q.wait.remove(r)
                q.timeouts += 1
                if verbose:
                    q.log.append("  t=%6.3f  %-18s %-16s lock_timeout — ABORTED,"
                                 " queue drains" % (q.now, r.name, r.mode))
                back = min(0.25 * (2 ** (r.attempts)), 2.0)
                back *= 0.9 + 0.2 * rng.random()          # jitter, seeded
                nxt = Req(r.name, r.mode, r.dur, q.now + back)
                nxt.attempts = r.attempts + 1
                push(q.now + back, nxt)

        q.grant_pass()

    blocked = {k: v for k, v in q.waits.items()
               if k.startswith("SELECT") and v > 1e-4}
    return {"blocked": float(len(blocked)),
            "max_wait": max(blocked.values()) * 1000 if blocked else 0.0,
            "total_wait": sum(blocked.values()),
            "ddl_done": ddl_done_at if ddl_done_at is not None else -1.0,
            "attempts": float(max(ddl_attempts, 1)),
            "timeouts": float(q.timeouts),
            "log": q.log}  # type: ignore[dict-item]


def section_four() -> Tuple[Dict[str, float], Dict[str, float]]:
    print("\n%s\n== 4 · THE LOCK QUEUE CASCADE (PostgreSQL semantics, MODELLED) ==\n%s"
          % (BAR, BAR))
    print("  Not observed from SQLite — SQLite has a different locking model.")
    print("  This implements PostgreSQL's rule: a lock request is granted only if")
    print("  it conflicts with nothing HELD *and* nothing already WAITING ahead of it.\n")
    print("  t=0.000  an analytics SELECT takes ACCESS SHARE and holds it 3.000 s")
    print("  t=0.500  ALTER TABLE asks for ACCESS EXCLUSIVE; its own work is 1 ms")
    print("  every 60 ms  an ordinary SELECT arrives, needing ACCESS SHARE for 5 ms\n")

    a = run_lock_scenario(None, True, random.Random(SEED))
    print("  --- run A: a bare ALTER TABLE, no lock_timeout ---")
    for line in a["log"][:6]:              # type: ignore[index]
        print(line)
    print("  ...")
    print("  ALTER TABLE finally ran at t=%.3f — it waited %.0f ms for 1 ms of work."
          % (a["ddl_done"], (a["ddl_done"] - 0.5) * 1000))
    print("  innocent SELECTs blocked behind the WAITING DDL: %d" % int(a["blocked"]))
    print("     worst wait %.0f ms; %.1f query-seconds of stalled traffic in total."
          % (a["max_wait"], a["total_wait"]))
    print("     none of them conflicted with the analytics query. They conflicted")
    print("     with the ALTER that was itself still waiting.\n")

    b = run_lock_scenario(0.050, True, random.Random(SEED))
    print("  --- run B: SET lock_timeout = '50ms', retry with jittered backoff ---")
    for line in b["log"][:5]:              # type: ignore[index]
        print(line)
    print("  ...")
    print("  the DDL gave up %d times and succeeded on attempt %d at t=%.3f."
          % (int(b["timeouts"]), int(b["attempts"]), b["ddl_done"]))
    print("  innocent SELECTs blocked: %d (was %d) — a %.0fx reduction."
          % (int(b["blocked"]), int(a["blocked"]),
             a["blocked"] / max(b["blocked"], 1.0)))
    print("     worst wait %.0f ms (was %.0f ms); %.2f query-seconds stalled (was %.1f)."
          % (b["max_wait"], a["max_wait"], b["total_wait"], a["total_wait"]))
    print("  the DDL landed later (%.2fs vs %.2fs). That is the whole trade:"
          % (b["ddl_done"], a["ddl_done"]))
    print("  a bounded wait costs the migration elapsed time and costs the table nothing.")
    return a, b


# --------------------------------------------------------------------------- #
# 5 · Rollback compatibility                                                    #
# --------------------------------------------------------------------------- #

STATES = [
    ("S0", "before expand", ("ship_to",), False),
    ("S1", "after EXPAND, not backfilled", ("ship_to", "shipping_address"), False),
    ("S2", "after BACKFILL", ("ship_to", "shipping_address"), True),
    ("S3", "after CONTRACT", ("shipping_address",), True),
]


def build_state(cols: Sequence[str], backfilled: bool) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer TEXT,"
                 " total_cents INTEGER, %s)" % ", ".join("%s TEXT" % c for c in cols))
    conn.execute("CREATE TABLE order_exports (order_id INTEGER, customer TEXT,"
                 " address TEXT)")
    vals = ["1 Legacy Row" if (c == "ship_to" or backfilled) else None for c in cols]
    conn.execute("INSERT INTO orders (id, customer, total_cents, %s)"
                 " VALUES (?,?,?,%s)" % (",".join(cols), ",".join("?" * len(cols))),
                 [1, "cust-1", 1999] + vals)
    conn.commit()
    return conn


def probe(version: Version, cols: Sequence[str], backfilled: bool) -> str:
    """Can this code version serve traffic against this schema state?
    OK = correct. SILENT = no error, wrong answer. FAIL = it raises."""
    conn = build_state(cols, backfilled)
    try:
        create_order(conn, version, 2, "cust-2", "2 New Row")
        conn.commit()
    except sqlite3.Error:
        conn.close()
        return "FAIL"
    verdict = "OK"
    for oid, expect in ((1, "1 Legacy Row"), (2, "2 New Row")):
        got, _ = read_order(conn, version, oid)
        if got != expect:
            verdict = "SILENT"
    conn.close()
    return verdict


def section_five() -> Dict[str, List[str]]:
    print("\n%s\n== 5 · ROLLBACK COMPATIBILITY: WHICH STEPS CAN YOU UNDO? ==\n%s"
          % (BAR, BAR))
    print("  Every code version is run against every schema state. OK = correct;")
    print("  SILENT = no exception and the wrong answer; FAIL = it raises.\n")
    versions = (V1, V1D, V2R, V2)
    print("  %-4s %-30s %-9s %-9s %-9s %-9s"
          % ("", "schema state", *[v.name for v in versions]))
    reachable: Dict[str, List[str]] = {}
    for sid, label, cols, backfilled in STATES:
        results = [probe(v, cols, backfilled) for v in versions]
        reachable[sid] = [v.name for v, r in zip(versions, results) if r == "OK"]
        print("  %-4s %-30s %-9s %-9s %-9s %-9s" % (sid, label, *results))
    print()
    print("  reachable rollback set, per step:")
    order = [("S0", "before expand"), ("S1", "after EXPAND"),
             ("S2", "after BACKFILL"), ("S3", "after CONTRACT")]
    for sid, label in order:
        names = reachable[sid]
        print("    %-22s -> %-24s (%d of 4 versions)"
              % (label, ", ".join(names) if names else "NOTHING", len(names)))
    print()
    print("  read the last row. After CONTRACT, v1 and v1d do not merely misbehave —")
    print("  they raise, on every single request. The DROP is the step that")
    print("  forfeits your rollback. Everything before it is reversible; that one")
    print("  is not, and it is the reason contract waits for a real soak.")
    return reachable


# --------------------------------------------------------------------------- #

def main() -> None:
    t0 = time.perf_counter()
    naive, persisted, blank = section_one()
    clean, clean_persisted = section_two()
    one, many = section_three(tempfile.mkdtemp(prefix="l13-"))
    a, b = section_four()
    section_five()

    print("\n%s\n== SUMMARY ==\n%s" % (BAR, BAR))
    print("  1 vs 2  same rename, %d requests through a mixed fleet either way:"
          % naive.requests)
    print("          naive : %d errors, %d bad reads, %d corrupt exported rows"
          % (naive.errors, naive.bad_reads, naive.bad_exports))
    print("          expand/migrate/contract : %d / %d / %d over %d requests"
          % (clean.errors, clean.bad_reads, clean.bad_exports, clean.requests))
    print("  3       backfill worst-case lock hold %.0f ms -> %.0f ms;"
          % (one["max_hold"] * 1000, many["max_hold"] * 1000))
    print("          worst concurrent read %.0f ms -> %.0f ms"
          % (one["max_read"] * 1000, many["max_read"] * 1000))
    print("  4       queries blocked behind a waiting DDL: %d -> %d with lock_timeout"
          % (int(a["blocked"]), int(b["blocked"])))
    print("  5       rollback is free until CONTRACT, and impossible after it.")
    print("\n  (total wall time %.1f s)" % (time.perf_counter() - t0))


if __name__ == "__main__":
    main()
