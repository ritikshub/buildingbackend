#!/usr/bin/env python3
"""Structured concurrency, built from scratch on bare asyncio primitives.

Reproduces the three failure modes of unowned tasks, then builds a ~60-line
nursery (an `asyncio.TaskGroup` equivalent) that makes all three structurally
impossible; measures cancellation latency, deadline propagation across three
service hops, and a bounded graceful shutdown.
Companion to docs/en.md (Phase 8, Lesson 06).
Background: Sustrik, "Structured Concurrency" (2016); Smith, "Notes on
structured concurrency, or: Go statement considered harmful" (2018);
PEP 654 (Exception Groups and except*); PEP 3156 (asyncio).
"""

from __future__ import annotations

import asyncio
import gc
import os
import signal
import time
import weakref
from typing import Any, Awaitable, Callable, Coroutine

T0 = time.perf_counter()
ABANDONED: list[asyncio.Task[Any]] = []      # tasks we deliberately gave up on


def ms(seconds: float) -> str:
    return f"{seconds * 1000:7.1f} ms"


def since_start() -> float:
    return time.perf_counter() - T0


def spin(duration: float) -> None:
    """Burn CPU for `duration` seconds without ever yielding to the event loop."""
    end = time.perf_counter() + duration
    while time.perf_counter() < end:
        pass


def banner(text: str) -> None:
    print(f"\n== {text} ==")


# ---------------------------------------------------------------------------
# 1 · THE THREE FAILURES OF UNOWNED TASKS
# ---------------------------------------------------------------------------

async def bug_a_silent_exception() -> None:
    """A fire-and-forget task raises. Nobody awaits it, so nobody sees it."""
    loop = asyncio.get_running_loop()
    captured: list[dict[str, Any]] = []
    previous = loop.get_exception_handler()
    loop.set_exception_handler(lambda _loop, ctx: captured.append(ctx))

    async def reconcile_ledger() -> None:
        await asyncio.sleep(0.01)
        raise RuntimeError("ledger row 8812 has no matching charge")

    task = asyncio.create_task(reconcile_ledger())
    await asyncio.sleep(0.05)                       # it has already failed by now

    print(f"  fire-and-forget task done={task.done()} exception_seen_by_anyone=False")
    print(f"  the caller returned normally and logged nothing: {captured == []}")

    del task                                        # drop the last reference
    gc.collect()                                    # force Task.__del__ to run
    loop.set_exception_handler(previous)
    for ctx in captured:
        print(f"  loop reported (only at GC time): {ctx['message']!r}")
        print(f"                                   {type(ctx['exception']).__name__}: "
              f"{ctx['exception']}")

    async def awaited() -> None:
        await asyncio.sleep(0.01)
        raise RuntimeError("ledger row 8812 has no matching charge")

    try:
        await asyncio.create_task(awaited())
    except RuntimeError as exc:
        print(f"  the SAME task, awaited -> raises at the await point: RuntimeError: {exc}")


async def bug_b_garbage_collected() -> None:
    """The loop keeps only weak references. An unreferenced task can vanish."""
    loop = asyncio.get_running_loop()
    silenced = loop.get_exception_handler()
    loop.set_exception_handler(lambda _l, _c: None)  # mute "Task was destroyed"

    class Connection:
        """Stands in for an HTTP client connection: it owns the pending-response
        future. Nothing outside the task references it, which is what closes the
        cycle task -> frame -> connection -> future -> callback -> task."""

        def __init__(self) -> None:
            self.pending: asyncio.Future[None] = loop.create_future()

    async def send_webhook(order: int) -> None:
        conn = Connection()
        await conn.pending                          # waiting on the response

    kept: list[asyncio.Task[None]] = []
    kept_refs: list[weakref.ref[asyncio.Task[None]]] = []
    dropped_refs: list[weakref.ref[asyncio.Task[None]]] = []

    for i in range(10):
        t = asyncio.create_task(send_webhook(i))
        kept.append(t)                              # a strong reference we hold
        kept_refs.append(weakref.ref(t))
    for i in range(10):
        t = asyncio.create_task(send_webhook(100 + i))
        dropped_refs.append(weakref.ref(t))
        del t                                       # the classic one-liner bug

    await asyncio.sleep(0)                          # let all 20 start and suspend
    await asyncio.sleep(0)
    before = len(asyncio.all_tasks())
    gc.collect()
    after = len(asyncio.all_tasks())

    alive_kept = sum(r() is not None for r in kept_refs)
    alive_dropped = sum(r() is not None for r in dropped_refs)
    print(f"  20 identical webhook tasks: 10 stored in a list, 10 not stored")
    print(f"  live tasks before gc.collect() = {before}, after = {after}")
    print(f"  still alive:  stored {alive_kept}/10        unstored {alive_dropped}/10")
    print(f"  the 10 collected tasks are unreachable: cannot be awaited, cannot be")
    print(f"  cancelled, will never report anything. In production the GC runs when")
    print(f"  it runs, which is why the webhook 'mostly' fired.")

    for t in kept:
        t.cancel()
    await asyncio.gather(*kept, return_exceptions=True)
    loop.set_exception_handler(silenced)


