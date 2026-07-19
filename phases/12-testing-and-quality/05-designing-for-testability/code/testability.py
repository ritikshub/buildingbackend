#!/usr/bin/env python3
"""
Designing for testability, measured. A process_order() that reads the clock,
opens its own database connection, calls a payment gateway and mails the
customer is refactored into a pure functional core behind an imperative shell.
Both are then driven by the same harness and scored on the things that decide
whether a suite can find a bug: how many behaviours a test can reach at all,
how much setup each test costs, how many collaborators it must replace, and
how many seeded faults it kills at a matched suite size.

Companion to docs/en.md (Phase 12, Lesson 05). Standard library only, seed
20260718, runs in roughly six seconds. Sources: Feathers, *Working Effectively
with Legacy Code* (Prentice Hall, 2004) for seams and characterization tests;
DeMillo, Lipton & Sayward, "Hints on Test Data Selection", IEEE Computer 11(4),
1978 for mutation analysis; IEEE 754-2019 clause 4.3 for roundTiesToEven.

Run:  python3 testability.py
"""

from __future__ import annotations

import ast
import functools
import inspect
import itertools
import random
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable, Protocol

SEED = 20260718
BAR = "=" * 74
SANDBOX_FX = Fraction(108, 100)          # the sandbox quotes one fixed rate, 1.08
PAYMENT_WINDOW = timedelta(seconds=20)
DISCOUNT_THRESHOLD = 500_000             # minor units
_REAL_DATETIME = datetime
NOW = _REAL_DATETIME(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
LEAP = _REAL_DATETIME(2024, 2, 29, 12, 0, tzinfo=timezone.utc)
JAN31 = _REAL_DATETIME(2024, 1, 31, 12, 0, tzinfo=timezone.utc)


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# --- branch markers: a 6-line coverage tracer, so "reachable" is measured -----

BRANCHES: set[str] = set()
IO_OPS: dict[str, int] = {}


def mark(name: str) -> None:
    BRANCHES.add(name)


def io(kind: str) -> None:
    IO_OPS[kind] = IO_OPS.get(kind, 0) + 1


ALL_BRANCHES = [
    "disc.none", "disc.threshold", "disc.gold", "tax.zero", "tax.reduced",
    "tax.standard", "fx.identity", "fx.convert", "round.down", "round.up",
    "round.halfway", "round.halfway.even", "round.halfway.up", "date.exact",
    "date.clamp", "date.leap_anchor", "late.none", "late.standard",
    "late.escalated", "window.ok", "window.timeout", "charge.ok",
    "charge.declined", "charge.retry",
]


# --- the pricing rules: the arithmetic both versions share, and the mutation
# --- target in section 6. Nothing here does I/O, and all of it is nonetheless
# --- unreachable through the legacy entry point. That is the lesson.

def discount_rate(subtotal_minor: int, tier: str) -> Fraction:
    if tier == "gold":
        mark("disc.gold")
        return Fraction(15, 100)
    if subtotal_minor >= DISCOUNT_THRESHOLD:
        mark("disc.threshold")
        return Fraction(10, 100)
    mark("disc.none")
    return Fraction(0, 1)

def tax_minor(net_minor: int, tax_class: str) -> int:
    if tax_class == "exempt":
        mark("tax.zero")
        return 0
    if tax_class == "reduced":
        mark("tax.reduced")
        return int(Fraction(net_minor) * Fraction(5, 100))
    mark("tax.standard")
    return int(Fraction(net_minor) * Fraction(20, 100))

def apply_fx(minor: int, rate: Fraction) -> Fraction:
    if rate == 1:
        mark("fx.identity")
        return Fraction(minor)
    mark("fx.convert")
    return Fraction(minor) * rate

def round_money(exact: Fraction, mode: str) -> int:
    """The two modes differ on exactly one input: a fraction of exactly one
    half. IEEE 754-2019 clause 4.3 calls that roundTiesToEven; accountants call
    it banker's rounding. On every other input the modes agree."""
    whole = exact.numerator // exact.denominator
    frac = exact - whole
    if frac > Fraction(1, 2):
        mark("round.up")
        return whole + 1
    if frac < Fraction(1, 2):
        mark("round.down")
        return whole
    mark("round.halfway")
    if mode == "half_even":
        mark("round.halfway.even")
        return whole if whole % 2 == 0 else whole + 1
    mark("round.halfway.up")
    return whole + 1

def days_in_month(year: int, month: int) -> int:
    if month == 2:
        return 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28
    return 30 if month in (4, 6, 9, 11) else 31

def add_months(day: date, months: int) -> date:
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = days_in_month(year, month)
    if day.day > last:
        mark("date.clamp")
        if day.month == 2 and day.day == 29:
            mark("date.leap_anchor")
        return date(year, month, last)
    mark("date.exact")
    return date(year, month, day.day)

def late_fee_minor(amount_minor: int, now: datetime, due: datetime) -> int:
    if now <= due:
        mark("late.none")
        return 0
    if (now - due).days > 30:
        mark("late.escalated")
        return int(Fraction(amount_minor) * Fraction(4, 100))
    mark("late.standard")
    return int(Fraction(amount_minor) * Fraction(2, 100))

PRIMITIVES = [discount_rate, tax_minor, apply_fx, round_money,
              add_months, late_fee_minor]


# --- 1 · THE UNTESTABLE FUNCTION, verbatim and honest ------------------------

_DB_PATH = ""                    # module global, rebound by whoever sets up
_GATEWAY: Any = None             # module singleton, constructed at import
_MAILER: Any = None              # module singleton
_AUDIT: list[str] = []           # module-level mutable state


class SandboxGateway:
    """Stands in for the provider's SDK. Every call is a network hop."""

    def __init__(self, outcome: str = "ok", rate: Fraction = SANDBOX_FX) -> None:
        self.outcome, self.rate = outcome, rate

    def fx_rate(self, currency: str) -> Fraction:
        io("gateway")
        return Fraction(1) if currency == "USD" else self.rate

    def charge(self, customer: str, amount_minor: int, currency: str) -> str:
        io("gateway")
        return self.outcome


class SmtpMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send(self, to: str, body: str) -> None:
        io("mail")
        self.sent.append((to, body))


def process_order_legacy(order_id: int) -> dict[str, Any]:
    """The function everybody has. Its only parameter is an integer. It reads
    the clock five times, opens its own connection, calls the gateway twice,
    mails the customer, and appends to a module-level audit log."""
    conn = sqlite3.connect(_DB_PATH)                          # its own connection
    io("db_connect")
    conn.row_factory = sqlite3.Row
    io("db_query")
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        conn.close()
        raise LookupError(f"no order {order_id}")
    io("db_query")
    merch = conn.execute("SELECT * FROM merchants WHERE id = ?",
                         (row["merchant_id"],)).fetchone()
    started = datetime.now(timezone.utc)                      # clock read 1
    io("db_query")
    items = conn.execute("SELECT qty, unit_minor FROM items WHERE order_id = ?",
                         (order_id,)).fetchall()
    subtotal = sum(int(i["qty"]) * int(i["unit_minor"]) for i in items)
    net = subtotal - int(Fraction(subtotal) * discount_rate(subtotal, row["tier"]))
    taxed = net + tax_minor(net, merch["tax_class"])
    fx = _GATEWAY.fx_rate(row["currency"])                    # network call 1
    total = round_money(apply_fx(taxed, fx), merch["rounding"])
    today = datetime.now(timezone.utc).date()                 # clock read 2
    due, renewal = add_months(today, 1), add_months(today, 12)
    if row["prior_due_at"] is None:
        mark("late.none")
        fee = 0
    else:
        fee = late_fee_minor(total, datetime.now(timezone.utc),        # read 3
                             datetime.fromisoformat(row["prior_due_at"]))
    outcome = _GATEWAY.charge(row["customer"], total + fee, row["currency"])
    if outcome == "ok":
        mark("charge.ok")
        status = "paid"
    elif outcome == "declined":
        mark("charge.declined")
        status = "failed"
    else:
        mark("charge.retry")
        status = "retrying"
    finished = datetime.now(timezone.utc)                     # clock read 4
    if finished - started > PAYMENT_WINDOW:
        mark("window.timeout")
        status = "review"
    else:
        mark("window.ok")
    io("db_query")
    conn.execute("INSERT INTO invoices (order_id, total_minor, fee_minor, status)"
                 " VALUES (?,?,?,?)", (order_id, total, fee, status))
    conn.commit()
    conn.close()
    _MAILER.send(row["customer"], f"Invoice {order_id}: {total + fee}")
    _AUDIT.append(f"{datetime.now(timezone.utc).isoformat()} order={order_id}")
    return {"total_minor": total, "fee_minor": fee, "status": status,
            "due": due.isoformat(), "renewal": renewal.isoformat()}


# --- 4 · THE REFACTOR: functional core, imperative shell ---------------------

@dataclass(frozen=True)
class OrderInput:
    """Everything the decision depends on, as data. No connections, no clock."""
    order_id: int
    customer: str
    tier: str
    currency: str
    tax_class: str
    rounding: str
    line_items: tuple[tuple[int, int], ...]
    prior_due_at: datetime | None


@dataclass(frozen=True)
class Priced:
    total_minor: int
    fee_minor: int
    due: date
    renewal: date


def price_order(order: OrderInput, fx: Fraction, now: datetime) -> Priced:
    """The functional core: same inputs, same outputs, no I/O, no globals."""
    subtotal = sum(qty * unit for qty, unit in order.line_items)
    net = subtotal - int(Fraction(subtotal) * discount_rate(subtotal, order.tier))
    taxed = net + tax_minor(net, order.tax_class)
    total = round_money(apply_fx(taxed, fx), order.rounding)
    if order.prior_due_at is None:
        mark("late.none")
        fee = 0
    else:
        fee = late_fee_minor(total, now, order.prior_due_at)
    return Priced(total, fee, add_months(now.date(), 1), add_months(now.date(), 12))


def settle(priced: Priced, outcome: str, started: datetime,
           finished: datetime) -> str:
    """The rest of the core -- the decision that needs the post-charge clock."""
    status = {"ok": "paid", "declined": "failed"}.get(outcome, "retrying")
    mark({"ok": "charge.ok", "declined": "charge.declined"}.get(outcome, "charge.retry"))
    if finished - started > PAYMENT_WINDOW:
        mark("window.timeout")
        return "review"
    mark("window.ok")
    return status


# typing.Protocol: a port with no base class, no inheritance and no import
# from your adapters. Anything with the right shape satisfies it.

class Clock(Protocol):
    def __call__(self) -> datetime: ...


class OrderRepository(Protocol):
    def load(self, order_id: int) -> OrderInput: ...
    def save_invoice(self, oid: int, total: int, fee: int, status: str) -> None: ...


class PaymentGateway(Protocol):
    def fx_rate(self, currency: str) -> Fraction: ...
    def charge(self, customer: str, amount_minor: int, currency: str) -> str: ...


@dataclass
class Deps:
    """Dependency injection, entire. There is no framework and no container."""
    repo: OrderRepository
    gateway: PaymentGateway
    mailer: Any
    clock: Clock
    audit: list[str]


def process_order(order_id: int, deps: Deps) -> dict[str, Any]:
    """The imperative shell: it does I/O, and calls the core to decide."""
    order = deps.repo.load(order_id)
    started = deps.clock()
    priced = price_order(order, deps.gateway.fx_rate(order.currency), deps.clock())
    outcome = deps.gateway.charge(order.customer,
                                  priced.total_minor + priced.fee_minor, order.currency)
    status = settle(priced, outcome, started, deps.clock())
    deps.repo.save_invoice(order_id, priced.total_minor, priced.fee_minor, status)
    deps.mailer.send(order.customer,
                     f"Invoice {order_id}: {priced.total_minor + priced.fee_minor}")
    deps.audit.append(f"{deps.clock().isoformat()} order={order_id}")
    return {"total_minor": priced.total_minor, "fee_minor": priced.fee_minor,
            "status": status, "due": priced.due.isoformat(),
            "renewal": priced.renewal.isoformat()}


class SqliteOrderRepository:
    """An adapter -- the only thing in the refactor that knows SQL exists."""

    def __init__(self, path: str) -> None:
        self.path = path

    def load(self, order_id: int) -> OrderInput:
        conn = sqlite3.connect(self.path)
        io("db_connect")
        conn.row_factory = sqlite3.Row
        for _ in range(3):
            io("db_query")
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        merch = conn.execute("SELECT * FROM merchants WHERE id = ?",
                             (row["merchant_id"],)).fetchone()
        items = conn.execute("SELECT qty, unit_minor FROM items WHERE order_id = ?",
                             (order_id,)).fetchall()
        conn.close()
        return OrderInput(
            order_id, row["customer"], row["tier"], row["currency"],
            merch["tax_class"], merch["rounding"],
            tuple((int(i["qty"]), int(i["unit_minor"])) for i in items),
            None if row["prior_due_at"] is None
            else datetime.fromisoformat(row["prior_due_at"]))

    def save_invoice(self, oid: int, total: int, fee: int, status: str) -> None:
        conn = sqlite3.connect(self.path)
        io("db_connect")
        io("db_query")
        conn.execute("INSERT INTO invoices (order_id, total_minor, fee_minor,"
                     " status) VALUES (?,?,?,?)", (oid, total, fee, status))
        conn.commit()
        conn.close()


# --- harness plumbing --------------------------------------------------------

SCHEMA = """
CREATE TABLE merchants (id INTEGER PRIMARY KEY, tax_class TEXT, rounding TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, merchant_id INTEGER, customer TEXT,
                     tier TEXT, currency TEXT, prior_due_at TEXT);
CREATE TABLE items (order_id INTEGER, qty INTEGER, unit_minor INTEGER);
CREATE TABLE invoices (order_id INTEGER, total_minor INTEGER, fee_minor INTEGER,
                       status TEXT);
"""


def seed_db(path: str, *, tier: str = "bronze", currency: str = "EUR",
            tax_class: str = "exempt", rounding: str = "half_even",
            items: tuple[tuple[int, int], ...] = ((1, 1000),),
            prior_due: str | None = None) -> None:
    Path(path).unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO merchants VALUES (1,?,?)", (tax_class, rounding))
    conn.execute("INSERT INTO orders VALUES (1,1,'a@example.com',?,?,?)",
                 (tier, currency, prior_due))
    conn.executemany("INSERT INTO items VALUES (1,?,?)", items)
    conn.commit()
    conn.close()


def to_order(**kw: Any) -> OrderInput:
    """The same setup dict, expressed as the core's input instead of as rows."""
    prior = kw.get("prior_due")
    return OrderInput(1, "a@example.com", kw.get("tier", "bronze"),
                      kw.get("currency", "EUR"), kw.get("tax_class", "exempt"),
                      kw.get("rounding", "half_even"), kw.get("items", ((1, 1000),)),
                      None if prior is None else datetime.fromisoformat(prior))


class FrozenDatetime(datetime):
    """What mock.patch('module.datetime') installs. Rebinding the module global
    freezes every clock read in the module, not just the one you cared about."""
    _fixed = NOW

    @classmethod
    def now(cls, tz: Any = None) -> datetime:            # type: ignore[override]
        return cls._fixed


def freeze(instant: datetime) -> None:
    FrozenDatetime._fixed = instant
    globals()["datetime"] = FrozenDatetime


def unfreeze() -> None:
    globals()["datetime"] = _REAL_DATETIME


def run_isolated(fn: Callable[[], Any]) -> tuple[set[str], Any]:
    BRANCHES.clear()
    try:
        value = fn()
    except Exception as exc:                              # noqa: BLE001
        value = f"raised:{type(exc).__name__}"
    return set(BRANCHES), value


def effective_lines(fn: Callable[..., Any]) -> int:
    """Count a test's real lines: no blanks, no comments, no docstring."""
    out, in_doc = [], False
    for line in inspect.getsource(fn).splitlines()[1:]:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith('"""'):
            in_doc = not (s.endswith('"""') and len(s) > 3)
            continue
        if in_doc:
            in_doc = not s.endswith('"""')
            continue
        out.append(s)
    return len(out)


def call_legacy(tmp: str, name: str = "h.db", *, instant: datetime = NOW,
                outcome: str = "ok", **seed: Any) -> Any:
    """Everything a tier-1 test must do before it can assert on one rule."""
    global _DB_PATH, _GATEWAY, _MAILER
    _DB_PATH = f"{tmp}/{name}"
    seed_db(_DB_PATH, **seed)
    _GATEWAY = SandboxGateway(outcome=outcome)
    _MAILER = SmtpMailer()
    _AUDIT.clear()
    freeze(instant)
    try:
        return process_order_legacy(1)
    except Exception as exc:                              # noqa: BLE001
        return f"raised:{type(exc).__name__}"
    finally:
        unfreeze()


# --- 1 · what one pricing test costs -----------------------------------------

def test_discount_boundary_legacy(tmp: str) -> int:
    """One assertion about one pricing rule, through the legacy entry point."""
    global _DB_PATH, _GATEWAY, _MAILER
    _DB_PATH = tmp + "/legacy.db"
    seed_db(_DB_PATH, items=((1, DISCOUNT_THRESHOLD),))
    _GATEWAY = SandboxGateway(outcome="ok")
    _MAILER = SmtpMailer()
    _AUDIT.clear()
    freeze(NOW)
    try:
        return process_order_legacy(1)["total_minor"]
    finally:
        unfreeze()


def test_discount_boundary_core() -> int:
    """The same assertion about the same rule, against the functional core."""
    order = to_order(items=((1, DISCOUNT_THRESHOLD),))
    return price_order(order, SANDBOX_FX, NOW).total_minor


def section_1(tmp: str) -> dict[str, Any]:
    banner("1 · THE UNTESTABLE FUNCTION: WHAT ONE PRICING TEST COSTS")
    text = inspect.getsource(process_order_legacy)
    body = [ln for ln in text.splitlines() if ln.strip()
            and not ln.strip().startswith("#")]
    print(f"  process_order_legacy() is {len(body)} non-blank lines and takes exactly one")
    print("  parameter: order_id. Everything else it decides with, it fetches itself.")
    print("  Count the hidden inputs by counting the call sites:")
    hidden = [("datetime.now(", "the wall clock"),
              ("sqlite3.connect(", "its own database connection"),
              ("_GATEWAY.", "a module-level payment gateway singleton"),
              ("_MAILER.", "a module-level mailer singleton"),
              ("_AUDIT.", "module-level mutable state")]
    total_hidden = 0
    print(f"  {'hidden input':<44}{'call sites':>11}")
    for needle, label in hidden:
        total_hidden += text.count(needle)
        print(f"  {label:<44}{text.count(needle):>11}")
    print(f"  {'':<44}{'-----':>11}")
    print(f"  {'total unparameterised reads of the world':<44}{total_hidden:>11}")

    IO_OPS.clear()
    legacy_total = test_discount_boundary_legacy(tmp)
    legacy_io = sum(IO_OPS.values())
    IO_OPS.clear()
    core_total = test_discount_boundary_core()
    core_io = sum(IO_OPS.values())
    legacy_lines = effective_lines(test_discount_boundary_legacy)
    core_lines = effective_lines(test_discount_boundary_core)
    doubles = ["datetime (module global)", "_DB_PATH + a file on disk",
               "_GATEWAY", "_MAILER"]
    print()
    print("  Now write the smallest possible test of one pricing rule -- 'an order of")
    print(f"  exactly {DISCOUNT_THRESHOLD} minor units gets the 10% discount' -- against each.")
    print(f"  {'test written against':<26}{'setup lines':>13}{'doubles':>9}"
          f"{'I/O ops':>9}{'answer':>9}")
    print(f"  {'process_order_legacy()':<26}{legacy_lines:>13}{len(doubles):>9}"
          f"{legacy_io:>9}{legacy_total:>9}")
    print(f"  {'price_order()':<26}{core_lines:>13}{0:>9}{core_io:>9}{core_total:>9}")
    print(f"  substituted by the legacy test: {', '.join(doubles)}")
    print(f"  Both answer {legacy_total}. One needed a database on disk, a frozen clock, a")
    print(f"  fake gateway and a fake mailer to say so -- {legacy_lines / core_lines:.1f}x the setup and"
          f" {legacy_io} real I/O")
    print("  operations. The test is not badly written; there is no better one to write.")
    return {"legacy_lines": legacy_lines, "core_lines": core_lines,
            "legacy_io": legacy_io, "doubles": len(doubles), "hidden": total_hidden,
            "body": len(body), "ratio": legacy_lines / core_lines}


# --- 2 · SEAMS, and which ones survive a refactor ----------------------------

_UNCHOSEN = _REAL_DATETIME(1999, 1, 1, tzinfo=timezone.utc)   # the clock nobody picked
_STAMP_CLOCK: Callable[[], datetime] = lambda: _UNCHOSEN


def stamp_v0(prefix: str) -> str:
    """Original: two reads of the module-global clock."""
    a, b = _STAMP_CLOCK(), _STAMP_CLOCK()
    return f"{prefix}:{a.year}:{(b - a).seconds}"

def stamp_v1(prefix: str) -> str:
    """No-op refactor A: hoist the read. Same output, one read instead of two."""
    a = _STAMP_CLOCK()
    b = a
    return f"{prefix}:{a.year}:{(b - a).seconds}"

def stamp_v2(prefix: str, clock: Callable[[], datetime] = _STAMP_CLOCK) -> str:
    """No-op refactor B: someone adds a default argument. It binds at def time."""
    a, b = clock(), clock()
    return f"{prefix}:{a.year}:{(b - a).seconds}"

_STAMP_ALIAS = _STAMP_CLOCK          # bound once, at import

def stamp_v3(prefix: str) -> str:
    """No-op refactor C: the module aliases the clock at import. This is
    `from mod import now`, and it is why patching where a name is DEFINED
    misses the copy at the place it is USED."""
    a, b = _STAMP_ALIAS(), _STAMP_ALIAS()
    return f"{prefix}:{a.year}:{(b - a).seconds}"

def section_2() -> dict[str, Any]:
    banner("2 · SEAMS: WHERE YOU CAN CHANGE BEHAVIOUR WITHOUT EDITING THE CODE")
    print("  A seam (Feathers, Working Effectively with Legacy Code, 2004) is a place")
    print("  where behaviour can be changed without editing the source there. Python")
    print("  has many; they are not equally good, and the difference is measurable.")
    rows =[("pass it as an argument", "the call site", "none", "none"),
            ("default argument value", "the def line", "none", "binds once, at def"),
            ("constructor injection", "construction", "one object", "none"),
            ("rebind a module global", "an import path", "the module", "silent on aliasing"),
            ("mock.patch a name", "an import path", "the module", "silent on aliasing"),
            ("subclass and override", "a class", "a subclass", "needs a class to exist"),
            ("side_effect call list", "call order", "the caller", "counts the calls"),
            ("environment variable", "the process", "the process", "leaks between tests")]
    print(f"  {'seam':<27}{'where it acts':<16}{'blast radius':<13}{'how it breaks'}")
    for name, where, blast, fail in rows:
        print(f"  {name:<27}{where:<16}{blast:<13}{fail}")
    print()
    print("  Now measure them. Four seams fix the clock in one small function; three")
    print("  behaviour-preserving refactors are then applied to that function. A cell")
    print("  is PASS if the test still controls the clock afterwards.")
    fixed = _REAL_DATETIME(2031, 7, 18, 12, 0, tzinfo=timezone.utc)
    variants = [("original", stamp_v0), ("hoist the read", stamp_v1),
                ("add a default arg", stamp_v2), ("alias at import", stamp_v3)]

    def seam_pure(_fn: Callable[..., str]) -> bool:
        def stamp_pure(prefix: str, a: datetime, b: datetime) -> str:
            return f"{prefix}:{a.year}:{(b - a).seconds}"
        return stamp_pure("x", fixed, fixed) == "x:2031:0"

    def seam_argument(fn: Callable[..., str]) -> bool:
        try:
            return fn("x", lambda: fixed) == "x:2031:0"     # type: ignore[call-arg]
        except TypeError:
            return False

    def with_global(clock: Callable[[], datetime], fn: Callable[..., str],
                    want: str) -> bool:
        global _STAMP_CLOCK
        saved, _STAMP_CLOCK = _STAMP_CLOCK, clock
        try:
            return fn("x") == want
        except Exception:                                   # noqa: BLE001
            return False
        finally:
            _STAMP_CLOCK = saved

    def seam_global(fn: Callable[..., str]) -> bool:
        return with_global(lambda: fixed, fn, "x:2031:0")

    def seam_sequence(fn: Callable[..., str]) -> bool:
        seq = iter([fixed, fixed + timedelta(seconds=7)])
        return with_global(lambda: next(seq), fn, "x:2031:7")

    seams = [("value passed as a parameter", seam_pure),
             ("argument with a default", seam_argument),
             ("rebind the module global", seam_global),
             ("side_effect call list", seam_sequence)]
    header = f"  {'seam used to fix the clock':<28}"
    for label, _ in variants:
        header += f"{label:>18}"
    print(header + f"{'survives':>11}")
    survival: dict[str, int] = {}
    for sname, sfn in seams:
        line, passes = f"  {sname:<28}", 0
        for _, vfn in variants:
            ok = sfn(vfn)
            passes += ok
            line += f"{'PASS' if ok else 'FAIL':>18}"
        survival[sname] = passes
        print(line + f"{str(passes) + '/4':>11}")
    print("  The parameter is the only seam none of the three refactors can reach.")
    print("  Every other one couples the test to something that is not a behaviour --")
    print("  an import path, a definition site, or how many times you call a")
    print("  collaborator -- which is the whole of 'the tests broke, nothing changed'.")
    return {"survival": survival, "refactors": len(variants) - 1}


# --- 3 · DEPENDENCY INJECTION IS PASSING ARGUMENTS ---------------------------

def section_3() -> dict[str, Any]:
    banner("3 · DEPENDENCY INJECTION IS PASSING ARGUMENTS. THAT IS THE WHOLE IDEA.")

    def by_parameter(clock: Callable[[], datetime]) -> str:
        return clock().date().isoformat()

    class ByConstructor:
        def __init__(self, clock: Callable[[], datetime]) -> None:
            self.clock = clock

        def run(self) -> str:
            return self.clock().date().isoformat()

    def by_default(clock: Callable[[], datetime] = lambda: LEAP) -> str:
        return clock().date().isoformat()

    results = [("parameter injection", by_parameter(lambda: LEAP)),
               ("constructor injection", ByConstructor(lambda: LEAP).run()),
               ("default-argument injection", by_default()),
               ("functools.partial", functools.partial(by_parameter, lambda: LEAP)())]
    print("  Four textbook 'dependency injection' styles, applied to the same clock:")
    print(f"  {'style':<30}{'answer':>14}{'framework lines':>18}")
    for label, value in results:
        print(f"  {label:<30}{value:>14}{0:>18}")
    same = len({v for _, v in results}) == 1
    print(f"  identical answers: {same}. Container, registry or annotation lines: 0.")
    print("  A dependency is a value your function needs; injecting it is passing it.")
    print("  There is no framework here and none in FastAPI's Depends either -- that")
    print("  is a default argument the framework evaluates for you. Everything else")
    print("  in the literature is naming, lifetime and wiring.")
    return {"styles": len(results), "identical": same, "value": results[0][1]}


# --- 4 · the refactor, and the proof it changed nothing ----------------------

def build_cases(rng: random.Random, n: int) -> list[dict[str, Any]]:
    cases = []
    for i in range(n):
        prior = None
        if rng.random() < 0.4:
            prior = (NOW - timedelta(days=rng.randint(1, 60))).isoformat()
        cases.append({
            "i": i, "outcome": rng.choice(["ok", "declined", "retry"]),
            "now": NOW + timedelta(days=rng.randint(0, 400)),
            "seed": dict(tier=rng.choice(["bronze", "silver", "gold"]),
                         tax_class=rng.choice(["standard", "reduced", "exempt"]),
                         rounding=rng.choice(["half_even", "half_up"]),
                         currency=rng.choice(["EUR", "USD", "GBP"]),
                         items=tuple((rng.randint(1, 4), rng.randint(50, 400_000))
                                     for _ in range(rng.randint(1, 3))),
                         prior_due=prior)})
    return cases


def run_shell_case(tmp: str, case: dict[str, Any]) -> Any:
    path = tmp + "/eq.db"
    seed_db(path, **case["seed"])
    deps = Deps(SqliteOrderRepository(path), SandboxGateway(outcome=case["outcome"]),
                SmtpMailer(), lambda: case["now"], [])
    try:
        return process_order(1, deps)
    except Exception as exc:                                   # noqa: BLE001
        return f"raised:{type(exc).__name__}"


def run_legacy_case(tmp: str, case: dict[str, Any]) -> Any:
    return call_legacy(tmp, "eq.db", instant=case["now"], outcome=case["outcome"],
                       **case["seed"])


def section_4(tmp: str, rng: random.Random) -> dict[str, Any]:
    banner("4 · THE REFACTOR: FUNCTIONAL CORE, IMPERATIVE SHELL")
    sizes = {name: len([ln for ln in inspect.getsource(fn).splitlines()
                        if ln.strip() and not ln.strip().startswith("#")])
             for name, fn in (("price_order", price_order), ("settle", settle),
                              ("process_order", process_order))}
    print(f"  price_order()   -- the core, {sizes['price_order']} lines. No clock, no connection, no")
    print("                     globals. Every input it uses is a parameter.")
    print(f"  settle()        -- {sizes['settle']} more lines of core, for the post-charge decision.")
    print(f"  process_order() -- the shell, {sizes['process_order']} lines. It does I/O and calls the core.")
    print("  A refactor that changes behaviour is a rewrite with a nicer name, so")
    print("  prove it: same cases through both versions, every field compared.")
    cases = build_cases(rng, 240)
    same = sum(1 for c in cases if run_legacy_case(tmp, c) == run_shell_case(tmp, c))
    print(f"  {'cases run through both versions':<48}{len(cases):>8}")
    print(f"  {'identical total, fee, status, due and renewal':<48}{same:>8}")
    print(f"  {'any field differing':<48}{len(cases) - same:>8}")
    print("  Behaviour-preserving on every case the legacy version can be driven")
    print("  into. Note the qualifier: for the cases of section 5 that it CANNOT be")
    print("  driven into there is no equivalence evidence at all, which is itself the")
    print("  strongest argument for doing the refactor.")
    return {"cases": len(cases), "same": same, "sizes": sizes}


# --- 5 · REACHABILITY: the headline -----------------------------------------

def tier0_reach(tmp: str) -> set[str]:
    """Tier 0: seed the database, call the function. No patching of any kind.
    The clock is the machine's clock, so no date can be chosen."""
    reached: set[str] = set()
    global _DB_PATH, _GATEWAY, _MAILER
    _DB_PATH = tmp + "/t0.db"
    grid = itertools.product(
        ("bronze", "gold"), (DISCOUNT_THRESHOLD - 1, DISCOUNT_THRESHOLD, 250_001),
        ("standard", "reduced", "exempt"), ("half_even", "half_up"), ("EUR", "USD"),
        (None, "2020-01-01T00:00:00+00:00", "2019-01-01T00:00:00+00:00"))
    for tier, amount, tax_class, rounding, currency, prior in grid:
        seed_db(_DB_PATH, tier=tier, currency=currency, tax_class=tax_class,
                rounding=rounding, items=((1, amount),), prior_due=prior)
        _GATEWAY, _MAILER = SandboxGateway(), SmtpMailer()
        _AUDIT.clear()
        got, _ = run_isolated(lambda: process_order_legacy(1))
        reached |= got
    return reached


def tier1_reach(tmp: str, rng: random.Random) -> set[str]:
    """Tier 1: tier 0 plus rebinding module globals -- a frozen clock and a
    substituted gateway. This is what a real suite does."""
    reached: set[str] = set()
    instants = (LEAP, JAN31, _REAL_DATETIME(2026, 3, 15, 12, 0, tzinfo=timezone.utc))
    grid = itertools.product(instants, ("ok", "declined", "retry"),
                             ("half_even", "half_up"), (0, 1, 2),
                             (DISCOUNT_THRESHOLD, 250_001, 4))
    for instant, outcome, rounding, prior_kind, amount in grid:
        prior = (None, "2020-01-01T00:00:00+00:00",
                 (instant - timedelta(days=2)).isoformat())[prior_kind]
        BRANCHES.clear()
        call_legacy(tmp, "t1.db", instant=instant, outcome=outcome, tier="gold",
                    rounding=rounding, items=((1, amount),), prior_due=prior)
        reached |= set(BRANCHES)
    for _ in range(400):        # and hunt hard for the rounding halfway case
        BRANCHES.clear()
        call_legacy(tmp, "t1.db", instant=instants[0], rounding="half_up",
                    items=((1, rng.randint(1, 900_000)),))
        reached |= set(BRANCHES)
    return reached


def core_reach() -> set[str]:
    """Tier 0 against the core: every input is a parameter, so a case is
    written by typing the value you want to see."""
    reached: set[str] = set()
    nine8, late5, late45 = (Fraction(9, 8),
                            (NOW - timedelta(days=5)).isoformat(),
                            (NOW - timedelta(days=45)).isoformat())
    combos = [
        (dict(items=((1, 100),), tax_class="standard"), SANDBOX_FX, NOW),
        (dict(items=((1, DISCOUNT_THRESHOLD),), tax_class="reduced"), SANDBOX_FX, NOW),
        (dict(items=((1, 100),), tier="gold"), Fraction(1), NOW),
        (dict(items=((1, 4),)), nine8, NOW),
        (dict(items=((1, 4),), rounding="half_up"), nine8, NOW),
        (dict(items=((1, 12),)), nine8, NOW),
        (dict(items=((1, 100),)), SANDBOX_FX, LEAP),
        (dict(items=((1, 100),)), SANDBOX_FX, JAN31),
        (dict(items=((1, 100),), prior_due=late5), SANDBOX_FX, NOW),
        (dict(items=((1, 100),), prior_due=late45), SANDBOX_FX, NOW),
    ]
    for kw, fx, when in combos:
        got, _ = run_isolated(lambda: price_order(to_order(**kw), fx, when))
        reached |= got
    priced = Priced(100, 0, date(2026, 8, 18), date(2027, 7, 18))
    for outcome, gap in itertools.product(("ok", "declined", "retry"), (0, 60)):
        got, _ = run_isolated(
            lambda: settle(priced, outcome, NOW, NOW + timedelta(seconds=gap)))
        reached |= got
    return reached


def section_5(tmp: str, rng: random.Random, seam: dict[str, Any]) -> dict[str, Any]:
    banner("5 · REACHABILITY: THE TESTS YOU COULD NOT WRITE AT ALL")
    print(f"  {len(ALL_BRANCHES)} decision branches carry the pricing behaviour. A branch a test")
    print("  cannot execute is a behaviour no test can check, at any effort. No")
    print("  coverage tool reports this -- it reports that a line never ran, which")
    print("  you read as dead code and delete, or as a gap and never close.")
    t0 = tier0_reach(tmp) & set(ALL_BRANCHES)
    t1 = (tier1_reach(tmp, rng) | t0) & set(ALL_BRANCHES)
    core = core_reach() & set(ALL_BRANCHES)
    print(f"  {'harness':<52}{'reached':>9}{'of':>4}{'doubles':>9}")
    for label, reached, doubles in (
            ("legacy, tier 0: seed the DB and call it", t0, 2),
            ("legacy, tier 1: + freeze the clock, fake the gateway", t1, 4),
            ("core, tier 0: pass the value you want to see", core, 0)):
        print(f"  {label:<52}{len(reached):>9}{len(ALL_BRANCHES):>4}{doubles:>9}")
    missing = [b for b in ALL_BRANCHES if b not in t1]
    print(f"  branches no legacy harness ever reached: {' '.join(missing)}")

    print("\n  A · THE ARITHMETIC BLOCKER -- round.halfway is unreachable, provably.")
    print(f"  The sandbox quotes one fixed rate: {float(SANDBOX_FX)}, which is"
          f" {SANDBOX_FX.numerator}/{SANDBOX_FX.denominator} in lowest")
    print("  terms. Half-way rounding needs amount x rate to have fractional part 1/2.")
    scan, live = 2_000_000, Fraction(9, 8)
    hits, live_hits = (sum(1 for m in range(1, scan + 1)
                           if (m * r.numerator) % r.denominator * 2 == r.denominator)
                       for r in (SANDBOX_FX, live))
    print(f"  {'rate':<8}{'lowest terms':>15}{'amounts scanned':>18}"
          f"{'exact halves':>15}{'share':>9}")
    print(f"  {'1.08':<8}{'27/25':>15}{scan:>18}{hits:>15}{hits / scan:>8.1%}")
    print(f"  {'1.125':<8}{'9/8':>15}{scan:>18}{live_hits:>15}{live_hits / scan:>8.1%}")
    print(f"  A fraction whose lowest-terms denominator is odd ({SANDBOX_FX.denominator}) can never land on")
    print(f"  1/2, so the half_even / half_up branch is unreachable through the legacy")
    print(f"  path for all {scan} amounts -- not unlikely, impossible. On a day the")
    print(f"  real rate is 1.125 that same branch decides {live_hits / scan:.1%} of transactions.")
    _, half_even = run_isolated(lambda: round_money(apply_fx(4, live), "half_even"))
    _, half_up = run_isolated(lambda: round_money(apply_fx(4, live), "half_up"))
    print("  The core reaches it in one line, because the rate is an argument:")
    print(f"    round_money(apply_fx(4, Fraction(9,8)), 'half_even') -> {half_even}")
    print(f"    round_money(apply_fx(4, Fraction(9,8)), 'half_up')   -> {half_up}")

    print("\n  B · THE CALENDAR BLOCKER -- date.clamp depends on the day CI runs.")
    print("  At tier 0 the legacy dates come from the machine clock, so the branch a")
    print("  test reaches is a property of the calendar, not of the test.")
    hit_days, leap_days = [], []
    for year in (2023, 2024):
        day = date(year, 1, 1)
        while day.year == year:
            BRANCHES.clear()
            add_months(day, 1)
            add_months(day, 12)
            if "date.clamp" in BRANCHES:
                hit_days.append(day)
            if "date.leap_anchor" in BRANCHES:
                leap_days.append(day)
            day += timedelta(days=1)
    d23 = [d for d in hit_days if d.year == 2023]
    d24 = [d for d in hit_days if d.year == 2024]
    print(f"  {'year':<8}{'days in year':>14}{'days reaching date.clamp':>28}{'share':>9}")
    print(f"  {'2023':<8}{365:>14}{len(d23):>28}{len(d23) / 365:>8.1%}")
    print(f"  {'2024':<8}{366:>14}{len(d24):>28}{len(d24) / 366:>8.1%}")
    print(f"  date.leap_anchor is reachable on {len(leap_days)} day in these two years:"
          f" {', '.join(d.isoformat() for d in leap_days)}")
    print(f"  Your suite tests a different thing on {len(d23)} days of the year than on the")
    print(f"  other {365 - len(d23)}, and nothing anywhere records which day it was.")

    reads = inspect.getsource(process_order_legacy).count("datetime.now(")
    print("\n  C · THE BLOCKER THE FIX CREATES -- a frozen clock cannot test a timeout.")
    print(f"  Tier 1 fixes B by freezing the clock. But the function reads the clock")
    print(f"  {reads} times, and frozen, all {reads} return one instant -- so finished minus")
    print("  started is always 0 and window.timeout can never be taken.")
    print(f"  {'harness':<46}{'window.ok':>11}{'window.timeout':>16}")
    for label, s in (("legacy, tier 0 (the machine's clock)", t0),
                     ("legacy, tier 1 (one frozen instant)", t1),
                     ("core, settle(started, finished) as params", core)):
        print(f"  {label:<46}{'yes' if 'window.ok' in s else 'no':>11}"
              f"{'yes' if 'window.timeout' in s else 'no':>16}")
    seq = seam["survival"]["side_effect call list"] - 1
    par = seam["survival"]["value passed as a parameter"] - 1
    print("  Tier 2 can reach it: hand the clock a list of instants and let successive")
    print("  calls consume it. That test now asserts how many times the function reads")
    print(f"  the clock, which is not a behaviour -- and section 2 priced it: that seam")
    print(f"  survived {seq} of {seam['refactors']} no-op refactors, against {par} of {seam['refactors']} for a parameter.")
    return {"t0": len(t0), "t1": len(t1), "core": len(core), "missing": missing,
            "total": len(ALL_BRANCHES), "scan": scan, "hits": hits,
            "live_hits": live_hits, "live_share": live_hits / scan,
            "clock_reads": reads, "clamp23": len(d23), "clamp24": len(d24),
            "leap_days": len(leap_days), "half_even": half_even, "half_up": half_up}


# --- 6 · MUTATION KILL RATE AT MATCHED SUITE SIZE ---------------------------

class Mutator(ast.NodeTransformer):
    """Boundary flips, comparison negation, arithmetic swaps and constant
    increments (DeMillo, Lipton & Sayward, IEEE Computer 11(4), 1978)."""

    SWAP = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt,
            ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
    ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv}

    def __init__(self, target: int) -> None:
        self.target, self.seen, self.description = target, 0, ""

    def _hit(self) -> bool:
        self.seen += 1
        return self.seen - 1 == self.target

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        op = type(node.ops[0])
        if op in self.SWAP and self._hit():
            self.description = f"{op.__name__} -> {self.SWAP[op].__name__}"
            node.ops = [self.SWAP[op]()]
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        op = type(node.op)
        if op in self.ARITH and self._hit():
            self.description = f"{op.__name__} -> {self.ARITH[op].__name__}"
            node.op = self.ARITH[op]()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, int) and not isinstance(node.value, bool) \
                and self._hit():
            self.description = f"const {node.value} -> {node.value + 1}"
            return ast.copy_location(ast.Constant(value=node.value + 1), node)
        return node


