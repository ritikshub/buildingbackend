#!/usr/bin/env python3
"""Phase 12 - Lesson 09: Flaky Tests - the trust arithmetic.

Companion program for phases/12-testing-and-quality/09-flaky-tests/docs/en.md.
Ten numbered sections, one per "### " sub-heading of that lesson's The Concept.
Canonical source: Zeller, A. & Hildebrandt, R., "Simplifying and Isolating
Failure-Inducing Input", IEEE TSE 28(2):183-200, 2002 (the ddmin algorithm,
section 8). Standard library only, seeded (SEED = 12), self-terminating, no
network, no files written. Runs in roughly 3 seconds.
"""

from __future__ import annotations

import math
import random
from typing import Callable, Sequence

SEED = 12

# The house scenario, used by every section so the numbers compose.
SUITE = 3000            # tests in the gating suite
FLAKE = 0.002           # per-test, per-run flake probability (0.2%)
BUILDS_PER_DAY = 6      # merges to main that trigger the gating suite
SUITE_MINUTES = 12.0    # wall-clock minutes for one full suite run


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def green(f: float, n: int) -> float:
    """P(a clean commit produces a green build) = (1 - f)^n."""
    return (1.0 - f) ** n


def flake_count(rng: random.Random, n: int, f: float) -> int:
    """Exact count of independently flaking tests in a suite of n at rate f.

    Samples geometric gaps between failures rather than n Bernoulli draws, so a
    3,000-test build costs ~7 random numbers instead of 3,000. Same distribution.
    """
    if f <= 0.0:
        return 0
    log1mf = math.log1p(-f)
    i, k = -1, 0
    while True:
        i += int(math.log(1.0 - rng.random()) / log1mf) + 1
        if i >= n:
            return k
        k += 1


def runs_for_confidence(p: float, conf: float) -> int:
    """Re-runs needed to observe at least one failure of a rate-p event."""
    if p <= 0.0:
        return -1
    if p >= 1.0:
        return 1
    return math.ceil(math.log(1.0 - conf) / math.log(1.0 - p))


# =========================================================================== #
# 1 - THE ARITHMETIC
# =========================================================================== #
def section1() -> None:
    banner("1 . THE ARITHMETIC: A PER-TEST RATE IS A PER-BUILD CATASTROPHE")
    rates = (0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01)
    sizes = (100, 300, 1000, 3000, 10000)

    print("  P(a build with NO real bug in it comes back green) = (1 - f)^n\n")
    print("   per-test flake rate f    " + "".join(f"n={n:<7,}" for n in sizes))
    for f in rates:
        one_in = int(round(1.0 / f))
        cells = "".join(f"{green(f, n):>8.2%} " for n in sizes)
        print(f"   {f:>7.2%}  (1 in {one_in:>6,})   {cells}")

    print(f"\n  the row to stare at is f = {FLAKE:.2%} - one flake per test per 500 runs, the")
    print(f"  number a team calls 'basically clean'. At {SUITE:,} tests it delivers a green")
    print(f"  build on {green(FLAKE, SUITE):.2%} of clean commits. The other"
          f" {1 - green(FLAKE, SUITE):.2%} are lies.")

    rng = random.Random(SEED + 1)
    trials = 500_000
    greens = sum(1 for _ in range(trials) if flake_count(rng, SUITE, FLAKE) == 0)
    print(f"\n  simulated {trials:,} clean builds at n={SUITE:,}, f={FLAKE:.1%}:"
          f" {greens / trials:.3%} green")
    print(f"  closed form (1-{FLAKE})^{SUITE} = {green(FLAKE, SUITE):.3%}"
          f"  -> the formula is the reality, not an approximation")

    print("\n  now invert it. what per-test flake rate does a 95% green build require?")
    print("   suite size      max f          i.e. no worse than")
    for n in sizes:
        fmax = 1.0 - 0.95 ** (1.0 / n)
        print(f"   {n:>6,}      {fmax:9.5%}        1 flake in {1 / fmax:>10,.0f} runs")
    fmax3000 = 1.0 - 0.95 ** (1.0 / SUITE)
    red_per_day = BUILDS_PER_DAY * (1 - green(FLAKE, SUITE))
    print(f"\n  at {SUITE:,} tests EVERY test must be reliable to 1-in-{1 / fmax3000:,.0f}"
          f" before the suite is")
    print(f"  95% trustworthy. Nobody measures a test that far out. Meanwhile, at"
          f" {BUILDS_PER_DAY}")
    print(f"  builds/day, {red_per_day:.2f} builds go red every day for no reason at all -"
          f" {red_per_day * 5:.0f} a week.")


# =========================================================================== #
# 2 - THE TRUST COLLAPSE (BAYES)
# =========================================================================== #
BUG_RATE = 0.05         # P(a given commit contains a regression the suite can see)
SUITE_POWER = 0.90      # P(the suite fails | such a regression is present)


def posterior(f: float, n: int) -> tuple[float, float, float, float]:
    """Return (P(red|clean), P(red|buggy), P(buggy|red), P(clean|green))."""
    quiet = green(f, n)                       # P(no flake fires anywhere)
    p_red_clean = 1.0 - quiet
    p_red_buggy = 1.0 - (1.0 - SUITE_POWER) * quiet
    num = BUG_RATE * p_red_buggy
    p_buggy_red = num / (num + (1.0 - BUG_RATE) * p_red_clean)
    p_green = BUG_RATE * (1.0 - p_red_buggy) + (1.0 - BUG_RATE) * quiet
    p_clean_green = (1.0 - BUG_RATE) * quiet / p_green
    return p_red_clean, p_red_buggy, p_buggy_red, p_clean_green


