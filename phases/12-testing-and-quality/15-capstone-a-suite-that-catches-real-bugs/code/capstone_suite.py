#!/usr/bin/env python3
"""
A small but complete order service -- a pure pricing core, a sqlite3 repository with
real migrations, HTTP-ish handlers, an asyncio worker over a queue and an outbound
payment client -- carrying 31 seeded bugs from every class Phase 12 covered, plus a
nine-layer test suite run against every bug in isolation. Prints the clean-run
check, the full 31 x 9 detection matrix, marginal value in build order AND under
three other orderings, exact Shapley values over all 512 layer subsets, cost per bug
caught, the bugs that survive all nine layers, mutation scoring, flake-adjusted
trust, and the optimal suite under a 90-second CI budget solved exhaustively.

Companion to docs/en.md (Phase 12, Lesson 15). Standard library only, one seed
(SEED = 20260718), deterministic, self-terminating in a few seconds, no network, no
files outside memory. Sources: Shapley, "A Value for n-Person Games", Contributions
to the Theory of Games II, Annals of Mathematics Studies 28, 1953; DeMillo, Lipton &
Sayward, IEEE Computer 11(4), 1978; Dijkstra, *Notes on Structured Programming*,
EWD249, 1970; Meszaros, *xUnit Test Patterns*, Addison-Wesley, 2007.

Run:  python3 capstone_suite.py
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import itertools
import math
import random
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any, Callable, Iterable, Sequence

SEED = 20260718


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# THE SERVICE UNDER TEST, AND THE 31 BUGS.
#
# Every bug is a real branch in real code, not a row in a table. A layer "detects" a
# bug only by actually failing an assertion against a service that carries it. The
# clean service must pass all nine layers, and section 1 verifies exactly that.

BUGS: list[tuple[str, str, str]] = [
    ("B01", "boundary",      "tier discount uses > instead of >= at the tier floor"),
    ("B02", "boundary",      "coupon expires a day early: today < valid_until"),
    ("B03", "boundary",      "coupon minimum uses > instead of >= on the threshold"),
    ("B04", "boundary",      "tax rounds half-up instead of half-to-even"),
    ("B05", "boundary",      "net total is not clamped at zero when discount exceeds it"),
    ("W01", "wiring",        "handler never passes the coupon down to the pricing core"),
    ("W02", "wiring",        "worker dispatch table has no route for OrderPlacedV2"),
    ("W03", "wiring",        "repository persists subtotal_cents into the total column"),
    ("S01", "schema",        "migration 003 adds currency and skips the backfill"),
    ("S02", "schema",        "idempotency table declared without its UNIQUE constraint"),
    ("S03", "schema",        "total kept in a TEXT column: ordering goes lexicographic"),
    ("S04", "schema",        "CHECK on orders.status dropped: any string is storable"),
    ("C01", "serialization", "response renames total_cents to amount_cents"),
    ("C02", "serialization", "response emits status 'succeeded', widening the enum"),
    ("C03", "serialization", "receipt_url omitted from the response while unsettled"),
    ("C04", "serialization", "total_cents serialized as a string, not an integer"),
    ("C05", "serialization", "total_cents redenominated into DOLLARS, still an integer"),
    ("D01", "duplicate",     "no dedupe: a redelivered event settles twice"),
    ("D02", "duplicate",     "dedupe key is customer_id only, not customer plus order"),
    ("R01", "race",          "payment application is read-modify-write with no CAS"),
    ("R02", "race",          "idempotency check and insert are not one atomic step"),
    ("T01", "timezone",      "renewal date computed from the box's naive local clock"),
    ("T02", "timezone",      "month arithmetic does not clamp: Jan 31 + 1 month raises"),
    ("T03", "timezone",      "coupon expiry compares an instant against local midnight"),
    ("Y01", "retry",         "retry mints a fresh idempotency key, so it charges again"),
    ("Y02", "retry",         "retries unbudgeted: offered load multiplies on a stall"),
    ("L01", "leak",          "repository handle is not released on the error path"),
    ("G01", "grey",          "outbound call has no timeout: the pool fills up"),
    ("G02", "grey",          "no circuit breaker: the backlog outlives the trigger"),
    ("M01", "semantic",      "tax computed on the gross subtotal, not the net"),
    ("N01", "semantic",      "an unknown currency is dropped instead of dead-lettered"),
]
BUG_IDS = [b[0] for b in BUGS]
BUG_CLASS = {b[0]: b[1] for b in BUGS}
BUG_DESC = {b[0]: b[2] for b in BUGS}

CLASS_LINE = {
    "boundary": "an off-by-one on a threshold real data rarely lands on",
    "wiring": "each part is right; the edge between two of them is not",
    "schema": "the rule lives in the database and the database was not asked",
    "serialization": "the wire format moved underneath somebody who reads it",
    "duplicate": "the same message arrives twice and the second one is not free",
    "race": "two correct sequences, interleaved, are not a correct sequence",
    "timezone": "the code asked what time it is and got an untestable answer",
    "retry": "the second attempt is a second side effect",
    "leak": "a resource acquired on a path that never releases it",
    "grey": "the dependency is not down, it is slow, which is worse",
    "semantic": "correctly typed, correctly shaped, and not what was meant",
}


@dataclass(frozen=True)
class Svc:
    """The service configuration. `on(id)` is the only route a bug takes into code."""
    bugs: frozenset[str] = frozenset()

    def on(self, b: str) -> bool:
        return b in self.bugs


# The system under test. The suite never parameterises itself over bugs -- it just
# tests "the service", exactly as a real suite does. The harness rebinds this.
SUT: Svc = Svc()

# ── the pure core: pricing, coupons, money, dates ─────────────────────────────
TIERS: tuple[tuple[int, int], ...] = ((10_000, 500), (50_000, 1000), (100_000, 1500))
TAX_BPS = 875                                   # 8.75%, the rate on the finance spec
STATUS_LITERAL = ("placed", "settled", "failed")
KNOWN_CURRENCIES = ("USD", "EUR")
FIXED_LOCAL_TZ = timezone(timedelta(hours=-5))  # the CI box, in UTC-5


@dataclass(frozen=True)
class Coupon:
    code: str
    min_cents: int
    valid_until: date
    off_cents: int


@dataclass(frozen=True)
class Invoice:
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int


def tier_bps(svc: Svc, subtotal: int) -> int:
    bps = 0
    for floor, b in TIERS:
        hit = subtotal > floor if svc.on("B01") else subtotal >= floor
        if hit:
            bps = b
    return bps


def coupon_off(svc: Svc, subtotal: int, coupon: Coupon | None, today: date) -> int:
    if coupon is None:
        return 0
    ok_date = today < coupon.valid_until if svc.on("B02") else today <= coupon.valid_until
    ok_min = subtotal > coupon.min_cents if svc.on("B03") else subtotal >= coupon.min_cents
    return coupon.off_cents if (ok_date and ok_min) else 0


def round_money(svc: Svc, cents: Decimal) -> int:
    """Half-to-even is the spec. Half-up is the bug. Both are called 'rounding'."""
    if svc.on("B04"):
        return int((cents + Decimal("0.5")).to_integral_value(rounding="ROUND_FLOOR"))
    return int(cents.quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def price_order(svc: Svc, subtotal: int, coupon: Coupon | None, today: date) -> Invoice:
    disc = subtotal * tier_bps(svc, subtotal) // 10_000 + coupon_off(svc, subtotal, coupon, today)
    if not svc.on("B05"):
        disc = min(disc, subtotal)
    net = subtotal - disc
    # The finance spec says tax applies to the DISCOUNTED amount. M01 reads the same
    # paragraph the other way. Both produce a valid, correctly typed invoice.
    base = subtotal if svc.on("M01") else net
    tax = round_money(svc, Decimal(base) * Decimal(TAX_BPS) / Decimal(10_000))
    if disc > 0:
        DISCOUNTED.append(disc)     # instrumentation for section 6, not behaviour
    return Invoice(subtotal, disc, tax, net + tax)


def add_months(svc: Svc, d: date, months: int) -> date:
    """Anniversary arithmetic. T02 forgets that not every month has a 31st."""
    carry, m0 = divmod(d.month - 1 + months, 12)
    y, m = d.year + carry, m0 + 1
    if svc.on("T02"):
        return date(y, m, d.day)
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    last = (nxt - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def renewal_date(svc: Svc, started_at: datetime, months: int, now: datetime) -> date:
    """
    The next renewal at or after `now`. T01 asks the box's local clock what day it
    is; the box is in UTC-5, so its answer flips at 19:00 UTC and CI picks the hour.
    """
    tz = FIXED_LOCAL_TZ if svc.on("T01") else timezone.utc
    start = started_at.astimezone(tz).date()
    today = now.astimezone(tz).date()
    k = months
    while add_months(svc, start, k) <= today:
        k += months
    return add_months(svc, start, k)


def coupon_live_at(svc: Svc, coupon: Coupon, now: datetime) -> bool:
    """T03 compares an instant against local midnight, so the coupon dies early."""
    if svc.on("T03"):
        naive = now.astimezone(FIXED_LOCAL_TZ).replace(tzinfo=None)
        return naive <= datetime(coupon.valid_until.year, coupon.valid_until.month,
                                 coupon.valid_until.day)
    return now.astimezone(timezone.utc).date() <= coupon.valid_until


# ── the repository, over stdlib sqlite3, with real migrations ─────────────────
class Repo:
    """Owns the schema, the migrations, and the handle lifecycle."""

    def __init__(self, svc: Svc) -> None:
        self.svc = svc
        self.conn = sqlite3.connect(":memory:")
        self.conn.isolation_level = None
        self.open_handles = 0          # L01 makes this climb and never come back
        self.stmts = 0
        self.applied: list[str] = []

    def migrate(self, upto: str = "004") -> None:
        s = self.svc
        check = "" if s.on("S04") else " CHECK (status IN ('placed','settled','failed'))"
        steps: list[tuple[str, list[str]]] = [
            ("001", [
                "CREATE TABLE orders ("
                " id INTEGER PRIMARY KEY,"
                " customer_id INTEGER NOT NULL,"
                " subtotal_cents INTEGER NOT NULL,"
                " discount_cents INTEGER NOT NULL,"
                " tax_cents INTEGER NOT NULL,"
                f" total_cents {'TEXT' if s.on('S03') else 'INTEGER'} NOT NULL,"
                " paid_cents INTEGER NOT NULL DEFAULT 0,"
                " version INTEGER NOT NULL DEFAULT 0,"
                " created_at TEXT NOT NULL,"
                f" status TEXT NOT NULL{check})",
            ]),
            ("002", [
                "CREATE TABLE idem (key TEXT NOT NULL, order_id INTEGER NOT NULL"
                + ("" if s.on("S02") else ", UNIQUE(key)") + ")",
            ]),
            ("003", ["ALTER TABLE orders ADD COLUMN currency TEXT"]
                    + ([] if s.on("S01") else
                       ["UPDATE orders SET currency = 'USD' WHERE currency IS NULL"])),
            ("004", ["CREATE INDEX idx_orders_customer ON orders(customer_id, id)"]),
        ]
        for name, sql in steps:
            if name in self.applied or name > upto:
                continue
            for stmt in sql:
                self.conn.execute(stmt)
                self.stmts += 1
            self.applied.append(name)

    # -- handle lifecycle: the only place L01 lives -----------------------------
    def query(self, sql: str, args: Sequence[Any] = ()) -> list[tuple[Any, ...]]:
        self.open_handles += 1
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(args))
            self.stmts += 1
            rows = cur.fetchall()
        except sqlite3.Error:
            if self.svc.on("L01"):
                raise                       # the handle is never given back
            cur.close()
            self.open_handles -= 1
            raise
        cur.close()
        self.open_handles -= 1
        return rows

    def execute(self, sql: str, args: Sequence[Any] = ()) -> int:
        self.open_handles += 1
        cur = self.conn.cursor()
        try:
            cur.execute(sql, tuple(args))
            self.stmts += 1
            n = cur.rowcount
        except sqlite3.Error:
            if self.svc.on("L01"):
                raise
            cur.close()
            self.open_handles -= 1
            raise
        cur.close()
        self.open_handles -= 1
        return n

    # -- operations -------------------------------------------------------------
    def insert_order(self, oid: int, customer: int, inv: Invoice, currency: str,
                     status: str, created_at: str) -> None:
        total = inv.subtotal_cents if self.svc.on("W03") else inv.total_cents
        cols = ("id, customer_id, subtotal_cents, discount_cents, tax_cents,"
                " total_cents, status, created_at")
        vals: list[Any] = [oid, customer, inv.subtotal_cents, inv.discount_cents,
                           inv.tax_cents, str(total) if self.svc.on("S03") else total,
                           status, created_at]
        if "003" in self.applied:
            cols += ", currency"
            vals.append(currency)
        self.execute(f"INSERT INTO orders ({cols}) VALUES ({','.join('?' * len(vals))})", vals)

    def get_order(self, oid: int) -> dict[str, Any] | None:
        cols = ["id", "customer_id", "subtotal_cents", "discount_cents", "tax_cents",
                "total_cents", "paid_cents", "status", "version", "created_at"]
        if "003" in self.applied:
            cols.append("currency")
        rows = self.query(f"SELECT {','.join(cols)} FROM orders WHERE id = ?", [oid])
        return dict(zip(cols, rows[0])) if rows else None

    def list_by_total(self, limit: int) -> list[Any]:
        return [r[0] for r in self.query(
            "SELECT total_cents FROM orders ORDER BY total_cents DESC LIMIT ?", [limit])]

    def claim_idem(self, key: str, oid: int,
                   on_step: Callable[[str], None] = lambda _s: None) -> bool:
        """
        True if this key is ours to process. `on_step` is a scheduling seam: the
        fault-injection layer uses it to interleave a second caller at the decision
        point. R02 splits the check from the act, so the seam matters.
        """
        if self.svc.on("R02"):
            seen = self.query("SELECT 1 FROM idem WHERE key = ?", [key])
            on_step("after-check")
            if seen:
                return False
            self.execute("INSERT INTO idem (key, order_id) VALUES (?,?)", [key, oid])
            return True
        on_step("after-check")
        try:
            self.execute("INSERT INTO idem (key, order_id) VALUES (?,?)", [key, oid])
            return True
        except sqlite3.IntegrityError:
            return False

    def read_paid(self, oid: int) -> tuple[int, int]:
        row = self.query("SELECT paid_cents, version FROM orders WHERE id = ?", [oid])[0]
        return int(row[0]), int(row[1])

    def write_paid(self, oid: int, paid: int, version: int) -> bool:
        """R01 drops the compare-and-set, which is the whole protection."""
        if self.svc.on("R01"):
            self.execute("UPDATE orders SET paid_cents=?, version=version+1 WHERE id=?",
                         [paid, oid])
            return True
        n = self.execute("UPDATE orders SET paid_cents=?, version=? "
                         "WHERE id=? AND version=?", [paid, version + 1, oid, version])
        return n == 1

    def apply_payment(self, oid: int, amount: int) -> None:
        for _ in range(8):
            paid, ver = self.read_paid(oid)
            if self.write_paid(oid, paid + amount, ver):
                return
        raise RuntimeError("contended out")

    def settle(self, oid: int, expected_version: int) -> bool:
        n = self.execute("UPDATE orders SET status='settled', version=version+1 "
                         "WHERE id=? AND version=?", [oid, expected_version])
        return n == 1


# ── the outbound payment client and its gateway ───────────────────────────────
class Gateway:
    """A payment provider. It deduplicates on whatever idempotency key it is given."""

    def __init__(self, fail_first: int = 0) -> None:
        self.charges: list[tuple[str, int, str]] = []
        self.by_key: dict[str, int] = {}
        self.fail_first = fail_first
        self.calls = 0

    def charge(self, key: str, amount_cents: int, currency: str) -> str:
        self.calls += 1
        if key in self.by_key:
            return "duplicate"
        self.by_key[key] = amount_cents
        self.charges.append((key, amount_cents, currency))
        if self.calls <= self.fail_first:
            raise TimeoutError("the gateway timed out after it wrote")
        return "captured"


class PaymentClient:
    """Y01: a retry that mints a new key is a second charge, not a second attempt."""

    def __init__(self, svc: Svc, gw: Gateway, attempts: int = 3) -> None:
        self.svc, self.gw, self.attempts = svc, gw, attempts
        self.attempts_made = 0

    def pay(self, order_id: int, amount_cents: int, currency: str) -> str:
        last: Exception | None = None
        for n in range(self.attempts):
            self.attempts_made += 1
            key = f"ord-{order_id}-try-{n}" if self.svc.on("Y01") else f"ord-{order_id}"
            try:
                return self.gw.charge(key, amount_cents, currency)
            except TimeoutError as exc:
                last = exc
        raise last if last else RuntimeError("no attempt was made")


# ── the HTTP-ish handlers and the wire serializer ─────────────────────────────
def response_schema(svc: Svc) -> dict[str, tuple[type, bool]]:
    """
    What the annotations SAY. A rename or an added enum member is a refactor: the
    annotation moves with the code, so a static checker sees nothing. A changed
    representation does not move the annotation, so a static checker sees it.
    """
    s: dict[str, tuple[type, bool]] = {
        "id": (int, True), "customer_id": (int, True), "currency": (str, True),
        "subtotal_cents": (int, True), "discount_cents": (int, True),
        "tax_cents": (int, True), "total_cents": (int, True),
        "status": (str, True), "receipt_url": (str, True),
    }
    if svc.on("C01"):
        s["amount_cents"] = s.pop("total_cents")
    if svc.on("C03"):
        s["receipt_url"] = (str, False)
    return s


def declared_statuses(svc: Svc) -> tuple[str, ...]:
    return STATUS_LITERAL + (("succeeded",) if svc.on("C02") else ())


def order_to_json(svc: Svc, row: dict[str, Any]) -> dict[str, Any]:
    total = row["total_cents"]
    body: dict[str, Any] = {
        "id": row["id"], "customer_id": row["customer_id"],
        "currency": row.get("currency"),
        "subtotal_cents": row["subtotal_cents"],
        "discount_cents": row["discount_cents"],
        "tax_cents": row["tax_cents"],
        "status": ("succeeded" if (svc.on("C02") and row["status"] == "settled")
                   else row["status"]),
    }
    key = "amount_cents" if svc.on("C01") else "total_cents"
    if svc.on("C05"):
        body[key] = int(total) // 100          # right type, right name, wrong unit
    elif svc.on("C04"):
        body[key] = str(total)
    elif svc.on("S03"):
        body[key] = total                      # whatever the column handed back
    else:
        body[key] = int(total)
    if not (svc.on("C03") and row["status"] != "settled"):
        body["receipt_url"] = f"https://receipts.example/{row['id']}"
    return body


class App:
    """The HTTP layer: validate, price, persist, serialize."""

    def __init__(self, svc: Svc, repo: Repo) -> None:
        self.svc, self.repo, self.next_id = svc, repo, 1

    def post_orders(self, body: dict[str, Any], coupon: Coupon | None,
                    now: datetime) -> tuple[int, dict[str, Any]]:
        passed = None if self.svc.on("W01") else coupon
        if passed is not None and not coupon_live_at(self.svc, passed, now):
            passed = None
        inv = price_order(self.svc, body["subtotal_cents"], passed,
                          now.astimezone(timezone.utc).date())
        oid, self.next_id = self.next_id, self.next_id + 1
        self.repo.insert_order(oid, body["customer_id"], inv, body["currency"],
                               "placed", now.astimezone(timezone.utc).isoformat())
        return 201, order_to_json(self.svc, self.repo.get_order(oid) or {})

    def get_order(self, oid: int) -> tuple[int, dict[str, Any]]:
        row = self.repo.get_order(oid)
        if row is None:
            return 404, {"error": "not_found"}
        return 200, order_to_json(self.svc, row)


# ── the asyncio worker over a queue ───────────────────────────────────────────
@dataclass(frozen=True)
class Event:
    kind: str
    seq: int
    order_id: int
    customer_id: int
    amount_cents: int
    currency: str


class Worker:
    def __init__(self, svc: Svc, repo: Repo, client: PaymentClient) -> None:
        self.svc, self.repo, self.client = svc, repo, client
        self.dlq: list[Event] = []
        self.dropped: list[Event] = []
        self.settled: list[int] = []
        self.routes: dict[str, Callable[[Event], Any]] = {"OrderPlaced": self._on_placed}
        if not svc.on("W02"):
            self.routes["OrderPlacedV2"] = self._on_placed

    async def drain(self, queue: "asyncio.Queue[Event | None]") -> None:
        while True:
            ev = await queue.get()
            if ev is None:
                queue.task_done()
                return
            handler = self.routes.get(ev.kind)
            if handler is None:
                self.dropped.append(ev)
            else:
                await handler(ev)
            queue.task_done()

    async def _on_placed(self, ev: Event) -> None:
        await asyncio.sleep(0)
        if ev.currency not in KNOWN_CURRENCIES:
            if self.svc.on("N01"):
                return                # silently gone: no DLQ, no log, no metric
            self.dlq.append(ev)
            return
        if not self.svc.on("D01"):
            key = (f"cust-{ev.customer_id}" if self.svc.on("D02")
                   else f"cust-{ev.customer_id}-ord-{ev.order_id}")
            if not self.repo.claim_idem(key, ev.order_id):
                return
        try:
            self.client.pay(ev.order_id, ev.amount_cents, ev.currency)
        except TimeoutError:
            self.dlq.append(ev)
            return
        self.settled.append(ev.order_id)


def run_worker(svc: Svc, repo: Repo, client: PaymentClient,
               events: Iterable[Event]) -> Worker:
    async def go() -> Worker:
        q: asyncio.Queue[Event | None] = asyncio.Queue()
        w = Worker(svc, repo, client)
        for e in events:
            q.put_nowait(e)
        q.put_nowait(None)
        await w.drain(q)
        return w
    return asyncio.run(go())


# ── the factory: fresh data per test, no shared seed ──────────────────────────
NOW = datetime(2026, 3, 17, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def make_service() -> tuple[Svc, Repo, App, Gateway, PaymentClient]:
    """Build the whole service against whatever SUT currently is."""
    svc = SUT
    repo = Repo(svc)
    repo.migrate("002")
    gw = Gateway()
    return svc, repo, App(svc, repo), gw, PaymentClient(svc, gw)


def seed_orders(app: App, n: int, now: datetime = NOW, currency: str = "USD") -> list[int]:
    ids = []
    for i in range(n):
        _, body = app.post_orders({"customer_id": 100 + i,
                                   "subtotal_cents": 1_000 * (i + 1),
                                   "currency": currency}, None, now)
        ids.append(body["id"])
    return ids


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# THE NINE LAYERS.
#
# Each check is an ordinary function that raises when it observes something wrong.
# Nothing in this section knows the bug list; each layer is written the way a
# competent engineer writes that layer, from the requirements. That is the only
# thing that makes section 2's matrix a measurement rather than an assertion.

# ── layer 1: types / static analysis ──────────────────────────────────────────
def l1_response_matches_its_declared_shape() -> None:
    svc, repo, app, _, _ = make_service()
    repo.migrate()
    _, body = app.post_orders({"customer_id": 1, "subtotal_cents": 20_000,
                               "currency": "USD"}, None, NOW)
    for name, (typ, required) in sorted(response_schema(svc).items()):
        if name not in body:
            assert not required, f"{name} is declared required and is absent"
            continue
        assert isinstance(body[name], typ), (
            f"{name}: declared {typ.__name__}, got {type(body[name]).__name__}")


def l1_status_is_a_declared_literal() -> None:
    svc, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 1, "subtotal_cents": 5_000, "currency": "USD"},
                    None, NOW)
    repo.settle(1, 0)
    _, body = app.get_order(1)
    assert body["status"] in declared_statuses(svc), body["status"]


def l1_repository_row_types_match_the_columns() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    seed_orders(app, 1)
    row = repo.get_order(1) or {}
    for col in ("id", "customer_id", "subtotal_cents", "discount_cents",
                "tax_cents", "total_cents", "paid_cents", "version"):
        assert isinstance(row[col], int), (
            f"{col} declared int, stored {type(row[col]).__name__}")


def l1_event_payload_types() -> None:
    ev = Event("OrderPlaced", 1, 7, 100, 48_600, "USD")
    for name, typ in (("kind", str), ("seq", int), ("order_id", int),
                      ("customer_id", int), ("amount_cents", int), ("currency", str)):
        assert isinstance(getattr(ev, name), typ), name


def l1_invoice_fields_are_integers() -> None:
    inv = price_order(SUT, 25_000, None, TODAY)
    for f in (inv.subtotal_cents, inv.discount_cents, inv.tax_cents, inv.total_cents):
        assert isinstance(f, int) and not isinstance(f, bool)


# ── layer 2: unit tests over the functional core ──────────────────────────────
def l2_tier_discount_applies_at_the_floor() -> None:
    for subtotal, want in ((9_999, 0), (10_000, 500), (10_001, 500),
                           (49_999, 500), (50_000, 1000),
                           (99_999, 1000), (100_000, 1500)):
        got = tier_bps(SUT, subtotal)
        assert got == want, f"subtotal {subtotal} -> {got} bps, expected {want}"


def l2_coupon_still_applies_on_its_last_valid_day() -> None:
    c = Coupon("SPRING", 0, date(2026, 3, 17), 500)
    assert coupon_off(SUT, 20_000, c, date(2026, 3, 17)) == 500, "expired a day early"
    assert coupon_off(SUT, 20_000, c, date(2026, 3, 18)) == 0


def l2_coupon_below_its_minimum_does_not_apply() -> None:
    c = Coupon("MIN20", 20_000, date(2026, 12, 31), 500)
    assert coupon_off(SUT, 25_000, c, TODAY) == 500
    assert coupon_off(SUT, 15_000, c, TODAY) == 0


def l2_tax_rounds_half_to_even() -> None:
    assert round_money(SUT, Decimal("2.5")) == 2, "2.5 must round to 2, not 3"
    assert round_money(SUT, Decimal("3.5")) == 4
    assert round_money(SUT, Decimal("4.5")) == 4


def l2_total_is_never_negative() -> None:
    c = Coupon("HUGE", 0, date(2026, 12, 31), 90_000)
    inv = price_order(SUT, 1_000, c, TODAY)
    assert inv.total_cents >= 0, f"total came out at {inv.total_cents}"
    assert inv.discount_cents <= inv.subtotal_cents


def l2_price_order_matches_the_hand_checked_invoices() -> None:
    for subtotal, tax, total in ((5_000, 438, 5_438), (8_000, 700, 8_700)):
        inv = price_order(SUT, subtotal, None, TODAY)
        assert (inv.tax_cents, inv.total_cents) == (tax, total), inv


def l2_anniversary_clamps_into_a_short_month() -> None:
    assert add_months(SUT, date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(SUT, date(2026, 3, 31), 1) == date(2026, 4, 30)


def l2_anniversary_of_a_leap_day() -> None:
    assert add_months(SUT, date(2024, 2, 29), 12) == date(2025, 2, 28)


# ── layer 3: fakes governed by one shared contract suite ──────────────────────
class FakeRepo:
    """The in-memory double every team writes for speed. It has no schema."""

    def __init__(self) -> None:
        self.rows: dict[int, dict[str, Any]] = {}
        self.keys: set[str] = set()

    def insert_order(self, oid: int, customer: int, inv: Invoice, currency: str,
                     status: str, created_at: str) -> None:
        self.rows[oid] = {"id": oid, "customer_id": customer,
                          "subtotal_cents": inv.subtotal_cents,
                          "discount_cents": inv.discount_cents,
                          "tax_cents": inv.tax_cents, "total_cents": inv.total_cents,
                          "paid_cents": 0, "status": status, "version": 0,
                          "created_at": created_at, "currency": currency}

    def get_order(self, oid: int) -> dict[str, Any] | None:
        return self.rows.get(oid)

    def list_by_total(self, limit: int) -> list[Any]:
        return sorted((r["total_cents"] for r in self.rows.values()), reverse=True)[:limit]

    def claim_idem(self, key: str, oid: int,
                   on_step: Callable[[str], None] = lambda _s: None) -> bool:
        on_step("after-check")
        if key in self.keys:
            return False
        self.keys.add(key)
        return True


REPO_CONTRACT: list[tuple[str, Callable[[Any], None]]] = []


def _contract(name: str) -> Callable[[Callable[[Any], None]], Callable[[Any], None]]:
    def deco(fn: Callable[[Any], None]) -> Callable[[Any], None]:
        REPO_CONTRACT.append((name, fn))
        return fn
    return deco


@_contract("insert then get returns the total that was persisted")
def _c_roundtrip(repo: Any) -> None:
    inv = price_order(SUT, 20_000, None, TODAY)
    repo.insert_order(9001, 1, inv, "USD", "placed", "2026-03-17T12:00:00+00:00")
    row = repo.get_order(9001)
    assert row is not None and int(row["total_cents"]) == inv.total_cents, row


@_contract("an idempotency key can be claimed exactly once")
def _c_idem_once(repo: Any) -> None:
    assert repo.claim_idem("k-contract", 1) is True
    assert repo.claim_idem("k-contract", 2) is False, "the same key was claimed twice"


@_contract("orders sort by total numerically, not lexicographically")
def _c_sort_numeric(repo: Any) -> None:
    for i, sub in enumerate((90_000, 9_000, 900)):
        repo.insert_order(9100 + i, 2, Invoice(sub, 0, 0, sub), "USD", "placed", "t")
    got = [int(v) for v in repo.list_by_total(3)]
    assert got == sorted(got, reverse=True), got


@_contract("every persisted order comes back with a currency")
def _c_currency_present(repo: Any) -> None:
    inv = price_order(SUT, 3_000, None, TODAY)
    repo.insert_order(9200, 3, inv, "EUR", "placed", "t")
    row = repo.get_order(9200)
    assert row is not None and row.get("currency") is not None, "currency came back NULL"


def _run_contract(repo: Any) -> list[str]:
    fails = []
    for name, fn in REPO_CONTRACT:
        try:
            fn(repo)
        except Exception as exc:                       # noqa: BLE001
            fails.append(f"{name}: {type(exc).__name__} {exc}")
    return fails


def l3_contract_holds_against_the_real_repository() -> None:
    _, repo, _, _, _ = make_service()
    repo.migrate()
    fails = _run_contract(repo)
    assert not fails, " | ".join(fails)


def l3_contract_holds_against_the_fake() -> None:
    fails = _run_contract(FakeRepo())
    assert not fails, " | ".join(fails)


def l3_fake_and_real_agree_on_a_priced_order() -> None:
    svc, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 1, "subtotal_cents": 60_000, "currency": "USD"},
                    None, NOW)
    fake = FakeRepo()
    fake.insert_order(1, 1, price_order(svc, 60_000, None, TODAY), "USD", "placed", "t")
    real_row = repo.get_order(1) or {}
    fake_row = fake.get_order(1) or {}
    assert int(real_row["total_cents"]) == int(fake_row["total_cents"]), (real_row, fake_row)


def l3_gateway_double_is_idempotent_like_the_real_one() -> None:
    gw = Gateway()
    assert gw.charge("k", 100, "USD") == "captured"
    assert gw.charge("k", 100, "USD") == "duplicate"
    assert len(gw.charges) == 1


# ── layer 4: integration against the real database, with factory data ─────────
def l4_post_then_get_round_trips() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    _, created = app.post_orders({"customer_id": 42, "subtotal_cents": 20_000,
                                  "currency": "USD"}, None, NOW)
    status, fetched = app.get_order(created["id"])
    assert status == 200 and fetched == created, (created, fetched)


def l4_migrations_backfill_the_currency_of_existing_rows() -> None:
    _, repo, app, _, _ = make_service()
    seed_orders(app, 4)
    repo.migrate("004")
    missing = repo.query("SELECT COUNT(*) FROM orders WHERE currency IS NULL")[0][0]
    assert missing == 0, f"{missing} of 4 pre-existing orders have a NULL currency"


def l4_totals_order_numerically() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    for sub in (90_000, 9_000, 900):
        app.post_orders({"customer_id": 5, "subtotal_cents": sub, "currency": "USD"},
                        None, NOW)
    got = [int(v) for v in repo.list_by_total(3)]
    assert got == sorted(got, reverse=True), got


def l4_the_database_refuses_a_duplicate_idempotency_key() -> None:
    _, repo, _, _, _ = make_service()
    repo.migrate()
    assert repo.claim_idem("k1", 1) is True
    assert repo.claim_idem("k1", 2) is False, "the database accepted a duplicate key"


def l4_the_schema_refuses_an_unknown_status() -> None:
    _, repo, _, _, _ = make_service()
    repo.migrate()
    try:
        repo.execute("INSERT INTO orders (id, customer_id, subtotal_cents,"
                     " discount_cents, tax_cents, total_cents, status, created_at,"
                     " currency) VALUES (77,1,1,0,0,1,'shipped','t','USD')")
    except sqlite3.IntegrityError:
        return
    raise AssertionError("the schema accepted status='shipped'")


def l4_persisted_total_matches_the_computed_invoice() -> None:
    svc, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 9, "subtotal_cents": 60_000, "currency": "USD"},
                    None, NOW)
    inv = price_order(svc, 60_000, None, TODAY)
    row = repo.get_order(1) or {}
    assert int(row["total_cents"]) == inv.total_cents, (row["total_cents"], inv)


def l4_a_coupon_reaches_the_stored_discount() -> None:
    """8000c sits below the first tier floor, so the coupon is the ONLY discount."""
    _, repo, app, _, _ = make_service()
    repo.migrate()
    c = Coupon("SAVE5", 0, date(2026, 12, 31), 500)
    app.post_orders({"customer_id": 3, "subtotal_cents": 8_000, "currency": "USD"},
                    c, NOW)
    row = repo.get_order(1) or {}
    assert row["discount_cents"] == 500, (
        f"the coupon was lost on the way down: discount {row['discount_cents']}")


def l4_handles_are_balanced_after_a_failed_statement() -> None:
    _, repo, _, _, _ = make_service()
    repo.migrate()
    for _ in range(6):
        try:
            repo.query("SELECT * FROM no_such_table")
        except sqlite3.Error:
            pass
    assert repo.open_handles == 0, f"{repo.open_handles} handles never came back"


# ── layer 5: determinism controls -- controllable clock, seeds, shuffled order ─
def l5_renewal_is_the_same_answer_all_day() -> None:
    started = datetime(2026, 1, 31, 6, 0, tzinfo=timezone.utc)
    seen = {renewal_date(SUT, started, 1,
                         datetime(2026, 2, 28, h, 30, tzinfo=timezone.utc))
            for h in range(24)}
    assert len(seen) == 1, f"the answer depends on the hour CI runs: {sorted(seen)}"


def l5_renewal_uses_the_stored_utc_date() -> None:
    started = datetime(2026, 3, 1, 2, 0, tzinfo=timezone.utc)   # Feb 28 21:00 in UTC-5
    now = datetime(2026, 3, 15, 12, 0, tzinfo=timezone.utc)
    got = renewal_date(SUT, started, 1, now)
    assert got == date(2026, 4, 1), got


def l5_coupon_validity_does_not_depend_on_the_hour() -> None:
    c = Coupon("SPRING", 0, date(2026, 3, 17), 500)
    live = {coupon_live_at(SUT, c, datetime(2026, 3, 17, h, 30, tzinfo=timezone.utc))
            for h in range(24)}
    assert live == {True}, "the coupon's validity changes during its last valid day"


def l5_the_suite_is_order_independent() -> None:
    rng = random.Random(SEED + 5)
    checks = [l4_the_database_refuses_a_duplicate_idempotency_key,
              l4_totals_order_numerically,
              l4_handles_are_balanced_after_a_failed_statement,
              l4_post_then_get_round_trips]
    for _ in range(8):
        order = checks[:]
        rng.shuffle(order)
        for fn in order:
            fn()


def l5_a_controllable_clock_reaches_the_retry_branch() -> None:
    _, _, _, gw, client = make_service()
    gw.fail_first = 1
    client.pay(1, 100, "USD")
    assert client.attempts_made >= 2, "the retry branch was never reached at all"


# ── layer 6: contract tests at the service seam ───────────────────────────────
# A contract recorded once by a downstream consumer against the baseline provider.
# It constrains the four fields that consumer actually reads, and nothing else.
CONSUMER_CONTRACT: dict[str, str] = {
    "total_cents": "integer",
    "currency": "string",
    "status": "enum:placed,settled,failed",
    "receipt_url": "string",
}


def verify_contract(body: dict[str, Any]) -> list[str]:
    problems = []
    for path, rule in sorted(CONSUMER_CONTRACT.items()):
        if path not in body:
            problems.append(f"$.{path}: MISSING from the provider response")
            continue
        val = body[path]
        if rule == "integer" and not (isinstance(val, int) and not isinstance(val, bool)):
            problems.append(f"$.{path}: expected integer, got {type(val).__name__}")
        elif rule == "string" and not isinstance(val, str):
            problems.append(f"$.{path}: expected string, got {type(val).__name__}")
        elif rule.startswith("enum:") and val not in rule[5:].split(","):
            problems.append(f"$.{path}: '{val}' is outside the agreed enum")
    return problems


def l6_provider_satisfies_the_placed_order_contract() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    _, body = app.post_orders({"customer_id": 1, "subtotal_cents": 20_000,
                               "currency": "USD"}, None, NOW)
    problems = verify_contract(body)
    assert not problems, " | ".join(problems)


def l6_provider_satisfies_it_in_the_settled_state() -> None:
    """A provider state: the consumer's example assumed a settled order exists."""
    _, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 1, "subtotal_cents": 20_000, "currency": "USD"},
                    None, NOW)
    repo.settle(1, 0)
    _, body = app.get_order(1)
    problems = verify_contract(body)
    assert not problems, " | ".join(problems)