async def bug_c_orphans_outlive_the_request() -> None:
    """The caller times out and returns 504. Its children never find out."""
    log: list[str] = []

    async def fetch(service: str, latency: float) -> str:
        await asyncio.sleep(latency)
        log.append(f"{service} wrote to the database at t={ms(since_start())}")
        return service

    async def handle_request() -> list[str]:
        children = [
            asyncio.create_task(fetch("inventory", 0.30)),
            asyncio.create_task(fetch("pricing", 0.34)),
            asyncio.create_task(fetch("recommendations", 0.38)),
        ]
        return await asyncio.gather(*children)

    start = time.perf_counter()
    request = asyncio.create_task(handle_request())
    gave_up = 0.0
    try:
        await asyncio.wait_for(asyncio.shield(request), timeout=0.12)
    except TimeoutError:
        gave_up = time.perf_counter() - start
        print(f"  caller gave up and returned 504 after {ms(gave_up)}")
    print(f"  work logged by then: {len(log)}")
    await asyncio.sleep(0.35)
    ABANDONED.append(request)
    print(f"  work logged {ms(time.perf_counter() - start - gave_up)} AFTER the "
          f"request ended: {len(log)}")
    for line in log:
        print(f"    {line}")
    print(f"  three connections and three DB writes belonged to a request that no")
    print(f"  longer exists. Under load this is how in-flight work outgrows served work.")


# ---------------------------------------------------------------------------
# 2 · THE NURSERY  (a from-scratch asyncio.TaskGroup)
# ---------------------------------------------------------------------------

class Nursery:
    """A scope that no child task can outlive.

    On exit every child has completed, failed, or been cancelled. One failure
    cancels the siblings; all failures are re-raised together as an
    ExceptionGroup. `grace` bounds how long exit will wait after cancelling.
    """

    def __init__(self, grace: float | None = None) -> None:
        self._children: set[asyncio.Task[Any]] = set()
        self._errors: list[BaseException] = []
        self._parent: asyncio.Task[Any] | None = None
        self._aborting = False
        self._exited = False
        self._parent_cancelled = False
        self._grace = grace
        self.abandoned: list[asyncio.Task[Any]] = []

    async def __aenter__(self) -> "Nursery":
        self._parent = asyncio.current_task()
        return self

    def start_soon(self, coro: Coroutine[Any, Any, Any]) -> asyncio.Task[Any]:
        if self._aborting:
            coro.close()
            raise RuntimeError("nursery is shutting down; cannot start new work")
        task = asyncio.create_task(coro)
        self._children.add(task)                 # a STRONG ref: bug (b) impossible
        task.add_done_callback(self._child_done)
        return task

    def _child_done(self, task: asyncio.Task[Any]) -> None:
        self._children.discard(task)
        if task.cancelled():
            return
        exc = task.exception()                   # ALWAYS retrieved: bug (a) impossible
        if exc is not None:
            self._errors.append(exc)
            self._abort()

    def cancel_scope(self) -> None:
        """Cancel every child on purpose. Not a failure: no error is recorded.
        This is Trio's `nursery.cancel_scope.cancel()`; `asyncio.TaskGroup` has
        no equivalent, which is why shutdown code there raises instead."""
        self._aborting = True
        for child in self._children:
            child.cancel()

    def _abort(self) -> None:
        if self._aborting:
            return
        self._aborting = True
        for child in self._children:
            child.cancel()                       # a cancellation path: bug (c) impossible
        if self._parent is not None and not self._exited and not self._parent.done():
            self._parent_cancelled = True
            self._parent.cancel()                # interrupt the body of the block

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        self._exited = True
        swallow = self._parent_cancelled and exc_type is asyncio.CancelledError
        if exc is not None and not swallow:
            self._errors.append(exc)
        if exc is not None or self._errors:
            self._abort()
        cancelled_from_outside = False
        while self._children:
            pending = set(self._children)
            try:
                _, still = await asyncio.wait(pending, timeout=self._grace)
            except asyncio.CancelledError:
                cancelled_from_outside = True
                self._abort()
                continue
            if still and self._grace is not None:
                for task in still:               # grace expired: force and abandon
                    task.cancel()
                    self.abandoned.append(task)
                    self._children.discard(task)
                break
        if swallow:
            self._parent.uncancel()              # type: ignore[union-attr]
        if self._errors:
            errors, self._errors = self._errors, []
            raise BaseExceptionGroup("unhandled errors in nursery", errors)
        if cancelled_from_outside:
            raise asyncio.CancelledError()
        return swallow