def section2() -> list[tuple[float, float, float]]:
    banner("2 . THE TRUST COLLAPSE: WHAT A RED BUILD ACTUALLY TELLS YOU")
    print(f"  prior: {BUG_RATE:.0%} of commits carry a regression this suite could catch,")
    print(f"  and the suite catches such a regression {SUITE_POWER:.0%} of the time when")
    print("  no flake interferes. Bayes on a red build:\n")
    print("    P(bug | red) = P(bug) . P(red | bug)")
    print("                   ---------------------------------------------")
    print("                   P(bug).P(red|bug) + P(no bug).P(red | no bug)\n")
    print("   flake rate f    P(red|clean)   P(red|bug)   P(bug|red)   evidence"
          "   P(clean|green)")
    print("   (n = 3,000)                                              (bits)")
    out: list[tuple[float, float, float]] = []
    for f in (0.0, 0.00001, 0.0001, 0.0005, 0.001, 0.002):
        prc, prb, pbr, pcg = posterior(f, SUITE)
        bits = math.log2(pbr / BUG_RATE)
        out.append((f, pbr, bits))
        label = "0 (perfect)" if f == 0.0 else f"{f:.3%}"
        print(f"   {label:<14} {prc:11.2%}   {prb:10.2%}   {pbr:10.2%}"
              f"   {bits:7.3f}   {pcg:12.4%}")

    perfect_bits, worst_bits = out[0][2], out[-1][2]
    print(f"\n  a red build in a deterministic suite carries {perfect_bits:.2f} bits: it moves"
          f" you from")
    print(f"  {BUG_RATE:.0%} certain to 100% certain, which is the entire reason the suite"
          f" gates a merge.")
    print(f"  the same red build at f = {FLAKE:.1%} carries {worst_bits:.3f} bits,"
          f" {perfect_bits / worst_bits:,.0f}x less. P(bug|red) is")
    print(f"  {out[-1][1]:.2%} against a prior of {BUG_RATE:.0%}: the build went red and"
          f" you learned NOTHING.")
    print("  That is not a metaphor - it is the measured information content.")
    print(f"\n  and the last column is the same number in every row. P(clean|green) is")
    print(f"  {posterior(FLAKE, SUITE)[3]:.2%} at every flake rate, which is algebra rather"
          f" than coincidence: a")
    print("  flake can turn a green build red, never a red build green. GREEN keeps")
    print(f"  all of its meaning. You just get one {green(FLAKE, SUITE):.2%} of the time.")
    print("  The signal was never destroyed. The delivery channel was.")
    return out


# =========================================================================== #
# 3 - THE ENGINEER-RESPONSE MODEL
# =========================================================================== #
def simulate_response(f: float, builds: int, seed: int) -> dict[str, float]:
    """Engineers learn P(bug|red) from experience and act on the estimate.

    Belief is a Beta(a, b) over 'a red build is real', started optimistic at
    Beta(3, 1). A red is investigated with probability equal to the posterior
    mean; investigating reveals ground truth. Ignoring a real regression ships
    it, and production teaches the same lesson ESCAPE_LAG builds later.
    """
    ESCAPE_LAG = 40
    rng = random.Random(seed)
    a, b = 3.0, 1.0
    pending: list[int] = []
    caught = bugs = 0
    lat_prod: list[int] = []
    p_start = a / (a + b)
    first_below_half = -1
    for t in range(builds):
        while pending and pending[0] <= t:
            pending.pop(0)
            a += 1.0                         # production taught them it was real
        p_inv = a / (a + b)
        if first_below_half < 0 and p_inv < 0.5:
            first_below_half = t
        real = rng.random() < BUG_RATE
        if real:
            bugs += 1
        quiet = rng.random() < green(f, SUITE)          # no flake fired anywhere
        red = (not quiet) or (real and rng.random() < SUITE_POWER)
        if not red:
            continue
        if rng.random() >= p_inv:                       # nobody opens it
            if real:
                pending.append(t + ESCAPE_LAG)
                lat_prod.append(ESCAPE_LAG)
            continue
        if real:
            caught += 1
            a += 1.0
        else:
            b += 1.0                                    # cried wolf again
    return {
        "p_inv_final": a / (a + b),
        "p_inv_start": p_start,
        "half_at": float(first_below_half),
        "bugs": float(bugs),
        "caught": float(caught),
        "escaped": float(bugs - caught),
        "catch_rate": caught / bugs if bugs else 0.0,
    }


def section3() -> list[tuple[float, dict[str, float]]]:
    banner("3 . THE ENGINEER-RESPONSE MODEL: A SUITE THAT TRAINS YOU TO IGNORE IT")
    builds = 8000
    print(f"  {builds:,} builds ({builds / BUILDS_PER_DAY / 30:.0f} months at"
          f" {BUILDS_PER_DAY}/day). Engineers hold a Beta belief over 'a red build")
    print("  is real', start optimistic at 75%, investigate with probability equal to")
    print("  that belief, and update on what they learn. Ignored regressions surface in")
    print("  production 40 builds later, teaching the same lesson far more expensively.\n")
    print("   flake rate    true         P(investigate)    drops below   regressions"
          "   caught   effective")
    print("   (n = 3,000)   P(bug|red)   start     end     50% at build     seen"
          "        in CI   suite power")
    rows: list[tuple[float, dict[str, float]]] = []
    for i, f in enumerate((0.0, 0.0001, 0.0005, 0.002)):
        r = simulate_response(f, builds, SEED + 300 + i)
        rows.append((f, r))
        label = "0 (perfect)" if f == 0.0 else f"{f:.2%}"
        half = "never" if r["half_at"] < 0 else f"{int(r['half_at']):,}"
        truth = posterior(f, SUITE)[2]
        print(f"   {label:<13} {truth:8.1%}    {r['p_inv_start']:5.0%}"
              f"   {r['p_inv_final']:6.1%}   {half:>12}   {int(r['bugs']):9,}"
              f"   {int(r['caught']):6,}   {r['catch_rate']:9.1%}")
    clean, dirty = rows[0][1], rows[-1][1]
    print(f"\n  not one test was edited and not one assertion weakened, and the suite's")
    print(f"  measured power to stop a regression went from {clean['catch_rate']:.1%} to"
          f" {dirty['catch_rate']:.1%} - purely because")
    print(f"  of what the humans learned to do with its output. P(investigate) decayed")
    print(f"  {dirty['p_inv_start']:.0%} -> {dirty['p_inv_final']:.1%}, crossing 50% at"
          f" build {int(dirty['half_at']):,}, about"
          f" {dirty['half_at'] / BUILDS_PER_DAY:.0f} days in: one sprint to")
    print(f"  disable a required check. {int(dirty['escaped']):,} regressions reached"
          f" production instead of {int(clean['escaped']):,}.")
    print(f"\n  note the calibration: engineers settle ABOVE the true P(bug|red)"
          f" ({dirty['p_inv_final']:.1%} vs")
    print(f"  {posterior(FLAKE, SUITE)[2]:.1%}) because production keeps teaching them"
          f" about the ones they")
    print("  ignored. They are not being irrational - they are being correctly Bayesian")
    print("  about a channel that stopped carrying information, and they still end up")
    print("  ignoring four reds in five. A flaky suite is not a slower suite. It is a")
    print("  suite that has been switched off by people who never voted to switch it off.")
    return rows


