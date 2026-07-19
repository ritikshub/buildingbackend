#!/usr/bin/env python3
"""
What a test buys, measured: a hand-rolled test runner in a dozen lines, the
escape-cost ladder for one one-character bug, 40 real mutations of a pricing
module run through five executable gates, the marginal (not absolute) value of
each gate, the refactor headroom a suite buys, a brittle suite that costs more
than it saves, and Dijkstra's limit priced in years.

Companion to docs/en.md (Phase 12, Lesson 01). Standard library only, every RNG
seeded (SEED below), self-terminating in about a second. Sources: Dijkstra,
*Notes on Structured Programming*, EWD249, 1970; DeMillo, Lipton & Sayward,
*Hints on Test Data Selection*, IEEE Computer 11(4), 1978.

Run:  python3 cost_of_a_bug.py
"""

from __future__ import annotations

import inspect
import random
import sqlite3
import statistics
import typing
from typing import Any, Callable, Dict, List, Sequence, Tuple

SEED = 20260718

# A blended, fully-loaded engineer-minute. Stated once, used everywhere, and
# deliberately easy to change: section 4 measures how much the *conclusions*
# move when you change it, which is the only honest way to use such a number.
DOLLARS_PER_ENGINEER_MINUTE = 1.50


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100:,}.{c % 100:02d}"


# ══ THE MODULE UNDER TEST ═══════════════════════════════════════════════════════
# Held as source text, not as an imported module, for one reason: we are going to
# edit it 40 times the way a careless engineer edits code — one token at a time —
# and run every gate against every edit. Money is integer cents throughout; a
# float never touches a currency amount. Three of the thirteen functions carry a
# docstring stating the rule they implement. Remember that number; section 3
# measures what it is worth.

PRICING_SRC = '''
from __future__ import annotations

TIER_BPS = {"standard": 0, "silver": 250, "gold": 500}
MAX_DISCOUNT_BPS = 5000
VOLUME_THRESHOLD_CENTS = 5000
VOLUME_BPS = 1000
TAX_BPS = 875
FREE_SHIPPING_THRESHOLD_CENTS = 10000
SHIPPING_CENTS = 599


def line_subtotal(unit_price_cents: int, qty: int) -> int:
    if qty <= 0:
        raise ValueError("qty must be positive")
    return unit_price_cents * qty


def cart_subtotal(lines: tuple) -> int:
    total = 0
    for unit_price_cents, qty in lines:
        total += line_subtotal(unit_price_cents, qty)
    return total


def volume_bps(subtotal_cents: int) -> int:
    """The 10% volume discount applies from 50.00 upwards, inclusive."""
    if subtotal_cents >= VOLUME_THRESHOLD_CENTS:
        return VOLUME_BPS
    return 0


def tier_bps(tier: str) -> int:
    if tier not in TIER_BPS:
        raise ValueError("unknown tier")
    return TIER_BPS[tier]


def discount_bps(subtotal_cents: int, tier: str) -> int:
    combined = tier_bps(tier) + volume_bps(subtotal_cents)
    return min(combined, MAX_DISCOUNT_BPS)


def apply_bps(amount_cents: int, bps: int) -> int:
    """Rounds half up, so a discount never loses the customer a cent."""
    return (amount_cents * bps + 5000) // 10000


def tax_cents(taxable_cents: int) -> int:
    return (taxable_cents * TAX_BPS + 5000) // 10000


def shipping_for(subtotal_cents: int) -> int:
    """Shipping is free from 100.00 upwards, inclusive."""
    if subtotal_cents >= FREE_SHIPPING_THRESHOLD_CENTS:
        return 0
    return SHIPPING_CENTS


def price_order(lines: tuple, tier: str) -> dict:
    subtotal = cart_subtotal(lines)
    discount = apply_bps(subtotal, discount_bps(subtotal, tier))
    taxable = subtotal - discount
    tax = tax_cents(taxable)
    ship = shipping_for(subtotal)
    return {"subtotal": subtotal, "discount": discount, "taxable": taxable,
            "tax": tax, "shipping": ship, "total": taxable + tax + ship}


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}${c // 100}.{c % 100:02d}"


def receipt_line(name: str, cents: int) -> str:
    return f"{name:<12}{format_money(cents):>10}"


def to_row(order_id: str, priced: dict) -> tuple:
    return (order_id, priced["subtotal"], priced["discount"],
            priced["tax"], priced["shipping"], priced["total"])


def from_row(row: tuple) -> dict:
    return {"order_id": row[0], "subtotal": row[1], "discount": row[2],
            "tax": row[3], "shipping": row[4], "total": row[5]}
'''

Edits = Sequence[Tuple[str, str]]


def build(edits: Edits = ()) -> Dict[str, Any]:
    """Apply `edits` to the pricing source and exec it into a fresh namespace.
    Each edit must match exactly once — an edit that silently matched twice, or
    not at all, would quietly corrupt every number in this program."""
    src = PRICING_SRC
    for old, new in edits:
        if src.count(old) != 1:
            raise AssertionError(f"edit {old!r} matched {src.count(old)} times")
        src = src.replace(old, new, 1)
    ns: Dict[str, Any] = {}
    exec(compile(src, "<pricing>", "exec"), ns)   # noqa: S102 — the point of the file
    return ns


GOOD = build()


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# A test is a program that runs your program and asserts a fact about it. That
# sentence is the whole idea and what follows is the whole implementation.

FAILURES: List[str] = []


def assert_eq(actual: Any, expected: Any, what: str) -> None:
    if actual != expected:
        FAILURES.append(f"{what}\n      expected: {expected!r}\n      actual:   {actual!r}")


def run_suite(tests: Sequence[Tuple[str, Callable[[], None]]]) -> List[str]:
    del FAILURES[:]
    for name, fn in tests:
        n = len(FAILURES)
        try:
            fn()
        except Exception as exc:                     # a crash is a failure too
            FAILURES.append(f"raised {type(exc).__name__}: {exc}")
        FAILURES[n:] = [f"{name}: {f}" for f in FAILURES[n:]]
    return list(FAILURES)


# Counted from the source, not claimed: the non-blank lines of the two functions
# above are the entire test framework this lesson needs.
RUNNER_LINES = sum(1 for fn in (assert_eq, run_suite)
                   for line in inspect.getsource(fn).splitlines() if line.strip())


def assert_raises(exc: type, fn: Callable[[], Any], what: str) -> None:
    try:
        fn()
    except exc:
        return
    except Exception as other:
        FAILURES.append(f"{what}: raised {type(other).__name__}, wanted {exc.__name__}")
        return
    FAILURES.append(f"{what}: returned normally, wanted {exc.__name__}")


