#!/usr/bin/env python3
"""Phase 11 - Lesson 11: The Tail at Scale (fan-out, hedged requests, correlated failure).

Companion program for phases/11-scalability-and-reliability/11-the-tail-at-scale/docs/en.md.
Sources: Dean, J. & Barroso, L. A., "The Tail at Scale", Communications of the ACM
56(2):74-80, 2013; Bronson, N. et al., "Metastable Failures in Distributed Systems",
HotOS 2021. Standard library only, seeded (SEED = 7), self-terminating, no network.
"""

from __future__ import annotations

import collections
import heapq
import itertools
import math
import random

SEED = 7

# --------------------------------------------------------------------------- #
# The backend response-time distribution.
#
# A lognormal body (the normal case: parse, index probe, serialise) plus a rare
# heavy-tailed "hiccup" (GC pause, compaction, a co-tenant stealing the memory
# bus, an SSD erase block). Real backend latency looks like this: a tight body
# and a tail that is orders of magnitude away from the median, not a few
# percent. A server-side execution limit truncates the tail at 3 s, because no
# real backend runs forever.
# --------------------------------------------------------------------------- #
BODY_MEDIAN = 9.0     # ms
BODY_SIGMA = 0.45     # lognormal shape
HICCUP_P = 0.03       # 3% of calls hit an interference event
HICCUP_XM = 48.0      # ms - Pareto scale of that event
HICCUP_ALPHA = 1.6    # Pareto shape: heavy, finite mean, infinite variance
EXEC_LIMIT = 3000.0   # ms - the backend's own server-side execution limit


def draw_latency(rng: random.Random) -> float:
    """One backend call's response time in milliseconds."""
    v = BODY_MEDIAN * math.exp(BODY_SIGMA * rng.gauss(0.0, 1.0))
    if rng.random() < HICCUP_P:
        v += HICCUP_XM / (1.0 - rng.random()) ** (1.0 / HICCUP_ALPHA)
    return v if v < EXEC_LIMIT else EXEC_LIMIT


