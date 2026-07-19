"""Anatomy of a unit test: two suites of the same size over one module, scored.

Companion program for phases/12-testing-and-quality/03-anatomy-of-a-unit-test/
docs/en.md (Phase 12, Lesson 03). Sources: Dijkstra, "Notes on Structured
Programming", 1970 (testing shows presence, never absence); DeMillo, Lipton &
Sayward, "Hints on Test Data Selection", IEEE Computer 11(4), 1978 (seeded
faults as a measure of a suite); IEEE Std 610.12-1990 (unit testing defined).
Standard library only. Seeded with random.Random(17). Exits 0 in about 1 s.
"""

from __future__ import annotations

import ast
import inspect
import math
import random
import re
import sys
import textwrap
import time
import traceback
import types
from typing import Any, Callable, Iterable, Optional, Tuple

RNG_SEED = 17
START = time.perf_counter()


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# ---------------------------------------------------------------------------
# THE MODULE UNDER TEST
# ---------------------------------------------------------------------------
# Kept as source text so that a "bug" is a real edit to real code, compiled and
# imported like any other module. Money is integer cents everywhere: a float
# has no exact representation for 0.10, and a pricing engine that drifts by a
# cent per order drifts by real money at volume.

PRICING_V1 = '''
COUPON_MIN_CENTS = 1000
DEFAULT_TAX_BPS = 825
TIERS = ((100000, 1500), (20000, 1000), (5000, 500))
COUPONS = {"SAVE10": (1000, 30), "SAVE25": (2500, 7), "LEGACY5": (500, 0)}

class PricingError(Exception):
    code = "pricing_error"

class InvalidQuantity(PricingError):
    code = "invalid_quantity"

class UnknownCoupon(PricingError):
    code = "unknown_coupon"

class CouponExpired(PricingError):
    code = "coupon_expired"

class Quote:
    def __init__(self, subtotal_cents, discount_cents, tax_cents,
                 total_cents, notes):
        self.subtotal_cents = subtotal_cents
        self.discount_cents = discount_cents
        self.tax_cents = tax_cents
        self.total_cents = total_cents
        self.notes = notes

    def __repr__(self):
        return ("Quote(subtotal_cents=%d, discount_cents=%d, tax_cents=%d, "
                "total_cents=%d, notes=%r)" % (
                    self.subtotal_cents, self.discount_cents, self.tax_cents,
                    self.total_cents, self.notes))

def div_round(num, den, mode="half_even"):
    """num/den to the nearest integer; a .5 tie is broken by `mode`."""
    q, r = divmod(num, den)
    twice = 2 * r
    if twice > den:
        q += 1
    elif twice == den:
        if mode == "half_up" or q % 2 == 1:
            q += 1
    return q

def subtotal_cents(items):
    total = 0
    for sku, unit_cents, qty in items:
        if qty < 1:
            raise InvalidQuantity(
                "quantity for %s must be at least 1, got %d" % (sku, qty))
        total += unit_cents * qty
    return total

def _tier_bps(subtotal):
    for threshold, bps in TIERS:
        if subtotal >= threshold:
            return bps
    return 0

def _coupon_bps(code, day):
    if code is None:
        return 0
    if code not in COUPONS:
        raise UnknownCoupon("no such coupon: %s" % code)
    bps, valid_days = COUPONS[code]
    if day > valid_days:
        raise CouponExpired("coupon %s expired on day %d" % (code, valid_days))
    return bps

def price_order(items, coupon=None, day=0, tax_bps=DEFAULT_TAX_BPS, audit=None):
    sub = subtotal_cents(items)
    tier = _tier_bps(sub)
    cpn = _coupon_bps(coupon, day)
    if sub < COUPON_MIN_CENTS:
        cpn = 0
    bps = max(tier, cpn)
    discount = div_round(sub * bps, 10000)
    taxable = sub - discount
    tax = div_round(taxable * tax_bps, 10000)
    total = taxable + tax
    notes = ("tier:%d" % tier, "coupon:%d" % cpn)
    if audit is not None:
        audit("discount", discount)
        audit("tax", tax)
    return Quote(sub, discount, tax, total, notes)

def format_receipt(q):
    return "Subtotal: $%.2f | Discount: -$%.2f | Tax: $%.2f | Total: $%.2f" % (
        q.subtotal_cents / 100, q.discount_cents / 100,
        q.tax_cents / 100, q.total_cents / 100)
'''

# The refactor of section 8: four cosmetic edits and one structural one. No
# money changes. Section 8 proves that against every case in both grids before
# it counts a single broken test.
REFACTOR_EDITS: tuple[tuple[str, str], ...] = (
    # 1 · rename an incidental field: notes -> applied
    ("notes", "applied"),
    ("tier:%d", "tier=%d"),
    ("coupon:%d", "coupon=%d"),
    # 2 · reword an error message; the exception TYPE is untouched
    ('"quantity for %s must be at least 1, got %d" % (sku, qty)',
     '"invalid quantity %d for line %s (minimum 1)" % (qty, sku)'),
    # 3 · reformat the receipt
    ('"Subtotal: $%.2f | Discount: -$%.2f | Tax: $%.2f | Total: $%.2f" % (',
     '"TOTAL %.2f USD (sub %.2f, disc %.2f, tax %.2f)" % (' ),
    ("q.subtotal_cents / 100, q.discount_cents / 100,\n        " "q.tax_cents / 100, q.total_cents / 100)",
     "q.total_cents / 100, q.subtotal_cents / 100,\n        " "q.discount_cents / 100, q.tax_cents / 100)"),
    # 4 · split the private tier helper in two
    ("def _tier_bps(subtotal):\n    for threshold, bps in TIERS:\n" "        if subtotal >= threshold:\n            return bps\n    return 0",
     "def _tier_index(subtotal):\n    for i, (threshold, _bps) in enumerate(TIERS):\n"
     "        if subtotal >= threshold:\n            return i\n    return -1\n\n\n" "def _bps_for_index(i):\n    return 0 if i < 0 else TIERS[i][1]"),
    ("tier = _tier_bps(sub)", "tier = _bps_for_index(_tier_index(sub))"),
    # 5 · batch the two audit events into one
    ('audit("discount", discount)\n        audit("tax", tax)',
     'audit("totals", (discount, tax))'),
)


def refactored_source(src: str) -> str:
    for old, new in REFACTOR_EDITS:
        if old not in src:
            raise SystemExit(f"refactor edit no longer applies: {old[:40]!r}")
        src = src.replace(old, new)
    return src


PRICING_V2 = refactored_source(PRICING_V1)


# ---------------------------------------------------------------------------
# THE 25 SEEDED BUGS
# ---------------------------------------------------------------------------
# Each is a one-line edit to PRICING_V1: the kind of thing that survives code
# review because it looks like the code around it. Categories are named so
# section 6 can ask which classes of bug which style of test actually finds.
# Seeding faults and scoring a suite on them is mutation testing; Lesson 13
# builds the engine that generates these automatically instead of by hand.