def l6_the_error_contract_is_unchanged() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    status, body = app.get_order(4242)
    assert status == 404 and body == {"error": "not_found"}, (status, body)


def l6_no_field_the_consumer_reads_changed_representation() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    _, body = app.post_orders({"customer_id": 1, "subtotal_cents": 300,
                               "currency": "USD"}, None, NOW)
    assert "total_cents" in body, "a field the consumer reads was renamed away"
    assert isinstance(body["total_cents"], int) and not isinstance(body["total_cents"], bool)


# ── layer 7: async, duplicate delivery and reordering ─────────────────────────
def _placed(seq: int, oid: int, cust: int, amount: int = 48_600,
            currency: str = "USD", kind: str = "OrderPlaced") -> Event:
    return Event(kind, seq, oid, cust, amount, currency)


def l7_a_redelivered_event_settles_once() -> None:
    svc, repo, _, gw, client = make_service()
    repo.migrate()
    ev = _placed(1, 1, 500)
    w = run_worker(svc, repo, client, [ev, ev, ev])
    assert len(w.settled) == 1, f"one order settled {len(w.settled)} times"
    assert len(gw.charges) == 1, f"{len(gw.charges)} charges for one order"


def l7_two_orders_from_one_customer_both_settle() -> None:
    svc, repo, _, gw, client = make_service()
    repo.migrate()
    w = run_worker(svc, repo, client, [_placed(1, 1, 500), _placed(2, 2, 500)])
    assert len(w.settled) == 2, f"only {len(w.settled)} of 2 orders settled"