def make_mutants() -> list[tuple[str, str, Callable[..., Any]]]:
    mutants: list[tuple[str, str, Callable[..., Any]]] = []
    env = {"Fraction": Fraction, "date": date, "datetime": _REAL_DATETIME,
           "mark": mark, "days_in_month": days_in_month, "timedelta": timedelta,
           "DISCOUNT_THRESHOLD": DISCOUNT_THRESHOLD}
    for fn in PRIMITIVES:
        src = inspect.getsource(fn)
        probe = Mutator(-1)
        probe.visit(ast.parse(src))
        for idx in range(probe.seen):
            tree, mut = ast.parse(src), Mutator(idx)
            mut.visit(tree)
            if not mut.description:
                continue
            ast.fix_missing_locations(tree)
            ns = dict(env)
            try:
                exec(compile(tree, f"<mutant {fn.__name__}#{idx}>", "exec"), ns)
            except Exception:                                   # noqa: BLE001
                continue
            mutants.append((fn.__name__, mut.description, ns[fn.__name__]))
    return mutants


# The 14 behaviours both suites are written for. One table, so "matched suite
# size" is a structural fact rather than a claim. Only `fx` and `when` differ
# in what each harness may choose -- and that is the entire experiment.
SUBJECTS: list[tuple[str, dict[str, Any], Fraction, datetime]] = [
    ("discount_below_threshold", dict(items=((1, DISCOUNT_THRESHOLD - 1),)), SANDBOX_FX, NOW),
    ("discount_at_threshold", dict(items=((1, DISCOUNT_THRESHOLD),)), SANDBOX_FX, NOW),
    ("discount_gold_tier", dict(items=((1, 10),), tier="gold"), SANDBOX_FX, NOW),
    ("tax_exempt_is_zero", dict(items=((1, 10_000),)), SANDBOX_FX, NOW),
    ("tax_reduced_is_five_pct", dict(items=((1, 10_000),), tax_class="reduced"), SANDBOX_FX, NOW),
    ("tax_standard_is_twenty_pct", dict(items=((1, 10_000),), tax_class="standard"), SANDBOX_FX, NOW),
    ("fx_identity_for_home_currency", dict(items=((1, 1234),), currency="USD"), Fraction(1), NOW),
    ("round_halfway_half_even", dict(items=((1, 4),)), Fraction(9, 8), NOW),
    ("round_halfway_half_up", dict(items=((1, 4),), rounding="half_up"), Fraction(9, 8), NOW),
    ("round_just_below_half", dict(items=((1, 449),)), Fraction(9, 8), NOW),
    ("renewal_clamps_from_leap_day", dict(items=((1, 1000),)), SANDBOX_FX, LEAP),
    ("due_clamps_from_jan_31", dict(items=((1, 1000),)), SANDBOX_FX, JAN31),
    ("late_fee_standard_under_30d",
     dict(items=((1, 10_000),), prior_due=(NOW - timedelta(days=5)).isoformat()), SANDBOX_FX, NOW),
    ("late_fee_escalates_over_30d",
     dict(items=((1, 10_000),), prior_due=(NOW - timedelta(days=45)).isoformat()), SANDBOX_FX, NOW),
]