Mutant = tuple[str, str, str, str]  # (id, category, old, new)

MUTANTS: tuple[Mutant, ...] = (
    ("B01", "boundary", "if subtotal >= threshold:", "if subtotal > threshold:"),
    ("B02", "boundary", "(100000, 1500)", "(100001, 1500)"),
    ("B03", "boundary", "(20000, 1000)", "(20001, 1000)"),
    ("B04", "boundary", "(5000, 500)", "(4999, 500)"),
    ("B05", "boundary", "if day > valid_days:", "if day >= valid_days:"),
    ("B06", "boundary", "if sub < COUPON_MIN_CENTS:", "if sub <= COUPON_MIN_CENTS:"),
    ("B07", "boundary", "if qty < 1:", "if qty < 0:"),
    ("R01", "rounding", "if twice > den:", "if twice >= den:"),
    ("R02", "rounding", 'mode == "half_up" or q % 2 == 1',
     'mode == "half_up" or q % 2 == 0'),
    ("R03", "rounding", "tax = div_round(taxable * tax_bps, 10000)",
     'tax = div_round(taxable * tax_bps, 10000, "half_up")'),
    ("R04", "rounding", 'mode == "half_up" or q % 2 == 1',
     'mode == "half_up" or q % 2 != 0'),
    ("A01", "arithmetic", "total += unit_cents * qty", "total += unit_cents + qty"),
    ("A02", "arithmetic", "taxable = sub - discount", "taxable = sub + discount"),
    ("A03", "arithmetic", "total = taxable + tax", "total = taxable - tax"),
    ("A04", "arithmetic", "discount = div_round(sub * bps, 10000)",
     "discount = div_round(sub * bps, 1000)"),
    ("A05", "arithmetic", "bps = max(tier, cpn)", "bps = tier + cpn"),
    ("C01", "conditional", "bps = max(tier, cpn)", "bps = min(tier, cpn)"),
    ("C02", "conditional", "            return bps\n    return 0",
     "            return bps\n    return 500"),
    ("C03", "conditional", "if code is None:", "if code is not None:"),
    ("E01", "exception", "            raise InvalidQuantity(\n"
     '                "quantity for %s must be at least 1, got %d" % (sku, qty))',
     "            qty = 1"),
    ("E02", "exception", "raise CouponExpired(", "raise UnknownCoupon("),
    ("E03", "exception", 'raise UnknownCoupon("no such coupon: %s" % code)',
     "return 0"),
    ("D01", "default", "tax_bps=DEFAULT_TAX_BPS", "tax_bps=800"),
    ("D02", "field", "return Quote(sub, discount, tax, total, notes)",
     "return Quote(sub, 0, tax, total, notes)"),
    ("D03", "field", 'notes = ("tier:%d" % tier, "coupon:%d" % cpn)',
     'notes = ("tier=%d" % tier, "coupon=%d" % cpn)'),
)

MUTANT_SUBJECT = {
    "B01": "discount", "B02": "discount", "B03": "discount", "B04": "discount",
    "B05": "coupon", "B06": "coupon", "B07": "quantity", "R01": "discount",
    "R02": "discount", "R03": "tax", "R04": "discount", "A01": "subtotal",
    "A02": "tax", "A03": "total", "A04": "discount", "A05": "discount",
    "C01": "discount", "C02": "discount", "C03": "coupon", "E01": "quantity",
    "E02": "coupon", "E03": "coupon", "D01": "tax", "D02": "discount",
    "D03": "notes",
}


def mutate(src: str, old: str, new: str) -> str:
    if src.count(old) != 1:
        raise SystemExit(f"mutation target is not unique: {old[:48]!r}")
    return src.replace(old, new, 1)


CODE_CACHE: dict[str, Any] = {}


def load(src: str, name: str) -> types.ModuleType:
    """Compile once, then hand every caller its own fresh module object."""
    code = CODE_CACHE.get(name)
    if code is None:
        code = compile(src, f"<{name}>", "exec")
        CODE_CACHE[name] = code
    mod = types.ModuleType(name)
    exec(code, mod.__dict__)
    return mod


MUTANT_SRC = {m[0]: mutate(PRICING_V1, m[2], m[3]) for m in MUTANTS}
MUTANT_IDS = [m[0] for m in MUTANTS]
MUTANT_CAT = {m[0]: m[1] for m in MUTANTS}


# ---------------------------------------------------------------------------
# THE TWO SUITES
# ---------------------------------------------------------------------------
# Both are ordinary Python: a test is a function that runs the code and asserts
# a fact about it. `mod` is the module under test, handed in fresh, so a test
# that monkey-patches it cannot leak into the next one.
#
# The BAD suite is not a straw man. Every one of these is a shape that ships:
# the fourteen-assertion happy path, the exact-string assertion, the test that
# stubs out the logic it is nominally testing, the test of the constructor.


def bad_test_1(mod):
    q = mod.price_order((("widget", 2500, 4), ("cable", 1500, 2)))
    assert q is not None
    assert q.subtotal_cents == 13000
    assert q.subtotal_cents > 0
    assert q.discount_cents == 650
    assert q.discount_cents < q.subtotal_cents
    assert q.tax_cents == 1019
    assert q.tax_cents > 0
    assert q.total_cents == 13369
    assert q.total_cents > q.subtotal_cents - q.discount_cents
    assert isinstance(q.total_cents, int)
    assert q.notes == ("tier:500", "coupon:0")
    assert len(q.notes) == 2
    q2 = mod.price_order((("widget", 2500, 4), ("cable", 1500, 2)), None, 0, 825)
    assert q2.total_cents == q.total_cents
    assert mod.format_receipt(q).startswith("Subtotal: $130.00")

def bad_test_pricing(mod):
    q = mod.price_order((("widget", 2500, 4),))
    assert mod.format_receipt(q) == (
        "Subtotal: $100.00 | Discount: -$5.00 | Tax: $7.84 | Total: $102.84")

def bad_test_happy_path(mod):
    mod._tier_bps = lambda subtotal: 1000
    mod._coupon_bps = lambda code, day: 0
    q = mod.price_order((("widget", 2500, 4),))
    assert q.discount_cents == 1000

def bad_test_it_works(mod):
    q = mod.price_order((("widget", 2500, 4),))
    assert q
    assert q.total_cents

def bad_test_discount(mod):
    try:
        mod.price_order((("widget", 2500, 0),))
        assert False
    except mod.InvalidQuantity as exc:
        assert str(exc) == "quantity for widget must be at least 1, got 0"

def bad_test_getter(mod):
    q = mod.Quote(1000, 100, 74, 974, ("tier:0",))
    assert q.subtotal_cents == 1000
    assert q.discount_cents == 100
    assert q.tax_cents == 74
    assert q.total_cents == 974

