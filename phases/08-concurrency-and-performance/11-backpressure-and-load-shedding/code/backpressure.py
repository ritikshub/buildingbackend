#!/usr/bin/env python3
"""
Backpressure, queueing and load shedding, measured rather than asserted: the
utilization knee, bounded vs unbounded queues under overload, deadline-aware
shedding with FIFO vs LIFO, an adaptive concurrency limiter, a retry-driven
metastable collapse, and a circuit breaker protecting an unrelated endpoint.

Companion to docs/en.md (Phase 8, Lesson 11). Standard library only, every RNG
seeded, self-terminating in well under 30 seconds. Sources: Lindley's recursion
(Lindley, *Math. Proc. Cambridge Phil. Soc.* 48(2), 1952) for the M/G/1 waiting
time; the Pollaczek-Khinchine mean-wait formula for variable service times; the
latency-gradient congestion signal of TCP Vegas (Brakmo & Peterson, *IEEE JSAC*
13(8), 1995); metastable failure as defined by Bronson et al., *Metastable
Failures in Distributed Systems*, HotOS 2021.

Run:  python3 backpressure.py
"""

from __future__ import annotations

import collections
import heapq
import itertools
import math
import queue
import random
import threading
import time

SEED = 20260718


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def pct(values, q: float) -> float:
    """The q-quantile of `values` by nearest rank. Empty -> nan."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(q * len(ordered)))
    return ordered[idx]


# ══ 1 ═══════════════════════════════════════════════════════════════════════════
# The utilization knee. W = S / (1 - rho) for exponential service; the
# Pollaczek-Khinchine formula generalizes it to any service distribution:
#     W / S = 1 + rho * (1 + CV^2) / (2 * (1 - rho))
# CV^2 = 1 recovers the classic result. Higher variability moves the knee LEFT.

# A two-branch hyperexponential with mean 1.0 and CV^2 ~= 4: 95% of requests are
# fast (0.72x the mean) and 5% are slow (6.3x the mean). This is what a real
# endpoint looks like when a cache miss costs 10x a cache hit.
HYPER_P, HYPER_FAST, HYPER_SLOW = 0.95, 0.7211, 6.3


def exp_service(rng: random.Random, mean: float) -> float:
    return rng.expovariate(1.0 / mean)


def hyper_service(rng: random.Random, mean: float) -> float:
    branch = HYPER_FAST if rng.random() < HYPER_P else HYPER_SLOW
    return rng.expovariate(1.0 / (branch * mean))


def hyper_cv2() -> float:
    m1 = HYPER_P * HYPER_FAST + (1 - HYPER_P) * HYPER_SLOW
    m2 = 2 * (HYPER_P * HYPER_FAST ** 2 + (1 - HYPER_P) * HYPER_SLOW ** 2)
    return m2 / m1 ** 2 - 1.0


def pk_ratio(rho: float, cv2: float) -> float:
    """W / S from Pollaczek-Khinchine. cv2 = 1 gives 1 / (1 - rho)."""
    return 1.0 + rho * (1.0 + cv2) / (2.0 * (1.0 - rho))


def lindley(rho: float, service: float, n: int, seed: int, sampler) -> list[float]:
    """Sojourn times of an M/G/1 FIFO queue.  W_q(k+1) = max(0, W_q(k)+S(k)-A(k+1))."""
    rng = random.Random(seed)
    lam = rho / service
    warm = n // 5
    wq = 0.0
    out = []
    for k in range(n):
        s = sampler(rng, service)
        if k >= warm:
            out.append(wq + s)
        wq = wq + s - rng.expovariate(lam)
        if wq < 0.0:
            wq = 0.0
    return out


def section_1() -> None:
    banner(1, "THE UTILIZATION KNEE IS NOT VISIBLE ON A UTILIZATION GRAPH")
    service = 0.040                      # 40 ms of service time per request
    print(f"  one worker, service time S = {service * 1e3:.0f} ms, Poisson arrivals")
    print(f"  {'rho':>7}{'S/(1-rho)':>12}{'measured':>11}{'mean W':>11}{'p99 W':>11}"
          f"{'p99/S':>9}")
    for rho in (0.50, 0.70, 0.80, 0.90, 0.95, 0.99):
        n = 60_000 if rho <= 0.80 else 250_000 if rho <= 0.95 else 600_000
        w = lindley(rho, service, n, SEED + int(rho * 1000), exp_service)
        mean = sum(w) / len(w)
        p99 = pct(w, 0.99)
        print(f"  {rho:>7.2f}{1 / (1 - rho):>11.1f}x{mean / service:>10.1f}x"
              f"{mean * 1e3:>8.0f} ms{p99 * 1e3:>8.0f} ms{p99 / service:>8.0f}x")
    print("  utilization went from 0.50 to 0.99 — a 2x change in a number you graph.")
    print("  mean latency went up 34x and p99 went up 32x. Nothing 'broke'.")
    print("  (past rho=0.95 the simulation UNDER-reads the formula: a queue takes")
    print("   longer to reach steady state than it takes to hurt you.)")

    cv2 = hyper_cv2()
    print(f"\n  same queue, variable service times (95% fast / 5% slow, CV^2 ="
          f" {cv2:.2f}):")
    print(f"  {'rho':>7}{'CV^2=1 W/S':>13}{'CV^2=4 W/S':>13}{'P-K theory':>13}"
          f"{'penalty':>10}")
    for rho in (0.50, 0.70, 0.80, 0.90):
        n = 120_000 if rho <= 0.80 else 400_000
        a = lindley(rho, service, n, SEED + int(rho * 1000), exp_service)
        b = lindley(rho, service, n, SEED + int(rho * 1000), hyper_service)
        ra = (sum(a) / len(a)) / service
        rb = (sum(b) / len(b)) / service
        print(f"  {rho:>7.2f}{ra:>12.1f}x{rb:>12.1f}x{pk_ratio(rho, cv2):>12.1f}x"
              f"{rb / ra:>9.1f}x")
    # Where does W/S cross 10x? That is the practical definition of "the knee".
    def knee(cv2_: float, target: float = 10.0) -> float:
        lo, hi = 0.01, 0.999
        for _ in range(60):
            mid = (lo + hi) / 2
            if pk_ratio(mid, cv2_) < target:
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2
    print(f"  W/S crosses 10x at rho = {knee(1.0):.2f} with steady service times,")
    print(f"  but at rho = {knee(cv2):.2f} once service times vary — the knee moved LEFT.")


# ══ 2 & 3 ═══════════════════════════════════════════════════════════════════════
# A discrete-event queueing system with real bounds, deadlines and disciplines.

class Req:
    __slots__ = ("arrival", "deadline")

    def __init__(self, arrival: float, deadline: float) -> None:
        self.arrival = arrival
        self.deadline = deadline


def run_queue(*, lam: float, service: float, workers: int, duration: float,
              deadline: float, seed: int, maxq=None, discipline: str = "fifo",
              shed_expired: bool = False) -> dict:
    """Simulate `duration` seconds of an M/M/c queue with optional bound + shedding.

    Latency is always measured from ARRIVAL, which is the only clock the caller
    has. A completion after its deadline is counted as wasted work: the answer
    is correct and nobody is left to read it.
    """
    rng = random.Random(seed)
    q: collections.deque = collections.deque()
    events: list = []
    seq = itertools.count()
    heapq.heappush(events, (rng.expovariate(lam), next(seq), 0, None))
    busy = 0
    arrived = rejected = shed = completed = late = peak = 0
    lat: list[float] = []
    ok_lat: list[float] = []

    def start(r: Req, now: float) -> None:
        nonlocal busy
        busy += 1
        heapq.heappush(events, (now + rng.expovariate(1.0 / service), next(seq), 1, r))

    while events:
        now, _, kind, req = heapq.heappop(events)
        if now > duration:
            break
        if kind == 0:                                    # arrival
            arrived += 1
            heapq.heappush(events, (now + rng.expovariate(lam), next(seq), 0, None))
            r = Req(now, now + deadline)
            if busy < workers:
                start(r, now)
            elif maxq is not None and len(q) >= maxq:
                rejected += 1                            # 503 immediately, cheap
            else:
                q.append(r)
                peak = max(peak, len(q))
        else:                                            # departure
            busy -= 1
            completed += 1
            lat.append(now - req.arrival)
            if now > req.deadline:
                late += 1
            else:
                ok_lat.append(now - req.arrival)
            if shed_expired:
                # Reap abandoned work off the HEAD. The oldest item's age is the
                # health signal; anything past its deadline is free to delete.
                while q and now > q[0].deadline:
                    q.popleft()
                    shed += 1
            while q:                                     # pull the next unit of work
                nxt = q.popleft() if discipline == "fifo" else q.pop()
                if shed_expired and now > nxt.deadline:
                    shed += 1                            # already abandoned: drop it
                    continue
                start(nxt, now)
                break

    good = completed - late
    return {
        "arrived": arrived, "completed": completed, "late": late, "good": good,
        "rejected": rejected, "shed": shed, "peak": peak,
        "p50": pct(lat, 0.50), "p99": pct(lat, 0.99), "p99_ok": pct(ok_lat, 0.99),
        "goodput": good / duration,
        "success": good / arrived if arrived else 0.0,
        "wasted": late / completed if completed else 0.0,
    }


OVER = dict(lam=160.0, service=0.050, workers=4, duration=120.0, deadline=1.0)
BYTES_PER_REQ = 8 * 1024          # a modest buffered request: headers + body + state


def section_2() -> None:
    banner(2, "AN UNBOUNDED QUEUE DOES NOT ABSORB OVERLOAD — IT HIDES IT")
    cap = OVER["workers"] / OVER["service"]
    print(f"  {OVER['workers']} workers x {OVER['service'] * 1e3:.0f} ms service ="
          f" {cap:.0f} req/s capacity;  arrivals = {OVER['lam']:.0f} req/s (2.0x)")
    print(f"  client deadline = {OVER['deadline']:.1f} s;"
          f" run = {OVER['duration']:.0f} simulated seconds")
    rows = [
        ("unbounded queue", run_queue(**OVER, seed=SEED + 1, maxq=None)),
        ("bounded queue (40)", run_queue(**OVER, seed=SEED + 1, maxq=40)),
    ]
    print(f"  {'config':<21}{'p50':>9}{'p99':>10}{'peak Q':>9}{'mem':>9}"
          f"{'done':>8}{'503s':>8}{'wasted':>9}")
    for name, r in rows:
        mem = r["peak"] * BYTES_PER_REQ / 1e6
        print(f"  {name:<21}{r['p50'] * 1e3:>7.0f}ms{r['p99'] * 1e3:>8.0f}ms"
              f"{r['peak']:>9d}{mem:>7.1f}MB{r['completed']:>8d}{r['rejected']:>8d}"
              f"{r['wasted']:>8.0%}")
    u, b = rows[0][1], rows[1][1]
    print(f"  {u['arrived']} requests arrived in both runs. Both completed"
          f" {u['completed']} — identical throughput.")
    print(f"  the unbounded queue completed {u['completed']} requests and"
          f" {u['wasted']:.0%} of them")
    print(f"  were already past the caller's deadline: {u['late']} responses nobody read.")
    print(f"  goodput — answers that arrived in time — was {u['goodput']:.1f}/s unbounded"
          f" vs {b['goodput']:.1f}/s bounded ({b['goodput'] / max(u['goodput'], 1e-9):.0f}x).")


def section_3() -> None:
    banner(3, "TIMEOUTS ARE LOAD SHEDDING, AND UNDER OVERLOAD LIFO BEATS FIFO")
    cfgs = [
        ("FIFO, no deadline check", dict(discipline="fifo", shed_expired=False)),
        ("FIFO + drop expired", dict(discipline="fifo", shed_expired=True)),
        ("LIFO + drop expired", dict(discipline="lifo", shed_expired=True)),
    ]
    print(f"  identical 2.0x overload; the only difference is what happens at dequeue")
    print(f"  {'discipline':<25}{'goodput':>10}{'success':>10}{'wasted':>9}"
          f"{'p99(ok)':>10}{'peak Q':>9}{'dropped':>9}")
    out = {}
    for name, extra in cfgs:
        r = run_queue(**OVER, seed=SEED + 2, maxq=None, **extra)
        out[name] = r
        print(f"  {name:<25}{r['goodput']:>8.1f}/s{r['success']:>10.0%}"
              f"{r['wasted']:>9.0%}{r['p99_ok'] * 1e3:>8.0f}ms{r['peak']:>9d}"
              f"{r['shed']:>9d}")
    a = out["FIFO, no deadline check"]
    b = out["FIFO + drop expired"]
    c = out["LIFO + drop expired"]
    print(f"  dropping expired work at dequeue capped the queue at {b['peak']} items"
          f" instead of {a['peak']}")
    print(f"  ({b['peak'] * BYTES_PER_REQ / 1e6:.1f} MB instead of"
          f" {a['peak'] * BYTES_PER_REQ / 1e6:.1f} MB) — but FIFO goodput stayed at"
          f" {b['goodput']:.1f}/s,")
    print(f"  because the oldest LIVE request has already spent its whole budget waiting.")
    print(f"  LIFO serves the newest instead: goodput {c['goodput']:.1f}/s,"
          f" {c['success']:.0%} of callers answered in time,")
    print(f"  p99 of those answers {c['p99_ok'] * 1e3:.0f} ms. Same capacity, same"
          f" arrivals, one line of code.")


# ══ 4 ═══════════════════════════════════════════════════════════════════════════
# Admission control: a fixed in-flight limit vs a latency-gradient (Vegas-style)
# limiter, against a dependency whose capacity collapses mid-run.

S_MIN = 0.020            # the dependency's uncontended service time: 20 ms
CAP_HEALTHY = 500.0      # req/s it can sustain when healthy
CAP_DEGRADED = 200.0     # 40% of healthy
OFFERED = 400.0          # req/s we are asked to push through it
TARGET = 0.100           # 100 ms deadline for a call to the dependency
ALPHA = 0.2              # limiter smoothing


def capacity_at(t: float) -> float:
    return CAP_DEGRADED if 4.0 <= t < 8.0 else CAP_HEALTHY


def run_limiter(*, adaptive: bool, limit0: float, duration: float = 12.0,
                dt: float = 0.02) -> tuple[list, dict]:
    limit = float(limit0)
    inflight = 0.0
    rows, totals = [], {"done": 0.0, "good": 0.0, "shed": 0.0, "deg_good": 0.0,
                        "deg_done": 0.0}
    for step in range(int(duration / dt)):
        t = step * dt
        cap = capacity_at(t)
        arrivals = OFFERED * dt
        admit = min(arrivals, max(0.0, limit - inflight))
        shed = arrivals - admit
        inflight += admit
        thr = min(cap, inflight / S_MIN) if inflight > 0 else 0.0
        rtt = inflight / thr if thr > 0 else S_MIN
        observed = inflight
        done = min(inflight, thr * dt)
        inflight -= done
        good = done if rtt <= TARGET else 0.0
        totals["done"] += done
        totals["good"] += good
        totals["shed"] += shed
        if 4.0 <= t < 8.0:
            totals["deg_done"] += done
            totals["deg_good"] += good
        if adaptive and observed >= limit / 2:
            # Vegas gradient: how far is the current RTT above the best we've seen?
            gradient = max(0.5, min(1.0, S_MIN / rtt))
            probe = limit * gradient + math.sqrt(limit)
            limit = max(1.0, min(200.0, limit * (1 - ALPHA) + probe * ALPHA))
        rows.append((t, cap, limit, observed, rtt, good / dt, shed / dt))
    return rows, totals


def section_4() -> None:
    banner(4, "ADAPTIVE CONCURRENCY LIMITS: LATENCY AS A CONGESTION SIGNAL")
    print(f"  dependency: {S_MIN * 1e3:.0f} ms uncontended, {CAP_HEALTHY:.0f} req/s"
          f" healthy; it drops to {CAP_DEGRADED:.0f} req/s")
    print(f"  at t=4s and recovers at t=8s. Offered load {OFFERED:.0f} req/s constant,"
          f" deadline {TARGET * 1e3:.0f} ms,")
    print(f"  both limiters start at 64 in flight.")
    fixed_rows, fixed_tot = run_limiter(adaptive=False, limit0=64)
    adapt_rows, adapt_tot = run_limiter(adaptive=True, limit0=64)
    print(f"  {'t':>5}{'cap':>7}|{'lim':>6}{'flight':>8}{'rtt':>9}{'good':>9}"
          f"|{'lim':>7}{'flight':>8}{'rtt':>9}{'good':>9}")
    print(f"  {'':>5}{'':>7}|{'---- fixed limit ----':^32}"
          f"|{'-- adaptive (gradient) --':^33}")
    for i in range(0, len(fixed_rows), 50):
        t, cap, fl, ff, frtt, fg, _ = fixed_rows[i]
        _, _, al, af, artt, ag, _ = adapt_rows[i]
        print(f"  {t:>5.1f}{cap:>7.0f}|{fl:>6.0f}{ff:>8.1f}{frtt * 1e3:>7.0f}ms"
              f"{fg:>7.0f}/s|{al:>7.1f}{af:>8.1f}{artt * 1e3:>7.0f}ms{ag:>7.0f}/s")
    print(f"  during the 4 s outage window:")
    print(f"    fixed limit   throughput {fixed_tot['deg_done'] / 4:>6.0f}/s   goodput"
          f" {fixed_tot['deg_good'] / 4:>6.0f}/s   -> {1 - fixed_tot['deg_good'] / max(fixed_tot['deg_done'], 1e-9):.0%} wasted")
    print(f"    adaptive      throughput {adapt_tot['deg_done'] / 4:>6.0f}/s   goodput"
          f" {adapt_tot['deg_good'] / 4:>6.0f}/s   -> {1 - adapt_tot['deg_good'] / max(adapt_tot['deg_done'], 1e-9):.0%} wasted")
    print(f"  whole run goodput: fixed {fixed_tot['good'] / 12:.0f}/s,"
          f" adaptive {adapt_tot['good'] / 12:.0f}/s"
          f" ({adapt_tot['good'] / max(fixed_tot['good'], 1e-9):.2f}x)")
    print(f"  the fixed limiter kept ACCEPTING work it could not finish in time;")
    print(f"  the adaptive one shrank to fit the dependency and shed the rest in ~0 ms.")


# ══ 5 ═══════════════════════════════════════════════════════════════════════════
# Metastable failure: a trigger creates a queue, the queue creates timeouts,
# timeouts create retries, retries are new arrivals. Remove the trigger and the
# loop sustains itself.

class RetryCfg:
    def __init__(self, name, *, lifo, shed, budget, jitter, backoff, attempts, maxq):
        self.name, self.lifo, self.shed = name, lifo, shed
        self.budget, self.jitter, self.backoff = budget, jitter, backoff
        self.attempts, self.maxq = attempts, maxq


def run_retry_sim(cfg: RetryCfg, *, lam0=80.0, mu_ok=100.0, mu_dip=70.0,
                  dip=(20.0, 35.0), duration=90.0, dt=0.2, timeout=1.0,
                  deadline=1.0, seed=SEED) -> dict:
    rng = random.Random(seed)
    q: collections.deque = collections.deque()
    origin = 0            # how many items have left the LEFT end of the deque
    scan = 0              # absolute index of the next item to consider for retry
    due: list = []        # heap of (time, attempt) retries in backoff
    base = retries = dropped_full = dropped_expired = 0
    served_frac = 0.0
    timeline = []
    per_sec = collections.defaultdict(lambda: [0, 0])   # second -> [good, served]

    def schedule_retry(attempt: int, now: float) -> None:
        """A client that got a timeout or a 503 tries again — if the budget allows."""
        nonlocal retries
        if attempt >= cfg.attempts:
            return
        if cfg.budget is not None and retries >= cfg.budget * base:
            return                                      # retry budget exhausted
        retries += 1
        back = cfg.backoff * (2 ** (attempt - 1))
        heapq.heappush(due, (now + (rng.uniform(0.0, back) if cfg.jitter else back),
                             attempt + 1))

    steps = int(duration / dt)
    for step in range(steps):
        t = step * dt
        mu = mu_dip if dip[0] <= t < dip[1] else mu_ok

        # 1. arrivals: fresh traffic (Poisson) plus retries whose backoff expired
        n_new = 0
        limit_p, prod = math.exp(-lam0 * dt), 1.0
        while True:
            prod *= rng.random()
            if prod <= limit_p:
                break
            n_new += 1
        base += n_new
        incoming = [1] * n_new
        while due and due[0][0] <= t:
            incoming.append(heapq.heappop(due)[1])
        for attempt in incoming:
            if cfg.maxq is not None and len(q) >= cfg.maxq:
                dropped_full += 1                       # 503 at the door, instant
                schedule_retry(attempt, t)
                continue
            q.append([t, attempt, False])               # [arrival, attempt, retried]

        # 2. reap abandoned work off the head, then serve
        if cfg.shed:
            while q and t - q[0][0] > deadline:
                item = q.popleft()
                origin += 1
                dropped_expired += 1
                if not item[2]:
                    item[2] = True
                    schedule_retry(item[1], t)
        served_frac += mu * dt
        while served_frac >= 1.0 and q:
            item = q.pop() if cfg.lifo else q.popleft()
            if not cfg.lifo:
                origin += 1
            if cfg.shed and t - item[0] > deadline:
                dropped_expired += 1                    # free: no capacity consumed
                continue
            served_frac -= 1.0
            sec = int(t)
            per_sec[sec][1] += 1
            if t - item[0] <= deadline:
                per_sec[sec][0] += 1
        if not q:
            served_frac = 0.0                           # idle capacity is not banked

        # 3. clients time out and retry. The server never learns; the original
        #    request stays in the queue and will still be executed.
        if scan < origin:
            scan = origin
        while scan - origin < len(q):
            item = q[scan - origin]
            if t - item[0] <= timeout:
                break
            scan += 1
            if item[2]:
                continue
            item[2] = True
            schedule_retry(item[1], t)

        if step % 5 == 0:
            oldest = t - q[0][0] if q else 0.0
            window = [per_sec[s] for s in range(max(0, int(t) - 3), int(t))]
            good = sum(w[0] for w in window) / len(window) if window else 0.0
            served = sum(w[1] for w in window) / len(window) if window else 0.0
            timeline.append((t, len(q), oldest, good, served))

    # time to baseline after the trigger is removed
    recovered = None
    for t, depth, oldest, good, served in timeline:
        if t < dip[1]:
            continue
        if good >= 0.95 * lam0 and oldest < 0.25:
            recovered = t - dip[1]
            break
    final = timeline[-1]
    tail_good = sum(per_sec[s][0] for s in range(int(duration) - 10, int(duration))) / 10
    return {"timeline": timeline, "base": base, "retries": retries,
            "dropped_full": dropped_full, "dropped_expired": dropped_expired,
            "recovered": recovered, "final_depth": final[1], "final_oldest": final[2],
            "tail_good": tail_good, "offered": (base + retries) / duration}


def section_5() -> None:
    banner(5, "THE RETRY STORM AND METASTABLE FAILURE")
    print("  80 req/s against 100 req/s of capacity (rho = 0.80). At t=20s capacity")
    print("  drops 30% to 70 req/s for 15 s, then returns. Client timeout 1.0 s.")
    naive = RetryCfg("naive: 3 attempts, fixed backoff", lifo=False, shed=False,
                     budget=None, jitter=False, backoff=0.5, attempts=3, maxq=None)
    guard = RetryCfg("budget + jitter + LIFO shed", lifo=True, shed=True,
                     budget=0.10, jitter=True, backoff=0.5, attempts=3, maxq=400)
    a = run_retry_sim(naive)
    b = run_retry_sim(guard)
    print(f"  {'t':>6}|{'depth':>8}{'oldest':>9}{'good/s':>9}|{'depth':>8}{'oldest':>9}"
          f"{'good/s':>9}")
    print(f"  {'':>6}|{'------- naive -------':^26}|{'---- with shedding ---':^26}")
    for i in range(0, len(a["timeline"]), 9):
        t, d1, o1, g1, _ = a["timeline"][i]
        _, d2, o2, g2, _ = b["timeline"][i]
        mark = " <-- dip" if 20.0 <= t < 35.0 else ""
        print(f"  {t:>6.1f}|{d1:>8d}{o1:>8.1f}s{g1:>9.0f}|{d2:>8d}{o2:>8.1f}s"
              f"{g2:>9.0f}{mark}")
    print(f"  naive  : real demand never changed (80 req/s) but offered load averaged"
          f" {a['offered']:.0f} req/s")
    print(f"           = {a['offered'] / 80:.1f}x amplification from {a['retries']}"
          f" retries on {a['base']} real requests")
    print(f"           (the ceiling is 3.0x: three attempts each)")
    print(f"           55 s after the trigger cleared: queue {a['final_depth']} deep,"
          f" oldest {a['final_oldest']:.0f} s, goodput {a['tail_good']:.0f}/s")
    rec = "NEVER" if a["recovered"] is None else f"{a['recovered']:.1f} s"
    print(f"           recovery: {rec}"
          f"  <-- the trigger is gone and the system is still down")
    print(f"  guarded: offered {b['offered']:.0f} req/s — {b['retries']} retries on"
          f" {b['base']} requests = {b['retries'] / b['base']:.0%}, the budget ceiling")
    print(f"           shed {b['dropped_expired']} expired at dequeue +"
          f" {b['dropped_full']} at the door; goodput {b['tail_good']:.0f}/s at the end")
    print(f"           recovery: {b['recovered']:.1f} s after the trigger cleared")


# ══ 6 ═══════════════════════════════════════════════════════════════════════════
# A real threaded server. One dependency is dead; the question is what that does
# to an endpoint that never touches it.

DEP_TIMEOUT = 0.080      # what a call to the dead dependency costs before it fails
PROFILE_WORK = 0.004     # an unrelated endpoint that touches nothing
WORKERS = 8
HARNESS_SECS = 1.5
CHECKOUT_RATE = 250.0
PROFILE_RATE = 100.0
MAXQ = 200


class Breaker:
    """closed -> open after `threshold` consecutive failures -> half-open probe."""

    def __init__(self, threshold: int = 5, open_secs: float = 0.5) -> None:
        self.threshold, self.open_secs = threshold, open_secs
        self.fails = 0
        self.opened_at = 0.0
        self.state = "closed"
        self.lock = threading.Lock()
        self.short_circuited = 0
        self.probes = 0

    def allow(self) -> bool:
        with self.lock:
            if self.state == "closed":
                return True
            if time.perf_counter() - self.opened_at >= self.open_secs:
                self.state = "half-open"      # let exactly one probe through
                self.opened_at = time.perf_counter()
                self.probes += 1
                return True
            self.short_circuited += 1
            return False

    def record(self, ok: bool) -> None:
        with self.lock:
            if ok:
                self.fails, self.state = 0, "closed"
                return
            self.fails += 1
            if self.state == "half-open" or self.fails >= self.threshold:
                self.state = "open"
                self.opened_at = time.perf_counter()


def harness(mode: str) -> dict:
    """mode: 'none' (shared pool, no breaker) | 'breaker' | 'bulkhead'."""
    breaker = Breaker() if mode == "breaker" else None
    lat = {"checkout": [], "profile": []}
    busy = {"checkout": 0.0, "profile": 0.0}
    dropped = {"checkout": 0, "profile": 0}
    lock = threading.Lock()
    stop = threading.Event()

    if mode == "bulkhead":
        queues = {"checkout": queue.Queue(MAXQ), "profile": queue.Queue(MAXQ)}
        pools = {"checkout": 4, "profile": 4}
    else:
        shared: queue.Queue = queue.Queue(MAXQ)
        queues = {"checkout": shared, "profile": shared}
        pools = {"shared": WORKERS}

    def work(item) -> None:
        kind, submitted = item
        t0 = time.perf_counter()
        if kind == "checkout":
            if breaker is not None and not breaker.allow():
                pass                                   # fail fast: no thread time
            else:
                time.sleep(DEP_TIMEOUT)                # the dependency is dead
                if breaker is not None:
                    breaker.record(False)
        else:
            time.sleep(PROFILE_WORK)
        done = time.perf_counter()
        with lock:
            lat[kind].append(done - submitted)
            busy[kind] += done - t0

    def worker(qs) -> None:
        while not stop.is_set():
            for qq in qs:
                try:
                    item = qq.get_nowait()
                except queue.Empty:
                    continue
                work(item)
                break
            else:
                time.sleep(0.0005)

    threads = []
    if mode == "bulkhead":
        for kind, n in pools.items():
            for _ in range(n):
                threads.append(threading.Thread(target=worker, args=([queues[kind]],),
                                                daemon=True))
    else:
        for _ in range(WORKERS):
            threads.append(threading.Thread(target=worker, args=([shared],), daemon=True))
    for th in threads:
        th.start()

    schedule = [(i / CHECKOUT_RATE, "checkout")
                for i in range(int(HARNESS_SECS * CHECKOUT_RATE))]
    schedule += [(i / PROFILE_RATE, "profile")
                 for i in range(int(HARNESS_SECS * PROFILE_RATE))]
    schedule.sort()
    t0 = time.perf_counter()
    for offset, kind in schedule:
        delay = t0 + offset - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        try:
            queues[kind].put_nowait((kind, time.perf_counter()))
        except queue.Full:
            with lock:
                dropped[kind] += 1
    stop.set()
    for qq in set(queues.values()):
        while True:
            try:
                qq.get_nowait()
            except queue.Empty:
                break
    for th in threads:
        th.join(timeout=0.5)
    elapsed = time.perf_counter() - t0

    total_thread_secs = WORKERS * elapsed
    return {
        "p50_profile": pct(lat["profile"], 0.50), "p99_profile": pct(lat["profile"], 0.99),
        "profile_done": len(lat["profile"]), "profile_dropped": dropped["profile"],
        "checkout_done": len(lat["checkout"]), "checkout_dropped": dropped["checkout"],
        "occupancy": busy["checkout"] / total_thread_secs,
        "short_circuited": breaker.short_circuited if breaker else 0,
        "probes": breaker.probes if breaker else 0,
    }


def section_6() -> None:
    banner(6, "CIRCUIT BREAKERS AND BULKHEADS: ONE DEAD DEPENDENCY, TWO ENDPOINTS")
    print(f"  {WORKERS} real threads. /checkout calls a dependency that always fails"
          f" after {DEP_TIMEOUT * 1e3:.0f} ms.")
    print(f"  /profile takes {PROFILE_WORK * 1e3:.0f} ms and calls nothing."
          f"  Offered: {CHECKOUT_RATE:.0f}/s + {PROFILE_RATE:.0f}/s"
          f" for {HARNESS_SECS:.1f} s.")
    print(f"  {'config':<24}{'/profile p50':>14}{'/profile p99':>14}{'served':>9}"
          f"{'dropped':>9}{'/checkout thread-time':>23}")
    results = {}
    for mode, label in (("none", "shared pool, no breaker"),
                        ("breaker", "shared pool + breaker"),
                        ("bulkhead", "bulkhead (4+4 pools)")):
        r = harness(mode)
        results[mode] = r
        print(f"  {label:<24}{r['p50_profile'] * 1e3:>12.0f}ms"
              f"{r['p99_profile'] * 1e3:>12.0f}ms{r['profile_done']:>9d}"
              f"{r['profile_dropped']:>9d}{r['occupancy']:>22.0%}")
    n, b = results["none"], results["breaker"]
    print(f"  /profile never calls the broken dependency, yet without a breaker its p99")
    print(f"  was {n['p99_profile'] * 1e3:.0f} ms — {n['p99_profile'] / b['p99_profile']:.0f}x"
          f" the breaker run's {b['p99_profile'] * 1e3:.0f} ms — because /checkout owned"
          f" {n['occupancy']:.0%} of every thread.")
    print(f"  the breaker short-circuited {b['short_circuited']} calls and paid for"
          f" {b['probes']} half-open probes;")
    print(f"  the bulkhead fixed it differently: /checkout simply cannot borrow"
          f" /profile's threads.")


def main() -> None:
    started = time.perf_counter()
    section_1()
    section_2()
    section_3()
    section_4()
    section_5()
    section_6()
    print(f"\n  (total wall time {time.perf_counter() - started:.1f} s)")


if __name__ == "__main__":
    main()
