#!/usr/bin/env python3
"""
Testing asynchronous, event-driven backends measured rather than argued: the
completion-time distribution behind every `time.sleep()` in a suite, the
two-dimensional flakiness-versus-duration trap a fixed sleep can never escape,
a polling primitive that reports the LAST error instead of "timed out", a
virtual clock that runs 1,200 seconds of sleeping in zero, duplicate delivery
corrupting state without an idempotency key, every permutation of one event set
against four invariants, an exact retry/backoff/DLQ schedule including the retry
that duplicates a write, and the forgotten `await` that makes a test pass.

Companion to docs/en.md (Phase 12, Lesson 11). Standard library only, every RNG
seeded with random.Random(20260718), no network, no files written,
self-terminating in about three seconds. Sources: Fischer, Lynch & Paterson,
*Impossibility of Distributed Consensus with One Faulty Process*, JACM 32(2),
1985; Lamport, *Time, Clocks, and the Ordering of Events in a Distributed
System*, CACM 21(7), 1978; PEP 492, *Coroutines with async and await syntax*,
2015; RFC 9110, *HTTP Semantics*, 2022 (§15.3.3 the 202 Accepted status code);
RFC 6298, *Computing TCP's Retransmission Timer*, 2011 (§5, backoff doubling).

Run:  python3 async_testing.py
"""

from __future__ import annotations

import asyncio
import heapq
import inspect
import itertools
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

SEED = 20260718

# The suite this lesson keeps pricing: 500 asynchronous assertions in one CI run.
SUITE_TESTS = 500
CALIBRATION_SAMPLES = 200_000


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def fmt_secs(s: float) -> str:
    """Seconds, in the unit a human would use, so tables stay readable."""
    if s < 1.0:
        return f"{s * 1000:.0f} ms"
    if s < 90.0:
        return f"{s:.1f} s"
    return f"{s / 60:.1f} min"


# ══ THE SYSTEM UNDER TEST ════════════════════════════════════════════════════
# `POST /orders` returns 202 Accepted (RFC 9110 §15.3.3): the request was
# accepted for processing, and processing has not completed. Between the 202
# and the row appearing in the read model there is a queue, a consumer, a
# database write and a projection. The test wants to assert on the row.
#
# How long that takes is a DISTRIBUTION, not a number. This one is drawn from
# a lognormal body (the ordinary path: enqueue, dequeue, handle, commit) with
# two additive tails: a retried delivery, and a consumer-group stall.

def draw_completion(rng: random.Random) -> float:
    """One end-to-end completion time, in seconds."""
    t = rng.lognormvariate(math.log(0.040), 0.50)   # ordinary path, median 40 ms
    roll = rng.random()
    if roll < 0.002:
        t += rng.uniform(1.0, 3.0)                  # consumer rebalance / GC stall
    elif roll < 0.022:
        t += rng.uniform(0.15, 0.50)                # one retry with backoff
    return t


def sample_completions(n: int, seed: int) -> List[float]:
    rng = random.Random(seed)
    return [draw_completion(rng) for _ in range(n)]


def quantile(sorted_xs: Sequence[float], q: float) -> float:
    """Nearest-rank quantile. No interpolation: every value printed is a value
    that was actually observed, which matters when the whole argument is about
    what the tail really contains."""
    idx = min(len(sorted_xs) - 1, max(0, math.ceil(q * len(sorted_xs)) - 1))
    return sorted_xs[idx]


# ══ 1 · THE COMPLETION-TIME DISTRIBUTION ═════════════════════════════════════

CALIBRATION = sorted(sample_completions(CALIBRATION_SAMPLES, SEED))

PCTS = (0.50, 0.90, 0.99, 0.999)
P50 = quantile(CALIBRATION, 0.50)
P999 = quantile(CALIBRATION, 0.999)


def section1() -> None:
    banner(1, "WHAT A time.sleep() IS ACTUALLY A GUESS ABOUT")
    print(f"  {CALIBRATION_SAMPLES:,} end-to-end completions of one POST /orders -> row visible.")
    print("  A fixed sleep is a horizontal line drawn across this distribution:")
    print("  everything to the right of it is a flaky test.\n")

    print("    quantile      completion      multiple of p50   what lives out here")
    notes = {
        0.50: "the ordinary path: enqueue, handle, commit",
        0.90: "still the ordinary path, slightly unlucky",
        0.99: "one redelivery, one backoff",
        0.999: "a consumer-group rebalance or a GC pause",
    }
    for q in PCTS:
        v = quantile(CALIBRATION, q)
        print(f"    p{q * 100:<11.6g} {fmt_secs(v):>10}      {v / P50:>13.1f}x   {notes[q]}")
    worst = CALIBRATION[-1]
    print(f"    {'max':<12} {fmt_secs(worst):>10}      {worst / P50:>13.1f}x   "
          f"the slowest of {CALIBRATION_SAMPLES:,}")

    print(f"\n  p99.9 is {P999 / P50:.0f}x the median. That ratio is the whole problem:")
    print("  a sleep sized for the median is wrong one time in two, and a sleep")
    print("  sized for the tail is wrong-by-waiting on every single run.")

    # A histogram, so the shape is visible and not merely asserted.
    print("\n  where the mass actually sits:")
    edges = [0.0, 0.025, 0.040, 0.060, 0.090, 0.150, 0.400, 1.000, 3.500]
    for lo, hi in zip(edges, edges[1:]):
        n = sum(1 for x in CALIBRATION if lo <= x < hi)
        bar = "#" * max(0, round(60 * n / CALIBRATION_SAMPLES))
        print(f"    {fmt_secs(lo):>7} - {fmt_secs(hi):>7}  {n / CALIBRATION_SAMPLES:6.2%}  {bar}")
    print("  97.8% of runs finish inside 150 ms. The suite is not paced by those.")


# ══ 2 · SLEEP VERSUS POLL, IN TWO DIMENSIONS ═════════════════════════════════
# The headline experiment. For each candidate strategy, measure BOTH axes over
# the same out-of-sample suite: how often does it flake, and how long does the
# whole suite take. A fixed sleep can move along the curve. It cannot leave it.