async def nursery_fixes_bug_a() -> None:
    async def failing(name: str) -> None:
        await asyncio.sleep(0.05)
        raise RuntimeError(f"{name} exploded")

    async def slow(name: str, log: list[str]) -> None:
        await asyncio.sleep(0.50)
        log.append(f"{name} completed")           # must never happen

    log: list[str] = []
    start = time.perf_counter()
    try:
        async with Nursery() as n:
            n.start_soon(failing("ledger"))
            n.start_soon(failing("payouts"))
            n.start_soon(slow("report", log))
    except* RuntimeError as group:
        print(f"  the block RAISED after {ms(time.perf_counter() - start)}: "
              f"{len(group.exceptions)} sibling failures, none silent")
        for sub in group.exceptions:
            print(f"    {type(sub).__name__}: {sub}")
    print(f"  the slow sibling was cancelled at the first failure: "
          f"log={log} (it needed 500 ms, the block took {ms(time.perf_counter() - start)})")


async def nursery_fixes_bug_b() -> None:
    loop = asyncio.get_running_loop()

    async def send_webhook(order: int) -> None:
        pending: asyncio.Future[None] = loop.create_future()
        await pending

    refs: list[weakref.ref[asyncio.Task[None]]] = []
    async with Nursery(grace=0.05) as n:
        for i in range(10):
            refs.append(weakref.ref(n.start_soon(send_webhook(i))))
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        gc.collect()
        alive = sum(r() is not None for r in refs)
        print(f"  10 tasks started with start_soon(), gc.collect() forced: "
              f"{alive}/10 still alive")
        print(f"  the nursery holds a strong reference to every child, so there is no")
        print(f"  cycle to collect. The bug is not 'avoided', it is unreachable.")
        n.cancel_scope()


async def nursery_fixes_bug_c() -> None:
    log: list[str] = []

    async def fetch(service: str, latency: float) -> None:
        await asyncio.sleep(latency)
        log.append(f"{service} wrote to the database")

    start = time.perf_counter()
    try:
        async with asyncio.timeout(0.12):
            async with Nursery() as n:
                n.start_soon(fetch("inventory", 0.30))
                n.start_soon(fetch("pricing", 0.34))
                n.start_soon(fetch("recommendations", 0.38))
    except TimeoutError:
        gave_up = time.perf_counter() - start
        print(f"  caller returned 504 after {ms(gave_up)}")
    await asyncio.sleep(0.35)
    print(f"  work logged {ms(time.perf_counter() - start - gave_up)} AFTER the "
          f"request ended: {len(log)}  (was 3)")
    print(f"  the timeout cancelled the SCOPE, and the scope owns the children.")


# ---------------------------------------------------------------------------
# 3 · CANCELLATION SEMANTICS, MEASURED
# ---------------------------------------------------------------------------

async def cancellation_latency() -> None:
    """CancelledError is raised at the NEXT await, so the gap between awaits
    is your cancellation latency."""
    print("  a 100 ms timeout over a loop that spins for `chunk` between awaits:")
    print("    chunk       requested   actual    overshoot")
    for chunk in (0.001, 0.030, 0.400):
        async def work() -> None:
            while True:
                spin(chunk)
                await asyncio.sleep(0)            # the only cancellation point

        start = time.perf_counter()
        try:
            async with asyncio.timeout(0.100):
                await work()
        except TimeoutError:
            pass
        actual = time.perf_counter() - start
        print(f"    {chunk * 1000:6.0f} ms      100.0 ms  {ms(actual)}  "
              f"{ms(actual - 0.100)}")
    print("  a coroutine that never awaits cannot be cancelled: the loop cannot even")
    print("  run the timer callback until the CPU comes back.")


