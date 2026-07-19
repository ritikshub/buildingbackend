#!/usr/bin/env python3
"""
Coverage measured against detection: a suite that calls every function and
asserts nothing, a line-and-branch coverage tracer built from sys.settrace, a
six-operator mutation engine built from ast, the divergence between coverage
and mutation score across five suites, the equivalent-mutant ceiling, and what
full-repo versus diff-only mutation actually costs.

Companion to docs/en.md (Phase 12, Lesson 13). Standard library only (`ast`,
`sys.settrace`), every RNG seeded with random.Random(20260718), no network, no
files written outside a tempfile.TemporaryDirectory, self-terminating in a few
seconds. Sources: DeMillo, Lipton & Sayward, *Hints on Test Data Selection:
Help for the Practicing Programmer*, IEEE Computer 11(4), 1978 (mutation
testing and the competent-programmer hypothesis); Jia & Harman, *An Analysis
and Survey of the Development of Mutation Testing*, IEEE TSE 37(5), 2011 (the
equivalent-mutant problem); RTCA DO-178C, 2011 (the MC/DC definition).

Run:  python3 coverage_mutation.py
"""

from __future__ import annotations

import ast
import bisect
import itertools
import random
import sys
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

SEED = 20260718
STEP_BUDGET = 20_000  # deterministic stand-in for a wall-clock mutation timeout


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def pct(a: float, b: float) -> str:
    return "  n/a" if b == 0 else f"{100.0 * a / b:5.1f}%"


# ══ 0 · THE MODULE UNDER TEST ════════════════════════════════════════════════
# Ordinary backend pricing code. Six functions: a discount ladder with three
# boundaries, two guard clauses that raise, a loop with a clamp, a while loop,
# and one composition function. It is deliberately small enough to mutate
# exhaustively and deliberately ordinary enough that every bug the mutation
# engine seeds is a bug someone has actually shipped.

TARGET_SOURCE = '''\
"""Order pricing."""


def discount_pct(qty, tier):
    if qty < 0:
        raise ValueError("qty must be non-negative")
    pct = 0
    if qty >= 100:
        pct = 15
    elif qty >= 10:
        pct = 5
    if tier == "gold":
        pct = pct + 8
    if pct > 20:
        pct = 20
    return pct


def line_total(unit_cents, qty, tier):
    if unit_cents <= 0:
        raise ValueError("unit_cents must be positive")
    gross = unit_cents * qty
    pct = discount_pct(qty, tier)
    return gross - gross * pct // 100


def shipping_cents(subtotal_cents, express):
    fee = 499
    if subtotal_cents >= 5000:
        fee = 0
    if express:
        fee = fee + 1200
    return fee


def apply_credits(total_cents, credits):
    if not credits:
        return total_cents
    remaining = total_cents
    for c in credits:
        remaining = remaining - c
        if remaining < 0:
            remaining = 0
    return remaining


def installments(total_cents, n):
    if n <= 0:
        raise ValueError("n must be positive")
    parts = []
    remaining = total_cents
    i = 0
    while i < n - 1:
        part = total_cents // n
        parts.append(part)
        remaining = remaining - part
        i = i + 1
    parts.append(remaining)
    return parts


def order_total(items, tier, express, credits):
    subtotal = 0
    for unit_cents, qty in items:
        subtotal = subtotal + line_total(unit_cents, qty, tier)
    subtotal = apply_credits(subtotal, credits)
    return subtotal + shipping_cents(subtotal, express)
'''


# ══ 1 · A COVERAGE TRACER, FROM SCRATCH ══════════════════════════════════════
# coverage.py is not magic. It is a trace function, a set of line numbers, and
# an AST walk that says which line numbers were possible. That is the whole
# product. This is the same thing in eighty lines.
#
# sys.settrace installs a GLOBAL trace function called once per frame creation.
# Return a LOCAL trace function from it and Python calls that on every line
# executed in that frame. We filter on co_filename so we only ever see the
# module under test, never the harness.
#
# Line coverage needs only the set of lines seen. Branch coverage needs ARCS:
# ordered (from_line, to_line) pairs. An `if` at line L with its body starting
# at line B took the true outcome iff the arc (L -> B) was observed, and took
# the false outcome iff any arc (L -> anything else) was observed. A frame that
# returns emits no further line event, so a `return` event records the arc
# (last_line -> -1) — otherwise a false outcome at the end of a function would
# be invisible.
#
# One correctness detail that a naive tracer gets wrong: `frame.f_lineno` is
# not a stable identifier for a statement. CPython has changed, more than once,
# which physical line it attributes an event to when a statement spans several
# of them, so a raw tally of f_lineno values measures the interpreter as well
# as the program. We fold every event down onto the first line of its enclosing
# statement, taken from the AST — the source decides the unit, not the runtime.


class CoverageTracer:
    """Line and branch coverage for one file, via sys.settrace.

    `starts` is the sorted list of every statement's first line, from the AST.
    Events are folded onto it so the result depends on the source, not on the
    interpreter's line-attribution rules.
    """

    def __init__(self, path: str, starts: Sequence[int], record_order: bool = False) -> None:
        self.path = path
        self.starts = list(starts)
        self.lines: Set[int] = set()
        self.arcs: Set[Tuple[int, int]] = set()
        self.record_order = record_order
        self.order: List[int] = []

    def fold(self, lineno: int) -> int:
        i = bisect.bisect_right(self.starts, lineno) - 1
        return self.starts[i] if i >= 0 else lineno

    def _local(self, prev: List[Optional[int]]) -> Callable[..., Any]:
        def trace(frame: types.FrameType, event: str, arg: Any) -> Any:
            if event == "line":
                line = self.fold(frame.f_lineno)
                if line != prev[0]:
                    if prev[0] is not None:
                        self.arcs.add((prev[0], line))
                    if self.record_order:
                        self.order.append(line)
                self.lines.add(line)
                prev[0] = line
            elif event == "return" and prev[0] is not None:
                self.arcs.add((prev[0], -1))
            return trace

        return trace

    def _global(self, frame: types.FrameType, event: str, arg: Any) -> Any:
        if frame.f_code.co_filename != self.path:
            return None
        return self._local([None])

    def __enter__(self) -> "CoverageTracer":
        sys.settrace(self._global)
        return self

    def __exit__(self, *exc: Any) -> None:
        sys.settrace(None)