POLL_INTERVAL = 0.010     # 10 ms between polls
POLL_QUERY_COST = 0.001   # each poll costs a real query
POLL_TIMEOUT = 10.0


@dataclass
class SuiteResult:
    label: str
    per_test_flake: float
    suite_seconds: float
    build_green: float
    empirical_build_green: float


def run_fixed_sleep(completions: Sequence[float], sleep_for: float) -> Tuple[int, float]:
    """A suite of `sleep(S); assert ...`. Every test pays S. A test flakes when
    the system had not finished by S."""
    flakes = sum(1 for c in completions if c > sleep_for)
    return flakes, sleep_for * len(completions)


def run_polling(completions: Sequence[float], interval: float = POLL_INTERVAL,
                timeout: float = POLL_TIMEOUT) -> Tuple[int, float, float]:
    """A suite of `eventually(...)`. Each test returns as soon as the condition
    holds, so it pays roughly its own completion time — plus the cost of the
    polls it issued. A test flakes only if the system exceeds the timeout."""
    flakes = 0
    total = 0.0
    polls = 0
    step = interval + POLL_QUERY_COST
    for c in completions:
        n = max(1, math.ceil(c / step))
        elapsed = n * step
        if elapsed > timeout:
            n = math.ceil(timeout / step)
            elapsed = timeout
            flakes += 1
        polls += n
        total += elapsed
    return flakes, total, polls / len(completions)


BUILDS = 200


def section2() -> Tuple[List[SuiteResult], float, float]:
    banner(2, "THE TWO-DIMENSIONAL TRAP: FLAKINESS x DURATION")
    print(f"  one CI run = {SUITE_TESTS} asynchronous assertions, drawn out-of-sample from")
    print("  the same distribution the sleeps were calibrated against.")
    print(f"  a build is green only if ALL {SUITE_TESTS} tests pass, so this measures")
    print(f"  {BUILDS} independent builds = {BUILDS * SUITE_TESTS:,} test runs per strategy.\n")

    results: List[SuiteResult] = []
    builds = [sample_completions(SUITE_TESTS, SEED + 100 + i) for i in range(BUILDS)]
    all_tests = [c for b in builds for c in b]

    strategies: List[Tuple[str, float]] = [
        (f"sleep(p50)   = {fmt_secs(quantile(CALIBRATION, 0.50))}", quantile(CALIBRATION, 0.50)),
        (f"sleep(p90)   = {fmt_secs(quantile(CALIBRATION, 0.90))}", quantile(CALIBRATION, 0.90)),
        (f"sleep(p99)   = {fmt_secs(quantile(CALIBRATION, 0.99))}", quantile(CALIBRATION, 0.99)),
        (f"sleep(p99.9) = {fmt_secs(quantile(CALIBRATION, 0.999))}", quantile(CALIBRATION, 0.999)),
    ]

    print("    strategy                  per-test flake   suite time   P(build green)   measured")
    for label, s in strategies:
        flakes, _ = run_fixed_sleep(all_tests, s)
        f = flakes / len(all_tests)
        secs = s * SUITE_TESTS
        analytic = (1 - f) ** SUITE_TESTS
        emp = sum(1 for b in builds if all(c <= s for c in b)) / len(builds)
        results.append(SuiteResult(label, f, secs, analytic, emp))
        print(f"    {label:<24}  {f:>13.3%}   {fmt_secs(secs):>10}   {analytic:>13.1%}   "
              f"{emp:>8.1%}")

    pflakes, ptotal, avg_polls = run_polling(all_tests)
    pf = pflakes / len(all_tests)
    psecs = ptotal / BUILDS
    p_analytic = (1 - pf) ** SUITE_TESTS
    p_emp = sum(1 for b in builds if run_polling(b)[0] == 0) / len(builds)
    poll_label = "eventually(10 ms, 10 s)"
    results.append(SuiteResult(poll_label, pf, psecs, p_analytic, p_emp))
    print(f"    {poll_label:<24}  {pf:>13.3%}   {fmt_secs(psecs):>10}   "
          f"{p_analytic:>13.1%}   {p_emp:>8.1%}")

    print(f"\n  the polling suite issued {avg_polls:.1f} polls per test on average and finished")
    print(f"  in {fmt_secs(psecs)} with a {p_emp:.0%} green-build rate over {BUILDS} builds.")

    # What fixed sleep would a 99%-green build actually require?
    target_per_test = 0.99 ** (1.0 / SUITE_TESTS)
    needed_q = target_per_test
    safe_sleep = quantile(CALIBRATION, needed_q)
    safe_secs = safe_sleep * SUITE_TESTS
    print(f"\n  what fixed sleep would a 99% green build need?")
    print(f"    per-test success required : {target_per_test:.6f}  (= 0.99 ^ (1/{SUITE_TESTS}))")
    print(f"    that is the p{needed_q * 100:.4f} of the distribution")
    print(f"    which is                  : {fmt_secs(safe_sleep)}   "
          f"({safe_sleep / P50:.0f}x the median)")
    print(f"    x {SUITE_TESTS} tests            : {fmt_secs(safe_secs)} of pure sleeping")
    print(f"    polling reaches the same green rate in {fmt_secs(psecs)} "
          f"— {safe_secs / psecs:.0f}x faster.")

    print("\n  and note what estimating that number required: the p"
          f"{needed_q * 100:.4f} of a")
    print(f"  distribution, computed from {CALIBRATION_SAMPLES:,} observations. A suite has")
    print(f"  {SUITE_TESTS}. You cannot measure the quantile you would have to sleep for,")
    print("  which is why the sleep in your repository was picked by doubling.")

    print("\n  the two-dimensional result: polling is strictly better on BOTH axes")
    print("  than every fixed sleep that has any chance of a green build.")
    print("    strategy                  suite time    flake rate   P(green)   polling wins both?")
    for r in results[:-1]:
        dom = "YES" if (psecs < r.suite_seconds and pf <= r.per_test_flake) else "faster, never green"
        print(f"    {r.label:<24}  {fmt_secs(r.suite_seconds):>10}   {r.per_test_flake:>9.3%}   "
              f"{r.empirical_build_green:>7.1%}   {dom}")
    r = results[-1]
    print(f"    {r.label:<24}  {fmt_secs(r.suite_seconds):>10}   {r.per_test_flake:>9.3%}   "
          f"{r.empirical_build_green:>7.1%}   —")
    print("  the one sleep that beats polling on time is the p50, and it produced")
    print(f"  {sum(1 for b in builds if all(c <= strategies[0][1] for c in b))} green builds "
          f"out of {BUILDS}. Being fast is not a property of a suite")
    print("  that never goes green.")
    return results, safe_sleep, psecs


