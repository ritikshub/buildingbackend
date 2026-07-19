#!/usr/bin/env python3
"""
Thread pools, bounded work queues and futures — built from scratch and measured.

Companion to docs/en.md (Phase 8, Lesson 07). Builds a real ThreadPool (fixed
workers, a BOUNDED queue, a Future carrying a value OR an exception, five
rejection policies, a draining shutdown via poison pills), then measures the two
decisions a pool forces on you: how deep the queue may get (unbounded vs bounded
under identical overload) and how many workers to run (the throughput/latency
knee against a capacity-limited dependency, checked against Little's Law,
L = lambda x W). Also reproduces pool deadlock behind a watchdog so the file
always terminates, and prices the pickling tax of ProcessPoolExecutor.

Standard library only, self-terminating:   python thread_pool.py
"""

from __future__ import annotations

import math
import os
import queue
import random
import statistics
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator

random.seed(20260718)

# ─── Rejection policies: what to do when the bounded queue is full ────────────
# There is no correct default. Each of these is right somewhere and wrong
# everywhere else, which is exactly why the pool must make you choose.
BLOCK = "block"                    # slow the submitter down — backpressure
REJECT = "reject"                  # raise immediately — fail fast / shed load
DISCARD_OLDEST = "discard_oldest"  # drop the stalest queued item — fresh data wins
DISCARD_NEWEST = "discard_newest"  # drop the arriving item — cheapest, silent
CALLER_RUNS = "caller_runs"        # the submitter executes it inline — hard backpressure


class RejectedError(RuntimeError):
    """Raised by submit() under the REJECT policy when the queue is full."""


class CancelledError(RuntimeError):
    """Set on a Future that was discarded or abandoned instead of executed."""


class FutureTimeout(RuntimeError):
    """Future.result(timeout=...) expired. The task may still be running."""


# ─── The Future: the only path an exception has back to the submitter ─────────

class Future:
    """A single-slot mailbox carrying either a value or an exception.

    Without this, an exception raised inside a worker thread is printed to
    stderr by threading's excepthook and lost: the submitter blocks forever or,
    worse, carries on believing the work succeeded.
    """

    __slots__ = ("_ready", "_value", "_exc", "_state")

    def __init__(self) -> None:
        self._ready = threading.Event()
        self._value: Any = None
        self._exc: BaseException | None = None
        self._state = "pending"

    def set_result(self, value: Any) -> None:
        self._value, self._state = value, "done"
        self._ready.set()

    def set_exception(self, exc: BaseException) -> None:
        # The same exception OBJECT crosses the thread boundary, so the
        # worker's traceback is still attached when the submitter re-raises it.
        self._exc, self._state = exc, "failed"
        self._ready.set()

    def cancel(self, reason: str) -> None:
        if self._state == "pending":
            self._exc, self._state = CancelledError(reason), "cancelled"
            self._ready.set()

    def done(self) -> bool:
        return self._ready.is_set()

    @property
    def state(self) -> str:
        return self._state

    def result(self, timeout: float | None = None) -> Any:
        if not self._ready.wait(timeout):
            raise FutureTimeout(f"future not ready after {timeout}s")
        if self._exc is not None:
            raise self._exc
        return self._value


@dataclass
class _Task:
    fn: Callable[..., Any]
    args: tuple
    kwargs: dict
    future: Future
    submitted_at: float
    payload: Any = None  # only used to make the queue's memory cost visible


_POISON = _Task(lambda: None, (), {}, Future(), 0.0)  # the shutdown sentinel


# ─── The pool ─────────────────────────────────────────────────────────────────

@dataclass
class PoolStats:
    submitted: int = 0
    completed: int = 0
    failed: int = 0
    rejected: int = 0
    discarded: int = 0
    abandoned: int = 0
    caller_ran: int = 0
    peak_depth: int = 0
    queue_waits: list = field(default_factory=list)   # dequeue - submit
    latencies: list = field(default_factory=list)     # completion - submit


