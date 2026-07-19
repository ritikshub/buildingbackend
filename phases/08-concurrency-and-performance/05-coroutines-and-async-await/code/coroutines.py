"""Coroutines and async/await built from the ground up: a stack frame that survives
suspension, a ~40-line scheduler that drives generator-based coroutines on a ready
queue plus a timer heap, a real `async def` stepped by hand with .send(None), and
three measurements -- sequential await vs gather, a blocking call stalling every
concurrent coroutine on the loop, and async's ~1x speedup on CPU-bound work.
Companion to docs/en.md (Phase 8, Lesson 05). Coroutine syntax: PEP 492; delegation
via `yield from`: PEP 380; generator send(): PEP 342. Standard library only.
"""

from __future__ import annotations

import asyncio
import heapq
import random
import statistics
import time
import warnings
from collections import deque

random.seed(8_05)

IO_MS = 100          # the simulated I/O call every measurement uses
IO_COUNT = 10        # how many of them we run
STALL_S = 0.30       # how long the offending coroutine hogs the loop
VICTIMS = 8          # concurrent coroutines sharing the loop with the offender
CPU_N = 1_500_000    # iterations of pure-Python work: ~0.1-0.2 s per call


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# ---------------------------------------------------------------------------
# 1 · A FRAME THAT SURVIVES
# ---------------------------------------------------------------------------

def accumulator(start: int):
    """A resumable function. `yield` suspends it; send() resumes it WITH a value."""
    total = start
    step = 1
    while total < 100:
        received = yield total          # <- suspends here, hands `total` out
        if received is not None:
            step = received             # <- ...and the resumer can hand a value IN
        total += step
    return total


def inner_level():
    """The delegate. It suspends, receives a value, and returns a result."""
    handed_in = yield "inner: I am suspending"
    return f"inner computed {handed_in * 3}"


def outer_level():
    """`yield from` forwards yields OUT, send() values IN, and the return value UP.
    This is exactly what `await` does on the awaitable protocol (PEP 380 -> PEP 492)."""
    result = yield from inner_level()
    return f"outer saw: {result}"


def demo_frames() -> None:
    banner("1 · A FUNCTION CALL IS A FRAME -- A GENERATOR'S FRAME SURVIVES")

    gen = accumulator(10)
    print("  calling accumulator(10) ran no code at all. Object:", type(gen).__name__)
    print(f"  its frame object already exists: {gen.gi_frame is not None}, but nothing has"
          f" run, so its locals are empty: {_locals(gen)}")

    out = next(gen)                     # runs until the first yield
    print(f"  next(gen)        -> yielded {out:>3}   frame locals: {_locals(gen)}")
    out = next(gen)
    print(f"  next(gen)        -> yielded {out:>3}   frame locals: {_locals(gen)}")
    out = gen.send(25)                  # two-way: a value goes back IN
    print(f"  gen.send(25)     -> yielded {out:>3}   frame locals: {_locals(gen)}"
          "   <- step changed, total kept")
    out = gen.send(None)
    print(f"  gen.send(None)   -> yielded {out:>3}   frame locals: {_locals(gen)}")
    try:
        gen.send(None)
    except StopIteration as stop:
        print(f"  gen.send(None)   -> StopIteration(value={stop.value})"
              "   <- the frame finally dies, return value rides on the exception")

    print("\n  yield from, two levels deep:")
    top = outer_level()
    print(f"    next(top)          -> {next(top)!r}      (inner's yield came straight out)")
    try:
        top.send(14)                    # sent to outer, forwarded to inner
    except StopIteration as stop:
        print(f"    top.send(14)       -> StopIteration(value={stop.value!r})")
    print("    one send() crossed two frames and one return value came back up.")


def _locals(gen) -> str:
    frame = gen.gi_frame
    if frame is None:
        return "<frame gone>"
    keep = ("total", "step", "received")
    return "{" + ", ".join(f"{k}={frame.f_locals[k]!r}" for k in keep if k in frame.f_locals) + "}"


