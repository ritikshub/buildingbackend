#!/usr/bin/env python3
"""
Processes, threads and the GIL — measured, not asserted.

Companion to docs/en.md (Phase 8, Lesson 02). Standard library only. Prices the
two units of concurrency (thread vs process creation, per-thread memory, one
context switch), then runs the headline experiment: the SAME workload on
1/2/4/8 threads is ~1x when it is pure CPython bytecode and near-linear when it
is I/O or a GIL-releasing C call, while processes scale on both. Ends with
address-space isolation. GIL = Global Interpreter Lock, a CPython implementation
detail (PEP 703 makes it optional); every number below is a property of THIS build.

Runs standalone on the standard library only:  python threads_and_gil.py
"""

from __future__ import annotations

import hashlib
import multiprocessing as mp
import os
import resource
import sys
import threading
import time

# ─── Tunables: sized so every conclusion (the ratios) survives run-to-run noise ──

CPU_TOTAL_ITERS = 12_000_000      # integer ops, split across workers; ~0.5 s serial
ROUNDS = 3                        # every timing is a best-of; noise only ever ADDS time
IO_TASKS, IO_SLEEP = 16, 0.05     # 0.80 s of pure waiting, split across workers
HASH_TASKS, HASH_MB = 40, 24      # 960 MB through sha256; releases the GIL
PINGPONG_ROUNDS = 20_000          # each round trip is two context switches
N_THREAD_SAMPLES = 200
N_FORK_SAMPLES, N_SPAWN_SAMPLES = 50, 10
RESIDENT_THREADS = 200            # held alive at once to measure real memory cost


# ─── Workloads. Module level so multiprocessing can pickle them by name. ─────────


def spin(n: int) -> int:
    """Pure CPython bytecode. Touches no C library that could release the GIL."""
    x = 0
    for i in range(n):
        x += i * i
    return x


def sleep_chunk(count: int) -> None:
    """Blocking I/O, faked. time.sleep() releases the GIL for its whole duration."""
    for _ in range(count):
        time.sleep(IO_SLEEP)


_BUF = b""      # filled in main(); kept empty at import so spawn() stays cheap


def hash_chunk(count: int) -> None:
    """A C extension call. hashlib drops the GIL for buffers over ~2 KB."""
    for _ in range(count):
        hashlib.sha256(_BUF).digest()


def noop() -> None:
    """The cheapest possible unit of work: exists, then exits."""
    return None


COUNTER = 0


def bump_counter(target: int) -> None:
    global COUNTER
    print(f"    child/thread sees COUNTER={COUNTER}, sets it to {target}")
    COUNTER = target


def bump_shared(box) -> None:
    with box.get_lock():
        box.value = 777


# ─── Helpers ────────────────────────────────────────────────────────────────────


def _proc_kb(field: str) -> int | None:
    """VmRSS (resident) / VmSize (virtual address space) for this process, in KB."""
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except OSError:
        pass
    return None


def run_threads(fn, args_list) -> float:
    """Wall time to run every task on its own thread, all started before any join."""
    threads = [threading.Thread(target=fn, args=(a,)) for a in args_list]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - t0


def best_of(measure, rounds: int = ROUNDS) -> float:
    """Fastest of N timed rounds. Scheduler noise can only make a run slower."""
    return min(measure() for _ in range(rounds))


def banner(n: int, claim: str) -> None:
    print(f"\n== {n} · {claim} ==")


def bar(speedup: float, width: int = 40) -> str:
    return "#" * max(1, min(width, round(speedup * 2.4)))


# ─── 0 · Who is running this ────────────────────────────────────────────────────


def section_0() -> None:
    banner(0, "THE MACHINE AND THE INTERPRETER (every number below is theirs)")
    print(f"  python           {sys.version.split()[0]}  ({sys.implementation.name})")
    print(f"  os.cpu_count()   {os.cpu_count()}")
    try:
        print(f"  schedulable CPUs {len(os.sched_getaffinity(0))}   <- what this process may actually use")
    except AttributeError:
        print("  schedulable CPUs unavailable on this platform")
    gil_probe = getattr(sys, "_is_gil_enabled", None)
    if gil_probe is None:
        print("  GIL              enabled (build predates sys._is_gil_enabled, so it cannot be disabled)")
    else:
        print(f"  GIL              {'enabled' if gil_probe() else 'DISABLED (free-threaded build)'}")
    print(f"  switch interval  {sys.getswitchinterval() * 1000:.1f} ms   <- how long a thread may hold the GIL")
    print(f"  start method     {mp.get_start_method()}")


# ─── 1 · What each unit costs to create and to keep ─────────────────────────────