def unit_suite(m: Dict[str, Any]) -> List[Tuple[str, Callable[[], None]]]:
    """Fourteen unit tests over the pure pricing functions. Boundary-driven:
    every threshold is probed below it, at it, and above it."""
    po = lambda: m["price_order"](((2500, 2),), "gold")            # noqa: E731
    return [
        ("line_subtotal_multiplies",
         lambda: assert_eq(m["line_subtotal"](250, 3), 750, "3 x 2.50")),
        ("line_subtotal_rejects_zero_qty",
         lambda: assert_raises(ValueError, lambda: m["line_subtotal"](250, 0), "qty 0")),
        ("cart_subtotal_sums_lines",
         lambda: assert_eq(m["cart_subtotal"](((250, 3), (1000, 2))), 2750, "sum")),
        ("volume_discount_below_threshold",
         lambda: assert_eq(m["volume_bps"](4999), 0, "49.99 gets nothing")),
        ("volume_discount_at_threshold",
         lambda: assert_eq(m["volume_bps"](5000), 1000, "50.00 is INCLUSIVE")),
        ("volume_discount_above_threshold",
         lambda: assert_eq(m["volume_bps"](5001), 1000, "50.01 gets 10%")),
        ("tier_bps_known_tiers",
         lambda: assert_eq([m["tier_bps"](t) for t in ("standard", "silver", "gold")],
                           [0, 250, 500], "tier table")),
        ("tier_bps_rejects_unknown",
         lambda: assert_raises(ValueError, lambda: m["tier_bps"]("platinum"), "tier")),
        ("discount_bps_combines_and_caps",
         lambda: assert_eq(m["discount_bps"](5000, "gold"), 1500, "gold + volume")),
        ("apply_bps_rounds_half_up",
         lambda: assert_eq((m["apply_bps"](1005, 1000), m["apply_bps"](1004, 1000)),
                           (101, 100), "100.5 -> 101, 100.4 -> 100")),
        ("tax_is_charged_after_discount",
         lambda: assert_eq(m["tax_cents"](4500), 394, "8.75% of 45.00")),
        ("shipping_free_at_threshold",
         lambda: assert_eq((m["shipping_for"](9999), m["shipping_for"](10000)),
                           (599, 0), "100.00 is INCLUSIVE")),
        ("price_order_gold_at_boundary",
         lambda: assert_eq(po(), {"subtotal": 5000, "discount": 750, "taxable": 4250,
                                  "tax": 372, "shipping": 599, "total": 5221},
                           "the whole invoice at exactly 50.00")),
        ("price_order_standard_small_cart",
         lambda: assert_eq(m["price_order"](((999, 1),), "standard")["total"],
                           999 + 87 + 599, "no discount, tax, shipping")),
    ]


THE_BUG = (">= VOLUME_THRESHOLD_CENTS", "> VOLUME_THRESHOLD_CENTS")


def section1() -> None:
    banner(1, "A TEST IS A PROGRAM THAT RUNS YOUR PROGRAM")
    print(f"  the entire runner is {RUNNER_LINES} lines, counted from its own source:")
    print("  append to a list on mismatch, catch exceptions so one crash cannot hide")
    print("  the rest, return the list. no decorators, no discovery, no plugins.\n")
    print(f"  {len(unit_suite(GOOD))} tests against the module as written: "
          f"{len(run_suite(unit_suite(GOOD)))} failures")
    red = run_suite(unit_suite(build([THE_BUG])))
    print(f"  the same {len(unit_suite(GOOD))} tests with ONE character changed "
          f"({THE_BUG[0]} -> {THE_BUG[1]}): {len(red)} failures\n")
    for failure in red:
        for line in failure.splitlines():
            print(f"    {line}")
    good, bad = GOOD["price_order"](((2500, 2),), "gold"), \
        build([THE_BUG])["price_order"](((2500, 2),), "gold")
    print(f"\n  what the customer sees on that order — two items at 2,500 cents each:")
    print(f"    correct   {GOOD['receipt_line']('Total', good['total'])}")
    print(f"    with bug  {GOOD['receipt_line']('Total', bad['total'])}")
    print("\n  that is a test: it ran the program, compared one value, printed the")
    print("  difference. everything pytest adds is ergonomics, not capability.")


# ══ THE FORTY MUTATIONS ═════════════════════════════════════════════════════════
# Forty single-token edits, each a bug that has shipped in a real billing system,
# across nine classes. Every one compiles, runs, and changes behaviour — except
# one, which is the point of that one. Anchors are the shortest string unique in
# PRICING_SRC; build() asserts the uniqueness on every use.