@dataclass
class Structure:
    """What the AST says was *possible* — the denominator of every ratio."""

    lines: Set[int] = field(default_factory=set)           # executable lines
    branches: List[Tuple[int, int, str]] = field(default_factory=list)
    line_owner: Dict[int, str] = field(default_factory=dict)  # line -> function
    starts: List[int] = field(default_factory=list)        # every statement start


def analyse(source: str) -> Structure:
    """Executable lines and two-way branch points, from the AST alone.

    Executable lines are statement lines inside function bodies: the `def`
    lines and the module docstring run at import, before any test does, and
    counting them would inflate every ratio. Branch points are `if`, `elif` and
    `while` only — the explicit two-way decisions. `for` is excluded because
    its exit arc is taken by every terminating loop, which would make the
    denominator flatter than the truth.
    """
    st = Structure()
    tree = ast.parse(source)
    st.starts = sorted({n.lineno for n in ast.walk(tree)
                        if isinstance(n, (ast.stmt, ast.ExceptHandler))})
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        for node in ast.walk(fn):
            if isinstance(node, ast.stmt) and node is not fn:
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                        and isinstance(node.value.value, str):
                    continue  # a docstring
                st.lines.add(node.lineno)
                st.line_owner[node.lineno] = fn.name
            if isinstance(node, (ast.If, ast.While)):
                body_first = node.body[0].lineno
                st.branches.append((node.lineno, body_first, fn.name))
    return st


def coverage_of(st: Structure, tr: CoverageTracer) -> Tuple[int, int, int, int]:
    """(lines hit, lines possible, branch outcomes hit, branch outcomes possible)."""
    hit_lines = st.lines & tr.lines
    outcomes = 0
    for cond_line, body_line, _ in st.branches:
        if (cond_line, body_line) in tr.arcs:
            outcomes += 1
        if any(a == cond_line and b != body_line for a, b in tr.arcs):
            outcomes += 1
    return len(hit_lines), len(st.lines), outcomes, 2 * len(st.branches)


# ══ 2 · RUNNING A SUITE, WITH A DETERMINISTIC TIMEOUT ════════════════════════
# A mutation engine must survive mutants that never terminate — delete `i = i +
# 1` from a while loop and the mutant runs forever. Real tools use a wall-clock
# timeout, which makes the report non-reproducible. We count executed lines
# instead: same purpose, same classification, identical output on every run and
# every machine.


class BudgetExceeded(Exception):
    """The mutant executed more lines than the budget allows: a 'timeout'."""


def call_budgeted(path: str, limit: int, fn: Callable[..., Any], *args: Any) -> Any:
    steps = [0]

    def local(frame: types.FrameType, event: str, arg: Any) -> Any:
        if event == "line":
            steps[0] += 1
            if steps[0] > limit:
                raise BudgetExceeded()
        return local

    def glob(frame: types.FrameType, event: str, arg: Any) -> Any:
        return local if frame.f_code.co_filename == path else None

    sys.settrace(glob)
    try:
        return fn(*args)
    finally:
        sys.settrace(None)


@dataclass(frozen=True)
class Test:
    name: str
    fn: Callable[[Any], None]


def run_suite(mod: Any, tests: Sequence[Test], path: str = "",
              budget: bool = False) -> Tuple[List[bool], bool]:
    """Returns (per-test pass/fail, whether any test blew the step budget)."""
    results: List[bool] = []
    timed_out = False
    for t in tests:
        try:
            if budget:
                call_budgeted(path, STEP_BUDGET, t.fn, mod)
            else:
                t.fn(mod)
            results.append(True)
        except BudgetExceeded:
            timed_out = True
            results.append(False)
        except Exception:
            results.append(False)
    return results, timed_out


def load(source: str, path: str) -> Any:
    ns: Dict[str, Any] = {"__name__": "pricing", "__file__": path}
    exec(compile(source, path, "exec"), ns)
    return types.SimpleNamespace(**ns)


def load_tree(tree: ast.Module, path: str) -> Any:
    ns: Dict[str, Any] = {"__name__": "pricing", "__file__": path}
    exec(compile(ast.fix_missing_locations(tree), path, "exec"), ns)
    return types.SimpleNamespace(**ns)


# ══ 3 · FIVE SUITES OF INCREASING QUALITY ════════════════════════════════════
# Suite 1 is the whole lesson in one object: it calls every function, swallows
# every exception, and asserts nothing. Suites 2-5 are cumulative — the calls
# only ever grow, so line coverage cannot fall. What changes is what each test
# is willing to claim about the answer.

GRID_QTY = (-1, 5, 50, 150)
GRID_UNIT = (0, 250)


def _eq(a: Any, b: Any) -> None:
    if a != b:
        raise AssertionError(f"{a!r} != {b!r}")


def _raises(exc: type, fn: Callable[..., Any], *args: Any) -> None:
    try:
        fn(*args)
    except exc:
        return
    raise AssertionError("expected " + exc.__name__)


def suite_no_assert() -> List[Test]:
    def t_discount(m: Any) -> None:
        for qty in GRID_QTY:
            try:
                m.discount_pct(qty, "gold")
            except Exception:
                pass

    def t_line_total(m: Any) -> None:
        for qty in GRID_QTY:
            for unit in GRID_UNIT:
                try:
                    m.line_total(unit, qty, "gold")
                except Exception:
                    pass

    def t_shipping(m: Any) -> None:
        for sub in (100, 6000):
            try:
                m.shipping_cents(sub, True)
            except Exception:
                pass

    def t_credits(m: Any) -> None:
        for cr in ([], [9999]):
            try:
                m.apply_credits(1000, cr)
            except Exception:
                pass

    def t_installments(m: Any) -> None:
        for n in (0, 3):
            try:
                m.installments(1000, n)
            except Exception:
                pass

    def t_order_total(m: Any) -> None:
        try:
            m.order_total([(250, 50)], "gold", True, [])
        except Exception:
            pass

    return [Test("no_assert_" + f.__name__[2:], f) for f in
            (t_discount, t_line_total, t_shipping, t_credits, t_installments, t_order_total)]