async def cleanup_on_cancellation() -> None:
    pool = {"in_use": 0, "released": 0}

    async def leaky() -> None:
        pool["in_use"] += 1
        await asyncio.sleep(1.0)
        pool["in_use"] -= 1

    async def correct() -> None:
        pool["in_use"] += 1
        try:
            await asyncio.sleep(1.0)
        finally:
            pool["in_use"] -= 1
            pool["released"] += 1

    for name, body in (("no try/finally", leaky), ("try/finally  ", correct)):
        pool["in_use"] = pool["released"] = 0
        tasks = [asyncio.create_task(body()) for _ in range(3)]
        await asyncio.sleep(0.02)
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print(f"  {name}: connections still checked out after cancel = {pool['in_use']}, "
              f"released = {pool['released']}")


async def swallowing_cancelled_error() -> None:
    async def run(swallow: bool) -> tuple[str, float]:
        async def work() -> str:
            try:
                await asyncio.sleep(0.60)
            except asyncio.CancelledError:
                if not swallow:
                    raise                          # the only correct move
                # "we cleaned up, everything is fine" -- and the timeout is gone
            await asyncio.sleep(0.30)              # still running past the deadline
            return "completed"

        start = time.perf_counter()
        try:
            async with asyncio.timeout(0.15):
                result = await work()
        except TimeoutError:
            result = "TimeoutError"
        return result, time.perf_counter() - start

    timings = {}
    for swallow in (False, True):
        label = "swallows CancelledError" if swallow else "re-raises CancelledError"
        result, elapsed = await asyncio.create_task(run(swallow))
        timings[swallow] = elapsed
        print(f"  150 ms timeout, coroutine {label}: -> {result:>13} after {ms(elapsed)}")
    print(f"  swallowing does not 'handle' the timeout; it deletes it. A 150 ms")
    print(f"  contract silently became {ms(timings[True])} "
          f"({timings[True] / 0.150:.1f}x) and the caller was never told.")


async def shielded_cleanup() -> None:
    """A `finally` that awaits can itself be cancelled. shield() keeps the WORK
    alive even when the WAIT is cancelled."""
    for shielded in (False, True):
        released: list[str] = []

        async def release() -> None:
            await asyncio.sleep(0.05)              # an abort/rollback round trip
            released.append("connection returned to pool")

        async def work() -> None:
            try:
                await asyncio.sleep(1.0)
            finally:
                if shielded:
                    await asyncio.shield(asyncio.create_task(release()))
                else:
                    await release()

        task = asyncio.create_task(work())
        await asyncio.sleep(0.02)
        task.cancel()                              # lands on the outer sleep
        await asyncio.sleep(0)                     # let it enter the finally
        task.cancel()                              # a second cancel lands in cleanup
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0.10)                  # give any shielded work time
        label = "await shield(task)" if shielded else "bare await        "
        print(f"  cleanup with {label}: released = {released}")


# ---------------------------------------------------------------------------
# 4 · DEADLINE PROPAGATION ACROSS THREE HOPS
# ---------------------------------------------------------------------------

HOPS = [("gateway", 0.12), ("auth", 0.17), ("profile", 0.45)]


async def run_chain(per_hop: float | None, budget: float,
                    tail_work: float) -> tuple[str, float, float]:
    """Simulate three services calling each other across process boundaries.

    Each hop runs in its own task and each downstream call is `shield`ed, so a
    caller giving up does NOT reach the callee -- exactly like a client closing
    a socket while the server keeps computing. With `per_hop` set, every hop
    starts a fresh timer; with `per_hop=None` one absolute deadline is threaded
    through and shrinks at every hop.
    """
    loop = asyncio.get_running_loop()
    start = loop.time()
    deadline = start + budget
    last_active = {"t": start}
    budgets: list[str] = []
    spawned: list[asyncio.Task[str]] = []
    work = [w for _, w in HOPS[:-1]] + [tail_work]

    async def server(index: int) -> str:
        allowance = per_hop if per_hop is not None else deadline - loop.time()
        budgets.append(f"{HOPS[index][0]} {allowance * 1000:.0f}ms")
        try:
            async with asyncio.timeout(allowance):
                await asyncio.sleep(work[index])
                if index + 1 < len(HOPS):
                    downstream = asyncio.create_task(server(index + 1))
                    spawned.append(downstream)
                    return await asyncio.shield(downstream)
                return "ok"
        finally:
            last_active["t"] = max(last_active["t"], loop.time())

    task = asyncio.create_task(server(0))
    spawned.append(task)
    try:
        async with asyncio.timeout(per_hop if per_hop is not None else budget):
            result = await asyncio.shield(task)
    except TimeoutError:
        result = "504 to the user" if per_hop is not None else "DeadlineExceeded"
    client_gave_up = loop.time() - start
    print(f"    hop budgets: {'  '.join(budgets)}")
    await asyncio.sleep(0.40)                       # watch for orphans
    for t in spawned:                               # retrieve every exception
        t.cancel()
    await asyncio.gather(*spawned, return_exceptions=True)
    return result, client_gave_up, last_active["t"] - start