# ══ 3 · eventually(): THE PRIMITIVE, AND THE ERROR IT CARRIES ════════════════
# Polling is only half of it. The half every hand-rolled helper gets wrong is
# what happens when the condition never becomes true.

class Clock:
    """A controllable clock. Not frozen — advanceable. A frozen clock cannot
    test a timeout; see Phase 12 Lesson 8."""

    def __init__(self, now: float = 0.0) -> None:
        self._now = now

    def now(self) -> float:
        return self._now

    def advance(self, delta: float) -> None:
        self._now += delta


class EventuallyFailed(AssertionError):
    """Carries the LAST failure, not the fact that a deadline passed."""


@dataclass
class Attempted:
    value: Any
    attempts: int
    elapsed: float


def eventually(check: Callable[[], Any], *, timeout: float, interval: float,
               clock: Clock, probe: Optional[Callable[[], str]] = None,
               what: str = "condition") -> Attempted:
    """Poll `check` until it returns something truthy or the deadline passes.

    Three details that are the whole difference between this and a `sleep`:
      - it returns the moment the condition holds, so a passing test costs
        roughly the system's own latency and not the timeout;
      - it remembers the LAST error, and re-raises with it as the cause, so the
        failure message describes the system rather than the helper;
      - `probe` is a diagnostic hook run once on failure — the queue depth, the
        dead-letter contents, the row that IS there. This is the difference
        between a bug you can read and a bug you have to reproduce.
    """
    start = clock.now()
    deadline = start + timeout
    attempts = 0
    last: Optional[BaseException] = None
    while True:
        attempts += 1
        try:
            value = check()
            if value:
                return Attempted(value, attempts, clock.now() - start)
            last = AssertionError(f"{what} was falsy: {value!r}")
        except Exception as exc:      # noqa: BLE001 — the point is to keep it
            last = exc
        if clock.now() >= deadline:
            break
        clock.advance(interval)
    elapsed = clock.now() - start
    detail = f"; {probe()}" if probe else ""
    raise EventuallyFailed(
        f"{what} never held: {type(last).__name__}: {last} "
        f"(last of {attempts} attempts over {elapsed:.3f}s{detail})") from last


def naive_eventually(check: Callable[[], Any], *, timeout: float, interval: float,
                     clock: Clock) -> Attempted:
    """The version everybody writes first. Same polling, no memory."""
    start = clock.now()
    attempts = 0
    while clock.now() - start <= timeout:
        attempts += 1
        try:
            v = check()
            if v:
                return Attempted(v, attempts, clock.now() - start)
        except Exception:             # noqa: BLE001 — swallowed, and that is the bug
            pass
        clock.advance(interval)
    raise TimeoutError(f"condition not met within {timeout}s")


# Five genuinely different root causes, each producing a broken read model.

@dataclass
class ReadModel:
    rows: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    dlq: List[str] = field(default_factory=list)
    unconsumed: int = 0


ROOT_CAUSES: Tuple[Tuple[str, Callable[[], ReadModel]], ...] = (
    ("consumer crashed on the payload",
     lambda: ReadModel(dlq=["o-1042: ValidationError(currency='XBT')"])),
    ("test asserts on an id nobody emitted",
     lambda: ReadModel(rows={"o-1043": {"status": "paid", "items": 2}})),
    ("projection lag: row exists, status stale",
     lambda: ReadModel(rows={"o-1042": {"status": "pending", "items": 2}})),
    ("partial write: order without its items",
     lambda: ReadModel(rows={"o-1042": {"status": "paid", "items": 0}})),
    ("worker never subscribed",
     lambda: ReadModel(unconsumed=1)),
)


def assertion_over(model: ReadModel) -> Callable[[], Any]:
    """The assertion the test is trying to make: order o-1042 is paid with two
    items. Written so each root cause surfaces a DIFFERENT exception."""

    def check() -> Any:
        row = model.rows.get("o-1042")
        if row is None:
            raise LookupError("no row for order 'o-1042' in read model")
        if row["status"] != "paid":
            raise AssertionError(f"status is {row['status']!r}, want 'paid'")
        if row["items"] != 2:
            raise AssertionError(f"{row['items']} items on the order, want 2")
        return row

    return check


def probe_over(model: ReadModel) -> Callable[[], str]:
    def probe() -> str:
        return (f"read model has {len(model.rows)} row(s) {sorted(model.rows)}, "
                f"dlq={model.dlq}, unconsumed={model.unconsumed}")
    return probe