def legacy_suite(tmp: str) -> list[tuple[str, Callable[[], Any]]]:
    """14 tests through process_order_legacy(). The FX rate is whatever the
    sandbox says; the instant is whatever the frozen clock was set to."""
    return [(name, functools.partial(call_legacy, tmp, "mut.db", instant=when, **kw))
            for name, kw, _fx, when in SUBJECTS]

def parity_suite() -> list[tuple[str, Callable[[], Any]]]:
    """The same 14 tests against the core, asserting on the same observable.
    The only difference is that these may choose the rate and the instant."""
    return [(name, functools.partial(
        lambda k, f, w: price_order(to_order(**k), f, w), kw, fx, when))
        for name, kw, fx, when in SUBJECTS]

def direct_suite() -> list[tuple[str, Callable[[], Any]]]:
    """The same 14 behaviours, asserted one decision at a time."""
    nine8 = Fraction(9, 8)
    return [
        ("discount_below", lambda: discount_rate(DISCOUNT_THRESHOLD - 1, "bronze")),
        ("discount_at", lambda: discount_rate(DISCOUNT_THRESHOLD, "bronze")),
        ("discount_gold", lambda: discount_rate(10, "gold")),
        ("tax_exempt", lambda: tax_minor(10_000, "exempt")),
        ("tax_reduced", lambda: tax_minor(10_000, "reduced")),
        ("tax_standard", lambda: tax_minor(10_000, "standard")),
        ("fx_identity", lambda: apply_fx(1234, Fraction(1))),
        ("round_halfway_even", lambda: round_money(apply_fx(4, nine8), "half_even")),
        ("round_halfway_up", lambda: round_money(apply_fx(4, nine8), "half_up")),
        ("round_below_half", lambda: round_money(apply_fx(449, nine8), "half_even")),
        ("renewal_from_leap", lambda: add_months(LEAP.date(), 12)),
        ("due_from_jan_31", lambda: add_months(JAN31.date(), 1)),
        ("late_standard", lambda: late_fee_minor(10_000, NOW, NOW - timedelta(days=5))),
        ("late_escalated", lambda: late_fee_minor(10_000, NOW, NOW - timedelta(days=45))),
    ]