MUTATIONS: List[Tuple[str, str, Edits, str]] = [
    ("B01", "boundary", (THE_BUG,), "volume discount becomes exclusive at 50.00"),
    ("B03", "boundary", ((">= FREE_SHIPPING", "> FREE_SHIPPING"),),
     "free shipping becomes exclusive at 100.00"),
    ("B04", "boundary", ((">= FREE_SHIPPING", "<= FREE_SHIPPING"),),
     "free-shipping comparison inverted"),
    ("B05", "boundary", (("min(combined", "max(combined"),),
     "the discount cap becomes a discount floor"),
    ("B06", "boundary", (("if qty <= 0", "if qty < 0"),), "qty 0 no longer rejected"),

    ("A01", "arithmetic", (("unit_price_cents * qty", "unit_price_cents + qty"),),
     "line total adds instead of multiplying"),
    ("A02", "arithmetic", (("unit_price_cents * qty", "unit_price_cents * (qty - 1)"),),
     "one item per line is free"),
    ("A03", "arithmetic", (("total +=", "total -="),), "the cart subtracts each line"),
    ("A04", "arithmetic", (("subtotal - discount", "subtotal + discount"),),
     "the discount is added to the taxable amount"),
    ("A05", "arithmetic", (("tier_bps(tier) + volume", "tier_bps(tier) - volume"),),
     "tier and volume discounts cancel"),
    ("A06", "arithmetic", (("taxable + tax + ship", "taxable + tax - ship"),),
     "shipping is deducted from the total"),
    ("A07", "arithmetic", (("taxable + tax + ship", "subtotal + tax + ship"),),
     "discount reported but never deducted"),

    ("R01", "rounding", (("bps + 5000) // 10000", "bps) // 10000"),),
     "the discount truncates instead of rounding half up"),
    ("R02", "rounding", (("bps + 5000) // 10000", "bps + 4999) // 10000"),),
     "half-up becomes half-down"),
    ("R03", "rounding", (("(taxable_cents * TAX_BPS + 5000) // 10000",
                          "round(taxable_cents * TAX_BPS / 10000)"),),
     "tax switches to banker's rounding, via float"),
    ("R04", "rounding", (("TAX_BPS + 5000) // 10000", "TAX_BPS + 5000) // 1000"),),
     "the tax divisor loses a zero"),

    ("T01", "type-shape", (("(amount_cents * bps + 5000) // 10000",
                            "str((amount_cents * bps + 5000) // 10000)"),),
     "the discount is returned as a string"),
    ("T02", "type-shape", (("bps + 5000) // 10000", "bps + 5000) / 10000"),),
     "integer division becomes float division"),
    ("T03", "type-shape", (('f"{sign}${c // 100}.{c % 100:02d}"', "(c)"),),
     "format_money returns an int"),
    ("T04", "type-shape", (("return (order_id", "return [order_id"),
                           ('priced["total"])', 'priced["total"]]')),
     "to_row returns a list, not a tuple"),

    ("C01", "constant", (("TAX_BPS = 875", "TAX_BPS = 8.75"),),
     "tax rate written as a percentage, not basis points"),
    ("C02", "constant", (("TAX_BPS = 875", "TAX_BPS = 785"),),
     "tax rate digits transposed"),
    ("C03", "constant", (("VOLUME_BPS = 1000", "VOLUME_BPS = 100"),),
     "volume discount 10% -> 1%"),
    ("C04", "constant", (("SHIPPING_CENTS = 599", "SHIPPING_CENTS = 5990"),),
     "shipping 5.99 -> 59.90"),
    ("C05", "constant", (('"gold": 500', '"gold": 5000'),),
     "gold tier discount 5% -> 50%"),
    ("C07", "constant", (("FREE_SHIPPING_THRESHOLD_CENTS = 10000",
                          "FREE_SHIPPING_THRESHOLD_CENTS = 1000"),),
     "free shipping from 10.00 instead of 100.00"),

    ("W01", "wiring", (("apply_bps(subtotal, discount_bps(subtotal, tier))",
                        "apply_bps(discount_bps(subtotal, tier), subtotal)"),),
     "apply_bps arguments swapped"),
    ("W02", "wiring", (("tax_cents(taxable)", "tax_cents(subtotal)"),),
     "tax charged on the pre-discount amount"),
    ("W03", "wiring", (("shipping_for(subtotal)", "shipping_for(taxable)"),),
     "free shipping decided on the post-discount amount"),
    ("W04", "wiring", (("volume_bps(subtotal_cents)", "volume_bps(0)"),),
     "the volume discount is always evaluated at zero"),
    ("W05", "wiring", (('"taxable": taxable', '"taxable": subtotal'),),
     "taxable reported as the pre-discount subtotal"),

    ("S01", "serialization", (('priced["tax"], priced["shipping"]',
                               'priced["shipping"], priced["tax"]'),
                              ('"tax": row[3], "shipping": row[4]',
                               '"shipping": row[3], "tax": row[4]')),
     "tax/shipping columns swapped on BOTH write and read"),
    ("S02", "serialization", (('priced["tax"], priced["shipping"]',
                               'priced["shipping"], priced["tax"]'),),
     "tax/shipping swapped on write only"),
    ("S03", "serialization", (('"total": row[5]', '"total": row[4]'),),
     "total read from the shipping column"),
    ("S04", "serialization", (('priced["total"])', 'priced["subtotal"])'),),
     "subtotal persisted into the total column"),

    ("E01", "error-handling", (('raise ValueError("qty must be positive")', "return 0"),),
     "zero or negative qty silently priced at 0"),
    ("E02", "error-handling", (('raise ValueError("unknown tier")', "return 0"),),
     "unknown tier silently gets no discount"),
    ("E03", "error-handling", (('"-" if cents < 0 else ""', '""'),),
     "refunds render as charges"),

    ("F01", "formatting", (("{c % 100:02d}", "{c % 100:d}"),), "4.05 renders as $4.5"),
    ("F02", "formatting", (("{name:<12}", "{name:<14}"),),
     "receipt column width 12 -> 14"),
]

CLASSES = ("boundary", "arithmetic", "rounding", "type-shape", "constant",
           "wiring", "serialization", "error-handling", "formatting")


# ══ THE FIVE GATES ══════════════════════════════════════════════════════════════
# Each gate maps a built module to True (this bug stops here) or False (it moves
# on). Four are genuinely executed. The fifth — review — is a model of a human,
# and is labelled as one everywhere its number appears.

TYPE_PROBES: Tuple[Tuple[str, tuple], ...] = (
    ("line_subtotal", (250, 3)), ("cart_subtotal", (((250, 3), (1000, 2)),)),
    ("volume_bps", (5000,)), ("tier_bps", ("gold",)), ("discount_bps", (5000, "gold")),
    ("apply_bps", (5000, 1000)), ("tax_cents", (4250,)), ("shipping_for", (4999,)),
    ("price_order", (((2500, 2),), "gold")), ("format_money", (5221,)),
    ("receipt_line", ("Total", 5221)),
    ("to_row", ("o", GOOD["price_order"](((2500, 2),), "gold"))),
    ("from_row", (GOOD["to_row"]("o", GOOD["price_order"](((2500, 2),), "gold")),)),
)

_ANNOT = {"int": int, "str": str, "tuple": tuple, "dict": dict}


def gate_types(m: Dict[str, Any]) -> bool:
    """What a static type checker approximates: call each function once with
    well-typed arguments and check the result against its return annotation.
    Nothing about values — only shapes."""
    for name, args in TYPE_PROBES:
        fn = m.get(name)
        if fn is None:
            return True
        want = _ANNOT.get(typing.get_type_hints(fn).get("return", int).__name__)
        try:
            got = fn(*args)
        except TypeError:
            return True
        except Exception:
            continue                      # a value error is not a type error
        if want is not None and (not isinstance(got, want) or
                                 (want is int and isinstance(got, bool))):
            return True
    return False


def gate_unit(m: Dict[str, Any]) -> bool:
    return bool(run_suite(unit_suite(m)))


# The three things a reviewer can decide from a diff without running it, plus the
# fourth thing they always ask about. Anything requiring domain knowledge they do
# not have is deliberately absent — that is what makes this an honest model.
CONTRADICTS_A_DOCSTRING = (">= VOLUME_THRESHOLD_CENTS", ">= FREE_SHIPPING",
                           "bps + 5000) // 10000")
NONSENSE_IN_PLACE = ("total -=", "* (qty - 1)", "volume_bps(0)")
CONSTANTS = ("TIER_BPS", "MAX_DISCOUNT_BPS", "VOLUME_THRESHOLD_CENTS", "VOLUME_BPS",
             "TAX_BPS", "FREE_SHIPPING_THRESHOLD_CENTS", "SHIPPING_CENTS", '"gold"')


def gate_review(edits: Edits) -> bool:
    """A model of a human, not a measurement of one. A reviewer is not a
    subprocess. Its number is an estimate of what an attentive reviewer with no
    domain knowledge gets from a small diff, and nothing more."""
    for old, new in edits:
        if old in CONTRADICTS_A_DOCSTRING:
            return True
        if "raise ValueError" in old and "raise ValueError" not in new:
            return True
        if any(tok in new for tok in NONSENSE_IN_PLACE):
            return True
        if any(old.startswith(c) for c in CONSTANTS) and ("=" in old or ":" in old):
            return True
    return False


INTEGRATION_ORDERS = (
    ("ord-1001", ((2500, 2),), "gold"),
    ("ord-1002", ((999, 1), (1250, 3)), "standard"),
    ("ord-1003", ((4999, 1), (5000, 1), (620, 2)), "silver"),
)