def section3() -> None:
    banner(3, "eventually(): THE FAILURE MESSAGE IS THE FEATURE")
    print("  five different root causes, one assertion, three ways of waiting.")
    print("  the question is not whether the test fails. All fifteen fail.")
    print("  the question is whether the message tells you WHICH of the five.\n")

    styles: Tuple[Tuple[str, Callable[[ReadModel], str]], ...] = (
        ("sleep(2.0) then assert", _msg_sleep_assert),
        ("naive eventually()", _msg_naive),
        ("eventually() with last error + probe", _msg_proper),
    )

    seen: Dict[str, set] = {name: set() for name, _ in styles}
    for cause, build in ROOT_CAUSES:
        print(f"    root cause: {cause}")
        for name, fn in styles:
            msg = fn(build())
            seen[name].add(msg)
            print(f"      {name:<38} {msg}")
        print()

    print("    way of waiting                          distinct messages across the 5 causes")
    for name, _ in styles:
        n = len(seen[name])
        print(f"    {name:<38}  {n}/{len(ROOT_CAUSES)}"
              f"{'   <- every failure looks the same' if n == 1 else ''}")

    print("\n  a `sleep` then a bare `assert` collapses five distinct system states")
    print("  into one string. So does a polling helper that swallows the exception")
    print("  and reports its own deadline. Keeping the last error costs four lines.")

    # And the other half: what the two styles cost on a test that PASSES.
    rng = random.Random(SEED + 7)
    comps = [draw_completion(rng) for _ in range(SUITE_TESTS)]
    _, sleep_secs = run_fixed_sleep(comps, 2.0)
    poll_flakes, poll_secs, _ = run_polling(comps)
    print(f"\n  cost on {SUITE_TESTS} PASSING tests, both configured to give up at 2.0 s:")
    print(f"    sleep(2.0) then assert                {fmt_secs(sleep_secs)}   "
          f"(every test pays the timeout)")
    print(f"    eventually(interval=10 ms, timeout=2 s)  {fmt_secs(poll_secs)}   "
          f"(each test pays its own latency), {poll_flakes} timeouts")
    print(f"    same verdict, {sleep_secs / poll_secs:.0f}x the wall clock.")


def _msg_sleep_assert(model: ReadModel) -> str:
    """`time.sleep(2.0); assert repo.get("o-1042")` — a bare assert on a bare
    expression. Python's assertion has no operands to report."""
    row = model.rows.get("o-1042")
    ok = bool(row) and row.get("status") == "paid" and row.get("items") == 2
    return "AssertionError" if not ok else "passed"


def _msg_naive(model: ReadModel) -> str:
    try:
        naive_eventually(assertion_over(model), timeout=2.0, interval=0.05, clock=Clock())
        return "passed"
    except TimeoutError as exc:
        return f"TimeoutError: {exc}"


def _msg_proper(model: ReadModel) -> str:
    try:
        eventually(assertion_over(model), timeout=2.0, interval=0.05, clock=Clock(),
                   probe=probe_over(model), what="order o-1042 is paid with 2 items")
        return "passed"
    except EventuallyFailed as exc:
        return f"EventuallyFailed: {exc}"


# ══ 4 · A VIRTUAL CLOCK FOR ASYNCHRONOUS TESTS ═══════════════════════════════
# A ~60-line deterministic scheduler. `vsleep(30)` advances a number instead of
# blocking a thread, so a workflow with half a minute of waiting in it costs
# nothing at all. Phase 8 Lesson 5 built coroutines from the ground up; this is
# the same machinery pointed at a test suite.

class _Sleep:
    """The awaitable the scheduler understands. `await _Sleep(d)` yields it out
    to the loop, which reschedules the coroutine at now + d."""

    __slots__ = ("delay",)

    def __init__(self, delay: float) -> None:
        self.delay = delay

    def __await__(self) -> Iterator["_Sleep"]:
        yield self


async def vsleep(delay: float) -> None:
    await _Sleep(delay)


class VirtualLoop:
    """Runs coroutines against a virtual clock. Time is a heap key, not a wait.

    Determinism is not a side benefit here — it is the point. A real event loop
    orders two callbacks scheduled for the same instant by whatever the OS did;
    this one orders them by a monotonically increasing sequence number, so a
    test that passes once passes every time on every machine."""

    def __init__(self) -> None:
        self.now = 0.0
        self.steps = 0
        self.slept = 0.0
        self._heap: List[Tuple[float, int, Any]] = []
        self._seq = 0
        self.pending_at_exit: List[str] = []
        self._names: Dict[int, str] = {}

    def spawn(self, coro: Any, *, at: Optional[float] = None, name: str = "task") -> None:
        self._seq += 1
        self._names[id(coro)] = name
        heapq.heappush(self._heap, (self.now if at is None else at, self._seq, coro))

    def run_until_idle(self, until: Optional[float] = None) -> None:
        """Advance virtual time until nothing is scheduled (or until `until`).
        Stopping early is what a test that forgets to clean up its tasks does."""
        while self._heap:
            when, seq, coro = self._heap[0]
            if until is not None and when > until:
                self.now = until
                break
            heapq.heappop(self._heap)
            if when > self.now:
                self.slept += when - self.now
                self.now = when
            self.steps += 1
            try:
                yielded = coro.send(None)
            except StopIteration:
                continue
            if isinstance(yielded, _Sleep):
                self._seq += 1
                heapq.heappush(self._heap, (self.now + yielded.delay, self._seq, coro))
            else:                       # pragma: no cover - defensive
                raise RuntimeError(f"unsupported await: {yielded!r}")
        self.pending_at_exit = sorted(self._names.get(id(c), "task")
                                      for _w, _s, c in self._heap)

    def cancel_pending(self) -> int:
        """What a test teardown must do. asyncio.TaskGroup does this for you;
        a bare create_task() does not."""
        n = len(self._heap)
        for _w, _s, coro in self._heap:
            coro.close()
        self._heap.clear()
        return n


# The workflow under test: an order that waits for four real-world delays.
WORKFLOW_STEPS: Tuple[Tuple[str, float], ...] = (
    ("payment webhook arrives", 5.0),
    ("fulfilment retry backoff 1+2+4+8", 15.0),
    ("reconciliation window", 10.0),
)
WORKFLOW_SECONDS = sum(d for _n, d in WORKFLOW_STEPS)
VIRTUAL_SUITE_TESTS = 40


def order_workflow(state: Dict[str, Any]) -> Any:
    async def run() -> None:
        state["status"] = "accepted"
        for name, delay in WORKFLOW_STEPS:
            await vsleep(delay)
            state["status"] = name
        state["status"] = "settled"
    return run()


async def _real_calibration() -> float:
    """Prove the obvious thing empirically rather than asserting it: a real
    event loop really does pay for its sleeps. Scaled to 30 ms so the program
    still exits quickly; the boolean is what gets printed, not the duration."""
    t0 = time.perf_counter()
    for _ in range(3):
        await asyncio.sleep(0.010)
    return time.perf_counter() - t0


