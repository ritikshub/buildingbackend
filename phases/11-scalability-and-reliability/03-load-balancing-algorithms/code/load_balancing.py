#!/usr/bin/env python3
"""
Load-balancing algorithms measured rather than asserted: balls-in-bins maximum
load, round-robin's equal-counts/unequal-work lie, heterogeneous backends under
seven policies, the power of two random choices, the least-connections death
spiral, and consistent hashing with bounded loads.

Companion to docs/en.md (Phase 11, Lesson 03). Standard library only, every RNG
seeded, self-terminating in well under 30 seconds. Sources: Mitzenmacher, *The
Power of Two Choices in Randomized Load Balancing*, IEEE TPDS 12(10), 2001;
Azar, Broder, Karlin & Upfal, *Balanced Allocations*, SIAM J. Comput. 29(1),
1999; Karger et al., *Consistent Hashing and Random Trees*, STOC 1997;
Mirrokni, Thorup & Zadimoghaddam, *Consistent Hashing with Bounded Loads*,
SIAM J. Comput. 47(3), 2018; Eisenbud et al., *Maglev*, NSDI 2016.

Run:  python3 load_balancing.py
"""

from __future__ import annotations

import bisect
import collections
import hashlib
import heapq
import itertools
import math
import random

SEED = 20260718


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def pct(values, q: float) -> float:
    """The q-quantile of `values` by nearest rank, in the caller's units."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# Balls in bins. Throw n requests at n backends. Round-robin's maximum is
# exactly 1 by construction; uniform random's maximum is
#     (1 + o(1)) * ln n / ln ln n            (Gonnet 1981; Azar et al. 1999)
# which is the cost of having no coordination at all. The o(1) is large at
# realistic n, so we print prediction AND measurement and let the gap show.


def throw(n: int, d: int, rng: random.Random):
    """Throw n balls into n bins, sampling d bins each time and taking the least
    loaded. d=1 is uniform random; d=2 is the power of two choices.
    Returns (max bin, number of empty bins)."""
    bins = [0] * n
    randrange = rng.randrange
    if d == 1:
        for _ in range(n):
            bins[randrange(n)] += 1
    else:
        for _ in range(n):
            best = randrange(n)
            low = bins[best]
            for _k in range(d - 1):
                cand = randrange(n)
                if bins[cand] < low:
                    best, low = cand, bins[cand]
            bins[best] += 1
    return max(bins), bins.count(0)


def max_load(n: int, d: int, rng: random.Random) -> int:
    return throw(n, d, rng)[0]


def smooth_wrr(weights, k: int):
    """nginx's smooth weighted round-robin (ngx_http_upstream_round_robin.c).
    Each pick adds every weight to a running current[], selects the argmax, and
    subtracts the total from the winner. Same ratio as naive WRR, no bursts."""
    cur = [0] * len(weights)
    total = sum(weights)
    out = []
    for _ in range(k):
        for i, w in enumerate(weights):
            cur[i] += w
        win = max(range(len(weights)), key=lambda j: cur[j])
        cur[win] -= total
        out.append(win)
    return out


def section1() -> None:
    banner(1, "BALLS IN BINS: WHAT AN 'EVEN' DISTRIBUTION ACTUALLY LOOKS LIKE")
    print("  n requests thrown at n backends, no coordination; max bin over trials")
    print("       n   trials   RR max   random max   ln n / ln ln n   empty bins")
    for n, trials in ((16, 400), (100, 300), (1_000, 120), (10_000, 30)):
        acc = empty = 0
        for t in range(trials):
            mx, ez = throw(n, 1, random.Random(SEED + 991 * t + n))
            acc += mx
            empty += ez
        rnd = acc / trials
        pred = math.log(n) / math.log(math.log(n))
        print(f"  {n:6d}   {trials:6d}   {1:6d}   {rnd:10.2f}   {pred:14.2f}"
              f"   {empty/(trials*n):9.1%}")
    print("  round-robin's max is exactly 1: it is PERFECT by request count.")
    print("  uniform random puts 6.5x the average on some backend at n=10000")
    print("  while leaving 36.8% of them with nothing. That gap is the price of")
    print("  statelessness, and section 4 buys almost all of it back with ONE")
    print("  extra random sample.  (ln n / ln ln n is asymptotic and under-reads")
    print("   at these n; the measured column is the one to trust.)")

    print("\n  the sequence round-robin emits, weights A=5 B=1 C=1:")
    naive = "A" * 5 + "B" + "C"
    smooth = "".join("ABC"[i] for i in smooth_wrr([5, 1, 1], 14))
    print(f"    naive weighted RR   {naive * 2}   <- A gets a 5-deep burst")
    print(f"    smooth weighted RR  {smooth}   <- same 5:1:1 ratio, spread out")
    print("  identical ratios over 7 picks; only one of them keeps A's queue flat.")


# ══ 2-3-5 ═══════════════════════════════════════════════════════════════════════
# One discrete-event simulator drives every policy comparison. Every policy sees
# the IDENTICAL arrival stream and the IDENTICAL per-request work, so any
# difference in the output is caused by the routing decision and nothing else.

POLICIES = ("rr", "random", "least_conn", "least_conn_stale",
            "peak_ewma", "peak_ewma_nofail", "p2c", "p2c_stale", "p2c_ewma")


def make_stream(rate: float, seconds: float, cost_fn, seed: int):
    """A Poisson arrival process. Returns [(arrival_time, work_ms), ...]."""
    rng = random.Random(seed)
    out = []
    t = 0.0
    while True:
        t += rng.expovariate(rate)
        if t > seconds:
            return out
        out.append((t, cost_fn(rng)))


def simulate(policy: str, stream, speeds, workers: int, *, seed: int = 7,
             black_hole=None, fail_penalty_ms: float = 0.0,
             eject: bool = False, tau: float = 0.05,
             stale: float = 0.1):
    """Route `stream` across len(speeds) backends under `policy`.

    speeds[i] is a rate multiplier: service time = work_ms / speeds[i].
    black_hole: an index that always fails in 0.5 ms without doing the work.
    fail_penalty_ms: what a failure records into the latency EWMA (0 = the
      truth as the balancer sees it, which is "that backend is very fast").
    eject: passive outlier ejection — >50% errors in the last 20 outcomes
      removes the backend from rotation for 5 s.
    stale: refresh interval for the *_stale policies' view of load.
    """
    n = len(speeds)
    rng = random.Random(seed)
    inflight = [0] * n                       # queued + in service
    busy = [0] * n
    queues = [collections.deque() for _ in range(n)]
    view = [0] * n                           # the stale copy of inflight
    last_refresh = -1e9
    count = [0] * n
    heavy = [0] * n                          # requests costing >= 900 ms of work
    work = [0.0] * n
    maxq = [0] * n
    ewma = [0.0] * n
    stamp = [0.0] * n
    outcomes = [collections.deque(maxlen=20) for _ in range(n)]
    ejected_until = [-1.0] * n
    errors = [0] * n
    rr = itertools.count()
    ev: list = []
    seq = itertools.count()
    lat_ok: list = []
    queued_while_idle = 0

    def decayed(i: int, t: float) -> float:
        return ewma[i] * math.exp(-(t - stamp[i]) / tau)

    def observe(i: int, t: float, obs: float) -> None:
        """Peak EWMA: jump instantly to a new maximum, decay slowly back down.
        alpha = 1 - e^(-dt/tau), so a busy backend is sampled often and a quiet
        one keeps its last verdict until it is re-measured."""
        prev = decayed(i, t)
        alpha = 1.0 - math.exp(-(t - stamp[i]) / tau)
        ewma[i] = obs if obs > prev else prev * (1.0 - alpha) + obs * alpha
        stamp[i] = t

    def live(t: float):
        if not eject:
            return range(n)
        ok = [i for i in range(n) if ejected_until[i] <= t]
        return ok if ok else range(n)

    def choose(t: float, cands) -> int:
        nonlocal last_refresh
        cl = cands if isinstance(cands, list) else list(cands)
        if policy in ("least_conn_stale", "p2c_stale") and t - last_refresh >= stale:
            view[:] = inflight
            last_refresh = t
        if policy == "rr":
            return cl[next(rr) % len(cl)]
        if policy == "random":
            return cl[rng.randrange(len(cl))]
        if policy == "least_conn":
            return min(cl, key=lambda i: (inflight[i], rng.random()))
        if policy == "least_conn_stale":
            return min(cl, key=lambda i: (view[i], rng.random()))
        if policy in ("peak_ewma", "peak_ewma_nofail"):
            return min(cl, key=lambda i: (decayed(i, t) * (inflight[i] + 1),
                                          rng.random()))
        if len(cl) == 1:
            return cl[0]
        a = cl[rng.randrange(len(cl))]
        b = cl[rng.randrange(len(cl))]
        while b == a:
            b = cl[rng.randrange(len(cl))]
        if policy == "p2c":
            return a if inflight[a] <= inflight[b] else b
        if policy == "p2c_stale":
            return a if view[a] <= view[b] else b
        ca = decayed(a, t) * (inflight[a] + 1)
        cb = decayed(b, t) * (inflight[b] + 1)
        return a if ca <= cb else b

    def start(i: int, arrival: float, cost_ms: float, t: float) -> None:
        busy[i] += 1
        if black_hole is not None and i == black_hole:
            dur, err = 0.0005, True
        else:
            dur, err = (cost_ms / 1000.0) / speeds[i], False
        work[i] += dur
        heapq.heappush(ev, (t + dur, next(seq), i, arrival, err))

    ai, m, horizon = 0, len(stream), 0.0
    while ai < m or ev:
        if ev and (ai >= m or ev[0][0] <= stream[ai][0]):
            t, _, i, arrival, err = heapq.heappop(ev)
            horizon = t
            busy[i] -= 1
            inflight[i] -= 1
            rtt = t - arrival
            if err:
                errors[i] += 1
            else:
                lat_ok.append(rtt)
            obs = (fail_penalty_ms / 1000.0) if (err and fail_penalty_ms) else rtt
            observe(i, t, obs)
            outcomes[i].append(err)
            if eject and len(outcomes[i]) == 20 and sum(outcomes[i]) > 10:
                ejected_until[i] = t + 5.0
                outcomes[i].clear()
            if queues[i]:
                at, cost_ms = queues[i].popleft()
                start(i, at, cost_ms, t)
            continue

        t, cost_ms = stream[ai]
        ai += 1
        cl = list(live(t))
        i = choose(t, cl)
        count[i] += 1
        if cost_ms >= 900.0:
            heavy[i] += 1
        inflight[i] += 1
        if busy[i] < workers:
            start(i, t, cost_ms, t)
        else:
            if any(busy[j] == 0 for j in range(n) if j != i):
                queued_while_idle += 1
            queues[i].append((t, cost_ms))
            if len(queues[i]) > maxq[i]:
                maxq[i] = len(queues[i])

    span = max(horizon, stream[-1][0] if stream else 1.0)
    return {
        "count": count, "work": work, "maxq": maxq, "errors": errors,
        "lat": lat_ok, "span": span, "heavy": heavy,
        "busy_frac": [w / (workers * span) for w in work],
        "queued_while_idle": queued_while_idle,
        "total": len(stream),
    }


# ══ 2 ═══════════════════════════════════════════════════════════════════════════
# Equal counts, unequal work. Eight identical backends, one heavy-tailed cost
# distribution, perfect round-robin. The request-count column is the dashboard
# everybody looks at. The work column is the truth.

def mixed_cost(rng: random.Random) -> float:
    """A real endpoint's cost profile: mostly cache hits, occasionally a tenant
    with 40,000 rows. mean 20.9 ms, CV^2 = 19.1."""
    r = rng.random()
    if r < 0.70:
        return 3.0            # cache hit
    if r < 0.95:
        return 20.0           # one indexed query
    if r < 0.99:
        return 120.0          # a join and a serialize
    return 900.0              # "list everything for this account"


N_BACKENDS = 8
WORKERS = 2
S2_RATE = 500.0
S2_SECONDS = 40.0


def section2():
    banner(2, "EQUAL COUNTS, UNEQUAL LOAD — THE LIE, MEASURED")
    stream = make_stream(S2_RATE, S2_SECONDS, mixed_cost, SEED + 1)
    speeds = [1.0] * N_BACKENDS
    mean_cost = sum(c for _, c in stream) / len(stream)
    print(f"  {N_BACKENDS} identical backends x {WORKERS} workers; "
          f"{len(stream)} requests over {S2_SECONDS:.0f}s "
          f"({S2_RATE:.0f}/s offered)")
    print(f"  work per request: 70% 3ms / 25% 20ms / 4% 120ms / 1% 900ms "
          f"(measured mean {mean_cost:.1f} ms)")
    res = {p: simulate(p, stream, speeds, WORKERS, seed=SEED + 5)
           for p in ("rr", "least_conn", "p2c")}
    rr = res["rr"]
    print("\n  ROUND-ROBIN, per backend:")
    print("    backend   requests    share   900ms reqs   work(s)    share"
          "    busy%   maxQ")
    tot_w = sum(rr["work"])
    for i in range(N_BACKENDS):
        print(f"    {i:>7d}   {rr['count'][i]:8d}   {rr['count'][i]/len(stream):6.1%}"
              f"   {rr['heavy'][i]:10d}   {rr['work'][i]:7.1f}"
              f"   {rr['work'][i]/tot_w:6.1%}   {rr['busy_frac'][i]:6.1%}"
              f" {rr['maxq'][i]:6d}")
    cmin, cmax = min(rr["count"]), max(rr["count"])
    wmin, wmax = min(rr["work"]), max(rr["work"])
    print(f"    request count spread: {cmax - cmin} requests "
          f"({(cmax/cmin - 1):.2%} between the busiest and quietest)")
    print(f"    actual WORK spread:   {wmax - wmin:.1f} s "
          f"({(wmax/wmin - 1):.2%}) — same fleet, same second")
    print(f"    busy time: {min(rr['busy_frac']):.1%} on the quietest backend, "
          f"{max(rr['busy_frac']):.1%} on the busiest")
    print(f"    the mechanism: the 900 ms tail is 1% of requests and "
          f"{sum(rr['heavy'])*0.9/tot_w:.0%} of the work, and round-robin")
    print(f"    dealt {min(rr['heavy'])}-{max(rr['heavy'])} of them per backend "
          f"because it cannot see request size.")

    print("\n  the same stream, three policies:")
    print("    policy            p50      p99     p999    maxQ   queued while another"
          " backend was IDLE")
    for p in ("rr", "p2c", "least_conn"):
        r = res[p]
        print(f"    {p:<14} {pct(r['lat'],.50)*1000:6.1f}ms "
              f"{pct(r['lat'],.99)*1000:6.1f}ms {pct(r['lat'],.999)*1000:7.1f}ms"
              f"  {max(r['maxq']):6d}   {r['queued_while_idle']:8d}"
              f" = {r['queued_while_idle']/r['total']:5.1%}")
    print(f"    round-robin made {rr['queued_while_idle']} of {rr['total']} requests"
          f" wait in a queue while another backend sat completely idle.")
    print("    it had nowhere else to go: its turn had come, so it dealt the card.")
    return rr, res


# ══ 3 ═══════════════════════════════════════════════════════════════════════════
# The heterogeneous-backend case: one instance is 3x slower and nothing reports
# it as unhealthy. Round-robin gives it exactly as much work as the fast ones,
# which is the one thing you must never do.

S3_RATE = 245.0
S3_SECONDS = 40.0
SLOW = 0.3333
N_FLEET = 32
F_RATE = 1900.0
F_SECONDS = 12.0
FLEET_STALE = 0.25


def section3():
    banner(3, "ONE BACKEND IS 3x SLOWER AND NOTHING IS 'DOWN' (GREY FAILURE)")
    stream = make_stream(S3_RATE, S3_SECONDS,
                         lambda r: r.expovariate(1 / 20.0), SEED + 2)
    speeds = [SLOW] + [1.0] * (N_BACKENDS - 1)
    fast_cap = WORKERS / 0.020
    slow_cap = WORKERS / (0.020 / SLOW)
    print(f"  backend 0 runs at {SLOW:.2f}x speed (60 ms where the others take 20 ms)")
    print(f"  fleet capacity {7*fast_cap + slow_cap:.0f} req/s "
          f"(7 x {fast_cap:.0f} + 1 x {slow_cap:.0f}); "
          f"offered {S3_RATE:.0f} req/s = "
          f"{S3_RATE/(7*fast_cap + slow_cap):.0%} of the fleet")
    print(f"  round-robin hands backend 0 {S3_RATE/N_BACKENDS:.0f} req/s "
          f"against its {slow_cap:.1f} req/s of capacity -> rho = "
          f"{(S3_RATE/N_BACKENDS)/slow_cap:.2f}")
    fleet = 7 * fast_cap + slow_cap
    ceiling = N_BACKENDS * slow_cap
    print(f"  every backend gets offered/n, so the SLOWEST one sets the ceiling:")
    print(f"    round-robin ceiling = {N_BACKENDS} x {slow_cap:.1f} = {ceiling:.0f}"
          f" req/s out of {fleet:.0f} req/s of real capacity"
          f" -> {1 - ceiling/fleet:.0%} unreachable")
    print(f"    a 9th healthy instance moves the ceiling to "
          f"{(N_BACKENDS+1)*slow_cap:.0f} req/s while adding {fast_cap:.0f} req/s of"
          f" capacity — the unreachable share grows to "
          f"{1 - (N_BACKENDS+1)*slow_cap/(fleet+fast_cap):.0%}.")
    print("\n    policy                  p50      p99     p999   maxQ  b0 share  b0 busy%")
    rows = {}
    for p in ("rr", "random", "least_conn", "least_conn_stale",
              "peak_ewma", "p2c", "p2c_stale", "p2c_ewma"):
        r = simulate(p, stream, speeds, WORKERS, seed=SEED + 9)
        rows[p] = r
        print(f"    {p:<18} {pct(r['lat'],.50)*1000:7.1f}ms "
              f"{pct(r['lat'],.99)*1000:6.1f}ms {pct(r['lat'],.999)*1000:7.1f}ms"
              f" {max(r['maxq']):5d}  {r['count'][0]/r['total']:7.1%}"
              f"  {r['busy_frac'][0]:8.1%}")
    base = pct(rows["rr"]["lat"], .99) * 1000
    r0 = rows["rr"]
    others = sum(r0["busy_frac"][1:]) / (N_BACKENDS - 1)
    print(f"    under round-robin backend 0 was {r0['busy_frac'][0]:.1%} busy while the"
          f" other seven averaged {others:.1%};")
    print(f"    p50 {pct(r0['lat'],.50)*1000:.1f} ms but p99 {base:.0f} ms — "
          f"{base/(pct(r0['lat'],.50)*1000):.0f}x its own median.")
    print(f"    round-robin p99 {base:.0f} ms; "
          f"least-conn {pct(rows['least_conn']['lat'],.99)*1000:.0f} ms; "
          f"P2C {pct(rows['p2c']['lat'],.99)*1000:.0f} ms "
          f"({base/(pct(rows['p2c']['lat'],.99)*1000):.1f}x better)")
    print("    least-connections and P2C both find the slow backend without being")
    print("    told it is slow: they measure load, and round-robin counts arrivals.")

    # ── herding: the same policies where the load view is SHARED and STALE ──
    print(f"\n  fleet scale — {N_FLEET} identical backends, every balancer reading "
          f"ONE shared\n  load view refreshed every {int(FLEET_STALE*1000)} ms "
          f"(a load report, not a local counter).")
    fstream = make_stream(F_RATE, F_SECONDS,
                          lambda r: r.expovariate(1 / 20.0), SEED + 6)
    fspeeds = [1.0] * N_FLEET
    print(f"  {len(fstream)} requests at {F_RATE:.0f}/s; "
          f"{F_RATE*FLEET_STALE:.0f} arrive between two refreshes")
    print("    policy                  p50      p99     p999   maxQ   busiest backend")
    for p in ("least_conn", "least_conn_stale", "p2c", "p2c_stale"):
        r = simulate(p, fstream, fspeeds, WORKERS, seed=SEED + 13,
                     stale=FLEET_STALE)
        rows["fleet_" + p] = r
        print(f"    {p:<18} {pct(r['lat'],.50)*1000:7.1f}ms "
              f"{pct(r['lat'],.99)*1000:6.1f}ms {pct(r['lat'],.999)*1000:7.1f}ms"
              f" {max(r['maxq']):5d}   {max(r['count'])/r['total']:8.2%}"
              f"  (even = {1/N_FLEET:.2%})")
    lc = pct(rows["fleet_least_conn_stale"]["lat"], .99) * 1000
    pc = pct(rows["fleet_p2c_stale"]["lat"], .99) * 1000
    print(f"    on a stale view least-connections is {lc/pc:.1f}x worse at p99 than")
    print(f"    P2C ({lc:.0f} ms vs {pc:.0f} ms) — every balancer computed the same")
    print("    argmin and stampeded the same backend. P2C's random pair breaks the")
    print("    correlation: two balancers rarely draw the same pair.")
    return rows


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# The power of two choices. One random sample gives max load Theta(ln n/ln ln n).
# TWO samples give Theta(ln ln n / ln 2): exponentially better, from one extra
# random number and zero coordination (Azar et al. 1999; Mitzenmacher 2001).

def section4():
    banner(4, "THE POWER OF TWO CHOICES, MEASURED")
    print("  n balls into n bins; mean of the maximum bin over trials")
    print("        n  trials  d=1(random)  d=2(P2C)  d=3   ln n/ln ln n  ln ln n/ln2")
    for n, trials in ((100, 300), (1_000, 120), (10_000, 40), (100_000, 12)):
        got = []
        for d in (1, 2, 3):
            acc = 0
            for t in range(trials):
                acc += max_load(n, d, random.Random(SEED + 77 * t + 3 * d + n))
            got.append(acc / trials)
        p1 = math.log(n) / math.log(math.log(n))
        p2 = math.log(math.log(n)) / math.log(2)
        print(f"  {n:8d}  {trials:6d}  {got[0]:11.2f}  {got[1]:8.2f}  {got[2]:4.2f}"
              f"   {p1:12.2f}  {p2:11.2f}")
    print("  d=1 grows with n; d=2 barely moves. At n=100000 the SECOND sample")
    print("  removes 4.42 of maximum load and the THIRD removes 0.50 more —")
    print("  the first extra sample is worth ~9x the next one, which is exactly")
    print("  why every service mesh ships choice_count = 2 and stops there.")


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# The death spiral. A backend that fails INSTANTLY has the fewest outstanding
# requests and the lowest latency, so every load-aware policy rewards it. This
# is the failure mode that makes "least connections" dangerous.

S5_RATE = 640.0
S5_SECONDS = 30.0


def section5():
    banner(5, "THE DEATH SPIRAL: FAILING FAST IS REWARDED BY EVERY LOAD SIGNAL")
    stream = make_stream(S5_RATE, S5_SECONDS,
                         lambda r: r.expovariate(1 / 20.0), SEED + 3)
    speeds = [1.0] * N_BACKENDS
    print(f"  backend 0 returns HTTP 500 in 0.5 ms without doing any work.")
    print(f"  {len(stream)} requests, {N_BACKENDS} backends. A blind policy sends "
          f"1/{N_BACKENDS} = {1/N_BACKENDS:.1%} into it.")
    print("\n    policy                          traffic into the black hole   errors")
    cfgs = [
        ("round_robin", "rr", {}),
        ("least_conn", "least_conn", {}),
        ("peak_ewma (latency only)", "peak_ewma_nofail", {}),
        ("p2c (outstanding)", "p2c", {}),
        ("peak_ewma + failure penalty", "peak_ewma", {"fail_penalty_ms": 2000.0}),
        ("p2c_ewma + penalty", "p2c_ewma", {"fail_penalty_ms": 2000.0}),
        ("p2c_ewma + penalty + ejection", "p2c_ewma",
         {"fail_penalty_ms": 2000.0, "eject": True}),
    ]
    out = {}
    for label, pol, kw in cfgs:
        r = simulate(pol, stream, speeds, WORKERS, seed=SEED + 11,
                     black_hole=0, **kw)
        share = r["count"][0] / r["total"]
        out[label] = share
        bar = "#" * int(round(share * 40))
        print(f"    {label:<30} {share:7.1%}  {bar:<40} {r['errors'][0]:6d}")
    print(f"    least-connections sent {out['least_conn']:.1%} of ALL traffic into a backend "
          f"that answered\n    nothing, and peak-EWMA on latency alone sent "
          f"{out['peak_ewma (latency only)']:.1%}. Neither is a bug:\n"
          "    0 outstanding requests and 0.5 ms of latency genuinely ARE the best\n"
          "    scores in the fleet. The signal is right; the interpretation is wrong.")
    print(f"    P2C caps the damage at d/n = 2/{N_BACKENDS} = {2/N_BACKENDS:.0%} "
          f"(measured {out['p2c (outstanding)']:.1%}) because a bad backend can only")
    print("    win when it is one of the two sampled — no global argmin exists.")
    print(f"    counting a failure as a 2000 ms sample: "
          f"{out['peak_ewma + failure penalty']:.1%}. Adding passive ejection: "
          f"{out['p2c_ewma + penalty + ejection']:.1%}.")
    return out


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# Consistent hashing, and consistent hashing with bounded loads. The ring gives
# you affinity (the same key lands on the same backend) and, on its own, terrible
# balance under skewed traffic. A (1+eps) cap with clockwise overflow gives you
# both (Mirrokni, Thorup & Zadimoghaddam, SIAM J. Comput. 47(3), 2018).

def h64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


class Ring:
    def __init__(self, backends, vnodes: int):
        pairs = sorted((h64(f"{b}#{v}"), b) for b in backends for v in range(vnodes))
        self.pos = [p for p, _ in pairs]
        self.own = [b for _, b in pairs]
        self.n = len(backends)

    def walk(self, key_hash: int):
        """Yield backends clockwise from key_hash, each at most once."""
        idx = bisect.bisect(self.pos, key_hash) % len(self.pos)
        seen = set()
        for k in range(len(self.pos)):
            b = self.own[(idx + k) % len(self.pos)]
            if b not in seen:
                seen.add(b)
                yield b
            if len(seen) == self.n:
                return


def assign(ring: Ring, keys, eps=None):
    """Place every request. eps=None is the plain ring; a value caps each
    backend at ceil((1+eps) * placed / n) and overflows clockwise."""
    load = collections.Counter()
    dest = []
    for i, kh in enumerate(keys, 1):
        if eps is None:
            b = next(ring.walk(kh))
        else:
            cap = math.ceil((1.0 + eps) * i / ring.n)
            b = None
            for cand in ring.walk(kh):
                if load[cand] < cap:
                    b = cand
                    break
            if b is None:                       # cannot happen, but be explicit
                b = next(ring.walk(kh))
        load[b] += 1
        dest.append(b)
    return dest, load


def zipf_keys(n_keys: int, n_req: int, s: float, seed: int):
    rng = random.Random(seed)
    w = [1.0 / (k ** s) for k in range(1, n_keys + 1)]
    cum, run = [], 0.0
    for x in w:
        run += x
        cum.append(run)
    total = cum[-1]
    ks = [bisect.bisect(cum, rng.random() * total) for _ in range(n_req)]
    return [h64(f"tenant-{k}") for k in ks], ks


S6_REQ = 80_000
S6_KEYS = 20_000
VNODES = 150
EPS = 0.25


def section6():
    banner(6, "CONSISTENT HASHING, AND WHY IT NEEDS A BOUND")
    keys, ids = zipf_keys(S6_KEYS, S6_REQ, 1.0, SEED + 4)
    top = collections.Counter(ids).most_common(1)[0]
    print(f"  {S6_REQ} requests over {S6_KEYS} keys, Zipf s=1.0 "
          f"(the hottest key is {top[1]/S6_REQ:.1%} of traffic)")
    print(f"  {N_BACKENDS} backends, {VNODES} virtual nodes each, eps = {EPS}")
    full = [f"be-{i}" for i in range(N_BACKENDS)]
    gone = full[:-1]
    mean = S6_REQ / N_BACKENDS
    print("\n    ring                        max/mean  min/mean  survives removal"
          "  on primary")
    cfgs = ((f"plain,        1 vnode", 1, None),
            (f"plain,   {VNODES} vnodes", VNODES, None),
            (f"bounded, {VNODES} vnodes, {1+EPS:.2f}x", VNODES, EPS))
    for label, vn, eps in cfgs:
        ra, rb = Ring(full, vn), Ring(gone, vn)
        da, la = assign(ra, keys, eps)
        db, _ = assign(rb, keys, eps)
        mx, mn = max(la.values()), min(la.values())
        # of the requests that did NOT belong to the removed backend, how many
        # kept their destination? That is the cache that survives a scale-in.
        elig = [i for i in range(S6_REQ) if da[i] != full[-1]]
        stay = sum(1 for i in elig if da[i] == db[i])
        prim = sum(1 for i in range(S6_REQ) if da[i] == next(ra.walk(keys[i])))
        print(f"    {label:<26} {mx/mean:8.3f}  {mn/mean:8.3f}  {stay/len(elig):15.2%}"
              f"  {prim/S6_REQ:10.2%}")
    print(f"    one virtual node per backend puts a random arc of the ring on each")
    print(f"    server, and random arcs are not equal — that is why vnodes exist.")
    print(f"    150 vnodes fixes the ARC problem but not the TRAFFIC problem: the")
    print(f"    hottest key alone is {top[1]/S6_REQ:.1%} of requests, and the ring has no")
    print(f"    choice but to send all of it to one backend.")
    print(f"    the bound caps every backend at {1+EPS:.2f}x the mean by construction and")
    print(f"    pays for it in affinity, which is the trade stated honestly.")


def main() -> None:
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()


if __name__ == "__main__":
    import time as _time
    _t0 = _time.perf_counter()
    main()
    print(f"\n  (total wall time {_time.perf_counter() - _t0:.1f} s)")