def section_1() -> None:
    banner(1, "A THREAD IS CHEAP, A PROCESS IS NOT — BY HOW MUCH?")

    def time_units(make, count):
        def once() -> float:
            t0 = time.perf_counter()
            for _ in range(count):
                u = make()
                u.start()
                u.join()
            return (time.perf_counter() - t0) / count * 1e6
        return best_of(once)

    fork_ctx, spawn_ctx = mp.get_context("fork"), mp.get_context("spawn")
    thread_us = time_units(lambda: threading.Thread(target=noop), N_THREAD_SAMPLES)
    fork_us = time_units(lambda: fork_ctx.Process(target=noop), N_FORK_SAMPLES)
    spawn_us = time_units(lambda: spawn_ctx.Process(target=noop), N_SPAWN_SAMPLES)

    print(f"  create+start+join a thread          {thread_us:9.1f} us   (n={N_THREAD_SAMPLES})")
    print(f"  create+start+join a fork()ed proc   {fork_us:9.1f} us   (n={N_FORK_SAMPLES})   {fork_us / thread_us:5.1f}x a thread")
    print(f"  create+start+join a spawn()ed proc  {spawn_us:9.1f} us   (n={N_SPAWN_SAMPLES})   {spawn_us / thread_us:5.1f}x a thread")

    stack = threading.stack_size()
    soft, _ = resource.getrlimit(resource.RLIMIT_STACK)
    reserve = stack or (soft if soft > 0 else 8 * 1024 * 1024)
    print(f"\n  threading.stack_size()  {stack}  (0 = platform default)")
    print(f"  RLIMIT_STACK soft       {soft} bytes = {soft / 1024 / 1024:.0f} MiB reserved per thread stack")

    gate = threading.Event()
    rss0, vsz0 = _proc_kb("VmRSS"), _proc_kb("VmSize")
    held = [threading.Thread(target=gate.wait) for _ in range(RESIDENT_THREADS)]
    for t in held:
        t.start()
    time.sleep(0.2)
    rss1, vsz1 = _proc_kb("VmRSS"), _proc_kb("VmSize")
    gate.set()
    for t in held:
        t.join()

    if None not in (rss0, rss1, vsz0, vsz1):
        rss_per = (rss1 - rss0) / RESIDENT_THREADS
        vsz_per = (vsz1 - vsz0) / RESIDENT_THREADS
        print(f"  {RESIDENT_THREADS} idle threads alive at once:")
        print(f"    virtual  +{vsz1 - vsz0:7d} KB = {vsz_per:8.0f} KB/thread  <- address space RESERVED (stack + a malloc arena)")
        print(f"    resident +{rss1 - rss0:7d} KB = {rss_per:8.0f} KB/thread  <- pages actually FAULTED IN")
        print("  extrapolate to 10,000 threads:")
        print(f"    stack reserve alone   {reserve / 1024 / 1024:.0f} MiB x 10,000 = {reserve * 10_000 / 1024**3:7.0f} GiB of address space")
        print(f"    measured virtual              x 10,000 = {vsz_per * 10_000 / 1024**2:7.0f} GiB of address space")
        print(f"    measured resident             x 10,000 = {rss_per * 10_000 / 1024**2:7.2f} GiB of real RAM")
        print("  -> the reservation is unaffordable, the residency is merely expensive. Lesson 03 needs this.")


# ─── 2 · What one context switch costs ──────────────────────────────────────────


def section_2() -> None:
    banner(2, "ONE CONTEXT SWITCH COSTS THOUSANDS OF MEMORY ACCESSES")

    a, b = threading.Event(), threading.Event()

    def pong() -> None:
        for _ in range(PINGPONG_ROUNDS):
            a.wait()
            a.clear()
            b.set()

    partner = threading.Thread(target=pong)
    partner.start()
    t0 = time.perf_counter()
    for _ in range(PINGPONG_ROUNDS):
        a.set()
        b.wait()
        b.clear()
    elapsed = time.perf_counter() - t0
    partner.join()

    per_switch_us = elapsed / (PINGPONG_ROUNDS * 2) * 1e6
    print(f"  {PINGPONG_ROUNDS} ping-pong round trips (2 switches each) in {elapsed:.3f} s")
    print(f"  -> {per_switch_us:.2f} us per forced context switch\n")
    for name, ns in (("L1 cache hit", 1.0), ("main memory (DRAM)", 100.0)):
        print(f"  one switch buys you {per_switch_us * 1000 / ns:9,.0f}  x  {name:<20} (~{ns:.0f} ns, lesson 01)")
    print("  A switch is not 'a bit of overhead'. It is the price of thousands of loads,")
    print("  and that is before the cache pollution the next thread inherits.")


# ─── 3 · The headline: CPU-bound threads do not scale; processes do ─────────────


