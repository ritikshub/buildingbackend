"""
The whole investigation, one stage at a time, printed as an argument.

Runs the inherited service (slow_service.py) through the open-loop harness
(harness.py): baseline, profile, and eight changes, each measured before and
after, including one change that is reverted because the measurement said so.
Companion to docs/en.md (Phase 8, Lesson 15).

Canonical command:  python3 run_capstone.py     (self-terminating, exits 0)
"""

from __future__ import annotations

import dataclasses

from harness import (
    LAT_EDGES,
    Result,
    SamplingProfiler,
    goodput_series,
    histogram,
    measure_capacity,
    run_closed_loop,
    run_open_loop,
)
from slow_service import (
    CPU_ROUNDS,
    N_ITEMS,
    SLO_ERR_PCT,
    SLO_MS,
    SLO_RATE,
    Stage,
    Upstream,
    perf,
    score_items,
    shutdown_cpu_pool,
)

replace = dataclasses.replace

WINDOW = 1.8          # seconds of arrivals per stage
TABLE: list[tuple[str, Result, str]] = []


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def row(res: Result, note: str = "") -> None:
    print(
        f"  {res.label:<26} thr {res.throughput:6.1f}/s  good {res.goodput:6.1f}/s "
        f" p50 {res.p50:7.1f}ms  p99 {res.p99:8.1f}ms  err {res.err_pct:5.1f}%  "
        f"{res.correctness():<5} {note}"
    )


def record(res: Result, verdict: str) -> None:
    TABLE.append((res.label, res, verdict))


