#!/usr/bin/env python3
"""
Phase 11, Lesson 01 — What One Machine Can Actually Do.
Companion to phases/11-scalability-and-reliability/01-what-one-machine-can-do/docs/en.md

Measures the four walls of THIS box (CPU, memory, I/O, NIC), decomposes a synthetic
request against them to find which one binds, measures a constant-factor efficiency
gap, prices vertical scale (a model, clearly marked), and does the availability
arithmetic that makes one machine one failure domain.

Sources: D. Kegel, "The C10K Problem" (1999-2014); J. Dean, "Software Engineering
Advice from Building Large-Scale Distributed Systems" (Stanford CS295, 2007) for the
latency ladder; J. Gray & A. Reuter, *Transaction Processing: Concepts and Techniques*,
Morgan Kaufmann 1993, ch. 12 (group commit); IEEE 802.3 for 10GBASE-T line rate.
"""

from __future__ import annotations

import array
import copy
import math
import os
import random
import statistics
import sys
import tempfile
import time

RNG = random.Random(7)

# ---------------------------------------------------------------- utilities


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def rate(n: float) -> str:
    """Format an operations-per-second figure with an SI-ish suffix."""
    if n >= 1e9:
        return f"{n / 1e9:8.2f} G/s"
    if n >= 1e6:
        return f"{n / 1e6:8.2f} M/s"
    if n >= 1e3:
        return f"{n / 1e3:8.2f} k/s"
    return f"{n:8.2f}  /s"


def secs(x: float) -> str:
    """Format a duration given in seconds, choosing a readable unit."""
    if x >= 1.0:
        return f"{x:7.2f} s "
    if x >= 1e-3:
        return f"{x * 1e3:7.2f} ms"
    if x >= 1e-6:
        return f"{x * 1e6:7.2f} us"
    return f"{x * 1e9:7.2f} ns"


def downtime(minutes: float) -> str:
    """Annual downtime in whatever unit stops it reading as noise."""
    if minutes >= 60:
        return f"{minutes / 60:7.1f} h"
    if minutes >= 1:
        return f"{minutes:7.1f} m"
    if minutes * 60 >= 1:
        return f"{minutes * 60:7.1f} s"
    return "     <1 s"


def nines(avail: float) -> str:
    """How many nines, as a number you can compare."""
    if avail >= 1.0:
        return "  inf"
    return f"{-math.log10(1 - avail):5.1f}"


# ------------------------------------------------------- 1 · the four walls


def measure_cpu(reps: int = 5, n: int = 400_000) -> float:
    """Pure interpreter work: one masked integer add per iteration.

    This is a CPython ceiling, not a silicon ceiling. That is the point — the
    CPU wall you actually hit is the one your runtime gives you.
    """
    best = 0.0
    for _ in range(reps):
        t0 = time.perf_counter()
        x = 0
        for i in range(n):
            x = (x + i) & 0xFFFFFFFF
        dt = time.perf_counter() - t0
        best = max(best, n / dt)
    return best


def measure_loop_overhead(reps: int = 3, n: int = 400_000) -> float:
    """Seconds per empty loop iteration — the baseline we subtract from syscalls."""
    best = math.inf
    for _ in range(reps):
        t0 = time.perf_counter()
        for _ in range(n):
            pass
        best = min(best, (time.perf_counter() - t0) / n)
    return best


def measure_mem_bandwidth(mib: int = 64, reps: int = 7) -> float:
    """Bytes/second for a large bytearray copy. Real traffic is 2x (read + write)."""
    size = mib << 20
    src = bytearray(size)
    dst = bytearray(size)
    best = 0.0
    for _ in range(reps):
        t0 = time.perf_counter()
        dst[:] = src
        dt = time.perf_counter() - t0
        best = max(best, size / dt)
    del src, dst
    return best