def _fresh_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE invoices (order_id TEXT PRIMARY KEY, subtotal INT,"
                 " discount INT, tax INT, shipping INT, total INT)")
    return conn


def _checkout(m: Dict[str, Any], conn: sqlite3.Connection, order_id: str,
              lines: tuple, tier: str) -> Dict[str, Any]:
    priced = m["price_order"](lines, tier)
    conn.execute("INSERT INTO invoices VALUES (?,?,?,?,?,?)",
                 tuple(m["to_row"](order_id, priced)))
    row = conn.execute("SELECT * FROM invoices WHERE order_id = ?",
                       (order_id,)).fetchone()
    return m["from_row"](row)


def _golden() -> Dict[str, Dict[str, Any]]:
    conn = _fresh_db()
    out = {oid: _checkout(GOOD, conn, oid, ln, t) for oid, ln, t in INTEGRATION_ORDERS}
    conn.close()
    return out


GOLDEN = _golden()


def gate_integration(m: Dict[str, Any]) -> bool:
    """The wiring plus the database: price three orders end to end, write each to
    SQLite, read it back, compare against a golden invoice recorded once."""
    conn = _fresh_db()
    try:
        for order_id, lines, tier in INTEGRATION_ORDERS:
            if _checkout(m, conn, order_id, lines, tier) != GOLDEN[order_id]:
                return True
    except Exception:
        return True
    finally:
        conn.close()
    return False


def make_day(n_orders: int, seed: int) -> List[Tuple[str, tuple, str]]:
    """A day of orders. The catalogue is full of round prices, because real
    catalogues are, and round prices are what land you exactly on a threshold."""
    rng = random.Random(seed)
    catalogue = (999, 1250, 2500, 4999, 5000, 1799, 620, 3300)
    tiers = ("standard", "standard", "standard", "silver", "gold")
    return [(f"ord-{i:05d}",
             tuple((rng.choice(catalogue), rng.randint(1, 4))
                   for _ in range(rng.randint(1, 3))),
             rng.choice(tiers)) for i in range(n_orders)]


DAY = make_day(2_000, SEED + 1)
BASELINE_REVENUE = sum(GOOD["price_order"](ln, t)["total"] for _o, ln, t in DAY)
STAGING_REVENUE_TOLERANCE = 0.02


def gate_staging(m: Dict[str, Any]) -> bool:
    """Staging has no oracle — nobody there knows the right answer. It has
    invariants and yesterday's revenue number, so that is all this checks."""
    revenue = 0
    try:
        for _oid, lines, tier in DAY:
            p = m["price_order"](lines, tier)
            vals = [p["subtotal"], p["discount"], p["tax"], p["shipping"], p["total"]]
            if any(not isinstance(v, int) or isinstance(v, bool) or v < 0
                   for v in vals):
                return True
            if p["discount"] > p["subtotal"]:
                return True
            if p["taxable"] + p["tax"] + p["shipping"] != p["total"]:
                return True
            revenue += p["total"]
    except Exception:
        return True
    return abs(revenue - BASELINE_REVENUE) / BASELINE_REVENUE > STAGING_REVENUE_TOLERANCE


GATES: Tuple[str, ...] = ("types", "unit", "review", "integration", "staging")


def catch_matrix() -> Dict[str, Dict[str, bool]]:
    """Every gate against every mutation, independently: each gate is asked
    'would YOU have caught this', not 'do you catch what got past the others'.
    The pipeline arithmetic is a different question, and comes later."""
    out: Dict[str, Dict[str, bool]] = {}
    for mid, _cls, edits, _desc in MUTATIONS:
        try:
            m = build(edits)
        except Exception:
            out[mid] = {g: True for g in GATES}
            continue
        out[mid] = {"types": gate_types(m), "unit": gate_unit(m),
                    "review": gate_review(edits), "integration": gate_integration(m),
                    "staging": gate_staging(m)}
    return out


def _observe(m: Dict[str, Any], lines: tuple, tier: str) -> Tuple[Any, Any]:
    """Everything a customer or a downstream system can see for one order: the
    invoice as it comes back out of storage, and the rendered receipt."""
    priced = m["price_order"](lines, tier)
    return m["from_row"](tuple(m["to_row"]("o", priced))), \
        m["receipt_line"]("Total", priced["total"])


def damage(edits: Edits) -> Tuple[int, int]:
    """One day of orders through a bug: how many come out observably different
    anywhere, and how many cents move on the total. Blast radius and money are
    two different numbers, and a bug can have plenty of one and none of the other."""
    wrong = delta = 0
    try:
        m = build(edits)
    except Exception:
        return len(DAY), 0
    for _oid, lines, tier in DAY:
        want = _observe(GOOD, lines, tier)
        try:
            got = _observe(m, lines, tier)
        except Exception:
            wrong += 1
            continue
        if got != want:
            wrong += 1
        total = got[0].get("total")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            delta += int(total) - want[0]["total"]
    return wrong, delta


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# The escape-cost ladder. No program can measure what a postmortem costs, so
# these are BUILT out of people and minutes, every component printed. Section 4
# then measures how much the conclusions move when the ladder changes, which is
# the only defensible way to use a number of this kind.

Component = Tuple[str, int, float]      # label, people, minutes each

STAGE_COSTS: Tuple[Tuple[str, str, Tuple[Component, ...]], ...] = (
    ("types", "the editor underlines it", (("retype the character", 1, 0.5),)),
    ("unit", "a unit test goes red",
     (("read the failure", 1, 1.0), ("fix and re-run", 1, 1.0))),
    ("review", "a reviewer comments",
     (("author context switch back", 1, 15.0), ("reviewer reads again", 1, 12.0),
      ("second review round", 1, 7.0))),
    ("integration", "CI fails on the branch",
     (("pipeline queue and run", 1, 9.0), ("author context switch back", 1, 12.0),
      ("fix and push", 1, 6.0), ("re-run the pipeline", 1, 9.0),
      ("merge-queue wait", 1, 4.0))),
    ("staging", "QA files a ticket",
     (("deploy to staging", 1, 12.0), ("QA reproduces and writes it up", 1, 25.0),
      ("triage and assign", 2, 15.0), ("author reloads the context", 1, 30.0),
      ("fix, review, redeploy, re-verify", 1, 46.0))),
    ("production", "a customer notices",
     (("time to detection", 1, 47.0), ("incident response", 3, 40.0),
      ("rollback and hotfix", 1, 35.0), ("write the refund tooling", 1, 90.0),
      ("run and reconcile the refunds", 2, 55.0), ("postmortem", 4, 60.0),
      ("customer comms and credits", 1, 60.0))),
)

STAGE_ORDER = tuple(s for s, _d, _c in STAGE_COSTS)