# =========================================================================== #
# 4 - THE TAXONOMY AND THE FIVE PROBES
# =========================================================================== #
# Reproduction probability of each root cause under each diagnostic probe. These
# are a stated model of each mechanism; what the program MEASURES is how much a
# probe set can actually tell them apart.
PROBES = (
    "A: test alone, same seed",
    "B: whole suite, same order",
    "C: whole suite, shuffled",
    "D: different runner, hours later",
    "E: test alone, 200x in a loop",
)
CAUSES: tuple[tuple[str, tuple[float, ...]], ...] = (
    ("async wait / fixed sleep too short", (0.12, 0.12, 0.12, 0.35, 0.92)),
    ("order dependence: needs a predecessor", (1.00, 0.02, 0.48, 0.02, 1.00)),
    ("test pollution: poisoned by a predecessor", (0.00, 0.90, 0.45, 0.90, 0.00)),
    ("shared mutable global across the suite", (0.00, 0.30, 0.55, 0.30, 0.00)),
    ("resource leak: fds/ports exhausted late", (0.00, 0.65, 0.60, 0.65, 0.02)),
    ("real network dependency", (0.06, 0.06, 0.06, 0.25, 0.55)),
    ("time-of-day / date boundary", (0.01, 0.01, 0.01, 0.50, 0.05)),
    ("unseeded randomness in a fixture", (0.20, 0.20, 0.20, 0.20, 0.98)),
    ("REAL product race (a concurrency bug)", (0.18, 0.18, 0.20, 0.22, 0.95)),
    ("infrastructure noise (CPU-starved runner)", (0.02, 0.03, 0.03, 0.30, 0.10)),
)
EPS = 1e-4
# log P(probe fires) and log P(it does not), precomputed per cause per probe.
_LOG_HIT = tuple(tuple(math.log(min(max(p, EPS), 1.0 - EPS)) for p in probs)
                 for _, probs in CAUSES)
_LOG_MISS = tuple(tuple(math.log(1.0 - min(max(p, EPS), 1.0 - EPS)) for p in probs)
                  for _, probs in CAUSES)


def diagnose(obs: Sequence[int], probes: Sequence[int]) -> int:
    """MAP root cause given an observed probe vector, uniform prior."""
    best, best_ll = 0, -1e18
    for k in range(len(CAUSES)):
        hit, miss = _LOG_HIT[k], _LOG_MISS[k]
        ll = 0.0
        for j in probes:
            ll += hit[j] if obs[j] else miss[j]
        if ll > best_ll:
            best_ll, best = ll, k
    return best


def section4() -> dict[str, float]:
    banner("4 . THE TAXONOMY: FIVE PROBES, AND THE ONE THING THEY CANNOT TELL YOU")
    print("  A flake is a symptom. These five re-runs are the differential diagnosis;")
    print("  each row is one root cause's probability of reproducing under each probe.\n")
    print("   root cause                                    " +
          "".join(f"{p.split(':')[0]:>8}" for p in PROBES))
    for name, probs in CAUSES:
        print(f"   {name:<44}" + "".join(f"{p:>8.0%}" for p in probs))
    print("\n   " + "\n   ".join(PROBES))

    rng = random.Random(SEED + 4)
    trials = 4000
    all_probes = tuple(range(5))
    confusion = [[0] * len(CAUSES) for _ in CAUSES]
    hits_all = 0
    for k, (_, probs) in enumerate(CAUSES):
        for _ in range(trials):
            obs = tuple(1 if rng.random() < p else 0 for p in probs)
            g = diagnose(obs, all_probes)
            confusion[k][g] += 1
            hits_all += (g == k)
    total = trials * len(CAUSES)
    acc_all = hits_all / total

    print(f"\n  simulate {total:,} flakes ({trials:,} per cause), run all five probes,")
    print("  take the maximum-likelihood cause. Which probes are worth their minutes?\n")
    print("   probe set                              accuracy   cost per flake")
    for name, ps in (("all five", all_probes),
                     ("A-D (skip the 200x loop)", (0, 1, 2, 3)),
                     ("A, B, C (no second machine)", (0, 1, 2)),
                     ("A + E (isolate and hammer)", (0, 4)),
                     ("B only (just press re-run)", (1,))):
        rng2 = random.Random(SEED + 40)
        hits = 0
        for k, (_, probs) in enumerate(CAUSES):
            for _ in range(trials):
                obs = tuple(1 if rng2.random() < p else 0 for p in probs)
                hits += (diagnose(obs, ps) == k)
        cost = sum((SUITE_MINUTES if j in (1, 2) else 0.4 if j == 0
                    else SUITE_MINUTES if j == 3 else 1.3) for j in ps)
        print(f"   {name:<38} {hits / total:7.1%}   {cost:9.1f} min")

    print("\n  now the column that matters. Row 9 is a REAL product race - a genuine")
    print("  concurrency bug in the code under test, not a bad test. Where does the")
    print("  five-probe diagnosis actually send it?\n")
    race = 8
    print("   observed 'real product race', diagnosed as:")
    ranked = sorted(range(len(CAUSES)), key=lambda j: (-confusion[race][j], j))
    for j in ranked[:4]:
        if confusion[race][j] == 0:
            continue
        print(f"     {confusion[race][j] / trials:6.1%}  {CAUSES[j][0]}")
    self_rate = confusion[race][race] / trials
    print(f"\n  the five-probe diagnosis named a real product race correctly"
          f" {confusion[race][race]:,} of {trials:,}")
    print(f"  times - {self_rate:.1%}. It never once said 'this is your code'. Every single"
          f" time it")
    print("  said 'this is a bad test', and the answer it preferred was a short sleep.")
    print("\n  that is not a defect in the probes. A race in your product and a sleep 20 ms")
    print("  too short are indistinguishable from outside, because both are exactly 'the")
    print(f"  same input sometimes produces a different answer'. The probes localise the")
    print(f"  MECHANISM well - that is what the {acc_all:.0%} overall accuracy buys. What no"
          f" re-run")
    print("  strategy can tell you is whether the non-determinism lives in the test or in")
    print("  the thing under test. Hold that until section 7: it is the entire reason")
    print("  automatic retries are dangerous rather than merely wasteful.")
    return {"acc_all": acc_all, "race_self": self_rate}