def measure_mem_latency(mib: int = 192, touches: int = 600_000) -> tuple[float, float]:
    """Sequential vs random 8-byte reads over a `mib`-sized array.

    Both loops execute identical Python; the only difference is the access
    pattern. The delta is the cache-miss penalty with the interpreter
    overhead cancelled out. The working set has to be far larger than the
    last-level cache or the "random" walk is just an L3 hit.
    """
    buf = array.array("q")
    chunk = bytes(1 << 20)          # grow in 1 MiB steps: never hold 2x the array
    for _ in range(mib):
        buf.frombytes(chunk)
    n = len(buf)
    stride = 8  # 8 int64s = 64 bytes = one cache line
    seq = array.array("q", [(i * stride) % n for i in range(touches)])
    rnd = array.array("q", [RNG.randrange(n) for _ in range(touches)])

    def walk(idx: array.array) -> float:
        best = math.inf
        for _ in range(2):
            s = 0
            t0 = time.perf_counter()
            for i in idx:
                s += buf[i]
            best = min(best, (time.perf_counter() - t0) / touches)
        return best

    return walk(seq), walk(rnd)


def measure_syscall(iters: int = 200_000, reps: int = 3) -> float:
    """Seconds per os.write() to /dev/null, interpreter overhead included."""
    fd = os.open(os.devnull, os.O_WRONLY)
    payload = b"x"
    best = math.inf
    try:
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(iters):
                os.write(fd, payload)
            best = min(best, (time.perf_counter() - t0) / iters)
    finally:
        os.close(fd)
    return best


def measure_writes(budget: float = 1.2) -> tuple[float, float, int]:
    """Cost of a 4 KiB buffered write, and of the same write plus fsync().

    Runs in a temp dir (container-local storage), not the bind-mounted repo,
    so we measure the sandbox's disk rather than a network filesystem.
    """
    rec = b"x" * 4096
    tmpdir = tempfile.mkdtemp(prefix="p11-01-")
    path = os.path.join(tmpdir, "wal.log")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        buffered: list[float] = []
        for _ in range(2000):
            t0 = time.perf_counter()
            os.write(fd, rec)
            buffered.append(time.perf_counter() - t0)
        os.fsync(fd)

        durable: list[float] = []
        deadline = time.perf_counter() + budget
        while time.perf_counter() < deadline and len(durable) < 500:
            t0 = time.perf_counter()
            os.write(fd, rec)
            os.fsync(fd)
            durable.append(time.perf_counter() - t0)
    finally:
        os.close(fd)
        try:
            os.unlink(path)
            os.rmdir(tmpdir)
        except OSError:
            pass
    return statistics.median(buffered), statistics.median(durable), len(durable)


# ------------------------------------------------- 3 · the efficiency gap

TAX = 1.08
# 200 regions, half of them "hot". The naive path scans a LIST for membership
# and calls list.index() for the rank; the careful path hashes a SET and a DICT.
# Same data, same answer, same algorithm on paper.
REGIONS = [f"r-{i:03d}" for i in range(200)]
HOT = set(REGIONS[:100])
RANK = {name: i for i, name in enumerate(REGIONS)}


def make_records(n: int) -> list[dict]:
    tags = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta"]
    out = []
    for i in range(n):
        out.append(
            {
                "id": i,
                "name": f"  Item {i % 977}  ",
                "amount": RNG.randrange(100, 900_00) / 100.0,
                "region": REGIONS[RNG.randrange(200)],
                "tags": [tags[RNG.randrange(6)] for _ in range(3)],
            }
        )
    return out


# Five renderers. Every one produces byte-identical output. They differ only in
# five ordinary habits, removed one at a time, so the console can price each one.


def render_v0(records: list[dict]) -> str:
    """All five habits. Nothing here would be stopped in code review."""
    out = []
    for i in range(len(records)):
        r = copy.deepcopy(records[i])             # 1. a defensive copy nobody needed
        if r["region"] not in list(HOT):          # 2. rebuild a 100-item list, then scan
            continue
        rank = REGIONS.index(r["region"])         # 3. linear scan over 200 strings
        tax = 1.0 + (8.0 / 100.0)                 # 4. constant re-derived per record
        line = ""                                 # 5. eight concatenations, eight strings
        line = line + str(r["id"])
        line = line + "|"
        line = line + r["name"].strip().lower()
        line = line + "|"
        line = line + str(round(r["amount"] * tax, 2))
        line = line + "|"
        line = line + str(rank)
        line = line + "|"
        line = line + ",".join(sorted(r["tags"]))
        out.append(line)
    return "\n".join(out)