def l7_reordered_delivery_preserves_the_invariants() -> None:
    rng = random.Random(SEED + 7)
    evs = [_placed(1, 1, 500), _placed(2, 2, 501), _placed(3, 3, 502)]
    for _ in range(6):
        order = evs[:]
        rng.shuffle(order)
        svc, repo, _, gw, client = make_service()
        repo.migrate()
        w = run_worker(svc, repo, client, order)
        assert len(w.settled) == 3, (len(w.settled), [e.seq for e in order])


def l7_an_unroutable_event_is_dead_lettered_not_dropped() -> None:
    svc, repo, _, _, client = make_service()
    repo.migrate()
    w = run_worker(svc, repo, client, [_placed(1, 1, 500, kind="OrderPlacedV2")])
    assert not w.dropped, f"{len(w.dropped)} events vanished with no route and no DLQ"


def l7_a_retried_payment_does_not_charge_twice() -> None:
    _, repo, _, gw, client = make_service()
    repo.migrate()
    gw.fail_first = 1
    client.pay(1, 48_600, "USD")
    assert len(gw.charges) == 1, f"{len(gw.charges)} charges after one retried payment"


# ── layer 8: property-based tests over the core ───────────────────────────────
def boundary_biased(rng: random.Random) -> int:
    """Uniform random rarely reaches a boundary. Bias toward the ones that exist."""
    pool = [0, 1, 9_999, 10_000, 10_001, 20_000, 49_999, 50_000, 50_001,
            99_999, 100_000, 100_001]
    return rng.choice(pool) if rng.random() < 0.55 else rng.randint(0, 200_000)