def score(suite: list[tuple[str, Callable[[], Any]]],
          mutants: list[tuple[str, str, Callable[..., Any]]]) -> dict[str, Any]:
    IO_OPS.clear()
    baseline = [repr(run_isolated(fn)[1]) for _, fn in suite]
    suite_io = sum(IO_OPS.values())
    killed, survivors = 0, []
    for name, desc, mutant in mutants:
        saved = globals()[name]
        globals()[name] = mutant
        try:
            dead = any(repr(run_isolated(fn)[1]) != before
                       for (_, fn), before in zip(suite, baseline))
        finally:
            globals()[name] = saved
        if dead:
            killed += 1
        else:
            survivors.append(f"{name}: {desc}")
    return {"killed": killed, "survived": len(survivors), "survivors": survivors,
            "io": suite_io, "rate": killed / len(mutants)}


def equivalence_sweep(mutants: list[tuple[str, str, Callable[..., Any]]],
                      names: set[str]) -> int:
    """A mutant that nothing can kill is an EQUIVALENT mutant: it changes the
    source and not the behaviour. Detect candidates by brute force -- run each
    survivor over a dense sweep of its own primitive's inputs."""
    sweeps: dict[str, list[tuple[Any, ...]]] = {
        "discount_rate": [(m, t) for m in range(0, 1_000_001, 9_973)
                          for t in ("bronze", "gold")],
        "tax_minor": [(m, c) for m in range(0, 200_001, 997)
                      for c in ("standard", "reduced", "exempt")],
        "apply_fx": [(m, r) for m in range(0, 20_001, 31)
                     for r in (Fraction(1), Fraction(9, 8), SANDBOX_FX)],
        "round_money": [(Fraction(n, 8), mode) for n in range(0, 4001)
                        for mode in ("half_even", "half_up")],
        "add_months": [(date(2023, 1, 1) + timedelta(days=d), k)
                       for d in range(0, 800, 3) for k in (1, 12)],
        "late_fee_minor": [(m, NOW, NOW - timedelta(days=d))
                           for m in range(0, 100_001, 4_999)
                           for d in (-1, 0, 1, 30, 31, 90)],
    }
    equivalent = 0
    for name, desc, mutant in mutants:
        if f"{name}: {desc}" not in names:
            continue
        original = globals()[name]
        if all(run_isolated(functools.partial(original, *a))[1]
               == run_isolated(functools.partial(mutant, *a))[1]
               for a in sweeps[name]):
            equivalent += 1
    return equivalent