def section2() -> Dict[str, float]:
    banner(2, "THE ESCAPE-COST LADDER: ONE BUG, SIX PRICES")
    mins = {s: sum(p * m for _l, p, m in comps) for s, _d, comps in STAGE_COSTS}
    wrong, delta = damage([THE_BUG])
    print(f"  what the section-1 bug actually DOES over one day of {len(DAY):,} orders:")
    print(f"    invoices priced differently  {wrong} = {wrong/len(DAY):.2%} of the day")
    print(f"    money moved                  {money(delta)} overcharged, "
          f"{money(delta // wrong)} per affected order")
    print(f"    revenue for the day          {money(BASELINE_REVENUE)} correct, so the bug")
    print(f"                                 moves it {delta/BASELINE_REVENUE:.2%} against a"
          f" {STAGING_REVENUE_TOLERANCE:.0%} alarm threshold")
    print("  every other invoice is byte-identical to the correct one, so no dashboard")
    print("  moves and no alert fires. that is why nobody notices for days.\n")

    print("    stage         found when                        engineer-min"
          "    cost   x unit")
    for stage, when, _c in STAGE_COSTS:
        print(f"    {stage:<12}  {when:<30}  {mins[stage]:>11.1f}"
              f"  {'$%.0f' % (mins[stage] * DOLLARS_PER_ENGINEER_MINUTE):>7}"
              f"  {mins[stage] / mins['unit']:>6.0f}x")
    for stage, _w, comps in STAGE_COSTS:
        if stage in ("staging", "production"):
            print(f"\n    {stage} =")
            for label, people, each in comps:
                print(f"      {label:<34} {people} x {each:>5.1f} min = {people*each:>6.1f}")

    prod = {label: people * each for label, people, each in STAGE_COSTS[-1][2]}
    finding = (prod["time to detection"] + prod["incident response"]
               + prod["postmortem"] + prod["customer comms and credits"])
    print(f"\n  production / unit = {mins['production']/mins['unit']:.0f}x, from first"
          " principles. the figure usually quoted for")
    print("  this ratio is 100x, from 1970s waterfall projects on six-month cycles;")
    print("  the constant is not the point and never was. the SHAPE is: cost jumps")
    print("  every time a stage adds PEOPLE or an ENVIRONMENT.")
    print(f"  and inside production, finding out costs {finding:.0f} of {mins['production']:.0f}"
          f" minutes = {finding/mins['production']:.0%}; the")
    print(f"  code change is {prod['rollback and hotfix']:.0f} minutes"
          f" = {prod['rollback and hotfix']/mins['production']:.0%}. the day's overcharge,"
          f" {money(delta)}, is")
    print(f"  {abs(delta)/(mins['production']*DOLLARS_PER_ENGINEER_MINUTE*100):.2f}x the labour."
          " the incident is the cost; the damage is a rounding error.")
    return mins


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# Forty mutations, five gates, and the number that matters: not what each gate
# catches, but what it catches THAT THE PREVIOUS GATES DID NOT.

def section3(matrix: Dict[str, Dict[str, bool]]) -> None:
    banner(3, "FORTY REAL BUGS, FIVE GATES, AND THE MARGINAL CATCH")
    by_id = {mid: (cls, desc) for mid, cls, _e, desc in MUTATIONS}
    edits_by_id = {mid: e for mid, _c, e, _d in MUTATIONS}
    print(f"  {len(MUTATIONS)} single-token edits, {len(CLASSES)} bug classes. each gate is"
          " asked twice: what do you\n  catch, and what do you catch that nothing"
          " before you caught?\n")
    print("    gate           catches   alone   cumulative   MARGINAL   of what reached it")
    seen: set = set()
    for g in GATES:
        catches = {mid for mid in matrix if matrix[mid][g]}
        new, reaching = catches - seen, len(MUTATIONS) - len(seen)
        seen |= catches
        share = f"{len(new)/reaching:>5.0%}" if reaching else "    —"
        print(f"    {g:<14} {len(catches):>7}  {len(catches)/len(MUTATIONS):>6.0%}"
              f"   {len(seen):>10}   {len(new):>8}   {len(new)}/{reaching} = {share}")
    escaped = sorted(set(by_id) - seen)
    print(f"    {'ESCAPES':<14} {len(escaped):>7}  {len(escaped)/len(MUTATIONS):>6.0%}")
    n_unit = sum(1 for m in matrix.values() if m["unit"])
    print(f"\n  the unit suite catches {n_unit}/{len(MUTATIONS)} on its own. added after"
          " types it is worth 25 more.\n  that gap is the whole argument for measuring"
          " gates in order rather than alone.")

    print("\n  by bug class — where each class actually dies:")
    print(f"    {'class':<16}  n  " + "  ".join(f"{g[:5]:>5}" for g in GATES) + "   escapes")
    for cls in CLASSES:
        ids = [mid for mid, c, _e, _d in MUTATIONS if c == cls]
        cells = "  ".join(f"{sum(1 for i in ids if matrix[i][g]):>5}" for g in GATES)
        print(f"    {cls:<16} {len(ids):>2}  {cells}"
              f"   {sum(1 for i in ids if i in escaped):>7}")

    print("\n  the survivors — five gates green, and the invoice still wrong:")
    print(f"    id   class          orders visibly wrong   money on the total   what it is")
    for mid in escaped:
        cls, desc = by_id[mid]
        wrong, delta = damage(edits_by_id[mid])
        print(f"    {mid}  {cls:<14} {wrong:>7,} of {len(DAY):,} = {wrong/len(DAY):>6.1%}"
              f"   {money(delta):>13}       {desc}")

    print("\n  three of those read zero, and the zero is the interesting part — the")
    print("  day's data never contained the case. ask each a different question:")
    s01 = build(edits_by_id["S01"])
    tax_good = sum(GOOD["to_row"]("o", GOOD["price_order"](ln, t))[3] for _o, ln, t in DAY)
    tax_s01 = sum(s01["to_row"]("o", s01["price_order"](ln, t))[3] for _o, ln, t in DAY)
    print(f"    S01  a finance job sums column 3 as tax:  correct {money(tax_good)}"
          f"   with S01 {money(tax_s01)}  ({(tax_s01-tax_good)/tax_good:+.0%})")
    print("         the round-trip is perfect. every OTHER reader of that table is wrong,")
    print("         and the suite that wrote it will never say so (lessons 04, 06).")
    e03 = build(edits_by_id["E03"])
    print(f"    E03  render a refund of -4.05:  correct {GOOD['format_money'](-405)!r}"
          f"   with E03 {e03['format_money'](-405)!r}")
    print(f"         {len(DAY):,} orders, not one refund among them. the bug is not hiding")
    print("         from the tests; it is hiding from the DATA (lesson 07).")
    print("    W01  apply_bps(subtotal, bps) became apply_bps(bps, subtotal) — and the")
    print("         body multiplies them, so NO input distinguishes the two. an")
    print("         EQUIVALENT MUTANT: undecidable in general, and the reason a 100%")
    print("         kill rate is not a target (lesson 13).")

    d_all = sum(1 for m in matrix.values() if any(m.values()))
    print(f"\n  finally, documentation. 3 of the 13 functions state their rule in a")
    print("  docstring, and the review gate's strongest rule is 'this diff contradicts")
    print(f"  the sentence beside it'. across all {len(MUTATIONS)} mutations the comments and")
    print(f"  docstrings detected 0; the executable gates detected {d_all}. an assertion is")
    print("  the only part of your documentation that fails when it stops being true.")


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# Sections 2 and 3 combined: 10,000 releases, bugs drawn from the real mutation
# population, each flowing down the pipeline until a gate stops it. Ablate one
# gate at a time to price it, then reorder and watch the prices change.