def section4() -> Tuple[float, int]:
    banner(4, "VIRTUAL TIME: 20 MINUTES OF SLEEPING, RUN IN ZERO")
    print("  the workflow under test contains three unavoidable real-world waits:")
    for name, delay in WORKFLOW_STEPS:
        print(f"    {delay:>5.1f} s   {name}")
    print(f"    {WORKFLOW_SECONDS:>5.1f} s   total, per test\n")

    real_elapsed = asyncio.run(_real_calibration())
    print(f"  does a real event loop actually pay for asyncio.sleep? "
          f"3 x 10 ms honoured: {real_elapsed >= 0.030}")
    print("  so a real loop costs the sum of the sleeps, every test, every run.\n")

    # A suite runs tests one at a time, each with its own event loop, so the
    # virtual time advanced is the sum over tests — exactly what a real loop
    # would have to spend on the wall clock.
    virtual_total = 0.0
    total_steps = 0
    settled = 0
    for i in range(VIRTUAL_SUITE_TESTS):
        loop = VirtualLoop()
        st: Dict[str, Any] = {"status": "new"}
        loop.spawn(order_workflow(st), name=f"test-{i:02d}")
        loop.run_until_idle()
        virtual_total += loop.slept
        total_steps += loop.steps
        settled += st["status"] == "settled"
    real_suite = WORKFLOW_SECONDS * VIRTUAL_SUITE_TESTS

    print(f"    {VIRTUAL_SUITE_TESTS} tests, each awaiting {WORKFLOW_SECONDS:.0f} s of workflow")
    print(f"    on a real event loop     : {fmt_secs(real_suite)} of wall clock, unavoidably")
    print(f"    on the virtual loop      : {fmt_secs(virtual_total)} of VIRTUAL time advanced")
    print(f"                               in {total_steps} scheduler steps, 0 real sleeps")
    print(f"    tests that reached 'settled': {settled}/{VIRTUAL_SUITE_TESTS}")
    print(f"    speed-up                 : {fmt_secs(real_suite)} -> 0 s of sleeping\n")

    # The other thing virtual time buys: timeouts become assertable.
    slow = VirtualLoop()
    mid: Dict[str, Any] = {"status": "new"}
    slow.spawn(order_workflow(mid), name="timeout-test")
    slow.run_until_idle(until=20.0)
    print("  and a timeout becomes a deterministic assertion rather than a race:")
    print(f"    at t=20.0 s the workflow is at {mid['status']!r} — exactly, every run.")
    print(f"    tasks still scheduled at that instant: {slow.pending_at_exit}")
    print("  on a real loop this test would take 20 seconds and still be a guess.")
    return virtual_total, total_steps


# ══ 5 · AT-LEAST-ONCE DELIVERY: THE TEST MUST SEND THE DUPLICATE ═════════════
# A broker that redelivers when it does not see an ack is behaving correctly.
# See Phase 6 Lesson 6: exactly-once DELIVERY is impossible; exactly-once
# EFFECT is a property of the consumer, and therefore testable.

@dataclass(frozen=True)
class Event:
    event_id: str
    order_id: str
    kind: str
    amount_cents: int = 0


def delivery_stream(events: Sequence[Event], rng: random.Random,
                    dup_rate: float) -> List[Event]:
    """At-least-once: some fraction of events are delivered more than once
    because the ack was lost, not because the producer sent them twice."""
    out: List[Event] = []
    for ev in events:
        out.append(ev)
        while rng.random() < dup_rate:
            out.append(ev)
    return out


class NaiveConsumer:
    """Correct against exactly-once delivery. There is no such thing."""

    def __init__(self) -> None:
        self.balances: Dict[str, int] = {}
        self.applied = 0

    def handle(self, ev: Event) -> None:
        self.balances[ev.order_id] = self.balances.get(ev.order_id, 0) + ev.amount_cents
        self.applied += 1