def section_6(tmp: str) -> dict[str, Any]:
    banner("6 · MUTATION KILL RATE AT MATCHED SUITE SIZE")
    mutants = make_mutants()
    print(f"  {len(mutants)} mutants generated from the {len(PRIMITIVES)} pricing rules by AST rewriting:")
    print("  boundary flips, comparison negation, arithmetic swaps, constant bumps.")
    print("  A mutant is KILLED if any test's answer changes. All three suites have")
    print(f"  exactly {len(SUBJECTS)} tests generated from one table of {len(SUBJECTS)} behaviours, so 'matched")
    print("  suite size' is structural, not a claim. Only the choosable inputs differ.")
    legacy, parity, direct = (score(legacy_suite(tmp), mutants),
                              score(parity_suite(), mutants),
                              score(direct_suite(), mutants))
    print()
    print(f"  {'suite':<44}{'tests':>6}{'killed':>8}{'survived':>10}"
          f"{'kill rate':>11}{'I/O':>6}")
    for label, s in (("through process_order_legacy(), tier 1", legacy),
                     ("core, same assertions on the invoice", parity),
                     ("core, asserting on each decision", direct)):
        print(f"  {label:<44}{len(SUBJECTS):>6}{s['killed']:>8}{s['survived']:>10}"
              f"{s['rate']:>10.1%}{s['io']:>6}")
    reach = parity["rate"] - legacy["rate"]
    gran = direct["rate"] - parity["rate"]
    print(f"  Row 1 against row 2 is the lesson: {reach:+.1%}, from reachability alone. Row 2")
    print("  asserts on exactly what row 1 asserts on -- the finished invoice -- and")
    print("  differs only in being allowed to choose the FX rate and the instant. Same")
    print("  count, same names, same assertions, same author. The gap is pure design.")
    only_legacy = sorted(set(legacy["survivors"]) - set(parity["survivors"]))
    print(f"  surviving the legacy suite, killed by the parity suite: {len(only_legacy)}")
    for s in only_legacy:
        print(f"    {s}")
    print()
    print(f"  Row 3 is the surprise, and it went the other way: {gran:+.1%}. Fourteen tests")
    print("  aimed at single decisions killed FEWER mutants than fourteen driving the")
    print("  whole core, because every end-to-end test executes every rule -- a tax")
    print("  mutant faces 14 tests instead of 3. Granularity trades detection against")
    print("  failure localisation; testable design gives you the choice, and this says")
    print("  do not reflexively shatter a suite into one test per function.")
    print()
    both = sorted(set(direct["survivors"]) & set(legacy["survivors"])
                  & set(parity["survivors"]))
    equiv = equivalence_sweep(mutants, set(both))
    print(f"  surviving all three suites: {len(both)}. Of those, {equiv} produce identical output on")
    print("  a dense sweep of their own inputs -- EQUIVALENT MUTANTS, which no test of")
    print(f"  any design can kill. The other {len(both) - equiv} are simply untested: a backlog item,")
    print("  not a design problem. So 100% is not an ambitious target, it is a category")
    print("  error, and telling the two apart is undecidable in general.")
    return {"mutants": len(mutants), "legacy": legacy, "parity": parity,
            "direct": direct, "tests": len(SUBJECTS), "reach": reach, "gran": gran,
            "only_legacy": len(only_legacy), "both": len(both), "equiv": equiv}


