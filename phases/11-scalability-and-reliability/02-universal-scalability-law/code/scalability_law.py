"""Phase 11, Lesson 02 — The Universal Scalability Law (companion to docs/en.md).

Prints the three capacity models side by side, then measures a discrete-event
simulation of N workers sharing one serial section and one all-to-all coordination
round, fits sigma and kappa to the measurements by least squares, and shows what
sharding the serial resource and subsetting the coordination graph do to the peak.

Sources: G. M. Amdahl, "Validity of the single processor approach to achieving
large scale computing capabilities", AFIPS Spring Joint Computer Conf. 1967;
N. J. Gunther, "Guerrilla Capacity Planning", Springer 2007 (the USL).
Standard library only. Seeded with random.Random(7). Exits in well under 30 s.
"""

from __future__ import annotations

import heapq
import math
import random
from collections import deque

# --------------------------------------------------------------------------
# The mechanism's parameters. Time is in milliseconds; a "task" is one request.
#   PAR  the part of a request a worker does entirely on its own
#   SER  the part that must hold the ONE shared serial resource (a lock, a
#        leader, a single primary database). Bursty: 90% short, 10% long.
#   MSG  what one directed coordination exchange between two workers costs
#        every worker that is waiting for the round to settle
# --------------------------------------------------------------------------
PAR = 100.0
SER = 8.0
MSG = 0.15
SEEDS = (7, 17, 27)
SWEEP = (1, 2, 4, 6, 8, 12, 16, 20, 24, 28, 32, 36, 40, 48, 56, 64)
WIDE = (8, 16, 24, 32, 40, 48, 64, 80, 96)


def usl(n: int, sigma: float, kappa: float) -> float:
    """Gunther's Universal Scalability Law. sigma=kappa=0 gives linear scaling."""
    return n / (1.0 + sigma * (n - 1) + kappa * n * (n - 1))


def amdahl(n: int, sigma: float) -> float:
    """Amdahl's Law: the kappa=0 special case. Saturates at 1/sigma, never falls."""
    return n / (1.0 + sigma * (n - 1))


# ==========================================================================
# 1 · THREE MODELS OF WHAT N MACHINES BUY YOU
# ==========================================================================
def section1() -> None:
    print("== 1 · THREE MODELS OF WHAT N MACHINES BUY YOU ==")
    sigma, kappa = 0.05, 0.001
    n_star = math.sqrt((1 - sigma) / kappa)
    print(f"  sigma = {sigma}  (5% of the work is serialized)")
    print(f"  kappa = {kappa}  (every PAIR of nodes costs a little coordination)")
    print(f"  Amdahl ceiling 1/sigma = {1/sigma:.0f}x     "
          f"USL peak N* = sqrt((1-sigma)/kappa) = {n_star:.1f}")
    print()
    print("       N     linear      Amdahl         USL    USL/linear   marginal gain")
    prev = None
    for n in (1, 2, 4, 8, 12, 16, 20, 24, 28, 31, 32, 40, 48, 56, 64):
        a, u = amdahl(n, sigma), usl(n, sigma, kappa)
        gain = "" if prev is None else f"{(u - prev[1]) / (n - prev[0]):+8.3f}/node"
        print(f"    {n:4d}   {n:8.2f}    {a:8.2f}    {u:8.2f}      {u/n:7.1%}   {gain:>16}")
        prev = (n, u)
    print()
    print(f"  at N=100 Amdahl says {amdahl(100, sigma):.2f}x and the USL says "
          f"{usl(100, sigma, kappa):.2f}x.")
    print(f"  the USL peaks at N={n_star:.1f} with {usl(31, sigma, kappa):.2f}x, then goes DOWN:")
    print(f"    N=31 -> {usl(31, sigma, kappa):.2f}x    N=62 -> {usl(62, sigma, kappa):.2f}x "
          f"({(usl(62, sigma, kappa)/usl(31, sigma, kappa) - 1):+.1%} for 2x the machines)")
    print("  the marginal-gain column is the one to read: it goes negative at N=31.")
    print()