class ThreadPool:
    """Fixed workers + one bounded queue + a Future per item.

    maxsize=0 means UNBOUNDED, which is what every convenience wrapper gives you
    by default and is measured against a bounded queue in section 2.
    """

    def __init__(
        self,
        workers: int,
        maxsize: int = 0,
        policy: str = BLOCK,
        submit_timeout: float | None = None,
        name: str = "pool",
        daemon: bool = False,
    ) -> None:
        self.workers = workers
        self.maxsize = maxsize
        self.policy = policy
        self.submit_timeout = submit_timeout
        self.stats = PoolStats()
        self._q: queue.Queue[_Task] = queue.Queue(maxsize=maxsize)
        self._lock = threading.Lock()
        self._shutdown = False
        self._threads = [
            threading.Thread(target=self._worker, name=f"{name}-{i}", daemon=daemon)
            for i in range(workers)
        ]
        for t in self._threads:
            t.start()

    # -- worker loop ----------------------------------------------------------
    def _worker(self) -> None:
        while True:
            task = self._q.get()
            if task is _POISON:                 # poison pill: one per worker
                self._q.task_done()
                return
            started = time.perf_counter()
            with self._lock:
                self.stats.queue_waits.append(started - task.submitted_at)
            try:
                value = task.fn(*task.args, **task.kwargs)
            except BaseException as exc:        # noqa: BLE001 - deliberate
                task.future.set_exception(exc)  # the caller decides, not stderr
                with self._lock:
                    self.stats.failed += 1
            else:
                task.future.set_result(value)
                with self._lock:
                    self.stats.completed += 1
            finally:
                with self._lock:
                    self.stats.latencies.append(time.perf_counter() - task.submitted_at)
                self._q.task_done()

    # -- submission -----------------------------------------------------------
    def submit(self, fn: Callable[..., Any], *args: Any, payload: Any = None, **kwargs: Any) -> Future:
        if self._shutdown:
            raise RuntimeError("submit() after shutdown()")
        fut = Future()
        task = _Task(fn, args, kwargs, fut, time.perf_counter(), payload)
        with self._lock:
            self.stats.submitted += 1

        if self.policy == BLOCK:
            try:
                self._q.put(task, block=True, timeout=self.submit_timeout)
            except queue.Full:                  # only reachable with a timeout set
                with self._lock:
                    self.stats.rejected += 1
                fut.cancel("submit timed out waiting for queue space")
                raise RejectedError("queue full: submit timed out") from None
            self._note_depth()
            return fut

        try:
            self._q.put_nowait(task)
            self._note_depth()
            return fut
        except queue.Full:
            pass

        if self.policy == REJECT:
            with self._lock:
                self.stats.rejected += 1
            fut.cancel("rejected: queue full")
            raise RejectedError("queue full: load shed")

        if self.policy == DISCARD_NEWEST:
            with self._lock:
                self.stats.discarded += 1
            fut.cancel("discarded: this item, queue full")
            return fut

        if self.policy == DISCARD_OLDEST:
            while True:
                try:                            # evict the stalest queued item
                    stale = self._q.get_nowait()
                except queue.Empty:
                    pass
                else:
                    self._q.task_done()
                    stale.future.cancel("discarded: newer work arrived")
                    with self._lock:
                        self.stats.discarded += 1
                try:
                    self._q.put_nowait(task)
                    self._note_depth()
                    return fut
                except queue.Full:
                    continue

        if self.policy == CALLER_RUNS:
            with self._lock:
                self.stats.caller_ran += 1
            try:
                fut.set_result(fn(*args, **kwargs))
                with self._lock:
                    self.stats.completed += 1
            except BaseException as exc:        # noqa: BLE001
                fut.set_exception(exc)
                with self._lock:
                    self.stats.failed += 1
            with self._lock:
                self.stats.latencies.append(time.perf_counter() - task.submitted_at)
            return fut

        raise ValueError(f"unknown rejection policy {self.policy!r}")

    def _note_depth(self) -> None:
        d = self._q.qsize()
        with self._lock:
            if d > self.stats.peak_depth:
                self.stats.peak_depth = d

    def map(self, fn: Callable[..., Any], items: Iterable[Any]) -> Iterator[Any]:
        """Submit everything, then yield results IN ORDER (re-raising failures)."""
        futures = [self.submit(fn, item) for item in items]
        for f in futures:
            yield f.result()

    # -- introspection --------------------------------------------------------
    def depth(self) -> int:
        return self._q.qsize()

    def oldest_wait(self) -> float:
        """Age of the oldest queued item — the saturation signal worth exporting."""
        with self._q.mutex:
            if not self._q.queue:
                return 0.0
            oldest = self._q.queue[0].submitted_at
        return time.perf_counter() - oldest

    # -- shutdown -------------------------------------------------------------
    def shutdown(self, wait: bool = True, drain: bool = True, timeout: float = 10.0) -> None:
        """drain=True finishes queued work; drain=False abandons it, but still
        lets the in-flight task finish rather than killing a thread mid-write."""
        self._shutdown = True
        if not drain:
            while True:
                try:
                    task = self._q.get_nowait()
                except queue.Empty:
                    break
                self._q.task_done()
                task.future.cancel("abandoned by shutdown(drain=False)")
                with self._lock:
                    self.stats.abandoned += 1
        for _ in self._threads:
            self._q.put(_POISON)                # exactly one pill per worker
        if wait:
            deadline = time.perf_counter() + timeout
            for t in self._threads:
                t.join(max(0.0, deadline - time.perf_counter()))


