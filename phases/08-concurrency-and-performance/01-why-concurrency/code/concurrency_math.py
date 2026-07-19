#!/usr/bin/env python3
"""
The arithmetic of concurrency: latency, throughput, Little's Law, the utilization
knee, Amdahl's Law and the Universal Scalability Law — measured, not asserted.

Companion to docs/en.md (Phase 8, Lesson 01). Standard library only, every RNG
seeded, self-terminating in well under 30 seconds. The queueing results are
CONFIRMED by discrete-event simulation rather than quoted: Little's Law
(L = lambda x W, Little, *Operations Research* 9(3), 1961) and the M/M/1 sojourn
time S/(1-rho) both fall out of a simulated queue. Amdahl's ceiling is from
Amdahl, *AFIPS Conf. Proc.* 30, 1967; the Universal Scalability Law is Gunther,
*Guerrilla Capacity Planning*, Springer 2007.

Run:  python3 concurrency_math.py
"""

from __future__ import annotations

import heapq
import math
import random
import time
from concurrent.futures import ThreadPoolExecutor

SEED = 20260718

# ─── The workload under study: one typical API request ────────────────────────
# 5 ms of CPU split across three phases, 195 ms of waiting split across two
# downstream calls. This is an ordinary read endpoint, not a pathological one.
CPU_WORK = (0.0025, 0.0015, 0.0010)   # parse+authorize, shape rows, serialize
IO_WAIT = (0.120, 0.075)              # database query 120 ms, payments API 75 ms
CORES = 16                            # the machine you are paying for

CPU_PER_REQ = sum(CPU_WORK)           # 0.005 s
WAIT_PER_REQ = sum(IO_WAIT)           # 0.195 s
LATENCY = CPU_PER_REQ + WAIT_PER_REQ  # 0.200 s


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def burn(seconds: float) -> None:
    """Occupy a CPU for `seconds` of *thread* CPU time — real work, not a sleep.

    thread_time() is per-thread CPU, so this burns the same amount of CPU whether
    or not another thread is contending for the interpreter lock.
    """
    end = time.thread_time() + seconds
    while time.thread_time() < end:
        pass


def handle_request() -> None:
    """One request: three bursts of CPU separated by two blocking waits."""
    burn(CPU_WORK[0])
    time.sleep(IO_WAIT[0])            # blocked on the database
    burn(CPU_WORK[1])
    time.sleep(IO_WAIT[1])            # blocked on the payments API
    burn(CPU_WORK[2])


def human_time(seconds: float) -> str:
    """Render a duration the way a person would say it out loud."""
    if seconds < 90:
        return f"{seconds:.0f} second" + ("" if seconds == 1 else "s")
    if seconds < 5400:
        return f"{seconds / 60:.1f} minutes"
    if seconds < 86_400:
        return f"{seconds / 3600:.1f} hours"
    if seconds < 63_072_000:
        return f"{seconds / 86400:.1f} days"
    return f"{seconds / 31_557_600:.1f} years"


# ══ 1 ═══════════════════════════════════════════════════════════════════════════

# (operation, real cost in seconds). Orders of magnitude, not vendor benchmarks.
LATENCY_LADDER = [
    ("L1 cache reference",        1e-9),
    ("L2 cache reference",        4e-9),
    ("main memory reference",     100e-9),
    ("NVMe SSD random read",      100e-6),
    ("same-datacenter round trip", 500e-6),
    ("cross-region round trip",   100e-3),
]