# ---------------------------------------------------------------------------
# 2 · A SCHEDULER IN ~40 LINES  (asyncio is not magic)
# ---------------------------------------------------------------------------

class Sleep:
    """A request a coroutine hands to the scheduler: 'resume me in N seconds'."""
    __slots__ = ("seconds",)

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds


class MiniLoop:
    """A ready queue and a timer heap. That is the whole idea behind asyncio."""

    def __init__(self) -> None:
        self.ready: deque = deque()     # coroutines that can run right now
        self.timers: list = []          # heap of (wake_at, seq, coroutine)
        self.seq = 0
        self.t0 = time.perf_counter()

    def now(self) -> float:
        return time.perf_counter() - self.t0

    def spawn(self, coro) -> None:
        self.ready.append(coro)

    def run(self) -> None:
        while self.ready or self.timers:
            # 1. any timer that is due becomes runnable
            while self.timers and self.timers[0][0] <= self.now():
                _, _, due = heapq.heappop(self.timers)
                self.ready.append(due)
            if not self.ready:
                # 2. nothing runnable: sleep until the earliest timer (the loop is idle)
                wake_at, _, coro = heapq.heappop(self.timers)
                delay = wake_at - self.now()
                if delay > 0:
                    time.sleep(delay)
                self.ready.append(coro)
                continue
            # 3. run ONE coroutine until it suspends or finishes
            coro = self.ready.popleft()
            try:
                request = coro.send(None)
            except StopIteration:
                continue                # this coroutine is done; its frame dies here
            if isinstance(request, Sleep):
                self.seq += 1
                heapq.heappush(self.timers, (self.now() + request.seconds, self.seq, coro))
            else:
                self.ready.append(coro)  # a bare yield == "let someone else run"


def mini_fetch(loop: MiniLoop, name: str, ms: int):
    """A 'coroutine' that suspends for I/O and RETURNS a value through yield from."""
    yield Sleep(ms / 1000)
    return f"{name}-payload"


def mini_worker(loop: MiniLoop, name: str, ms: int, steps: int):
    for step in range(1, steps + 1):
        print(f"    t={loop.now() * 1000:6.1f}ms  {name} runs step {step}")
        data = yield from mini_fetch(loop, name, ms)     # <- the ancestor of `await`
        assert data == f"{name}-payload"
    print(f"    t={loop.now() * 1000:6.1f}ms  {name} DONE (got {data!r})")


def demo_mini_loop() -> None:
    banner("2 · A 40-LINE SCHEDULER DRIVING THREE COROUTINES CONCURRENTLY")
    loop = MiniLoop()
    loop.spawn(mini_worker(loop, "A", ms=30, steps=3))
    loop.spawn(mini_worker(loop, "B", ms=50, steps=2))
    loop.spawn(mini_worker(loop, "C", ms=20, steps=4))
    loop.run()
    print(f"  three coroutines, one thread, total wall time {loop.now() * 1000:.1f}ms")
    print("  A+B+C sleep for 90+100+80 = 270ms of 'I/O' -- it overlapped, so the")
    print("  wall time is the LONGEST chain, not the sum.")


# ---------------------------------------------------------------------------
# 3 · DRIVING A REAL `async def` BY HAND
# ---------------------------------------------------------------------------

class Suspend:
    """The awaitable protocol: __await__ returns an iterator. Whatever it yields
    goes to whoever is driving the coroutine -- in asyncio, that is the event loop."""

    def __init__(self, tag: str) -> None:
        self.tag = tag

    def __await__(self):
        handed_back = yield f"<{self.tag}: suspending, please resume me later>"
        return handed_back


async def three_steps(x: int) -> int:
    print(f"    [coro] step 1 running, x={x}")
    first = await Suspend("io-1")
    print(f"    [coro] step 2 resumed with {first!r}")
    y = x * 2
    second = await Suspend("io-2")
    print(f"    [coro] step 3 resumed with {second!r}, locals x={x} y={y}")
    return x + y