# ─── measurement helpers ──────────────────────────────────────────────────────

def pctl(samples: list[float], q: float) -> float:
    if not samples:
        return float("nan")
    s = sorted(samples)
    idx = min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))
    return s[idx]


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# ─── 1 · anatomy ──────────────────────────────────────────────────────────────

def demo_anatomy() -> None:
    banner("1 · A POOL IS FIXED WORKERS + A BOUNDED QUEUE + A FUTURE")
    pool = ThreadPool(workers=3, maxsize=16, name="anatomy")

    def slow_double(n: int) -> int:
        time.sleep(0.01)
        return n * 2

    def explode(n: int) -> int:
        raise ValueError(f"task {n} could not be processed")

    t0 = time.perf_counter()
    doubled = list(pool.map(slow_double, range(12)))
    elapsed = time.perf_counter() - t0
    print(f"  map over 12 tasks x 10ms on 3 workers -> {doubled[:6]}... in {elapsed * 1000:6.1f} ms")
    print(f"  serial would have been 120.0 ms; speedup {120 / (elapsed * 1000):.2f}x (3 workers, ceiling 3.00x)")

    fut = pool.submit(explode, 7)
    try:
        fut.result(timeout=1.0)
    except ValueError as exc:
        tb_depth = 0
        tb = exc.__traceback__
        while tb:
            tb_depth += 1
            tb = tb.tb_next
        print(f"  worker raised -> caller caught {type(exc).__name__}: {exc}")
        print(f"  traceback survived the thread hop ({tb_depth} frames) instead of going to stderr")

    print(f"  future states: done={fut.done()} state={fut.state!r}")
    pool.shutdown(wait=True, drain=True)
    s = pool.stats
    print(f"  shutdown(drain=True): submitted={s.submitted} completed={s.completed} failed={s.failed}")
    print(f"  worker threads still alive after shutdown: {sum(t.is_alive() for t in pool._threads)}")


# ─── 2 · unbounded vs bounded ─────────────────────────────────────────────────