def l8_property_total_is_never_negative() -> None:
    rng = random.Random(SEED + 8)
    for _ in range(400):
        sub = boundary_biased(rng)
        off = rng.choice([0, 1, 500, sub, sub + 1, 90_000])
        c = Coupon("P", 0, date(2026, 12, 31), off)
        inv = price_order(SUT, sub, c, TODAY)
        assert inv.total_cents >= 0, (sub, off, inv)


def l8_property_components_reconstruct_the_total() -> None:
    rng = random.Random(SEED + 81)
    for _ in range(400):
        sub = boundary_biased(rng)
        inv = price_order(SUT, sub, None, TODAY)
        assert inv.subtotal_cents - inv.discount_cents + inv.tax_cents == inv.total_cents, inv


def l8_property_the_coupon_minimum_is_inclusive() -> None:
    """A boundary-biased generator lands on `subtotal == min_cents`. Nobody types it."""
    rng = random.Random(SEED + 82)
    hits = 0
    for _ in range(400):
        threshold = boundary_biased(rng)
        sub = rng.choice([threshold, threshold, threshold + 1, threshold - 1,
                          boundary_biased(rng)])
        c = Coupon("P", threshold, date(2026, 12, 31), 500)
        got = coupon_off(SUT, sub, c, TODAY)
        if sub >= threshold:
            hits += 1
            assert got == 500, f"subtotal {sub} vs minimum {threshold} gave {got}"
        else:
            assert got == 0, f"subtotal {sub} vs minimum {threshold} gave {got}"
    assert hits > 0


def l8_property_the_discount_rate_never_decreases() -> None:
    rng = random.Random(SEED + 83)
    for _ in range(300):
        a = boundary_biased(rng)
        b = a + rng.randint(1, 5_000)
        assert tier_bps(SUT, b) >= tier_bps(SUT, a), (a, b)


def l8_property_the_anniversary_is_total_over_a_year() -> None:
    d = date(2026, 1, 1)
    for i in range(365):
        add_months(SUT, d + timedelta(days=i), 1)


