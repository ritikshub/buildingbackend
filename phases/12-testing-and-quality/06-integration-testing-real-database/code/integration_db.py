"""Phase 12, Lesson 06 — Integration Testing Against a Real Database (docs/en.md).

Runs a real SQL engine (stdlib `sqlite3`) as the database under test and measures:
the SQLite/PostgreSQL divergence table, what a hand-written fake cannot enforce, four
test-isolation strategies costed in deterministic work units, the rollback lie, every
interleaving of a lost update, and migrate-forward vs load-a-dump schema drift.
Sources: PostgreSQL 17 docs ch.8 (Data Types), ch.13 (Concurrency Control), Appendix A
(Error Codes); SQLite "Datatypes In SQLite" §3 (type affinity) and "Isolation In SQLite";
ISO/IEC 9075-2:2016 §4.35 (isolation levels).  Standard library only, seed = 11,
temp files only, no wall-clock value is printed so two runs are byte-identical.
Runtime: about 6 seconds.
"""

from __future__ import annotations

import os
import random
import sqlite3
import tempfile
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

SEED = 11

# Two constants this program does NOT measure, used only in the clearly-labelled
# projection at the end of section 3. Substitute values from your own server.
FSYNC_MS = 1.0      # one PostgreSQL commit with fsync on
STMT_MS = 0.05      # one simple prepared-statement round trip, same host


def banner(s: str) -> None:
    print(f"\n== {s} ==")


def rule() -> None:
    print("  " + "-" * 74)