def demo_manual_drive() -> None:
    banner("3 · A REAL `async def`, STEPPED BY HAND WITH .send(None)")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        forgotten = three_steps(1)
        print(f"  three_steps(1) returned a {type(forgotten).__name__} and ran NOTHING"
              " (no output above).")
        del forgotten
    msgs = [str(w.message) for w in caught]
    print(f"  dropping it un-awaited: {msgs[0] if msgs else 'RuntimeWarning: never awaited'}")

    coro = three_steps(21)
    step1 = coro.send(None)              # start it; runs to the first await
    print(f"  coro.send(None)  -> loop receives {step1}")
    print(f"                      frame alive? locals now {_cr_locals(coro)}")
    step2 = coro.send("RESULT-A")        # resume it, injecting the awaited value
    print(f"  coro.send('RESULT-A') -> loop receives {step2}")
    print(f"                      frame alive? locals now {_cr_locals(coro)}")
    try:
        coro.send("RESULT-B")
    except StopIteration as stop:
        print(f"  coro.send('RESULT-B') -> StopIteration(value={stop.value})"
              "  <- the coroutine's return")
    print("  That loop of send / catch-StopIteration IS what an asyncio Task does.")


def _cr_locals(coro) -> str:
    frame = coro.cr_frame
    keep = ("x", "y", "first", "second")
    return "{" + ", ".join(f"{k}={frame.f_locals[k]!r}" for k in keep if k in frame.f_locals) + "}"


# ---------------------------------------------------------------------------
# 4 · THE HEADLINE: CONCURRENCY COMES FROM gather, NOT FROM async
# ---------------------------------------------------------------------------

async def fake_io(label: str, seconds: float = IO_MS / 1000) -> str:
    """Stands in for a database round trip or an HTTP call: time spent waiting."""
    await asyncio.sleep(seconds)
    return label


async def measure_sequential_vs_gather() -> tuple[float, float]:
    t0 = time.perf_counter()
    for i in range(IO_COUNT):
        await fake_io(f"req-{i}")        # each await genuinely waits for THIS one
    sequential = time.perf_counter() - t0

    t0 = time.perf_counter()
    await asyncio.gather(*(fake_io(f"req-{i}") for i in range(IO_COUNT)))
    gathered = time.perf_counter() - t0
    return sequential, gathered


async def demo_gather() -> None:
    banner(f"4 · {IO_COUNT} x {IO_MS}ms I/O CALLS: SEQUENTIAL await VS gather")
    sequential, gathered = await measure_sequential_vs_gather()
    print(f"  sequential `await` in a for-loop : {sequential * 1000:7.1f} ms")
    print(f"  asyncio.gather(*coros)           : {gathered * 1000:7.1f} ms")
    print(f"  speedup                          : {sequential / gathered:7.2f}x"
          f"   (ideal ceiling {IO_COUNT}.00x)")
    print(f"  the {IO_COUNT} coroutines are identical. Only the SCHEDULING changed.")

    durations = sorted(round(random.uniform(0.02, 0.12), 3) for _ in range(6))
    random.shuffle(durations)
    print(f"\n  as_completed: results arrive as they finish, not in submission order")
    print(f"  submitted in order: {['%.0fms' % (d * 1000) for d in durations]}")
    t0 = time.perf_counter()
    coros = [fake_io(f"job-{i}({d * 1000:.0f}ms)", d) for i, d in enumerate(durations)]
    for finished in asyncio.as_completed(coros):
        label = await finished
        print(f"    +{(time.perf_counter() - t0) * 1000:6.1f}ms  {label}")

    results = await asyncio.gather(fake_io("ok", 0.01), boom(), return_exceptions=True)
    print(f"  gather(..., return_exceptions=True) -> {results}")


async def boom() -> str:
    await asyncio.sleep(0.01)
    raise ValueError("this coroutine failed")


# ---------------------------------------------------------------------------
# 5 · THE CARDINAL SIN: A BLOCKING CALL INSIDE A COROUTINE
# ---------------------------------------------------------------------------

