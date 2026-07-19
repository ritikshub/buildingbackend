#!/usr/bin/env python3
"""
The shape of a test suite, derived rather than asserted. One call-graph model of a
backend service, a 12-class defect population, per-level detection computed from
test SCOPE and environment CAPABILITY, failure localisation measured in implicated
lines, and the central result: given a fixed CI budget, the composition maximising
expected defects caught -- solved numerically, verified against exhaustive search,
then swept over budget, over cost ratio, over oracle strength, and with flake and
localisation priced in engineer-minutes.

Companion to docs/en.md (Phase 12, Lesson 02). Standard library only, seed 20260718,
deterministic, self-terminating in about a second. Sources: Cohn, *Succeeding with
Agile: Software Development Using Scrum*, Addison-Wesley, 2009 (the test pyramid);
Dijkstra, *Notes on Structured Programming*, EWD249, 1970; Humble & Farley,
*Continuous Delivery*, Addison-Wesley, 2010 (the ten-minute feedback rule).

Run:  python3 suite_shape.py
"""

from __future__ import annotations

import math
import random
from typing import Callable, NamedTuple, Sequence

SEED = 20260718

# ── the four levels, and everything that distinguishes them ───────────────────
# COST and FLAKE are the two numbers you must measure in YOUR repo; every result
# below is downstream of them, which is the lesson. The defaults are a plausible
# mid-size Python service: a unit test that imports nothing, a contract
# verification over a loopback socket, an integration test against a real database
# on a warm connection, and an end-to-end test that stands up the whole stack.
LEVELS = ("unit", "contract", "integration", "e2e")
COST = [0.010, 0.25, 0.80, 14.0]              # seconds of CI per test, one worker
FLAKE = [0.00002, 0.00060, 0.00200, 0.01200]  # P(this test reds on a clean tree)
ORACLE = [0.85, 0.80, 0.70, 0.55]             # P(the assertion observes the defect)

# What each level's ENVIRONMENT makes reachable at all. A capability a level does
# not have is a hard zero, not a small number: no quantity of unit tests reaches a
# database constraint, because in a unit test there is no database.
CAPS: list[frozenset[str]] = [
    frozenset(),                                       # unit: doubles all the way down
    frozenset({"provider", "wire"}),                   # contract: real seam, over the wire
    frozenset({"db"}),                                 # integration: real database
    frozenset({"db", "config", "provider", "wire",     # e2e: the whole world
               "queue", "concurrency", "volume"}),
]

# ── the economics, in engineer-minutes ────────────────────────────────────────
BUILDS_PER_SPRINT = 40
P_DEFECT_PER_MERGE = 0.18       # P(a merged change carries a defect)
MIN_PER_ESCAPE = 480.0          # engineer-minutes when a defect reaches production
MIN_PER_FALSE_RED = 14.0        # fixed cost of a red build: notice, re-run, switch
FALSE_RED_READ = 0.35           # a false red is usually abandoned part-way in
DEBUG_FIXED = 6.0               # minutes to reproduce and open any failure
DEBUG_PER_LINE = 0.12           # minutes per implicated line, once you are reading
DEBUG = [0.0, 0.0, 0.0, 0.0]    # filled from the measured graph in main()
CI_WORKERS = 8                  # parallel workers, for wall-clock feedback latency
FEEDBACK_LIMIT_S = 600.0        # Humble & Farley's ten minutes, in seconds


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# The system under test, as a call graph. Everything else in this program is
# measured on this one object: how much code a failing test implicates, how likely
# a test at a given level is to execute a given defect, and therefore what a suite
# of a given shape is worth. Build it once, seeded, and never mutate it.

LAYER_SPEC = (
    # layer      count  min_lines  max_lines
    ("route",     10,   18, 34),
    ("worker",     5,   22, 42),
    ("service",   18,   26, 58),
    ("repo",      14,   14, 30),
    ("client",     6,   12, 26),
    ("util",      11,    8, 20),
)


class Graph(NamedTuple):
    layer: tuple[str, ...]            # layer[v]
    lines: tuple[int, ...]            # lines[v]
    cases: tuple[int, ...]            # distinguishable input cases inside v
    out: tuple[tuple[int, ...], ...]  # out[v] = callees
    by_layer: dict[str, tuple[int, ...]]
    edges: tuple[tuple[int, int], ...]