def suite_smoke() -> List[Test]:
    def t_discount(m: Any) -> None:
        for qty in GRID_QTY:
            for tier in ("gold", "standard"):
                try:
                    assert isinstance(m.discount_pct(qty, tier), int)
                except ValueError:
                    pass

    def t_line_total(m: Any) -> None:
        for qty in GRID_QTY:
            for unit in GRID_UNIT:
                try:
                    assert isinstance(m.line_total(unit, qty, "gold"), int)
                except ValueError:
                    pass

    def t_shipping(m: Any) -> None:
        for sub in (100, 6000):
            for exp in (True, False):
                assert isinstance(m.shipping_cents(sub, exp), int)

    def t_credits(m: Any) -> None:
        for cr in ([], [9999]):
            assert isinstance(m.apply_credits(1000, cr), int)

    def t_installments(m: Any) -> None:
        for n in (0, 3):
            try:
                assert isinstance(m.installments(1000, n), list)
            except ValueError:
                pass

    def t_order_total(m: Any) -> None:
        assert isinstance(m.order_total([(250, 50)], "gold", True, []), int)

    return [Test("smoke_" + f.__name__[2:], f) for f in
            (t_discount, t_line_total, t_shipping, t_credits, t_installments, t_order_total)]


def suite_happy() -> List[Test]:
    def t_discount_standard(m: Any) -> None:
        _eq(m.discount_pct(5, "standard"), 0)
        _eq(m.discount_pct(50, "standard"), 5)
        _eq(m.discount_pct(150, "standard"), 15)

    def t_discount_gold(m: Any) -> None:
        _eq(m.discount_pct(5, "gold"), 8)
        _eq(m.discount_pct(50, "gold"), 13)

    def t_line_total_typical(m: Any) -> None:
        _eq(m.line_total(250, 4, "standard"), 1000)
        _eq(m.line_total(250, 50, "standard"), 11875)

    def t_shipping_typical(m: Any) -> None:
        _eq(m.shipping_cents(1000, False), 499)
        _eq(m.shipping_cents(6000, False), 0)
        _eq(m.shipping_cents(6000, True), 1200)

    def t_credits_typical(m: Any) -> None:
        _eq(m.apply_credits(1000, []), 1000)
        _eq(m.apply_credits(1000, [300]), 700)

    def t_installments_typical(m: Any) -> None:
        _eq(m.installments(1000, 3), [333, 333, 334])

    def t_order_total_typical(m: Any) -> None:
        _eq(m.order_total([(250, 4)], "standard", False, []), 1499)

    return suite_smoke() + [Test("happy_" + f.__name__[2:], f) for f in
                            (t_discount_standard, t_discount_gold, t_line_total_typical,
                             t_shipping_typical, t_credits_typical, t_installments_typical,
                             t_order_total_typical)]


def suite_errors() -> List[Test]:
    def t_discount_rejects_negative(m: Any) -> None:
        _raises(ValueError, m.discount_pct, -1, "standard")

    def t_line_total_rejects_zero_price(m: Any) -> None:
        _raises(ValueError, m.line_total, 0, 4, "standard")
        _raises(ValueError, m.line_total, -250, 4, "standard")

    def t_installments_rejects_zero(m: Any) -> None:
        _raises(ValueError, m.installments, 1000, 0)
        _raises(ValueError, m.installments, 1000, -3)

    def t_credits_never_negative(m: Any) -> None:
        _eq(m.apply_credits(1000, [9999]), 0)
        _eq(m.apply_credits(1000, [600, 600]), 0)

    def t_discount_caps_at_20(m: Any) -> None:
        _eq(m.discount_pct(150, "gold"), 20)

    return suite_happy() + [Test("error_" + f.__name__[2:], f) for f in
                            (t_discount_rejects_negative, t_line_total_rejects_zero_price,
                             t_installments_rejects_zero, t_credits_never_negative,
                             t_discount_caps_at_20)]


def suite_boundary() -> List[Test]:
    def t_discount_qty_boundaries(m: Any) -> None:
        _eq(m.discount_pct(0, "standard"), 0)
        _eq(m.discount_pct(9, "standard"), 0)
        _eq(m.discount_pct(10, "standard"), 5)
        _eq(m.discount_pct(99, "standard"), 5)
        _eq(m.discount_pct(100, "standard"), 15)

    def t_shipping_threshold(m: Any) -> None:
        _eq(m.shipping_cents(4999, False), 499)
        _eq(m.shipping_cents(5000, False), 0)
        _eq(m.shipping_cents(4999, True), 1699)

    def t_credits_exact(m: Any) -> None:
        _eq(m.apply_credits(1000, [1000]), 0)
        _eq(m.apply_credits(1000, [999]), 1)
        _eq(m.apply_credits(1000, [1001]), 0)

    def t_credits_sequence(m: Any) -> None:
        _eq(m.apply_credits(1000, [400, 400, 400]), 0)
        _eq(m.apply_credits(1000, [400, 300]), 300)

    def t_installments_one(m: Any) -> None:
        _eq(m.installments(1000, 1), [1000])
        _eq(m.installments(1000, 2), [500, 500])
        _eq(m.installments(1001, 2), [500, 501])

    def t_line_total_rounding(m: Any) -> None:
        _eq(m.line_total(333, 10, "standard"), 3164)
        _eq(m.line_total(1, 1, "standard"), 1)

    def t_order_total_composed(m: Any) -> None:
        _eq(m.order_total([(250, 4), (100, 12)], "standard", True, [200]), 3639)
        _eq(m.order_total([], "standard", False, []), 499)

    def t_discount_gold_ladder(m: Any) -> None:
        _eq(m.discount_pct(0, "gold"), 8)
        _eq(m.discount_pct(10, "gold"), 13)
        _eq(m.discount_pct(100, "gold"), 20)

    return suite_errors() + [Test("bound_" + f.__name__[2:], f) for f in
                             (t_discount_qty_boundaries, t_shipping_threshold, t_credits_exact,
                              t_credits_sequence, t_installments_one, t_line_total_rounding,
                              t_order_total_composed, t_discount_gold_ladder)]


def suite_typical_incomplete() -> List[Test]:
    """A perfectly ordinary suite that asserts real values but never exercises
    the guard clauses. It exists to measure the coverage asymmetry in section
    3: what a suite catches on lines it ran, versus lines it did not."""

    def t_shipping_both_ways(m: Any) -> None:
        _eq(m.shipping_cents(1000, True), 1699)
        _eq(m.shipping_cents(6000, False), 0)

    return suite_happy()[6:] + [Test("typical_shipping_both_ways", t_shipping_both_ways)]


