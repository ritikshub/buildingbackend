#!/usr/bin/env python3
"""Benchmarking and load testing from scratch — standard library only.

Builds an honest microbenchmark harness (warmup, independent trials, percentiles, a
"is this difference real" verdict), three benchmarks that lie, a timer-resolution probe,
an end-to-end demonstration of COORDINATED OMISSION, a throughput/latency curve, and a
generator-saturation self-check. Companion to docs/en.md (Phase 8, Lesson 14).
Coordinated omission and recordValueWithExpectedInterval are due to Gil Tene
(HdrHistogram, https://github.com/HdrHistogram/HdrHistogram).
"""

from __future__ import annotations

import functools
import hashlib
import heapq
import math
import random
import statistics
import time
from collections import defaultdict, deque

SEED = 20260718


# ---------------------------------------------------------------------------
# Shared statistics helpers. Nearest-rank percentiles: no interpolation, so a
# reported p99 is always a value that some real sample actually took.
# ---------------------------------------------------------------------------

def pct(xs, q):
    """Nearest-rank percentile. q is a fraction, e.g. 0.99."""
    if not xs:
        return float("nan")
    s = sorted(xs)
    idx = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return s[idx]


def ms(seconds):
    return seconds * 1e3


def us(seconds):
    return seconds * 1e6


def banner(n, title):
    print(f"\n== {n} · {title} ==")


# ---------------------------------------------------------------------------
# 1 · An honest microbenchmark harness
# ---------------------------------------------------------------------------

def calibrate(fn, arg, target_batch_s=0.002, cap=1 << 22):
    """Pick a batch size N so that timing N calls is far above the clock's noise.

    Timing one sub-microsecond call measures the clock, not the call (section 3).
    """
    n = 1
    while n < cap:
        t0 = time.perf_counter()
        for _ in range(n):
            fn(arg)
        dt = time.perf_counter() - t0
        if dt >= target_batch_s:
            return n
        # Grow towards the target, but never by less than 2x.
        n = max(n * 2, int(n * target_batch_s / max(dt, 1e-9)) + 1)
    return cap


def benchmark(fn, arg, trials=12, samples_per_trial=12, warmup_batches=5):
    """Warm up, then run `trials` INDEPENDENT trials of `samples_per_trial` batches.

    Repetition inside one trial measures the same environmental state over and over;
    only separate trials sample the environment (frequency, cache, scheduler) afresh.
    Returns every per-operation sample plus the per-trial medians.
    """
    n = calibrate(fn, arg)
    for _ in range(warmup_batches):                 # cold caches, lazy imports,
        for _ in range(n):                          # first-call attribute resolution
            fn(arg)
    all_samples, trial_medians = [], []
    for _ in range(trials):
        trial = []
        for _ in range(samples_per_trial):
            t0 = time.perf_counter()
            for _ in range(n):
                fn(arg)
            trial.append((time.perf_counter() - t0) / n)
        all_samples.extend(trial)
        trial_medians.append(statistics.median(trial))
    return {"batch": n, "samples": all_samples, "trial_medians": trial_medians}


def report(label, res):
    s = res["samples"]
    print(f"  {label:<26} batch={res['batch']:>7}  n={len(s):>4}")
    print(f"    {'min':>6} {us(min(s)):9.3f} us   {'median':>6} {us(statistics.median(s)):9.3f} us"
          f"   {'p95':>4} {us(pct(s, 0.95)):9.3f} us")
    print(f"    {'p99':>6} {us(pct(s, 0.99)):9.3f} us   {'stdev':>6} {us(statistics.stdev(s)):9.3f} us"
          f"   {'spread':>4} {(max(s) / min(s)):8.2f}x")


def verdict(name_a, res_a, name_b, res_b):
    """Is the difference real? Two conditions, both cheap and both necessary.

    1. The per-trial medians must not OVERLAP. If the worst trial of the fast one is
       still faster than the best trial of the slow one, no plausible re-run flips it.
    2. The gap must exceed 3x the combined run-to-run spread of the trial medians.
    """
    a, b = res_a["trial_medians"], res_b["trial_medians"]
    ma, mb = statistics.median(a), statistics.median(b)
    noise = statistics.stdev(a) + statistics.stdev(b)
    gap = abs(ma - mb)
    disjoint = max(a) < min(b) or max(b) < min(a)
    real = disjoint and gap > 3 * noise
    faster, slower = (name_a, name_b) if ma < mb else (name_b, name_a)
    print(f"  {name_a} median {us(ma):.3f} us   vs   {name_b} median {us(mb):.3f} us")
    print(f"    gap {us(gap):.3f} us   combined trial noise {us(noise):.3f} us"
          f"   gap/noise = {(gap / noise if noise else float('inf')):.1f}x")
    print(f"    trial-median ranges disjoint: {disjoint}")
    if real:
        print(f"    VERDICT: REAL — {faster} is {max(ma, mb) / min(ma, mb):.2f}x faster than {slower}")
    else:
        print("    VERDICT: NOT PROVEN — the difference is inside the noise. Report no change.")
    return real