def section_1() -> None:
    banner(1, "WHERE THE TIME ACTUALLY GOES")
    print(f"  one request = {CPU_PER_REQ * 1e3:.1f} ms CPU + {WAIT_PER_REQ * 1e3:.1f} ms waiting"
          f" = {LATENCY * 1e3:.1f} ms  ({CPU_PER_REQ / LATENCY:.1%} CPU, "
          f"{WAIT_PER_REQ / LATENCY:.1%} idle)")

    n = 6
    t0, c0 = time.perf_counter(), time.process_time()
    for _ in range(n):
        handle_request()
    wall_ser, cpu_ser = time.perf_counter() - t0, time.process_time() - c0

    t0, c0 = time.perf_counter(), time.process_time()
    with ThreadPoolExecutor(max_workers=n) as pool:
        list(pool.map(lambda _: handle_request(), range(n)))
    wall_con, cpu_con = time.perf_counter() - t0, time.process_time() - c0

    print(f"  {n} requests, ONE at a time : wall {wall_ser:6.3f} s  cpu {cpu_ser:5.3f} s"
          f"  -> {n / wall_ser:6.2f} req/s")
    print(f"      CPU busy {cpu_ser / wall_ser:6.2%} of one core"
          f" = {cpu_ser / wall_ser / CORES:6.3%} of a {CORES}-core machine")
    print(f"  {n} requests, {n} IN FLIGHT   : wall {wall_con:6.3f} s  cpu {cpu_con:5.3f} s"
          f"  -> {n / wall_con:6.2f} req/s   ({wall_ser / wall_con:.1f}x)")
    print(f"      same work, same CPU, {wall_ser - wall_con:.2f} s of waiting overlapped away")

    print(f"\n  projection: N requests in flight, each {LATENCY * 1e3:.0f} ms with"
          f" {CPU_PER_REQ * 1e3:.0f} ms of CPU")
    print(f"  {'in flight N':>12}  {'throughput':>12}  {'latency':>9}  {'cores busy':>11}"
          f"  {'% of ' + str(CORES):>10}")
    ceiling = int(CORES / CPU_PER_REQ)                # requests/s the CPU can retire
    for in_flight in (1, 8, 64, 256, int(ceiling * LATENCY), int(ceiling * LATENCY * 2)):
        thru = min(in_flight / LATENCY, ceiling)
        cores = thru * CPU_PER_REQ
        note = ("  <- CPU saturated: past here N only adds queueing"
                if in_flight > ceiling * LATENCY else
                "  <- CPU saturated" if cores >= CORES - 1e-9 else "")
        print(f"  {in_flight:>12}  {thru:>10.1f}/s  {in_flight / thru * 1e3:>6.0f} ms"
              f"  {cores:>11.3f}  {cores / CORES:>10.1%}{note}")
    print(f"  the CPU ceiling is {CORES} cores / {CPU_PER_REQ * 1e3:.0f} ms = {ceiling} req/s,")
    print(f"  and reaching it needs L = {ceiling}/s x {LATENCY:.3f} s = "
          f"{int(ceiling * LATENCY)} requests in flight (Little's Law, section 3)")

    print("\n  why waiting dominates — the same clock, scaled so L1 = 1 second")
    print(f"  {'operation':<28}{'real':>12}   {'if L1 took 1 second':>22}")
    for name, secs in LATENCY_LADDER:
        real = (f"{secs * 1e9:.0f} ns" if secs < 1e-6
                else f"{secs * 1e6:.0f} us" if secs < 1e-3
                else f"{secs * 1e3:.0f} ms")
        print(f"  {name:<28}{real:>12}   {human_time(secs / 1e-9):>22}")
    ratio = LATENCY_LADDER[-1][1] / LATENCY_LADDER[0][1]
    print(f"  a cross-region round trip costs {ratio:,.0f}x an L1 hit. You do not")
    print("  optimize your way past that. You overlap it with other work.")


# ══ 2 ═══════════════════════════════════════════════════════════════════════════