class IdempotentConsumer(NaiveConsumer):
    """The fix, and it is four lines: a key derived from the BUSINESS event, a
    seen-set, and both checked and written in the same transaction."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: set = set()
        self.suppressed = 0

    def handle(self, ev: Event) -> None:
        if ev.event_id in self.seen:
            self.suppressed += 1
            return
        self.seen.add(ev.event_id)
        super().handle(ev)


def section5() -> Tuple[int, int, int]:
    banner(5, "DUPLICATE DELIVERY: THE SUITE THAT NEVER SENDS ONE")
    orders = 400
    rng = random.Random(SEED + 11)
    events = [Event(f"e-{i:04d}", f"o-{i:04d}", "payment_captured",
                    rng.randrange(500, 20000)) for i in range(orders)]
    expected = {e.order_id: e.amount_cents for e in events}

    dup_rate = 0.08
    stream = delivery_stream(events, random.Random(SEED + 12), dup_rate)
    dups = len(stream) - len(events)
    print(f"  {orders} payment_captured events, an at-least-once broker, and a")
    print(f"  {dup_rate:.0%} redelivery rate: {len(stream)} deliveries, {dups} of them repeats.\n")

    print("    the suite a team actually writes: each event delivered exactly once")
    clean = NaiveConsumer()
    for ev in events:
        clean.handle(ev)
    wrong_clean = sum(1 for oid, amt in expected.items() if clean.balances.get(oid) != amt)
    print(f"      naive consumer, no duplicates    : {wrong_clean}/{orders} balances wrong  "
          f"-> the suite is GREEN")
    print("      and the bug is shipped, because the test never asked the question.\n")

    print("    the same consumer, duplicates delivered as the broker will:")
    naive = NaiveConsumer()
    for ev in stream:
        naive.handle(ev)
    wrong = sum(1 for oid, amt in expected.items() if naive.balances.get(oid) != amt)
    overcharge = sum(naive.balances[o] - expected[o] for o in expected)
    print(f"      naive consumer                   : {wrong}/{orders} balances wrong "
          f"({wrong / orders:.1%})")
    print(f"      total over-credit                : {overcharge:,}c "
          f"(${overcharge / 100:,.2f}) on {sum(expected.values()):,}c of real payments")
    print(f"      worst single order               : "
          f"{max(naive.balances[o] - expected[o] for o in expected):,}c too much")

    idem = IdempotentConsumer()
    for ev in stream:
        idem.handle(ev)
    wrong_idem = sum(1 for oid, amt in expected.items() if idem.balances.get(oid) != amt)
    print(f"      idempotent consumer              : {wrong_idem}/{orders} balances wrong, "
          f"{idem.suppressed} duplicates suppressed")

    print(f"\n  both consumers pass the no-duplicate suite. Only one of them is correct.")
    print("  the test that separates them is one line long: deliver the event twice.")
    return dups, wrong, overcharge


# ══ 6 · ORDER IS AN ASSUMPTION UNTIL YOU PERMUTE IT ══════════════════════════
# Lamport (CACM 21(7), 1978): in a distributed system there is no total order
# of events unless something imposes one. Across partitions, retries and
# parallel consumers, arrival order is not emission order.

ORDER_EVENTS: Tuple[Event, ...] = (
    Event("v1", "o-77", "order_created"),
    Event("v2", "o-77", "item_added", 3000),
    Event("v3", "o-77", "item_added", 1500),
    Event("v4", "o-77", "discount_applied", 10),     # 10% off
    Event("v5", "o-77", "payment_captured", 4050),
    Event("v6", "o-77", "shipped"),
)


@dataclass
class OrderState:
    created: bool = False
    items_total: int = 0
    item_count: int = 0
    discount_pct: int = 0
    discount_applications: int = 0
    charged: int = 0
    shipped: bool = False
    shipped_before_payment: bool = False
    total_at_discount: int = 0


def fold(events: Sequence[Event]) -> OrderState:
    """The projection under test. Written by someone who read the events in
    the order they were emitted, which is the only order they ever saw."""
    st = OrderState()
    for ev in events:
        if ev.kind == "order_created":
            st.created = True
        elif ev.kind == "item_added":
            st.items_total += ev.amount_cents
            st.item_count += 1
        elif ev.kind == "discount_applied":
            st.discount_pct = ev.amount_cents
            st.discount_applications += 1
            # the order-dependent line: the discount is applied to whatever the
            # total happens to be AT THE MOMENT THE EVENT ARRIVES.
            st.total_at_discount = st.items_total * (100 - ev.amount_cents) // 100
        elif ev.kind == "payment_captured":
            st.charged += ev.amount_cents
        elif ev.kind == "shipped":
            st.shipped = True
            if st.charged == 0:
                st.shipped_before_payment = True
    return st


INVARIANTS: Tuple[Tuple[str, Callable[[OrderState], bool]], ...] = (
    ("items_total is 4500c", lambda s: s.items_total == 4500),
    ("item_count is 2", lambda s: s.item_count == 2),
    ("discount applied exactly once", lambda s: s.discount_applications == 1),
    ("discounted total is 4050c", lambda s: s.total_at_discount == 4050),
    ("never ships before payment", lambda s: not s.shipped_before_payment),
)


def section6() -> Tuple[int, Dict[str, int]]:
    banner(6, "ORDER DEPENDENCE: EVERY PERMUTATION OF ONE EVENT SET")
    perms = list(itertools.permutations(ORDER_EVENTS))
    print(f"  6 events for one order -> {len(perms)} arrival orders. The suite runs 1 of them:")
    print("    " + " -> ".join(e.kind for e in ORDER_EVENTS))
    natural = fold(ORDER_EVENTS)
    print(f"    all {len(INVARIANTS)} invariants hold in emission order: "
          f"{all(fn(natural) for _n, fn in INVARIANTS)}\n")

    failures: Dict[str, int] = {name: 0 for name, _ in INVARIANTS}
    for p in perms:
        st = fold(p)
        for name, fn in INVARIANTS:
            if not fn(st):
                failures[name] += 1

    print(f"    invariant                          fails in   of {len(perms)}   survives all orders?")
    for name, _fn in INVARIANTS:
        n = failures[name]
        print(f"    {name:<34} {n:>8}   {n / len(perms):>7.1%}   "
              f"{'YES' if n == 0 else 'no'}")

    survived = [n for n, _ in INVARIANTS if failures[n] == 0]
    broken = [n for n, _ in INVARIANTS if failures[n] > 0]
    print(f"\n  {len(survived)} of {len(INVARIANTS)} invariants are genuinely order-independent: "
          f"{', '.join(survived)}")
    print(f"  {len(broken)} secretly depended on arrival order and nobody wrote that down.")

    # How many random permutations does a suite need to find it?
    print("\n  if you shuffle K deliveries per CI run, how likely is detection?")
    print("    invariant                          p(fail)   K=1    K=5    K=20   K=100")
    for name, _fn in INVARIANTS:
        p = failures[name] / len(perms)
        if p == 0:
            continue
        cells = "".join(f"{1 - (1 - p) ** k:>7.1%}" for k in (1, 5, 20, 100))
        print(f"    {name:<34} {p:>7.1%}  {cells}")

    any_fail = sum(1 for p in perms if any(not fn(fold(p)) for _n, fn in INVARIANTS))
    p_any = any_fail / len(perms)
    print(f"    {'ANY of the five fails':<34} {p_any:>7.1%}  "
          f"{''.join(f'{1 - (1 - p_any) ** k:>7.1%}' for k in (1, 5, 20, 100))}"
          f"   ({any_fail} of {len(perms)} orders)")

    # Simulated, so the arithmetic is checked against a run rather than trusted.
    rng = random.Random(SEED + 21)
    trials = 2000
    print("\n  simulated (random shuffles rather than exhaustive enumeration):")
    for k in (1, 5, 20):
        hits = 0
        for _ in range(trials):
            found = False
            for _ in range(k):
                st = fold(rng.sample(ORDER_EVENTS, len(ORDER_EVENTS)))
                if any(not fn(st) for _n, fn in INVARIANTS):
                    found = True
            hits += found
        print(f"    K={k:<3} detects some order dependence in {hits / trials:>6.1%} of "
              f"{trials} runs   (predicted {1 - (1 - p_any) ** k:.1%})")
    rare = 2 / len(perms)
    k99 = math.ceil(math.log(0.01) / math.log(1 - rare))
    print(f"  five shuffles is enough HERE, because the cheapest dependence in this")
    print(f"  event set fails in {min(f for f in failures.values() if f)} of {len(perms)} orders. "
          f"A dependence that only 2 of {len(perms)}")
    print(f"  orders expose needs {k99:,} shuffles for the same 99% confidence.")
    print("  'shuffle the events' is not a policy until you compute that number.")
    return len(perms), failures


# ══ 7 · RETRIES, BACKOFF, THE DLQ — AND THE RETRY THAT DUPLICATES A WRITE ════
# RFC 6298 §5 is the canonical statement of the doubling rule (TCP's RTO).
# The interesting assertions here are the exact ones: how many attempts, at
# what delays, and what is in the dead-letter queue afterwards.

MAX_ATTEMPTS = 5
BASE_BACKOFF = 0.100
BACKOFF_FACTOR = 2.0


def backoff_schedule(attempts: int = MAX_ATTEMPTS) -> List[float]:
    return [BASE_BACKOFF * (BACKOFF_FACTOR ** i) for i in range(attempts - 1)]


@dataclass
class DeadLetter:
    event_id: str
    attempts: int
    last_error: str


class OrderWorker:
    """Consumes payment events. `fail_mode` selects where the failure lands:

      'before_write' — the handler raises before it touches the database
      'after_write'  — the handler writes the row, THEN the downstream call
                       fails. The retry re-runs the whole handler.
    """

    def __init__(self, *, guard: bool) -> None:
        self.rows: List[Tuple[str, int]] = []
        self.dlq: List[DeadLetter] = []
        self.attempts: Dict[str, int] = {}
        self.delays: Dict[str, List[float]] = {}
        self.guard = guard          # an idempotency key on the write
        self.written_keys: set = set()
        self.emails_sent: List[str] = []

    def _write(self, ev: Event) -> None:
        if self.guard and ev.event_id in self.written_keys:
            return
        self.written_keys.add(ev.event_id)
        self.rows.append((ev.order_id, ev.amount_cents))

    def deliver(self, ev: Event, fail_mode: str, fail_until: int) -> None:
        """One delivery, retried in-process with backoff, then dead-lettered."""
        schedule = backoff_schedule()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            self.attempts[ev.event_id] = attempt
            try:
                if fail_mode == "before_write" and attempt <= fail_until:
                    raise ConnectionError("payments API: connection reset")
                if fail_mode == "after_write":
                    self._write(ev)
                    if attempt <= fail_until:
                        raise TimeoutError("receipt service: 504 after 30s")
                    self.emails_sent.append(ev.order_id)
                    return
                self._write(ev)
                self.emails_sent.append(ev.order_id)
                return
            except Exception as exc:      # noqa: BLE001
                if attempt == MAX_ATTEMPTS:
                    self.dlq.append(DeadLetter(ev.event_id, attempt,
                                               f"{type(exc).__name__}: {exc}"))
                    return
                self.delays.setdefault(ev.event_id, []).append(schedule[attempt - 1])


def section7() -> Tuple[List[float], int, int]:
    banner(7, "RETRY, BACKOFF, DLQ — AND THE RETRY THAT WRITES TWICE")
    sched = backoff_schedule()
    print(f"  policy under test: {MAX_ATTEMPTS} attempts, {BASE_BACKOFF * 1000:.0f} ms base, "
          f"x{BACKOFF_FACTOR:.0f} per retry (RFC 6298 §5).")
    print(f"    exact backoff schedule the test must assert: "
          f"{[f'{d * 1000:.0f} ms' for d in sched]}")
    print(f"    total delay before the dead-letter queue   : {sum(sched) * 1000:.0f} ms\n")

    ev = Event("e-9001", "o-9001", "payment_captured", 4200)

    w = OrderWorker(guard=False)
    w.deliver(ev, "before_write", fail_until=MAX_ATTEMPTS)
    print("    a · permanently failing handler, failure BEFORE the write:")
    print(f"      attempts            : {w.attempts[ev.event_id]}  "
          f"(assert this exactly, not 'more than one')")
    print(f"      observed delays     : {[f'{d * 1000:.0f} ms' for d in w.delays[ev.event_id]]}")
    print(f"      rows written        : {len(w.rows)}")
    print(f"      dlq                 : {len(w.dlq)} message(s) — "
          f"{w.dlq[0].event_id}, {w.dlq[0].attempts} attempts, {w.dlq[0].last_error}")
    print(f"      emails sent         : {len(w.emails_sent)}\n")

    w2 = OrderWorker(guard=False)
    w2.deliver(ev, "after_write", fail_until=3)
    print("    b · THE CLASSIC BUG: the handler writes, THEN the downstream call fails.")
    print("        the retry re-runs the whole handler, including the write.")
    print(f"      attempts            : {w2.attempts[ev.event_id]}")
    print(f"      rows written        : {len(w2.rows)}   <- one order, "
          f"{len(w2.rows)} rows, {sum(a for _o, a in w2.rows):,}c charged")
    print(f"      dlq                 : {len(w2.dlq)} — the retry SUCCEEDED, so nothing is red")
    print(f"      emails sent         : {len(w2.emails_sent)}")

    w3 = OrderWorker(guard=True)
    w3.deliver(ev, "after_write", fail_until=3)
    print(f"      with an idempotency key on the write: {len(w3.rows)} row(s), "
          f"{sum(a for _o, a in w3.rows):,}c\n")

    # At suite scale, so the bug has a price rather than an anecdote.
    rng = random.Random(SEED + 31)
    batch = [Event(f"e-{i:04d}", f"o-{i:04d}", "payment_captured", rng.randrange(500, 20000))
             for i in range(300)]
    fails = {e.event_id: (rng.random() < 0.06) for e in batch}
    naive = OrderWorker(guard=False)
    guarded = OrderWorker(guard=True)
    for e in batch:
        mode, until = ("after_write", 2) if fails[e.event_id] else ("after_write", 0)
        naive.deliver(e, mode, until)
        guarded.deliver(e, mode, until)
    n_failing = sum(fails.values())
    extra = len(naive.rows) - len(batch)
    overcharged = sum(a for o, a in naive.rows) - sum(e.amount_cents for e in batch)
    print(f"    c · 300 events, {n_failing} of which fail twice AFTER the write:")
    print(f"      naive worker   : {len(naive.rows)} rows for {len(batch)} events "
          f"(+{extra}), {overcharged:,}c over-charged, dlq={len(naive.dlq)}")
    print(f"      guarded worker : {len(guarded.rows)} rows for {len(batch)} events, "
          f"0c over-charged, dlq={len(guarded.dlq)}")
    print("      note the dlq is empty in BOTH. The retry worked. That is why")
    print("      no alert fires and no test fails: the only evidence is the")
    print("      duplicate row, and only a test that counts rows will see it.")
    return sched, extra, overcharged


# ══ 8 · PYTHON HAZARDS: THE FORGOTTEN await, AND THE TASK THAT OUTLIVES ══════

async def order_is_paid(order_id: str) -> bool:
    """Deliberately returns False: the order is NOT paid. The system is broken
    and the test is about to say it is fine."""
    return False


async def charged_amount(order_id: str) -> int:
    return 0


def section8() -> Tuple[int, int, int]:
    banner(8, "THE FORGOTTEN await, AND THE TASK THAT OUTLIVES THE TEST")
    print("  a · the system is broken: order_is_paid() returns False for every order.")
    print("      six assertions are written against it, none of them awaited.\n")

    checks: Tuple[Tuple[str, Any], ...] = (
        ("assert order_is_paid('o-1')", order_is_paid("o-1")),
        ("assert order_is_paid('o-2')", order_is_paid("o-2")),
        ("assert order_is_paid('o-3')", order_is_paid("o-3")),
        ("assert charged_amount('o-1')", charged_amount("o-1")),
        ("assert charged_amount('o-2')", charged_amount("o-2")),
        ("assert order_is_paid('o-4')", order_is_paid("o-4")),
    )
    passed = 0
    for label, coro in checks:
        truthy = bool(coro)
        is_coro = inspect.iscoroutine(coro)
        if truthy:
            passed += 1
        print(f"      {label:<34} type={type(coro).__name__:<10} bool={truthy}  "
              f"coroutine={is_coro}")
        coro.close()
    print(f"\n      {passed}/{len(checks)} assertions PASSED against a system where every")
    print("      answer is False. A coroutine object is always truthy — it has no")
    print("      __bool__, so Python falls back to 'objects are true'. The assertion")
    print("      never touched the function's return value.")

    awaited = asyncio.run(order_is_paid("o-1"))
    print(f"\n      the same call, awaited: order_is_paid('o-1') -> {awaited}  "
          f"(the test fails, correctly)")
    print(f"      and the guard that makes it impossible to miss:")
    try:
        strict_assert(order_is_paid("o-9"))
    except TypeError as exc:
        print(f"        strict_assert(order_is_paid('o-9')) -> TypeError: {exc}")

    print("\n  b · a background task scheduled inside a test outlives it.")
    print("      test A spawns a reconciliation task at t+50 ms and returns at t+10 ms.")
    print("      test B then writes a balance and reads it back 60 ms later.\n")

    leaked_fail = _leak_suite(cleanup=False)
    clean_fail = _leak_suite(cleanup=True)
    print(f"      without teardown cleanup : {leaked_fail[0]}/{leaked_fail[2]} innocent tests "
          f"corrupted, {leaked_fail[1]} task(s) still scheduled at test exit")
    print(f"      with cancel-on-teardown  : {clean_fail[0]}/{clean_fail[2]} innocent tests "
          f"corrupted, {clean_fail[1]} task(s) left over")
    print("      the failure lands in a test that did nothing wrong, which is why")
    print("      this class of flake is always blamed on the wrong file — and why")
    print("      it moves when the suite is shuffled (Phase 12 Lesson 9).")
    return passed, leaked_fail[0], leaked_fail[1]


def strict_assert(value: Any) -> None:
    """Refuses to evaluate the truthiness of an un-awaited coroutine. Four
    lines, and it turns this lesson's silent pass into a loud failure."""
    if inspect.isawaitable(value):
        value.close() if hasattr(value, "close") else None
        raise TypeError("assertion on an un-awaited coroutine — you meant `await`")
    assert value