def main() -> None:
    t_start = perf()

    # ---------------------------------------------------------------- 0 ---- #
    banner("0 . BASELINE, MEASURED HONESTLY")
    print(f"  SLO      p99 <= {SLO_MS:.0f} ms and errors < {SLO_ERR_PCT:.0f}% at "
          f"{SLO_RATE:.0f} req/s offered")
    print("  method   open loop: arrivals on a clock, latency measured from the")
    print("           INTENDED arrival time, not from when a worker got round to it")
    print(f"  caveat   {int(SLO_RATE * WINDOW)} requests per stage, so the reported p99 "
          f"IS the worst request")
    print("           observed. Read it as 'the tail', not as a stable percentile.")
    n_calls = 3 + N_ITEMS
    print(f"  handler  {n_calls} sequential upstream calls on {n_calls} fresh "
          f"connections,")
    print("           one global lock held across all of it, one CPU scoring step")

    payload = tuple(range(1, N_ITEMS + 1))
    score_items(payload)                       # warm: never time a cold first call
    t0 = perf()
    for _ in range(5):
        score_items(payload)
    cpu_ms = (perf() - t0) * 1000.0 / 5.0
    print(f"  score_items({CPU_ROUNDS} rounds) = {cpu_ms:.2f} ms of CPU per request")

    base = Stage("0 baseline")
    r0 = run_open_loop(base, SLO_RATE, WINDOW, label="0 baseline", budget=13.0)
    row(r0)
    print(f"    {r0.sent} requests offered at {SLO_RATE:.0f}/s; {r0.ok} completed in "
          f"{r0.wall:.1f}s -> {r0.throughput:.1f} req/s is the real capacity")
    print(f"    p99 wait for the global lock      {r0.lockwait_p99:8.1f} ms")
    print(f"    p99 as the SERVICE times it       {r0.naive_p99:8.1f} ms  <- its own "
          f"dashboard")
    print(f"    p99 as the USER experiences it    {r0.p99:8.1f} ms  <- "
          f"{r0.p99 / max(r0.naive_p99, 1e-9):.0f}x worse")
    print("    the service's timer starts after it owns the lock, so it cannot see")
    print("    the queue in front of it. That gap is the whole reason to load-test.")
    print(f"    latency histogram, {r0.ok} responses, buckets in ms:")
    print(f"      {' '.join(f'{e:>5}' for e in LAT_EDGES)}   +inf")
    print(f"      {' '.join(f'{c:>5}' for c in histogram(r0.lat))}")

    prof_req = SamplingProfiler(interval=0.003)
    p50c, p99c, thrc = run_closed_loop(base, clients=1, requests=14, profiler=prof_req)
    print(f"  the same service measured the WRONG way (closed loop, 1 client, 14 reqs):")
    print(f"    p50 {p50c:.1f} ms   p99 {p99c:.1f} ms   throughput {thrc:.1f}/s "
          f"-- 'p99 is {p99c:.0f} ms, we are fine'")
    print("    coordinated omission: the client never sent request k+1 until k came")
    print(f"    back, so it never measured a queue. Open loop says p99 = {r0.p99:.0f} ms,")
    print(f"    which is {r0.p99 / p99c:.0f}x the closed-loop answer. Users do not wait "
          f"their turn.")
    record(r0, "the service as inherited")

    # ---------------------------------------------------------------- 1 ---- #
    banner("1 . PROFILE BEFORE TOUCHING ANYTHING")
    prof_load = SamplingProfiler(interval=0.004)
    run_open_loop(base, SLO_RATE, 0.6, label="profile run", budget=6.0,
                  profiler=prof_load)
    print(f"  (a) UNDER LOAD -- {prof_load.samples} stack samples across every request "
          f"thread")
    for label, w, _c, _n in prof_load.table()[:3]:
        print(f"      {label:<34}{w:8.1f}% of wall clock")
    print("      one lock owns almost all of the wall clock. That is a CONTENTION")
    print("      signal, not a cost signal: it says where requests wait, not what")
    print("      they wait FOR. For that, profile one request with nothing in its way.")

    rows = prof_req.table()
    print(f"\n  (b) ONE REQUEST AT A TIME -- {prof_req.samples} samples, "
          f"{prof_req.requests} requests, budget {p50c:.0f} ms")
    print(f"      {'WHERE THE TIME IS':<34}{'wall%':>8}{'cpu%':>8}{'calls/req':>11}")
    for label, w, c, per_req in rows:
        cr = f"{per_req:.1f}" if per_req else "-"
        print(f"      {label:<34}{w:8.1f}{c:8.1f}{cr:>11}")

    wall = {label: w for label, w, _, _ in rows}
    connect_pct = wall.get("connect  (TCP+TLS handshake)", 0.0)
    item_pct = wall.get("GET /item/{id}", 0.0)
    cpu_pct = wall.get("score_items()  [CPU]", 0.0)
    max_cpu = max((c for _, _, c, _ in rows), default=0.0)
    print("\n  AMDAHL CEILINGS -- the most a change could possibly buy, from (b)")
    print(f"      {'if you made this free'.ljust(40)}{'wall%':>8}{'max speedup':>14}")
    cands = [
        ("the N+1: item calls + their connects",
         item_pct + connect_pct * (N_ITEMS / n_calls)),
        ("every connection handshake", connect_pct),
        ("the two overlappable calls",
         wall.get("GET /profile", 0.0) + wall.get("GET /settings", 0.0)),
        ("score_items() -- the standing theory", cpu_pct),
    ]
    for name, p in cands:
        frac = min(p / 100.0, 0.985)
        print(f"      {name:<40}{p:8.1f}{1.0 / (1.0 - frac):13.2f}x")
    print(f"      the red herring: score_items() is {cpu_pct:.1f}% of the WALL clock "
          f"and {max_cpu:.0f}% of")
    print(f"      the CPU samples. A CPU profiler ranks it first. Rewriting it in C, "
          f"perfectly,")
    print(f"      buys {1.0 / (1.0 - min(cpu_pct / 100.0, 0.985)):.2f}x. Arithmetic "
          f"settles the argument, not seniority.")
    n_item_calls = prof_req.call_counts.get("GET /item/{id}", 0)
    print(f"      the tell no flat profile prints: {n_item_calls} item fetches across "
          f"{prof_req.requests} requests")
    print(f"      = {n_item_calls / max(prof_req.requests, 1):.1f} calls per request. "
          f"That is an N+1, and it is the biggest number here.")

    # ---------------------------------------------------------------- 2 ---- #
    banner("2 . KILL THE N+1")
    pred = 1.0 / (1.0 - min((item_pct + connect_pct * (N_ITEMS / n_calls)) / 100.0, 0.985))
    print(f"  hypothesis: {N_ITEMS} item calls -> 1 batch call deletes {N_ITEMS} "
          f"handshakes and {N_ITEMS} round")
    print(f"  trips. Amdahl ceiling from (b): {pred:.2f}x. The batch call is not free "
          f"(it is still a")
    print(f"  connect plus a round trip), so predict a little under that.")
    s2 = replace(base, name="2 batched", batch=True)
    r2 = run_open_loop(s2, SLO_RATE, WINDOW, label="2 batch the N+1", budget=11.0)
    row(r2, f"({r2.throughput / r0.throughput:.2f}x throughput)")
    print(f"    predicted <= {pred:.2f}x, measured {r2.throughput / r0.throughput:.2f}x. "
          f"throughput {r0.throughput:.1f} -> {r2.throughput:.1f} req/s, "
          f"p99 {r0.p99:.0f} -> {r2.p99:.0f} ms. KEEP.")
    print(f"    still {r2.p99 / SLO_MS:.0f}x over the {SLO_MS:.0f} ms SLO. One fix is "
          f"never the fix.")
    record(r2, f"{r2.throughput / r0.throughput:.2f}x -- kept")

    # ---------------------------------------------------------------- 3 ---- #
    banner("3 . SEQUENTIAL -> CONCURRENT I/O, AND THE BUG IT UNCOVERS")
    print("  the three remaining calls do not depend on each other. Fan them out.")
    s3a = replace(s2, name="3 concurrent", concurrent=True)
    r3a = run_open_loop(s3a, SLO_RATE, WINDOW, label="3 concurrent I/O", budget=9.0)
    row(r3a, f"({r3a.throughput / r2.throughput:.2f}x)")
    lost = r3a.calls_real - r3a.calls_seen
    print(f"    faster -- and WRONG. upstream_calls_total reads {r3a.calls_seen}; "
          f"the true count is {r3a.calls_real}.")
    print(f"    {lost} increments vanished "
          f"({100.0 * lost / max(r3a.calls_real, 1):.0f}% of them). The metric now "
          f"under-reports every")
    print("    dashboard, alert and capacity model that reads it.")
    print("    diagnosis: CallStats.record() is a read-modify-write. The global lock")
    print("    serialised REQUESTS, so it was atomic BY ACCIDENT. Nothing serialises")
    print("    the three fan-out threads inside ONE request, and they all read the")
    print("    same value. (we widened the window on purpose -- _widen() forces a GIL")
    print("    hand-off mid-update -- so the bug reproduces on every run instead of")
    print("    once a fortnight. The bug is real either way; only the odds changed.)")
    record(r3a, f"{r3a.throughput / r2.throughput:.2f}x -- but WRONG")

    s3b = replace(s3a, name="3b race fixed", race_fixed=True)
    r3b = run_open_loop(s3b, SLO_RATE, WINDOW, label="3b + lock the counter", budget=9.0)
    row(r3b, f"({r3b.throughput / r2.throughput:.2f}x)")
    pb3 = measure_capacity(s3b, n=70, budget=9.0)
    r3b.capacity = pb3.rps
    print(f"    counter reads {r3b.calls_seen} against {r3b.calls_real} true. "
          f"Throughput {r3a.throughput:.1f} -> {r3b.throughput:.1f} req/s:")
    print("    correctness cost nothing measurable here, because the lock protects a")
    print("    counter increment, not a network call. The lock goes around the DATA,")
    print("    not around the request. Scope is the whole skill.")
    print(f"    saturating probe: capacity {r2.throughput:.0f} -> {pb3.rps:.0f} req/s, and at "
          f"saturation the p99")
    print(f"    wait for the global lock is {pb3.lockwait_p99:.0f} ms. That is the next "
          f"thing to attack.")
    record(r3b, f"{r3b.throughput / r2.throughput:.2f}x -- kept")

    # ---------------------------------------------------------------- 4 ---- #
    banner("4 . GET THE I/O OUT FROM UNDER THE GLOBAL LOCK")
    print(f"  measured: p99 wait for the global lock is {r0.lockwait_p99:.0f} ms at "
          f"baseline and {pb3.lockwait_p99:.0f} ms")
    print("  at saturation even after stages 2 and 3, because it is still held across")
    print("  every network call. Shrink it to the index write itself; shard 16 ways.")
    s4 = replace(s3b, name="4 narrow lock", narrow_lock=True)
    r4 = run_open_loop(s4, SLO_RATE, WINDOW, label="4 shrink+shard the lock", budget=8.0)
    pb4 = measure_capacity(s4, n=600, budget=9.0)
    cap4 = pb4.rps
    r4.capacity = cap4
    row(r4, f"(capacity {cap4:.0f}/s)")
    print(f"    p99 lock wait at saturation {pb3.lockwait_p99:.0f} ms -> "
          f"{pb4.lockwait_p99:.2f} ms: it is gone.")
    print(f"    p99 end to end at {SLO_RATE:.0f} req/s {r3b.p99:.1f} ms -> "
          f"{r4.p99:.1f} ms -- but the offered load is the")
    print("    ceiling on that number now, so latency has stopped being the "
          "interesting measurement.")
    print(f"    at {SLO_RATE:.0f}/s the queue is empty, so throughput == offered rate "
          f"and stops being")
    print(f"    informative. Saturating probe instead: capacity {pb3.rps:.0f} -> "
          f"{cap4:.0f} req/s ({cap4 / max(pb3.rps, 1e-9):.1f}x),")
    print(f"    which is {cap4 / r0.throughput:.0f}x the {r0.throughput:.1f} req/s we "
          f"started with. Biggest single win of the run.")
    record(r4, f"capacity {pb3.rps:.0f} -> {cap4:.0f}/s, lock wait to zero -- kept")

    # ---------------------------------------------------------------- 5 ---- #
    banner("5 . POOL THE CONNECTIONS, SIZED FROM THE CURVE")
    print("  every call still pays a handshake. Reuse connections instead -- but")
    print("  size the pool from a measurement, not from a round number.")
    print(f"      {'pool size':>10}{'capacity req/s':>17}{'p99 service ms':>17}"
          f"{'peak upstream':>15}")
    curve = []
    for size in (2, 4, 8, 16, 32):
        st = replace(s4, name=f"pool={size}", pool_size=size)
        pb = measure_capacity(st, n=min(500, 110 * size ** 0.6), budget=9.0)
        curve.append((size, pb.rps))
        print(f"      {size:>10}{pb.rps:>17.0f}{pb.p99_service:>17.1f}{pb.up_peak:>15}")
    knee = max(curve, key=lambda kv: kv[1])
    hold_ms = 1000.0 * knee[0] / max(knee[1], 1e-9)
    need = SLO_RATE * hold_ms / 1000.0
    print(f"      the curve: {' -> '.join(f'{c:.0f}' for _, c in curve)} req/s across "
          f"pool sizes {', '.join(str(k) for k, _ in curve)}.")
    print(f"      it climbs steeply while the pool is the constraint and flattens when "
          f"something else becomes one --")
    print(f"      here the interpreter itself, which served {cap4:.0f} req/s with no "
          f"pool at all.")
    print(f"      Little's Law sizes it: at pool {knee[0]} the service sustains "
          f"{knee[1]:.0f} req/s, so a request holds")
    print(f"      {hold_ms:.0f} ms of connection time; serving the {SLO_RATE:.0f} req/s "
          f"we actually get needs {need:.1f} connections.")
    print(f"      Take 16 -- {16 / max(need, 1e-9):.0f}x the measured need for bursts, "
          f"and still at or under the dependency's own knee of {Upstream.KNEE}.")
    s5 = replace(s4, name="5 pooled", pool_size=16)
    r5 = run_open_loop(s5, SLO_RATE, WINDOW, label="5 pool (size 16)", budget=8.0)
    pb5 = measure_capacity(s5, n=600, budget=9.0)
    cap5 = pb5.rps
    r5.capacity = cap5
    row(r5, f"(capacity {cap5:.0f}/s)")
    print(f"    capacity {cap4:.0f} -> {cap5:.0f} req/s: unchanged within the noise. "
          f"The ceiling was never the handshakes.")
    print(f"    p50 {r4.p50:.1f} -> {r5.p50:.1f} ms, p99 {r4.p99:.1f} -> {r5.p99:.1f} "
          f"ms, p99 pool wait {r5.poolwait_p99:.2f} ms.")
    print("    pooling bought LATENCY, not capacity. Both are worth buying; confusing")
    print("    them is how people ship a change and then argue about what it did.")
    record(r5, f"p50 {r4.p50:.0f} -> {r5.p50:.0f} ms -- kept")

    # ---------------------------------------------------------------- 6 ---- #
    banner("6 . THE CPU-BOUND STEP")
    print(f"  score_items() is {cpu_ms:.1f} ms of pure Python. It holds the GIL (Global")
    print("  Interpreter Lock), so more threads cannot make it parallel. Prove that")
    print("  before spending anything on it:")
    for w in (24, 96):
        st = replace(s5, name=f"threads={w}", workers=w)
        pb = measure_capacity(st, n=350, budget=9.0)
        print(f"      {w:>3} worker threads -> capacity {pb.rps:6.0f} req/s   "
              f"p99 service {pb.p99_service:6.1f} ms")
    s6 = replace(s5, name="6 CPU offloaded", offload_cpu=True)
    pb6 = measure_capacity(s6, n=800, tries=3, budget=12.0)
    cap6, sp6, peak6, fl6, all6 = (pb6.rps, pb6.p99_service, pb6.up_peak,
                                   pb6.inflight_peak, pb6.runs)
    r6 = run_open_loop(s6, SLO_RATE, WINDOW, label="6 CPU -> process pool", budget=8.0)
    r6.capacity = cap6
    row(r6, f"(capacity {cap6:.0f}/s)")
    print(f"    4 processes dodge the GIL: capacity {cap5:.0f} -> {cap6:.0f} req/s "
          f"({cap6 / max(cap5, 1e-9):.2f}x)")
    print(f"    three probes of the SAME build: "
          f"{', '.join(f'{c:.0f}' for c in all6)} req/s -- a "
          f"{100 * (all6[-1] - all6[0]) / max(all6[0], 1e-9):.0f}% spread.")
    print("    that spread is the noise floor of this harness. Any 'improvement' "
          "smaller than it is a story, not a result.")
    print(f"    p99 at {SLO_RATE:.0f}/s: {r5.p99:.1f} -> {r6.p99:.1f} ms -- barely "
          f"moved. This bought HEADROOM,")
    print("    not latency. Every call pickles its payload and crosses a pipe; at")
    print(f"    {cpu_ms:.1f} ms of work that tax is worth paying, at 0.2 ms it is not.")
    print(f"    latency histogram, {r6.ok} responses, same buckets as stage 0:")
    print(f"      {' '.join(f'{e:>5}' for e in LAT_EDGES)}   +inf")
    print(f"      {' '.join(f'{c:>5}' for c in histogram(r6.lat))}")
    record(r6, f"capacity {cap5:.0f} -> {cap6:.0f}/s -- kept")

    # ---------------------------------------------------------------- 7 ---- #
    banner("7 . A FIX THAT FAILS")
    print("  'more parallelism is more throughput.' The pool is already sized from")
    print("  the curve, so the only knob left is the worker count: 24 -> 128.")
    print("  Ship it, and measure it like everything else.")
    s7 = replace(s6, name="7 more workers", workers=128)
    pb7 = measure_capacity(s7, n=800, tries=3, budget=12.0)
    cap7, sp7, peak7, fl7, all7 = (pb7.rps, pb7.p99_service, pb7.up_peak,
                                   pb7.inflight_peak, pb7.runs)
    r7 = run_open_loop(s7, SLO_RATE, WINDOW, label="7 workers 24 -> 128", budget=8.0)
    r7.capacity = cap7
    row(r7, f"(capacity {cap7:.0f}/s)")
    # Never claim a resolution better than 3%: that is the floor for any
    # wall-clock benchmark on a machine you share with an operating system.
    noise = max(0.03, (max(all6) - min(all6)) / max(cap6, 1e-9)
                + (max(all7) - min(all7)) / max(cap7, 1e-9))
    change = cap7 / max(cap6, 1e-9) - 1.0
    flat = abs(change) <= noise
    print(f"    capacity {cap6:.0f} -> {cap7:.0f} req/s "
          f"({cap7 / max(cap6, 1e-9):.2f}x, medians of three).")
    print(f"    the runs: {', '.join(f'{c:.0f}' for c in all6)} against "
          f"{', '.join(f'{c:.0f}' for c in all7)}: a {100 * change:+.1f}% change "
          f"against a")
    print(f"    {100 * noise:.1f}% combined spread, so the honest verdict on "
          f"throughput is "
          + ("FLAT." if flat else f"that it really did move {100 * change:+.0f}%."))
    print(f"    p99 service under saturation {sp6:.1f} -> {sp7:.1f} ms "
          f"({sp7 / max(sp6, 1e-9):.1f}x worse) -- and that regression never "
          f"overlaps.")
    print(f"    p99 at the {SLO_RATE:.0f} req/s we actually serve: {r6.p99:.1f} -> "
          f"{r7.p99:.1f} ms -- unchanged.")
    print(f"    peak requests in flight {fl6} -> {fl7}, but peak concurrent upstream "
          f"calls {peak6} -> {peak7}:")
    print(f"    the pool of {s6.pool_size} was already the constraint, so the extra "
          f"104 threads bought no")
    print(f"    concurrency at all. p99 wait for a connection {pb6.poolwait_p99:.1f} ms "
          f"-> {pb7.poolwait_p99:.1f} ms -- the queue")
    print("    did not shrink, it moved from our accept queue into the pool.")
    print(f"    Little's Law, applied backwards: latency = in-flight / throughput.")
    print(f"      {fl6:>3} in flight / {cap6:.0f} req/s = {1000.0 * fl6 / max(cap6, 1e-9):6.1f} ms")
    print(f"      {fl7:>3} in flight / {cap7:.0f} req/s = {1000.0 * fl7 / max(cap7, 1e-9):6.1f} ms")
    print("    every extra in-flight request converts one-for-one into queue time.")
    print(f"    VERDICT: at today's load this changes nothing, and at saturation it")
    print(f"    multiplies the tail by {sp7 / max(sp6, 1e-9):.1f}x. We run at "
          f"{100 * SLO_RATE / max(cap6, 1e-9):.0f}% of capacity: we are not")
    print("    short of throughput, we are defending a latency SLO, and there is no")
    print("    load at which this change helps the number we promised. REVERT.")
    record(r7, f"p99 at saturation {sp7 / max(sp6, 1e-9):.1f}x worse -- REVERTED")

    # ---------------------------------------------------------------- 8 ---- #
    banner("8 . SURVIVE OVERLOAD")
    over = 3.0 * cap6
    print(f"  measured capacity is {cap6:.0f} req/s. Offer 3x that ({over:.0f} req/s) "
          f"for 0.8 s")
    print("  with the queue unbounded and no deadlines -- the configuration we ship.")
    r8a = run_open_loop(s6, over, 0.8, label="8a overload, unbounded", budget=8.0)
    row(r8a)
    inside = int(round(r8a.goodput * r8a.wall))
    print(f"    accepted all {r8a.sent} requests and eventually completed {r8a.ok} of "
          f"them -- a 0% error rate --")
    print(f"    but only {inside} landed inside the {SLO_MS:.0f} ms SLO. Goodput "
          f"{r8a.goodput:.0f}/s against a capacity of {cap6:.0f}/s.")
    print(f"    p50 {r8a.p50:.0f} ms, p99 {r8a.p99:.0f} ms. This is metastable: the "
          f"queue fills with work whose")
    print("    user has already left, and serving it is exactly what stops us "
          "serving anyone new.")
    record(r8a, f"goodput {r8a.goodput:.0f}/s of {cap6:.0f} capacity -- collapse")

    s8b = replace(s6, name="8b bounded+shed", bounded=True, queue_max=96,
                  deadline_ms=SLO_MS)
    r8b = run_open_loop(s8b, over, 0.8, label="8b bounded + deadlines", budget=5.0)
    row(r8b)
    print(f"    same {r8b.sent} requests. Shed at the door (queue full): {r8b.shed}. "
          f"Dropped on a blown deadline: {r8b.expired}.")
    print(f"    goodput {r8a.goodput:.0f}/s -> {r8b.goodput:.0f}/s "
          f"({r8b.goodput / max(r8a.goodput, 1e-9):.1f}x), "
          f"p99 {r8a.p99:.0f} -> {r8b.p99:.0f} ms, "
          f"p50 {r8a.p50:.0f} -> {r8b.p50:.0f} ms.")
    print(f"    the error rate went UP, {r8a.err_pct:.0f}% -> {r8b.err_pct:.0f}%, and "
          f"that is the point. A bounded queue")
    print("    converts 'everyone gets a useless slow answer' into 'most people get")
    print("    a fast right answer and the rest get a fast, honest 503'.")
    ga, ta = goodput_series(r8a, SLO_MS)
    gb, tb = goodput_series(r8b, SLO_MS)
    print("    goodput and throughput per 200 ms window, req/s:")
    print(f"      8a  throughput {' '.join(f'{v:>4}' for v in ta)}")
    print(f"      8a  GOODPUT    {' '.join(f'{v:>4}' for v in ga)}")
    print(f"      8b  throughput {' '.join(f'{v:>4}' for v in tb)}")
    print(f"      8b  GOODPUT    {' '.join(f'{v:>4}' for v in gb)}")
    print("    read the 8a rows together: the machine stays busy at full throughput")
    print("    for two seconds while goodput sits at zero. It is not idle, it is")
    print("    working flat out on answers nobody is still waiting for.")
    record(r8b, f"goodput {r8b.goodput / max(r8a.goodput, 1e-9):.1f}x -- kept")

    # ---------------------------------------------------------------- 9 ---- #
    banner("9 . THE WHOLE INVESTIGATION IN ONE TABLE")
    print(f"  {'stage':<26}{'offered':>8}{'thr/s':>8}{'good/s':>8}{'p50 ms':>9}"
          f"{'p99 ms':>10}{'err%':>7}{'correct':>9}  verdict")
    for label, res, verdict in TABLE:
        print(f"  {label:<26}{res.offered:8.0f}{res.throughput:8.1f}{res.goodput:8.1f}"
              f"{res.p50:9.1f}{res.p99:10.1f}{res.err_pct:7.1f}{res.correctness():>9}"
              f"  {verdict}")
    print(f"  (stages 0-7 are offered {SLO_RATE:.0f} req/s, the real traffic; stage 8")
    print(f"   is offered 3x the measured capacity, which is a different question)")
    print(f"\n  end to end, at the {SLO_RATE:.0f} req/s the product actually sends:")
    print(f"    throughput {r0.throughput:7.1f} -> {r6.throughput:6.1f} req/s "
          f"({r6.throughput / r0.throughput:.1f}x)")
    print(f"    p50        {r0.p50:7.1f} -> {r6.p50:6.1f} ms     "
          f"({r0.p50 / max(r6.p50, 1e-9):.0f}x faster)")
    print(f"    p99        {r0.p99:7.1f} -> {r6.p99:6.1f} ms     "
          f"({r0.p99 / max(r6.p99, 1e-9):.0f}x faster)")
    print(f"    capacity   {r0.throughput:7.1f} -> {cap6:6.0f} req/s "
          f"({cap6 / max(r0.throughput, 1e-9):.0f}x headroom)")
    ok = r6.p99 <= SLO_MS and r6.err_pct < SLO_ERR_PCT
    print(f"    SLO (p99 <= {SLO_MS:.0f} ms, err < {SLO_ERR_PCT:.0f}%): baseline FAIL, "
          f"final {'PASS' if ok else 'FAIL'}")
    print(f"\n  what mattered, in order of measured effect:")
    print(f"    the global lock scope  {r3b.throughput:.0f} -> {cap4:.0f} req/s "
          f"of capacity")
    print(f"    the N+1                {r0.throughput:.0f} -> {r2.throughput:.0f} "
          f"req/s ({r2.throughput / r0.throughput:.2f}x)")
    print(f"    concurrent I/O         {r2.throughput:.0f} -> {r3b.throughput:.0f} "
          f"req/s ({r3b.throughput / r2.throughput:.2f}x)")
    print("  what did not: raising the worker count to 128 (stage 7, reverted), and")
    print("  -- at this load -- the CPU offload, which moved the ceiling but not the")
    print("  p99 anyone was complaining about.")
    print(f"\n  total run time {perf() - t_start:.1f} s")

    shutdown_cpu_pool()


if __name__ == "__main__":
    main()