# =========================================================================== #
# 5 - sleep() AS THE UNIVERSAL FLAKE GENERATOR
# =========================================================================== #
def section5() -> None:
    banner("5 . sleep() IS A GUESS, AND IT IS EITHER FLAKY OR SLOW")
    rng = random.Random(SEED + 5)
    pool: list[float] = []
    for _ in range(200_000):
        v = 40.0 * math.exp(0.8 * rng.gauss(0.0, 1.0))       # ms, lognormal body
        if rng.random() < 0.04:
            v += 90.0 / (1.0 - rng.random()) ** (1.0 / 1.7)  # a runner hiccup
        pool.append(v)
    pool.sort()

    def q(x: float) -> float:
        return pool[min(len(pool) - 1, int(x * len(pool)))]

    n_async = 500
    print(f"  an async assertion waits for work whose completion time is measured over")
    print(f"  {len(pool):,} runs: p50 {q(.50):.0f} ms, p90 {q(.90):.0f} ms,"
          f" p99 {q(.99):.0f} ms, p99.9 {q(.999):.0f} ms.")
    print(f"  a fixed sleep(D) is a bet that the work finished by D. {n_async} such tests:\n")
    print("   sleep set at    D (ms)   per-test flake   suite time   P(green build)"
          "   P(green build)")
    print("                                              (500 tests)   500 tests"
          "        3,000 tests")
    for name, qq in (("p50", .50), ("p90", .90), ("p99", .99),
                     ("p99.9", .999), ("p99.99", .9999)):
        d = q(qq)
        f = 1.0 - qq
        secs = n_async * d / 1000.0
        print(f"   {name:<12} {d:8.0f}   {f:14.3%}   {secs:8.0f} s   "
              f"{green(f, n_async):13.3%}   {green(f, SUITE):14.3%}")
    print("\n  there is no good row. Sleeping at the p99 leaves a 1% per-test flake rate,")
    print(f"  which section 1 already priced at {green(0.01, n_async):.4%} green over 500 tests."
          f" Sleeping at the")
    print(f"  p99.99 costs {n_async * q(.9999) / 1000.0:.0f} s of doing nothing per run and"
          f" STILL flakes 1 in 10,000. A fixed")
    print("  sleep encodes a percentile of someone else's scheduler as a constant, and a")
    print("  CI runner is not the machine you measured on. Poll for the condition with a")
    print("  deadline instead of sleeping for a duration - Lesson 11 measures that.")


# =========================================================================== #
# 6 - DETECTION POWER
# =========================================================================== #
def section6() -> list[tuple[int, int, int]]:
    banner("6 . DETECTION POWER: HOW MANY RE-RUNS TO PROVE A TEST IS FLAKY")
    print("  A test fails 1 run in K. You want 95% confidence that R re-runs will show")
    print("  it at least once:  1 - (1 - 1/K)^R >= 0.95,  so  R = ln(0.05) / ln(1 - 1/K).\n")
    print("   flake is    R for 95%   R for 99%   re-run the TEST   re-run the SUITE")
    print("   1 in K                              (0.4 s each)      (12 min each)")
    rows: list[tuple[int, int, int]] = []
    for k in (2, 5, 10, 20, 50, 100, 200, 500, 1000):
        r95 = runs_for_confidence(1.0 / k, 0.95)
        r99 = runs_for_confidence(1.0 / k, 0.99)
        rows.append((k, r95, r99))
        t_test = r95 * 0.4 / 60.0
        t_suite = r95 * SUITE_MINUTES / 60.0
        print(f"   {k:>6,}     {r95:>9,}   {r99:>9,}   {t_test:12.1f} min"
              f"   {t_suite:14.0f} h")
    print("\n  R is almost exactly 3K at 95% and 4.6K at 99%, because ln(0.05) = -3.00 and")
    print("  ln(1 - 1/K) ~ -1/K - a rule of thumb you can do in your head. The two right")
    print("  columns are the operational point: confirming a 1-in-100 flake costs 2")
    print(f"  minutes if you re-run the TEST and {rows[5][1] * SUITE_MINUTES / 60:.0f} HOURS"
          f" of CI if you re-run the suite.")
    print("  Never chase a flake with a full pipeline.")

    print("\n  and the confidence you already have, for free, from normal CI traffic:")
    print("   window        suite runs   detects flakes down to")
    for label, days in (("1 day", 1), ("1 week", 7), ("1 month", 30), ("1 quarter", 91)):
        r = BUILDS_PER_DAY * days
        # largest K with runs_for_confidence(1/K, .95) <= r
        k = 1
        while runs_for_confidence(1.0 / (k + 1), 0.95) <= r:
            k += 1
        print(f"   {label:<12} {r:>10,}   1 in {k:<6,}  at 95% confidence")
    print(f"  at {BUILDS_PER_DAY} builds/day a 1-in-500 flake is invisible for a quarter."
          f" It is not rare;")
    print("  it is under-observed. This is why flake rate must be a recorded metric")
    print("  across every run, not a thing someone noticed on a Tuesday.")
    return rows


# =========================================================================== #
# 7 - RETRIES MAKE A REAL BUG INVISIBLE          <-- the headline experiment
# =========================================================================== #
# 6 genuine intermittent product bugs (real races) and 14 environmental flakes,
# in a 400-test suite. 200 warm-up builds let the team's belief equilibrate on
# environmental noise alone; the 6 races are then merged on the same day and the
# clock runs for 600 more builds (100 days at 6 builds/day).
REAL_BUGS = (0.35, 0.22, 0.14, 0.09, 0.06, 0.03)
ENV_FLAKES = (0.20, 0.15, 0.12, 0.10, 0.09, 0.07, 0.06,
              0.05, 0.04, 0.03, 0.03, 0.02, 0.02, 0.01)
SUITE_400 = 400
WARMUP = 200
HORIZON = 600
TRIAGE_CAP = 3          # failing tests a team will actually open per build
ENV_MATCH = 0.92        # env flake raises an error --only-rerun is configured for
RACE_MATCH = 0.15       # a race that ALSO surfaces as a TimeoutError


def _attempt(rng: random.Random, rate: float, reruns: int, only_rerun: bool,
             match: float) -> tuple[bool, int]:
    """Run one unstable test under a retry policy. Returns (hard_red, extra_runs)."""
    if rng.random() >= rate:
        return False, 0
    allowed = reruns
    if only_rerun and rng.random() >= match:
        allowed = 0                       # error did not match the allowlist
    extra = 0
    for _ in range(allowed):
        extra += 1
        if rng.random() >= rate:
            return False, extra           # passed on re-run: filed as green
    return True, extra