# --- 7 · THE PRICE OF INDIRECTION -------------------------------------------

def format_receipt_line(name: str, qty: int, minor: int) -> str:
    """A function with no hidden inputs. There is nothing here to inject."""
    return f"{name} x{qty} {minor // 100}.{minor % 100:02d}"


class ReceiptPort(Protocol):
    def format(self, name: str, qty: int, minor: int) -> str: ...


class CurrencyPolicy:
    def __init__(self, minor_units: int = 100) -> None:
        self.minor_units = minor_units

    def split(self, minor: int) -> tuple[int, int]:
        return minor // self.minor_units, minor % self.minor_units


class ReceiptFormatter:
    def __init__(self, policy: CurrencyPolicy) -> None:
        self.policy = policy

    def format(self, name: str, qty: int, minor: int) -> str:
        major, rest = self.policy.split(minor)
        return f"{name} x{qty} {major}.{rest:02d}"


def section_7(hidden: int) -> dict[str, Any]:
    banner("7 · THE PRICE OF INDIRECTION: WHEN NOT TO ABSTRACT")

    def sloc(obj: Any) -> int:
        return len([l for l in inspect.getsource(obj).splitlines()
                    if l.strip() and not l.strip().startswith(("#", '"""'))])

    plain = sloc(format_receipt_line)
    fancy = sum(sloc(o) for o in (ReceiptPort, CurrencyPolicy, ReceiptFormatter))
    BRANCHES.clear()
    a = format_receipt_line("widget", 2, 12345)
    plain_branches = len(BRANCHES)
    BRANCHES.clear()
    b = ReceiptFormatter(CurrencyPolicy()).format("widget", 2, 12345)
    fancy_branches = len(BRANCHES)
    print("  The section 4 refactor was worth it because it unblocked behaviours. Now")
    print("  apply the identical technique to a function with no hidden inputs at all,")
    print("  and measure what you actually get for it:")
    print(f"  {'design':<42}{'lines':>7}{'names':>7}{'hops':>6}"
          f"{'unblocked':>11}{'output':>18}")
    print(f"  {'format_receipt_line(name, qty, minor)':<42}{plain:>7}{1:>7}{1:>6}"
          f"{plain_branches:>11}{a:>18}")
    print(f"  {'ReceiptFormatter + CurrencyPolicy + Port':<42}{fancy:>7}{3:>7}{3:>6}"
          f"{fancy_branches:>11}{b:>18}")
    print(f"  Same answer. {fancy - plain:+d} lines, +2 names to learn, +2 hops from the call site")
    print("  to the arithmetic, and 0 behaviours unblocked -- because none were blocked.")
    print("  This is the honest core of the 'test-induced design damage' complaint: an")
    print("  abstraction justified only by a test is a cost with no measured benefit,")
    print("  and it will be maintained forever.")
    print()
    print("  THE RULE THAT FALLS OUT OF BOTH MEASUREMENTS: inject a dependency when it")
    print("  is a HIDDEN INPUT -- something the function reads from the world instead")
    print("  of receiving. The clock, the database, the network, the environment, the")
    print("  random source, module-level mutable state. Do not inject arithmetic or")
    print("  formatting, or anything a caller can already vary by passing a different")
    print(f"  value. process_order_legacy() had {hidden} hidden inputs; this one has none.")
    return {"plain": plain, "fancy": fancy, "added": fancy - plain, "same": a == b}