# ==========================================================================
# 2 · A SYSTEM WHOSE CURVE NOBODY CHOSE
# ==========================================================================
def simulate(n: int, *, par: float = PAR, ser: float = SER, msg: float = MSG,
             fanout: int | None = None, shards: int = 1, seed: int = 7,
             warmup: int = 1200, measure: int = 16000) -> tuple[float, float]:
    """Discrete-event simulation of n workers. Returns (tasks/sec, serial busy fraction).

    Each worker loops forever over three phases:
      1. PAR ms of work it can do alone (exponential, mean `par`)
      2. the serial section: it must hold one of `shards` shared resources,
         FIFO, bursty hold times.  Nothing here is a formula -- the wait
         emerges from other workers actually being in the queue.
      3. the coordination round: it must wait for the medium to carry every
         directed exchange between the workers it coordinates with.  With
         all-to-all coordination that is n*(n-1) exchanges -- twice the
         n*(n-1)/2 pairs, once in each direction.  With subsetting each
         worker has a fixed `fanout`, so the round is n*fanout: LINEAR in n.
    """
    rng = random.Random(seed + n * 131)
    peers = (n - 1) if fanout is None else min(fanout, n - 1)
    round_ms = msg * n * peers          # the whole coordination round, in ms
    busy = [False] * shards
    waiting: list[deque[int]] = [deque() for _ in range(shards)]
    shard_of: dict[int, int] = {}
    events: list[tuple[float, int, int, int]] = []
    seq = done = 0
    t = t0 = 0.0
    serial_busy = 0.0

    def hold() -> float:
        # bursty lock hold times: 90% short, 10% long, same mean, CV^2 ~ 5
        return rng.expovariate(1.0 / (ser * 0.5)) if rng.random() < 0.9 \
            else rng.expovariate(1.0 / (ser * 5.5))

    def push(when: float, kind: int, w: int) -> None:
        nonlocal seq
        seq += 1
        heapq.heappush(events, (when, seq, kind, w))

    for w in range(n):
        push(rng.expovariate(1.0 / par), 0, w)

    while done < warmup + measure:
        t, _, kind, w = heapq.heappop(events)
        if kind == 0:                                   # done working alone
            s = rng.randrange(shards)
            shard_of[w] = s
            if busy[s]:
                waiting[s].append(w)                    # contention, measured
            else:
                busy[s] = True
                d = hold()
                serial_busy += d if done >= warmup else 0.0
                push(t + d, 1, w)
        elif kind == 1:                                 # released the serial resource
            s = shard_of[w]
            if waiting[s]:
                nxt = waiting[s].popleft()
                shard_of[nxt] = s
                d = hold()
                serial_busy += d if done >= warmup else 0.0
                push(t + d, 1, nxt)
            else:
                busy[s] = False
            push(t + round_ms, 2, w)                    # wait out the round
        else:                                           # task complete
            done += 1
            if done == warmup:
                t0 = t
                serial_busy = 0.0
            push(t + rng.expovariate(1.0 / par), 0, w)

    span = t - t0
    return measure / span * 1000.0, serial_busy / (span * shards)


def sweep(ns, **kw) -> dict[int, float]:
    """Average each concurrency level over three seeds, as a load test should."""
    return sweep2(ns, **kw)[0]


def sweep2(ns, **kw) -> tuple[dict[int, float], dict[int, float]]:
    """As sweep(), but also returns the serial resource's busy fraction."""
    tp: dict[int, float] = {}
    busy: dict[int, float] = {}
    for n in ns:
        runs = [simulate(n, seed=s, **kw) for s in SEEDS]
        tp[n] = sum(r[0] for r in runs) / len(runs)
        busy[n] = sum(r[1] for r in runs) / len(runs)
    return tp, busy