def bad_test_tier_helper(mod):
    assert mod._tier_bps(6000) == 500
    assert mod._tier_bps(30000) == 1000

def bad_test_coupon(mod):
    calls = []
    mod.price_order((("widget", 2500, 4),), "SAVE10", 0, 825,
                    lambda kind, amount: calls.append((kind, amount)))
    assert [c[0] for c in calls] == ["discount", "tax"]
    assert len(calls) == 2

def bad_test_smoke(mod):
    for subtotal in (100, 2500, 9000, 45000):
        q = mod.price_order((("sku", subtotal, 1),))
        assert q.total_cents >= 0

def bad_test_repr(mod):
    q = mod.price_order((("widget", 2500, 4),))
    assert "Quote(" in repr(q)
    assert "total_cents=10284" in repr(q)


# The GOOD suite. Same language, same module, same budget of lines. Every name
# is a proposition; every test drives the public entry point; every table walks
# a boundary rather than a comfortable middle.

def good_test_tier_discount_changes_only_at_the_documented_thresholds(mod):
    cases = ((4999, 0), (5000, 250), (5001, 250), (19999, 1000), (20000, 2000),
             (20001, 2000), (99999, 10000), (100000, 15000), (100001, 15000))
    for subtotal, expected in cases:
        q = mod.price_order((("sku", subtotal, 1),))
        assert q.discount_cents == expected, (subtotal, q.discount_cents)

def good_test_percentage_rounding_breaks_exact_halves_to_even(mod):
    cases = ((5010, 250), (5030, 252), (5050, 252),
             (5070, 254), (5090, 254), (5110, 256))
    for subtotal, expected in cases:
        q = mod.price_order((("sku", subtotal, 1),))
        assert q.discount_cents == expected, (subtotal, q.discount_cents)

def good_test_tax_rounding_breaks_exact_halves_to_even(mod):
    for subtotal, expected in ((200, 16), (600, 50), (1000, 82)):
        q = mod.price_order((("sku", subtotal, 1),))
        assert q.tax_cents == expected, (subtotal, q.tax_cents)

def good_test_tax_uses_the_declared_default_rate_when_none_is_passed(mod):
    assert mod.price_order((("sku", 10000, 1),)).tax_cents == 784

def good_test_tax_is_charged_on_the_discounted_amount(mod):
    q = mod.price_order((("sku", 20000, 1),), "SAVE25", 0)
    assert (q.tax_cents, q.total_cents) == (1238, 16238)

def good_test_coupon_and_tier_discounts_do_not_stack(mod):
    q = mod.price_order((("sku", 20000, 1),), "SAVE25", 0)
    assert q.discount_cents == 5000

def good_test_coupon_still_applies_on_its_last_valid_day(mod):
    assert mod.price_order((("sku", 2000, 1),), "SAVE10", 30).discount_cents == 200

def good_test_coupon_is_rejected_the_day_after_it_expires(mod):
    try:
        mod.price_order((("sku", 2000, 1),), "SAVE10", 31)
    except mod.CouponExpired as exc:
        assert exc.code == "coupon_expired"
    else:
        raise AssertionError("expected CouponExpired")

def good_test_coupon_is_ignored_below_the_minimum_order_value(mod):
    for subtotal, expected in ((999, 0), (1000, 100)):
        q = mod.price_order((("sku", subtotal, 1),), "SAVE10", 0)
        assert q.discount_cents == expected, (subtotal, q.discount_cents)

def good_test_unknown_coupon_code_is_rejected(mod):
    try:
        mod.price_order((("sku", 2000, 1),), "NOPE", 0)
    except mod.UnknownCoupon as exc:
        assert exc.code == "unknown_coupon"
    else:
        raise AssertionError("expected UnknownCoupon")

def good_test_quantity_below_one_is_rejected_before_pricing(mod):
    try:
        mod.price_order((("sku", 500, 0),))
    except mod.InvalidQuantity as exc:
        assert exc.code == "invalid_quantity"
    else:
        raise AssertionError("expected InvalidQuantity")

def good_test_subtotal_sums_unit_price_times_quantity_per_line(mod):
    assert mod.price_order((("a", 250, 3), ("b", 400, 2))).subtotal_cents == 1550

def good_test_subtotal_is_zero_for_an_order_with_no_lines(mod):
    assert mod.price_order(()).subtotal_cents == 0

def good_test_quote_totals_are_internally_consistent(mod):
    for subtotal in (999, 5000, 20000, 100000):
        q = mod.price_order((("sku", subtotal, 1),))
        assert q.total_cents == q.subtotal_cents - q.discount_cents + q.tax_cents


TestFn = Callable[[types.ModuleType], None]


def collect(prefix: str) -> list[TestFn]:
    fns = [v for k, v in globals().items()
           if k.startswith(prefix) and callable(v)]
    return sorted(fns, key=lambda f: f.__code__.co_firstlineno)


BAD_SUITE = collect("bad_test_")
GOOD_SUITE = collect("good_test_")


# ---------------------------------------------------------------------------
# THE RUNNER — twelve lines, because a test framework is not magic
# ---------------------------------------------------------------------------


def run_test(test: TestFn, src_name: str, src: str) -> str | None:
    """Return None if the test passed, else a one-line failure reason.

    Reporting the failing source line is the whole of what pytest's much
    admired assertion rewriting buys you, minus the operand values.
    """
    mod = load(src, src_name)
    try:
        test(mod)
    except AssertionError as exc:
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        return (frame.line or "assert").strip()
    except Exception as exc:  # a crash is a failure, same as any framework
        return f"{type(exc).__name__}: {exc}"
    return None


def kills(suite: Iterable[TestFn]) -> dict[str, set[str]]:
    """mutant id -> set of test names that failed on it (i.e. killed it)."""
    out: dict[str, set[str]] = {}
    for mid in MUTANT_IDS:
        out[mid] = {t.__name__ for t in suite
                    if run_test(t, mid, MUTANT_SRC[mid]) is not None}
    return out


def logical_lines(fn: TestFn) -> int:
    src = textwrap.dedent(inspect.getsource(fn))
    return sum(1 for line in src.splitlines()
               if line.strip() and not line.strip().startswith("#"))


def suite_lines(suite: Iterable[TestFn]) -> int:
    return sum(logical_lines(t) for t in suite)


# ---------------------------------------------------------------------------
# THE INPUT GRIDS
# ---------------------------------------------------------------------------
# ORACLE_GRID is systematic and deliberately includes every threshold and every
# rounding tie: it exists to prove that a mutant is observable at all.
# RANDOM_GRID is what a plausible catalogue produces — round-ish prices, small
# quantities, valid coupons — and it exists to measure how often a bug shows up
# in an input nobody chose on purpose.

Case = Tuple[Tuple[Tuple[str, int, int], ...], Optional[str], int]

CATALOGUE = (499, 750, 999, 1250, 1500, 2000, 2500, 3000, 4999, 5000,
             7500, 9999, 12500, 20000, 25000, 50000)