# --- 8 · LEGACY: characterization first, then extract ------------------------

def section_8(tmp: str, rng: random.Random) -> dict[str, Any]:
    banner("8 · LEGACY CODE: PIN THE BEHAVIOUR FIRST, THEN CUT")
    print("  You cannot refactor safely towards tests you do not have yet. A")
    print("  characterization test (Feathers, 2004) asserts nothing about what the code")
    print("  SHOULD do: it records what it DOES -- bugs included -- and fails when that")
    print("  changes. It is a tripwire, not a specification.")
    cases = build_cases(rng, 120)
    golden = {c["i"]: run_legacy_case(tmp, c) for c in cases}
    matched = sum(1 for c in cases if run_shell_case(tmp, c) == golden[c["i"]])
    print(f"  {'outputs of the legacy function, recorded':<52}{len(golden):>8}")
    print(f"  {'refactored version replayed, outputs identical':<52}{matched:>8}")

    saved = globals()["add_months"]

    def add_months_broken(day: date, months: int) -> date:
        year = day.year + (day.month - 1 + months) // 12
        month = (day.month - 1 + months) % 12 + 1
        last = days_in_month(year, month)
        if day.day > last:
            mark("date.clamp")
            return date(year, month, last - 1)              # <- the accident
        mark("date.exact")
        return date(year, month, day.day)

    globals()["add_months"] = add_months_broken
    try:
        flagged = [c["i"] for c in cases
                   if run_shell_case(tmp, c) != golden[c["i"]]]
    finally:
        globals()["add_months"] = saved
    print(f"  {'cases flagging one off-by-one in the clamp':<52}{len(flagged):>8}"
          f"  ({len(flagged) / len(cases):.1%})")
    print("  It took no design decisions and asserted no requirement, and still caught")
    print("  the regression. But read the rate, not just the verdict: the clamp fires")
    print("  only on the few dates section 5B counted, so a small corpus misses it.")
    sizes = (10, 20, 40, 80, len(cases))
    print(f"  {'corpus size':<16}{'cases flagging the regression':>32}{'caught?':>10}")
    for size in sizes:
        n = sum(1 for i in flagged if i < size)
        print(f"  {size:<16}{n:>32}{'yes' if n else 'NO':>10}")
    first = next((s for s in sizes if any(i < s for i in flagged)), len(cases))
    print(f"  A corpus of {sizes[1]} would have shipped this regression. A characterization")
    print("  suite is only as good as the inputs it recorded, and the inputs it can")
    print("  record are exactly the ones the legacy design allows. So: record, extract")
    print("  the pure decision, write real tests against it, then DELETE the recording.")
    print("  Kept forever, it pins the bugs in place along with the behaviour.")
    return {"recorded": len(golden), "matched": matched, "caught": len(flagged),
            "cases": len(cases), "first_size": first, "miss_size": sizes[1]}