def section2() -> dict[int, float]:
    print("== 2 · A SYSTEM WHOSE CURVE NOBODY CHOSE ==")
    print(f"  N workers. Each request = {PAR:.0f} ms alone + {SER:.0f} ms holding ONE shared")
    print(f"  serial resource (bursty, CV^2 ~ 5) + a coordination round in which the")
    print(f"  medium must carry every directed exchange at {MSG} ms each.")
    print("  Nothing below is computed from the USL. It is what the simulation did.")
    print()
    meas, busy = sweep2(SWEEP)
    x1 = meas[1]
    print("       N   throughput    C(N)=X(N)/X(1)   per-node    serial busy   pair exchanges")
    for n in SWEEP:
        print(f"    {n:4d}   {meas[n]:7.1f}/s        {meas[n]/x1:7.2f}x   "
              f"{meas[n]/n:7.2f}/s        {busy[n]:6.1%}   {n*(n-1):12,d}")
    peak = max(meas, key=lambda n: meas[n])
    print()
    print(f"  one worker does {x1:.1f} req/s with the serial resource {busy[1]:.1%} busy.")
    print(f"  measured peak: N={peak} at {meas[peak]:.1f} req/s ({meas[peak]/x1:.2f}x).")
    print(f"  N=64 does {meas[64]:.1f} req/s -- {(meas[64]/meas[peak] - 1):+.1%} against N={peak},")
    print(f"  with per-node throughput down from {meas[peak]/peak:.2f}/s to {meas[64]/64:.2f}/s")
    print(f"  and the serial resource {busy[64]:.1%} busy against {busy[peak]:.1%} at the peak --")
    print("  LESS contended, and slower. Every worker is healthy. Nothing errored.")
    print()
    return meas


# ==========================================================================
# 3 · FITTING SIGMA AND KAPPA TO THE MEASUREMENTS
# ==========================================================================
def fit(meas: dict[int, float], passes: int = 4, steps: int = 120) -> tuple[float, float, float]:
    """Least squares over a grid, refined four times. Returns (sigma, kappa, sse).

    Deliberately a grid and not a solver: two parameters, a bounded and
    well-behaved surface, and you can see exactly what it searched.
    """
    x1 = meas[1]
    s_lo, s_hi, k_lo, k_hi = 0.0, 0.30, 0.0, 0.010
    best = (1e18, 0.0, 0.0)
    for _ in range(passes):
        ds, dk = (s_hi - s_lo) / steps, (k_hi - k_lo) / steps
        best = (1e18, 0.0, 0.0)
        for i in range(steps + 1):
            s = s_lo + i * ds
            for j in range(steps + 1):
                k = k_lo + j * dk
                err = 0.0
                for n, x in meas.items():
                    err += (x1 * usl(n, s, k) - x) ** 2
                if err < best[0]:
                    best = (err, s, k)
        _, s, k = best
        s_lo, s_hi = max(0.0, s - 2 * ds), s + 2 * ds
        k_lo, k_hi = max(0.0, k - 2 * dk), k + 2 * dk
    return best[1], best[2], best[0]


def fit_amdahl(meas: dict[int, float]) -> float:
    """The same least squares with kappa pinned to zero -- Amdahl's Law alone."""
    x1 = meas[1]
    best = (1e18, 0.0)
    for i in range(6001):
        s = i * 0.00005
        err = sum((x1 * amdahl(n, s) - x) ** 2 for n, x in meas.items())
        if err < best[0]:
            best = (err, s)
    return best[1]


def rel_err(meas: dict[int, float], x1: float, s: float, k: float) -> float:
    return max(abs(x1 * usl(n, s, k) - x) / x for n, x in meas.items())