def simulate_mmc(lam: float, mu: float, c: int, n: int, seed: int):
    """FCFS M/M/c queue. Poisson arrivals at `lam`, exponential service at `mu`.

    Returns (throughput, W_mean, L_time_average, utilization) — all *measured*
    from the simulated trace, so L = lam x W is a result, not an input.
    """
    rng = random.Random(seed)
    free = [0.0] * c                  # min-heap of per-server next-free times
    heapq.heapify(free)
    clock = 0.0
    arrivals: list[float] = []
    departures: list[float] = []
    busy = 0.0
    for _ in range(n):
        clock += rng.expovariate(lam)
        earliest = heapq.heappop(free)
        start = clock if clock > earliest else earliest
        svc = rng.expovariate(mu)
        done = start + svc
        heapq.heappush(free, done)
        arrivals.append(clock)
        departures.append(done)
        busy += svc

    span_start, span_end = arrivals[0], max(departures)
    horizon = span_end - span_start

    # Time-average number in system: integrate n(t) over the whole run.
    events = [(t, 1) for t in arrivals]
    events += [(t, -1) for t in departures]
    events.sort()
    area, level, prev = 0.0, 0, span_start
    for t, delta in events:
        area += level * (t - prev)
        prev = t
        level += delta

    w_mean = sum(d - a for a, d in zip(arrivals, departures)) / n
    return n / horizon, w_mean, area / horizon, busy / (c * horizon)


# (label, worker count, mean service time in seconds)
CONFIGS = [
    ("A  1 worker  x 10 ms", 1, 0.010),
    ("B 20 workers x 40 ms", 20, 0.040),
    ("C  4 workers x 25 ms", 4, 0.025),
]


def section_2() -> None:
    banner(2, "LATENCY AND THROUGHPUT ARE INDEPENDENT DIALS")
    print("  three implementations of the same endpoint, simulated as M/M/c queues")
    print(f"  {'config':<22}{'capacity':>11}{'W unloaded':>13}{'W at 80% load':>15}{'1/W':>10}")
    rows = []
    for i, (label, c, s) in enumerate(CONFIGS):
        mu = 1.0 / s
        capacity = c * mu
        _, w_idle, _, _ = simulate_mmc(capacity * 0.05, mu, c, 60_000, SEED + i)
        thru, w_busy, _, _ = simulate_mmc(capacity * 0.80, mu, c, 200_000, SEED + 10 + i)
        rows.append((label, capacity, w_idle, w_busy, thru))
        print(f"  {label:<22}{capacity:>9.1f}/s{w_idle * 1e3:>11.1f} ms{w_busy * 1e3:>13.1f} ms"
              f"{1 / w_idle:>8.1f}/s")

    cfg_a, cfg_b, cfg_c = rows[0], rows[1], rows[2]
    print(f"\n  A has {cfg_c[2] / cfg_a[2]:.1f}x better latency than C and"
          f" {cfg_b[1] / cfg_a[1]:.1f}x LESS throughput than B.")
    print(f"  C -> B improves throughput {cfg_b[1] / cfg_c[1]:.1f}x while making latency"
          f" {cfg_b[2] / cfg_c[2]:.1f}x WORSE.")
    print(f"  B: 1/W = {1 / cfg_b[2]:.1f}/s but capacity = {cfg_b[1]:.1f}/s — off by"
          f" {cfg_b[1] * cfg_b[2]:.0f}x, which is exactly its worker count.")
    print("  throughput = concurrency / latency. Not 1 / latency. That is Little's Law.")


# ══ 3 ═══════════════════════════════════════════════════════════════════════════

def erlang_c_L(lam: float, mu: float, c: int) -> float:
    """Steady-state mean number in an M/M/c system, from the Erlang C formula."""
    a = lam / mu                       # offered load in erlangs
    rho = a / c
    head = sum(a ** k / math.factorial(k) for k in range(c))
    tail = a ** c / (math.factorial(c) * (1 - rho))
    p_wait = tail / (head + tail)      # probability an arrival has to queue
    return p_wait * rho / (1 - rho) + a