def pct(xs: list[float], q: float) -> float:
    """Linear-interpolated percentile of an already-sorted list."""
    if not xs:
        return 0.0
    k = (len(xs) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    if lo == hi:
        return xs[int(k)]
    return xs[lo] * (hi - k) + xs[hi] * (k - lo)


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# =========================================================================== #
# 1 - FAN-OUT AMPLIFICATION
# =========================================================================== #
def section1(pool: list[float]) -> dict[str, float]:
    banner("1 . FAN-OUT AMPLIFICATION: YOUR p99 IS EVERYONE'S MEDIAN")
    rng = random.Random(SEED + 1)
    K = len(pool)
    randrange = rng.randrange

    single = {q: pct(pool, q) for q in (0.50, 0.90, 0.99, 0.999)}
    print(f"  one backend call, {K:,} samples "
          f"(lognormal body + {HICCUP_P:.0%} heavy-tailed hiccup):")
    print(f"    p50 {single[0.50]:7.1f} ms   p90 {single[0.90]:7.1f} ms   "
          f"p99 {single[0.99]:7.1f} ms   p99.9 {single[0.999]:7.1f} ms")
    print("  every backend team would call that a healthy service.\n")

    p99_ms = single[0.99]
    p999_ms = single[0.999]

    print("  a user request fans out to N shards and must wait for ALL of them,")
    print("  so its latency is the MAXIMUM of N independent calls:\n")
    print("     N      p50      p90      p99    p99.9   P(>=1 call over backend p99)"
          "     hit the")
    print("                                              measured    1-(1-p)^N"
          "       3 s limit")

    results: dict[int, dict[str, float]] = {}
    for n, m in ((1, 40000), (5, 40000), (20, 40000), (100, 20000), (500, 4000)):
        maxes: list[float] = []
        over = under_p999 = capped = 0
        for _ in range(m):
            worst = 0.0
            for _ in range(n):
                v = pool[randrange(K)]
                if v > worst:
                    worst = v
            maxes.append(worst)
            if worst > p99_ms:
                over += 1
            if worst <= p999_ms:
                under_p999 += 1
            if worst >= EXEC_LIMIT:
                capped += 1
        maxes.sort()
        measured = over / m
        theory = 1.0 - (1.0 - 0.01) ** n
        results[n] = {
            "p50": pct(maxes, 0.50), "p90": pct(maxes, 0.90),
            "p99": pct(maxes, 0.99), "p999": pct(maxes, 0.999),
            "under_p999": under_p999 / m, "capped": capped / m,
        }
        r = results[n]
        print(f"  {n:4d}  {r['p50']:7.1f}  {r['p90']:7.1f}  {r['p99']:7.1f}  "
              f"{r['p999']:7.1f}      {measured:7.1%}     {theory:7.1%}"
              f"     {r['capped']:8.2%}")

    print("\n  the arithmetic is exact, and it is the whole lesson:")
    print(f"    backend p99      = {p99_ms:6.1f} ms   (1% of calls are slower)")
    print(f"    user p50 at N=100 = {results[100]['p50']:6.1f} ms   "
          f"<-- the MEDIAN 100-way request is "
          f"{results[100]['p50'] / p99_ms:.2f}x the p99 of every backend it called")
    print(f"    user p50 at N=500 = {results[500]['p50']:6.1f} ms   "
          f"= {results[500]['p50'] / p99_ms:.2f}x that same backend p99")
    print(f"  and one backend's p99.9 ({p999_ms:.0f} ms) is the "
          f"p{results[100]['under_p999'] * 100:.1f} of a 100-way fan-out")
    print(f"  (theory: 0.999^100 = {0.999 ** 100:.3f}). Nobody's dashboard shows this,")
    print("  because the problem is not in any one service - it is in the multiplication.")
    return {"p50": single[0.50], "p95": pct(pool, 0.95), "p99": p99_ms, "p999": p999_ms}


# =========================================================================== #
# 2 - HEDGED REQUESTS
# =========================================================================== #
def hedged(pool: list[float], K: int, randrange, delay: float) -> tuple[float, bool]:
    """One call, hedged to a second replica if it has not answered by `delay`."""
    a = pool[randrange(K)]
    if a <= delay:
        return a, False
    b = pool[randrange(K)]          # a second copy, to a different replica
    return (a if a < delay + b else delay + b), True


def section2(pool: list[float], single: dict[str, float]) -> float:
    banner("2 . HEDGED REQUESTS: BUY THE TAIL BACK FOR 5% MORE LOAD")
    rng = random.Random(SEED + 2)
    K = len(pool)
    randrange = rng.randrange
    delay95 = single["p95"]

    m = 200_000
    base = sorted(pool[randrange(K)] for _ in range(m))
    lat: list[float] = []
    hedges = 0
    for _ in range(m):
        v, h = hedged(pool, K, randrange, delay95)
        lat.append(v)
        hedges += h
    lat.sort()
    print(f"  hedge delay = the measured p95 of one call = {delay95:.1f} ms")
    print(f"  {m:,} single calls, each replicated to a second replica only if slow:\n")
    print("                      p50      p99    p99.9   hedged   extra load")
    print(f"  no hedge        {pct(base, .50):7.1f}  {pct(base, .99):7.1f}  "
          f"{pct(base, .999):7.1f}     0.0%         0.0%")
    print(f"  hedge @ p95     {pct(lat, .50):7.1f}  {pct(lat, .99):7.1f}  "
          f"{pct(lat, .999):7.1f}  {hedges / m:6.1%}  {hedges / m:11.1%}")
    print(f"  -> p99 {pct(base, .99):.1f} -> {pct(lat, .99):.1f} ms "
          f"({pct(base, .99) / pct(lat, .99):.2f}x better), "
          f"p99.9 {pct(base, .999):.0f} -> {pct(lat, .999):.0f} ms "
          f"({pct(base, .999) / pct(lat, .999):.2f}x)")

    print("\n  the same hedging, applied to every shard of a 100-way fan-out:")
    n, fm = 100, 20_000
    for label, d in (("no hedge", None), ("hedge @ p95", delay95)):
        maxes, calls, hh = [], 0, 0
        for _ in range(fm):
            worst = 0.0
            for _ in range(n):
                if d is None:
                    v, h = pool[randrange(K)], False
                else:
                    v, h = hedged(pool, K, randrange, d)
                calls += 1 + h
                hh += h
                if v > worst:
                    worst = v
            maxes.append(worst)
        maxes.sort()
        print(f"  {label:<14}  p50 {pct(maxes, .50):7.1f}   p99 {pct(maxes, .99):7.1f}   "
              f"p99.9 {pct(maxes, .999):7.1f}   backend calls "
              f"{calls / (fm * n):.3f} per shard")

    print("\n  sweeping the hedge delay - the trade, made visible:")
    print("   delay set at    delay     p50      p99    p99.9   hedged   extra load")
    for name, q in (("p50", .50), ("p75", .75), ("p90", .90), ("p95", .95), ("p99", .99)):
        d = pct(pool, q)
        s = 60_000
        ls, hs = [], 0
        for _ in range(s):
            v, h = hedged(pool, K, randrange, d)
            ls.append(v)
            hs += h
        ls.sort()
        print(f"   {name:<12} {d:7.1f} {pct(ls, .50):7.1f}  {pct(ls, .99):7.1f}  "
              f"{pct(ls, .999):7.1f}  {hs / s:6.1%}  {hs / s:11.1%}")
    print("  hedging at p50 buys a slightly better p99.9 for ~50% more backend load.")
    print("  hedging at p95 buys almost all of it for ~5%. That is the operating point.")
    return delay95


# =========================================================================== #
# The cluster simulator - a fleet of single-threaded replicas with real queues.
# =========================================================================== #
class Task:
    __slots__ = ("req", "server", "started", "cancelled", "dead")

    def __init__(self, req: "Req", server: int) -> None:
        self.req = req
        self.server = server
        self.started: float | None = None
        self.cancelled = False
        self.dead = False       # was already useless when it began executing


class Req:
    __slots__ = ("arrival", "done_at", "tasks")

    def __init__(self, arrival: float) -> None:
        self.arrival = arrival
        self.done_at: float | None = None
        self.tasks: list[Task] = []


def simulate_cluster(seed: int, *, servers: int, slots: int, lam: float,
                     n_requests: int, mode: str = "none", hedge_delay: float = 0.0,
                     hedge_budget: float | None = None, msg_delay: float = 1.0,
                     cancel_enqueued: bool = False) -> dict[str, float]:
    """Discrete-event sim. `lam` is arrivals per millisecond. Times are ms.

    Each of `servers` replicas serves `slots` requests concurrently and queues the
    rest, so a single hiccup does not block the whole replica.

    mode: "none" | "hedge" (second copy after hedge_delay) | "tied" (both copies
    immediately, each carrying the other's identity; whoever STARTS first sends a
    cancel to its twin, which lands msg_delay later).

    cancel_enqueued: whether the SERVER can drop queued work whose answer is no
    longer wanted. False is the HTTP default - a client that gives up does not
    stop the server, so every copy issued is a copy executed. True requires real
    cancellation propagation (gRPC, or Dean & Barroso's tied requests).
    """
    rng = random.Random(seed)
    heap: list = []
    seq = itertools.count()
    queues = [collections.deque() for _ in range(servers)]
    inflight = [0] * servers
    st = {"requests": 0, "extra": 0, "started": 0, "service_ms": 0.0,
          "wasted_ms": 0.0, "dropped": 0, "denied": 0}

    def push(t: float, kind: str, payload) -> None:
        heapq.heappush(heap, (t, next(seq), kind, payload))

    def try_start(s: int, now: float) -> None:
        q = queues[s]
        while inflight[s] < slots and q:
            task = q.popleft()
            dead = task.cancelled or task.req.done_at is not None
            if dead and cancel_enqueued:
                st["dropped"] += 1          # dropped before it cost anything
                continue
            inflight[s] += 1
            task.started = now
            task.dead = dead
            svc = draw_latency(rng)
            st["started"] += 1
            st["service_ms"] += svc
            if dead:
                st["wasted_ms"] += svc      # nobody is waiting for this answer
            push(now + svc, "finish", (s, task, svc))
            if mode == "tied":
                for twin in task.req.tasks:
                    if twin is not task and twin.started is None:
                        push(now + msg_delay, "cancel", twin)

    t = 0.0
    reqs: list[Req] = []
    for _ in range(n_requests):
        t += rng.expovariate(lam)
        r = Req(t)
        reqs.append(r)
        push(t, "arrive", r)
    horizon = t

    def other(s: int) -> int:
        return (s + 1 + rng.randrange(servers - 1)) % servers

    while heap:
        now, _, kind, payload = heapq.heappop(heap)
        if kind == "arrive":
            r = payload
            st["requests"] += 1
            s = rng.randrange(servers)
            t0 = Task(r, s)
            r.tasks.append(t0)
            queues[s].append(t0)
            if mode == "tied":
                s2 = other(s)
                t1 = Task(r, s2)
                r.tasks.append(t1)
                queues[s2].append(t1)
                st["extra"] += 1
                try_start(s, now)
                try_start(s2, now)
            else:
                if mode == "hedge":
                    push(now + hedge_delay, "hedge", r)
                try_start(s, now)
        elif kind == "hedge":
            r = payload
            if r.done_at is not None:
                continue
            if hedge_budget is not None and st["extra"] >= hedge_budget * st["requests"]:
                st["denied"] += 1           # the hedge budget said no
                continue
            s2 = other(r.tasks[0].server)
            t1 = Task(r, s2)
            r.tasks.append(t1)
            queues[s2].append(t1)
            st["extra"] += 1
            try_start(s2, now)
        elif kind == "cancel":
            task = payload
            if task.started is None:
                task.cancelled = True
        else:                                # finish
            s, task, svc = payload
            inflight[s] -= 1
            r = task.req
            if r.done_at is None:
                r.done_at = now
                for tw in r.tasks:
                    if tw is not task and tw.started is None:
                        tw.cancelled = True
            elif not task.dead:
                st["wasted_ms"] += svc       # lost the race after starting alive
            try_start(s, now)

    lat = sorted(r.done_at - r.arrival for r in reqs)
    return {
        "p50": pct(lat, .50), "p95": pct(lat, .95), "p99": pct(lat, .99),
        "p999": pct(lat, .999),
        "extra_pct": st["extra"] / st["requests"],
        "waste_pct": st["wasted_ms"] / st["service_ms"],
        "busy": st["service_ms"] / (servers * slots * horizon),
        "dropped": st["dropped"], "denied": st["denied"],
        "started": st["started"], "requests": st["requests"],
    }


# =========================================================================== #
# 3 - HEDGING UNDER OVERLOAD
# =========================================================================== #
SERVERS = 16
SLOTS = 4
MEAN_SVC = (BODY_MEDIAN * math.exp(BODY_SIGMA ** 2 / 2)
            + HICCUP_P * HICCUP_XM * HICCUP_ALPHA / (HICCUP_ALPHA - 1))
CAPACITY = SERVERS * SLOTS / MEAN_SVC          # requests per ms


def section3() -> float:
    banner("3 . HEDGING UNDER OVERLOAD IS A RETRY STORM WITH A NICER NAME")
    print(f"  {SERVERS} replicas x {SLOTS} concurrent slots, mean service "
          f"{MEAN_SVC:.1f} ms => capacity {CAPACITY * 1000:.0f} req/s")

    calm = simulate_cluster(SEED + 30, servers=SERVERS, slots=SLOTS,
                            lam=0.50 * CAPACITY, n_requests=40_000)
    delay = calm["p95"]
    print(f"  calibration run at rho = 0.50: p50 {calm['p50']:.1f} ms, "
          f"p95 {calm['p95']:.1f} ms, p99 {calm['p99']:.1f} ms")
    print(f"  you set the hedge delay to the p95 you measured while healthy: "
          f"{delay:.1f} ms\n")
    print("  traffic then grows to rho = 0.85 and nobody changes the delay. The")
    print("  backends are plain HTTP: a client that gives up does NOT stop the")
    print("  server, so every second copy issued is a second copy executed.\n")
    print("  config                          p50       p99     p99.9   hedged    busy")
    rows = [
        ("rho=0.85, no hedging", dict(mode="none")),
        ("rho=0.85, hedge, no budget", dict(mode="hedge", hedge_delay=delay)),
        ("rho=0.85, hedge, 5% budget",
         dict(mode="hedge", hedge_delay=delay, hedge_budget=0.05)),
    ]
    out = {}
    for label, kw in rows:
        r = simulate_cluster(SEED + 31, servers=SERVERS, slots=SLOTS,
                             lam=0.85 * CAPACITY, n_requests=60_000, **kw)
        out[label] = r
        print(f"  {label:<28} {r['p50']:7.1f}  {r['p99']:8.1f}  {r['p999']:8.1f}  "
              f"{r['extra_pct']:6.1%}  {r['busy']:6.1%}")
    nb = out["rho=0.85, hedge, no budget"]
    bd = out["rho=0.85, hedge, 5% budget"]
    nh = out["rho=0.85, no hedging"]
    print(f"\n  at rho = 0.85 a delay of {delay:.1f} ms is no longer the p95 of anything. "
          f"Queueing moved")
    print(f"  the whole distribution right, so {nb['extra_pct']:.0%} of requests crossed "
          f"it instead of 5%, and")
    print(f"  offered load became {1 + nb['extra_pct']:.2f}x demand - which turns "
          f"rho = 0.85 into rho = {0.85 * (1 + nb['extra_pct']):.2f}.")
    print(f"  Replicas went {nh['busy']:.0%} -> {nb['busy']:.0%} busy and p99 went "
          f"{nh['p99']:.0f} -> {nb['p99']:.0f} ms, "
          f"{nb['p99'] / nh['p99']:.0f}x WORSE.")
    print("  That is the loop: slow -> hedge -> more load -> slower -> hedge more.")
    print(f"  The 5% budget denied {bd['denied']:,} hedges, held extra load at "
          f"{bd['extra_pct']:.1%}, and kept p99 at")
    print(f"  {bd['p99']:.0f} ms - {nb['p99'] / bd['p99']:.0f}x better than the "
          f"unbudgeted hedge and {nh['p99'] / bd['p99']:.2f}x better than no hedge at all.")
    print("  A hedge without a budget is a retry without a budget. Phase 8 Lesson 11")
    print("  called the general form a metastable failure; this is how you build one.")
    return delay


# =========================================================================== #
# 4 - TIED REQUESTS
# =========================================================================== #
def section4() -> None:
    banner("4 . TIED REQUESTS: PAY A CROSS-SERVER MESSAGE, DELETE THE DELAY")
    # Tied requests were designed for a STORAGE shard: one I/O worker per replica
    # and a real queue in front of it. The cancel only saves work it can catch
    # still sitting in that queue, so this is the regime where it pays.
    servers, slots = 64, 1
    cap = servers * slots / MEAN_SVC
    calm = simulate_cluster(SEED + 39, servers=servers, slots=slots,
                            lam=0.50 * cap, n_requests=40_000)
    delay = calm["p95"]
    print(f"  {servers} storage replicas, ONE I/O worker each, so a real queue forms in")
    print("  front of every one - the regime Dean & Barroso designed tied requests for.")
    print(f"  rho = 0.75, hedge delay = the calm p95 = {delay:.1f} ms, cancel message "
          f"1.0 ms.")
    print("  These servers CAN drop enqueued-but-not-started work; the last row is the")
    print("  same policy on servers that cannot.\n")
    print("  config                   p50      p99     p99.9   2nd copies   of those,   "
          "duplicate")
    print("                                                       issued    ran anyway  "
          "work")
    res = {}
    runs = [
        ("no hedge", dict(mode="none", cancel_enqueued=True)),
        ("hedged @ p95", dict(mode="hedge", hedge_delay=delay, cancel_enqueued=True)),
        ("tied", dict(mode="tied", msg_delay=1.0, cancel_enqueued=True)),
        ("tied, NO cancel path", dict(mode="tied", msg_delay=1.0,
                                      cancel_enqueued=False)),
    ]
    for label, kw in runs:
        r = simulate_cluster(SEED + 40, servers=servers, slots=slots,
                             lam=0.75 * cap, n_requests=40_000, **kw)
        res[label] = r
        ran = ((r["started"] - r["requests"]) / (r["extra_pct"] * r["requests"])
               if r["extra_pct"] else 0.0)
        print(f"  {label:<20} {r['p50']:7.1f}  {r['p99']:7.1f}  {r['p999']:8.1f}  "
              f"{r['extra_pct']:10.1%}  {ran:10.1%}  {r['waste_pct']:10.1%}")
    nh, h, ti, nc = (res["no hedge"], res["hedged @ p95"], res["tied"],
                     res["tied, NO cancel path"])
    print(f"\n  tied cuts the tail harder than hedging (p99 {ti['p99']:.0f} vs "
          f"{h['p99']:.0f} ms against {nh['p99']:.0f} unprotected)")
    print(f"  because it never spends {delay:.0f} ms finding out the first copy is slow. "
          f"It issues a")
    print("  second copy for 100% of requests, which sounds like 2x the load - but only")
    print(f"  {(ti['started'] - ti['requests']) / ti['requests'] * 100:.0f}% of requests "
          f"ever executed one, because the rest were cancelled while")
    print(f"  still queued. Net duplicate work is {ti['waste_pct']:.1%}, against "
          f"{h['waste_pct']:.1%} for hedging - the same order,")
    print(f"  for a much better tail. What is left is the race window: both replicas")
    print("  started inside the 1.0 ms the cancel spent on the wire.")
    print(f"\n  the last row is why this is not free. Strip the cancel path and the same")
    print(f"  tied policy executes both copies of "
          f"{(nc['started'] - nc['requests']) / nc['requests'] * 100:.0f}% of requests, "
          f"burns {nc['waste_pct']:.0%} of all service time on")
    print(f"  answers nobody reads, and takes p99 from {ti['p99']:.0f} to "
          f"{nc['p99']:.0f} ms. Tied requests are a")
    print("  server capability the client gets to use, not a client-side trick.")


# =========================================================================== #
# 5 - CORRELATED VS INDEPENDENT SLOWNESS
# =========================================================================== #
def section5(pool: list[float], delay: float) -> None:
    banner("5 . THE HONEST LIMIT: HEDGING DIES ON CORRELATED SLOWNESS")
    rng = random.Random(SEED + 5)
    K = len(pool)
    randrange = rng.randrange
    random_ = rng.random
    n, m, q = 100, 8_000, 0.05
    stall_lo, stall_hi = 150.0, 450.0
    print(f"  100-way fan-out, hedge delay {delay:.1f} ms. At any moment {q:.0%} of "
          f"replicas are")
    print(f"  stalled - a compaction, a GC pause, a co-tenant - adding "
          f"{stall_lo:.0f}-{stall_hi:.0f} ms to every call.")
    print("  INDEPENDENT: the replica you hedge to draws its own luck.")
    print("  CORRELATED : both replicas of a shard share the cause (same rack, same")
    print("               co-tenant, same bad deploy), so the hedge inherits the stall.\n")
    print("  regime                     p50      p99    p99.9   hedged   p50 gain  "
          "p99 gain")
    baseline: dict[str, tuple[float, float]] = {}
    for regime in ("independent", "correlated"):
        for use_hedge in (False, True):
            maxes: list[float] = []
            hedges = calls = 0
            for _ in range(m):
                worst = 0.0
                for _ in range(n):
                    stall_a = (rng.uniform(stall_lo, stall_hi)
                               if random_() < q else 0.0)
                    a = pool[randrange(K)] + stall_a
                    calls += 1
                    if use_hedge and a > delay:
                        # the shared cause is what "correlated" means: the second
                        # replica of this shard is behind the SAME stall.
                        stall_b = stall_a if regime == "correlated" else (
                            rng.uniform(stall_lo, stall_hi) if random_() < q else 0.0)
                        b = pool[randrange(K)] + stall_b
                        calls += 1
                        hedges += 1
                        a = a if a < delay + b else delay + b
                    if a > worst:
                        worst = a
                maxes.append(worst)
            maxes.sort()
            label = f"{regime}, {'hedged' if use_hedge else 'no hedge'}"
            if not use_hedge:
                baseline[regime] = (pct(maxes, .50), pct(maxes, .99))
                g50 = g99 = "     -"
            else:
                g50 = f"{baseline[regime][0] / pct(maxes, .50):5.2f}x"
                g99 = f"{baseline[regime][1] / pct(maxes, .99):5.2f}x"
            print(f"  {label:<22} {pct(maxes, .50):8.1f} {pct(maxes, .99):8.1f} "
                  f"{pct(maxes, .999):8.1f}  {hedges / calls:6.1%}  {g50:>9} {g99:>9}")
    print("\n  hedging is a bet that the SECOND replica is having a better minute than")
    print("  the first. Independent slowness: the bet pays, and the median 100-way")
    print("  request gets its whole day back. Correlated slowness: the hedge lands on a")
    print("  replica behind the SAME stall, so you paid the extra load and the median")
    print("  did not move. Correlated slowness is a capacity or blast-radius problem")
    print("  (Lesson 9), not a tail problem - and no way of ISSUING requests can fix a")
    print("  problem that lives in the resource both copies are sharing.")


# =========================================================================== #
# 6 - CORRELATION AT FLEET SCALE
# =========================================================================== #
def section6() -> None:
    banner("6 . WHAT BREAKS WHEN 300 INSTANCES RUN THE SAME GOOD PATTERN")
    print("  (a) retry amplification MULTIPLIES across layers - it does not add:\n")
    print("   layers   2 attempts each   3 attempts each   3 attempts, 10% budget each")
    for L in (1, 2, 3, 4):
        print(f"   {L:^6}   {2 ** L:^15d}   {3 ** L:^15d}   {1.1 ** L:^26.2f}")
    print("   a gateway, a mesh sidecar and an SDK that each retry 3x turn ONE user")
    print("   request into 27 at the bottom of the stack, and each layer's owner")
    print("   believes they are the only one retrying.\n")

    INSTANCES, COOLDOWN, WINDOW, DEP_CAP, HORIZON = 300, 5000.0, 100.0, 25, 60_000.0
    print(f"  (b) {INSTANCES} circuit breakers trip in the same second. The recovering")
    print(f"      dependency can absorb {DEP_CAP} probes per {WINDOW:.0f} ms window;")
    print("      more than that and it falls over again and every probe fails.\n")
    print("  cool-down            peak probes    windows      failed    all breakers")
    print("                       per 100 ms   overwhelmed    probes    closed at")
    for label, jitter in (("fixed 5.000 s", False), ("5 s * U(0.5, 1.5)", True)):
        rng = random.Random(SEED + 6)
        pending = []
        for i in range(INSTANCES):
            trip = rng.uniform(0.0, 200.0)         # they all saw the same failure
            wait = COOLDOWN * (0.5 + rng.random()) if jitter else COOLDOWN
            heapq.heappush(pending, (trip + wait, i))
        buckets: dict[int, list[int]] = {}
        closed, failed, peak, bad, closed_at = 0, 0, 0, 0, None
        while pending and pending[0][0] <= HORIZON:
            t0 = pending[0][0]
            w = int(t0 // WINDOW)
            group = []
            while pending and int(pending[0][0] // WINDOW) == w:
                group.append(heapq.heappop(pending)[1])
            buckets[w] = group
            peak = max(peak, len(group))
            if len(group) <= DEP_CAP:
                closed += len(group)
                if closed == INSTANCES:
                    closed_at = t0
            else:
                bad += 1
                failed += len(group)
                for i in group:                    # reopen, wait again, try again
                    wait = COOLDOWN * (0.5 + rng.random()) if jitter else COOLDOWN
                    heapq.heappush(pending, (t0 + wait, i))
        when = f"{closed_at / 1000:.2f} s" if closed_at else f"NEVER (>{HORIZON / 1000:.0f}s)"
        print(f"  {label:<20} {peak:^11d}  {bad:^11d}  {failed:^8d}    {when}")
    print("  the unjittered fleet re-kills its dependency once every cool-down,")
    print("  forever: the synchronised probe burst IS the outage. Jitter every")
    print("  periodic action - cool-downs, cron, TTLs, backoff, health checks -")
    print("  because correlation, not volume, is what turns 300 into an incident.")


# =========================================================================== #
# 7 - DEADLINE PROPAGATION
# =========================================================================== #
def section7() -> None:
    banner("7 . DEADLINE PROPAGATION: THE FLEET-LEVEL VERSION OF A TIMEOUT")
    HOPS, DEADLINE, HOP_TIMEOUT, SCALE, M = 3, 1000.0, 1000.0, 20.0, 80_000
    rng = random.Random(SEED + 7)
    work = sorted(min(draw_latency(rng) * SCALE, HOP_TIMEOUT) for _ in range(20_000))
    min_useful = pct(work, 0.50)
    print(f"  A -> B -> C. Each hop's own work ~ the same distribution x{SCALE:.0f} "
          f"(p50 {min_useful:.0f} ms).")
    print(f"  The user's deadline is {DEADLINE:.0f} ms, absolute, set when the "
          f"request is accepted.")
    print(f"  Independent mode: every hop starts its own {HOP_TIMEOUT:.0f} ms timeout "
          f"and knows nothing else.")
    print("  Propagated mode : the absolute deadline travels; each hop computes")
    print(f"                    remaining = deadline - now and refuses if remaining < "
          f"{min_useful:.0f} ms.\n")
    print("  mode          p50 total   p99 total   worst    late    wasted ms/req   "
          "refused early")
    worst_seen: dict[str, float] = {}
    for mode in ("independent", "propagated"):
        rng = random.Random(SEED + 70)
        totals, wasted_total, late = [], 0.0, 0
        refused = 0
        for _ in range(M):
            t, wasted, was_refused = 0.0, 0.0, False
            for _ in range(HOPS):
                w = min(draw_latency(rng) * SCALE, HOP_TIMEOUT)
                if mode == "propagated":
                    remaining = DEADLINE - t
                    if remaining < min_useful:
                        refused += 1
                        was_refused = True
                        break                       # fail fast, do no work
                    w = min(w, remaining)           # abandon at the deadline, not later
                start, end = t, t + w
                if end > DEADLINE:                  # service time spent after the
                    wasted += end - max(start, DEADLINE)   # caller stopped waiting
                t = end
            totals.append(t)
            wasted_total += wasted
            if t > DEADLINE:
                late += 1
            _ = was_refused
        totals.sort()
        worst_seen[mode] = totals[-1]
        print(f"  {mode:<12} {pct(totals, .50):9.0f}   {pct(totals, .99):9.0f}   "
              f"{totals[-1]:6.0f}  {late / M:6.1%}   {wasted_total / M:12.1f}   "
              f"{refused / M:12.1%}")
    print(f"\n  independent timeouts are bounded only by {HOPS} x {HOP_TIMEOUT:.0f} ms = "
          f"{HOPS * HOP_TIMEOUT:.0f} ms - three times the")
    print(f"  budget the user actually had; {M:,} requests reached "
          f"{worst_seen['independent']:.0f} ms. Propagated deadlines")
    print(f"  cannot exceed {DEADLINE:.0f} ms by construction, and the worst observed was "
          f"{worst_seen['propagated']:.0f} ms.")
    print("  A deadline is an ABSOLUTE TIME, not a duration: hop B must inherit what is")
    print("  LEFT, not restart the clock. Every millisecond in the wasted column is")
    print("  capacity spent on an answer nobody is waiting for - Phase 8's goodput")
    print("  problem, one network hop further out.")


def main() -> None:
    print("THE TAIL AT SCALE - fan-out arithmetic, hedging, and correlated failure")
    print(f"seed = {SEED}; all latencies in milliseconds; no network, no servers")
    pool_rng = random.Random(SEED)
    pool = sorted(draw_latency(pool_rng) for _ in range(200_000))
    single = section1(pool)
    delay = section2(pool, single)
    cluster_delay = section3()
    section4()
    section5(pool, delay)
    section6()
    section7()
    print()


if __name__ == "__main__":
    main()