def section3(meas: dict[int, float]) -> tuple[float, float]:
    print("== 3 · FITTING SIGMA AND KAPPA TO THE MEASUREMENTS ==")
    x1 = meas[1]
    sigma, kappa, _ = fit(meas)
    n_star = math.sqrt((1 - sigma) / kappa)
    peak = max(meas, key=lambda n: meas[n])

    # what the mechanism actually charges, in USL's own units
    kappa_mech = MSG / (PAR + SER)      # the round is msg*N*(N-1) ms of task time
    serial_frac = SER / (PAR + SER)     # Amdahl's upper bound on sigma
    ctrl = sweep(SWEEP, msg=0.0)        # same system, coordination switched OFF
    sigma_ctrl = fit_amdahl(ctrl)
    ctrl_peak = max(ctrl, key=lambda n: ctrl[n])

    print("  16 concurrency levels x 3 seeds, N = 1..64, both sides of the knee.")
    print()
    print("              fitted    from the mechanism")
    print(f"    sigma   {sigma:9.4f}  {serial_frac:10.4f}    serial ms / total ms -- an UPPER bound")
    print(f"    kappa   {kappa:9.6f}  {kappa_mech:10.6f}    one exchange / total ms -- exact")
    print(f"    kappa recovered to within {abs(kappa - kappa_mech)/kappa_mech:.1%} "
          f"of what the mechanism charges.")
    print()
    print("  control: the SAME system with the coordination round switched off (msg=0).")
    print(f"    it rises to {max(ctrl.values())/ctrl[1]:.1f}x (peak N={ctrl_peak}) and NEVER turns down.")
    print(f"    the serial fraction {serial_frac:.4f} predicts a ceiling of 1/sigma = "
          f"{1/serial_frac:.1f}x; measured {max(ctrl.values())/ctrl[1]:.1f}x.")
    print(f"    an Amdahl-only fit (kappa pinned to 0) gives sigma = {sigma_ctrl:.4f}.")
    print("    so: the number you can read off the code gives you the CEILING. It does")
    print("    not give you the curve, and nothing about it gives you a peak.")
    print()
    print("       N   measured    USL fit    error       linear      Amdahl-only")
    for n in SWEEP:
        pred = x1 * usl(n, sigma, kappa)
        print(f"    {n:4d}  {meas[n]:8.1f}/s {pred:8.1f}/s  {(pred-meas[n])/meas[n]:+6.1%}   "
              f"{x1*n:8.1f}/s   {x1*amdahl(n, sigma):8.1f}/s")
    print()
    print(f"  worst point off by {rel_err(meas, x1, sigma, kappa):.1%}.")
    print(f"  predicted peak N* = sqrt((1-{sigma:.4f})/{kappa:.6f}) = {n_star:.1f}")
    print(f"  measured peak     = N={peak}   -> the model found the peak to within "
          f"{abs(n_star-peak)/peak:.0%}.")
    print(f"  Amdahl alone would predict a ceiling of 1/sigma = {1/sigma:.0f}x and tell you")
    print(f"  to keep buying. The system actually peaks at {meas[peak]/x1:.2f}x.")
    print()
    print("  the same fit, using ONLY the points below the knee (N <= 16):")
    under = {n: meas[n] for n in SWEEP if n <= 16}
    s2, k2, _ = fit(under)
    star2 = math.sqrt((1 - s2) / k2) if k2 > 0 else float("inf")
    print(f"    sigma = {s2:.4f}   kappa = {k2:.6f}   N* = {star2:.0f}")
    print(f"    it predicts {x1*usl(64, s2, k2):.1f} req/s at N=64; the truth is {meas[64]:.1f} "
          f"-- off by {abs(x1*usl(64, s2, k2) - meas[64])/meas[64]:.0%}.")
    print("    seven points, all on the rising side, and every one of them fits. A fit")
    print("    that never sampled past the knee cannot tell you where the knee is.")
    print()
    return sigma, kappa


# ==========================================================================
# 4 · RETROGRADE: THE FIX IS TO REMOVE MACHINES
# ==========================================================================
def section4(meas: dict[int, float], sigma: float, kappa: float) -> None:
    print("== 4 · RETROGRADE: THE FIX IS TO REMOVE MACHINES ==")
    x1 = meas[1]
    peak = max(meas, key=lambda n: meas[n])
    print(f"  you are running N={peak} and you need more throughput. You double the fleet.")
    print()
    print("       N   throughput   vs N=%-2d   per-node   $/req (relative)   verdict" % peak)
    base = meas[peak]
    for n in (peak, int(peak * 1.5), peak * 2):
        if n not in meas:
            continue
        cost = (n / meas[n]) / (peak / base)
        verdict = "the peak" if n == peak else ("worse" if meas[n] < base else "better")
        print(f"    {n:4d}   {meas[n]:7.1f}/s   {(meas[n]/base - 1):+6.1%}   "
              f"{meas[n]/n:6.2f}/s          {cost:6.2f}x   {verdict}")
    print()
    twice = peak * 2
    print(f"  {twice} machines cost 2x and deliver {(meas[twice]/base - 1):+.1%}. Per request you are")
    print(f"  paying {((twice/meas[twice])/(peak/base)):.2f}x what you paid at N={peak}.")
    print()
    print("  now the incident-response version -- you are at N=%d and throughput is falling:" % twice)
    print("      action              N       throughput    change vs now")
    print(f"      (nothing)         {twice:3d}      {meas[twice]:7.1f}/s              --")
    for n in (48, 40, 32):
        if n in meas and n <= twice:
            print(f"      scale in to {n:2d}    {n:3d}      {meas[n]:7.1f}/s          "
                  f"{(meas[n]/meas[twice] - 1):+6.1%}")
    print()
    print(f"  removing {twice - peak} machines recovered {(base/meas[twice] - 1):+.1%} of throughput and cut the")
    print("  bill in half. There is no dashboard on which that is the obvious move.")
    print()