def section_3() -> None:
    banner(3, "LITTLE'S LAW: L = lambda x W, VERIFIED THEN USED")
    print(f"  {'queue':<16}{'lambda(meas)':>14}{'W(meas)':>11}{'lambda x W':>12}"
          f"{'L(meas)':>10}{'L(theory)':>11}{'err':>8}")
    scenarios = [
        ("M/M/1 rho=.50", 50.0, 100.0, 1),
        ("M/M/1 rho=.85", 85.0, 100.0, 1),
        ("M/M/4 rho=.70", 28.0, 10.0, 4),
        ("M/M/16 rho=.90", 144.0, 10.0, 16),
    ]
    for i, (label, lam, mu, c) in enumerate(scenarios):
        thru, w, ell, _ = simulate_mmc(lam, mu, c, 250_000, SEED + 100 + i)
        theory = erlang_c_L(lam, mu, c)
        print(f"  {label:<16}{thru:>12.2f}/s{w * 1e3:>8.2f} ms{thru * w:>12.3f}"
              f"{ell:>10.3f}{theory:>11.3f}{(ell - theory) / theory:>8.1%}")
    print("  lambda x W and L(meas) agree to every printed digit — that is not luck.")
    print("  L is the area under the in-system curve sliced by TIME; sum(W) is the same")
    print("  area sliced by REQUEST. Little's Law is an accounting identity, and the")
    print("  Erlang-C column is the independent check that the queue itself is right.")

    print("\n  using it forward — three questions you get asked at work")
    lam1, w1 = 800.0, 0.250
    print(f"  (a) how many requests are in flight at {lam1:.0f} req/s and {w1 * 1e3:.0f} ms?")
    print(f"      L = {lam1:.0f} x {w1:.3f} = {lam1 * w1:.0f} concurrent requests."
          f" A 50-thread pool serves {50 / w1:.0f}/s, not 800.")
    lam2, w2, head = 800.0, 0.250, 1.5
    print(f"  (b) how big should the pool be? L x headroom = {lam2 * w2:.0f} x {head} ="
          f" {math.ceil(lam2 * w2 * head)} slots.")
    print(f"      CPU needed is separate: {lam2:.0f}/s x {CPU_PER_REQ * 1e3:.0f} ms ="
          f" {lam2 * CPU_PER_REQ:.1f} cores. Threads are for waiting, cores are for working.")
    pool, w3 = 200, 0.250
    print(f"  (c) the pool is {pool} and W has risen to {w3 * 1e3:.0f} ms. Ceiling ="
          f" {pool / w3:.0f} req/s.")
    for degraded in (0.400, 1.000):
        print(f"      if a dependency slows W to {degraded * 1e3:.0f} ms the same pool"
              f" caps you at {pool / degraded:.0f} req/s — a"
              f" {(1 - (pool / degraded) / (pool / w3)):.0%} capacity loss with no code change.")


# ══ 4 ═══════════════════════════════════════════════════════════════════════════

def mm1_mean_sojourn(rho: float, mu: float, n: int, seed: int) -> float:
    """Mean time in system for M/M/1 via Lindley's recursion, discarding a warmup.

    W_q(k+1) = max(0, W_q(k) + S(k) - A(k+1)); sojourn = W_q + S.
    """
    rng = random.Random(seed)
    lam = rho * mu
    expo = rng.expovariate
    warm = n // 5
    wq = 0.0
    total = 0.0
    counted = 0
    for k in range(n):
        s = expo(mu)
        if k >= warm:
            total += wq + s
            counted += 1
        wq = wq + s - expo(lam)
        if wq < 0.0:
            wq = 0.0
    return total / counted