# ══ 4 · A MUTATION ENGINE, FROM SCRATCH ══════════════════════════════════════
# Six operators, chosen because they are the six mistakes that actually reach
# production in backend code (DeMillo, Lipton & Sayward, IEEE Computer 11(4),
# 1978, argue the case: real faults are small deviations from a nearly-correct
# program, so seeding small deviations is a fair proxy for real faults).
#
#   boundary       <  <->  <=      >  <->  >=          the off-by-one
#   conditional    if C -> if not C, == <-> !=          the inverted guard
#   arithmetic     + <-> -,  * <-> //                   the wrong operator
#   return         return X -> return None              the forgotten result
#   exception      raise E -> pass                      the swallowed failure
#   deletion       stmt -> pass                         the missing line

CMP_BOUNDARY = {ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt}
CMP_NEGATE = {ast.Eq: ast.NotEq, ast.NotEq: ast.Eq}
ARITH = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult}
OPSYM = {ast.Lt: "<", ast.LtE: "<=", ast.Gt: ">", ast.GtE: ">=", ast.Eq: "==", ast.NotEq: "!=",
         ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.FloorDiv: "//"}


@dataclass
class Site:
    operator: str
    lineno: int
    col: int
    func: str
    before: str
    after: str
    apply: Callable[[], None]


def _own_exprs(st: ast.stmt) -> Any:
    """Every expression node belonging to this statement, without descending
    into nested statements — those are enumerated as statements in their own
    right, and walking into them would generate each mutant twice."""
    queue: List[ast.AST] = []
    for fieldname, value in ast.iter_fields(st):
        if fieldname in ("body", "orelse", "finalbody", "handlers"):
            continue
        if isinstance(value, list):
            queue.extend(v for v in value if isinstance(v, ast.AST))
        elif isinstance(value, ast.AST):
            queue.append(value)
    while queue:
        node = queue.pop(0)
        if isinstance(node, ast.stmt):
            continue
        yield node
        queue.extend(ast.iter_child_nodes(node))


def _stmt_slots(node: ast.AST) -> Any:
    for fieldname in ("body", "orelse", "finalbody"):
        stmts = getattr(node, fieldname, None)
        if isinstance(stmts, list):
            for idx, st in enumerate(stmts):
                yield stmts, idx, st
            for st in stmts:
                yield from _stmt_slots(st)


def mutation_sites(tree: ast.Module) -> List[Site]:
    """Every single-point mutation available in this tree, in a stable order."""
    sites: List[Site] = []
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        last = fn.body[-1]
        for stmts, idx, st in _stmt_slots(fn):
            # -- exception removal -------------------------------------------
            if isinstance(st, ast.Raise):
                sites.append(Site("exception", st.lineno, st.col_offset, fn.name,
                                  ast.unparse(st), "pass",
                                  (lambda s=stmts, i=idx: s.__setitem__(i, ast.Pass()))))
            # -- statement deletion ------------------------------------------
            deletable = isinstance(st, (ast.Assign, ast.AugAssign))
            if isinstance(st, ast.Expr) and not (isinstance(st.value, ast.Constant)
                                                 and isinstance(st.value.value, str)):
                deletable = True
            if isinstance(st, ast.Return) and st is not last:
                deletable = True
            if deletable:
                sites.append(Site("deletion", st.lineno, st.col_offset, fn.name,
                                  ast.unparse(st), "pass",
                                  (lambda s=stmts, i=idx: s.__setitem__(i, ast.Pass()))))
            # -- return-value replacement ------------------------------------
            if isinstance(st, ast.Return) and st.value is not None:
                if isinstance(st.value, ast.Constant) and isinstance(st.value.value, int):
                    new: ast.expr = ast.Constant(value=st.value.value + 1)
                else:
                    new = ast.Constant(value=None)
                sites.append(Site("return", st.lineno, st.col_offset, fn.name,
                                  ast.unparse(st), "return " + ast.unparse(new),
                                  (lambda r=st, v=new: setattr(r, "value", v))))
            # -- expression-level operators inside this statement ------------
            for node in _own_exprs(st):
                if isinstance(node, ast.Compare) and len(node.ops) == 1:
                    op = type(node.ops[0])
                    if op in CMP_BOUNDARY:
                        sites.append(Site("boundary", node.lineno, node.col_offset, fn.name,
                                          OPSYM[op], OPSYM[CMP_BOUNDARY[op]],
                                          (lambda c=node, o=CMP_BOUNDARY[op]:
                                           c.ops.__setitem__(0, o()))))
                    if op in CMP_NEGATE:
                        sites.append(Site("conditional", node.lineno, node.col_offset, fn.name,
                                          OPSYM[op], OPSYM[CMP_NEGATE[op]],
                                          (lambda c=node, o=CMP_NEGATE[op]:
                                           c.ops.__setitem__(0, o()))))
                if isinstance(node, ast.BinOp) and type(node.op) in ARITH:
                    op2 = type(node.op)
                    sites.append(Site("arithmetic", node.lineno, node.col_offset, fn.name,
                                      OPSYM[op2], OPSYM[ARITH[op2]],
                                      (lambda b=node, o=ARITH[op2]: setattr(b, "op", o()))))
            # -- conditional negation of the decision itself -----------------
            if isinstance(st, (ast.If, ast.While)):
                sites.append(Site("conditional", st.lineno, st.col_offset, fn.name,
                                  ast.unparse(st.test), "not (" + ast.unparse(st.test) + ")",
                                  (lambda w=st: setattr(
                                      w, "test", ast.UnaryOp(op=ast.Not(), operand=w.test)))))
    sites.sort(key=lambda s: (s.lineno, s.col, s.operator, s.before, s.after))
    return sites


def build_mutant(source: str, index: int) -> Tuple[ast.Module, Site]:
    tree = ast.parse(source)
    sites = mutation_sites(tree)
    site = sites[index]
    site.apply()
    return tree, site


@dataclass
class MutantResult:
    index: int
    site: Site
    status: str  # killed | survived | timeout