def top_k_sort(xs, k=10):
    return sorted(xs, reverse=True)[:k]


def top_k_heap(xs, k=10):
    return heapq.nlargest(k, xs)


def section_1_harness(random_data):
    banner(1, "AN HONEST HARNESS: WARMUP, TRIALS, PERCENTILES, A VERDICT")
    print("  task: top-10 of 20,000 ints   A = sorted(xs)[:10]   B = heapq.nlargest(10, xs)")
    res_sort = benchmark(top_k_sort, random_data)
    res_heap = benchmark(top_k_heap, random_data)
    report("A sorted(xs)[:10]", res_sort)
    report("B heapq.nlargest", res_heap)
    verdict("A", res_sort, "B", res_heap)
    print("  control: the SAME implementation benchmarked twice — a harness must be able")
    print("  to say 'no difference', or every result it prints is a coin flip.")
    ctrl_a = benchmark(top_k_heap, random_data)
    ctrl_b = benchmark(top_k_heap, random_data)
    verdict("B(run1)", ctrl_a, "B(run2)", ctrl_b)
    return res_sort, res_heap


# ---------------------------------------------------------------------------
# 2 · Three benchmarks that lie
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=None)
def price_quote(sku: str) -> int:
    """Expensive pure function — and memoized, exactly like the real one."""
    h = sku.encode()
    for _ in range(300):
        h = hashlib.sha256(h).digest()
    return h[0]


_TABLE = None


def normalize_row(row: str) -> int:
    """Lazily builds a lookup table on first call: the classic warmup cliff."""
    global _TABLE
    if _TABLE is None:
        import unicodedata                        # lazy import: paid once, on call #1
        _TABLE = {chr(c): unicodedata.normalize("NFKD", chr(c))[0]
                  for c in range(0x0080, 0x2E00)}
    return sum(len(_TABLE.get(ch, ch)) for ch in row)


def section_2a_cache_lie():
    print("  (a) THE BENCHMARK MEASURED A CACHE")
    warm = benchmark(price_quote, "SKU-CONSTANT", trials=6, samples_per_trial=6)
    warm_med = statistics.median(warm["samples"])

    counter = [0]

    def fresh(_):
        counter[0] += 1
        return price_quote(f"SKU-{counter[0]}")

    t0 = time.perf_counter()
    for _ in range(2000):
        fresh(None)
    cold_med = (time.perf_counter() - t0) / 2000
    print(f"      same input, 1 distinct key   : {us(warm_med):10.3f} us/op   <- what the benchmark reported")
    print(f"      fresh key every call         : {us(cold_med):10.3f} us/op   <- what production pays")
    print(f"      false speedup claimed        : {cold_med / warm_med:10.1f}x")
    print("      The loop measured a dict lookup. The function was never called twice.")
    return warm_med, cold_med


def section_2b_warmup_lie():
    print("  (b) NO WARMUP")
    global _TABLE
    _TABLE = None
    row = "".join(chr(0x00C0 + (i % 300)) for i in range(400))
    per_iter = []
    for _ in range(40):
        t0 = time.perf_counter()
        normalize_row(row)
        per_iter.append(time.perf_counter() - t0)
    print(f"      iteration 1  : {ms(per_iter[0]):9.3f} ms")
    print(f"      iteration 2  : {ms(per_iter[1]):9.3f} ms")
    print(f"      iteration 3  : {ms(per_iter[2]):9.3f} ms")
    print(f"      iterations 4-40 median : {ms(statistics.median(per_iter[3:])):9.3f} ms")
    mean_all = statistics.mean(per_iter)
    mean_warm = statistics.mean(per_iter[3:])
    print(f"      mean INCLUDING warmup  : {ms(mean_all):9.3f} ms   <- reported")
    print(f"      mean EXCLUDING warmup  : {ms(mean_warm):9.3f} ms   <- steady state")
    print(f"      inflation from 3 cold iterations : {mean_all / mean_warm:6.2f}x")
    return mean_all, mean_warm