def section_4() -> None:
    banner(4, "THE UTILIZATION KNEE: W = S / (1 - rho)")
    service = 0.020          # 20 ms of service time
    mu = 1.0 / service
    print(f"  service time S = {service * 1e3:.0f} ms; W is the time a request spends"
          f" in the system")
    print(f"  {'rho':>7}{'W/S formula':>14}{'W formula':>12}{'W simulated':>14}"
          f"{'sim/formula':>13}")
    for rho in (0.10, 0.30, 0.50, 0.70, 0.80, 0.90):
        formula = service / (1 - rho)
        measured = mm1_mean_sojourn(rho, mu, 900_000, SEED + int(rho * 100))
        print(f"  {rho:>7.3f}{1 / (1 - rho):>13.1f}x{formula * 1e3:>10.1f} ms"
              f"{measured * 1e3:>12.1f} ms{measured / formula:>12.2f}")
    print("  the simulation confirms the formula wherever it converges; past rho=0.9")
    print("  a queue takes longer to reach steady state than it does to hurt you:")
    for rho in (0.95, 0.99, 0.995):
        print(f"  {rho:>7.3f}{1 / (1 - rho):>13.1f}x{service / (1 - rho) * 1e3:>10.1f} ms"
              f"{'—':>12}  {'(formula only)':>12}")
    print(f"  going 80% -> 90% busy costs +{(1 / 0.10) / (1 / 0.20) - 1:.0%} latency for"
          f" +12.5% work.")
    print(f"  going 90% -> 99% busy costs +{(1 / 0.01) / (1 / 0.10) - 1:.0%} latency for"
          f" +10% work.")


# ══ 5 ═══════════════════════════════════════════════════════════════════════════

def amdahl(serial: float, workers: int) -> float:
    """Speedup with a fraction `serial` that cannot be parallelized."""
    return 1.0 / (serial + (1.0 - serial) / workers)


def usl(workers: int, sigma: float, kappa: float) -> float:
    """Universal Scalability Law: contention (sigma) plus coherency (kappa)."""
    n = float(workers)
    return n / (1.0 + sigma * (n - 1.0) + kappa * n * (n - 1.0))


def section_5() -> None:
    banner(5, "AMDAHL'S CEILING AND THE USL'S CLIFF")
    fractions = (0.001, 0.01, 0.05, 0.25)
    counts = (2, 8, 32, 128, 1024)
    print("  Amdahl — speedup vs workers, by serial fraction")
    print(f"  {'serial':>8}" + "".join(f"{'N=' + str(k):>9}" for k in counts) + f"{'N=inf':>9}")
    for s in fractions:
        row = "".join(f"{amdahl(s, k):>8.1f}x" for k in counts)
        print(f"  {s:>7.1%}{row}{1 / s:>8.1f}x")
    print(f"  5% serial caps you at {1 / 0.05:.0f}x. 1024 workers buys"
          f" {amdahl(0.05, 1024):.1f}x — {amdahl(0.05, 1024) / 1024:.1%} efficiency.")

    sigma, kappa = 0.05, 0.0001
    peak_n = max(range(1, 4001), key=lambda k: usl(k, sigma, kappa))
    predicted = math.sqrt((1 - sigma) / kappa)
    print(f"\n  USL — sigma={sigma} (contention), kappa={kappa} (coherency)")
    print(f"  {'workers':>9}{'Amdahl':>11}{'USL':>11}")
    for k in (1, 4, 16, 64, peak_n, 256, 512, 1024, 2048):
        mark = "  <- USL peak" if k == peak_n else ""
        print(f"  {k:>9}{amdahl(sigma, k):>10.2f}x{usl(k, sigma, kappa):>10.2f}x{mark}")
    print(f"  peak measured at N={peak_n}; sqrt((1-sigma)/kappa) predicts"
          f" {predicted:.1f}. Throughput at")
    print(f"  N=1024 is {usl(1024, sigma, kappa):.2f}x — worse than N=16's"
          f" {usl(16, sigma, kappa):.2f}x. Amdahl says {amdahl(sigma, 1024):.2f}x and never")
    print("  goes down; only the coherency term explains a system that gets slower.")


def main() -> None:
    random.seed(SEED)
    start = time.perf_counter()
    section_1()
    section_2()
    section_3()
    section_4()
    section_5()
    print(f"\n  (total runtime {time.perf_counter() - start:.1f} s)")


if __name__ == "__main__":
    main()