def render_v1(records: list[dict]) -> str:
    """v0 minus the defensive deepcopy. Nothing was ever mutated."""
    out = []
    for i in range(len(records)):
        r = records[i]
        if r["region"] not in list(HOT):
            continue
        rank = REGIONS.index(r["region"])
        tax = 1.0 + (8.0 / 100.0)
        line = ""
        line = line + str(r["id"])
        line = line + "|"
        line = line + r["name"].strip().lower()
        line = line + "|"
        line = line + str(round(r["amount"] * tax, 2))
        line = line + "|"
        line = line + str(rank)
        line = line + "|"
        line = line + ",".join(sorted(r["tags"]))
        out.append(line)
    return "\n".join(out)


def render_v2(records: list[dict]) -> str:
    """v1 with both linear scans replaced by hashed lookups: the set is tested
    directly instead of being rebuilt as a list, and the rank comes from a dict
    instead of list.index(). Two O(n) lookups become two O(1) lookups.
    """
    out = []
    for i in range(len(records)):
        r = records[i]
        if r["region"] not in HOT:
            continue
        rank = RANK[r["region"]]
        tax = 1.0 + (8.0 / 100.0)
        line = ""
        line = line + str(r["id"])
        line = line + "|"
        line = line + r["name"].strip().lower()
        line = line + "|"
        line = line + str(round(r["amount"] * tax, 2))
        line = line + "|"
        line = line + str(rank)
        line = line + "|"
        line = line + ",".join(sorted(r["tags"]))
        out.append(line)
    return "\n".join(out)


def render_v3(records: list[dict]) -> str:
    """v2 with the constant hoisted, the globals bound to locals, and one join
    instead of eight concatenations. This is the careful version.
    """
    hot = HOT
    rank_of = RANK
    tax = TAX
    out = []
    append = out.append
    for r in records:
        region = r["region"]
        if region not in hot:
            continue
        append(
            "|".join(
                (
                    str(r["id"]),
                    r["name"].strip().lower(),
                    str(round(r["amount"] * tax, 2)),
                    str(rank_of[region]),
                    ",".join(sorted(r["tags"])),
                )
            )
        )
    return "\n".join(out)


def timed(fn, arg, reps: int = 5) -> tuple[float, str]:
    best = math.inf
    out = ""
    for _ in range(reps):
        t0 = time.perf_counter()
        out = fn(arg)
        best = min(best, time.perf_counter() - t0)
    return best, out


# ------------------------------------------------------------------ main