def l8_property_applying_two_payments_is_additive() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 1, "subtotal_cents": 5_000, "currency": "USD"},
                    None, NOW)
    repo.apply_payment(1, 2_000)
    repo.apply_payment(1, 3_000)
    assert repo.read_paid(1)[0] == 5_000, repo.read_paid(1)


def l8_property_settling_twice_is_refused() -> None:
    _, repo, app, _, _ = make_service()
    repo.migrate()
    app.post_orders({"customer_id": 1, "subtotal_cents": 5_000, "currency": "USD"},
                    None, NOW)
    assert repo.settle(1, 0) is True
    assert repo.settle(1, 0) is False, "a stale settle was accepted a second time"


# ── layer 9: fault injection against a steady-state hypothesis ────────────────
def simulate(svc: Svc, ticks: int = 44, slow_from: int = 8, slow_to: int = 18,
             factor: float = 6.0) -> tuple[list[float], float, float]:
    """
    A tick model of the worker pool: fixed arrivals, a concurrency limit, a service
    time a fault multiplies, a timeout (unless G01), a retry budget (unless Y02) and
    a breaker (unless G02). No RNG -- the schedule is fixed. Returns the served
    fraction per tick, the peak offered/real load ratio, and the peak backlog.
    """
    arrivals, workers, base = 20.0, 24.0, 1.0
    timeout = math.inf if svc.on("G01") else 2.0
    budget = math.inf if svc.on("Y02") else 0.10
    queue = retry_q = 0.0
    peak_load, peak_queue, breaker = 1.0, 0.0, 0
    served: list[float] = []
    for t in range(ticks):
        svc_time = base * (factor if slow_from <= t < slow_to else 1.0)
        hold = min(svc_time, timeout)
        offered = arrivals + retry_q
        peak_load = max(peak_load, offered / arrivals)
        queue += offered
        peak_queue = max(peak_queue, queue)
        if breaker > 0:
            breaker -= 1
            admitted = min(queue, workers / 0.05)   # failing fast is cheap
            queue -= admitted
            done, failed = 0.0, admitted
        else:
            admitted = min(queue, workers / hold)
            queue -= admitted
            done = admitted if svc_time <= timeout else 0.0
            failed = admitted - done
            if not svc.on("G02") and failed > arrivals * 0.5:
                breaker = 2
        retry_q = failed if budget == math.inf else min(failed, arrivals * budget)
        served.append(min(1.0, done / arrivals))
    return served, peak_load, peak_queue


def l9_the_system_returns_to_steady_state_after_the_fault() -> None:
    served, _, _ = simulate(SUT)
    end = 18
    recovered = next((t for t in range(end, len(served)) if served[t] >= 0.95), None)
    assert recovered is not None and recovered - end <= 5, (
        f"still below steady state {recovered if recovered else 'forever'} ticks "
        f"after the trigger was removed")


def l9_offered_load_does_not_multiply_under_a_stall() -> None:
    _, peak, _ = simulate(SUT)
    assert peak <= 1.5, f"offered load reached {peak:.2f}x real demand"


def l9_the_backlog_stays_bounded() -> None:
    _, _, peak_queue = simulate(SUT)
    assert peak_queue <= 60.0, f"backlog peaked at {peak_queue:.0f} requests"


def l9_the_error_path_does_not_exhaust_the_pool() -> None:
    _, repo, _, _, _ = make_service()
    repo.migrate()
    for _ in range(40):
        try:
            repo.query("SELECT * FROM missing_table")
        except sqlite3.Error:
            pass
    assert repo.open_handles == 0, f"{repo.open_handles} handles held after 40 errors"


def l9_no_interleaving_of_two_payments_loses_one() -> None:
    """Enumerate every legal interleaving of two read-modify-write payments."""
    losses = []
    for pattern in sorted(set(itertools.permutations("AABB"))):
        _, repo, app, _, _ = make_service()
        repo.migrate()
        app.post_orders({"customer_id": 1, "subtotal_cents": 50_000,
                         "currency": "USD"}, None, NOW)
        readings: dict[str, tuple[int, int]] = {}
        retry: list[str] = []
        for step in pattern:
            if step not in readings:
                readings[step] = repo.read_paid(1)
            else:
                paid, ver = readings[step]
                if not repo.write_paid(1, paid + 500, ver):
                    retry.append(step)
        for step in retry:                       # the CAS loser retries, serially
            repo.apply_payment(1, 500)
        if repo.read_paid(1)[0] != 1_000:
            losses.append("".join(pattern))
    assert not losses, f"{len(losses)} of 6 interleavings lost a payment: {losses}"


def l9_two_interleaved_claims_produce_one_winner() -> None:
    """
    Interleave a second claimant exactly at the first one's decision point, using
    the repository's scheduling seam. A serial test can never reach this state.
    """
    _, repo, _, _, _ = make_service()
    repo.migrate()
    results: list[bool] = []
    fired = [False]

    def hook(_step: str) -> None:
        if not fired[0]:
            fired[0] = True
            results.append(repo.claim_idem("race-key", 2))

    results.append(repo.claim_idem("race-key", 1, hook))
    assert sum(1 for r in results if r) == 1, f"{sum(results)} claimants won: {results}"


# ── the layer registry ────────────────────────────────────────────────────────
LAYERS: list[tuple[int, str, str, list[Callable[[], None]]]] = [
    (1, "types", "types / static analysis", [
        l1_response_matches_its_declared_shape, l1_status_is_a_declared_literal,
        l1_repository_row_types_match_the_columns, l1_event_payload_types,
        l1_invoice_fields_are_integers]),
    (2, "unit", "unit tests over the core", [
        l2_tier_discount_applies_at_the_floor,
        l2_coupon_still_applies_on_its_last_valid_day,
        l2_coupon_below_its_minimum_does_not_apply, l2_tax_rounds_half_to_even,
        l2_total_is_never_negative, l2_price_order_matches_the_hand_checked_invoices,
        l2_anniversary_clamps_into_a_short_month, l2_anniversary_of_a_leap_day]),
    (3, "fakes", "fakes + a contract suite", [
        l3_contract_holds_against_the_real_repository,
        l3_contract_holds_against_the_fake,
        l3_fake_and_real_agree_on_a_priced_order,
        l3_gateway_double_is_idempotent_like_the_real_one]),
    (4, "integr", "integration, real database", [
        l4_post_then_get_round_trips,
        l4_migrations_backfill_the_currency_of_existing_rows,
        l4_totals_order_numerically,
        l4_the_database_refuses_a_duplicate_idempotency_key,
        l4_the_schema_refuses_an_unknown_status,
        l4_persisted_total_matches_the_computed_invoice,
        l4_a_coupon_reaches_the_stored_discount,
        l4_handles_are_balanced_after_a_failed_statement]),
    (5, "determ", "determinism controls", [
        l5_renewal_is_the_same_answer_all_day, l5_renewal_uses_the_stored_utc_date,
        l5_coupon_validity_does_not_depend_on_the_hour,
        l5_the_suite_is_order_independent,
        l5_a_controllable_clock_reaches_the_retry_branch]),
    (6, "contract", "contract tests at the seam", [
        l6_provider_satisfies_the_placed_order_contract,
        l6_provider_satisfies_it_in_the_settled_state,
        l6_the_error_contract_is_unchanged,
        l6_no_field_the_consumer_reads_changed_representation]),
    (7, "async", "async, duplicates, reorder", [
        l7_a_redelivered_event_settles_once,
        l7_two_orders_from_one_customer_both_settle,
        l7_reordered_delivery_preserves_the_invariants,
        l7_an_unroutable_event_is_dead_lettered_not_dropped,
        l7_a_retried_payment_does_not_charge_twice]),
    (8, "property", "property-based on the core", [
        l8_property_total_is_never_negative,
        l8_property_components_reconstruct_the_total,
        l8_property_the_coupon_minimum_is_inclusive,
        l8_property_the_discount_rate_never_decreases,
        l8_property_the_anniversary_is_total_over_a_year,
        l8_property_applying_two_payments_is_additive,
        l8_property_settling_twice_is_refused]),
    (9, "fault", "fault injection", [
        l9_the_system_returns_to_steady_state_after_the_fault,
        l9_offered_load_does_not_multiply_under_a_stall,
        l9_the_backlog_stays_bounded,
        l9_the_error_path_does_not_exhaust_the_pool,
        l9_no_interleaving_of_two_payments_loses_one,
        l9_two_interleaved_claims_produce_one_winner]),
]
NL = len(LAYERS)
LAYER_NAME = {n: short for n, short, _, _ in LAYERS}
LAYER_LONG = {n: long for n, _, long, _ in LAYERS}

# The cost model. Check COUNTS and authoring LINES are measured from this file; the
# per-layer constants below are declared, and they are the two numbers to measure in
# your own repo -- Lesson 02 makes the same point about COST and FLAKE.
SETUP_S = {1: 8.0, 2: 0.6, 3: 1.2, 4: 22.0, 5: 1.5, 6: 9.0, 7: 6.0, 8: 3.0, 9: 35.0}
PER_CHECK_S = {1: 0.15, 2: 0.012, 3: 0.09, 4: 1.60, 5: 0.35,
               6: 0.90, 7: 2.10, 8: 3.60, 9: 9.00}
FLAKE = {1: 0.0, 2: 0.00002, 3: 0.00005, 4: 0.00200, 5: 0.00080,
         6: 0.00060, 7: 0.00900, 8: 0.00150, 9: 0.02500}


def run_layer(fns: Sequence[Callable[[], None]], bugs: frozenset[str]) -> list[str]:
    """Run one layer against a service carrying `bugs`. Returns the failing names."""
    global SUT
    saved = SUT
    SUT = Svc(bugs)
    failures = []
    try:
        for fn in fns:
            try:
                fn()
            except Exception as exc:                   # noqa: BLE001
                failures.append(f"{fn.__name__}[{type(exc).__name__}]")
    finally:
        SUT = saved
    return failures


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 -- THE SUITE, RUN CLEAN. A layer that reds on a healthy service is not a
# detector, it is a flake, and every number below depends on this being green.


def section1() -> dict[int, int]:
    banner(1, "THE SERVICE, THE BUGS, AND THE SUITE RUN CLEAN")
    counts = {n: len(fns) for n, _, _, fns in LAYERS}
    by_class: dict[str, int] = {}
    for _, k, _ in BUGS:
        by_class[k] = by_class.get(k, 0) + 1
    print(f"  seed {SEED}; {len(BUGS)} seeded bugs across {len(by_class)} classes; "
          f"{sum(counts.values())} checks across {NL} layers.")
    print("    class            n   what the class actually is")
    for k in sorted(by_class):
        print(f"    {k:<15} {by_class[k]:2d}   {CLASS_LINE[k]}")
    print()
    print("  clean run -- every layer against a service carrying zero bugs:")
    total_fail = 0
    for n, short, _, fns in LAYERS:
        fails = run_layer(fns, frozenset())
        total_fail += len(fails)
        mark = "all green" if not fails else "RED: " + ", ".join(fails)
        print(f"    layer {n} {short:<9} {len(fns):2d} checks   {mark}")
    total = sum(counts.values())
    print(f"  {total - total_fail} of {total} checks green on a healthy service; "
          f"false-positive rate {total_fail / total:.1%}.")
    print("  Every X in the matrix below is therefore a bug being observed, not noise.")
    return counts


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 -- THE 31 x 9 DETECTION MATRIX. One bug at a time, all nine layers,
# every cell a real assertion that really ran.