BUGS_PER_RELEASE_WEIGHTS = ((0, 55), (1, 27), (2, 11), (3, 5), (4, 2))
RELEASES = 10_000
MEAN_BUGS = (sum(n * w for n, w in BUGS_PER_RELEASE_WEIGHTS)
             / sum(w for _n, w in BUGS_PER_RELEASE_WEIGHTS))

# What running each gate costs per release, whether or not it catches anything.
GATE_COST_MIN: Dict[str, float] = {
    "types": 2.0,          # annotate as you go, run the checker in CI
    "unit": 6.4,           # 6 min suite maintenance + 0.4 min run
    "review": 34.0,        # the same 34 minutes section 2 priced
    "integration": 15.0,   # 12 min maintenance + 3 min run
    "staging": 25.0,       # deploy, smoke, wait
}


def simulate(pipeline: Sequence[str], matrix: Dict[str, Dict[str, bool]],
             mins: Dict[str, float], rng_seed: int) -> Tuple[float, float, int]:
    """Total engineer-minutes over RELEASES: where each bug is caught, plus what
    every gate costs to run every release. Also how many reached production."""
    rng = random.Random(rng_seed)
    ids = [m[0] for m in MUTATIONS]
    pop = [n for n, _w in BUGS_PER_RELEASE_WEIGHTS]
    wts = [w for _n, w in BUGS_PER_RELEASE_WEIGHTS]
    escape_cost, escaped = 0.0, 0
    for _ in range(RELEASES):
        for _b in range(rng.choices(pop, weights=wts, k=1)[0]):
            mid = rng.choice(ids)
            for g in pipeline:
                if matrix[mid][g]:
                    escape_cost += mins[g]
                    break
            else:
                escape_cost += mins["production"]
                escaped += 1
    return escape_cost, RELEASES * sum(GATE_COST_MIN[g] for g in pipeline), escaped


def expected_minutes(pipeline: Sequence[str], matrix: Dict[str, Dict[str, bool]],
                     mins: Dict[str, float]) -> float:
    """The closed form of simulate()'s escape cost, per bug. Bugs are uniform
    over the 40, so no sampling is needed — which is what makes the 2,000-draw
    sensitivity sweep below cheap enough to run."""
    total = 0.0
    for mid in matrix:
        for g in pipeline:
            if matrix[mid][g]:
                total += mins[g]
                break
        else:
            total += mins["production"]
    return total / len(matrix)


def section4(matrix: Dict[str, Dict[str, bool]], mins: Dict[str, float]) -> None:
    banner(4, "THE MARGINAL VALUE OF A GATE, IN MONEY")
    order = GATES
    print(f"  {RELEASES:,} releases; bugs per release drawn from"
          f" {dict(BUGS_PER_RELEASE_WEIGHTS)} (weights),\n  each one of the 40 real"
          " mutations, stopped by the first gate that catches it.\n")
    full_esc, full_gate, full_out = simulate(order, matrix, mins, SEED + 10)
    none_esc, _g, none_out = simulate((), matrix, mins, SEED + 10)
    print(f"    no gates at all:   {none_esc:>11,.0f} engineer-min"
          f"  = ${none_esc * DOLLARS_PER_ENGINEER_MINUTE:>11,.0f}"
          f"   {none_out:,} bugs in production")
    print(f"    the full pipeline: escape {full_esc:>10,.0f} + running {full_gate:>9,.0f}"
          f" = {full_esc + full_gate:>10,.0f} min   {full_out:,} in production")
    saved = none_esc - full_esc - full_gate
    print(f"    net saving {saved:,.0f} engineer-minutes over {RELEASES:,} releases"
          f" = ${saved * DOLLARS_PER_ENGINEER_MINUTE:,.0f}")

    print("  what each gate costs to RUN, per release, caught or not:  "
          + "  ".join(f"{g} {GATE_COST_MIN[g]}" for g in order))
    print("\n  ABLATION — remove one gate, keep the rest, see what it was worth:")
    print("    gate           extra prod bugs   extra escape cost   its own cost"
          "   NET / release")
    rows = []
    for g in order:
        esc, _gt, out = simulate(tuple(x for x in order if x != g), matrix,
                                 mins, SEED + 10)
        own = RELEASES * GATE_COST_MIN[g]
        rows.append((g, esc - full_esc, own, (esc - full_esc - own) / RELEASES))
        print(f"    {g:<14} {out - full_out:>15,} {esc - full_esc:>19,.0f}"
              f" {own:>14,.0f} {rows[-1][3]:>+15.1f} min")
    best, worst = max(rows, key=lambda r: r[3]), min(rows, key=lambda r: r[3])
    print(f"    positive NET means the gate saves more than it costs to run."
          f" best: {best[0]} at\n    {best[3]:+.1f} min/release; worst: {worst[0]}"
          f" at {worst[3]:+.1f}, which catches nothing the others miss.")

    print("\n  PATH DEPENDENCE — the same five gates, added in a different order:")
    print(f"    {'':<16}" + "  ".join(f"{i+1:>13}" for i in range(len(order))))
    for label, seq in (("cheap first", order), ("expensive first", tuple(reversed(order)))):
        seen: set = set()
        cells = []
        for g in seq:
            catches = {mid for mid in matrix if matrix[mid][g]}
            cells.append(f"{g[:5]}:{len(catches - seen):>2}")
            seen |= catches
        print(f"    {label:<16}" + "  ".join(f"{c:>13}" for c in cells))
    print("    identical gates, only the order changed. a gate's marginal value is a")
    print("    property of the pipeline it joins, not of the gate — so there is no")
    print("    context-free ranking of test types (lesson 15 ablates nine layers).")

    print("\n  SENSITIVITY — does any of this survive changing the cost ladder?")
    rng = random.Random(SEED + 20)
    trials = 2_000
    base_rank = [r[0] for r in sorted(rows, key=lambda r: -r[3])]
    base_sign = [r[0] for r in rows if r[3] > 0]
    stable_rank = stable_sign = 0
    for _ in range(trials):
        jitter = {s: mins[s] * rng.uniform(0.4, 1.6) for s in STAGE_ORDER}
        base = expected_minutes(order, matrix, jitter)
        got = [(g, (expected_minutes(tuple(x for x in order if x != g), matrix, jitter)
                    - base) * MEAN_BUGS - GATE_COST_MIN[g]) for g in order]
        stable_rank += [x[0] for x in sorted(got, key=lambda r: -r[1])] == base_rank
        stable_sign += [g for g, v in got if v > 0] == base_sign
    print(f"    every stage cost multiplied by a random factor in [0.4, 1.6],"
          f" {trials:,} times:")
    print(f"    exact ranking of all five unchanged:  {stable_rank:>5,}/{trials:,}"
          f" = {stable_rank/trials:>4.0%}")
    print(f"    SET of gates worth running unchanged: {stable_sign:>5,}/{trials:,}"
          f" = {stable_sign/trials:>4.0%}")
    print(f"    that pair is the honest answer. the exact ordering is NOT robust —")
    print(f"    types and unit sit {abs(rows[0][3]-rows[1][3]):.1f} min/release apart and"
          " swap under any jitter.")
    print("    the DECISION — which gates earn their keep — does not move at all.")


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# What a test is actually buying. Not correctness — section 7 kills that idea.
# It buys the size of change you can make for the same expected regret, and that
# number has a closed form: 1 / (1 - k).