def section_2c_data_lie(rng):
    print("  (c) UNREPRESENTATIVE DATA")
    n = 20_000
    presorted = list(range(n))
    uniform = presorted[:]
    rng.shuffle(uniform)
    realistic = presorted[:]                       # mostly-ordered, e.g. arrival times
    for _ in range(n // 20):                       # 5% displaced
        i, j = rng.randrange(n), rng.randrange(n)
        realistic[i], realistic[j] = realistic[j], realistic[i]

    print(f"      {'dataset':<22}{'A sorted()[:10]':>18}{'B nlargest(10)':>18}   winner")
    winners = {}
    for name, data in (("already sorted", presorted), ("uniform random", uniform),
                       ("realistic (5% out)", realistic)):
        a = statistics.median(benchmark(top_k_sort, data, trials=5, samples_per_trial=5)["samples"])
        b = statistics.median(benchmark(top_k_heap, data, trials=5, samples_per_trial=5)["samples"])
        win = "A" if a < b else "B"
        winners[name] = (a, b, win)
        print(f"      {name:<22}{ms(a):15.3f} ms{ms(b):16.3f} ms   {win} by {max(a, b) / min(a, b):.2f}x")
    print("      Timsort is O(n) on sorted input, so 'already sorted' answers a different question.")

    # Key skew: the same cache, two workloads.
    print("      key skew, same 1000-entry LRU cache over 10,000 keys:")
    for label, keys in (("uniform keys", [rng.randrange(10_000) for _ in range(50_000)]),
                        ("zipf-ish keys", [min(9_999, int(10_000 * (rng.random() ** 6)))
                                           for _ in range(50_000)])):
        cache, hits = deque(), 0
        member = set()
        for k in keys:
            if k in member:
                hits += 1
            else:
                cache.append(k)
                member.add(k)
                if len(cache) > 1000:
                    member.discard(cache.popleft())
        hit_rate = hits / len(keys)
        eff = hit_rate * 0.0001 + (1 - hit_rate) * 0.010     # 0.1 ms hit, 10 ms miss
        print(f"        {label:<16} hit rate {hit_rate * 100:5.1f}%   effective latency {ms(eff):7.3f} ms")
    print("        benchmarking with a 100% hit rate would have claimed   0.100 ms")
    return winners


def section_2_lies(rng):
    banner(2, "THREE BENCHMARKS THAT LIE (WITH THE TRUE NUMBER BESIDE EACH)")
    a = section_2a_cache_lie()
    b = section_2b_warmup_lie()
    c = section_2c_data_lie(rng)
    return a, b, c


# ---------------------------------------------------------------------------
# 3 · Timer resolution
# ---------------------------------------------------------------------------

def section_3_timers():
    banner(3, "TIMER RESOLUTION: TIMING ONE FAST OPERATION MEASURES THE CLOCK")
    for name in ("perf_counter", "process_time", "monotonic", "time"):
        info = time.get_clock_info(name)
        print(f"  time.{name:<13} resolution={info.resolution:.0e}s  monotonic={str(info.monotonic):<5}"
              f"  adjustable={info.adjustable}")

    deltas = []
    prev = time.perf_counter()
    for _ in range(200_000):
        cur = time.perf_counter()
        if cur != prev:
            deltas.append(cur - prev)
            prev = cur
    print(f"  measured perf_counter tick    : {us(min(deltas)):8.4f} us"
          f"  (median gap between distinct reads {us(statistics.median(deltas)):.4f} us)")

    d = {"k": 1}
    raw = []
    for _ in range(15):
        t0 = time.perf_counter()
        d["k"]
        raw.append(time.perf_counter() - t0)
    print(f"  timing ONE dict lookup, 15 times: min {us(min(raw)):.4f} us  max {us(max(raw)):.4f} us"
          f"  spread {max(raw) / max(min(raw), 1e-12):.0f}x")
    print("  the operation costs tens of nanoseconds; every number above is clock overhead.")

    print("  the fix — time a batch of N and divide:")
    for n in (1, 10, 1_000, 100_000, 5_000_000):
        t0 = time.perf_counter()
        for _ in range(n):
            d["k"]
        dt = time.perf_counter() - t0
        print(f"      N={n:>9}  total {ms(dt):9.4f} ms   per-op {us(dt / n):8.4f} us")
    print("  per-op only converges once the batch is far larger than one clock tick.")


# ---------------------------------------------------------------------------
# 4 · THE CENTREPIECE — coordinated omission
# ---------------------------------------------------------------------------

class SimServer:
    """Single-threaded FIFO server in virtual time (so the result is reproducible).

    Service time is exponential with mean `service_s`, so the healthy baseline has a
    real tail of its own. Completely unavailable during [stall_at, stall_at+stall_s):
    a stop-the-world GC pause, a failover, a lock convoy, a cache flush. Requests that
    arrive then queue and are served, in order, the moment it comes back.
    """

    def __init__(self, service_s, stall_at, stall_s, seed=SEED):
        self.service_s, self.stall_at, self.stall_s = service_s, stall_at, stall_s
        self.rng = random.Random(seed)
        self.free_at = 0.0

    def serve(self, arrival):
        start = max(arrival, self.free_at)
        if self.stall_at <= start < self.stall_at + self.stall_s:
            start = self.stall_at + self.stall_s      # frozen: wait it out, then queue
        self.free_at = start + self.rng.expovariate(1.0 / self.service_s)
        return self.free_at


def run_open_loop(server, rate, duration):
    """Fixed ARRIVAL RATE. Request i is *intended* to start at i/rate no matter what
    the server is doing, and latency is measured from that intended time."""
    lat = []
    for i in range(int(rate * duration)):
        intended = i / rate
        lat.append(server.serve(intended) - intended)
    return lat


def run_closed_loop(server, users, cycle_s, duration):
    """N virtual users. Each sends, WAITS for the response, then paces to `cycle_s`.
    Latency is measured from the actual send. Nothing is sent while a user is blocked."""
    heap = [(u * cycle_s / users, u) for u in range(users)]
    heapq.heapify(heap)
    per_user = defaultdict(list)
    while heap:
        send, u = heapq.heappop(heap)
        if send >= duration:
            continue                                  # this user is done; drop it
        per_user[u].append(server.serve(send) - send)
        heapq.heappush(heap, (max(server.free_at, send + cycle_s), u))
    return per_user


def correct_for_omission(samples, expected_interval):
    """HdrHistogram's recordValueWithExpectedInterval, by hand.

    A sample of L when a request was due every `expected_interval` means the requests
    that were due at L-i*interval never got sent. Each of those WOULD have observed
    the remaining wait, so back-fill L-interval, L-2*interval, ... down to zero.
    """
    out = []
    for v in samples:
        out.append(v)
        x = v - expected_interval
        while x > 0:
            out.append(x)
            x -= expected_interval
    return out


def latency_row(label, lat):
    print(f"  {label:<34}{len(lat):>8}{ms(pct(lat, 0.50)):>11.2f}{ms(pct(lat, 0.99)):>11.2f}"
          f"{ms(pct(lat, 0.999)):>12.2f}{ms(max(lat)):>11.2f}")


def section_4_coordinated_omission():
    banner(4, "COORDINATED OMISSION: THE SAME SERVER, TWO GENERATORS, TWO REALITIES")
    rate, duration, service = 200, 60.0, 0.001
    users, cycle = 20, 0.1                            # 20 / 0.1 s = 200 rps intended
    stall_at, stall_s = 30.0, 2.0
    print(f"  server: mean 1 ms/request (capacity ~1000 rps), frozen for {stall_s:.0f}s at t={stall_at:.0f}s")
    print(f"  target: {rate} rps for {duration:.0f}s = {int(rate * duration)} requests")
    print(f"  closed loop: {users} virtual users, {cycle * 1e3:.0f} ms cycle each = {users / cycle:.0f} rps")

    closed_by_user = run_closed_loop(SimServer(service, stall_at, stall_s), users, cycle, duration)
    closed = [v for vs in closed_by_user.values() for v in vs]
    openl = run_open_loop(SimServer(service, stall_at, stall_s), rate, duration)
    corrected = [v for u, vs in closed_by_user.items()
                 for v in correct_for_omission(vs, cycle)]

    print(f"\n  {'generator':<34}{'samples':>8}{'p50 ms':>11}{'p99 ms':>11}{'p99.9 ms':>12}{'max ms':>11}")
    latency_row("closed loop (what most tools do)", closed)
    latency_row("open loop (intended start time)", openl)
    latency_row("closed loop + HdrHistogram fix", corrected)

    ratio99 = pct(openl, 0.99) / pct(closed, 0.99)
    recovery = pct(corrected, 0.99) / pct(openl, 0.99)
    missing = int(rate * duration) - len(closed)
    print(f"\n  requests the closed loop never sent : {missing}"
          f"   ({missing / (rate * duration) * 100:.1f}% of the intended {int(rate * duration)})")
    print(f"  achieved rate (closed) {len(closed) / duration:7.1f} rps  vs intended {rate} rps"
          f"  -> {len(closed) / duration / rate * 100:.1f}% — the tell, if you look")
    print(f"  p99 understated by the closed loop  : {ratio99:8.1f}x"
          f"   ({ms(pct(closed, 0.99)):.2f} ms reported vs {ms(pct(openl, 0.99)):.2f} ms real)")
    print(f"  back-filled p99 recovers the open-loop answer to {recovery * 100:.1f}% "
          f"({ms(pct(corrected, 0.99)):.2f} ms vs {ms(pct(openl, 0.99)):.2f} ms)")
    print(f"  corrected sample count {len(corrected)} vs open-loop {len(openl)}"
          f"  — the correction re-creates the requests, it does not invent latency")
    return {"closed_p99": pct(closed, 0.99), "open_p99": pct(openl, 0.99),
            "corr_p99": pct(corrected, 0.99), "ratio": ratio99, "recovery": recovery,
            "missing": missing, "closed_n": len(closed), "open_n": len(openl),
            "corr_n": len(corrected), "closed_p999": pct(closed, 0.999),
            "open_p999": pct(openl, 0.999), "closed_p50": pct(closed, 0.50)}


# ---------------------------------------------------------------------------
# 5 · The throughput/latency curve and the knee
# ---------------------------------------------------------------------------

def load_step(rng, offered_rate, duration, mean_service, queue_cap, timeout_s, deadline_s):
    """Open-loop Poisson arrivals into one bounded FIFO queue with a client deadline.

    THROUGHPUT counts every response the server produced. GOODPUT counts only the ones
    that were successful AND arrived inside `deadline_s` — the number a user would
    recognise as the service working.
    """
    inflight = deque()
    free_at, t = 0.0, 0.0
    lat, shed, timedout, sent = [], 0, 0, 0
    while True:
        t += rng.expovariate(offered_rate)
        if t >= duration:
            break
        sent += 1
        while inflight and inflight[0] <= t:
            inflight.popleft()
        if len(inflight) >= queue_cap:               # load shedding: queue is full
            shed += 1
            continue
        start = max(t, free_at)
        free_at = start + rng.expovariate(1.0 / mean_service)
        inflight.append(free_at)
        latency = free_at - t
        lat.append(latency)
        if latency > timeout_s:                      # server finished; the client had gone
            timedout += 1
    good = [v for v in lat if v <= deadline_s]
    return {"offered": offered_rate, "achieved": len(lat) / duration,
            "goodput": len(good) / duration, "err": (shed + timedout) / max(sent, 1) * 100,
            "p50": pct(lat, 0.50), "p99": pct(lat, 0.99), "sent": sent, "shed": shed}


def section_5_curve(rng):
    banner(5, "THE THROUGHPUT/LATENCY CURVE: WHERE CAPACITY ACTUALLY IS")
    mean_service, duration, queue_cap, timeout_s, slo_s = 0.005, 40.0, 120, 1.0, 0.200
    print(f"  one server, mean service {mean_service * 1e3:.0f} ms -> theoretical ceiling "
          f"{1 / mean_service:.0f} rps; queue cap {queue_cap}; client deadline {timeout_s * 1e3:.0f} ms")
    print(f"  SLO: p99 < {slo_s * 1e3:.0f} ms. Goodput = responses delivered inside that SLO.")
    rows = [load_step(rng, offered, duration, mean_service, queue_cap, timeout_s, slo_s)
            for offered in (40, 80, 120, 150, 170, 185, 200, 240, 320, 400)]
    within = [r for r in rows if r["p99"] <= slo_s]
    best = within[-1]
    print(f"\n  {'offered':>8}{'achieved':>10}{'goodput':>9}{'p50 ms':>9}{'p99 ms':>10}{'err %':>8}   note")
    for r in rows:
        if r is best:
            note = "<- KNEE: max useful throughput"
        elif r["p99"] <= slo_s:
            note = "within SLO"
        elif r["achieved"] < r["offered"] * 0.95:
            note = "SATURATED: achieved << offered"
        else:
            note = "over the knee: p99 climbing"
        print(f"  {r['offered']:>8}{r['achieved']:>10.1f}{r['goodput']:>9.1f}"
              f"{ms(r['p50']):>9.1f}{ms(r['p99']):>10.1f}{r['err']:>8.1f}   {note}")
    peak = max(r["achieved"] for r in rows)
    print(f"\n  peak throughput the box can produce      : {peak:6.1f} rps  (at any latency)")
    print(f"  MAXIMUM USEFUL THROUGHPUT (p99 < {slo_s * 1e3:.0f} ms) : {best['achieved']:6.1f} rps"
          f"  at p99 {ms(best['p99']):.1f} ms")
    print(f"  quoting the peak overstates capacity by  : {peak / best['achieved']:6.2f}x")
    last = rows[-1]
    print(f"  at {last['offered']} rps offered: achieved {last['achieved']:.1f} rps but goodput only "
          f"{last['goodput']:.1f} rps, {last['err']:.1f}% errors")
    print(f"  offered {last['offered']} -> achieved {last['achieved']:.1f} rps "
          f"({last['achieved'] / last['offered'] * 100:.0f}% of offered): that gap IS saturation.")
    print(f"  goodput collapses from {best['goodput']:.1f} rps at the knee to "
          f"{last['goodput']:.1f} rps under overload — a {best['goodput'] / max(last['goodput'], 0.1):.0f}x drop"
          f" while 'throughput' barely moved.")
    return rows, best, peak


# ---------------------------------------------------------------------------
# 6 · Generator honesty
# ---------------------------------------------------------------------------

def paced_run(target_rate, duration_s):
    """A real open-loop generator on a real clock. Reports what it ACHIEVED."""
    interval = 1.0 / target_rate
    payload = b"GET /checkout HTTP/1.1"
    t0 = time.perf_counter()
    sent, lags = 0, []
    while True:
        now = time.perf_counter()
        if now - t0 >= duration_s:
            break
        intended = t0 + sent * interval
        if now < intended:
            while time.perf_counter() < intended:    # spin: sleep() granularity is ~1 ms
                pass
        lags.append(time.perf_counter() - intended)
        hashlib.sha256(payload).digest()             # stand-in for encoding a request
        sent += 1
    elapsed = time.perf_counter() - t0
    return sent / elapsed, lags


def section_6_generator_honesty():
    banner(6, "GENERATOR HONESTY: THE HARNESS SATURATES BEFORE THE SERVER DOES")
    print(f"  {'intended rps':>13}{'achieved rps':>14}{'ratio':>8}{'median lag ms':>15}{'max lag ms':>12}   verdict")
    for target in (20_000, 200_000, 1_000_000, 3_000_000):
        achieved, lags = paced_run(target, 0.35)
        ratio = achieved / target
        ok = ratio >= 0.95
        print(f"  {target:>13}{achieved:>14.0f}{ratio * 100:>7.1f}%{ms(statistics.median(lags)):>15.4f}"
              f"{ms(max(lags)):>12.3f}   {'ok' if ok else 'GENERATOR SATURATED — result invalid'}")
    print("  A generator that cannot keep up stops sending while it is behind.")
    print("  That is coordinated omission produced by your own client. Always print this table.")


# ---------------------------------------------------------------------------

def main():
    rng = random.Random(SEED)
    random.seed(SEED)
    data = [rng.randrange(1_000_000) for _ in range(20_000)]

    section_1_harness(data)
    section_2_lies(random.Random(SEED))
    section_3_timers()
    co = section_4_coordinated_omission()
    section_5_curve(random.Random(SEED + 1))
    section_6_generator_honesty()

    banner("*", "THE ONE NUMBER TO REMEMBER")
    print(f"  Same server, same 200 rps target, same 2-second stall.")
    print(f"  Closed-loop p99 {ms(co['closed_p99']):.2f} ms.  Open-loop p99 {ms(co['open_p99']):.2f} ms."
          f"  {co['ratio']:.0f}x.")
    print(f"  Nothing was wrong with the measurement. The requests were never sent.")


if __name__ == "__main__":
    main()