def build_matrix() -> tuple[dict[str, dict[int, bool]], dict[str, dict[int, list[str]]]]:
    caught: dict[str, dict[int, bool]] = {}
    why: dict[str, dict[int, list[str]]] = {}
    for bug in BUG_IDS:
        caught[bug], why[bug] = {}, {}
        for n, _, _, fns in LAYERS:
            fails = run_layer(fns, frozenset({bug}))
            caught[bug][n] = bool(fails)
            why[bug][n] = fails
    return caught, why


def coverage(caught: dict[str, dict[int, bool]], subset: Iterable[int]) -> int:
    s = list(subset)
    return sum(1 for b in BUG_IDS if any(caught[b][n] for n in s))


def section2(caught: dict[str, dict[int, bool]],
             why: dict[str, dict[int, list[str]]]) -> list[str]:
    banner(2, "THE 31 x 9 DETECTION MATRIX")
    print("  columns are the nine layers in build order; X = at least one check in")
    print("  that layer went red against a service carrying only that bug.")
    print()
    head = ("  bug  class         " + " ".join(str(n) for n in range(1, NL + 1))
            + "   n  the mistake")
    print(head)
    print("  " + "-" * 101)
    for bug, klass, desc in BUGS:
        cells = " ".join("X" if caught[bug][n] else "." for n in range(1, NL + 1))
        hits = sum(caught[bug].values())
        flag = " " if hits else "*"
        print(f"  {bug}  {klass:<13} {cells}  {hits:2d}{flag} {desc[:57]}")
    print("  " + "-" * 99)
    per_layer = [sum(1 for b in BUG_IDS if caught[b][n]) for n in range(1, NL + 1)]
    print("  caught by layer    " + " ".join(str(v) for v in per_layer))
    for n in range(1, NL + 1):
        print(f"    layer {n} {LAYER_NAME[n]:<9} {per_layer[n-1]:2d} of {len(BUGS)} "
              f"({per_layer[n-1]/len(BUGS):5.1%})  {LAYER_LONG[n]}")
    union = coverage(caught, range(1, NL + 1))
    survivors = [b for b in BUG_IDS if not any(caught[b].values())]
    print(f"  union of all nine layers: {union} of {len(BUGS)} ({union/len(BUGS):.1%}). "
          f"{len(survivors)} bugs marked * survive everything.")
    print(f"  sum of the 'caught by layer' column is {sum(per_layer)} against a union of "
          f"{union}: the layers overlap {sum(per_layer)/union:.2f}x.")
    print()
    print(f"  B03 is the boundary nobody types: the unit check probes 25000 against a "
          f"20000")
    print(f"  minimum, which passes either way; only the boundary-biased generator in "
          f"layer 8")
    print(f"  lands on subtotal == min_cents.")
    print()
    print("  a sample of what actually went red (bug -> the first failing check):")
    for bug in ("B01", "S01", "C04", "D01", "R01", "G02"):
        first = next((f"L{n} {why[bug][n][0]}" for n in range(1, NL + 1) if why[bug][n]),
                     "nothing")
        print(f"    {bug}  {first}")
    return survivors


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 & 4 -- MARGINAL VALUE, AND THE FACT THAT IT MOVES WHEN YOU REORDER.


def marginal(caught: dict[str, dict[int, bool]],
             order: Sequence[int]) -> list[tuple[int, int, int]]:
    have: set[str] = set()
    out = []
    for n in order:
        alone = {b for b in BUG_IDS if caught[b][n]}
        new = alone - have
        out.append((n, len(alone), len(new)))
        have |= alone
    return out


def section3(caught: dict[str, dict[int, bool]]) -> list[tuple[int, int, int]]:
    banner(3, "MARGINAL VALUE IN BUILD ORDER")
    rows = marginal(caught, list(range(1, NL + 1)))
    print(f"  {'layer':<28}{'alone':>6}{'marginal':>11}{'cumulative':>13}{'of 31':>8}")
    cum = 0
    for n, alone, new in rows:
        cum += new
        print(f"  {n} {LAYER_LONG[n]:<26} {alone:5d} {new:10d} {cum:12d} {cum/len(BUGS):7.1%}")
    print(f"  The 'alone' column sums to {sum(r[1] for r in rows)} and the marginal column to "
          f"{cum}. Only the")
    print("  marginal column is ever an argument for building the next layer.")
    zero = [n for n, _, new in rows if new == 0]
    if zero:
        print(f"  layers with zero marginal value in this order: "
              f"{', '.join(f'{n} ({LAYER_LONG[n]})' for n in zero)}")
    return rows


def shapley(caught: dict[str, dict[int, bool]]) -> dict[int, float]:
    """Exact Shapley value of each layer over the coverage set function."""
    layers = list(range(1, NL + 1))
    cov: dict[frozenset[int], int] = {}
    for r in range(NL + 1):
        for sub in itertools.combinations(layers, r):
            cov[frozenset(sub)] = coverage(caught, sub)
    out = {}
    for n in layers:
        rest = [m for m in layers if m != n]
        total = 0.0
        for r in range(NL):
            w = math.factorial(r) * math.factorial(NL - r - 1) / math.factorial(NL)
            for sub in itertools.combinations(rest, r):
                s = frozenset(sub)
                total += w * (cov[s | {n}] - cov[s])
        out[n] = total
    return out


def section4(caught: dict[str, dict[int, bool]],
             build_rows: list[tuple[int, int, int]]) -> dict[int, float]:
    banner(4, "MARGINAL VALUE IS PATH-DEPENDENT")
    orders: dict[str, list[int]] = {
        "build 1..9": list(range(1, NL + 1)),
        "reversed 9..1": list(range(NL, 0, -1)),
        "outside-in": [9, 7, 4, 6, 3, 5, 2, 8, 1],
        "cheapest-first": [2, 3, 5, 1, 6, 7, 8, 4, 9],
    }
    marg = {lab: {n: new for n, _, new in marginal(caught, order)}
            for lab, order in orders.items()}
    print("  the SAME nine layers and the SAME 31 bugs, built in four different orders:")
    print(f"  {'layer':<28}" + "".join(f"{lab:>16}" for lab in orders))
    for n in range(1, NL + 1):
        cells = "".join(f"{marg[lab][n]:>16d}" for lab in orders)
        print(f"  {n} {LAYER_LONG[n]:<26}{cells}")
    print("  " + "-" * 91)
    print(f"  {'total':<28}" + "".join(
        f"{sum(marg[lab].values()):>16d}" for lab in orders))
    spread = {n: (min(marg[l][n] for l in orders), max(marg[l][n] for l in orders))
              for n in range(1, NL + 1)}
    ranked = sorted(spread, key=lambda n: spread[n][0] - spread[n][1])
    print(f"  Every column sums to {coverage(caught, range(1, NL+1))}: the union is a "
          f"property of the layers, not of the order.")
    for n in ranked[:3]:
        lo, hi = spread[n]
        print(f"  layer {n} {LAYER_NAME[n]:<9} worth {lo} in one order, {hi} in "
              f"another — a {hi-lo}-bug swing")
    print()
    print(f"  the order-free answer: exact Shapley values over all {2**NL} subsets.")
    shap = shapley(caught)
    bm = {n: new for n, _, new in build_rows}
    print(f"  rank  {'layer':<28}{'Shapley':>8}{'build-order marginal':>23}{'delta':>9}")
    for i, (n, v) in enumerate(sorted(shap.items(), key=lambda kv: -kv[1]), 1):
        print(f"  {i:4d}  {n} {LAYER_LONG[n]:<26}{v:8.2f}{bm[n]:23d}{bm[n]-v:+9.2f}")
    print(f"  Shapley values sum to {sum(shap.values()):.2f} = the union, by construction.")
    order_by_shap = [n for n, _ in sorted(shap.items(), key=lambda kv: -kv[1])]
    order_by_marg = [n for n, _ in sorted(bm.items(), key=lambda kv: -kv[1])]
    agree = sum(1 for a, b in zip(order_by_shap, order_by_marg) if a == b)
    print(f"  The Shapley ranking and the build-order ranking agree on {agree} of {NL} "
          f"positions.")
    return shap


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 -- WHAT EACH LAYER COSTS, AND WHAT A BUG COSTS AT EACH LAYER.


def layer_seconds(n: int, counts: dict[int, int]) -> float:
    return SETUP_S[n] + PER_CHECK_S[n] * counts[n]


def authoring_lines() -> dict[int, int]:
    out = {}
    for n, _, _, fns in LAYERS:
        out[n] = sum(len(inspect.getsource(fn).rstrip().split("\n")) for fn in fns)
    return out


def section5(caught: dict[str, dict[int, bool]], counts: dict[int, int],
             build_rows: list[tuple[int, int, int]]) -> dict[int, int]:
    banner(5, "COST PER BUG CAUGHT")
    lines = authoring_lines()
    print("  check counts and authoring lines are measured from this file; the CI")
    print("  seconds per layer come from the declared cost model at the top.")
    print()
    print(f"  {'layer':<28}{'checks':>7}{'lines':>7}{'CI s':>8}{'marginal':>11}"
          f"{'s/bug':>9}{'lines/bug':>11}")
    bm = {n: new for n, _, new in build_rows}
    tot_s = 0.0
    tot_lines = 0
    for n in range(1, NL + 1):
        s = layer_seconds(n, counts)
        tot_s += s
        tot_lines += lines[n]
        per = f"{s/bm[n]:8.2f}" if bm[n] else "       -"
        perl = f"{lines[n]/bm[n]:10.1f}" if bm[n] else "         -"
        print(f"  {n} {LAYER_LONG[n]:<26} {counts[n]:6d} {lines[n]:6d} {s:7.2f} "
              f"{bm[n]:10d} {per} {perl}")
    total_caught = coverage(caught, range(1, NL + 1))
    print("  " + "-" * 88)
    print(f"  {'whole suite':<28}{sum(counts.values()):7d}{tot_lines:7d}{tot_s:8.2f}"
          f"{total_caught:11d}{tot_s/total_caught:9.2f}"
          f"{tot_lines/total_caught:11.1f}")
    ranked = sorted((n for n in range(1, NL + 1) if bm[n]),
                    key=lambda n: layer_seconds(n, counts) / bm[n])
    print("  cheapest marginal bug first:")
    for i in range(0, len(ranked), 4):
        print("    " + "  ".join(
            f"{n}:{LAYER_NAME[n]} {layer_seconds(n, counts)/bm[n]:.2f} s/bug"
            for n in ranked[i:i + 4]))
    cheap = ranked[0]
    cs = layer_seconds(cheap, counts) / bm[cheap]
    ratios = ", ".join(f"layer {n} {layer_seconds(n, counts)/bm[n]/cs:.0f}x"
                       for n in ranked[-2:])
    print(f"  per marginal bug, against layer {cheap} as 1x: {ratios}.")
    print(f"  layers 2 + 5 together: {layer_seconds(2, counts) + layer_seconds(5, counts):.2f} s "
          f"for {len(set(b for b in BUG_IDS if caught[b][2] or caught[b][5]))} bugs.")
    dead = [n for n in range(1, NL + 1) if not bm[n]]
    if dead:
        print(f"  layers that bought nothing in build order: "
              f"{', '.join(f'{n} ({layer_seconds(n, counts):.1f} s)' for n in dead)}")
    return lines