def run_mutation(source: str, path: str, tests: Sequence[Test],
                 baseline: Sequence[bool], indices: Sequence[int],
                 needs_budget: Callable[[Site], bool]) -> Tuple[List[MutantResult], int]:
    """Run `tests` against every mutant in `indices`. Returns results and the
    number of individual test executions performed (the cost unit)."""
    out: List[MutantResult] = []
    executions = 0
    for i in indices:
        tree, site = build_mutant(source, i)
        try:
            mod = load_tree(tree, path)
        except Exception:
            out.append(MutantResult(i, site, "killed"))
            continue
        res, timed = run_suite(mod, tests, path, budget=needs_budget(site))
        executions += len(tests)
        if timed:
            out.append(MutantResult(i, site, "timeout"))
        elif any(b and not r for b, r in zip(baseline, res)):
            out.append(MutantResult(i, site, "killed"))
        else:
            out.append(MutantResult(i, site, "survived"))
    return out, executions


# ══ 5 · THE EQUIVALENCE PROBE ════════════════════════════════════════════════
# Deciding whether a mutant is equivalent to the original is undecidable in
# general (Jia & Harman, IEEE TSE 37(5), 2011, §5.1 — it reduces to program
# equivalence). What IS decidable is whether any input in a chosen finite set
# distinguishes them. So we build a large probe set, run both programs over all
# of it, and report the mutants that no probe separates. Those are CANDIDATES,
# not proofs: the honest claim is "no input we tried tells these apart".


def build_probes(rng: random.Random) -> List[Tuple[str, Tuple[Any, ...]]]:
    probes: List[Tuple[str, Tuple[Any, ...]]] = []
    qtys = (-2, -1, 0, 1, 9, 10, 11, 99, 100, 101, 500)
    tiers = ("gold", "standard", "")
    for q, t in itertools.product(qtys, tiers):
        probes.append(("discount_pct", (q, t)))
    for u, q, t in itertools.product((-1, 0, 1, 250, 333), (0, 1, 10, 100), tiers):
        probes.append(("line_total", (u, q, t)))
    for s, e in itertools.product((-1, 0, 1, 4999, 5000, 5001, 99999), (True, False)):
        probes.append(("shipping_cents", (s, e)))
    for tot in (-100, 0, 1, 500, 1000):
        for cr in ([], [0], [1], [500], [1000], [1001], [400, 400, 400], [1, 1], [-5]):
            probes.append(("apply_credits", (tot, tuple(cr))))
    for tot, n in itertools.product((-1, 0, 1, 1000, 1001), (-1, 0, 1, 2, 3, 7)):
        probes.append(("installments", (tot, n)))
    for _ in range(120):
        items = tuple((rng.choice((0, 1, 250, 333)), rng.choice((0, 1, 10, 120)))
                      for _ in range(rng.randint(0, 3)))
        probes.append(("order_total", (items, rng.choice(tiers), rng.choice((True, False)),
                                       tuple(rng.choice(((), (100,), (99999,))) for _ in "x")[0])))
    return probes


def probe_signature(mod: Any, probes: Sequence[Tuple[str, Tuple[Any, ...]]],
                    path: str, budget: bool) -> Tuple[str, ...]:
    sig: List[str] = []
    for name, args in probes:
        call_args = tuple(list(a) if isinstance(a, tuple) and name in
                          ("apply_credits", "order_total") else a for a in args)
        try:
            fn = getattr(mod, name)
            val = call_budgeted(path, STEP_BUDGET, fn, *call_args) if budget else fn(*call_args)
            sig.append("v:" + repr(val))
        except BudgetExceeded:
            sig.append("t:")
        except Exception as exc:
            sig.append("e:" + type(exc).__name__)
    return tuple(sig)


# ══ 6 · PATH COUNTING ════════════════════════════════════════════════════════


def branchy_source(n: int, dependent: bool) -> str:
    lines = ["def route(flags):", "    score = 0"]
    for k in range(n):
        test = f"flags[{k}]" if not dependent or k == 0 else f"flags[{k}] and flags[{k - 1}]"
        lines.append(f"    if {test}:")
        lines.append(f"        score = score + {2 ** k}")
    lines.append("    return score")
    return "\n".join(lines) + "\n"


def count_paths(source: str, n: int, path: str) -> Tuple[int, int, int, int, int]:
    """Distinct executed line-sequences over all 2^n inputs, plus the line and
    branch coverage a two-test suite achieves."""
    st = analyse(source)
    mod = load(source, path)
    seen: Set[Tuple[int, ...]] = set()
    for combo in itertools.product((False, True), repeat=n):
        tr = CoverageTracer(path, st.starts, record_order=True)
        with tr:
            mod.route(list(combo))
        seen.add(tuple(tr.order))
    two = CoverageTracer(path, st.starts)
    with two:
        mod.route([True] * n)
        mod.route([False] * n)
    lh, lp, bh, bp = coverage_of(st, two)
    return len(seen), 2 ** n, lh * 100 // lp, bh * 100 // bp, len(st.branches)


def mcdc_minimum() -> Tuple[int, int, List[Tuple[int, ...]]]:
    """A decision with four conditions: how many tests does MC/DC need?

    MC/DC = Modified Condition/Decision Coverage (RTCA DO-178C, 2011): every
    condition must be shown to independently affect the decision — i.e. for
    each condition there must be two tests differing only in that condition
    and producing different decisions.
    """
    def decision(v: Tuple[int, ...]) -> bool:
        a, b, c, d = v
        return bool((a and b) or (c and d))

    space = list(itertools.product((0, 1), repeat=4))
    pairs: Dict[int, List[Tuple[Tuple[int, ...], Tuple[int, ...]]]] = {k: [] for k in range(4)}
    for x, y in itertools.combinations(space, 2):
        diff = [k for k in range(4) if x[k] != y[k]]
        if len(diff) == 1 and decision(x) != decision(y):
            pairs[diff[0]].append((x, y))
    for size in range(2, 8):
        for cand in itertools.combinations(space, size):
            s = set(cand)
            if all(any(x in s and y in s for x, y in pairs[k]) for k in range(4)):
                return size, len(space), list(cand)
    return -1, len(space), []


# ══ MAIN ═════════════════════════════════════════════════════════════════════