COUPON_CODES = (None, "SAVE10", "SAVE25", "LEGACY5", "NOPE")


def build_oracle_grid() -> list[Case]:
    grid: list[Case] = []
    edges = [0, 1, 199, 200, 600, 998, 999, 1000, 1001, 4998, 4999, 5000, 5001,
             5010, 5030, 5050, 5070, 19999, 20000, 20001, 99999, 100000, 100001]
    for sub in edges:
        for code in COUPON_CODES:
            for day in (0, 6, 7, 8, 29, 30, 31):
                grid.append(((("sku", sub, 1),), code, day))
    grid.append(((("a", 250, 3), ("b", 400, 2)), None, 0))
    grid.append(((("a", 500, 0),), None, 0))
    grid.append(((("a", 500, -2),), None, 0))
    return grid


def build_random_grid(n: int) -> list[Case]:
    rng = random.Random(RNG_SEED)
    grid: list[Case] = []
    for _ in range(n):
        lines = tuple(
            (f"s{i}", rng.choice(CATALOGUE), rng.randint(1, 4))
            for i in range(rng.randint(1, 3)))
        code = rng.choice(COUPON_CODES[:4])
        grid.append((lines, code, rng.randint(0, 40)))
    return grid


ORACLE_GRID = build_oracle_grid()
RANDOM_GRID = build_random_grid(8000)


def outcome_full(mod: types.ModuleType, case: Case) -> tuple:
    """Everything a caller can observe, including labels and messages."""
    items, code, day = case
    try:
        q = mod.price_order(items, code, day)
    except Exception as exc:
        return (type(exc).__name__, str(exc))
    return (q.subtotal_cents, q.discount_cents, q.tax_cents, q.total_cents,
            q.notes)


def outcome_money(mod: types.ModuleType, case: Case) -> tuple:
    """Only the money and the error TYPE — what a caller actually depends on."""
    items, code, day = case
    try:
        q = mod.price_order(items, code, day)
    except Exception as exc:
        return (type(exc).__name__,)
    return (q.subtotal_cents, q.discount_cents, q.tax_cents, q.total_cents)


# ---------------------------------------------------------------------------
# 1 · WHAT A "UNIT" IS — AND THE CEILING YOUR CHOICE OF UNIT SETS
# ---------------------------------------------------------------------------


def section_1() -> dict[str, Any]:
    banner("1 · WHAT A 'UNIT' IS, AND THE CEILING YOUR CHOICE OF UNIT SETS")
    base = load(PRICING_V1, "V1")
    src_lines = sum(1 for line in PRICING_V1.splitlines() if line.strip())
    print(f"  module under test: {src_lines} lines, 5 public names, " f"2 private helpers, 4 exception types")
    print(f"  seeded bugs: {len(MUTANTS)}, each a single edit to that source\n")

    golden_o = [outcome_full(base, c) for c in ORACLE_GRID]
    observable = {}
    for mid in MUTANT_IDS:
        mod = load(MUTANT_SRC[mid], mid)
        observable[mid] = any(outcome_full(mod, c) != golden_o[i]
                              for i, c in enumerate(ORACLE_GRID))

    dead = [m for m in MUTANT_IDS if not observable[m]]
    print(f"  {len(ORACLE_GRID)} systematic cases covering every threshold, " f"every rounding tie and every coupon day:")
    print(f"    {len(MUTANT_IDS) - len(dead)} of {len(MUTANT_IDS)} bugs change " f"an observable result on at least one case")
    print(f"    {len(dead)} do not: {', '.join(dead) if dead else '(none)'} " f"-> equivalent mutant, unkillable by any test")
    print("  R04 turned `q % 2 == 1` into `q % 2 != 0` and q is never negative:")
    print("  an EQUIVALENT MUTANT, a source change with no behavioural")
    print("  consequence. Deciding which ones they are is undecidable in")
    print("  general, so 100% is not a target. Lesson 13 measures the rate.\n")

    # A test can only kill a bug in code it actually runs. Whichever function
    # you point a test at, its reach is that function plus everything it calls.
    fn_of = {
        "div_round": ("R01", "R02", "R04"),
        "subtotal_cents": ("A01", "B07", "E01"),
        "_tier_bps": ("B01", "B02", "B03", "B04", "C02"),
        "_coupon_bps": ("B05", "C03", "E02", "E03"),
    }
    fn_of["price_order"] = tuple(MUTANT_IDS)
    live_total = len(MUTANT_IDS) - len(dead)
    print(f"  {'if you point a test at...':<26}{'it also runs':>26}" f"{'bugs in reach':>15}{'ceiling':>9}")
    calls = {"div_round": "-", "subtotal_cents": "-", "_tier_bps": "-",
             "_coupon_bps": "-", "price_order": "all four helpers"}
    for fn, ids in fn_of.items():
        n = len([i for i in ids if observable[i]])
        print(f"  {fn + '()':<26}{calls[fn]:>26}{n:>15}{n / live_total:>8.0%}")
    print("\n  Testing _tier_bps() directly is what 'one test file per class'")
    print(f"  pushes you toward, and it caps you at {5 / live_total:.0%} before you have")
    print("  written a single assertion — nothing in that file can reach the")
    print("  rounding, the coupon window or the tax base. A unit is a behaviour")
    print("  the caller can name, not whichever function the IDE stubbed out.")
    return {"observable": observable, "dead": dead, "fn_of": fn_of,
            "live_total": live_total}


# ---------------------------------------------------------------------------
# 2 · ARRANGE / ACT / ASSERT — THE SHAPE OF BOTH SUITES, BY AST
# ---------------------------------------------------------------------------
# Not opinion: parse the suites and count. An "act" is a call into the module
# under test. More than one act in a test means more than one unit under test.

PUBLIC_CALLS = {"price_order", "subtotal_cents", "div_round", "format_receipt",
                "_tier_bps", "_coupon_bps", "Quote"}


def shape(fn: TestFn) -> tuple[int, int, int]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    asserts = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Assert))
    asserts += sum(1 for n in ast.walk(tree) if isinstance(n, ast.Raise))
    acts = sum(1 for n in ast.walk(tree)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr in PUBLIC_CALLS)
    return asserts, acts, logical_lines(fn)