def run_policy(name: str, reruns: int, only_rerun: bool, seed: int) -> dict:
    """One CI policy run against the same 20 unstable tests, warm-up then bugs."""
    rng = random.Random(seed)
    a, b = 3.0, 1.0
    found_at: dict[int, int] = {}
    alive: set[int] = set()
    executions = red_builds = investigations = 0
    hard_real = hard_env = 0
    p_inv_at_merge = 0.0
    for t in range(WARMUP + HORIZON):
        if t == WARMUP:
            alive = set(range(len(REAL_BUGS)))       # the six races are merged
            p_inv_at_merge = a / (a + b)
        p_inv = a / (a + b)
        executions += SUITE_400
        hard: list[tuple[int, bool]] = []
        for idx, rate in enumerate(ENV_FLAKES):
            red, extra = _attempt(rng, rate, reruns, only_rerun, ENV_MATCH)
            executions += extra
            if red:
                hard.append((1000 + idx, False))
                if t >= WARMUP:
                    hard_env += 1
        for idx in sorted(alive):
            red, extra = _attempt(rng, REAL_BUGS[idx], reruns, only_rerun, RACE_MATCH)
            executions += extra
            if red:
                hard.append((idx, True))
                hard_real += 1
        if t >= WARMUP and hard:
            red_builds += 1
        hard.sort()
        opened = 0
        for key, is_real in hard:
            if opened >= TRIAGE_CAP:
                break
            if rng.random() >= p_inv:        # triaged as "probably that flake again"
                continue
            opened += 1
            investigations += 1
            if is_real:
                a += 1.0
                found_at[key] = t - WARMUP
                alive.discard(key)
            else:
                b += 1.0
    return {
        "name": name, "found_at": found_at, "alive": alive,
        "executions": executions / (WARMUP + HORIZON),
        "red_rate": red_builds / HORIZON,
        "p_inv": a / (a + b), "p_inv_merge": p_inv_at_merge,
        "investigations": investigations,
        "hard_real": hard_real, "hard_env": hard_env,
    }


def clean_green_rate(reruns: int, only_rerun: bool, seed: int) -> float:
    """Green rate on a commit with NO real bug - the reason teams add retries."""
    rng = random.Random(seed)
    greens = 0
    for _ in range(20_000):
        ok = True
        for rate in ENV_FLAKES:
            red, _ = _attempt(rng, rate, reruns, only_rerun, ENV_MATCH)
            if red:
                ok = False
        greens += ok
    return greens / 20_000


def section7() -> list[dict]:
    banner("7 . THE EXPERIMENT THAT MATTERS: RETRIES HIDE REAL BUGS")
    print(f"  a {SUITE_400}-test suite with {len(ENV_FLAKES)} environmental flakes"
          f" (bad tests, {min(ENV_FLAKES):.0%}-{max(ENV_FLAKES):.0%}).")
    print(f"  {WARMUP} warm-up builds let the team's belief settle on that noise. Then"
          f" {len(REAL_BUGS)} genuine")
    print(f"  intermittent PRODUCT bugs - real races, manifesting"
          f" {min(REAL_BUGS):.0%}-{max(REAL_BUGS):.0%} of runs - are merged")
    print(f"  on the same day, and the clock runs {HORIZON} builds"
          f" ({HORIZON // BUILDS_PER_DAY} days).")
    print("  Under --reruns R a failure must lose R+1 times in a row to be reported at")
    print("  all; anything that passes on re-run is filed green and nobody sees it.")
    print("  Triage capacity: 3 opened failures per build, gated by section 3's belief.\n")
    print("  visibility arithmetic first, because it is the entire mechanism.")
    print("  a race that manifests p of the time is reported hard-red at rate p^(R+1):\n")
    print("      p      R=0       R=1        R=2      R=2 vs R=0")
    for p in REAL_BUGS:
        print(f"    {p:4.0%}   {p:6.2%}   {p ** 2:6.3%}   {p ** 3:7.4%}"
              f"    {1 / p ** 2:9,.0f}x less visible")

    policies = [
        ("A  no retries", 0, False, SEED + 700),
        ("B  --reruns 2 (blanket)", 2, False, SEED + 701),
        ("C  --reruns 2 --only-rerun", 2, True, SEED + 702),
    ]
    results = []
    print("\n  policy                       green on   builds   test runs   P(invest-"
          "   races    races still")
    print("                               a clean      red     per build   igate) at"
          "    found     hidden at")
    print("                                commit                          the end"
          "     in 100d    day 100")
    for name, reruns, only, seed in policies:
        r = run_policy(name, reruns, only, seed)
        r["clean_green"] = clean_green_rate(reruns, only, seed + 50)
        results.append(r)
        print(f"  {name:<28} {r['clean_green']:7.1%}  {r['red_rate']:7.1%}"
              f"   {r['executions']:9.1f}   {r['p_inv']:8.1%}"
              f"   {len(r['found_at']):6d}   {len(r['alive']):10d}")

    print("\n  per-race detection latency (days from merge to somebody opening it):")
    print("   manifests    A no retries     B --reruns 2     C --only-rerun")
    for idx, rate in enumerate(REAL_BUGS):
        cells = []
        for r in results:
            if idx in r["found_at"]:
                cells.append(f"{r['found_at'][idx] / BUILDS_PER_DAY:.1f} d")
            else:
                cells.append("NEVER")
        print(f"   {rate:8.0%}   {cells[0]:>13}   {cells[1]:>14}   {cells[2]:>15}")

    a_r, b_r, c_r = results
    slow = min(REAL_BUGS)
    c_rate = (1 - RACE_MATCH) * slow + RACE_MATCH * slow ** 3
    print(f"""
  read this in the order the team would. Blanket --reruns 2 bought exactly the
  thing it was added for: a clean commit goes green {b_r['clean_green']:.1%} of the time instead
  of {a_r['clean_green']:.1%}, and the build is red on {b_r['red_rate']:.1%} of runs instead of {a_r['red_rate']:.1%}. It cost
  {b_r['executions'] / a_r['executions'] - 1:.1%} more test executions. Those are the numbers in the PR that adds it
  and they are all true. Note the cost in particular: per-test retries are nearly
  FREE in CI minutes, which is why the case against them cannot be made on money.
  It has to be made on information.

  and here is the information. Blanket retry left {len(b_r['alive'])} of the {len(REAL_BUGS)} real product races
  undiscovered after {HORIZON // BUILDS_PER_DAY} days, against {len(a_r['alive'])} with no retries at all. The suite
  ran those tests every build. They failed. Every failure was filed as a pass.
  The {slow:.0%} race needs {1 / slow ** 3:,.0f} builds to lose three coin flips in a row -
  {1 / slow ** 3 / BUILDS_PER_DAY / 365:,.0f} years at {BUILDS_PER_DAY} builds a day.

  now the counter-intuitive column, and do not skip it: policy B has the HIGHEST
  trust per red build ({b_r['p_inv']:.1%} against {a_r['p_inv']:.1%} for no retries). That is not a mistake.
  Retries suppress noise, so the reds that survive really are more likely to be
  real and the team is right to believe it. Retries do not make engineers stupid.
  They make the channel narrow, and high confidence in a signal you almost never
  receive is worth less than moderate confidence in one that arrives on time.

  --only-rerun is the answer and it is one flag. Retry only failures whose error
  matches an environmental signature - ConnectionError, TimeoutError, the
  container-not-ready message - and let AssertionError through untouched:
    clean-commit green {c_r['clean_green']:.1%} (against {b_r['clean_green']:.1%} blanket, {a_r['clean_green']:.1%} bare)
    {len(c_r['found_at'])}/{len(REAL_BUGS)} races found, worst latency {max(c_r['found_at'].values()) / BUILDS_PER_DAY:.1f} days
    P(investigate) {c_r['p_inv']:.1%}, against {a_r['p_inv']:.1%} bare
  the residual is honest and measured: {RACE_MATCH:.0%} of races surface as a timeout and get
  retried anyway, so C masks something too. Price it. For the hardest race ({slow:.0%}),
  C reports a hard red on {c_rate:.2%} of builds against blanket retry's {slow ** 3:.4%} -
  {c_rate / slow ** 3:,.0f}x more visible, for {(1 - c_r['clean_green']) / (1 - b_r['clean_green']):.0f}x more red builds on a clean commit.
  That is the trade, and it is not close.""")
    return results