def main() -> None:
    started = time.perf_counter()
    rng = random.Random(SEED)
    tmp = TemporaryDirectory()
    path = str(Path(tmp.name) / "pricing.py")
    Path(path).write_text(TARGET_SOURCE, encoding="utf-8")

    st = analyse(TARGET_SOURCE)
    base_mod = load(TARGET_SOURCE, path)
    sites = mutation_sites(ast.parse(TARGET_SOURCE))
    loops = {"installments"}  # the only function whose mutants can fail to terminate

    def needs_budget(s: Site) -> bool:
        return s.func in loops or s.func == "order_total"

    suites: List[Tuple[str, List[Test]]] = [
        ("1 calls everything, asserts nothing", suite_no_assert()),
        ("2 smoke: a value came back", suite_smoke()),
        ("3 + happy-path values", suite_happy()),
        ("4 + error paths", suite_errors()),
        ("5 + boundary cases", suite_boundary()),
    ]

    # ── 1 ────────────────────────────────────────────────────────────────────
    banner(1, "THE NO-ASSERT SUITE: 100% LINE COVERAGE, 0% DETECTION")
    print("  the module under test: 6 functions,", len(st.lines), "executable lines,",
          len(st.branches), "two-way branches.")
    print("  the suite: calls every function over a grid of inputs, swallows every")
    print("  exception, and contains not one assertion. Every test passes.\n")

    no_assert = suites[0][1]
    tr = CoverageTracer(path, st.starts)
    with tr:
        base_res, _ = run_suite(base_mod, no_assert)
    lh, lp, bh, bp = coverage_of(st, tr)
    all_idx = list(range(len(sites)))
    na_results, _ = run_mutation(TARGET_SOURCE, path, no_assert, base_res, all_idx, needs_budget)
    na_killed = sum(1 for r in na_results if r.status != "survived")

    print(f"    tests                     {len(no_assert)}")
    print(f"    tests passing             {sum(base_res)}/{len(base_res)}")
    print(f"    assertions in the suite   0")
    print(f"    line coverage             {lh}/{lp}   {pct(lh, lp)}")
    print(f"    branch coverage           {bh}/{bp}   {pct(bh, bp)}")
    print(f"    mutants killed            {na_killed}/{len(sites)}   {pct(na_killed, len(sites))}")
    print("\n  A CI gate of 'fail_under = 90' passes this suite. It detects nothing.")

    # ── 2 ────────────────────────────────────────────────────────────────────
    banner(2, "WHAT COVERAGE MEASURES: LINE 100%, BRANCH 50%, SAME TEST")
    ship_src = "\n".join(TARGET_SOURCE.split("\n")[
        TARGET_SOURCE.split("\n").index("def shipping_cents(subtotal_cents, express):"):][:8])
    ship_st = analyse(ship_src)
    ship_mod = load(ship_src, path)
    t2 = CoverageTracer(path, ship_st.starts)
    with t2:
        ship_mod.shipping_cents(6000, True)
    a, b, c, d = coverage_of(ship_st, t2)
    print("    def shipping_cents(subtotal_cents, express):")
    print("        fee = 499")
    print("        if subtotal_cents >= 5000:")
    print("            fee = 0")
    print("        if express:")
    print("            fee = fee + 1200")
    print("        return fee\n")
    print(f"    one test — shipping_cents(6000, True):")
    print(f"      line coverage    {a}/{b}   {pct(a, b)}   every line ran")
    print(f"      branch coverage  {c}/{d}   {pct(c, d)}   neither false outcome ever ran")
    print("\n  The free-shipping-off path and the standard-shipping path are untested,")
    print("  and line coverage reports 100%. This is not an edge case; it is the")
    print("  ordinary behaviour of the metric on an `if` with no `else`.")

    size, space, cand = mcdc_minimum()
    print(f"\n  the criteria, on a 4-condition decision  (a and b) or (c and d):")
    print(f"    line coverage      1 test   'the statement ran'")
    print(f"    branch coverage    2 tests  'the decision was both true and false'")
    print(f"    MC/DC              {size} tests  'each condition independently flipped it'"
          f"   (n+1 = 5)")
    print(f"    condition combos   {space} tests  every assignment of the 4 conditions")

    # ── 3 ────────────────────────────────────────────────────────────────────
    banner(3, "COVERAGE IS A CEILING, NOT A FLOOR")
    partial = suite_typical_incomplete()
    tr3 = CoverageTracer(path, st.starts)
    with tr3:
        base3, _ = run_suite(base_mod, partial)
    l3h, l3p, b3h, b3p = coverage_of(st, tr3)
    res3, _ = run_mutation(TARGET_SOURCE, path, partial, base3, all_idx, needs_budget)
    covered = st.lines & tr3.lines
    on_cov = [r for r in res3 if r.site.lineno in covered]
    off_cov = [r for r in res3 if r.site.lineno not in covered]
    k_on = sum(1 for r in on_cov if r.status != "survived")
    k_off = sum(1 for r in off_cov if r.status != "survived")
    print(f"  a perfectly ordinary suite: {len(partial)} tests, line coverage {pct(l3h, l3p)}"
          f" ({l3h}/{l3p}).\n")
    print("    mutants sited on...        count   killed   kill rate")
    print(f"    a line the suite ran       {len(on_cov):5}   {k_on:6}   {pct(k_on, len(on_cov))}")
    print(f"    a line it did not run      {len(off_cov):5}   {k_off:6}   "
          f"{pct(k_off, len(off_cov))}")
    print("\n  P(bug caught | line never ran) = 0, exactly, by construction — you cannot")
    print(f"  detect a change to code you never execute. P(bug caught | line ran) ="
          f" {pct(k_on, len(on_cov)).strip()}, not 100%.")
    print("  That asymmetry is the whole correct reading of coverage: low coverage is")
    print("  hard evidence of a gap; high coverage is not evidence of anything.")

    # ── 4 ────────────────────────────────────────────────────────────────────
    banner(4, "PATH EXPLOSION: WHY 100% PATH COVERAGE IS UNREACHABLE")
    print("  paths enumerated by tracing the function over every input combination.")
    print("  'dependent' is the same function with each condition ANDed to the previous.\n")
    print(f"    {'branches':>8}   {'2^n predicts':>13}   {'measured':>14}   "
          f"{'dependent conds':>20}    {'2-test cov':>9}")
    for n in (4, 8, 10):
        seen, total, lcov, bcov, nb = count_paths(branchy_source(n, False), n, path)
        seen_d, _, _, _, _ = count_paths(branchy_source(n, True), n, path)
        print(f"    {nb:8}   {total:13}   {seen:14}   {seen_d:20}    {lcov:9}% / {bcov}%")
    print("\n  Ten independent branches is a small function. Two tests — all-true and")
    print("  all-false — reach 100% line and 100% branch coverage and 2 of 1024 paths")
    print("  (0.2%). At 1 ms per test, exhausting the paths of a 10-branch function")
    print("  takes 1.0 s; 20 branches takes 17.5 min; 30 branches takes 12.4 days.")
    print("  A loop with a branch in its body and no bound has infinitely many.")

    # ── 5 ────────────────────────────────────────────────────────────────────
    banner(5, "THE MUTATION ENGINE: SIX OPERATORS OVER ONE MODULE")
    by_op: Dict[str, int] = {}
    for s in sites:
        by_op[s.operator] = by_op.get(s.operator, 0) + 1
    print(f"  {len(sites)} mutants from {len(st.lines)} executable lines"
          f" ({len(sites) / len(st.lines):.2f} per line):\n")
    print("    operator      mutants   example")
    example = {}
    for s in sites:
        example.setdefault(s.operator, f"L{s.lineno}  {s.before}  ->  {s.after}")
    for op in sorted(by_op):
        print(f"    {op:<12}  {by_op[op]:7}   {example[op]}")

    best = suites[-1][1]
    base5, _ = run_suite(base_mod, best)
    res5, _ = run_mutation(TARGET_SOURCE, path, best, base5, all_idx, needs_budget)
    counts = {"killed": 0, "survived": 0, "timeout": 0}
    for r in res5:
        counts[r.status] += 1
    print(f"\n  the best suite ({len(best)} tests) against all {len(sites)} mutants:")
    print(f"    killed    {counts['killed']:4}")
    print(f"    timeout   {counts['timeout']:4}   (a non-terminating mutant: also detected)")
    print(f"    survived  {counts['survived']:4}   <- the suite cannot tell these from the"
          f" original")
    print(f"    mutation score  {pct(counts['killed'] + counts['timeout'], len(sites))}")
    print("\n  survivors, by operator:")
    surv_by_op: Dict[str, int] = {}
    for r in res5:
        if r.status == "survived":
            surv_by_op[r.site.operator] = surv_by_op.get(r.site.operator, 0) + 1
    for op in sorted(by_op):
        print(f"    {op:<12}  {surv_by_op.get(op, 0):3} of {by_op[op]:3} survived")

    # ── 6 ────────────────────────────────────────────────────────────────────
    banner(6, "THE DIVERGENCE: FIVE SUITES, THREE METRICS")
    print("    suite                                tests   line     branch   mutation")
    divergence: List[Tuple[str, int, str, str, str]] = []
    per_suite_results: Dict[str, List[MutantResult]] = {}
    for name, tests in suites:
        tr_s = CoverageTracer(path, st.starts)
        with tr_s:
            base_s, _ = run_suite(base_mod, tests)
        lhs, lps, bhs, bps = coverage_of(st, tr_s)
        res_s, _ = run_mutation(TARGET_SOURCE, path, tests, base_s, all_idx, needs_budget)
        per_suite_results[name] = res_s
        killed = sum(1 for r in res_s if r.status != "survived")
        row = (name, len(tests), pct(lhs, lps), pct(bhs, bps), pct(killed, len(sites)))
        divergence.append(row)
        print(f"    {name:<35}  {len(tests):5}   {pct(lhs, lps)}   {pct(bhs, bps)}   "
              f"{pct(killed, len(sites))}")
    print("\n  Line coverage is at its maximum on suite 1 and never moves again. Branch")
    print("  coverage saturates by suite 3. Mutation score is still climbing at suite 5.")
    print("  The gap between the first column and the last is the amount of quality")
    print("  difference that coverage is structurally unable to see.")

    # ── 7 ────────────────────────────────────────────────────────────────────
    banner(7, "EQUIVALENT MUTANTS: THE CEILING NOBODY CAN REACH")
    probes = build_probes(rng)
    base_sig = probe_signature(base_mod, probes, path, budget=False)

    # Hand analysis. Each of these was read, reasoned about and written down by
    # a human; the probe set only tells you WHICH mutants to go and read.
    REASONS = {
        (14, "boundary"): "pct only ever takes 0/5/8/13/15/23 — never exactly 20",
        (38, "deletion"): "the fast path is redundant: the loop below returns total_cents",
        (42, "boundary"): "setting remaining to 0 when it is already 0 is a no-op",
    }

    print(f"  {len(probes)} probe calls spanning every function, run against the original")
    print("  and against every survivor. A survivor no probe separates from the original")
    print("  is an equivalent-mutant CANDIDATE — 'no input we tried tells these apart'.\n")
    print("    suite                                survivors   indistinguishable   real gaps")
    equivalents: List[MutantResult] = []
    for name in (suites[2][0], suites[4][0]):
        survivors = [r for r in per_suite_results[name] if r.status == "survived"]
        same: List[MutantResult] = []
        for r in survivors:
            tree, site = build_mutant(TARGET_SOURCE, r.index)
            mod = load_tree(tree, path)
            if probe_signature(mod, probes, path, budget=needs_budget(site)) == base_sig:
                same.append(r)
        if name == suites[4][0]:
            equivalents = same
        print(f"    {name:<35}   {len(survivors):9}   {len(same):17}   "
              f"{len(survivors) - len(same):9}")
    print("\n  Triage in one step: the 'real gaps' column is the work list, and the")
    print("  'indistinguishable' column is the part of the score you will never recover.\n")
    print("  the candidates, and why each is unkillable — read by hand, one at a time:")
    for r in sorted(equivalents, key=lambda x: (x.site.lineno, x.site.operator)):
        why = REASONS.get((r.site.lineno, r.site.operator), "")
        print(f"    L{r.site.lineno:<3} {r.site.operator:<10} {r.site.before:<22} -> "
              f"{r.site.after}")
        print(f"         {why}")
    ceiling = (len(sites) - len(equivalents)) / len(sites)
    print(f"\n  equivalent-mutant rate over all {len(sites)} mutants:"
          f" {pct(len(equivalents), len(sites))}")
    print("\n  Worked proof, the clearest of them — apply_credits:")
    print("      if not credits:")
    print("          return total_cents      <- delete this line")
    print("      remaining = total_cents")
    print("      for c in credits: ...")
    print("      return remaining")
    print("  With `credits` empty the deleted fast path falls through to a loop that")
    print("  does not execute, and the function returns `total_cents` anyway. The mutant")
    print("  computes the same function on every input in its domain. No test can kill")
    print("  it, because there is nothing to detect.")
    print("  Deciding this in general reduces to program equivalence and is therefore")
    print("  undecidable (Jia & Harman, IEEE TSE 37(5), 2011, on the equivalent-mutant")
    print("  problem). 100% is not the target: the achievable ceiling on this module is")
    print(f"  {100 * ceiling:.1f}%, and the best suite reaches"
          f" {pct(counts['killed'] + counts['timeout'], len(sites)).strip()}.")

    # ── 8 ────────────────────────────────────────────────────────────────────
    banner(8, "GOODHART: OPTIMISING FOR COVERAGE VS OPTIMISING FOR KILLS")
    pool = suite_no_assert() + suite_boundary()[6:]
    base_pool, _ = run_suite(base_mod, pool)
    per_test_lines: List[Set[int]] = []
    for t in pool:
        trt = CoverageTracer(path, st.starts)
        with trt:
            run_suite(base_mod, [t])
        per_test_lines.append(st.lines & trt.lines)
    per_test_kills: List[Set[int]] = []
    for ti, t in enumerate(pool):
        res_t, _ = run_mutation(TARGET_SOURCE, path, [t], [base_pool[ti]], all_idx, needs_budget)
        per_test_kills.append({r.index for r in res_t if r.status != "survived"})

    def greedy(score: List[Set[int]], budget: int) -> List[int]:
        chosen: List[int] = []
        got: Set[int] = set()
        while len(chosen) < budget:
            gains = [(len(score[i] - got), -i) for i in range(len(pool)) if i not in chosen]
            gain, negi = max(gains)
            chosen.append(-negi)
            got |= score[-negi]
        return chosen

    BUDGET = 8
    for label, sel in (("optimises for line coverage", greedy(per_test_lines, BUDGET)),
                       ("optimises for mutants killed", greedy(per_test_kills, BUDGET))):
        tests = [pool[i] for i in sorted(sel)]
        trg = CoverageTracer(path, st.starts)
        with trg:
            bg, _ = run_suite(base_mod, tests)
        lg, lpg, bg2, bpg = coverage_of(st, trg)
        rg, _ = run_mutation(TARGET_SOURCE, path, tests, bg, all_idx, needs_budget)
        kg = sum(1 for r in rg if r.status != "survived")
        noassert = sum(1 for t in tests if t.name.startswith("no_assert"))
        print(f"    a team that {label:<30} ({BUDGET} tests)")
        print(f"      line coverage   {pct(lg, lpg)}      branch {pct(bg2, bpg)}"
              f"      mutation score {pct(kg, len(sites))}")
        print(f"      assertion-free tests it chose: {noassert} of {BUDGET}")
    print("\n  Same pool of candidate tests, same budget of 8 tests, two objectives. The")
    print("  two suites are INDISTINGUISHABLE on every coverage metric a CI gate reads,")
    print("  and one of them detects roughly half of what the other does. A coverage")
    print("  target does not merely fail to measure quality — it pays, in review time")
    print("  and in run time, for the tests that have none. (Goodhart, 'Problems of")
    print("  Monetary Management', 1975: a measure that becomes a target stops")
    print("  measuring what it measured.)")

    # ── 9 ────────────────────────────────────────────────────────────────────
    banner(9, "COST: FULL-MODULE VERSUS DIFF-ONLY MUTATION")
    changed = {"apply_credits", "installments"}
    diff_idx = [i for i, s in enumerate(sites) if s.func in changed]
    full_res, full_exec = run_mutation(TARGET_SOURCE, path, best, base5, all_idx, needs_budget)
    diff_res, diff_exec = run_mutation(TARGET_SOURCE, path, best, base5, diff_idx, needs_budget)
    fk = sum(1 for r in full_res if r.status != "survived")
    dk = sum(1 for r in diff_res if r.status != "survived")
    changed_lines = sum(1 for l in sorted(st.lines) if st.line_owner[l] in changed)
    print(f"  the diff touches 2 of 6 functions ({changed_lines} of {len(st.lines)}"
          f" executable lines).\n")
    print("    scope             mutants   suite runs   test executions   score")
    print(f"    whole module      {len(all_idx):7}   {len(all_idx):10}   {full_exec:15}"
          f"   {pct(fk, len(all_idx))}")
    print(f"    changed lines     {len(diff_idx):7}   {len(diff_idx):10}   {diff_exec:15}"
          f"   {pct(dk, len(diff_idx))}")
    print(f"    ratio             {len(all_idx) / max(1, len(diff_idx)):6.1f}x"
          f"   {len(all_idx) / max(1, len(diff_idx)):9.1f}x"
          f"   {full_exec / max(1, diff_exec):14.1f}x")
    density = len(sites) / len(st.lines)
    print("\n  Cost is reported in test executions, not seconds, so that two runs of this")
    print("  program produce byte-identical output. The arithmetic transfers either way:")
    print("  mutation testing costs (mutants x suite run), and mutants scale with lines.\n")
    print(f"    measured mutant density                 {density:.2f} per executable line")
    for label, loc, workers in (("a 12,000-line service", 12000, 8),
                                ("one 800-line module", 800, 8),
                                ("a 60-line pull request", 60, 8)):
        m = int(round(loc * density))
        secs = m * 30 / workers
        unit = f"{secs / 3600:.1f} hours" if secs > 3600 else f"{secs / 60:.1f} minutes"
        print(f"    {label:<24} {m:6} mutants  x 30 s suite / {workers} workers = {unit}")
    print("\n  The first belongs in a nightly job behind --paths-to-mutate. The last one")
    print("  fits inside a pull request — and it is the one scoped to the lines that")
    print("  actually changed, which is where this week's bugs are.")

    tmp.cleanup()
    # To stderr, not stdout: a wall-clock value on stdout makes consecutive runs
    # differ, and this phase's contract is that stdout is byte-identical run to run.
    print(f"\nelapsed {time.perf_counter() - started:.2f}s  (not quoted in the lesson)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