def overload_run(maxsize: int, label: str, seconds: float = 1.0,
                 target_rate: float = 3000.0) -> dict:
    """Submit far faster than 4 workers x 5ms can serve, for a fixed duration."""
    pool = ThreadPool(workers=4, maxsize=maxsize, policy=BLOCK, name=label)

    def unit(_: int) -> None:
        time.sleep(0.005)

    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    t0 = time.perf_counter()
    deadline = t0 + seconds
    n, burst, slot = 0, 6, 0.002       # 6 items every 2 ms -> ~3000 offered/s
    while time.perf_counter() < deadline:
        for _ in range(burst):
            # a queued item is never free: it pins its arguments in memory until
            # it runs. 4 KiB is a modest request body.
            pool.submit(unit, n, payload=bytes(4096))
            n += 1
        time.sleep(slot)
    submit_secs = time.perf_counter() - t0
    peak_mem = tracemalloc.get_traced_memory()[1]
    depth_at_stop = pool.depth()
    oldest = pool.oldest_wait()
    tracemalloc.stop()

    s = pool.stats
    done_lat = list(s.latencies)
    tenth = max(1, len(done_lat) // 10)
    served_rate = s.completed / submit_secs if submit_secs else 0.0
    pool.shutdown(wait=True, drain=False)   # abandon the backlog; never wait it out
    return {
        "label": label,
        "arrival": n / submit_secs,
        "served": served_rate,
        "peak_depth": s.peak_depth,
        "depth_at_stop": depth_at_stop,
        "mib": (peak_mem - base) / 1048576,
        "completed": s.completed,
        "abandoned": s.abandoned,
        "first10": statistics.median(done_lat[:tenth]) * 1000,
        "last10": statistics.median(done_lat[-tenth:]) * 1000,
        "p50": pctl(done_lat, 0.50) * 1000,
        "p99": pctl(done_lat, 0.99) * 1000,
        "oldest": oldest * 1000,
        "drain_s": depth_at_stop / served_rate if served_rate else float("inf"),
    }


def demo_queue_bound() -> None:
    banner("2 · UNBOUNDED QUEUES CONVERT OVERLOAD INTO AN INVISIBLE DELAY LINE")
    print("  identical load: 4 workers x 5 ms of work each (= 800 items/s of capacity),")
    print("  offered at ~3000 items/s for 1.0 s. Only the queue bound differs.")
    print()
    rows = [overload_run(0, "unbounded"), overload_run(64, "bounded(64)")]
    print(f"  {'queue':<12}{'offered/s':>11}{'served/s':>10}{'peak depth':>12}"
          f"{'queue MiB':>11}{'done':>7}{'accepted+lost':>15}")
    for r in rows:
        print(f"  {r['label']:<12}{r['arrival']:>11.0f}{r['served']:>10.0f}"
              f"{r['peak_depth']:>12}{r['mib']:>11.1f}{r['completed']:>7}{r['abandoned']:>15}")
    print()
    print(f"  end-to-end latency, measured FROM SUBMIT (not from start-of-work):")
    print(f"  {'queue':<12}{'p50 ms':>9}{'p99 ms':>9}{'first 10%':>11}{'last 10%':>10}"
          f"{'oldest queued':>15}{'drain s':>9}")
    for r in rows:
        print(f"  {r['label']:<12}{r['p50']:>9.1f}{r['p99']:>9.1f}{r['first10']:>11.1f}"
              f"{r['last10']:>10.1f}{r['oldest']:>15.1f}{r['drain_s']:>9.1f}")
    u, b = rows
    growth = u["mib"] / 1.0
    print()
    print(f"  UNBOUNDED: latency climbed {u['first10']:.0f} ms -> {u['last10']:.0f} ms "
          f"during a single second and had not stopped;")
    print(f"    the queue grew {growth:.1f} MiB/s, so a 2 GiB container OOMs in "
          f"~{2048 / max(growth, 1e-9) / 60:.0f} min of this;")
    print(f"    {u['abandoned']} items were accepted and never run, and the survivors would need "
          f"{u['drain_s']:.1f} s more to drain.")
    print(f"  BOUNDED  : latency flat at {b['first10']:.0f} ms -> {b['last10']:.0f} ms, "
          f"backlog pinned at {b['peak_depth']}, memory {b['mib']:.1f} MiB.")
    print(f"    The queue bound converted the same overload into backpressure: the submitter was")
    print(f"    slowed from {u['arrival']:.0f}/s to {b['arrival']:.0f}/s, which is a signal you can act on.")


# ─── 3 · the sizing curve ─────────────────────────────────────────────────────

class Downstream:
    """A shared dependency with LIMITED CAPACITY — a database, an API, a disk.

    `capacity` requests are served at once; everyone else queues AT THE
    DEPENDENCY. Implemented as a fair c-server queue: each caller is assigned
    the server that frees soonest and sleeps until its own completion instant,
    so the queueing delay is exact and FIFO instead of depending on the
    operating system's (unfair) wakeup order.

    A small coherency penalty proportional to the number of in-flight callers
    models what makes a real throughput curve bend back DOWN past saturation —
    lock convoys, cache pressure, plan contention — rather than merely flatten.
    """

    def __init__(self, capacity: int = 8, service_s: float = 0.008) -> None:
        self.capacity = capacity
        self.service_s = service_s
        self._lock = threading.Lock()
        self._free = [0.0] * capacity     # when each server next becomes idle
        self._inflight = 0
        self.peak_inflight = 0
        self.queue_waits: list[float] = []

    def call(self) -> float:
        arrival = time.perf_counter()
        with self._lock:
            self._inflight += 1
            n = self._inflight
            if n > self.peak_inflight:
                self.peak_inflight = n
            i = min(range(self.capacity), key=lambda k: self._free[k])
            start = max(arrival, self._free[i])
            service = self.service_s * (1.0 + 0.025 * n)
            self._free[i] = start + service
            finish = self._free[i]
            self.queue_waits.append(start - arrival)
        delay = finish - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        with self._lock:
            self._inflight -= 1
        return time.perf_counter() - arrival


def demo_sizing_curve() -> None:
    banner("3 · THE SIZING CURVE: THROUGHPUT PEAKS AND FALLS, LATENCY ONLY RISES")
    print("  I/O-bound tasks against ONE shared dependency: 8 concurrent calls served at once,")
    print("  8 ms each, so the naive ceiling is 8 / 0.008 = 1000 calls/s -- PLUS a contention")
    print("  penalty of 2.5% per concurrent caller, which is why the real peak lands below it.")
    print("  Latency below is the DEPENDENCY call itself: worker pickup -> completion.")
    print()
    print(f"  {'workers':>8}{'tasks':>7}{'thru/s':>9}{'p50 ms':>9}{'p99 ms':>9}"
          f"{'wait@dep ms':>13}   throughput")

    results = []
    for w in (1, 2, 4, 8, 16, 32, 64):
        n = min(560, 80 + 36 * w)
        down = Downstream(capacity=8, service_s=0.008)
        samples: list[float] = []
        slock = threading.Lock()

        def task(_: int) -> None:
            took = down.call()
            with slock:
                samples.append(took)

        pool = ThreadPool(workers=w, maxsize=n + 8, policy=BLOCK, name=f"sz{w}")
        t0 = time.perf_counter()
        futs = [pool.submit(task, i) for i in range(n)]
        for f in futs:
            f.result(timeout=30.0)
        wall = time.perf_counter() - t0
        pool.shutdown(wait=True, drain=True)
        results.append({
            "w": w, "n": n, "thru": n / wall,
            "p50": pctl(samples, 0.50) * 1000,
            "p99": pctl(samples, 0.99) * 1000,
            "wait": statistics.fmean(down.queue_waits) * 1000,
            "peak": down.peak_inflight,
        })

    best = max(results, key=lambda r: r["thru"])
    for r in results:
        bar = "#" * max(1, round(r["thru"] / best["thru"] * 22))
        mark = "  <- knee" if r is best else ""
        print(f"  {r['w']:>8}{r['n']:>7}{r['thru']:>9.0f}{r['p50']:>9.1f}{r['p99']:>9.1f}"
              f"{r['wait']:>13.1f}   {bar}{mark}")

    knee, past, unloaded = best, results[-1], results[0]
    w0 = unloaded["p50"] / 1000.0                 # service time with no queueing
    target = knee["thru"]
    predicted = target * w0
    at_pred = min(results, key=lambda r: abs(r["w"] - predicted))
    print()
    print(f"  Little's Law starting point : to sustain {target:.0f} tasks/s at an UNLOADED service time")
    print(f"    of {w0 * 1000:.1f} ms you need L = lambda x W = {predicted:.1f} workers in flight "
          f"(nearest sweep point: {at_pred['w']}).")
    print(f"  Measured optimum            : {knee['w']} workers -> {knee['thru']:.0f} tasks/s, "
          f"p50 {knee['p50']:.1f} ms, p99 {knee['p99']:.1f} ms, {knee['wait']:.1f} ms queued at the dependency.")
    print()
    print(f"  Now watch the formula stop being useful. At {past['w']} workers W has inflated to "
          f"{past['p50']:.1f} ms,")
    print(f"    of which {past['wait']:.1f} ms is pure queueing AT THE DEPENDENCY. Little's Law still "
          f"balances there")
    print(f"    ({past['thru']:.0f}/s x {past['p50']:.1f} ms = {past['thru'] * past['p50'] / 1000:.1f} "
          f"in flight) -- it is an identity, always true, and it is")
    print(f"    NOT an optimiser. It tells you where to start the sweep; the curve tells you where to stop.")
    print()
    print(f"  Past the knee: {past['w']} workers held {past['thru'] / knee['thru'] * 100:.0f}% of peak "
          f"throughput ({past['thru']:.0f} vs {knee['thru']:.0f}/s) while p50 got "
          f"{past['p50'] / knee['p50']:.1f}x worse and p99 {past['p99'] / knee['p99']:.1f}x worse.")
    print(f"    {past['w'] - knee['w']} extra workers bought 0 throughput and "
          f"+{past['p99'] - knee['p99']:.0f} ms of p99. They bought queue at the dependency.")
    print(f"    The pool size is a CONCURRENCY LIMIT on whatever the pool calls, not a speed dial.")


# ─── 4 · CPU-bound work and the serialization tax ─────────────────────────────

def _cpu_burn(n: int) -> int:
    """Pure-Python arithmetic: holds the GIL, so threads cannot overlap it."""
    total = 0
    for i in range(n):
        total += i * i % 7
    return total


def _echo(payload: bytes) -> int:
    """Round-trips a payload through the pickling pipe and back."""
    return len(payload)


def _timed(fn: Callable[[], Any]) -> float:
    t0 = time.perf_counter()
    fn()
    return time.perf_counter() - t0


def demo_cpu_and_pickling() -> None:
    banner("4 · CPU-BOUND: THREADS DO NOT SCALE, PROCESSES CHARGE POSTAGE")
    cores = os.cpu_count() or 1
    chunk, tasks = 150_000, 16
    print(f"  {tasks} tasks x {chunk:,} iterations of pure-Python arithmetic on {cores} cores")
    print(f"  (best of 3 runs each, because a shared machine's first run is always the slowest)")

    def best_of(fn, reps: int = 3) -> float:
        return min(_timed(fn) for _ in range(reps))

    # 5 reps for the baseline: it is the divisor for every other row, so a single
    # unlucky serial run would inflate every speedup below it.
    serial = best_of(lambda: [_cpu_burn(chunk) for _ in range(tasks)], reps=5)
    print(f"  {'serial (1 thread)':<28}{serial * 1000:>8.0f} ms   1.00x")

    for w in (2, 4, 8):
        def run_threads(w=w):
            pool = ThreadPool(workers=w, maxsize=tasks + 4, name=f"cpu{w}")
            list(pool.map(_cpu_burn, [chunk] * tasks))
            pool.shutdown()
        el = best_of(run_threads)
        print(f"  {f'ThreadPool({w})':<28}{el * 1000:>8.0f} ms   {serial / el:.2f}x")

    for w in (2, 4, 8):
        with ProcessPoolExecutor(max_workers=w) as ex:
            list(ex.map(_cpu_burn, [1] * (w * 2)))            # force the workers to spawn
            el = best_of(lambda: list(ex.map(_cpu_burn, [chunk] * tasks)))
        print(f"  {f'ProcessPool({w})':<28}{el * 1000:>8.0f} ms   {serial / el:.2f}x")

    print()
    print("  the crossover: how big must one task be before a process pool pays for itself?")
    print(f"  {'iters/task':>11}{'us/task':>9}{'serial ms':>11}{'ProcPool(4)':>13}"
          f"{'+chunk=10':>11}{'speedup':>9}   verdict")
    n_tasks = 24
    with ProcessPoolExecutor(max_workers=4) as ex:
        list(ex.map(_cpu_burn, [1] * 12))                     # force the workers to spawn
        for iters in (200, 2_000, 20_000, 100_000):
            ser = min(_timed(lambda: [_cpu_burn(iters) for _ in range(n_tasks)])
                      for _ in range(2))
            par = min(_timed(lambda: list(ex.map(_cpu_burn, [iters] * n_tasks)))
                      for _ in range(2))
            chunked = min(_timed(lambda: list(ex.map(_cpu_burn, [iters] * n_tasks, chunksize=10)))
                          for _ in range(2))
            verdict = "processes win" if par < ser else "postage dominates"
            print(f"  {iters:>11,}{ser / n_tasks * 1e6:>9.0f}{ser * 1000:>11.1f}{par * 1000:>13.1f}"
                  f"{chunked * 1000:>11.1f}{ser / par:>9.2f}   {verdict}")

    print()
    print("  the postage itself: a no-op task, varying argument size (pickle + pipe, round trip)")
    print(f"  {'payload':>11}{'per-call ms':>13}{'MB/s':>10}")
    with ProcessPoolExecutor(max_workers=2) as ex:
        list(ex.map(_echo, [b"x"] * 2))                       # warm
        for size in (64, 64_000, 1_000_000, 4_000_000):
            blob = bytes(size)
            reps = 20 if size < 500_000 else 8
            t0 = time.perf_counter()
            list(ex.map(_echo, [blob] * reps))
            per = (time.perf_counter() - t0) / reps
            print(f"  {size:>10,}B{per * 1000:>13.3f}{size / per / 1e6:>10.1f}")


# ─── 5 · pool deadlock ────────────────────────────────────────────────────────

def demo_pool_deadlock() -> None:
    banner("5 · POOL DEADLOCK: N WORKERS WAITING ON WORK QUEUED BEHIND THEM")
    workers = 4
    # daemon=True purely so a demo of a deadlock can never wedge this file.
    pool = ThreadPool(workers=workers, maxsize=64, name="dead", daemon=True)
    inner_ran = threading.Event()

    def inner(i: int) -> int:
        inner_ran.set()
        time.sleep(0.002)
        return i * 10

    def outer(i: int) -> int:
        sub = pool.submit(inner, i)      # SAME pool
        return sub.result(timeout=1.6)   # and block a worker waiting for it

    t0 = time.perf_counter()
    outers = [pool.submit(outer, i) for i in range(workers)]
    watchdog = 0.9
    done = sum(1 for f in outers if f.done() or _wait_quiet(f, watchdog / len(outers)))
    stalled = time.perf_counter() - t0
    if done < workers:
        print(f"  DEADLOCK: no progress after {stalled:.1f} s "
              f"({done}/{workers} outer tasks done, queue depth {pool.depth()})")
        print(f"  all {workers} workers are blocked inside outer() waiting on inner(),")
        print(f"  and inner() is item #1..{pool.depth()} in the queue BEHIND them. Nothing can move.")
        print(f"  inner() ever started: {inner_ran.is_set()}")
    else:
        print(f"  (no deadlock observed in {stalled:.1f}s — unexpected on this machine)")
    pool.shutdown(wait=False, drain=False)   # workers unblock at their 1.6s timeout

    print()
    print("  FIX A - two pools (a bulkhead): the tier that waits is never the tier that works")
    tier2 = ThreadPool(workers=4, maxsize=64, name="tier2")
    tier1 = ThreadPool(workers=4, maxsize=64, name="tier1")

    def outer2(i: int) -> int:
        return tier2.submit(inner, i).result(timeout=2.0)

    t0 = time.perf_counter()
    got = [f.result(timeout=2.0) for f in [tier1.submit(outer2, i) for i in range(8)]]
    el = (time.perf_counter() - t0) * 1000
    tier1.shutdown(); tier2.shutdown()
    print(f"  8 nested tasks across two pools -> {got} in {el:.1f} ms")

    print()
    print("  FIX B - do not block at all: fold the dependency into one task")
    flat = ThreadPool(workers=4, maxsize=64, name="flat")
    t0 = time.perf_counter()
    got = list(flat.map(lambda i: inner(i), range(8)))
    el = (time.perf_counter() - t0) * 1000
    flat.shutdown()
    print(f"  8 flattened tasks on one pool          -> {got} in {el:.1f} ms")
    print("  the rule: never call .result() on the pool you are currently running inside.")


def _wait_quiet(fut: Future, timeout: float) -> bool:
    try:
        fut.result(timeout=timeout)
        return True
    except BaseException:                                    # noqa: BLE001
        return False


# ─── 6 · rejection policies ───────────────────────────────────────────────────

def demo_rejection_policies() -> None:
    banner("6 · REJECTION POLICIES: FIVE HONEST ANSWERS TO A FULL QUEUE")
    offered, rate, work = 360, 500.0, 0.006
    print(f"  identical overload for each policy: 2 workers x {work * 1000:.0f} ms of work")
    print(f"  (= {2 / work:.0f} items/s of capacity), queue bound 8, {offered} items offered at "
          f"a steady {rate:.0f}/s.")
    print()
    print(f"  {'policy':<16}{'done':>7}{'rejected':>10}{'dropped':>9}{'inline':>8}"
          f"{'wall ms':>9}{'mean age':>10}{'oldest served':>15}")

    for policy in (BLOCK, REJECT, DISCARD_OLDEST, DISCARD_NEWEST, CALLER_RUNS):
        pool = ThreadPool(workers=2, maxsize=8, policy=policy,
                          submit_timeout=0.05 if policy == BLOCK else None,
                          name=policy)
        served_ids: list[int] = []
        idlock = threading.Lock()

        def unit(i: int) -> None:
            time.sleep(work)
            with idlock:
                served_ids.append(i)

        t0 = time.perf_counter()
        for i in range(offered):
            due = t0 + i / rate            # a steady arrival process, not a burst
            slack = due - time.perf_counter()
            if slack > 0:
                time.sleep(slack)
            try:
                pool.submit(unit, i)
            except RejectedError:
                pass
        wall = (time.perf_counter() - t0) * 1000
        pool.shutdown(wait=True, drain=True)
        s = pool.stats
        # "age" is queue time: how stale an item was by the moment a worker
        # finally picked it up. This is the metric to export, not depth.
        age = statistics.fmean(s.queue_waits) * 1000 if s.queue_waits else 0.0
        oldest = max(s.queue_waits) * 1000 if s.queue_waits else 0.0
        assert served_ids or s.completed == 0
        print(f"  {policy:<16}{s.completed:>7}{s.rejected:>10}{s.discarded:>9}"
              f"{s.caller_ran:>8}{wall:>9.0f}{age:>10.1f}{oldest:>15.1f}")

    print()
    print("  BLOCK      : loses nothing, but the submitter is now the queue -- the pressure")
    print("               propagates upstream, which is what you usually want.")
    print("  REJECT     : the fastest, loudest failure, and the only one an upstream can")
    print("               deliberately retry, shed or route elsewhere. Load shedding.")
    print("  DISC.OLDEST: bounded staleness -- right for live prices, positions, sensor reads,")
    print("               metrics, anything where the newest value supersedes the old one.")
    print("  DISC.NEWEST: cheapest to implement and silently biased toward whatever arrived")
    print("               first; the newest (often most relevant) data is what you throw away.")
    print("  CALLER_RUNS: backpressure with zero loss, but the thread that stops is your accept")
    print("               loop -- so the pressure reaches the socket, not just your code.")


def main() -> None:
    t0 = time.perf_counter()
    demo_anatomy()
    demo_queue_bound()
    demo_sizing_curve()
    demo_cpu_and_pickling()
    demo_pool_deadlock()
    demo_rejection_policies()
    print(f"\n(total runtime {time.perf_counter() - t0:.1f} s; "
          f"python {sys.version_info.major}.{sys.version_info.minor}, {os.cpu_count()} cores)")


if __name__ == "__main__":
    main()