# =========================================================================== #
# 8 - DELTA DEBUGGING A FAILING TEST SET
# =========================================================================== #
def ddmin(items: list[int], oracle: Callable[[list[int]], bool]) -> tuple[list[int], int]:
    """Zeller & Hildebrandt's ddmin. Returns (1-minimal set, oracle calls)."""
    calls = 0

    def fails(sub: list[int]) -> bool:
        nonlocal calls
        calls += 1
        return oracle(sub)

    c = list(items)
    n = 2
    while len(c) >= 2:
        size = len(c) / n
        chunks = [c[int(i * size):int((i + 1) * size)] for i in range(n)]
        reduced = False
        for ch in chunks:                       # reduce to a subset
            if ch and fails(ch):
                c, n, reduced = ch, 2, True
                break
        if not reduced:
            for ch in chunks:                   # reduce to a complement
                drop = set(ch)
                comp = [x for x in c if x not in drop]
                if comp and fails(comp):
                    c, n, reduced = comp, max(n - 1, 2), True
                    break
        if not reduced:
            if n >= len(c):
                break
            n = min(2 * n, len(c))
    return c, calls


def section8() -> dict[str, float]:
    banner("8 . DELTA DEBUGGING: MINIMISING A FAILING TEST *SET*, NOT A TEST")
    print("  A 200-test job fails only when three particular tests all run in it: one")
    print("  seeds a module global, one mutates it, one asserts on it. No single test is")
    print("  the culprit and none fails alone. 2^200 subsets, one oracle call per CI run.")
    print("  Zeller & Hildebrandt's ddmin (IEEE TSE 28(2):183-200, 2002) finds the")
    print("  minimal failing set in a number of calls you can actually afford.\n")

    N = 200
    rng = random.Random(SEED + 8)

    # (a) can plain bisection even start?
    bis_trials = 40_000
    stuck = 0
    for _ in range(bis_trials):
        cause = set(rng.sample(range(N), 3))
        lo = set(range(N // 2))
        if not (cause <= lo or cause <= set(range(N // 2, N))):
            stuck += 1
    theory = 1.0 - 2.0 * (100 * 99 * 98) / (200 * 199 * 198)

    # (b) ddmin, deterministic oracle
    dd_trials = 600
    dd_calls: list[int] = []
    dd_ok = 0
    for _ in range(dd_trials):
        cause = frozenset(rng.sample(range(N), 3))
        got, calls = ddmin(list(range(N)), lambda sub, c=cause: len(c.intersection(sub)) == 3)
        dd_calls.append(calls)
        dd_ok += (set(got) == set(cause))
    dd_calls.sort()
    med = dd_calls[len(dd_calls) // 2]
    print("   strategy                         succeeds   oracle calls (= CI runs)")
    print(f"   halve, keep the red half        {1 - stuck / bis_trials:8.1%}"
          f"   1, then it is stuck")
    print(f"   remove one test at a time       {1.0:8.1%}   {N:,}")
    print(f"   ddmin                           {dd_ok / dd_trials:8.1%}"
          f"   {med:,} median ({dd_calls[0]:,}-{dd_calls[-1]:,})")
    print(f"\n  bisection fails on the FIRST step {stuck / bis_trials:.1%} of the time"
          f" (theory {theory:.1%}): the three")
    print("  culprits straddle the split, neither half is red, and the search has nowhere")
    print("  to go. That is exactly what ddmin's COMPLEMENT step is for - removing a")
    print("  chunk instead of keeping one is the only move that preserves an interaction")
    print("  the algorithm cannot see.")

    print(f"\n  {med} calls does not look like much of a win over 200, and at small n"
          f" ddmin")
    print("  is genuinely worse. It is not supposed to win there; the win is scaling:\n")
    print("   job size n   one-at-a-time   ddmin (median)   ratio")
    scale: list[tuple[int, int]] = []
    for n in (50, 200, 1000, 5000):
        rng2 = random.Random(SEED + 81)
        calls_list = []
        for _ in range(60):
            cause = frozenset(rng2.sample(range(n), 3))
            _, calls = ddmin(list(range(n)), lambda sub, c=cause: len(c.intersection(sub)) == 3)
            calls_list.append(calls)
        calls_list.sort()
        m = calls_list[len(calls_list) // 2]
        scale.append((n, m))
        print(f"   {n:>10,}   {n:>13,}   {m:>14,}   {n / m:5.1f}x")
    print(f"\n  ddmin is O(|culprits| . log n) in the good case; one-at-a-time is O(n). At")
    print(f"  n = {scale[-1][0]:,} that is {scale[-1][0]:,} CI runs against {scale[-1][1]:,}"
          f" - the difference between 'run it")
    print("  overnight' and 'this is not a plan'.")

    print("\n  now the version you will actually meet: the interaction only fails 40% of")
    print("  the time it is present, so the ORACLE lies - a subset containing all three")
    print("  culprits can come back green, and ddmin throws the culprit away. Section 6")
    print("  already told us how many repeats buy 95% confidence in one oracle call:"),
    q = 0.40
    need = runs_for_confidence(q, 0.95)
    print(f"    P(fail | culprits present) = {q:.0%}  ->  R ="
          f" {need} repeats for 95% confidence\n")
    print("   repeats m   minimal set correct   CI runs per debug   vs m=1")
    base_runs = 0.0
    for m in (1, 2, 3, 6, 9):
        rng2 = random.Random(SEED + 88)
        ok = 0
        total_runs = 0
        t2 = 400
        for _ in range(t2):
            cause = frozenset(rng2.sample(range(N), 3))

            def noisy(sub: list[int], c: frozenset = cause) -> bool:
                if len(c.intersection(sub)) != 3:
                    return False
                return any(rng2.random() < q for _ in range(m))

            got, calls = ddmin(list(range(N)), noisy)
            total_runs += calls * m
            ok += (set(got) == set(cause))
        if m == 1:
            base_runs = total_runs / t2
        print(f"   {m:>9}   {ok / t2:19.1%}   {total_runs / t2:17.0f}"
              f"   {total_runs / t2 / base_runs:5.1f}x")
    print(f"\n  a single run per oracle call gets the answer right almost never, and it")
    print("  fails SILENTLY - you finish holding a 'minimal' set that is simply wrong.")
    print(f"  At m = {need}, exactly the section-6 number, it becomes reliable. The repeat")
    print("  count is not a tuning knob; it is the same confidence calculation as")
    print("  everything else here. Delta debugging a flaky failure is delta debugging")
    print("  with a flaky oracle.")
    return {"dd_median": float(med), "bisect_ok": 1 - stuck / bis_trials}


# =========================================================================== #
# 9 - QUARANTINE DECAY
# =========================================================================== #
def simulate_quarantine(sprints: int, expiry: int | None, fix_budget: float,
                        seed: int) -> dict[str, float]:
    """A quarantine policy run for `sprints` two-week sprints.

    Every test guards one area of behaviour. A quarantined test still runs and
    reports but gates nothing, so a regression in its area ships; a DELETED
    test's area is uncovered permanently. `expiry` is how many sprints a test
    may sit quarantined before it must be fixed or deleted, None being the
    usual policy of "we will get to it".
    """
    rng = random.Random(seed)
    HAZARD = 0.0006          # P(a stable test acquires a flake) per test per sprint
    ADDED = 25               # new tests per sprint
    BUGS = 12                # regressions per sprint, aimed at a random covered area
    gating = SUITE
    quarantined: list[int] = []          # sprint each test entered quarantine
    dead = 0                             # areas whose test was deleted: gone for good
    esc_q = esc_d = seen = 0
    fixed = deleted = 0
    budget = 0.0
    peak = 0
    for s in range(sprints):
        newly = flake_count(rng, gating, HAZARD)
        gating -= newly
        quarantined.extend([s] * newly)
        gating += ADDED
        covered = gating + len(quarantined) + dead
        for _ in range(BUGS):
            seen += 1
            u = rng.random() * covered
            if u < len(quarantined):
                esc_q += 1
            elif u < len(quarantined) + dead:
                esc_d += 1
        budget += fix_budget
        while budget >= 1.0 and quarantined:
            quarantined.pop(0)           # oldest first; a fix returns it to gating
            gating += 1
            fixed += 1
            budget -= 1.0
        if expiry is not None:
            keep = [e for e in quarantined if s - e < expiry]
            gone = len(quarantined) - len(keep)
            deleted += gone
            dead += gone
            quarantined = keep
        peak = max(peak, len(quarantined))
    total = gating + len(quarantined)
    return {
        "quarantined": float(len(quarantined)),
        "gating": float(gating),
        "non_gating_pct": len(quarantined) / total,
        "escape_q": esc_q / seen,
        "escape_d": esc_d / seen,
        "escape_all": (esc_q + esc_d) / seen,
        "fixed": float(fixed),
        "deleted": float(deleted),
        "peak": float(peak),
    }


def section9() -> list[tuple[str, dict[str, float]]]:
    banner("9 . QUARANTINE, AND WHAT AN EXPIRY DATE ACTUALLY BUYS")
    S = 100
    print(f"  {S} sprints ({S * 2 / 52:.0f} years). The suite starts at {SUITE:,} gating"
          f" tests and grows by 25 a")
    print("  sprint. Each stable test has a 0.06% chance per sprint of acquiring a flake -")
    print("  a dependency changes, a timeout tightens, a fixture starts sharing state -")
    print("  which is ~2 new flakes a sprint here. Quarantined tests still run and still")
    print("  report, but gate nothing. Twelve regressions a sprint land somewhere in the")
    print("  suite's coverage; one aimed at a quarantined area ships, and one aimed at a")
    print("  DELETED area ships forever after. All four policies share one seed, so they")
    print("  see the identical sequence of flakes and regressions. Only policy differs.\n")
    print("   policy                             quarantined  deleted   fixed"
          "   coverage lost   regressions")
    print("                                      at sprint 100                "
          "   recov'ble/gone   that shipped")
    rows = [
        ("no expiry, 0.5 fixes/sprint", None, 0.5),
        ("no expiry, 2 fixes/sprint", None, 2.0),
        ("2-sprint expiry, 0.5 fixes/sprint", 2, 0.5),
        ("2-sprint expiry, 2 fixes/sprint", 2, 2.0),
    ]
    out: list[tuple[str, dict[str, float]]] = []
    for label, exp, budget in rows:
        r = simulate_quarantine(S, exp, budget, SEED + 900)
        out.append((label, r))
        print(f"   {label:<35} {int(r['quarantined']):8,}  {int(r['deleted']):7,}"
              f"   {int(r['fixed']):5,}   {int(r['quarantined']):6,} /"
              f" {int(r['deleted']):<6,}   {r['escape_all']:9.2%}")
    lax, lax2, strict_poor, strict_ok = (out[0][1], out[1][1], out[2][1], out[3][1])
    print(f"""
  this did NOT come out the way the slogan says, so read it carefully.

  without an expiry and without a budget the quarantine grew to {int(lax['quarantined']):,} tests -
  {lax['non_gating_pct']:.1%} of the suite silently gating nothing - and {lax['escape_all']:.2%} of regressions shipped.
  Nobody ever chose that. It is a coverage decision made by default, one sprint
  at a time, by people who each thought they were buying a week.

  now compare rows 1 and 3. Same fix budget, differing only in the expiry, and
  the result is exact rather than approximate: {int(lax['quarantined']):,} quarantined against {int(strict_poor['deleted']):,}
  deleted, and BOTH shipped {lax['escape_all']:.2%} of regressions. Identical. An expiry date on
  its own changed nothing about how much coverage the suite had, because a
  quarantined test and a deleted test gate exactly the same amount: none. On the
  escape metric, expiry without budget IS deletion with extra steps.

  what differs is RECOVERABILITY. The lax policy's {int(lax['quarantined']):,} tests are a debt still on
  the balance sheet - fund the budget next quarter and the coverage comes back.
  The expiry policy's {int(strict_poor['deleted']):,} deletions are written off, and no future budget buys
  them back. Run the clock out and watch the write-off compound:""")
    print("\n   horizon      no expiry, 0.5/sprint       2-sprint expiry, 0.5/sprint")
    print("               quarantined  recoverable     deleted    recoverable")
    for horizon in (100, 250, 500):
        l = simulate_quarantine(horizon, None, 0.5, SEED + 950)
        d = simulate_quarantine(horizon, 2, 0.5, SEED + 950)
        print(f"   {horizon:>4} sprints  {int(l['quarantined']):9,}  {'ALL of it':>11}"
              f"   {int(d['deleted']):9,}    {'NONE of it':>11}")
    print(f"""
  rows 2 and 4 both shipped {strict_ok['escape_all']:.2%}, {lax['escape_all'] / max(strict_ok['escape_all'], 1e-9):.0f}x better than rows 1 and 3. What
  separates the good rows from the bad ones is the FIX BUDGET, in every pairing;
  the expiry date changes the escape rate by nothing at all.

  so state the opinion precisely instead of as a slogan. Quarantine needs an
  expiry date AND a funded fix budget, and if you can only have one, take the
  budget - that is the variable the measurement responds to. What the expiry
  date buys is not coverage. It is that the bill arrives on a known day, in a
  diff someone has to approve, instead of never. Put the date IN the marker so
  the test itself fails when it passes:

      @pytest.mark.flaky(reason='ORDERS-4412', expires='2026-09-01')

  and fail the build on an expired marker. A quarantine list that only ever
  grows is not a policy. It is an outbox.""")
    return out


# =========================================================================== #
# 10 - THE ECONOMICS: FIX, QUARANTINE, OR DELETE
# =========================================================================== #
def section10() -> None:
    banner("10 . THE ECONOMICS: FIX IT, DELETE IT, OR LIVE WITH IT")
    BUILDS_WK = BUILDS_PER_DAY * 5
    TRIAGE_MIN = 9.0        # human minutes burnt per red: re-run, wait, resume
    FIX_HOURS = 6.0         # median engineer-hours to root-cause and fix one flake
    ESCAPE_HOURS = 14.0     # engineer-hours when a bug this test would catch ships
    print(f"  {BUILDS_WK} builds/week. One flaky test at rate p turns {BUILDS_WK}p builds"
          f" red, and each red costs")
    print(f"  {TRIAGE_MIN:.0f} engineer-minutes of re-run, wait and lost context. A"
          f" root-cause fix costs")
    print(f"  {FIX_HOURS:.0f} engineer-hours. Deleting the test costs whatever it would"
          f" have caught.\n")
    print("   flake rate p   red builds/wk   min/wk   h/quarter   a fix pays back in")
    for p in (0.002, 0.005, 0.01, 0.02, 0.05, 0.10, 0.20):
        reds = BUILDS_WK * p
        mins = reds * TRIAGE_MIN
        print(f"   {p:>10.1%}   {reds:13.1f}   {mins:6.1f}   {mins * 13 / 60:9.1f}"
              f"   {FIX_HOURS * 60 / mins:11.0f} weeks")
    breakeven = FIX_HOURS * 60.0 / (BUILDS_WK * TRIAGE_MIN * 52.0)
    print(f"\n  the break-even is exact: a fix repays itself inside a year at")
    print(f"    p* = fix_hours . 60 / (builds_per_week . triage_min . 52) ="
          f" {breakeven:.2%}")
    print(f"  above {breakeven:.1%} flake rate, FIX IT and stop discussing it. Below that,")
    print("  one flake genuinely is not worth six hours - which is the honest reason")
    print("  nobody fixes them, and precisely how a population accumulates.")
    print(f"\n  and p* is inversely proportional to build volume: a team shipping"
          f" {BUILDS_WK * 8} builds")
    print(f"  a week has a break-even of {breakeven / 8:.2%}. The busier you get, the less"
          f" flakiness you")
    print("  can afford - and nobody re-derives this when the team grows.")

    agg_failures = BUILDS_WK * SUITE * FLAKE
    print(f"\n  and price the POPULATION, not the test. The house scenario -"
          f" {SUITE:,} tests at")
    print(f"  {FLAKE:.1%} - produces {agg_failures:,.0f} flaky test failures a week."
          f" At {TRIAGE_MIN:.0f} minutes each that is")
    print(f"  {agg_failures * TRIAGE_MIN / 60:,.0f} engineer-hours per week,"
          f" {agg_failures * TRIAGE_MIN / 60 * 52 / 1800:,.1f} full-time engineers,"
          f" burnt on re-running")
    print(f"  a suite that already knew the answer. Every single one is below p*.")

    print(f"\n  the decision is therefore never per-test; it is per-test-VALUE. A test's")
    print(f"  worth is the bugs it catches per year x {ESCAPE_HOURS:.0f} h of escape cost:\n")
    print("   test catches      worth    |   action at p = 0.5%   p = 2%   p = 5%")
    for v in (0.05, 0.25, 1.0, 3.0):
        value = v * ESCAPE_HOURS
        cells = []
        for p in (0.005, 0.02, 0.05):
            cost = BUILDS_WK * p * TRIAGE_MIN * 52 / 60.0      # engineer-hours/year
            if cost >= FIX_HOURS:
                cells.append("FIX")
            elif value < cost:
                cells.append("DELETE")
            else:
                cells.append("KEEP")
        print(f"   {v:>5.2f} bugs/yr   {value:5.1f} h/yr   |"
              f"   {cells[0]:>13}   {cells[1]:>6}   {cells[2]:>6}")
    print(f"""
  the three-way rule the arithmetic actually produces:
   . p >= {breakeven:.1%}: FIX IT. The flake costs more than the fix inside a year,
     whatever the test is worth, and there is nothing left to discuss.
   . p < p* and the test has never caught a real bug: DELETE IT. No measured
     value plus a nonzero flake rate is negative expected value - and section 3
     is why: the cost is not paid by that test, it is paid out of every other
     test's credibility.
   . otherwise: KEEP IT, and if it blocks, quarantine with a FUNDED expiry.

  every branch needs bugs-caught-per-test, which almost nobody records. Record
  it. Per failure: test id, commit, worker, seed, duration, and the one field
  that makes this whole lesson decidable - whether the failure turned out real.""")


def main() -> None:
    print("FLAKY TESTS - the trust arithmetic")
    print(f"seed = {SEED}; house scenario: {SUITE:,} tests, {FLAKE:.1%} per-test flake"
          f" rate, {BUILDS_PER_DAY} builds/day")
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    section7()
    section8()
    section9()
    section10()
    print()


if __name__ == "__main__":
    main()