# ==========================================================================
# 5 · ATTACKING EACH TERM
# ==========================================================================
def section5(meas: dict[int, float]) -> None:
    print("== 5 · ATTACKING EACH TERM ==")
    print("  three changes to the SAME system, measured the same way:")
    print("    shard   : two independent serial resources instead of one -> sigma / 2")
    print("    subset  : each worker coordinates with 8 peers, not N-1  -> round is LINEAR in N")
    print("    both    : shard the serial resource AND subset the coordination graph")
    print()
    base = sweep(WIDE)
    shard = sweep(WIDE, shards=2)
    subset = sweep(WIDE, fanout=8)
    both = sweep(WIDE, shards=2, fanout=8)
    x1 = meas[1]

    print("       N     baseline        shard         subset          both")
    for n in WIDE:
        print(f"    {n:4d}   {base[n]:7.1f}/s    {shard[n]:7.1f}/s    "
              f"{subset[n]:7.1f}/s    {both[n]:7.1f}/s")
    print()
    print("    config       sigma      kappa        N*     peak N   peak req/s   vs baseline")
    rows = (("baseline", base), ("shard", shard), ("subset", subset), ("both", both))
    peak_base = None
    for name, data in rows:
        d = dict(data)
        d[1] = x1
        s, k, _ = fit(d)
        star = math.sqrt((1 - s) / k) if k > 1e-9 else float("inf")
        pk = max(data, key=lambda n: data[n])
        if peak_base is None:
            peak_base = data[pk]
        star_s = f"{star:6.0f}" if star < 1e5 else "  none"
        print(f"    {name:10s}  {s:8.4f}  {k:9.6f}  {star_s}     {pk:5d}   {data[pk]:8.1f}/s"
              f"      {(data[pk]/peak_base - 1):+7.1%}")
    print()
    s_b, k_b, _ = fit({**dict(base), 1: x1})
    s_s, k_s, _ = fit({**dict(subset), 1: x1})
    s_sh, _, _ = fit({**dict(shard), 1: x1})
    print(f"  sharding the serial resource cut sigma {s_b:.4f} -> {s_sh:.4f} and lifted peak")
    print(f"    throughput {(shard[max(shard, key=lambda n: shard[n])]/peak_base - 1):+.1%} "
          f"-- but the peak is still at N=32. Sharding raised the")
    print("    ceiling; it did not move the cliff, because the cliff is kappa's.")
    print(f"  subsetting cut kappa {k_b:.6f} -> {k_s:.6f} "
          f"({(1 - k_s/k_b):.0%}), which is the whole game:")
    print(f"    at N=96 the baseline does {base[96]:.1f} req/s and the subset does "
          f"{subset[96]:.1f} req/s ({subset[96]/base[96]:.2f}x).")
    print(f"    coordination round at N=96: {96*95:,} exchanges all-to-all vs "
          f"{96*8:,} with a fanout of 8 ({96*95/(96*8):.1f}x less).")
    print(f"    note the subset row's sigma went UP ({s_b:.4f} -> {s_s:.4f}). Subsetting did not")
    print("    delete the coordination cost, it made it LINEAR in N -- and a cost linear in")
    print("    N is exactly what the sigma term is. A ceiling you can live with, not a cliff.")
    print("  sigma caps you. kappa kills you. Attack them in that order of severity,")
    print("  not in the order they are easy.")
    print()


def main() -> None:
    section1()
    m = section2()
    sigma, kappa = section3(m)
    section4(m, sigma, kappa)
    section5(m)


if __name__ == "__main__":
    main()