# ══ 7 ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 -- THE BUGS NOTHING CAUGHT, AND THE ONE CHECK THAT WOULD HAVE.

DISCOUNTED: list[int] = []          # every non-zero discount the suite ever produced


def checks_pricing_a_discounted_order() -> list[str]:
    """Which checks actually put a non-zero discount through the pricing core."""
    out = []
    for _, _, _, fns in LAYERS:
        for fn in fns:
            DISCOUNTED.clear()
            run_layer([fn], frozenset())
            if DISCOUNTED:
                out.append(fn.__name__)
    DISCOUNTED.clear()
    return out


def money_equalities(fn: Callable[[], None]) -> list[ast.Compare]:
    """Every `assert ... == ...` in `fn` that mentions tax_cents or total_cents."""
    wanted = {"tax_cents", "total_cents"}
    out = []
    for node in ast.walk(ast.parse(inspect.getsource(fn))):
        if not isinstance(node, ast.Assert):
            continue
        for cmp in (c for c in ast.walk(node.test) if isinstance(c, ast.Compare)):
            if not any(isinstance(o, ast.Eq) for o in cmp.ops):
                continue
            names = {a.attr for a in ast.walk(cmp) if isinstance(a, ast.Attribute)}
            names |= {c.value for c in ast.walk(cmp)
                      if isinstance(c, ast.Constant) and isinstance(c.value, str)}
            if wanted & names:
                out.append(cmp)
    return out


def has_an_external_number(cmp: ast.Compare) -> bool:
    """
    True if one side of the equality is a number the TEST supplied, rather than
    another output of the code under test. A comparison with no numeric literal in
    it is the code being checked against itself.
    """
    return any(isinstance(c, ast.Constant) and isinstance(c.value, (int, float))
               and not isinstance(c.value, bool) for c in ast.walk(cmp))


def checks_asserting_an_exact_money_value() -> list[str]:
    """
    Which checks contain an `assert` whose equality mentions tax_cents or
    total_cents -- i.e. which ones state what the number should BE. Found by
    walking each check's AST, so it is a fact about the file, not a guess.
    """
    wanted = {"tax_cents", "total_cents"}
    out = []
    for _, _, _, fns in LAYERS:
        for fn in fns:
            tree = ast.parse(inspect.getsource(fn))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assert):
                    continue
                for cmp in (c for c in ast.walk(node.test) if isinstance(c, ast.Compare)):
                    if not any(isinstance(o, ast.Eq) for o in cmp.ops):
                        continue
                    names = {a.attr for a in ast.walk(cmp) if isinstance(a, ast.Attribute)}
                    names |= {c.value for c in ast.walk(cmp)
                              if isinstance(c, ast.Constant) and isinstance(c.value, str)}
                    if wanted & names:
                        out.append(fn.__name__)
    return sorted(set(out))


def probe_golden_invoice() -> None:
    """
    ONE check, hand-computed from the finance spec by somebody reading the spec
    rather than the code, asserting the whole invoice of one discounted order.
    20000 gross; 5% tier = 1000; coupon 5000; net 14000; 8.75% of 14000 = 1225.
    """
    _, repo, app, _, _ = make_service()
    repo.migrate()
    c = Coupon("SAVE50", 0, date(2026, 12, 31), 5_000)
    _, body = app.post_orders({"customer_id": 1, "subtotal_cents": 20_000,
                               "currency": "USD"}, c, NOW)
    got = (body["subtotal_cents"], body["discount_cents"],
           body["tax_cents"], body["total_cents"])
    assert got == (20_000, 6_000, 1_225, 15_225), got


def section6(caught: dict[str, dict[int, bool]], survivors: list[str]) -> None:
    banner(6, "THE BUGS THAT SURVIVED ALL NINE LAYERS")
    remedies = {
        "C05": ("a human, plus one golden-value assertion anywhere in the suite",
                "nine layers checked the TYPE of total_cents; none checked the NUMBER"),
        "M01": ("the finance spec, read by somebody who did not write the code",
                "the checks that price a discount compare the code against itself"),
        "N01": ("a monitor: events_received minus events_settled, alerting on the gap",
                "no fixture in the whole suite ever produced an unknown currency"),
    }
    for b in survivors:
        who, why = remedies.get(b, ("unknown", "unknown"))
        print(f"  {b}  {BUG_CLASS[b]:<13} {BUG_DESC[b]}")
        print(f"        why it survived : {why}")
        print(f"        what catches it : {who}")
    print()
    # Measure the three claims rather than asserting them.
    total_checks = sum(len(f) for _, _, _, f in LAYERS)
    discounting = checks_pricing_a_discounted_order()
    exact = checks_asserting_an_exact_money_value()
    both = sorted(set(discounting) & set(exact))
    by_name = {fn.__name__: fn for _, _, _, fns in LAYERS for fn in fns}
    independent = [n for n in both
                   if any(has_an_external_number(c) for c in money_equalities(by_name[n]))]
    print(f"  M01, measured over all {total_checks} checks by walking their ASTs:")
    print(f"       {len(discounting):2d} put a NON-ZERO DISCOUNT through the pricing core")
    print(f"       {len(exact):2d} assert an EXACT value of tax_cents or total_cents")
    print(f"       {len(both):2d} do both:")
    for n in both:
        print(f"            {n}")
    print(f"       {len(independent):2d} of those compare it against a number the TEST "
          f"supplied.")
    print("       All three compare one output of the code against another output of the")
    print("       same code: persisted vs computed, real vs fake, components vs total.")
    print("       A tautology cannot be false, so it cannot fail. THAT is where M01 lives —")
    print("       not in a missing test, but in a suite with no independent oracle.")
    gross = price_order(Svc(frozenset({"M01"})), 20_000,
                        Coupon("X", 0, date(2026, 12, 31), 5_000), TODAY)
    net = price_order(Svc(frozenset()), 20_000,
                      Coupon("X", 0, date(2026, 12, 31), 5_000), TODAY)
    print(f"       a 20000c order with a 5000c coupon bills {gross.total_cents} instead of "
          f"{net.total_cents} — {gross.total_cents - net.total_cents}c of")
    print("       tax charged on money the customer never paid, on every discounted order.")

    currencies = set()
    for _, _, _, fns in LAYERS:
        for fn in fns:
            src = inspect.getsource(fn)
            for cur in ("USD", "EUR", "JPY", "GBP"):
                if f'"{cur}"' in src:
                    currencies.add(cur)
    print(f"  N01, measured: the {sum(len(f) for _, _, _, f in LAYERS)} checks use "
          f"{len(currencies)} distinct currency literal(s): {sorted(currencies)}.")
    print(f"       The service knows {len(KNOWN_CURRENCIES)}. No test ever supplies one it "
          f"does not know,")
    print("       so the branch that drops the event is never executed by the suite.")

    svc = Svc(frozenset({"C05"}))
    repo = Repo(svc)
    repo.migrate()
    app = App(svc, repo)
    _, body = app.post_orders({"customer_id": 1, "subtotal_cents": 20_000,
                               "currency": "USD"}, None, NOW)
    truth = price_order(Svc(frozenset()), 20_000, None, TODAY)
    print(f"  C05, measured: the wire says total_cents={body['total_cents']} where the "
          f"invoice is {truth.total_cents} —")
    print(f"       a {truth.total_cents / max(1, body['total_cents']):.0f}x understatement "
          f"in a correctly typed integer with the right name.")
    passes = sum(1 for n in range(1, NL + 1) if not caught["C05"][n])
    print(f"       It passes {passes} of {NL} layers, the JSON round-trips, and the contract "
          f"verifies clean.")
    print()
    print("  All three are the same shape: the suite verified every property it could")
    print("  state, and the defect was in a property nobody stated. That is a gap in KIND,")
    print("  not in effort — more tests of these nine kinds reach none of them.")
    print()
    # The tenth thing: one hand-computed invoice, asserted end to end.
    print("  SO ADD THE TENTH THING. One check, hand-computed from the finance spec by")
    print("  somebody reading the spec rather than the code, asserting the whole invoice")
    print("  of one discounted order end to end:")
    kills = [b for b in BUG_IDS if run_layer([probe_golden_invoice], frozenset({b}))]
    clean_ok = not run_layer([probe_golden_invoice], frozenset())
    src_lines = len(inspect.getsource(probe_golden_invoice).rstrip().split("\n"))
    print(f"    green on a healthy service : {clean_ok}")
    print(f"    bugs it catches on its own : {len(kills)} of {len(BUGS)} — "
          f"{', '.join(kills)}")
    survived_but_caught = [b for b in kills if b in survivors]
    print(f"    of the {len(survivors)} survivors it catches : "
          f"{', '.join(survived_but_caught) if survived_but_caught else 'none'}")
    print(f"    cost : {src_lines} lines including the docstring, one HTTP call, "
          f"no new infrastructure.")
    _s2, _r2, _a2, _, _ = make_service()
    _r2.migrate()
    _, gold = _a2.post_orders({"customer_id": 1, "subtotal_cents": 20_000,
                               "currency": "USD"}, Coupon("SAVE50", 0,
                                                          date(2026, 12, 31), 5_000), NOW)
    print(f"    the invoice it pins, hand-computed from the spec: subtotal "
          f"{gold['subtotal_cents']}, discount {gold['discount_cents']},")
    print(f"    tax {gold['tax_cents']}, total {gold['total_cents']} "
          f"(5% tier = 1000, coupon 5000, net 14000, 8.75% of 14000 = 1225).")
    print(f"  It kills {len(survived_but_caught)} of the {len(survivors)} bugs that nine "
          f"layers and {sum(len(f) for _, _, _, f in LAYERS)} checks could not,")
    print("  and it is not a tenth technique. It is an INDEPENDENT ORACLE: a number that")
    print("  came from the specification instead of from the implementation. The remaining")
    print(f"  survivor, {', '.join(b for b in survivors if b not in kills)}, has no oracle "
          f"anywhere in a test process — only production has")
    print("  the input that triggers it, so only a monitor can be the thing that notices.")