def _leak_suite(*, cleanup: bool) -> Tuple[int, int, int]:
    """Six tests on the virtual loop. Tests 0, 2 and 4 spawn a background task
    that fires long after their own assertion. Tests 1, 3 and 5 are innocent."""
    shared: Dict[str, int] = {"balance": 0}
    loop = VirtualLoop()
    corrupted = 0
    leaked = 0
    innocents = 0

    async def reconcile() -> None:
        await vsleep(0.050)
        shared["balance"] = 0          # a stale reconciliation from a dead test

    async def victim() -> None:
        shared["balance"] = 2500
        await vsleep(0.060)

    for i in range(6):
        if i % 2 == 0:
            loop.spawn(reconcile(), name=f"reconcile-from-test-{i}")
            loop.run_until_idle(until=loop.now + 0.010)
            if cleanup:
                loop.cancel_pending()
            else:
                leaked += len(loop.pending_at_exit)
        else:
            innocents += 1
            loop.spawn(victim(), name=f"victim-test-{i}")
            loop.run_until_idle(until=loop.now + 0.070)
            if shared["balance"] != 2500:
                corrupted += 1
            loop.cancel_pending()
    return corrupted, leaked, innocents


def main() -> None:
    # No wall-clock value is ever printed: two runs of this file produce
    # byte-identical output, which is the only way a lesson's numbers can be
    # checked against its prose.
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    section7()
    section8()
    print()


if __name__ == "__main__":
    main()