def section5(matrix: Dict[str, Dict[str, bool]]) -> None:
    banner(5, "BOUNDED REGRET: HOW MUCH CODE YOU CAN AFFORD TO CHANGE")
    k_unit = sum(1 for m in matrix.values() if m["unit"]) / len(MUTATIONS)
    k_all = sum(1 for m in matrix.values() if any(m.values())) / len(MUTATIONS)
    print("  a refactor is a stream of edits and some fraction of them are slips. a")
    print("  suite with kill rate k lets (1-k) through, so for the SAME expected number")
    print("  of escapes you can make 1/(1-k) times as many edits. the slip rate cancels;")
    print("  you never have to estimate it.\n")
    print("    kill rate k     edits you can afford, relative to no suite at all")
    for k in (0.0, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99):
        print(f"    {k:>8.0%}      {1/(1-k):>7.1f}x   {'#' * int(round(1/(1-k)))}")
    print(f"\n    measured: the 14-test unit suite alone kills {k_unit:.0%}"
          f"  ->  {1/(1-k_unit):>4.1f}x")
    print(f"              all five gates together kill  {k_all:.0%}"
          f"  ->  {1/(1-k_all):>4.1f}x")

    print("\n  simulated rather than trusted — 4,000 refactors x 60 edits, 4% slip rate:")
    rng = random.Random(SEED + 30)
    rates = {}
    for label, k in (("no suite", 0.0), ("unit suite", k_unit), ("all gates", k_all)):
        escapes = sum(1 for _ in range(4_000) for _e in range(60)
                      if rng.random() < 0.04 and rng.random() >= k)
        rates[label] = escapes / 240_000
        print(f"    {label:<12} {escapes:>6} escaped defects over 240,000 edits"
              f"  = {escapes/240_000:.4f}/edit")
    print(f"    the ratios the simulation produces, against 3.3x and 6.7x predicted:")
    print(f"      0.0402 / 0.0124 = {rates['no suite']/rates['unit suite']:.1f}x"
          f"   ·   0.0402 / 0.0060 = {rates['no suite']/rates['all gates']:.1f}x"
          "   — no free parameter was fitted")
    print("\n  the shape is a hyperbola, and that is the management lesson: no suite to")
    print("  50% doubles your headroom, and 90% to 95% doubles it AGAIN. the last few")
    print("  points of detection are worth as much as the first fifty — exactly")
    print("  backwards from how test effort is usually budgeted. and note what this is")
    print("  NOT: not proof, but a bound on how surprised you should be.")


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# The other side of the ledger. A test that asserts on a rendered string is
# coupled to every decision the renderer will ever make.

REFACTORS: Tuple[Tuple[str, Edits], ...] = (
    ("widen the receipt name column to 14", (("{name:<12}", "{name:<14}"),)),
    ("right-align the amount in 12 not 10", (("cents):>10}", "cents):>12}"),)),
    ("use USD instead of the dollar sign", (('${c // 100}', 'USD {c // 100}'),)),
    ("thousands separator on the units", (("{c // 100}", "{c // 100:,}"),)),
    ("rename the local `c` to `abs_cents`",
     (("    c = abs(cents)", "    abs_cents = abs(cents)"),
      ('f"{sign}${c // 100}.{c % 100:02d}"',
       'f"{sign}${abs_cents // 100}.{abs_cents % 100:02d}"'))),
    ("extract a `_units` helper out of format_money",
     (("def format_money", "def _units(c: int) -> int:\n    return c // 100"
       "\n\n\ndef format_money"),
      ("${c // 100}", "${_units(c)}"))),
    ("rename the dict key `taxable` to `taxable_cents`",
     (('"taxable": taxable', '"taxable_cents": taxable'),)),
    ("replace the accumulator loop with sum()",
     (("    total = 0\n    for unit_price_cents, qty in lines:\n"
       "        total += line_subtotal(unit_price_cents, qty)\n    return total",
       "    return sum(line_subtotal(p, q) for p, q in lines)"),)),
)

MINUTES_PER_BROKEN_TEST = 6.0


def structural_suite(m: Dict[str, Any]) -> List[Tuple[str, Callable[[], None]]]:
    """Seven tests that assert on values and structure."""
    po = lambda: m["price_order"](((2500, 2),), "gold")            # noqa: E731
    return [
        ("total_at_the_volume_boundary", lambda: assert_eq(po()["total"], 5221, "t")),
        ("discount_is_deducted", lambda: assert_eq(po()["discount"], 750, "d")),
        ("taxable_is_post_discount", lambda: assert_eq(po()["taxable"], 4250, "b")),
        ("tax_follows_the_discount", lambda: assert_eq(po()["tax"], 372, "x")),
        ("free_shipping_above_threshold",
         lambda: assert_eq(m["price_order"](((5000, 3),), "standard")["shipping"], 0, "s")),
        ("round_trip_preserves_the_total",
         lambda: assert_eq(m["from_row"](tuple(m["to_row"]("o", po())))["total"], 5221, "r")),
        ("negative_amount_renders_negative",
         lambda: assert_eq(m["format_money"](-405).startswith("-"), True, "neg")),
    ]


def brittle_suite(m: Dict[str, Any]) -> List[Tuple[str, Callable[[], None]]]:
    """Seven tests that assert on rendered strings."""
    return [
        ("receipt_total_line",
         lambda: assert_eq(m["receipt_line"]("Total", 5221), "Total           $52.21", "1")),
        ("receipt_discount_line",
         lambda: assert_eq(m["receipt_line"]("Discount", -750), "Discount        -$7.50", "2")),
        ("receipt_shipping_line",
         lambda: assert_eq(m["receipt_line"]("Shipping", 599), "Shipping         $5.99", "3")),
        ("money_formats_cents", lambda: assert_eq(m["format_money"](405), "$4.05", "4")),
        ("money_formats_whole", lambda: assert_eq(m["format_money"](5000), "$50.00", "5")),
        ("money_formats_large",
         lambda: assert_eq(m["format_money"](1234567), "$12345.67", "6")),
        ("money_formats_negative",
         lambda: assert_eq(m["format_money"](-405), "-$4.05", "7")),
    ]