# ══ 8 ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 -- MUTATION SCORING: A MEASUREMENT OF THE SUITE, NOT OF THE PRODUCT.

# A faithful transcription of the pricing core, mutated by an AST rewriter and run
# against the exact cases layers 2 and 8 use. It measures whether those cases can
# SEE an edit -- which is a different question from whether the product is correct.
CORE_SRC = """
def tier_bps(subtotal):
    bps = 0
    for floor, b in TIERS:
        if subtotal >= floor:
            bps = b
    return bps

def coupon_off(subtotal, min_cents, off_cents):
    if subtotal < min_cents:
        return 0
    return off_cents

def price(subtotal, min_cents, off_cents):
    disc = subtotal * tier_bps(subtotal) // 10000
    disc = disc + coupon_off(subtotal, min_cents, off_cents)
    if disc > subtotal:
        disc = subtotal
    net = subtotal - disc
    tax = (net * 875 + 5000) // 10000
    return net + tax
"""


class Mutator(ast.NodeTransformer):
    CMP = {ast.GtE: ast.Gt, ast.Gt: ast.GtE, ast.LtE: ast.Lt, ast.Lt: ast.LtE,
           ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
    ARITH = {ast.Sub: ast.Add, ast.Add: ast.Sub, ast.Mult: ast.FloorDiv}

    def __init__(self, target: int) -> None:
        self.target, self.seen = target, 0

    def _hit(self) -> bool:
        self.seen += 1
        return self.seen - 1 == self.target

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        op = type(node.ops[0])
        if op in self.CMP and self._hit():
            node.ops = [self.CMP[op]()]
        return node

    def visit_BinOp(self, node: ast.BinOp) -> ast.AST:
        self.generic_visit(node)
        if type(node.op) in self.ARITH and self._hit():
            node.op = self.ARITH[type(node.op)]()
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, int) and not isinstance(node.value, bool) and self._hit():
            return ast.Constant(value=node.value + 1)
        return node


def section7() -> tuple[int, int, int]:
    banner(7, "MUTATION SCORING -- A MEASUREMENT OF THE SUITE, NOT OF THE PRODUCT")
    counter = Mutator(-1)
    counter.visit(ast.parse(CORE_SRC))
    n_sites = counter.seen
    tier_probes = [(9_999, 0), (10_000, 500), (10_001, 500), (49_999, 500),
                   (50_000, 1000), (99_999, 1000), (100_000, 1500), (0, 0)]
    coupon_probes = [(20_000, 20_000, 500, 500), (19_999, 20_000, 500, 0),
                     (25_000, 20_000, 500, 500)]
    price_probes = [(5_000, 0, 0, 5_438), (8_000, 0, 0, 8_700),
                    (1_000, 0, 90_000, 0), (60_000, 0, 0, 58_725)]
    killed = survived = 0
    survivors: list[int] = []
    for i in range(n_sites):
        tree = Mutator(i).visit(ast.parse(CORE_SRC))
        ast.fix_missing_locations(tree)
        env: dict[str, Any] = {"TIERS": TIERS}
        try:
            exec(compile(tree, "<mutant>", "exec"), env)
            died = False
            for sub, want in tier_probes:
                if env["tier_bps"](sub) != want:
                    died = True
                    break
            if not died:
                for sub, mn, off, want in coupon_probes:
                    if env["coupon_off"](sub, mn, off) != want:
                        died = True
                        break
            if not died:
                for sub, mn, off, want in price_probes:
                    if env["price"](sub, mn, off) != want:
                        died = True
                        break
        except Exception:                              # noqa: BLE001
            died = True
        if died:
            killed += 1
        else:
            survived += 1
            survivors.append(i)
    print(f"  {n_sites} mutants generated from the pricing core by an AST rewriter")
    print("  (comparison flip, arithmetic flip, integer constant +1), run against the")
    print("  exact cases layers 2 and 8 use.")
    print(f"    killed    {killed:3d}   ({killed/n_sites:5.1%})   a probe went red")
    print(f"    survived  {survived:3d}   ({survived/n_sites:5.1%})   the suite is blind to that edit")
    print(f"  mutation score {killed/n_sites:.1%}; surviving mutant indices {survivors}.")
    print(f"  And the number that matters here: mutation testing detected 0 of the "
          f"{len(BUGS)} seeded")
    print("  bugs directly. It does not test the product; it tests whether the tests can")
    print("  see. That is why it belongs in a nightly job and never in the matrix above.")
    return n_sites, killed, survived


# ══ 9 ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 -- FLAKE-ADJUSTED TRUST OF THE ASSEMBLED SUITE.


def build_green(counts: dict[int, int], subset: Iterable[int]) -> float:
    p = 1.0
    for n in subset:
        p *= (1.0 - FLAKE[n]) ** counts[n]
    return p


def section8(counts: dict[int, int], caught: dict[str, dict[int, bool]]) -> float:
    banner(8, "FLAKE-ADJUSTED TRUST OF THE ASSEMBLED SUITE")
    print("  per-check flake rates are declared per layer; the counts are measured.")
    print(f"  {'layer':<28}{'checks':>7}{'flake/check':>15}{'P(layer green)':>17}")
    for n in range(1, NL + 1):
        p = (1.0 - FLAKE[n]) ** counts[n]
        print(f"  {n} {LAYER_LONG[n]:<26} {counts[n]:6d} {FLAKE[n]:14.5%} {p:16.4%}")
    g = build_green(counts, range(1, NL + 1))
    d = coverage(caught, range(1, NL + 1)) / len(BUGS)
    prior = 0.05
    post = prior * d / (prior * d + (1 - prior) * (1 - g))
    print(f"  whole suite green on a clean tree: {g:.4%}")
    print(f"  detection rate d = {d:.1%} (measured union), prior P(bug) = {prior:.0%}")
    print(f"  P(a real bug | the build is red) = {post:.2%} "
          f"= {math.log2(post/prior):.3f} bits of evidence.")
    for mult in (5, 10, 20):
        big = {n: counts[n] * mult for n in counts}
        gb = build_green(big, range(1, NL + 1))
        pb = prior * d / (prior * d + (1 - prior) * (1 - gb))
        print(f"    at {mult:2d}x the checks ({sum(big.values()):4d}): green {gb:7.2%},"
              f"  P(bug|red) {pb:6.2%},  {math.log2(pb/prior):+6.3f} bits")
    worst = max(range(1, NL + 1), key=lambda n: 1 - (1 - FLAKE[n]) ** (counts[n] * 10))
    print(f"  at 10x, layer {worst} ({LAYER_LONG[worst]}) alone is red "
          f"{1-(1-FLAKE[worst])**(counts[worst]*10):.1%} of the time on a clean tree.")
    print("  Suite growth is a flake amplifier, and the most expensive layer is also the")
    print("  flakiest, so it burns trust exactly where it costs the most to run.")
    return g


# ══ 10 ══════════════════════════════════════════════════════════════════════════
# SECTION 9 -- THE 90-SECOND SUITE, SOLVED EXHAUSTIVELY OVER ALL 512 SUBSETS.


def section9(caught: dict[str, dict[int, bool]], counts: dict[int, int]) -> None:
    banner(9, "THE MINIMUM SUITE UNDER A 90-SECOND CI BUDGET")
    layers = list(range(1, NL + 1))
    full_s = sum(layer_seconds(n, counts) for n in layers)
    full_c = coverage(caught, layers)
    best: dict[int, tuple[int, float, tuple[int, ...]]] = {}
    for budget in (15, 30, 60, 90, 120, 200, 300):
        top = (-1, 0.0, ())
        for r in range(NL + 1):
            for sub in itertools.combinations(layers, r):
                s = sum(layer_seconds(n, counts) for n in sub)
                if s > budget:
                    continue
                c = coverage(caught, sub)
                if (c, -s) > (top[0], -top[1]):
                    top = (c, s, sub)
        best[budget] = top
    print(f"  exhaustive over all {2**NL} subsets; the whole suite is {full_s:.1f} s "
          f"for {full_c} of {len(BUGS)} bugs.")
    print("  budget    bugs   of 31    CI s     layers kept")
    for budget, (c, s, sub) in best.items():
        names = " ".join(f"{n}:{LAYER_NAME[n]}" for n in sub)
        print(f"  {budget:5d}s {c:7d} {c/len(BUGS):7.1%} {s:8.2f}    {names}")
    c90, s90, sub90 = best[90]
    dropped = [n for n in layers if n not in sub90]
    print()
    print(f"  the 90 s answer: layers {', '.join(str(n) for n in sub90)} — "
          f"{c90} of {len(BUGS)} bugs for {s90:.2f} s.")
    print(f"  that is {c90/full_c:.0%} of the detection for {s90/full_s:.0%} of the "
          f"whole suite's time.")
    print(f"  it drops layers {', '.join(f'{n}:{LAYER_NAME[n]}' for n in dropped)}.")
    escaping = [b for b in BUG_IDS
                if any(caught[b].values()) and not any(caught[b][n] for n in sub90)]
    print(f"  what a 90 s gate lets through: {', '.join(escaping) if escaping else 'nothing'} "
          f"({len(escaping)} bugs).")
    top = max(best.values(), key=lambda t: (t[0], -t[1]))
    print(f"  the frontier is flat above {top[1]:.2f} s: the whole suite costs "
          f"{full_s:.2f} s, so the last")
    print(f"  {full_s - top[1]:.2f} seconds buy 0 additional bugs.")
    print("  Those are the nightly job. A gate is not the whole suite; it is the part")
    print("  that has to answer before a human can be expected to wait.")
    print()
    print("  whole-suite marginal (drop exactly one layer, keep the other eight):")
    print(f"  {'layer':<28}{'bugs lost if dropped':>21}{'CI s freed':>14}{'bugs/s':>10}")
    for n in layers:
        lost = full_c - coverage(caught, [m for m in layers if m != n])
        s = layer_seconds(n, counts)
        print(f"  {n} {LAYER_LONG[n]:<26} {lost:20d} {s:13.2f} {lost/s:9.4f}")
    print("  A layer whose 'lost if dropped' is 0 is not useless: it is currently")
    print("  redundant with the layers around it — a different, and reversible, claim.")


def main() -> None:
    counts = section1()
    caught, why = build_matrix()
    survivors = section2(caught, why)
    build_rows = section3(caught)
    section4(caught, build_rows)
    section5(caught, counts, build_rows)
    section6(caught, survivors)
    section7()
    section8(counts, caught)
    section9(caught, counts)


if __name__ == "__main__":
    import time as _time

    _t0 = _time.perf_counter()
    main()
    print(f"\n  (total wall time {_time.perf_counter() - _t0:.1f} s)")