# ---------------------------------------------------------------------------
# 5 · BOUNDED GRACEFUL SHUTDOWN
# ---------------------------------------------------------------------------

async def graceful_shutdown(grace: float) -> None:
    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    cleaned: list[int] = []

    try:
        loop.add_signal_handler(signal.SIGTERM, stop.set)
        real_signal = True
    except (NotImplementedError, RuntimeError):
        real_signal = False

    async def worker(i: int, cleanup_cost: float) -> None:
        try:
            while True:
                await asyncio.sleep(0.04)          # one unit of real work
        finally:
            await asyncio.sleep(cleanup_cost)      # flush, commit, close
            cleaned.append(i)

    start = time.perf_counter()
    nursery = Nursery(grace=grace)
    async with nursery as n:
        for i in range(6):
            n.start_soon(worker(i, 0.06))
        n.start_soon(worker(99, 2.0))              # a worker that will not stop
        if real_signal:
            os.kill(os.getpid(), signal.SIGTERM)
        else:
            loop.call_soon(stop.set)
        await stop.wait()
        print(f"  SIGTERM received at {ms(time.perf_counter() - start)} "
              f"(real signal handler: {real_signal})")
        print(f"  stopped accepting; cancelling the scope, grace = {grace * 1000:.0f} ms")
        n.cancel_scope()                           # every child, at once
    elapsed = time.perf_counter() - start
    if real_signal:
        loop.remove_signal_handler(signal.SIGTERM)
    ABANDONED.extend(nursery.abandoned)
    print(f"  workers that ran cleanup cleanly: {len(cleaned)}/7  -> {sorted(cleaned)}")
    print(f"  abandoned after the grace period : {len(nursery.abandoned)} "
          f"(worker 99, whose cleanup needs 2000 ms)")
    print(f"  total shutdown time              : {ms(elapsed)} "
          f"(bounded by grace, not by the worst worker)")


# ---------------------------------------------------------------------------

async def main() -> None:
    banner("1 · THE THREE FAILURES OF UNOWNED TASKS")
    print(" (a) an exception nobody retrieves")
    await bug_a_silent_exception()
    print(" (b) a task nobody references")
    await bug_b_garbage_collected()
    print(" (c) children nobody can cancel")
    await bug_c_orphans_outlive_the_request()

    banner("2 · THE SAME THREE SCENARIOS INSIDE A NURSERY")
    print(" (a) failures are re-raised as a group at the block's closing brace")
    await nursery_fixes_bug_a()
    print(" (b) children are strongly referenced for the life of the scope")
    await nursery_fixes_bug_b()
    print(" (c) a timeout on the scope reaches every child")
    await nursery_fixes_bug_c()

    banner("3 · CANCELLATION IS AN EXCEPTION, NOT A KILL")
    await cancellation_latency()
    print(" cleanup:")
    await cleanup_on_cancellation()
    print(" swallowing CancelledError defeats every timeout above it:")
    await swallowing_cancelled_error()
    print(" a finally that awaits can itself be cancelled:")
    await shielded_cleanup()

    banner("4 · DEADLINE PROPAGATION VS FRESH TIMEOUTS")
    print(" (a) a fresh 500 ms timeout at every hop")
    result, gave_up, last = await run_chain(0.500, 0.500, 0.45)
    print(f"    client result: {result} at {ms(gave_up)}")
    print(f"    downstream kept working until {ms(last)} "
          f"-> {ms(last - gave_up)} of orphaned work")
    print(" (b) one absolute 500 ms deadline, propagated and shrinking")
    result, gave_up, last = await run_chain(None, 0.500, 0.45)
    print(f"    client result: {result} at {ms(gave_up)}")
    print(f"    downstream kept working until {ms(last)} "
          f"-> {ms(max(0.0, last - gave_up))} of orphaned work")
    print(" (c) the same propagated deadline, when the tail hop is fast (150 ms)")
    result, gave_up, last = await run_chain(None, 0.500, 0.15)
    print(f"    client result: {result} at {ms(gave_up)} -- inside budget")

    banner("5 · BOUNDED GRACEFUL SHUTDOWN")
    await graceful_shutdown(grace=0.35)

    for task in ABANDONED:
        task.cancel()
    await asyncio.gather(*ABANDONED, return_exceptions=True)
    print(f"\nTotal wall time: {ms(since_start())}")


if __name__ == "__main__":
    asyncio.run(main())