class Counted:
    """A sqlite3 connection that counts statements, row changes and commits.

    Cost is reported in these integers rather than in seconds. Wall-clock time is
    not reproducible across machines; the physical work the clock is measuring is.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        # isolation_level=None turns OFF the sqlite3 module's implicit BEGIN, so
        # every transaction below is one that was typed on purpose.
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.stmts = 0
        self.commits = 0
        self.conn.set_trace_callback(self._trace)

    def _trace(self, sql: str) -> None:
        self.stmts += 1
        if sql.strip().upper().startswith(("COMMIT", "END")):
            self.commits += 1

    def x(self, sql: str, args: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, args)

    def one(self, sql: str, args: Sequence[Any] = ()) -> Any:
        row = self.conn.execute(sql, args).fetchone()
        return row[0] if row and len(row) == 1 else row

    @property
    def changes(self) -> int:
        return self.conn.total_changes

    def close(self) -> None:
        self.conn.close()


# ===========================================================================
# 1 · THE SUBSTITUTE-DATABASE FALLACY: THE DIVERGENCE TABLE
# ===========================================================================

@dataclass
class Divergence:
    """One semantic difference: executed live on SQLite, documented for Postgres."""

    tag: str
    what: str
    probe: Callable[[Counted], str]      # runs for real, returns SQLite's answer
    pg: str                              # PostgreSQL's answer
    sqlstate: str                        # "" when PostgreSQL also returns a row
    sqlite_answer: str = field(default="", init=False)

    @property
    def raises_in_pg(self) -> bool:
        return bool(self.sqlstate)


def _d_affinity(c: Counted) -> str:
    c.x("CREATE TABLE d1(sku TEXT, qty INTEGER)")
    c.x("INSERT INTO d1 VALUES('A-1', '12 units')")
    return (f"row stored, typeof='{c.one('SELECT typeof(qty) FROM d1')}', "
            f"SUM(qty)={c.one('SELECT sum(qty) FROM d1')}")


def _d_varchar(c: Counted) -> str:
    c.x("CREATE TABLE d2(code VARCHAR(10))")
    c.x("INSERT INTO d2 VALUES(?)", ("X" * 30,))
    return f"row stored, length(code)={c.one('SELECT length(code) FROM d2')}"


def _d_numeric(c: Counted) -> str:
    c.x("CREATE TABLE d3(cents NUMERIC(10,2))")
    for v in ("10.005", "0.1", "0.2"):
        c.x(f"INSERT INTO d3 VALUES({v})")
    return (f"typeof='{c.one('SELECT typeof(cents) FROM d3 LIMIT 1')}', "
            f"SUM={c.one('SELECT sum(cents) FROM d3')}")


def _d_divzero(c: Counted) -> str:
    c.x("CREATE TABLE d4(revenue INTEGER, units INTEGER)")
    c.x("INSERT INTO d4 VALUES(500, 0)")
    return f"returns {c.one('SELECT revenue / units FROM d4')!r} — one row, no error"


def _d_like(c: Counted) -> str:
    c.x("CREATE TABLE d5(email TEXT)")
    c.x("INSERT INTO d5 VALUES('ada@example.com')")
    n = c.one("SELECT count(*) FROM d5 WHERE email LIKE 'ADA%'")
    return f"LIKE 'ADA%' matches {n} row"


def _d_fk(c: Counted) -> str:
    on = c.one("PRAGMA foreign_keys")
    c.x("CREATE TABLE d6p(id INTEGER PRIMARY KEY)")
    c.x("CREATE TABLE d6c(id INTEGER PRIMARY KEY, pid INTEGER REFERENCES d6p(id))")
    c.x("INSERT INTO d6c VALUES(1, 999)")
    n = c.one("SELECT count(*) FROM d6c")
    return f"PRAGMA foreign_keys={on} by default; {n} orphan row inserted"


def _d_collation(c: Counted) -> str:
    c.x("CREATE TABLE d7(name TEXT)")
    for n in ("ada", "Zoe", "Bob", "carol"):
        c.x("INSERT INTO d7 VALUES(?)", (n,))
    return f"page 1 = {[r[0] for r in c.x('SELECT name FROM d7 ORDER BY name LIMIT 2')]}"


def _d_groupby(c: Counted) -> str:
    c.x("CREATE TABLE d8(cust INTEGER, city TEXT)")
    for a, b in ((1, "Berlin"), (1, "Lisbon"), (2, "Oslo")):
        c.x("INSERT INTO d8 VALUES(?,?)", (a, b))
    rows = c.x("SELECT cust, city, count(*) FROM d8 GROUP BY cust").fetchall()
    return f"returns {rows} — picks a city arbitrarily"


def _d_sequence(c: Counted) -> str:
    c.x("CREATE TABLE d9(id INTEGER PRIMARY KEY, v TEXT)")
    c.x("INSERT INTO d9(v) VALUES('first')")
    c.x("BEGIN")
    c.x("INSERT INTO d9(v) VALUES('rolled back')")
    c.x("ROLLBACK")
    c.x("INSERT INTO d9(v) VALUES('second')")
    return f"ids are {[r[0] for r in c.x('SELECT id FROM d9')]} — id 2 reused"


def _d_snapshot(c: Counted) -> str:
    # Needs WAL, which is what any serious SQLite setup uses. In the default
    # rollback journal an open reader blocks the writer outright — a second
    # divergence from PostgreSQL's MVCC, and not the one being shown here.
    path = os.path.join(os.path.dirname(c.path), "d10.db")
    a = sqlite3.connect(path, isolation_level=None)
    a.execute("PRAGMA journal_mode=WAL")
    a.execute("CREATE TABLE d10(id INTEGER PRIMARY KEY, bal INTEGER)")
    a.execute("INSERT INTO d10 VALUES(1, 100)")
    other = sqlite3.connect(path, isolation_level=None)
    a.execute("BEGIN")
    first = a.execute("SELECT bal FROM d10 WHERE id=1").fetchone()[0]
    other.execute("UPDATE d10 SET bal=555 WHERE id=1")
    second = a.execute("SELECT bal FROM d10 WHERE id=1").fetchone()[0]
    a.execute("ROLLBACK")
    a.close()
    other.close()
    return f"same txn reads {first} then {second} — unchanged"


def _d_nullunique(c: Counted) -> str:
    c.x("CREATE TABLE d11(email TEXT UNIQUE)")
    for _ in range(3):
        c.x("INSERT INTO d11 VALUES(NULL)")
    return f"{c.one('SELECT count(*) FROM d11')} NULL rows accepted"


DIVERGENCES: list[Divergence] = [
    Divergence("type affinity", "INSERT '12 units' INTO an INTEGER column",
               _d_affinity,
               'ERROR: invalid input syntax for type integer: "12 units"', "22P02"),
    Divergence("VARCHAR length", "INSERT 30 chars INTO VARCHAR(10)", _d_varchar,
               "ERROR: value too long for type character varying(10)", "22001"),
    Divergence("NUMERIC is exact", "SUM over a NUMERIC(10,2) money column",
               _d_numeric,
               "typeof='numeric', SUM=10.31 (exact decimal, 10.005 -> 10.01)", ""),
    Divergence("divide by zero", "SELECT revenue / units WHERE units = 0",
               _d_divzero, "ERROR: division by zero", "22012"),
    Divergence("LIKE case", "WHERE email LIKE 'ADA%'", _d_like,
               "LIKE 'ADA%' matches 0 rows (LIKE is case-sensitive)", ""),
    Divergence("FK enforcement", "INSERT a child row with no parent", _d_fk,
               "ERROR: insert or update violates foreign key constraint", "23503"),
    Divergence("ORDER BY collation", "ORDER BY name LIMIT 2 (mixed case)",
               _d_collation, "page 1 = ['ada', 'Bob']  (en_US.UTF-8 collation)", ""),
    Divergence("GROUP BY strictness", "SELECT cust, city ... GROUP BY cust",
               _d_groupby,
               'ERROR: column "d8.city" must appear in the GROUP BY clause', "42803"),
    Divergence("sequence gaps", "id of the next row after a rolled-back INSERT",
               _d_sequence, "ids are [1, 3] — the sequence is non-transactional", ""),
    Divergence("read snapshot", "re-read a row another txn committed", _d_snapshot,
               "same txn reads 100 then 555 — READ COMMITTED re-reads", ""),
]

CONTROL = Divergence("nullable UNIQUE", "three NULLs into a UNIQUE column",
                     _d_nullunique,
                     "3 NULL rows accepted (NULLS DISTINCT is the default)", "")


def section1(tmp: str) -> tuple[int, int]:
    banner("1 · THE SUBSTITUTE-DATABASE FALLACY: THE DIVERGENCE TABLE")
    print("  The SQLITE column is executed live, right now, by this program. The")
    print("  POSTGRESQL column is documented behaviour with its SQLSTATE code")
    print("  (PostgreSQL 17 ch.8 Data Types, ch.13 Concurrency Control, Appendix A")
    print("  Error Codes). Same schema, same SQL, two engines.\n")

    c = Counted(os.path.join(tmp, "divergence.db"))
    for d in DIVERGENCES + [CONTROL]:
        d.sqlite_answer = d.probe(c)
    c.close()

    for d in DIVERGENCES:
        print(f"  {d.tag.upper()}  ·  {d.what}")
        print(f"     sqlite3     {d.sqlite_answer}")
        print(f"     postgres    {f'[{d.sqlstate}] ' if d.sqlstate else ''}{d.pg}\n")

    raises = sum(1 for d in DIVERGENCES if d.raises_in_pg)
    silent = len(DIVERGENCES) - raises
    rule()
    print(f"  {len(DIVERGENCES)} schema/query pairs; all {len(DIVERGENCES)} answered "
          "differently.")
    print(f"    {raises:2d} PostgreSQL refuses outright. Your suite is green and")
    print("       production throws a 500 the first time that path runs.")
    print(f"    {silent:2d} BOTH engines answer, with different answers. No error is")
    print("       raised anywhere, ever — the wrong number IS the output. Those")
    print("       five are money (SUM differs in the 3rd decimal), search (a LIKE")
    print("       that matches here and not there), ordering (page 1 holds")
    print("       different rows), identity (the next id) and isolation.")
    rule()
    print(f"\n  THE CONTROL — {CONTROL.what}:")
    print(f"     sqlite3     {CONTROL.sqlite_answer}")
    print(f"     postgres    {CONTROL.pg}")
    print("  Identical. This is the divergence everybody names first and it is not")
    print("  one: both follow SQL:2016 and treat NULLs as distinct in a UNIQUE")
    print("  index. The differences that bite are never the ones you worry about.")
    return raises, silent


# ===========================================================================
# 2 · WHAT ONLY A REAL DATABASE ENFORCES
# ===========================================================================

class FakeOrderRepo:
    """The in-memory fake a competent engineer writes on the second day.

    It re-implements the one constraint that was in the ticket (unique email),
    because nothing else was.
    """

    def __init__(self) -> None:
        self.customers: dict[int, dict[str, Any]] = {}
        self.orders: dict[int, dict[str, Any]] = {}
        self._next = 1

    def _id(self) -> int:
        self._next += 1
        return self._next - 1

    def add_customer(self, email: str | None, tier: str = "std") -> int:
        if email is not None and any(c["email"] == email
                                     for c in self.customers.values()):
            raise ValueError("duplicate email")
        self.customers[(cid := self._id())] = {"email": email, "tier": tier}
        return cid

    def add_order(self, cid: int, cents: int, status: str = "new") -> int:
        self.orders[(oid := self._id())] = {"cid": cid, "cents": cents,
                                          "status": status}
        return oid

    def delete_customer(self, cid: int) -> None:
        self.customers.pop(cid, None)

    def upsert_customer(self, email: str, tier: str) -> int:
        for cid, row in self.customers.items():
            if row["email"] == email:
                row["tier"] = tier
                return cid
        return self.add_customer(email, tier)


DDL_REAL = [
    "CREATE TABLE customers(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL,"
    " tier TEXT NOT NULL DEFAULT 'std' CHECK(tier IN ('std','gold')))",
    "CREATE TABLE orders(id INTEGER PRIMARY KEY,"
    " cid INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,"
    " cents INTEGER NOT NULL CHECK(cents > 0), status TEXT NOT NULL DEFAULT 'new')",
    "CREATE UNIQUE INDEX uniq_open_order ON orders(cid) WHERE status='open'",
]


def section2(tmp: str) -> tuple[int, int]:
    banner("2 · WHAT ONLY A REAL DATABASE ENFORCES")
    print("  Ten rules this schema states. The fake re-implements the ones its")
    print("  author thought of; the engine enforces the ones it was told.\n")

    c = Counted(os.path.join(tmp, "enforce.db"))
    c.x("PRAGMA foreign_keys=ON")          # off by default — divergence 6
    for stmt in DDL_REAL:
        c.x(stmt)

    def refused_real(fn: Callable[[], Any]) -> bool:
        try:
            c.x("SAVEPOINT probe")
            fn()
            c.x("RELEASE probe")
            return False
        except sqlite3.Error:
            c.x("ROLLBACK TO probe")
            c.x("RELEASE probe")
            return True

    def refused_fake(fn: Callable[[], Any]) -> bool:
        try:
            fn()
            return False
        except Exception:
            return True

    f = FakeOrderRepo()
    c.x("INSERT INTO customers(id,email,tier) VALUES(1,'ada@x.io','gold')")
    f.add_customer("ada@x.io", "gold")
    c.x("INSERT INTO orders(id,cid,cents,status) VALUES(10,1,500,'open')")
    f.add_order(1, 500, "open")

    checks = [
        ("UNIQUE(email) rejects a duplicate",
         lambda: c.x("INSERT INTO customers(email) VALUES('ada@x.io')"),
         lambda: f.add_customer("ada@x.io")),
        ("NOT NULL rejects a missing email",
         lambda: c.x("INSERT INTO customers(email) VALUES(NULL)"),
         lambda: f.add_customer(None)),
        ("CHECK(tier IN ...) rejects 'platinum'",
         lambda: c.x("INSERT INTO customers(email,tier) VALUES('b@x.io','platinum')"),
         lambda: f.add_customer("b@x.io", "platinum")),
        ("CHECK(cents > 0) rejects a zero-value order",
         lambda: c.x("INSERT INTO orders(cid,cents) VALUES(1,0)"),
         lambda: f.add_order(1, 0)),
        ("FOREIGN KEY rejects an order for customer 999",
         lambda: c.x("INSERT INTO orders(cid,cents) VALUES(999,100)"),
         lambda: f.add_order(999, 100)),
        ("partial UNIQUE: one 'open' order per customer",
         lambda: c.x("INSERT INTO orders(cid,cents,status) VALUES(1,900,'open')"),
         lambda: f.add_order(1, 900, "open")),
    ]

    print("     rule                                            fake     real engine")
    fake_ok = real_ok = 0
    for name, real_fn, fake_fn in checks:
        r, k = refused_real(real_fn), refused_fake(fake_fn)
        fake_ok += k
        real_ok += r
        print(f"     {name:<47}{'PASS' if k else 'MISS':<9}{'PASS' if r else 'MISS'}")

    # Four more where the question is a value, not a refusal.
    c.x("INSERT INTO customers(id,email) VALUES(2,'bo@x.io')")
    fid = f.add_customer("bo@x.io")
    vals = [("DEFAULT 'std' applied on INSERT",
             f.customers[fid]["tier"] == "std",
             c.one("SELECT tier FROM customers WHERE id=2") == "std")]

    c.x("INSERT INTO orders(id,cid,cents) VALUES(20,2,700)")
    f.add_order(fid, 700)
    c.x("DELETE FROM customers WHERE id=2")
    f.delete_customer(fid)
    vals.append(("ON DELETE CASCADE removes the child order",
                 not any(o["cid"] == fid for o in f.orders.values()),
                 c.one("SELECT count(*) FROM orders WHERE cid=2") == 0))

    c.x("INSERT INTO customers(email,tier) VALUES('ada@x.io','std') "
        "ON CONFLICT(email) DO UPDATE SET tier=excluded.tier")
    f.upsert_customer("ada@x.io", "std")
    vals.append(("upsert updates instead of duplicating", len(f.customers) == 1,
                 c.one("SELECT count(*) FROM customers") == 1))

    rid = c.one("INSERT INTO orders(cid,cents) VALUES(1,250) RETURNING id")
    vals.append(("INSERT ... RETURNING id gives the new key", False,
                 isinstance(rid, int)))

    print()
    for name, k, r in vals:
        fake_ok += bool(k)
        real_ok += bool(r)
        print(f"     {name:<47}{'PASS' if k else 'MISS':<9}{'PASS' if r else 'MISS'}")

    total = len(checks) + len(vals)
    c.close()
    rule()
    print(f"  fake repository ....... {fake_ok:2d}/{total} rules")
    print(f"  real SQL engine ....... {real_ok:2d}/{total} rules")
    print("  The fake is not lazy. Every rule it missed is one its author never had")
    print("  to think about, because the schema was thinking about it for them. That")
    print("  is the bug class integration tests exist for — not 'more code per test',")
    print("  but the rules that live outside your process.")
    return fake_ok, total


# ===========================================================================
# 3 · TEST ISOLATION: FOUR STRATEGIES, COSTED
# ===========================================================================

FIXTURE_TABLES = [
    ("customers", "CREATE TABLE customers(id INTEGER PRIMARY KEY, email TEXT,"
                  " tier TEXT)", "(id,email,tier)", 40),
    ("addresses", "CREATE TABLE addresses(id INTEGER PRIMARY KEY, cid INTEGER,"
                  " line TEXT)", "(id,cid,line)", 60),
    ("products", "CREATE TABLE products(id INTEGER PRIMARY KEY, sku TEXT,"
                 " cents INTEGER)", "(id,sku,cents)", 50),
    ("orders", "CREATE TABLE orders(id INTEGER PRIMARY KEY, cid INTEGER,"
               " status TEXT)", "(id,cid,status)", 50),
    ("order_items", "CREATE TABLE order_items(id INTEGER PRIMARY KEY, oid INTEGER,"
                    " pid INTEGER, qty INTEGER)", "(id,oid,pid,qty)", 30),
    ("payments", "CREATE TABLE payments(id INTEGER PRIMARY KEY, oid INTEGER,"
                 " cents INTEGER)", "(id,oid,cents)", 10),
]
FIXTURE_INDEXES = [
    "CREATE INDEX ix_addr_cid ON addresses(cid)",
    "CREATE INDEX ix_orders_cid ON orders(cid)",
    "CREATE INDEX ix_items_oid ON order_items(oid)",
]
FIXTURE_ROWS = sum(n for *_, n in FIXTURE_TABLES)
N_TESTS = 200


def create_schema(c: Counted) -> None:
    for _, ddl, _, _ in FIXTURE_TABLES:
        c.x(ddl)
    for ddl in FIXTURE_INDEXES:
        c.x(ddl)


def seed(c: Counted) -> None:
    """Row at a time, like every fixture loader ever written."""
    for name, _, cols, n in FIXTURE_TABLES:
        width = cols.count(",") + 1
        placeholders = ",".join(["?"] * width)
        for i in range(1, n + 1):
            args = [i] + [f"v{i}" if k % 2 else i * 10 for k in range(width - 1)]
            c.x(f"INSERT INTO {name} {cols} VALUES({placeholders})", args)


def one_test(c: Counted, i: int) -> None:
    """What an average integration test actually does to the database."""
    c.x("INSERT INTO orders(cid,status) VALUES(?,?)", (i % 40 + 1, "new"))
    c.x("UPDATE orders SET status='paid' WHERE cid=?", (i % 40 + 1,))
    c.one("SELECT count(*) FROM orders WHERE status='paid'")


@dataclass
class Strat:
    name: str
    stmts: int
    rows: int
    commits: int
    copied: int          # bytes of database file copied, whole run
    isolates: str


def section3(tmp: str) -> list[Strat]:
    banner("3 · TEST ISOLATION: FOUR STRATEGIES OVER 200 TESTS")
    print(f"  Fixture: {len(FIXTURE_TABLES)} tables, {len(FIXTURE_INDEXES)} indexes, "
          f"{FIXTURE_ROWS} seed rows. {N_TESTS} tests.")
    print("  Cost is counted in STATEMENTS, ROW CHANGES and COMMITS — the physical")
    print("  work. Seconds are not printed: they differ on every machine and would")
    print("  make this program non-reproducible. These integers do not.\n")

    out: list[Strat] = []

    # recreate — drop it all, rebuild it, reseed.
    c = Counted(os.path.join(tmp, "s_recreate.db"))
    base = c.stmts
    for i in range(N_TESTS):
        for name, *_ in reversed(FIXTURE_TABLES):
            c.x(f"DROP TABLE IF EXISTS {name}")
        create_schema(c)
        c.x("BEGIN")
        seed(c)
        c.x("COMMIT")
        one_test(c, i)
    out.append(Strat("recreate schema", c.stmts - base, c.changes, c.commits, 0,
                     "everything"))
    c.close()

    # truncate — keep the schema, empty the tables, reseed.
    c = Counted(os.path.join(tmp, "s_truncate.db"))
    create_schema(c)
    base = c.stmts
    for i in range(N_TESTS):
        c.x("BEGIN")
        for name, *_ in reversed(FIXTURE_TABLES):
            c.x(f"DELETE FROM {name}")
        seed(c)
        c.x("COMMIT")
        one_test(c, i)
    out.append(Strat("truncate + reseed", c.stmts - base, c.changes, c.commits, 0,
                     "committed rows"))
    c.close()

    # rollback — seed once, wrap each test in a transaction, undo it.
    c = Counted(os.path.join(tmp, "s_rollback.db"))
    create_schema(c)
    c.x("BEGIN")
    seed(c)
    c.x("COMMIT")
    b_s, b_r, b_c = c.stmts, c.changes, c.commits
    for i in range(N_TESTS):
        c.x("BEGIN")
        one_test(c, i)
        c.x("ROLLBACK")
    out.append(Strat("transaction rollback", c.stmts - b_s, c.changes - b_r,
                     c.commits - b_c, 0, "uncommitted writes only"))
    # Every test INSERTed one order above the seeded 50. If rollback works, none
    # of them survived.
    leaked = c.one(f"SELECT count(*) FROM orders WHERE id > {FIXTURE_ROWS}")
    c.close()

    # template — one seeded file, byte-copied per test.
    tpl = os.path.join(tmp, "template.db")
    c = Counted(tpl)
    create_schema(c)
    c.x("BEGIN")
    seed(c)
    c.x("COMMIT")
    tpl_bytes = os.path.getsize(tpl)
    c.close()
    copy_path = os.path.join(tmp, "s_template.db")
    ts = tr = tc = 0
    for i in range(N_TESTS):
        with open(tpl, "rb") as src, open(copy_path, "wb") as dst:
            dst.write(src.read())
        cc = Counted(copy_path)
        one_test(cc, i)
        ts, tr, tc = ts + cc.stmts, tr + cc.changes, tc + cc.commits
        cc.close()
    out.append(Strat("template copy", ts, tr, tc, tpl_bytes * N_TESTS,
                     "everything, incl. schema"))

    print("     strategy               stmts/test   row changes/test   commits"
          "   bytes copied/test")
    for r in out:
        print(f"     {r.name:<22}{r.stmts / N_TESTS:8.1f}   {r.rows / N_TESTS:16.1f}"
              f"   {r.commits:7d}   {r.copied // N_TESTS:14,}")
    print()
    for r in out:
        print(f"     {r.name:<22}isolates {r.isolates}")
    rule()

    rb = out[2]
    for r in (out[0], out[1]):
        print(f"  {r.name:<22}{r.stmts / rb.stmts:6.1f}x the statements and "
              f"{r.rows / rb.rows:6.1f}x the row changes of rollback")
    print(f"  {rb.name:<22}{rb.stmts / N_TESTS:.0f} statements per test, "
          f"{rb.commits} commits all run, 0 bytes copied")
    print()
    print(f"  Rollback re-seeds NOTHING. Truncate and recreate write all "
          f"{FIXTURE_ROWS} fixture")
    print(f"  rows {N_TESTS} times over: {out[1].rows:,} row changes against "
          f"{rb.rows:,}. The template")
    print(f"  strategy does almost no SQL and copies {tpl_bytes:,} bytes per test")
    print("  instead — the direct analogue of PostgreSQL's CREATE DATABASE ...")
    print("  TEMPLATE, whose cost scales with the database, not the fixture.")

    print()
    print("  PROJECTION onto a real PostgreSQL, SQL work only. Assumed constants,")
    print(f"  NOT measured here: one commit with fsync on = {FSYNC_MS:.1f} ms, one")
    print(f"  statement round trip = {STMT_MS:.2f} ms. Substitute your own.")
    print("     strategy               projected SQL time for 200 tests")
    for r in out:
        ms = r.stmts * STMT_MS + r.commits * FSYNC_MS
        print(f"     {r.name:<22}{ms / 1000:9.2f} s"
              f"{'  + the byte copy above' if r.copied else ''}")
    rb_ms = rb.stmts * STMT_MS + rb.commits * FSYNC_MS
    tr_ms = out[1].stmts * STMT_MS + out[1].commits * FSYNC_MS
    rc_ms = out[0].stmts * STMT_MS + out[0].commits * FSYNC_MS
    print(f"  Rollback is {tr_ms / rb_ms:.0f}x cheaper than truncate and "
          f"{rc_ms / rb_ms:.0f}x cheaper than recreate under")
    print("  these constants, and the gap widens with fixture size: rollback's cost")
    print("  does not depend on how big your seed data is, and the others' do.")

    print()
    print("  WHAT EACH ONE CANNOT ISOLATE")
    print("     rollback   anything the code under test COMMITS itself (section 4);")
    print("                sequence values, which PostgreSQL never rolls back;")
    print("                side effects outside the database — files, mail, caches")
    print("     truncate   sequence values unless you say RESTART IDENTITY;")
    print("                schema changes a migration test made")
    print("     template   nothing, if the template is rebuilt when migrations change")
    print("     recreate   nothing — and that is what it costs")
    print(f"  Rollback leaked {leaked} of the {N_TESTS} rows the tests inserted. That "
          "is the")
    print("  strategy working. Section 4 is the same strategy lying.")
    return out


# ===========================================================================
# 4 · THE ROLLBACK LIE
# ===========================================================================

SUITE_SIZE = 200
N_COMMITTERS = 3
ASSERT_AT = (40, 90, 140)
N_SHUFFLES = 400


class ProductRepo:
    """Production code. It owns its transaction, because that is its job."""

    def __init__(self, conn: sqlite3.Connection, honest: bool = False) -> None:
        self.conn = conn
        self.honest = honest

    def create(self, sku: str) -> None:
        self.conn.execute("INSERT INTO products(sku) VALUES(?)", (sku,))
        if self.honest:
            # The test handed us a connection whose commit() is a savepoint
            # release, so "commit" means "publish to my caller" and the outer
            # transaction survives.
            self.conn.execute("RELEASE SAVEPOINT svc")
            self.conn.execute("SAVEPOINT svc")
        else:
            self.conn.execute("COMMIT")     # ends the TEST's transaction too
            self.conn.execute("BEGIN")


def build_suite() -> list[tuple[str, str]]:
    """200 tests. 3 call a repository that commits; 3 assert the table is empty."""
    suite = [(f"test_{i:03d}_ordinary", "plain") for i in range(SUITE_SIZE)]
    # File order puts the committing tests LAST. That is why the suite is green.
    for k in range(N_COMMITTERS):
        i = SUITE_SIZE - 1 - k
        suite[i] = (f"test_{i:03d}_creates_product", "commits")
    for pos in ASSERT_AT:
        suite[pos] = (f"test_{pos:03d}_catalogue_starts_empty", "asserts_empty")
    return suite


def run_suite(path: str, order: Iterable[tuple[str, str]],
              honest: bool) -> tuple[int, int]:
    """Returns (failed tests, rows that survived the rollback)."""
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path, isolation_level=None)
    conn.execute("CREATE TABLE products(id INTEGER PRIMARY KEY, sku TEXT)")
    failed = 0
    for name, kind in order:
        conn.execute("BEGIN")
        if honest:
            conn.execute("SAVEPOINT svc")
        if kind == "commits":
            ProductRepo(conn, honest=honest).create(name)
        elif kind == "asserts_empty":
            if conn.execute("SELECT count(*) FROM products").fetchone()[0] != 0:
                failed += 1
        else:
            conn.execute("SELECT count(*) FROM products")
        try:
            if honest:
                conn.execute("ROLLBACK TO SAVEPOINT svc")
                conn.execute("RELEASE SAVEPOINT svc")
            conn.execute("ROLLBACK")
        except sqlite3.OperationalError:
            pass                      # "no transaction is active" — it committed
    leaked = conn.execute("SELECT count(*) FROM products").fetchone()[0]
    conn.close()
    return failed, leaked


def section4(tmp: str) -> tuple[int, float]:
    banner("4 · THE ROLLBACK LIE")
    print(f"  A {SUITE_SIZE}-test suite, every test wrapped in BEGIN ... ROLLBACK.")
    print(f"  {N_COMMITTERS} exercise a repository whose create() calls commit(), "
          "because in")
    print("  production that method owns its transaction and nobody wrote it wrong.")
    print(f"  {len(ASSERT_AT)} assert the catalogue is empty, at positions "
          f"{', '.join(str(p) for p in ASSERT_AT)}.\n")

    suite = build_suite()
    path = os.path.join(tmp, "leak.db")
    f_ord, l_ord = run_suite(path, suite, honest=False)
    print("  IN FILE ORDER (committing tests last, as they were written):")
    print(f"     failures {f_ord}      rows that survived the rollback {l_ord}")
    print("     Green. Shipped. The rollback did nothing at all for those 3 tests:")
    print("     COMMIT ended the transaction the harness opened, so the ROLLBACK")
    print("     that followed had no transaction left to undo.\n")

    green, fails = 0, []
    rng = random.Random(SEED + 1)
    for _ in range(N_SHUFFLES):
        order = suite[:]
        rng.shuffle(order)
        f, _ = run_suite(path, order, honest=False)
        fails.append(f)
        green += (f == 0)
    detect = 100.0 * (N_SHUFFLES - green) / N_SHUFFLES
    print(f"  SHUFFLED {N_SHUFFLES} TIMES (what pytest-randomly does every run):")
    print(f"     runs that went green ......... {green:4d}/{N_SHUFFLES} "
          f"({100.0 * green / N_SHUFFLES:5.2f}%)")
    print(f"     runs that caught it .......... {N_SHUFFLES - green:4d}/{N_SHUFFLES} "
          f"({detect:5.2f}%)")
    print(f"     mean failing tests when caught {sum(fails) / (N_SHUFFLES - green):.2f}"
          f"      worst run {max(fails)}")
    print(f"     P(three shuffled runs ALL miss it) "
          f"{(1 - detect / 100.0) ** 3 * 100:.2f}%")
    print("     Not rare — CONDITIONAL. In file order it is green 100% of the time,")
    print("     for ever, because file order is one permutation and it happens to")
    print(f"     be a safe one. Shuffling finds it on the first run {detect:.1f}% of")
    print("     the time, for one line of configuration.")

    f_fix, l_fix = run_suite(path, suite, honest=True)
    green_fix = 0
    rng = random.Random(SEED + 1)
    for _ in range(N_SHUFFLES):
        order = suite[:]
        rng.shuffle(order)
        f, _ = run_suite(path, order, honest=True)
        green_fix += (f == 0)
    print()
    print("  THE FIX — give the code under test a connection whose commit() is a")
    print("  SAVEPOINT release, so the outer transaction is still there to undo:")
    print(f"     file order:  failures {f_fix}   rows survived {l_fix}")
    print(f"     shuffled:    {green_fix}/{N_SHUFFLES} runs green "
          f"({100.0 * green_fix / N_SHUFFLES:.2f}%)")
    print("  Same suite, same tests, same three repositories still calling commit().")
    print("  Nothing about the production code changed. The seam moved.")
    return l_ord, detect


# ===========================================================================
# 5 · A LOST UPDATE, DETERMINISTICALLY
# ===========================================================================

DELTA = {1: 10, 2: 5}
EXPECTED = 115
SCHEDULES = ["R1 W1 R2 W2", "R2 W2 R1 W1", "R1 R2 W1 W2",
             "R1 R2 W2 W1", "R2 R1 W1 W2", "R2 R1 W2 W1"]
SERIAL = {"R1 W1 R2 W2", "R2 W2 R1 W1"}


def fresh_account(path: str, bal: int = 100) -> None:
    if os.path.exists(path):
        os.remove(path)
    c = sqlite3.connect(path, isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE acct(id INTEGER PRIMARY KEY, bal INTEGER,"
              " ver INTEGER NOT NULL DEFAULT 0)")
    c.execute("INSERT INTO acct VALUES(1, ?, 0)", (bal,))
    c.close()


def replay(path: str, schedule: str, versioned: bool) -> tuple[int, int]:
    """Drive two connections through one explicit interleaving of R/W steps."""
    fresh_account(path)
    conns = {1: sqlite3.connect(path, isolation_level=None),
             2: sqlite3.connect(path, isolation_level=None)}
    read: dict[int, tuple[int, int]] = {}
    conflicts = 0
    for op in schedule.split():
        who = int(op[1])
        conn = conns[who]
        if op[0] == "R":
            read[who] = conn.execute("SELECT bal, ver FROM acct WHERE id=1").fetchone()
            continue
        bal, ver = read[who]
        if not versioned:
            conn.execute("UPDATE acct SET bal=? WHERE id=1", (bal + DELTA[who],))
            continue
        cur = conn.execute("UPDATE acct SET bal=?, ver=ver+1 WHERE id=1 AND ver=?",
                           (bal + DELTA[who], ver))
        if cur.rowcount == 0:                    # somebody moved it under us
            conflicts += 1
            bal, ver = conn.execute(
                "SELECT bal, ver FROM acct WHERE id=1").fetchone()
            conn.execute("UPDATE acct SET bal=?, ver=ver+1 WHERE id=1 AND ver=?",
                         (bal + DELTA[who], ver))
    final = conns[1].execute("SELECT bal FROM acct WHERE id=1").fetchone()[0]
    for conn in conns.values():
        conn.close()
    return final, conflicts


def section5(tmp: str) -> tuple[int, int]:
    banner("5 · A LOST UPDATE, DETERMINISTICALLY")
    print("  One row, balance 100. T1 adds 10, T2 adds 5, both read-modify-write in")
    print("  the way every ORM writes it. The correct answer is 115, always.")
    print("  Two connections driven step by step from one thread — no threads, no")
    print("  sleeps, no luck. Every legal interleaving, replayed for real:\n")
    path = os.path.join(tmp, "lost.db")

    print("     schedule            naive           version column"
          "              kind")
    lost = 0
    for s in SCHEDULES:
        naive, _ = replay(path, s, versioned=False)
        vers, conf = replay(path, s, versioned=True)
        bad = naive != EXPECTED
        lost += bad
        note = f"{naive} LOST {EXPECTED - naive}" if bad else f"{naive} ok"
        fix = f"{vers} ok, {conf} conflict caught" if conf else f"{vers} ok"
        print(f"     {s:<18}{note:<16}{fix:<28}"
              f"{'serial' if s in SERIAL else 'interleaved'}")
    rule()
    print(f"  {lost} of {len(SCHEDULES)} interleavings lose an update. "
          f"{len(SERIAL)} of {len(SCHEDULES)} are serial, and the serial")
    print("  two are exactly the two a normal test explores — because a normal test")
    print("  runs one transaction, then the next. The test passes. It has proved")
    print(f"  nothing about the {lost} schedules that lose money. With a version")
    print(f"  column, {len(SCHEDULES)}/{len(SCHEDULES)} end at {EXPECTED}: the "
          "UPDATE that finds rowcount 0 knows it")
    print("  was overwritten and retries. Nothing is guessed and nothing sleeps.\n")

    print("  THE SAME THING AT SCALE — 8 workers, 25 increments of +1 each,")
    print("  interleaved round-robin (all read, then all write, 25 times over):")
    naive_final = 0
    for versioned in (False, True):
        fresh_account(path, bal=0)
        ws = [sqlite3.connect(path, isolation_level=None) for _ in range(8)]
        retries = 0
        for _ in range(25):
            snap = [w.execute("SELECT bal, ver FROM acct WHERE id=1").fetchone()
                    for w in ws]
            for w, (bal, ver) in zip(ws, snap):
                if not versioned:
                    w.execute("UPDATE acct SET bal=? WHERE id=1", (bal + 1,))
                    continue
                while True:
                    cur = w.execute("UPDATE acct SET bal=?, ver=ver+1 "
                                    "WHERE id=1 AND ver=?", (bal + 1, ver))
                    if cur.rowcount:
                        break
                    retries += 1
                    bal, ver = w.execute(
                        "SELECT bal, ver FROM acct WHERE id=1").fetchone()
        final = ws[0].execute("SELECT bal FROM acct WHERE id=1").fetchone()[0]
        for w in ws:
            w.close()
        extra = f", {retries} retries" if versioned else ""
        print(f"     {'version column' if versioned else 'naive read-modify-write':<26}"
              f"final balance {final:4d} / 200 expected   (lost {200 - final}{extra})")
        if not versioned:
            naive_final = final
    print("  Serial execution of the identical code gives 200 and a green test.")
    return lost, naive_final


# ===========================================================================
# 6 · MIGRATE FORWARD vs LOAD A DUMP
# ===========================================================================

MIGRATIONS: list[tuple[str, list[str]]] = [
    ("001_initial", [
        "CREATE TABLE customers(id INTEGER PRIMARY KEY, email TEXT NOT NULL)",
        "CREATE TABLE orders(id INTEGER PRIMARY KEY, cid INTEGER NOT NULL,"
        " cents INTEGER NOT NULL, legacy_total INTEGER)"]),
    ("002_order_index", ["CREATE INDEX ix_orders_cid ON orders(cid)"]),
    ("003_order_status", [
        "ALTER TABLE orders ADD COLUMN status TEXT NOT NULL DEFAULT 'new'"]),
    ("004_currency", [
        "ALTER TABLE orders ADD COLUMN currency TEXT",
        # The backfill everyone writes: it touches only the rows the author was
        # thinking about. Everything else is left NULL.
        "UPDATE orders SET currency='USD' WHERE status='paid'"]),
    ("005_discount", [
        "ALTER TABLE orders ADD COLUMN discount_cents INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE orders DROP COLUMN legacy_total"]),
]
DUMPED_AT = 4      # schema.sql was regenerated after migration 004


def columns_of(conn: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]


def section6(tmp: str) -> tuple[int, int, list[str], list[str]]:
    banner("6 · MIGRATE FORWARD vs LOAD A DUMP")
    print("  Two ways to get a schema into a test database. They do not converge.\n")

    # A — the real thing: migrations in order, over rows that already existed.
    a = sqlite3.connect(os.path.join(tmp, "migrated.db"), isolation_level=None)
    a.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)")
    rng = random.Random(SEED + 7)
    for name, steps in MIGRATIONS:
        if name == "004_currency":
            for i in range(1, 401):        # production had 400 orders before 004
                a.execute("INSERT INTO customers(id,email) VALUES(?,?)",
                          (i, f"c{i}@example.com"))
                a.execute("INSERT INTO orders(id,cid,cents,legacy_total)"
                          " VALUES(?,?,?,0)", (i, i, rng.randrange(100, 9000)))
            a.execute("UPDATE orders SET status='paid' WHERE id % 4 = 0")
        for s in steps:
            a.execute(s)
        a.execute("INSERT INTO schema_migrations VALUES(?)", (name,))

    # B — schema.sql, dumped from a developer's machine after 004.
    scratch = sqlite3.connect(":memory:", isolation_level=None)
    scratch.execute("CREATE TABLE schema_migrations(version TEXT PRIMARY KEY)")
    for _, steps in MIGRATIONS[:DUMPED_AT]:
        for s in steps:
            if not s.startswith("UPDATE"):     # a dump carries schema, not data
                scratch.execute(s)
    dump = [r[0] for r in scratch.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL")]
    scratch.close()
    b = sqlite3.connect(os.path.join(tmp, "from_dump.db"), isolation_level=None)
    for line in dump:
        b.execute(line)

    a_cols, b_cols = columns_of(a, "orders"), columns_of(b, "orders")
    only_a = [c for c in a_cols if c not in b_cols]
    only_b = [c for c in b_cols if c not in a_cols]

    print(f"     migrated forward   {len(MIGRATIONS)} migrations applied: "
          f"{', '.join(m.split('_')[0] for m, _ in MIGRATIONS)}")
    print(f"     loaded from dump   schema.sql, regenerated at "
          f"{MIGRATIONS[DUMPED_AT - 1][0].split('_')[0]}\n")
    print(f"     orders columns, migrated  {a_cols}")
    print(f"     orders columns, from dump {b_cols}")
    print(f"     in migrated only  {only_a}")
    print(f"     in dump only      {only_b}")
    print("\n  The dump drifts in BOTH directions at once: it lacks discount_cents,")
    print("  which 005 added, and it still carries legacy_total, which 005 dropped.")
    print("  Nobody is at fault. A dump is a photograph of one machine at one")
    print("  moment and the migrations kept moving. It is not wrong about")
    print("  everything, which is exactly why nobody audits it.")

    q = "SELECT count(*) FROM orders WHERE discount_cents = 0"
    try:
        b_ans: Any = b.execute(q).fetchone()[0]
    except sqlite3.OperationalError as exc:
        b_ans = f"OperationalError: {exc}"
    print(f"\n     {q}")
    print(f"       migrated   {a.execute(q).fetchone()[0]}")
    print(f"       from dump  {b_ans}")

    nulls_a = a.execute("SELECT count(*) FROM orders "
                        "WHERE currency IS NULL").fetchone()[0]
    total_a = a.execute("SELECT count(*) FROM orders").fetchone()[0]
    nulls_b = b.execute("SELECT count(*) FROM orders "
                        "WHERE currency IS NULL").fetchone()[0]
    total_b = b.execute("SELECT count(*) FROM orders").fetchone()[0]
    print("\n  AND THE BUG NEITHER SCHEMA COMPARISON FINDS. Migration 004 backfilled")
    print("  currency for status='paid' rows only. Everything else is still NULL:")
    print(f"     migrated forward   {nulls_a} of {total_a} orders have currency IS NULL")
    print(f"     loaded from dump   {nulls_b} of {total_b} orders have currency IS NULL")
    print("  The dump database is not passing this test. It has no rows to fail it.")
    print("  A schema dump can never exercise a data migration, because a data")
    print("  migration is a function of data the dump does not contain. Every")
    print("  backfill you ship is untested unless the test database was migrated")
    print("  forward over rows that existed before the migration ran.")
    a.close()
    b.close()
    return nulls_a, nulls_b, only_a, only_b


# ===========================================================================
# 7 · MAKING IT FAST WITHOUT MAKING IT A LIE
# ===========================================================================

def section7(tmp: str, strat: list[Strat]) -> tuple[int, int]:
    banner("7 · MAKING IT FAST WITHOUT MAKING IT A LIE")
    print("  PARALLEL WORKERS, ONE SHARED DATABASE (4 workers)")
    shared_db = os.path.join(tmp, "shared.db")
    w0 = sqlite3.connect(shared_db, isolation_level=None)
    w0.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v INTEGER)")
    workers = [sqlite3.connect(shared_db, isolation_level=None, timeout=0.0)
               for _ in range(4)]
    w0.execute("BEGIN IMMEDIATE")
    w0.execute("INSERT INTO t(v) VALUES(1)")
    locked = 0
    for w in workers:
        try:
            w.execute("BEGIN IMMEDIATE")
            w.execute("INSERT INTO t(v) VALUES(2)")
            w.execute("COMMIT")
        except sqlite3.OperationalError:
            locked += 1
    w0.execute("ROLLBACK")
    print(f"     writes refused with 'database is locked'   {locked}/4")
    print("     PostgreSQL would not error here. It would BLOCK — which is worse in")
    print("     a suite: the failure arrives as a timeout minutes later, attributed")
    print("     to whichever test happened to be holding the lock.")

    print("\n  PARALLEL WORKERS, ONE DATABASE EACH (4 workers)")
    locked_iso = 0
    for i in range(4):
        wc = sqlite3.connect(os.path.join(tmp, f"worker_{i}.db"),
                             isolation_level=None)
        wc.execute("CREATE TABLE t(id INTEGER PRIMARY KEY, v INTEGER)")
        try:
            wc.execute("BEGIN IMMEDIATE")
            wc.execute("INSERT INTO t(v) VALUES(1)")
            wc.execute("COMMIT")
        except sqlite3.OperationalError:
            locked_iso += 1
        wc.close()
    for w in workers:
        w.close()
    w0.close()
    print(f"     writes refused                            {locked_iso}/4")
    print("     Parallelism in an integration suite is a DATA problem, not a thread")
    print("     problem. One database per worker and the contention is gone.")

    rb = strat[2]
    print("\n  THE ORDER TO DO IT IN, by what each step removes:")
    print(f"     1. transaction rollback per test   {strat[1].rows - rb.rows:,} row "
          f"changes and {strat[1].commits} commits")
    print("     2. one container started per SUITE, not per test")
    print(f"     3. one database per worker         {locked}/4 lock errors")
    print("     4. fsync off, tmpfs storage        the disk — safe ONLY because")
    print("        losing the entire test database costs you nothing")
    return locked_iso, locked


def main() -> None:
    print("INTEGRATION TESTING AGAINST A REAL DATABASE — Phase 12, Lesson 06")
    print(f"seed={SEED}. The database under test is stdlib sqlite3 "
          f"{sqlite3.sqlite_version}, in a temp dir.")
    print("READ SECTION 1 BEFORE YOU TRUST THAT SENTENCE.")

    with tempfile.TemporaryDirectory() as tmp:
        section1(tmp)
        section2(tmp)
        strat = section3(tmp)
        section4(tmp)
        section5(tmp)
        section6(tmp)
        section7(tmp, strat)

    banner("THE SHAPE OF THE ANSWER")
    print("  Run the engine you deploy, in a container, started once per suite.")
    print("  Migrate it forward over real rows; never load a dump.")
    print("  Isolate with a transaction rollback, and make the code's commit() a")
    print("  savepoint release so the rollback is not a lie.")
    print("  Write at least one test that interleaves two connections on purpose.")
    print("  Everything else in this lesson is an optimisation on top of those four.")


if __name__ == "__main__":
    main()