def section_2() -> None:
    banner("2 · ARRANGE / ACT / ASSERT — BOTH SUITES, PARSED AND COUNTED")
    print("  an 'act' is a call into the module under test. Two acts in one")
    print("  test is two units under test, and the failure cannot say which.\n")
    out = {}
    for label, suite in (("bad", BAD_SUITE), ("good", GOOD_SUITE)):
        rows = [(t.__name__,) + shape(t) for t in suite]
        n = len(rows)
        tot_a = sum(r[1] for r in rows)
        tot_c = sum(r[2] for r in rows)
        one_act = sum(1 for r in rows if r[2] == 1)
        out[label] = {"tests": n, "asserts": tot_a, "acts": tot_c,
                      "max_asserts": max(r[1] for r in rows),
                      "one_act": one_act, "lines": sum(r[3] for r in rows)}
        print(f"  {label.upper()} SUITE — {n} tests, {out[label]['lines']} lines")
        print(f"  {'test':<66}{'asserts':>9}{'acts':>6}{'lines':>7}")
        for name, a, c, l in rows:
            flag = "  <--" if a >= 5 or c >= 2 else ""
            print(f"  {name:<66}{a:>9}{c:>6}{l:>7}{flag}")
        print(f"  {'':<66}{tot_a:>9}{tot_c:>6}{out[label]['lines']:>7}")
        print(f"    asserts/test {tot_a / n:.1f} (max {out[label]['max_asserts']})" f"  ·  single-act tests {one_act}/{n}\n")
    b, g = out["bad"], out["good"]
    print(f"  Same module, {b['lines']} lines each. The bad suite puts {b['asserts']} assertions")
    print(f"  in {b['tests']} tests with {b['max_asserts']} in its worst; the good suite spreads " f"{g['asserts']} across {g['tests']},")
    print(f"  maximum {g['max_asserts']}, and every one of them has exactly one act. AAA is")
    print("  not a style rule: it is the shape that makes 'what broke' answerable")
    print("  from the name alone, and section 4 prices abandoning it.")
    return out


# ---------------------------------------------------------------------------
# 3 · THE MATCHED-SIZE SHOWDOWN
# ---------------------------------------------------------------------------


def section_3(ctx: dict[str, Any]) -> dict[str, Any]:
    banner("3 · SAME MODULE, SAME NUMBER OF LINES, SCORED ON THE SAME 25 BUGS")
    observable = ctx["observable"]
    killable = [m for m in MUTANT_IDS if observable[m]]

    for label, suite in (("bad", BAD_SUITE), ("good", GOOD_SUITE)):
        broken = [t.__name__ for t in suite
                  if run_test(t, "V1", PRICING_V1) is not None]
        if broken:
            raise SystemExit(f"{label} suite is red on clean code: {broken}")
    print(f"  self-check: all {len(BAD_SUITE) + len(GOOD_SUITE)} tests pass " f"against the unmutated module.\n")

    kb, kg = kills(BAD_SUITE), kills(GOOD_SUITE)
    print(f"  {'bug':>5}{'category':>13}{'bad suite':>26}{'good suite':>26}")
    for mid in MUTANT_IDS:
        if not observable[mid]:
            print(f"  {mid:>5}{MUTANT_CAT[mid]:>13}{'- equivalent -':>26}" f"{'- equivalent -':>26}")
            continue
        b = sorted(kb[mid])
        g = sorted(kg[mid])
        bt = f"KILLED by {len(b)}" if b else "SURVIVED"
        gt = f"KILLED by {len(g)}" if g else "SURVIVED"
        print(f"  {mid:>5}{MUTANT_CAT[mid]:>13}{bt:>26}{gt:>26}")

    bad_k = [m for m in killable if kb[m]]
    good_k = [m for m in killable if kg[m]]
    only_bad = sorted(set(bad_k) - set(good_k))
    only_good = sorted(set(good_k) - set(bad_k))
    print(f"\n  {'suite':<14}{'lines':>7}{'tests':>7}{'killed':>9}" f"{'kill rate':>11}{'bugs/line':>11}")
    for label, suite, k in (("bad", BAD_SUITE, bad_k), ("good", GOOD_SUITE, good_k)):
        ln = suite_lines(suite)
        print(f"  {label:<14}{ln:>7}{len(suite):>7}{len(k):>9}" f"{len(k) / len(killable):>10.0%}{len(k) / ln:>11.3f}")
    ratio = len(good_k) / max(len(bad_k), 1)
    print(f"\n  {ratio:.2f}x the bugs caught, for the same number of lines of test code.")
    print(f"  bugs only the bad suite caught : {', '.join(only_bad) or '(none)'}")
    print(f"  bugs only the good suite caught: {', '.join(only_good)}")
    if only_bad:
        m = only_bad[0]
        print(f"  {m} is the label reformat — the one bug in the set that changes no")
        print("  money. The bad suite catches it by asserting on a debug string,")
        print("  and section 8 charges it for exactly that assertion.")
    print("\n  by category — what each style of test is actually good at:")
    cats = sorted({MUTANT_CAT[m] for m in killable})
    print(f"  {'category':<14}{'bugs':>6}{'bad':>7}{'good':>7}")
    for cat in cats:
        ids = [m for m in killable if MUTANT_CAT[m] == cat]
        print(f"  {cat:<14}{len(ids):>6}" f"{sum(1 for m in ids if kb[m]):>7}" f"{sum(1 for m in ids if kg[m]):>7}")
    return {"kb": kb, "kg": kg, "killable": killable, "bad_k": bad_k,
            "good_k": good_k, "ratio": ratio, "only_bad": only_bad}


# ---------------------------------------------------------------------------
# 4 · ONE REASON TO FAIL — WHAT THE FOURTEEN-ASSERT TEST HIDES
# ---------------------------------------------------------------------------
# To see what fail-fast never reported, rewrite bad_test_1's own AST: every
# `assert X` becomes `_rec(i, lambda: X)`, which records the verdict and
# carries on. Rewriting the assert statement is precisely what pytest does to
# print operand values; here it is used to keep the test running.


class Deassert(ast.NodeTransformer):
    def __init__(self) -> None:
        self.labels: list[str] = []

    def visit_Assert(self, node: ast.Assert) -> ast.Expr:
        self.labels.append(ast.unparse(node.test))
        call = ast.Call(
            func=ast.Name(id="_rec", ctx=ast.Load()),
            args=[ast.Constant(len(self.labels) - 1),
                  ast.Lambda(args=ast.arguments(
                      posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[],
                      defaults=[]), body=node.test)],
            keywords=[])
        return ast.fix_missing_locations(ast.copy_location(ast.Expr(call), node))