async def victim(started_at: float, latencies: list[float]) -> None:
    """An unrelated 'endpoint': 50ms of real I/O, then it answers the user."""
    await asyncio.sleep(0.05)
    latencies.append((time.perf_counter() - started_at) * 1000)


async def offender_blocking() -> None:
    time.sleep(STALL_S)                                  # sync call: NOBODY else runs


async def offender_awaiting() -> None:
    await asyncio.sleep(STALL_S)                         # yields: the loop stays free


async def offender_to_thread() -> None:
    await asyncio.to_thread(time.sleep, STALL_S)         # blocking work, off the loop


async def run_scenario(offender) -> list[float]:
    latencies: list[float] = []
    started_at = time.perf_counter()
    tasks = [victim(started_at, latencies) for _ in range(VICTIMS // 2)]
    tasks.append(offender())
    tasks += [victim(started_at, latencies) for _ in range(VICTIMS // 2)]
    await asyncio.gather(*tasks)
    return sorted(latencies)


async def demo_blocking_stall() -> None:
    banner(f"5 · ONE BLOCKING CALL ({STALL_S * 1000:.0f}ms) VS {VICTIMS} UNRELATED COROUTINES")
    for name, offender in (
        ("time.sleep(0.3)          BLOCKING", offender_blocking),
        ("await asyncio.sleep(0.3) YIELDING", offender_awaiting),
        ("await to_thread(sleep)   OFFLOADED", offender_to_thread),
    ):
        lat = await run_scenario(offender)
        spread = " ".join(f"{v:5.0f}" for v in lat)
        print(f"  {name}")
        print(f"    victim latencies (ms): {spread}")
        print(f"    min {min(lat):6.1f}   median {statistics.median(lat):6.1f}"
              f"   max {max(lat):6.1f}   (each victim only ever asked for 50 ms)")
    print("  The blocking call never touched those endpoints. It froze their loop.")


# ---------------------------------------------------------------------------
# 6 · ASYNC IS NOT PARALLEL
# ---------------------------------------------------------------------------

def cpu_work(n: int = CPU_N) -> int:
    h = 0
    for i in range(n):
        h = (h * 31 + i) & 0xFFFFFFFF
    return h


async def cpu_coro() -> int:
    return cpu_work()


async def demo_not_parallel() -> None:
    banner("6 · ASYNC IS NOT PARALLEL: CPU-BOUND WORK ON THE LOOP")
    cpu_work(200_000)                    # warm up, so the two timings are comparable
    seq_runs, gat_runs = [], []
    for _ in range(3):                   # alternate and keep the best of each: this box
        t0 = time.perf_counter()         # is shared, and one slow round would be noise
        for _ in range(4):
            cpu_work()
        seq_runs.append(time.perf_counter() - t0)

        t0 = time.perf_counter()
        await asyncio.gather(*(cpu_coro() for _ in range(4)))
        gat_runs.append(time.perf_counter() - t0)
    sequential, gathered = min(seq_runs), min(gat_runs)

    print(f"  4 x {CPU_N:,}-iteration hash loop, plain sequential calls : {sequential * 1000:7.1f} ms")
    print(f"  the same 4 wrapped in `async def` and gathered           : {gathered * 1000:7.1f} ms")
    print(f"  speedup from asyncio.gather                              : {sequential / gathered:7.2f}x"
          "   (best of 3)")
    print("  Call it 1x. Four cores were available and none of them helped: there is one")
    print("  thread and no await inside cpu_work, so the four coroutines run strictly one")
    print("  after another. Parallelism needs separate processes (Lesson 2), not async.")


# ---------------------------------------------------------------------------

async def async_main() -> None:
    await demo_gather()
    await demo_blocking_stall()
    await demo_not_parallel()


def main() -> None:
    start = time.perf_counter()
    demo_frames()
    demo_mini_loop()
    demo_manual_drive()
    asyncio.run(async_main())            # ONE asyncio.run, at the entry point
    print(f"\ntotal wall time: {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    main()