def build_graph(seed: int = SEED) -> Graph:
    """A deterministic layered DAG: routes and queue workers call services,
    services call repositories, outbound clients and each other, and everything
    calls utilities. Layer order is the topological order, so no cycle can be
    constructed and `closure` always terminates."""
    rng = random.Random(seed)
    layer: list[str] = []
    lines: list[int] = []
    by_layer: dict[str, list[int]] = {}
    for name, count, lo, hi in LAYER_SPEC:
        ids = []
        for _ in range(count):
            ids.append(len(layer))
            layer.append(name)
            lines.append(rng.randint(lo, hi))
        by_layer[name] = ids

    def pick(pool: Sequence[int], k: int) -> list[int]:
        k = min(k, len(pool))
        return sorted(rng.sample(list(pool), k)) if k else []

    out: list[list[int]] = [[] for _ in layer]
    svc, repo, cli, util = (by_layer["service"], by_layer["repo"],
                            by_layer["client"], by_layer["util"])
    for v in by_layer["route"]:
        out[v] = pick(svc, rng.randint(2, 3)) + pick(util, 1 if rng.random() < 0.5 else 0)
    for v in by_layer["worker"]:
        out[v] = pick(svc, rng.randint(1, 2))
    for i, v in enumerate(svc):
        callees = pick(repo, rng.randint(0, 3))
        if rng.random() < 0.40:
            callees += pick(cli, 1)
        callees += pick(util, rng.randint(1, 2))
        deeper = svc[i + 1:]
        if deeper and rng.random() < 0.35:
            callees += pick(deeper, 1)
        out[v] = sorted(set(callees))
    for v in repo + cli:
        out[v] = pick(util, 1 if rng.random() < 0.5 else 0)

    edges = tuple(sorted((u, w) for u, ws in enumerate(out) for w in ws))
    cases = tuple(max(2, ln // 6) for ln in lines)
    return Graph(tuple(layer), tuple(lines), cases,
                 tuple(tuple(o) for o in out),
                 {k: tuple(v) for k, v in by_layer.items()}, edges)


def closure(g: Graph, root: int, allowed: frozenset[str] | None = None) -> frozenset[int]:
    """Every node reachable from `root`, optionally restricted to some layers.
    This is a test's SCOPE: the code that one test at that level actually runs."""
    seen: set[int] = set()
    stack = [root]
    while stack:
        v = stack.pop()
        if v in seen:
            continue
        if allowed is not None and g.layer[v] not in allowed and v != root:
            continue
        seen.add(v)
        stack.extend(g.out[v])
    return frozenset(seen)


NO_CLIENT = frozenset({"service", "repo", "util", "worker"})


def scopes_for(g: Graph) -> tuple[tuple[frozenset[int], ...], ...]:
    """The complete, finite set of scopes a test at each level can have. These are
    enumerated exhaustively — there is no sampling anywhere in the core result."""
    unit = tuple(frozenset({v}) for v in range(len(g.layer)))
    # A contract test covers exactly one side of one seam: our outbound client's
    # recorded expectations of a provider, or one of our own routes replaying a
    # consumer's recorded expectations. Its ORACLE is the message shape, not the
    # business outcome, so its effective scope is that one node and nothing under it.
    contract = tuple(frozenset({v}) for v in g.by_layer["client"] + g.by_layer["route"])
    # An integration test enters at a service or worker entry point, runs the real
    # database, and doubles the outbound client — so the client subtree is out of
    # scope, and so is anything reachable only through it.
    integration = tuple(closure(g, e, NO_CLIENT)
                        for e in g.by_layer["service"] + g.by_layer["worker"])
    # An end-to-end test enters at an HTTP route or by publishing to the queue and
    # runs everything downstream, for real.
    e2e = tuple(closure(g, e) for e in g.by_layer["route"] + g.by_layer["worker"])
    return unit, contract, integration, e2e


def scope_stats(g: Graph, sc: Sequence[frozenset[int]]) -> tuple[float, int, float]:
    """(mean implicated lines, max implicated lines, mean distinct layers)."""
    impl = [sum(g.lines[v] for v in s) for s in sc]
    lay = [len({g.layer[v] for v in s}) for s in sc]
    return sum(impl) / len(impl), max(impl), sum(lay) / len(lay)


def section1(g: Graph, scopes) -> None:
    banner(1, "THE THREE AXES, MEASURED ON ONE CALL GRAPH")
    print(f"  service under test: {len(g.layer)} functions, {sum(g.lines)} lines, "
          f"{len(g.edges)} call edges")
    print("  layers  " + "  ".join(f"{n}:{len(g.by_layer[n])}" for n, *_ in LAYER_SPEC))
    print()
    print("    level         distinct   cost per   scope: fns   implicated lines"
          "   layers   flake")
    print("                    tests       test    mean   max    mean    max    "
          " in scope   per test")
    for li, name in enumerate(LEVELS):
        sc = scopes[li]
        nodes = [len(s) for s in sc]
        mean_i, max_i, mean_l = scope_stats(g, sc)
        print(f"    {name:<12} {len(sc):9d} {COST[li]:10.3f}s {sum(nodes)/len(nodes):7.1f}"
              f" {max(nodes):5d} {mean_i:7.0f} {max_i:6d} {mean_l:10.1f}"
              f" {FLAKE[li]:10.5f}")
    u_i = scope_stats(g, scopes[0])[0]
    e_i = scope_stats(g, scopes[3])[0]
    print(f"  the three axes of the whole lesson are those columns. A failing unit test")
    print(f"  implicates {u_i:.0f} lines in 1 layer; a failing end-to-end test implicates")
    print(f"  {e_i:.0f} lines across {scope_stats(g, scopes[3])[2]:.1f} layers — {e_i/u_i:.0f}x the reading — "
          f"and costs {COST[3]/COST[0]:.0f}x the")
    print(f"  CI seconds and {FLAKE[3]/FLAKE[0]:.0f}x the flake rate to produce. Three of those four")
    print("  favour the cheap level; the fourth is a hard capability limit, and section 2")
    print("  shows it is the one that decides the answer.")


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# The defect population and the catch matrix. A defect is a (class, site) pair. A
# test detects it when three independent things hold, and this is the whole model:
#
#   1. CAPABILITY   the level's environment can express the defect at all
#   2. SCOPE        the test actually executes the site
#   3. ORACLE       the test's assertion observes the resulting difference
#
# Detection probability per test is the mean of that product over every
# (site, scope) pair — exhaustive, so the matrix below is a computation, not an
# opinion about how good unit tests are.

class BugClass(NamedTuple):
    name: str
    weight: float          # share of the defect population
    sites: str             # where in the graph it can live
    needs: frozenset[str]  # capabilities required to reach or observe it


CLASSES: tuple[BugClass, ...] = (
    BugClass("logic",         0.20, "service+util",        frozenset()),
    BugClass("boundary",      0.14, "service+util+repo",   frozenset()),
    BugClass("wiring",        0.11, "edge",                frozenset()),
    BugClass("serialization", 0.08, "route",               frozenset({"wire"})),
    BugClass("contract",      0.08, "client",              frozenset({"provider"})),
    BugClass("auth",          0.07, "route",               frozenset({"wire"})),
    BugClass("schema",        0.07, "repo",                frozenset({"db"})),
    BugClass("concurrency",   0.06, "repo",                frozenset({"concurrency"})),
    BugClass("config",        0.05, "service+repo+client", frozenset({"config"})),
    BugClass("duplicate",     0.05, "worker",              frozenset({"queue"})),
    BugClass("n_plus_1",      0.05, "repo",                frozenset({"db", "volume"})),
    BugClass("migration",     0.04, "repo",                frozenset({"db"})),
)
CLASS_W = tuple(c.weight for c in CLASSES)
NC = len(CLASSES)


def sites_for(g: Graph, sel: str) -> list[tuple[int, ...]]:
    """Every place a defect of this class can live. A node-sited defect is a
    1-tuple; a wiring defect is a 2-tuple, because a wrong argument at a call site
    is only wrong when BOTH functions run — which is why no unit test can see it."""
    if sel == "edge":
        return [(u, v) for u, v in g.edges
                if g.layer[u] in ("route", "service", "worker")]
    layers = frozenset(sel.split("+"))
    return [(v,) for v in range(len(g.layer)) if g.layer[v] in layers]


def detection_matrix(g: Graph, scopes) -> list[list[float]]:
    """p[level][class] = P(one randomly targeted test at this level detects one
    randomly placed defect of this class)."""
    p = [[0.0] * NC for _ in LEVELS]
    for ci, bc in enumerate(CLASSES):
        sites = sites_for(g, bc.sites)
        for li in range(len(LEVELS)):
            if not bc.needs <= CAPS[li]:
                continue          # hard zero: the environment cannot express it
            acc = 0.0
            for site in sites:
                inv_cases = 1.0 / g.cases[site[0]]
                for sc in scopes[li]:
                    if all(v in sc for v in site):
                        acc += inv_cases
            p[li][ci] = ORACLE[li] * acc / (len(sites) * len(scopes[li]))
    return p


def section2(g: Graph, scopes) -> list[list[float]]:
    banner(2, "THE CATCH MATRIX: WHAT ONE TEST AT EACH LEVEL IS WORTH")
    p = detection_matrix(g, scopes)
    print("  P(one test detects one defect of this class) x1000. A dot is a HARD zero:")
    print("  the level's environment cannot express that defect at ANY test count.")
    print()
    print("    class          weight      unit  contract  integr'n      e2e   "
          "levels that can reach it")
    for ci, bc in enumerate(CLASSES):
        cells = "".join("       ." if p[li][ci] == 0.0 else f"{p[li][ci]*1000:8.2f}"
                        for li in range(4))
        reach = ",".join(LEVELS[li] for li in range(4) if p[li][ci] > 0) or "NOTHING"
        print(f"    {bc.name:<14} {bc.weight:5.2f}  {cells}   {reach}")
    print()
    for li, name in enumerate(LEVELS):
        share = sum(CLASS_W[ci] for ci in range(NC) if p[li][ci] > 0)
        print(f"    {name:<12} reaches {share:5.1%} of the defect population at INFINITE"
              f" test count")
    print("  those ceilings are the reason a suite has a shape at all. 'wiring' is a dot\n"
          "  in the unit column by construction — a unit test's scope is one function and a\n"
          "  wiring defect lives on the edge between two — and every hard zero after it is\n"
          "  a capability the cheaper environment simply does not have.")
    return p


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# Failure localisation. When a test goes red, how much code is a candidate? This is
# the argument for unit tests that everyone makes as a feeling ("they pin the bug
# down") and nearly nobody makes as a number. Section 6 turns it into minutes.

def section3(g: Graph, scopes, p: list[list[float]]) -> None:
    banner(3, "FAILURE LOCALISATION: HOW MUCH CODE DOES A RED TEST IMPLICATE?")
    total = sum(g.lines)
    print(f"  the service is {total} lines. A red test narrows that to its scope.")
    print()
    print("    level        implicated lines     share of   bisection   minutes to")
    print("                  mean   p90    max   codebase     steps      diagnose")
    for li, name in enumerate(LEVELS):
        impl = sorted(sum(g.lines[v] for v in s) for s in scopes[li])
        mean = sum(impl) / len(impl)
        p90 = impl[min(len(impl) - 1, int(0.90 * len(impl)))]
        dbg = DEBUG_FIXED + DEBUG_PER_LINE * mean
        print(f"    {name:<12} {mean:6.0f} {p90:5d} {max(impl):6d} {mean/total:10.1%}"
              f" {math.log2(max(2.0, mean)):11.1f} {dbg:13.1f}")
    u = scope_stats(g, scopes[0])[0]
    e = scope_stats(g, scopes[3])[0]
    print(f"  {e/u:.0f}x the code to read, and {math.log2(e)-math.log2(u):.1f} extra halvings"
          f" if you bisect systematically.")
    print(f"  the minutes column is {DEBUG_FIXED:.0f} + {DEBUG_PER_LINE} x lines, and it is the term"
          f" section 6 prices.")
    print("  now the number that complicates the story:")
    print()
    print("    level        detection per CI-second   detection per implicated line")
    for li, name in enumerate(LEVELS):
        per_test = sum(CLASS_W[ci] * p[li][ci] for ci in range(NC))
        impl = scope_stats(g, scopes[li])[0]
        print(f"    {name:<12} {per_test/COST[li]*1000:22.3f}   {per_test/impl*1e6:24.2f}")
    print("  per CI-second the unit level wins by two orders of magnitude — but the catch\n"
          "  matrix already showed it can only ever reach part of the population. 'Most\n"
          "  detection per second' and 'the suite you want' are different claims.")


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# Budget allocation as an optimisation problem. THIS IS THE LESSON.
#
#   maximise    sum_c  w_c * (1 - prod_L (1 - p_Lc)^{n_L})
#   subject to  sum_L  n_L * cost_L  <=  B,        n_L integer >= 0
#
# The objective is the expected share of the defect population caught, assuming
# tests are independently targeted. That assumption is generous to large suites —
# real tests cluster on the code someone was already thinking about — and it is
# stated here so you can discount it; section 5 sweeps the parameter it depends on.
# The objective is concave in each n_L and submodular overall, so greedy on
# marginal value per second is near-optimal. We polish with local search and then
# VERIFY against exhaustive enumeration rather than asserting optimality.

Composition = list[int]


def seconds(n: Sequence[int]) -> float:
    return n[0] * COST[0] + n[1] * COST[1] + n[2] * COST[2] + n[3] * COST[3]


def make_logq(p: list[list[float]]) -> list[list[float]]:
    return [[math.log1p(-p[li][ci]) if p[li][ci] > 0 else 0.0 for ci in range(NC)]
            for li in range(4)]


def expected_catch(n: Sequence[int], logq: list[list[float]]) -> float:
    tot = 0.0
    for ci in range(NC):
        s = (n[0] * logq[0][ci] + n[1] * logq[1][ci]
             + n[2] * logq[2][ci] + n[3] * logq[3][ci])
        tot += CLASS_W[ci] * -math.expm1(s)
    return tot


def attribution(n: Sequence[int], logq: list[list[float]]) -> tuple[list[float], float]:
    """P(a defect is first caught at level L), levels tried in cost order — which
    is the order a real pipeline runs them, cheapest gate first. Returns the
    per-level shares and the share that escapes everything."""
    order = sorted(range(4), key=lambda i: COST[i])
    share = [0.0, 0.0, 0.0, 0.0]
    escaped = 0.0
    for ci in range(NC):
        surv = 1.0
        for li in order:
            passed = math.exp(n[li] * logq[li][ci])
            share[li] += CLASS_W[ci] * surv * (1.0 - passed)
            surv *= passed
        escaped += CLASS_W[ci] * surv
    return share, escaped


def build_green(n: Sequence[int]) -> float:
    """P(a build on a clean tree comes back green) — Lesson 09's arithmetic, early."""
    return math.exp(sum(n[i] * math.log1p(-FLAKE[i]) for i in range(4)))


def wall_seconds(n: Sequence[int]) -> float:
    return seconds(n) / CI_WORKERS


def false_red_cost(li: int) -> float:
    """Minutes lost to one red build caused by a flake at this level. You do not
    read the whole scope before concluding it is flaky — but you do start."""
    return MIN_PER_FALSE_RED + FALSE_RED_READ * DEBUG[li]


def false_red_minutes(n: Sequence[int]) -> float:
    """Expected triage minutes per build from tests that red on a clean tree. A
    flaky end-to-end test costs more than a flaky unit test twice over: it reds
    more often, and even a partial read of its scope is a longer read."""
    return sum(-math.expm1(n[i] * math.log1p(-FLAKE[i])) * false_red_cost(i)
               for i in range(4))


def net_minutes(n: Sequence[int], logq: list[list[float]]) -> float:
    """Engineer-minutes per build, net. Catching a defect before merge saves
    MIN_PER_ESCAPE minus the cost of diagnosing it at the level that caught it —
    which is where failure localisation stops being a feeling and becomes money."""
    share, _ = attribution(n, logq)
    caught = P_DEFECT_PER_MERGE * sum(share[i] * (MIN_PER_ESCAPE - DEBUG[i])
                                      for i in range(4))
    return caught - false_red_minutes(n) - wall_seconds(n) / 60.0


def polish(n: Composition, budget: float,
           score: Callable[[Sequence[int]], float]) -> Composition:
    """Local search: spend leftover budget on whichever level gains most, then try
    moving tests between levels. Stops when nothing improves."""
    n = list(n)
    cur = score(n)
    for _ in range(60):
        improved = False
        for _ in range(4):
            best_gain, best_li, best_k = 1e-12, -1, 0
            free = budget - seconds(n)
            for li in range(4):
                k = int(free // COST[li])
                if k <= 0:
                    continue
                cand = list(n)
                cand[li] += k
                g = score(cand) - cur
                if g > best_gain:
                    best_gain, best_li, best_k = g, li, k
            if best_li < 0:
                break
            n[best_li] += best_k
            cur = score(n)
            improved = True
        for a in range(4):
            for b in range(4):
                if a == b or n[a] == 0:
                    continue
                for k in (1, 2, 4, 8, 16, 64, 256):
                    if n[a] < k:
                        break
                    cand = list(n)
                    cand[a] -= k
                    add = int((budget - seconds(cand)) // COST[b])
                    if add <= 0:
                        continue
                    cand[b] += add
                    s = score(cand)
                    if s > cur + 1e-12:
                        n, cur, improved = cand, s, True
                        break
        if not improved:
            break
    return n


def optimise(budget: float, score: Callable[[Sequence[int]], float],
             steps: int = 200) -> Composition:
    """Greedy on marginal value per CI-second, in blocks worth budget/steps, then
    polish. `score` is any objective; pass detection or net minutes."""
    n = [0, 0, 0, 0]
    cur = score(n)
    block = budget / steps
    for _ in range(2 * steps):
        spent = seconds(n)
        best = (1e-15, -1, 0)
        for li in range(4):
            k = max(1, int(round(block / COST[li])))
            if spent + k * COST[li] > budget + 1e-9:
                k = int((budget - spent) // COST[li])
                if k <= 0:
                    continue
            cand = list(n)
            cand[li] += k
            g = (score(cand) - cur) / (k * COST[li])
            if g > best[0]:
                best = (g, li, k)
        if best[1] < 0:
            break
        n[best[1]] += best[2]
        cur = score(n)
    return polish(n, budget, score)


def exhaustive(budget: float,
               score: Callable[[Sequence[int]], float]) -> tuple[Composition, float, int]:
    """Brute force over every feasible composition at this budget, with the unit
    count taking whatever is left. Tractable only at a small budget — which is why
    the greedy exists, and exactly why we check the greedy against it here."""
    best_n, best_s, evals = [0, 0, 0, 0], -1e18, 0
    ne = 0
    while ne * COST[3] <= budget:
        nc = 0
        while ne * COST[3] + nc * COST[2] <= budget:
            nb = 0
            while ne * COST[3] + nc * COST[2] + nb * COST[1] <= budget:
                left = budget - ne * COST[3] - nc * COST[2] - nb * COST[1]
                cand = [int(left // COST[0] + 1e-9), nb, nc, ne]
                s = score(cand)
                evals += 1
                if s > best_s:
                    best_n, best_s = cand, s
                nb += 1
            nc += 1
        ne += 1
    return best_n, best_s, evals


HEADER = ("    composition                 unit  ctrt  intg  e2e    CI time"
          "        caught   green   net/build")


def show(label: str, n: Sequence[int], logq: list[list[float]]) -> None:
    print(f"    {label:<26} {n[0]:6d} {n[1]:5d} {n[2]:5d} {n[3]:4d}"
          f" {seconds(n):8.0f}s {seconds(n)/60:6.1f}m {expected_catch(n, logq):7.1%}"
          f" {build_green(n):7.1%} {net_minutes(n, logq):10.1f}")


def section4(logq: list[list[float]]) -> Composition:
    banner(4, "BUDGET ALLOCATION AS AN OPTIMISATION — THE HEADLINE")
    score: Callable[[Sequence[int]], float] = lambda n: expected_catch(n, logq)

    ver = 60.0
    ex_n, ex_s, evals = exhaustive(ver, score)
    gr_n = optimise(ver, score)
    gr_s = score(gr_n)
    print(f"  verification first. At a {ver:.0f} s budget, exhaustive enumeration over")
    print(f"  {evals} feasible compositions against the greedy + local-search optimiser:")
    print(f"    exhaustive  {str(ex_n):<22} -> {ex_s:.4%}")
    print(f"    greedy      {str(gr_n):<22} -> {gr_s:.4%}")
    print(f"    gap {abs(ex_s-gr_s)*100:.4f} percentage points. The greedy is trusted below.")

    print("\n  the optimal suite at each CI budget, and how its SHAPE moves:")
    print(HEADER)
    budgets = (30.0, 60.0, 120.0, 240.0, 600.0, 1200.0, 2400.0, 4800.0)
    rows: list[tuple[float, Composition]] = []
    for b in budgets:
        n = optimise(b, score)
        rows.append((b, n))
        show(f"budget {b:6.0f}s", n, logq)
    print("\n    budget     share of CI SECONDS            share of TEST COUNT")
    print("               unit  ctrt  intg   e2e      unit  ctrt  intg   e2e")
    for b, n in rows:
        sec = [n[i] * COST[i] / max(1e-9, seconds(n)) for i in range(4)]
        cnt = [n[i] / max(1, sum(n)) for i in range(4)]
        print(f"    {b:7.0f} " + "".join(f"{x:6.1%}" for x in sec)
              + "   " + "".join(f"{x:6.1%}" for x in cnt))
    print("  read the two halves against each other. By test COUNT the optimum is a\n"
          "  pyramid at small budgets and stops being one as the budget grows. By CI\n"
          "  SECONDS — the thing you actually pay — it is never a pyramid at all.")

    print("\n  is the unit count above meaningful, or is the objective flat there?")
    print("  take the 600 s optimum and force the unit count, paying out of contract:")
    print("    forced unit count      resulting composition        caught")
    opt600 = [n for b, n in rows if b == 600.0][0]
    for forced in (0, 500, 1000, 2000, 4000):
        cand = list(opt600)
        cand[0] = forced
        while seconds(cand) > 600.0 and cand[1] > 0:
            cand[1] -= 1
        cand[1] += int((600.0 - seconds(cand)) // COST[1])
        print(f"    {forced:14d}       {str(cand):<26} {score(cand):8.3%}")
    print("  the objective is nearly flat in the unit count once the higher levels are\n"
          "  bought: they have already saturated everything unit tests can reach. That\n"
          "  flatness is a real finding, not a rounding error — and section 6 breaks the\n"
          "  tie with the one thing detection-counting ignores: where the failure points.")

    print("\n  the marginal budget is brutally convex. Read the caught column above:")
    print(f"  the first 30 s buys {score(rows[0][1]):.1%}, and the 4,200 s from 600 s to 4,800 s buys")
    print(f"  {score(rows[-1][1])-score(rows[4][1]):.1%} more. The last points cost orders of magnitude more than")
    print("  the first ones. That convexity, not virtue, is why every suite stops somewhere.")
    return opt600


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# Named shapes versus the optimum at one budget, plus the two suites from The
# Problem at their own budgets. A "shape" is a ratio of TEST COUNTS — which is how
# every version of this argument is stated — so each ratio is scaled to fill the
# same CI budget, and only then compared. Then the two sensitivity sweeps that say
# whether any of this survives contact with a different repo.

NAMED = (
    ("pyramid 70/20/10",  (70, 0, 20, 10)),
    ("pyramid 80/15/5",   (80, 0, 15, 5)),
    ("testing trophy",    (25, 20, 50, 5)),
    ("honeycomb",         (20, 5, 70, 5)),
    ("ice-cream cone",    (10, 10, 20, 60)),
    ("all unit",          (100, 0, 0, 0)),
)


def scale_to_budget(ratio: Sequence[int], budget: float) -> Composition:
    k = budget / sum(ratio[i] * COST[i] for i in range(4))
    n = [int(ratio[i] * k) for i in range(4)]
    while seconds(n) > budget:                       # integer rounding may overshoot
        n[max(range(4), key=lambda i: n[i] * COST[i])] -= 1
    n[0] += int((budget - seconds(n)) // COST[0])    # remainder to the cheapest level
    return n


def section5(g: Graph, scopes, logq: list[list[float]], opt600: Composition) -> None:
    banner(5, "THE TWO TEAMS, THE NAMED SHAPES, AND WHETHER ANY OF IT SURVIVES")
    score: Callable[[Sequence[int]], float] = lambda n: expected_catch(n, logq)
    print("  the suites from The Problem, each at its OWN budget, against the optimum")
    print("  for that same budget:")
    print(HEADER)
    team_a = [4000, 0, 0, 0]
    team_b = [0, 0, 0, 180]
    for label, team in (("Team A: 4,000 unit", team_a), ("Team B: 180 e2e", team_b)):
        show(label, team, logq)
        show("  detection-optimum here", optimise(seconds(team), score), logq)
    print(f"  Team A buys {expected_catch(team_a, logq):.1%} of the defect population for "
          f"{seconds(team_a):.0f} s and cannot buy more")
    print("  at any price — its ceiling is the unit column of the catch matrix. The")
    print(f"  optimum at Team A's identical 40 s buys "
          f"{expected_catch(optimise(seconds(team_a), score), logq):.1%}.")
    print(f"  Team B's clean build comes back green {build_green(team_b):.1%} of the time. That is")
    print("  why nobody on that team reads a red build. Neither team is being stupid.")

    b = 600.0
    print(f"\n  every named shape scaled to the SAME {b:.0f} s budget:")
    print(HEADER)
    scored = []
    for label, ratio in NAMED:
        n = scale_to_budget(ratio, b)
        scored.append((expected_catch(n, logq), label))
        show(label, n, logq)
    show("OPTIMUM (measured)", opt600, logq)
    scored.sort()
    print(f"  best named shape {scored[-1][1]} at {scored[-1][0]:.1%}; worst "
          f"{scored[0][1]} at {scored[0][0]:.1%};")
    print(f"  the measured optimum is {expected_catch(opt600, logq):.1%}. The spread between the best")
    print(f"  and worst named shape at an IDENTICAL budget is {scored[-1][0]-scored[0][0]:.1%} of the defect")
    print("  population — same minutes, same money, same engineers, same code.")

    base_e2e = COST[3]
    print("\n  sensitivity 1 — the shape is a consequence of the COST RATIO, so vary it.")
    print("  e2e cost swept, everything else held, optimum recomputed at 600 s:")
    print("    e2e cost   x unit cost     unit  ctrt  intg  e2e   e2e share s   caught")
    for c in (1.0, 2.0, 4.0, 7.0, 14.0, 28.0, 60.0, 120.0):
        COST[3] = c
        n = optimise(b, score)
        print(f"    {c:8.1f}s {c/COST[0]:12.0f}x {n[0]:8d} {n[1]:5d} {n[2]:5d} {n[3]:4d}"
              f" {n[3]*c/max(1e-9, seconds(n)):13.1%} {expected_catch(n, logq):8.1%}")
    COST[3] = base_e2e
    print("  halve the price of an end-to-end test and the optimiser buys more of them; at\n"
          "  120 s each it buys one. The pyramid is not a value judgement about test types.\n"
          "  It is a shadow cast by a cost ratio, and changing the ratio moves the shadow.")

    print("\n  sensitivity 2 — the model assumes tests are randomly targeted. Real unit")
    print("  tests are aimed at the hard cases; real integration tests follow the happy")
    print("  path. Sweep that bias directly: raise the unit oracle, drop the others.")
    print("    unit/intg/e2e oracle     unit  ctrt  intg  e2e   unit share s   caught")
    base_oracle = list(ORACLE)
    for uo, io, eo in ((0.85, 0.70, 0.55), (0.90, 0.55, 0.42),
                       (0.95, 0.40, 0.30), (0.98, 0.25, 0.20)):
        ORACLE[0], ORACLE[2], ORACLE[3] = uo, io, eo
        lq = make_logq(detection_matrix(g, scopes))
        n = optimise(b, lambda x: expected_catch(x, lq))
        print(f"    {uo:5.2f} /{io:5.2f} /{eo:5.2f} {n[0]:12d} {n[1]:5d} {n[2]:5d} {n[3]:4d}"
              f" {n[0]*COST[0]/max(1e-9, seconds(n)):13.1%} {expected_catch(n, lq):8.1%}")
    ORACLE[:] = base_oracle
    print("  even when unit assertions are near-perfect and the higher levels are half\n"
          "  blind, the unit level never takes a large share of the BUDGET — because its\n"
          "  ceiling is a capability limit, and no oracle strength buys a capability.")


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# Flake and localisation, priced. A test that reds on a clean tree costs triage
# minutes and, worse, trust. A test that catches a defect 200 lines from the cause
# costs debugging minutes. Re-solve the same allocation on engineer-minutes and
# watch the answer move. Lesson 09 develops the trust collapse properly.

def section6(logq: list[list[float]], opt600: Composition) -> None:
    banner(6, "FLAKE AND LOCALISATION, PRICED IN ENGINEER-MINUTES")
    print(f"  one caught defect = {MIN_PER_ESCAPE:.0f} min saved, minus the minutes to diagnose it")
    print(f"  at the level that caught it: " + ", ".join(
        f"{LEVELS[i]} {DEBUG[i]:.1f}" for i in range(4)) + " min.")
    print(f"  one false red = {MIN_PER_FALSE_RED:.0f} min + {FALSE_RED_READ:.0%} of that diagnosis cost "
          f"(you start reading before")
    print(f"  you conclude it is flaky): " + ", ".join(
        f"{LEVELS[i]} {false_red_cost(i):.1f}" for i in range(4)) + " min.")
    print(f"  {P_DEFECT_PER_MERGE:.0%} of merges carry a defect; {CI_WORKERS} CI workers; "
          f"everyone waits on the wall clock.")

    share, escaped = attribution(opt600, logq)
    print(f"\n  where the 600 s detection-optimum actually catches things:")
    print("    level        share of all defects   diagnosis min   contribution/build")
    for li, name in enumerate(LEVELS):
        print(f"    {name:<12} {share[li]:20.1%} {DEBUG[li]:15.1f}"
              f" {P_DEFECT_PER_MERGE*share[li]*(MIN_PER_ESCAPE-DEBUG[li]):18.2f}")
    print(f"    {'escapes':<12} {escaped:20.1%} {'—':>15} "
          f"{-P_DEFECT_PER_MERGE*escaped*MIN_PER_ESCAPE:18.2f}")

    print("\n    net value of ONE more test, at the margin, from the 600 s optimum:")
    print("      level      delta caught   value min   flake cost   CI cost      NET")
    for li, name in enumerate(LEVELS):
        cand = list(opt600)
        cand[li] += 1
        val = net_minutes(cand, logq) - net_minutes(opt600, logq)
        d = expected_catch(cand, logq) - expected_catch(opt600, logq)
        fl = FLAKE[li] * false_red_cost(li)
        ci = COST[li] / CI_WORKERS / 60.0
        print(f"      {name:<10} {d:13.6f} {val+fl+ci:11.4f} {fl:12.4f} {ci:9.4f}"
              f" {val:8.4f}")
    print("    the unit row is the whole point: it adds NO detection — the higher levels\n"
          "    already saturate everything it can reach — and is still the only level with\n"
          "    positive marginal value, because it moves the catch somewhere cheap to read.")
    print("\n    break-even flake rate — above this, one more test of that level is worth")
    print("    less than nothing no matter how many defects it could catch:")
    print("      level      break-even flake   actual flake   headroom")
    for li, name in enumerate(LEVELS):
        cand = list(opt600)
        cand[li] += 1
        gross = (net_minutes(cand, logq) - net_minutes(opt600, logq)
                 + FLAKE[li] * false_red_cost(li))
        fstar = gross / false_red_cost(li)
        mark = "worthless" if fstar <= 0 else f"{fstar/FLAKE[li]:7.2f}x"
        print(f"      {name:<10} {fstar:18.5f} {FLAKE[li]:14.5f}   {mark}")

    print("\n  re-solving the allocation on NET MINUTES rather than raw detection:")
    print(HEADER)
    catch_score: Callable[[Sequence[int]], float] = lambda n: expected_catch(n, logq)
    net_score: Callable[[Sequence[int]], float] = lambda n: net_minutes(n, logq)
    for b in (600.0, 1200.0, 2400.0):
        show(f"{b:.0f}s max detection", optimise(b, catch_score), logq)
        show(f"{b:.0f}s max net value", optimise(b, net_score), logq)
    print(f"  two things change at once. The value-maximising suite buys unit tests back")
    print(f"  by the thousand — not for detection, which they barely move, but to move")
    print(f"  the CATCH to a level that costs {DEBUG[0]:.0f} minutes to diagnose instead of "
          f"{DEBUG[3]:.0f}. And it")
    print("  refuses to spend the budget it was offered: at 1200 s and 2400 s it still")
    print("  builds the same ~400 s suite, because past that point one more test buys")
    print("  more false reds than defects. Detection-maximising and value-maximising")
    print("  suites are not the same suite, and — this is the surprise — not the same")
    print("  LENGTH. The budget is an output of the model, not an input to it.")

    print("\n  so what does end-to-end flake actually cost you? Sweep the per-test e2e")
    print("  flake rate and re-solve at 600 s on net minutes, everything else held:")
    print("    e2e flake   1 red per N runs   unit  ctrt  intg  e2e   CI s   caught   net")
    base_flake = FLAKE[3]
    sweep: list[tuple[float, Composition]] = []
    for f in (0.01200, 0.00600, 0.00300, 0.00150, 0.00050, 0.00010):
        FLAKE[3] = f
        n = optimise(600.0, lambda x: net_minutes(x, logq))
        sweep.append((f, n))
        print(f"    {f:9.5f} {1/max(f, 1e-9):16.0f} {n[0]:7d} {n[1]:5d} {n[2]:5d} {n[3]:4d}"
              f" {seconds(n):6.0f} {expected_catch(n, logq):8.1%} {net_minutes(n, logq):6.1f}")
    hi_f, hi_n = sweep[0]
    lo_f, lo_n = sweep[3]
    FLAKE[3] = lo_f
    lo_net, lo_catch = net_minutes(lo_n, logq), expected_catch(lo_n, logq)
    FLAKE[3] = base_flake
    print("  flake does not BAN the expensive level. It rations it — and it rations the")
    print(f"  whole budget with it: at {hi_f:.1%} per-test flake the optimiser buys {hi_n[3]} e2e tests")
    print(f"  and refuses to spend more than {seconds(hi_n):.0f} of its {600:.0f} s. Take the same tests to")
    print(f"  {lo_f:.2%} — one flaky red in {1/lo_f:.0f} — and it buys {lo_n[3]}, spends the whole "
          f"{seconds(lo_n):.0f} s, and")
    print(f"  gains {lo_catch-expected_catch(hi_n, logq):.1%} of detection and "
          f"{lo_net-net_minutes(hi_n, logq):.1f} minutes a build. The flake work is not")
    print("  hygiene you do after the suite: it is what makes the suite affordable.")

    print("\n  and with no budget imposed at all — let the economics choose the budget:")
    print(HEADER)
    free = optimise(9000.0, net_score, steps=300)
    show("unconstrained optimum", free, logq)
    w = wall_seconds(free)
    print(f"  wall time on {CI_WORKERS} workers: {w:.0f} s = {w/60:.1f} min "
          f"({'inside' if w <= FEEDBACK_LIMIT_S else 'OUTSIDE'} the "
          f"{FEEDBACK_LIMIT_S/60:.0f}-minute feedback rule — Humble & Farley, 2010).")
    print("  nobody needs to legislate a suite budget. Price the terms and one falls out.")


# ══ 7 ═══════════════════════════════════════════════════════════════════════════
# The ice-cream cone, simulated. Nobody chooses an inverted suite. It accretes, one
# reasonable decision at a time: a defect reaches production, there is a
# postmortem, the action item is "add an end-to-end test so this cannot happen
# again", and that action item is approved every single time.

SPRINTS = 200
CHANGES_PER_SPRINT = 6
START = [400, 4, 20, 2]
STEADY_UNIT = 12
STEADY_INTEGRATION = 1


def accrete(policy: str, logq: list[list[float]],
            stream: list[list[tuple[int, float]]]) -> tuple[Composition, int, float]:
    n = list(START)
    escapes = 0
    minutes = 0.0
    for sprint in range(SPRINTS):
        n[0] += STEADY_UNIT
        n[2] += STEADY_INTEGRATION
        minutes += BUILDS_PER_SPRINT * (false_red_minutes(n) + wall_seconds(n) / 60.0)
        for ci, roll in stream[sprint]:
            caught = -math.expm1(sum(n[li] * logq[li][ci] for li in range(4)))
            if roll < caught:
                continue
            escapes += 1
            minutes += MIN_PER_ESCAPE
            if policy == "e2e":
                n[3] += 1
            else:
                reachable = [li for li in range(4) if logq[li][ci] < 0.0]
                li = min(reachable, key=lambda i: COST[i])
                n[li] += 1 if li == 3 else 4
    return n, escapes, minutes


def section7(logq: list[list[float]]) -> None:
    banner(7, "THE ICE-CREAM CONE IS NOT A CHOICE — IT ACCRETES")
    rng = random.Random(SEED + 17)
    stream: list[list[tuple[int, float]]] = []
    for _ in range(SPRINTS):
        sprint: list[tuple[int, float]] = []
        for _ in range(CHANGES_PER_SPRINT):
            if rng.random() < P_DEFECT_PER_MERGE:
                r = rng.random()
                acc = 0.0
                ci = NC - 1
                for k, w in enumerate(CLASS_W):
                    acc += w
                    if r <= acc:
                        ci = k
                        break
                sprint.append((ci, rng.random()))
        stream.append(sprint)
    planted = sum(len(s) for s in stream)
    print(f"  {SPRINTS} sprints x {CHANGES_PER_SPRINT} changes at a "
          f"{P_DEFECT_PER_MERGE:.0%} defect rate = {planted} defects.")
    print(f"  both policies start from {START}, both add {STEADY_UNIT} unit +"
          f" {STEADY_INTEGRATION} integration test per")
    print("  sprint for new features, and both see the IDENTICAL defect stream. The")
    print("  only difference is the action item after a defect reaches production.")
    print()
    print(HEADER)
    show("start of sprint 1", list(START), logq)
    results = {}
    for pol, label in (("e2e", "policy A, 200 sprints"),
                       ("cheapest", "policy B, 200 sprints")):
        n, esc, mins = accrete(pol, logq, stream)
        results[pol] = (n, esc, mins)
        show(label, n, logq)
    print()
    print("    policy                     escapes   engineer-minutes   e2e share of CI s")
    for pol, label in (("A: always an e2e test", "e2e"),
                       ("B: cheapest able level", "cheapest")):
        n, esc, mins = results[label]
        print(f"    {pol:<27} {esc:5d} {mins:18.0f} {n[3]*COST[3]/seconds(n):18.1%}")
    na, ea, ma = results["e2e"]
    nb, eb, mb = results["cheapest"]
    print(f"    A holds {sum(na)} tests ({na[0]/sum(na):.0%} unit by count); B holds {sum(nb)} "
          f"({nb[0]/sum(nb):.0%} unit); A costs {seconds(na)/seconds(nb)-1:.0%} more CI than B.")
    print(f"  policy A is what every postmortem writes, and it is not irrational: each")
    print(f"  individual end-to-end test genuinely does raise detection. {SPRINTS} sprints later")
    print(f"  it holds {na[3]} end-to-end tests — {na[3]/sum(na):.1%} of the test COUNT and "
          f"{na[3]*COST[3]/seconds(na):.0%} of the CI")
    print(f"  SECONDS. That inversion is the ice-cream cone, and it is only visible in")
    print(f"  the column nobody plots. The build goes green {build_green(na):.1%} of the time on a")
    print(f"  clean tree, so the suite has stopped answering the question it exists for.")
    print(f"  policy B — same defects, same sprints, one different sentence in the")
    print(f"  postmortem template — lands at {seconds(nb)/60:.0f} min instead of {seconds(na)/60:.0f}, "
          f"{build_green(nb):.1%} green instead of")
    print(f"  {build_green(na):.1%}, with {eb} escapes against {ea} — the same detection — and "
          f"{ma-mb:.0f} fewer")
    print(f"  engineer-minutes ({(ma-mb)/60:.0f} hours) over the same period.")
    print("  Nobody chose the cone. Every step of policy A was approved in a meeting.")


def main() -> None:
    g = build_graph()
    sc = scopes_for(g)
    for li in range(4):
        DEBUG[li] = DEBUG_FIXED + DEBUG_PER_LINE * scope_stats(g, sc[li])[0]
    section1(g, sc)
    p = section2(g, sc)
    section3(g, sc, p)
    logq = make_logq(p)
    opt600 = section4(logq)
    section5(g, sc, logq, opt600)
    section6(logq, opt600)
    section7(logq)


if __name__ == "__main__":
    import time as _time

    _t0 = _time.perf_counter()
    main()
    print(f"\n  (total wall time {_time.perf_counter() - _t0:.1f} s)")