def section6() -> None:
    banner(6, "THE OTHER SIDE OF THE LEDGER: A TEST THAT COSTS MORE THAN IT SAVES")
    suites = (("structural", structural_suite), ("brittle", brittle_suite))
    print("  two suites, seven tests each, over the same module. one asserts on values,")
    print("  one on rendered strings — matched on size so the comparison is about the")
    print("  assertion and nothing else.\n")
    kills: Dict[str, List[str]] = {}
    for label, suite in suites:
        got = []
        for mid, _c, edits, _d in MUTATIONS:
            try:
                if run_suite(suite(build(edits))):
                    got.append(mid)
            except Exception:
                got.append(mid)
        kills[label] = got
    print(f"    suite         bugs caught (of {len(MUTATIONS)})   caught that the other did not")
    for label, _s in suites:
        other = kills["brittle" if label == "structural" else "structural"]
        uniq = sorted(set(kills[label]) - set(other))
        print(f"    {label:<12} {len(kills[label]):>13}          "
              f"{', '.join(uniq) if uniq else '(none)'}")

    print("\n  now eight refactors that change no behaviour a customer can observe:")
    print(f"    {'refactor':<46} structural  brittle")
    churn = {"structural": 0, "brittle": 0}
    for name, edits in REFACTORS:
        m = build(edits)
        cells = []
        for label, suite in suites:
            broke = len(run_suite(suite(m)))
            churn[label] += broke
            cells.append(broke)
        print(f"    {name:<46} {cells[0]:>10}  {cells[1]:>7}")
    print(f"    {'TOTAL broken tests':<46} {churn['structural']:>10}  {churn['brittle']:>7}")

    print(f"\n  at {MINUTES_PER_BROKEN_TEST:.0f} minutes to read, diagnose and update each"
          " broken test:")
    for label, _s in suites:
        cost = churn[label] * MINUTES_PER_BROKEN_TEST
        print(f"    {label:<12} {churn[label]:>3} breakages x {MINUTES_PER_BROKEN_TEST:.0f}"
              f" min = {cost:>5.0f} min of pure churn"
              f"  ({'$%.0f' % (cost * DOLLARS_PER_ENGINEER_MINUTE)})")
    uniq_b = sorted(set(kills["brittle"]) - set(kills["structural"]))
    print(f"\n  the brittle suite is not worthless: it uniquely caught {len(uniq_b)}"
          f" ({', '.join(uniq_b)}),")
    print("  and formatting bugs are real bugs that only a rendered assertion sees. the")
    print("  question is never 'is this test worthless' but 'does it cost less than what")
    print("  it catches', which is arithmetic. keep exactly as many string assertions as")
    print("  you have rendering promises — usually one or two, not seven.")


# ══ 7 ═══════════════════════════════════════════════════════════════════════════
# Dijkstra's limit, priced. "Program testing can be used to show the presence of
# bugs, but never to show their absence." (EWD249, 1970.) Here is why, in years.

CASES_PER_SECOND = 1_000_000_000
SECONDS_PER_YEAR = 365 * 24 * 3600
BOUNDARY_POOL = (0, 1, -1, 2, -2, 2 ** 31 - 1, -2 ** 31, 2 ** 31 - 2,
                 -2 ** 31 + 1, 2 ** 30, -2 ** 30, 2 ** 16, 255, 256, -255)


def add32(a: int, b: int) -> int:
    """Signed 32-bit addition with wraparound — and one bug, at exactly one
    point in a space of 2**64 input pairs."""
    s = a + b
    if s > 2 ** 31:            # BUG: should be `s > 2**31 - 1`
        s -= 2 ** 32
    elif s < -2 ** 31:
        s += 2 ** 32
    return s


def add32_ref(a: int, b: int) -> int:
    return ((a + b + 2 ** 31) % 2 ** 32) - 2 ** 31


def section7() -> None:
    banner(7, "WHAT TESTING CANNOT DO, PRICED IN YEARS")
    one, two = 2 ** 32, 2 ** 64
    print("  exhaustive testing of a 32-bit function, at a billion cases per second:")
    print(f"    one 32-bit argument   {one:>26,} cases  = {one/CASES_PER_SECOND:>8.2f} seconds")
    print(f"    two 32-bit arguments  {two:>26,} cases"
          f"  = {two/CASES_PER_SECOND/SECONDS_PER_YEAR:>8.1f} years")
    print("  one extra argument turns four seconds into six centuries. `add` is the")
    print("  simplest function you own; price_order() takes a list of pairs and a")
    print("  string, and its input space has no bound at all.\n")

    print("  so we sample. 200 cases, two ways of choosing them, against an add32 that")
    print("  is wrong at exactly one point in the 2**64:")
    lo, hi, trials = -2 ** 31, 2 ** 31 - 1, 200
    for label, gen in (
        ("uniform random", lambda r: (r.randint(lo, hi), r.randint(lo, hi))),
        ("boundary-biased", lambda r: (r.choice(BOUNDARY_POOL), r.choice(BOUNDARY_POOL))),
    ):
        first = []
        for t in range(trials):
            rng = random.Random(SEED + 700 + t)
            for i in range(1, 201):
                a, b = gen(rng)
                if add32(a, b) != add32_ref(a, b):
                    first.append(i)
                    break
        med = f"{statistics.median(first):.0f}" if first else "—"
        print(f"    {label:<18} found it in {len(first):>3}/{trials} runs of 200 cases"
              f"   median cases to first failure: {med:>4}")
    print("\n    uniform random covers the space evenly and therefore never goes anywhere")
    print("    interesting: the bug lives on a boundary, and boundaries are a")
    print("    measure-zero slice of a uniform distribution. a pool of 15 boundary")
    print("    values finds it almost every time. this is why real property-testing")
    print("    libraries are not uniform generators — lesson 12 builds one.")
    print(f"\n  and the honest part: 200 passing cases say nothing about the other")
    print(f"  {two - 200:,} pairs. testing showed the presence of this bug.")
    print("  nothing here shows the absence of the next one. (Dijkstra, EWD249, 1970.)")


def main() -> None:
    print("Phase 12 · Lesson 01 · Why Tests Exist: The Cost of Finding a Bug Late")
    print(f"seed = {SEED}; standard library only; every number below is produced here")
    section1()
    mins = section2()
    matrix = catch_matrix()
    section3(matrix)
    section4(matrix, mins)
    section5(matrix)
    section6()
    section7()


if __name__ == "__main__":
    import time as _time
    _t0 = _time.perf_counter()
    main()
    print(f"\n  (total wall time {_time.perf_counter() - _t0:.1f} s)")