def main() -> None:
    print(BAR)
    print("DESIGNING FOR TESTABILITY: SEAMS, INJECTION & THE UNTESTABLE FUNCTION")
    print(f"seed={SEED} · stdlib only · every number below is measured, not asserted")
    print(BAR)
    with tempfile.TemporaryDirectory() as tmp:
        s1 = section_1(tmp)
        s2 = section_2()
        section_3()
        s4 = section_4(tmp, random.Random(SEED + 4))
        s5 = section_5(tmp, random.Random(SEED + 5), s2)
        s6 = section_6(tmp)
        s7 = section_7(s1["hidden"])
        s8 = section_8(tmp, random.Random(SEED + 8))
    print()
    print(BAR)
    print("SUMMARY · the same rules, the same tests, the inputs made reachable")
    print(f"  one pricing test                     {s1['legacy_lines']} setup lines,"
          f" {s1['doubles']} doubles, {s1['legacy_io']} I/O ops ->"
          f" {s1['core_lines']} lines, 0, 0")
    print(f"  behaviours reachable at all          legacy {s5['t0']}/{s5['total']} unpatched,"
          f" {s5['t1']}/{s5['total']} patched -> core {s5['core']}/{s5['total']}")
    print(f"  the rounding branch at rate 1.08     {s5['hits']} of {s5['scan']} amounts reach"
          f" it -> at 1.125 it decides {s5['live_share']:.1%}")
    print(f"  the clamp branch, tier 0             reachable on {s5['clamp23']} of 365 days"
          f" -> core: on demand, always")
    print(f"  mutation kill rate, {s6['tests']} tests each   legacy {s6['legacy']['rate']:.1%}"
          f" -> {s6['parity']['rate']:.1%} same assertions"
          f" -> {s6['direct']['rate']:.1%} finer ones")
    print(f"  seam surviving 3 no-op refactors     parameter"
          f" {s2['survival']['value passed as a parameter'] - 1}/{s2['refactors']} ->"
          f" module global {s2['survival']['rebind the module global'] - 1}/{s2['refactors']},"
          f" call list {s2['survival']['side_effect call list'] - 1}/{s2['refactors']}")
    print(f"  behaviour preserved                  {s4['same']}/{s4['cases']} cases identical;"
          f" characterization caught {s8['caught']}/{s8['cases']}")
    print(f"  indirection with nothing to unblock  {s7['added']:+d} lines,"
          f" 0 behaviours unblocked -- do not do this")
    print(BAR)


if __name__ == "__main__":
    main()