def section_3() -> None:
    banner(3, "CPU-BOUND: THREADS BUY YOU NOTHING, PROCESSES BUY YOU CORES")
    print(f"  fixed total work: {CPU_TOTAL_ITERS:,} integer ops of pure bytecode\n")

    widths = (1, 2, 4, 8)
    thr, prc = {}, {}

    base_t = None
    print("  THREADS (threading.Thread)")
    for n in widths:
        per = CPU_TOTAL_ITERS // n
        wall = best_of(lambda p=per, k=n: run_threads(spin, [p] * k), rounds=2)
        base_t = base_t if base_t is not None else wall
        thr[n] = base_t / wall
        print(f"    {n:2d} threads   {wall:6.3f} s   speedup {thr[n]:5.2f}x  {bar(thr[n])}")

    fork_ctx = mp.get_context("fork")
    base_p = None
    print("\n  PROCESSES (multiprocessing.Pool, fork)")
    for n in widths:
        per = CPU_TOTAL_ITERS // n
        with fork_ctx.Pool(n) as pool:
            pool.map(spin, [1] * n, chunksize=1)   # warm the workers; startup is not timed

            def one_round(p=pool, w=per, k=n) -> float:
                t0 = time.perf_counter()
                p.map(spin, [w] * k, chunksize=1)
                return time.perf_counter() - t0

            wall = best_of(one_round, rounds=5)
        base_p = base_p if base_p is not None else wall
        prc[n] = base_p / wall
        print(f"    {n:2d} procs     {wall:6.3f} s   speedup {prc[n]:5.2f}x  {bar(prc[n])}")

    print("\n  workers   threads   processes")
    for n in widths:
        print(f"    {n:2d}       {thr[n]:5.2f}x     {prc[n]:5.2f}x")

    handoffs = base_t / sys.getswitchinterval()
    print("\n  Same machine, same cores, same total work. The threads took turns:")
    print(f"  a {base_t:.2f} s run has room for only ~{handoffs:,.0f} forced GIL handoffs at a"
          f" {sys.getswitchinterval() * 1000:.0f} ms switch interval,")
    print("  so the 8 threads were not interleaving finely — they were queueing for one lock.")
    print(f"  (Processes fall short of {widths[-1]}x because this sandbox's vCPUs are shared and")
    print("   not all equally fast. The point is the COLUMN GAP, not the absolute ceiling.)")


# ─── 4 · The mirror image: the same threads, on waiting ─────────────────────────


def section_4() -> None:
    banner(4, "I/O-BOUND: THE SAME THREADS, THE SAME GIL, NEAR-LINEAR SPEEDUP")
    print(f"  fixed total work: {IO_TASKS} tasks x {IO_SLEEP * 1000:.0f} ms of blocking wait"
          f" = {IO_TASKS * IO_SLEEP:.2f} s serial\n")

    base = None
    for n in (1, 2, 4, 8, 16):
        per = IO_TASKS // n
        wall = run_threads(sleep_chunk, [per] * n)
        base = base if base is not None else wall
        print(f"    {n:2d} threads   {wall:6.3f} s   speedup {base / wall:5.2f}x  {bar(base / wall)}")
    print("\n  Nothing about the GIL changed between section 3 and section 4.")
    print("  What changed is whether the thread was HOLDING it while it waited.")


# ─── 5 · The GIL is a mutex around bytecode, and only around bytecode ───────────


def section_5() -> None:
    banner(5, "PROOF IT IS THE BYTECODE LOCK: A C CALL THAT DROPS THE GIL SCALES")
    print(f"  fixed total work: {HASH_TASKS} x sha256 over {HASH_MB} MiB = {HASH_TASKS * HASH_MB} MiB\n")

    base = None
    results = {}
    for n in (1, 2, 4):
        per = HASH_TASKS // n
        wall = run_threads(hash_chunk, [per] * n)
        base = base if base is not None else wall
        results[n] = base / wall
        print(f"    {n:2d} threads   {wall:6.3f} s   speedup {base / wall:5.2f}x  {bar(base / wall)}")

    print(f"\n  hashlib on 4 threads: {results[4]:.2f}x")
    print("  Identical thread code, identical interpreter. The only difference is that")
    print("  sha256_update() wraps its C loop in Py_BEGIN_ALLOW_THREADS and spin() cannot.")


# ─── 6 · One address space, or two ──────────────────────────────────────────────


def section_6() -> None:
    banner(6, "SHARED MEMORY IS THE WHOLE DIFFERENCE BETWEEN A THREAD AND A PROCESS")
    global COUNTER

    COUNTER = 42
    print(f"  parent sets COUNTER={COUNTER}")

    t = threading.Thread(target=bump_counter, args=(99,))
    t.start()
    t.join()
    print(f"  after the THREAD ran:  COUNTER={COUNTER}   <- the write landed in OUR heap\n")

    COUNTER = 42
    fork_ctx = mp.get_context("fork")
    p = fork_ctx.Process(target=bump_counter, args=(777,))
    p.start()
    p.join()
    print(f"  after the PROCESS ran: COUNTER={COUNTER}   <- the child copied our page and wrote to the copy")

    box = fork_ctx.Value("i", 42)
    p = fork_ctx.Process(target=bump_shared, args=(box,))
    p.start()
    p.join()
    print(f"  via mp.Value (real shared memory + a lock): {box.value}   <- sharing across processes is opt-in and explicit")


def main() -> None:
    global _BUF
    started = time.perf_counter()
    section_0()
    section_1()
    section_2()
    section_3()
    section_4()
    _BUF = b"\xa5" * (HASH_MB * 1024 * 1024)
    section_5()
    section_6()
    print(f"\n(total runtime {time.perf_counter() - started:.1f} s)")


if __name__ == "__main__":
    main()