def build_ledger() -> tuple[Callable[..., list[bool]], list[str]]:
    """Return a runner that evaluates every assertion in bad_test_1."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(bad_test_1)))
    rewriter = Deassert()
    tree = rewriter.visit(tree)
    ns: dict[str, Any] = {}
    exec(compile(tree, "<deasserted>", "exec"), ns)
    body = ns["bad_test_1"]
    n = len(rewriter.labels)

    def verdicts(mod: types.ModuleType) -> list[bool]:
        out = [True] * n
        seen = [False] * n

        def _rec(i: int, thunk: Callable[[], Any]) -> None:
            seen[i] = True
            try:
                out[i] = bool(thunk())
            except Exception:
                out[i] = False
        ns["_rec"] = _rec
        try:
            body(mod)
        except Exception:  # a crash stops the test; unreached asserts count broken
            pass
        return [v and s for v, s in zip(out, seen)]

    return verdicts, rewriter.labels


SUBJ_RE = re.compile(
    r"subtotal_cents|discount_cents|tax_cents|total_cents|notes|format_receipt")
SUBJ_MAP = {"subtotal_cents": "subtotal", "discount_cents": "discount",
            "tax_cents": "tax", "total_cents": "total", "notes": "notes",
            "format_receipt": "receipt"}


def ledger_subject(label: str) -> str:
    """The first money field an assertion mentions is what it is about."""
    m = SUBJ_RE.search(label)
    return SUBJ_MAP[m.group(0)] if m else "structure"


def section_4(ctx: dict[str, Any]) -> dict[str, Any]:
    verdicts, labels = build_ledger()
    n_assert = len(labels)
    banner(f"4 · ONE REASON TO FAIL: WHAT A {n_assert}-ASSERTION TEST HIDES")
    print(f"  bad_test_1 holds {n_assert} assertions over 3 calls into the module. Python")
    print("  stops at the first one that fails, so a run reports ONE broken fact")
    print("  and never evaluates the rest. Below, bad_test_1's own AST is")
    print("  rewritten so each assertion records a verdict instead of raising —")
    print("  the same trick pytest uses, for the opposite purpose. (self-check:")
    print("  the rewrite must agree with the real test on every bug.)\n")
    observable = ctx["observable"]
    total_broken = reported = 0
    broken_count = [0] * n_assert
    first_count = [0] * n_assert
    rows = []
    for mid in MUTANT_IDS:
        if not observable[mid]:
            continue
        v = verdicts(load(MUTANT_SRC[mid], mid))
        broken = [i for i, ok in enumerate(v) if not ok]
        if bool(broken) != (run_test(bad_test_1, mid, MUTANT_SRC[mid]) is not None):
            raise SystemExit(f"rewritten test disagrees with bad_test_1 on {mid}")
        if not broken:
            continue
        for i in broken:
            broken_count[i] += 1
        first = broken[0]
        first_count[first] += 1
        total_broken += len(broken)
        reported += 1
        rows.append((mid, len(broken), first + 1, labels[first][:34],
                     ledger_subject(labels[first]), MUTANT_SUBJECT[mid]))

    print(f"  {'bug':>5}{'facts broken':>14}{'reported':>10}  {'you are shown':<36}" f"{'points at':>10}{'bug is in':>11}")
    for mid, nb, idx, label, sf, st in rows:
        mark = "  <--" if sf != st else ""
        print(f"  {mid:>5}{nb:>14}{('#' + str(idx)):>10}  {label:<36}" f"{sf:>10}{st:>11}{mark}")

    masked = total_broken - reported
    print(f"\n  {'#':>3}  {'the assertion, as written':<46}{'broken by':>11}" f"{'you saw':>9}{'masked':>8}")
    for i, label in enumerate(labels):
        mark = "  <-- never seen" if broken_count[i] and not first_count[i] else ""
        print(f"  {i + 1:>3}  {label[:46]:<46}{broken_count[i]:>11}" f"{first_count[i]:>9}{broken_count[i] - first_count[i]:>8}{mark}")

    seen = sum(1 for c in first_count if c)
    never = sum(1 for i, c in enumerate(first_count)
                if not c and broken_count[i])
    print(f"\n  {reported} of the {len(ctx['killable'])} killable bugs break at least one " f"assertion here, and")
    print(f"  between them they break {total_broken}. The runs report {reported}. The other " f"{masked} —")
    print(f"  {masked / total_broken:.0%} of everything this test knows — are masked behind an")
    print(f"  earlier failure in the same body. Only {seen} of the {n_assert} assertions was")
    print(f"  ever the one you were shown; {never} broke repeatedly and reported")
    print(f"  nothing, ever. Mean facts broken per failing run: " f"{total_broken / reported:.2f}, which is")
    print("  the number of fix-and-rerun round trips this one test costs you.")
    return {"total_broken": total_broken, "reported": reported, "seen": seen,
            "masked": masked, "never": never, "rows": rows}


# ---------------------------------------------------------------------------
# 5 · THE NAME IS THE FAILURE REPORT
# ---------------------------------------------------------------------------

SUBJECT_WORDS = {
    "tier_discount": "discount", "percentage_rounding": "discount",
    "tax_rounding": "tax", "tax_uses": "tax", "tax_is": "tax",
    "coupon_and_tier": "discount", "coupon_still": "coupon",
    "coupon_is_rejected": "coupon", "coupon_is_ignored": "coupon",
    "unknown_coupon": "coupon", "quantity_below": "quantity",
    "subtotal_sums": "subtotal", "quote_totals": "total",
}


def declared_subject(name: str) -> str | None:
    body = name.split("test_", 1)[1]
    for key in sorted(SUBJECT_WORDS, key=len, reverse=True):
        if body.startswith(key):
            return SUBJECT_WORDS[key]
    return None


def section_5(ctx: dict[str, Any]) -> None:
    banner("5 · THE NAME IS THE FAILURE REPORT")
    print("  A test name should let you delete the body and still know what")
    print("  broke. Measured: when a test goes red, does its NAME alone name")
    print("  the part of the system the bug is in?\n")
    out = {}
    print(f"  {'suite':<7}{'bugs caught':>13}{'locatable from':>16}" f"{'red tests':>11}{'that named it':>15}")
    print(f"  {'':<7}{'':>13}{'a name alone':>16}{'':>11}{'':>15}")
    for label, suite, k in (("bad", BAD_SUITE, ctx["kb"]),
                            ("good", GOOD_SUITE, ctx["kg"])):
        named = hits = locatable = caught = 0
        for mid in ctx["killable"]:
            if not k[mid]:
                continue
            caught += 1
            if any(declared_subject(t) == MUTANT_SUBJECT[mid]
                   for t in sorted(k[mid])):
                locatable += 1
            for tname in sorted(k[mid]):
                hits += 1
                if declared_subject(tname) == MUTANT_SUBJECT[mid]:
                    named += 1
        out[label] = named / hits if hits else 0.0
        out[label + "_locatable"] = locatable
        print(f"  {label:<7}{caught:>13}{f'{locatable}/{caught}':>16}" f"{hits:>11}{f'{named} ({out[label]:.0%})':>15}")
    print("\n  the bad suite's first three names, then the good suite's:")
    for t in BAD_SUITE[:3] + GOOD_SUITE[:3]:
        print(f"    {t.__name__}")
    print("  'bad_test_pricing' is a topic and 'test_1' is an ordinal. Neither")
    print("  can be false, and a name that cannot be false cannot report a")
    print("  failure. <unit>_<condition>_<expected> can: read one in a CI log at")
    print("  02:00 and you know the blast radius before you open the file.")
    return out


# ---------------------------------------------------------------------------
# 6 · BOUNDARIES, AND THE ARITHMETIC OF FINDING THEM BY ACCIDENT
# ---------------------------------------------------------------------------


def section_6(ctx: dict[str, Any]) -> dict[str, Any]:
    banner("6 · BOUNDARIES: WHAT A RANDOM INPUT WOULD HAVE TO GET LUCKY TO FIND")
    base = load(PRICING_V1, "V1")
    golden = [outcome_full(base, c) for c in RANDOM_GRID]
    n = len(RANDOM_GRID)
    print(f"  {n:,} orders drawn from a plausible catalogue (16 prices, 1-3 lines,")
    print("  quantity 1-4, a real coupon or none, day 0-40). For each bug: on")
    print("  what fraction of those orders does the output actually differ?\n")

    p_of, first_of = {}, {}
    for mid in ctx["killable"]:
        mod = load(MUTANT_SRC[mid], mid)
        hits, first = 0, None
        for i, case in enumerate(RANDOM_GRID):
            if outcome_full(mod, case) != golden[i]:
                hits += 1
                if first is None:
                    first = i
        p_of[mid] = hits / n
        first_of[mid] = first

    def needed(p: float) -> str:
        if p <= 0.0:
            return "> " + f"{n:,}"
        if p >= 1.0:
            return "1"
        return f"{math.ceil(math.log(0.05) / math.log(1.0 - p)):,}"

    order = sorted(ctx["killable"], key=lambda m: p_of[m])
    print(f"  {'bug':>5}{'category':>13}{'differs on':>12}{'random cases for':>19}" f"{'first hit':>11}")
    print(f"  {'':>5}{'':>13}{'':>12}{'95% confidence':>19}{'at case':>11}")
    for mid in order:
        fh = f"{first_of[mid]:,}" if first_of[mid] is not None else "never"
        print(f"  {mid:>5}{MUTANT_CAT[mid]:>13}{p_of[mid]:>11.3%}" f"{needed(p_of[mid]):>19}{fh:>11}")

    rare = [m for m in order if 0.0 < p_of[m] < 0.01]
    invis = [m for m in order if p_of[m] == 0.0]
    worst = min((m for m in order if p_of[m] > 0), key=lambda m: p_of[m])
    print(f"\n  {len(rare) + len(invis)} of {len(ctx['killable'])} bugs show up on " f"under 1% of realistic orders, and {len(invis)}")
    print(f"  never showed up at all in {n:,} of them " f"({', '.join(invis) if invis else '(none)'}).")
    print(f"  The narrowest that did show up, {worst}, needs {needed(p_of[worst])} random orders")
    print("  before you are 95% likely to have tripped it even once.")

    # The parametrized boundary tables, alone.
    sweep = good_test_tier_discount_changes_only_at_the_documented_thresholds
    tables = [sweep,
              good_test_percentage_rounding_breaks_exact_halves_to_even,
              good_test_tax_rounding_breaks_exact_halves_to_even,
              good_test_coupon_is_ignored_below_the_minimum_order_value]
    solo = {m for m in ctx["killable"]
            if run_test(sweep, m, MUTANT_SRC[m]) is not None}
    group = {m for m in ctx["killable"]
             for t in tables if run_test(t, m, MUTANT_SRC[m]) is not None}
    ln, gln = logical_lines(sweep), sum(logical_lines(t) for t in tables)
    bad_ln, bad_k = suite_lines(BAD_SUITE), len(ctx["bad_k"])
    print(f"\n  now the parametrized tables. ONE of them — {ln} lines, 9 cases, every")
    print("  one on a threshold or a cent either side of it:")
    print(f"    kills {len(solo)} of {len(ctx['killable'])} bugs alone: {', '.join(sorted(solo))}")
    print(f"  all {len(tables)} boundary tables together — {gln} lines, 22 cases:")
    print(f"    kill {len(group)} of {len(ctx['killable'])}, against the " f"{bad_ln}-line bad suite's {bad_k}.")
    print(f"    {gln} lines beat {bad_ln} lines by {len(group) - bad_k} bugs — "
          f"{gln / bad_ln:.0%} of the code, {len(group) / bad_k:.1f}x the detection.")
    print("  Boundary values are not exotic inputs. They are the values the code")
    print("  branches on, which is exactly why a plausible random order almost")
    print("  never lands on one.")

    # The unhappy path: bugs no valid input can reach.
    base_o = [outcome_full(base, c) for c in ORACLE_GRID]
    valid = [i for i, c in enumerate(ORACLE_GRID)
             if not isinstance(base_o[i][0], str)]
    invalid = [i for i in range(len(ORACLE_GRID)) if i not in set(valid)]
    only_unhappy = []
    for mid in ctx["killable"]:
        mod = load(MUTANT_SRC[mid], mid)
        on_valid = any(outcome_full(mod, ORACLE_GRID[i]) != base_o[i] for i in valid)
        on_invalid = any(outcome_full(mod, ORACLE_GRID[i]) != base_o[i]
                         for i in invalid)
        if on_invalid and not on_valid:
            only_unhappy.append(mid)
    unhappy_bad = sum(1 for t in BAD_SUITE if "except mod." in inspect.getsource(t))
    unhappy_good = sum(1 for t in GOOD_SUITE if "except mod." in inspect.getsource(t))
    never_generated = [m for m in only_unhappy if p_of[m] == 0.0]
    print(f"\n  the unhappy path: {len(only_unhappy)} of {len(ctx['killable'])} bugs " f"({', '.join(only_unhappy)}) change")
    print("  nothing on any input the module ACCEPTS. They live entirely in the")
    print("  branches that reject input, so no amount of valid data reaches them.")
    print(f"  {len(never_generated)} of them ({', '.join(never_generated)}) never appeared in " f"the {n:,} random")
    print("  orders at all: a generator written by someone thinking about")
    print("  pricing produces prices, not malformed orders.")
    print(f"    tests that assert on a rejection: bad {unhappy_bad}/{len(BAD_SUITE)}, " f"good {unhappy_good}/{len(GOOD_SUITE)}")
    print("  Error branches are the least-exercised code you ship and the code")
    print("  that runs on your worst day. Write the rejection tests first.")
    return {"p_of": p_of, "solo": solo, "group": group}


# ---------------------------------------------------------------------------
# 7 · ASSERT ON THE OUTCOME, NOT ON THE CALLS
# ---------------------------------------------------------------------------


def section_7(ctx: dict[str, Any]) -> None:
    banner("7 · STATE VS INTERACTION: WHAT EACH KIND OF ASSERTION CAN PROVE")
    print("  bad_test_coupon asserts that price_order CALLED the audit port")
    print("  twice, in order. bad_test_happy_path replaces the tier and coupon")
    print("  helpers with stubs and then asserts the discount. Both are green,")
    print("  both are about price_order, and neither is about the price.\n")
    named = {t.__name__: t for t in BAD_SUITE + GOOD_SUITE}
    probes = [
        ("interaction (asserts on calls)", "bad_test_coupon"),
        ("over-mocked (stubs the logic)", "bad_test_happy_path"),
        ("string (asserts the receipt)", "bad_test_pricing"),
        ("state (asserts the money)", "good_test_tax_is_charged_on_the_discounted_amount"),
        ("state (asserts an invariant)", "good_test_quote_totals_are_internally_consistent"),
    ]
    print(f"  {'assertion style':<34}{'lines':>7}{'bugs killed':>13}{'of':>4}" f"   which")
    for label, name in probes:
        fn = named[name]
        k = sorted(m for m in ctx["killable"]
                   if run_test(fn, m, MUTANT_SRC[m]) is not None)
        print(f"  {label:<34}{logical_lines(fn):>7}{len(k):>13}" f"{len(ctx['killable']):>4}   {', '.join(k) or '-'}")

    blind = sorted(set(ctx["fn_of"]["_tier_bps"] + ctx["fn_of"]["_coupon_bps"])
                   & set(ctx["killable"]))
    print(f"\n  bad_test_happy_path stubbed out _tier_bps and _coupon_bps, so the")
    print(f"  {len(blind)} bugs living in them ({', '.join(blind)})")
    print("  cannot reach it at ANY input. It is not a weak test of the tier")
    print("  logic; it is structurally incapable of being one — it asserts that")
    print("  a stub returned what the test configured the stub to return.")
    print("  Lesson 04 prices that against a real provider that keeps changing.")


# ---------------------------------------------------------------------------
# 8 · THE BRITTLE-ASSERT TAX: A REFACTOR THAT CHANGES NO BEHAVIOUR
# ---------------------------------------------------------------------------


def section_8(ctx: dict[str, Any]) -> dict[str, Any]:
    banner("8 · A REFACTOR THAT CHANGES NO MONEY, AND WHAT IT COSTS EACH SUITE")
    v1, v2 = load(PRICING_V1, "V1"), load(PRICING_V2, "V2")
    checked = 0
    for grid in (ORACLE_GRID, RANDOM_GRID):
        for case in grid:
            if outcome_money(v1, case) != outcome_money(v2, case):
                raise SystemExit(f"refactor changed behaviour on {case!r}")
            checked += 1
    print("  the refactor: rename the internal `notes` field to `applied`,")
    print("  reword one error message, reformat the receipt, split _tier_bps()")
    print("  into _tier_index() + _bps_for_index(), and batch the two audit")
    print("  events into one. Five edits, all cosmetic or structural.")
    print(f"  proof it is behaviour-preserving: {checked:,} cases through both")
    print("  versions — every amount and every exception type identical.\n")

    out = {}
    for label, suite in (("bad", BAD_SUITE), ("good", GOOD_SUITE)):
        broken = [(t.__name__, run_test(t, "V2", PRICING_V2)) for t in suite]
        broken = [(n, r) for n, r in broken if r is not None]
        out[label] = broken
        print(f"  {label.upper()} SUITE: {len(broken)} of {len(suite)} tests go red")
        for name, reason in broken:
            print(f"    {name:<22}{reason[:64]}")
        if not broken:
            print("    (none)")
        print()

    nb, ng = len(out["bad"]), len(out["good"])
    print(f"  {nb} of {len(BAD_SUITE)} against {ng} of {len(GOOD_SUITE)}, and every red test is red for")
    print("  the same reason: it asserted on something the caller does not")
    print("  depend on — a label, a message, a call, a private helper's name.")
    print("  None found a bug. All must be read and rewritten by whoever did")
    print("  the refactor. A test that breaks when behaviour has not changed")
    print("  has negative value: it charges maintenance and buys no detection.")
    return out


# ---------------------------------------------------------------------------
# 9 · THE TESTS YOU SHOULD NOT WRITE
# ---------------------------------------------------------------------------


def section_9(ctx: dict[str, Any], churn: dict[str, Any]) -> None:
    banner("9 · THE TESTS YOU SHOULD NOT WRITE, PRICED")
    suspects = {
        "bad_test_getter": "asserts the constructor assigns its arguments",
        "bad_test_it_works": "asserts the return value is truthy",
        "bad_test_smoke": "asserts a total is not negative",
        "bad_test_happy_path": "asserts a stub returned the stubbed value",
        "bad_test_repr": "asserts on __repr__ output",
        "bad_test_coupon": "asserts which calls were made",
    }
    named = {t.__name__: t for t in BAD_SUITE}
    kb = ctx["kb"]
    broken_names = {n for n, _ in churn["bad"]}
    others = [t for t in BAD_SUITE if t.__name__ not in suspects]
    covered_by_others = {m for m in ctx["killable"]
                         if any(t.__name__ in kb[m] for t in others)}

    print(f"  {'test':<24}{'lines':>6}{'kills':>7}{'unique':>8}{'red after':>11}" f"   what it asserts")
    tot_l = tot_k = tot_u = tot_r = 0
    for name, what in suspects.items():
        fn = named[name]
        k = [m for m in ctx["killable"] if name in kb[m]]
        uniq = [m for m in k if m not in covered_by_others]
        red = 1 if name in broken_names else 0
        tot_l += logical_lines(fn)
        tot_k += len(k)
        tot_u += len(uniq)
        tot_r += red
        print(f"  {name:<24}{logical_lines(fn):>6}{len(k):>7}{len(uniq):>8}" f"{('yes' if red else 'no'):>11}   {what}")
    print(f"  {'total':<24}{tot_l:>6}{tot_k:>7}{tot_u:>8}{tot_r:>11}")
    share = tot_l / suite_lines(BAD_SUITE)
    print(f"\n  {len(suspects)} tests, {tot_l} lines, {tot_u} bugs that no other test in")
    print(f"  their own suite would have caught, and {tot_r} of them went red on a")
    print(f"  refactor that changed nothing. Deleting all {len(suspects)} leaves the bad")
    print(f"  suite's detection exactly where it was and removes {share:.0%} of its")
    print("  maintenance surface. The rule they all break is the same one:")
    print("  do not test the language, the framework, the constructor, or the")
    print("  double — test the behaviour someone is paying for.")


def main() -> None:
    print("ANATOMY OF A UNIT TEST — two suites, one module, 25 seeded bugs")
    print(f"Phase 12 · Lesson 03 · seed={RNG_SEED} · stdlib only")
    ctx = section_1()
    section_2()
    ctx.update(section_3(ctx))
    ctx["mask"] = section_4(ctx)
    section_5(ctx)
    section_6(ctx)
    section_7(ctx)
    churn = section_8(ctx)
    section_9(ctx, churn)
    # stdout is bit-reproducible; the only varying value goes to stderr so that
    # two runs can be diffed byte for byte.
    print(f"\n  (elapsed on stderr; stdout is identical run to run)")
    print(f"total wall time {time.perf_counter() - START:.2f} s",
          file=sys.stderr)


if __name__ == "__main__":
    main()