def main() -> None:
    t_start = time.perf_counter()
    print("one machine — what it actually does, measured on the box this runs on")
    print(f"  python {sys.version.split()[0]}   os.cpu_count() = {os.cpu_count()}   "
          f"page = {os.sysconf('SC_PAGE_SIZE')} B")

    # ---------------------------------------------------------------- 1
    banner(1, "FIND YOUR WALLS — WHAT THIS BOX ACTUALLY DOES PER SECOND")
    cpu_ops = measure_cpu()
    loop_s = measure_loop_overhead()
    mem_bw = measure_mem_bandwidth()
    LAT_MIB = 192
    seq_s, rnd_s = measure_mem_latency(mib=LAT_MIB)
    sys_s = measure_syscall()
    buf_s, fsync_s, fsync_n = measure_writes()

    sys_net = max(sys_s - loop_s, 1e-12)
    print("  wall            what was measured                       cost/op        ceiling")
    print(f"  CPU             interpreter integer op                {secs(1 / cpu_ops)}   {rate(cpu_ops)}")
    print(f"  MEMORY bw       64 MiB bytearray copy                 {secs(1 / (mem_bw / (1 << 20)))}/MiB  "
          f"{mem_bw / 1e9:6.2f} GB/s")
    print(f"  MEMORY lat      random 8 B read, {LAT_MIB} MiB working set  {secs(rnd_s)}   {rate(1 / rnd_s)}")
    print(f"  MEMORY lat      sequential 8 B read, same array       {secs(seq_s)}   {rate(1 / seq_s)}")
    print(f"  I/O syscall     os.write(1 B) to /dev/null            {secs(sys_s)}   {rate(1 / sys_s)}")
    print(f"  I/O buffered    os.write(4 KiB), no flush             {secs(buf_s)}   {rate(1 / buf_s)}")
    print(f"  I/O durable     os.write(4 KiB) + os.fsync()          {secs(fsync_s)}   {rate(1 / fsync_s)}")
    print(f"  NIC             10 GbE line rate (IEEE 802.3, spec)   {'      --':>10}    1.25 GB/s")
    print(f"  the empty-loop baseline is {secs(loop_s)}, so the syscall itself is ~{secs(sys_net)}.")
    print(f"  random reads cost {rnd_s / seq_s:.1f}x sequential ones "
          f"(+{secs(rnd_s - seq_s)} of pure cache miss, {fsync_n} fsyncs sampled).")
    print(f"  durability costs {fsync_s / buf_s:8.0f}x a buffered write. That factor is the whole")
    print("  reason group commit exists (Gray & Reuter 1993, ch. 12).")

    # ---------------------------------------------------------------- 2
    banner(2, "ONE REQUEST, DECOMPOSED — WHICH WALL BINDS FIRST")
    # A synthetic request budget. The COSTS below are chosen (a modelled request);
    # every per-operation price they are multiplied by was measured in section 1.
    SYSCALLS = 12           # accept, 2 reads, 4 writes, epoll_wait, close, log, ...
    MEM_BYTES = 96 * 1024   # parse + serialize + one copy, per request
    CPU_OPS = 8_000         # a light handler's interpreter work
    WIRE_BYTES = 14 * 1024  # response on the wire
    NIC_BPS = 1.25e9        # 10 GbE, IEEE 802.3 line rate — a spec, not a measurement
    CORES = os.cpu_count() or 1

    print(f"  one request = {CPU_OPS:,} interpreter ops + {MEM_BYTES // 1024} KiB of memory")
    print(f"  traffic + {SYSCALLS} syscalls + 1 fsync + {WIRE_BYTES // 1024} KiB on the wire.")
    print(f"  'per core' x{CORES} only for the walls that actually replicate per core.")

    def ceilings(fsyncs_per_req: float) -> list[tuple[str, str, float, bool]]:
        return [
            ("CPU", f"{CPU_OPS:,} interpreter ops", cpu_ops / CPU_OPS, True),
            ("MEMORY bw", f"{MEM_BYTES // 1024} KiB of traffic", mem_bw / MEM_BYTES, False),
            ("I/O syscall", f"{SYSCALLS} syscalls", (1 / sys_s) / SYSCALLS, True),
            ("I/O durable", f"{fsyncs_per_req:g} fsync",
             (1 / fsync_s) / fsyncs_per_req if fsyncs_per_req else math.inf, False),
            ("NIC", f"{WIRE_BYTES // 1024} KiB on the wire", NIC_BPS / WIRE_BYTES, False),
        ]

    box_ceiling = {}
    for label, fsyncs in (("(a) one fsync per request", 1.0),
                          ("(b) group commit, 1 fsync per 128 requests", 1 / 128)):
        rows = [(n, c, x, s, x * CORES if s else x) for n, c, x, s in ceilings(fsyncs)]
        binds = min(rows, key=lambda r: r[4])
        print(f"  {label}")
        print("    wall           cost per request           req/s 1 core   x cores?   req/s this box")
        for name, cost, one, scales, box in rows:
            mark = "  <-- BINDS" if name == binds[0] else ""
            flag = "yes" if scales else "NO "
            print(f"    {name:<14} {cost:<26} {one:12,.0f}   {flag:^8}   {box:12,.0f}{mark}")
        runner_up = min(r[4] for r in rows if r[0] != binds[0])
        box_ceiling[label[:3]] = binds[4]
        print(f"    ceiling {binds[4]:,.0f} req/s, set by {binds[0]}; the next wall is "
              f"{runner_up / binds[4]:.1f}x further out.")
    moved = box_ceiling["(b)"] / box_ceiling["(a)"]
    print(f"  the binding wall MOVED, and the box got {moved:.1f}x faster. No hardware changed.")
    print(f"  one fsync per request is a {1 / fsync_s:,.0f} Hz device pretending to be an architecture.")
    print("  note which walls do NOT multiply by cores: memory bandwidth is one bus, the")
    print("  disk is one queue, the NIC is one link. And CPU only multiplies if you run")
    print("  one worker process per core — a single CPython process does not (Phase 8 L02).")

    # ---------------------------------------------------------------- 3
    banner(3, "THE EFFICIENCY GAP — THE MACHINES YOU DID NOT NEED TO BUY")
    N_RECORDS = 40_000
    ROWS_PER_REQUEST = 400   # a chosen shape: one report response renders 400 rows
    TARGET_RPS = 12_000      # the fleet's actual traffic, from The Problem
    records = make_records(N_RECORDS)

    ladder = [
        ("v0 all five habits", render_v0),
        ("v1 drop the deepcopy", render_v1),
        ("v2 hash, do not scan", render_v2),
        ("v3 hoist + one join", render_v3),
    ]
    results = []
    reference = None
    for name, fn in ladder:
        dt, out = timed(fn, records)
        if reference is None:
            reference = out
        assert out == reference, f"{name} changed the output — not a fair comparison"
        results.append((name, dt, N_RECORDS / dt))

    t0_naive = results[0][1]
    print(f"  {N_RECORDS:,} records -> {len(reference):,} bytes of identical output, best of 5.")
    print(f"  one response renders {ROWS_PER_REQUEST} rows; the fleet must serve {TARGET_RPS:,} req/s.")
    print("    step                       wall time    records/s     req/s   boxes   this fix alone")
    prev = None
    for name, dt, ips in results:
        rps = ips / ROWS_PER_REQUEST
        boxes = math.ceil(TARGET_RPS / rps)
        step = f"{prev / dt:6.2f}x" if prev else "     --"
        print(f"    {name:<26} {secs(dt)}   {ips:10,.0f}   {rps:7,.0f}   {boxes:5d}   {step}")
        prev = dt
    # Report the attribution honestly, including the step that bought nothing.
    steps = [(results[i][0], results[i - 1][1] / results[i][1]) for i in range(1, len(results))]
    big = [n for n, f in steps if f >= 1.5]
    small = [n for n, f in steps if f < 1.05]
    print(f"  the whole win is in: {', '.join(n.split(' ', 1)[1] for n in big)}.")
    if small:
        last = steps[-1]
        print(f"  and {last[0].split(' ', 1)[1]} measured {last[1]:.2f}x — inside the noise.")
        print("  the two habits code review argues about (string concatenation, global")
        print("  lookups) are the two CPython 3.12's specializing interpreter already")
        print("  handles. The two nobody mentions — a defensive copy and a linear scan —")
        print("  were the entire factor. This is why you profile before you optimise")
        print("  (Phase 8 L13) and profile before you provision.")

    total = t0_naive / results[-1][1]
    boxes_naive = math.ceil(TARGET_RPS / (results[0][2] / ROWS_PER_REQUEST))
    boxes_careful = math.ceil(TARGET_RPS / (results[-1][2] / ROWS_PER_REQUEST))
    print(f"  {total:.1f}x end to end. No new dependency, no new algorithm, no C extension,")
    print("  and byte-identical output — the assert above fails the run if it is not.")
    print(f"  at {TARGET_RPS:,} req/s that is {boxes_naive} machines against {boxes_careful}: "
          f"{boxes_naive - boxes_careful} boxes")
    print(f"  that were never a capacity problem. The v0 box serves {results[0][2] / ROWS_PER_REQUEST:,.0f} req/s")
    print("  and looks maxed out. It is not maxed out. It is wasteful, and buying machines")
    print("  makes the waste permanent, load-balanced, and somebody's monthly line item.")

    # ---------------------------------------------------------------- 4
    banner(4, "THE VERTICAL PRICE CURVE (A MODEL, NOT AN INVOICE)")
    # MODEL. Both columns below are assumptions, not measurements:
    #   price   — within an instance family list price is near-linear in vCPU;
    #             the top two rungs (whole-socket / metal) carry a premium.
    #   capacity— a bigger box does not deliver proportionally more work.
    #             1.85x per doubling is a stand-in for contention; Lesson 02
    #             (the Universal Scalability Law) derives the real shape.
    print("  MODELLED, not measured: price factors and the sublinear capacity factor")
    print("  are assumptions. Lesson 02 derives the capacity curve properly.")
    sizes = [2, 4, 8, 16, 32, 64, 128]
    price_step = {4: 2.00, 8: 2.00, 16: 2.00, 32: 2.00, 64: 2.15, 128: 2.60}
    cap_step = 1.85
    price, cap = 1.0, 1.0
    print("    vCPU    price(rel)   capacity(rel)   $ per unit capacity   vs 2 vCPU")
    base_unit = None
    rows4 = []
    for size in sizes:
        if size != 2:
            price *= price_step[size]
            cap *= cap_step
        unit = price / cap
        if base_unit is None:
            base_unit = unit
        rows4.append((size, price, cap, unit, unit / base_unit))
        print(f"    {size:5d}   {price:10.2f}   {cap:13.2f}   {unit:19.3f}   {unit / base_unit:8.2f}x")
    big = rows4[-1]
    fleet = math.ceil(big[2])
    print(f"  scale-out alternative: {big[2]:.2f} units of capacity needs {fleet} x 2-vCPU boxes")
    print(f"  = {fleet:d} price units against the big box's {big[1]:.2f} — "
          f"{big[1] / fleet:.2f}x cheaper per unit of capacity.")
    print(f"  scale-out already wins at the FIRST doubling ({rows4[1][4]:.2f}x worse at 4 vCPU)")
    print("  and never stops winning. So why does anyone still buy the big machine?")
    print("  because this table prices hardware and nothing else.")
    print("  the small-box column omits the load balancer, the cross-AZ bytes, the")
    print("  consistency work, the partial failures and the engineer-years. Vertical")
    print("  scaling's real product is not price/performance — it is a distribution tax")
    print("  of exactly zero. That is the bill the next thirteen lessons itemise.")

    # ---------------------------------------------------------------- 5
    banner(5, "ONE MACHINE IS ONE FAILURE DOMAIN")
    p_up = 0.999
    q_down = 1 - p_up
    year_min = 365.0 * 24 * 60
    print(f"  a machine with {p_up:.1%} annual availability is down {downtime(q_down * year_min)}/year.")
    print("  a machine 64x larger, with the same availability, is down for exactly as long:")
    print("  vertical scaling buys throughput and buys ZERO nines. Redundancy buys nines.")
    print("    replicas" + "".join(f" | {t:<16}" for t in
                                   ("independent", "1% common-mode", "10% common-mode")))
    print("            " + "".join(f" | {'nines':<5}  {'per year':>9}" for _ in range(3)))
    for n in (1, 2, 3, 4):
        cells = ""
        for c in (0.0, 0.01, 0.10):
            # P(all n down) = c * P(one down)  +  (1 - c) * P(one down)^n
            q = c * q_down + (1 - c) * q_down ** n if n > 1 else q_down
            cells += f" | {nines(1 - q)}  {downtime(q * year_min)}"
        print(f"    {n:^8d}{cells}")
    print("  independence is the assumption doing all the work. A shared power feed, a")
    print("  shared deploy, a shared config push, a shared AZ: all of them make c > 0.")
    print("  at c = 10%, two replicas buy you ONE extra nine, not three, and the third and")
    print("  fourth replica buy you nothing at all. Lesson 09 measures correlated failure.")
    print("  and the tax in the other direction, which nobody budgets for:")
    print("    a request that must touch N services, each 99.95% available:")
    for n in (1, 2, 5, 10, 20):
        a = 0.9995 ** n
        print(f"      N = {n:2d}   end-to-end {a * 100:8.4f}%   nines {nines(a)}   "
              f"{downtime((1 - a) * year_min)}/year")
    print("  split one 99.95% machine into 10 services that must ALL answer and you have")
    print("  99.50% — you spent 1.3 nines to buy scalability, and nobody sent an email.")

    print(f"\n  (total wall time {time.perf_counter() - t_start:.1f} s)")


if __name__ == "__main__":
    main()
