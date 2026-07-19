#!/usr/bin/env python3
"""
Profiling from scratch: a deterministic profiler, a signal-driven on-CPU sampler
and a thread-driven wall-clock sampler, all graded against a synthetic checkout
endpoint whose TRUE per-component cost is measured and printed first.

Companion to docs/en.md (Phase 8, Lesson 13). Standard library only, seeded,
self-terminating in well under 30 seconds. Amdahl's ceiling is from Amdahl,
*AFIPS Conf. Proc.* 30, 1967. Interval timers (ITIMER_PROF counts down in CPU
time, ITIMER_REAL in wall time) are POSIX.1-2001; ITIMER_PROF is the mechanism
every classical on-CPU profiler is built on.

Run:  python3 profiling.py
"""

from __future__ import annotations

import asyncio
import cProfile
import io
import linecache
import pstats
import random
import signal
import sys
import threading
import time
import tracemalloc
from collections import defaultdict
from time import perf_counter

SEED = 20260718
random.seed(SEED)

# The five components of the endpoint, in call order. Every table in this file
# is keyed by these names, so each profiler's answer can be diffed against truth.
COMPONENTS = (
    "validate_cart",
    "price_line_items",
    "compute_tax",
    "charge_payment",
    "serialize_response",
)

# The cost budget the endpoint is built to. Nothing below trusts these numbers --
# section 1 measures what actually happened on this machine. They exist so the
# shape is deliberate: ~400 ms of CPU, ~500 ms of waiting, and one component
# (serialize_response) that looks expensive and is 2% of the runtime.
TARGET_S = {
    "validate_cart": 0.032,
    "price_line_items": 0.200,   # 50,000 cheap calls: the N+1 shape
    "compute_tax": 0.150,        # one genuinely CPU-hot function
    "charge_payment": 0.500,     # a blocking wait: zero CPU
    "serialize_response": 0.018,  # the red herring
}
N_LINE_ITEMS = 50_000


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


# ─── Burning CPU portably ────────────────────────────────────────────────────

def _spin(iters: int) -> int:
    """A tight integer loop. The only primitive in this file that burns CPU."""
    x = 0
    for i in range(iters):
        x = (x * 31 + i) & 0xFFFFFFFF
    return x


def _measure_spin_rate() -> float:
    best = 0.0
    for _ in range(3):
        t0 = perf_counter()
        _spin(400_000)
        best = max(best, 400_000 / (perf_counter() - t0))
    return best


ITERS_PER_SEC = _measure_spin_rate()


def _burn(seconds: float) -> None:
    """Occupy the CPU until `seconds` of wall clock have passed.

    Deadline-driven rather than iteration-driven so the component costs are the
    same on a fast laptop and a throttled container -- which is what makes the
    ground-truth table below reproducible enough to grade profilers against.
    """
    end = perf_counter() + seconds
    chunk = max(64, int(ITERS_PER_SEC * min(0.0003, seconds / 40)))
    while perf_counter() < end:
        _spin(chunk)


# ─── The endpoint under study ────────────────────────────────────────────────

_PRICES = {i: round(random.uniform(1.0, 99.0), 2) for i in range(N_LINE_ITEMS)}


def fetch_price(item_id: int, iters: int) -> float:
    """One row lookup. Individually trivial; called once per line item.

    This is the N+1 shape: in a real service the body is a round trip to the
    database; here it is a couple of microseconds of arithmetic. Either way what
    makes it expensive is the CALL COUNT, not the per-call duration.
    """
    _spin(iters)
    return _PRICES[item_id]


def _calibrate_fetch(target_s: float, n_calls: int) -> int:
    """Pick per-call iterations so n_calls of fetch_price cost about target_s.

    Per-call cost is affine in `iters` (fixed call overhead plus the loop), so
    two probes fix the line; a couple of refinement rounds absorb the error.
    """
    probe_n = 20_000

    def probe(iters: int) -> float:
        t0 = perf_counter()
        for i in range(probe_n):
            fetch_price(i, iters)
        return (perf_counter() - t0) / probe_n

    lo_i, hi_i = 1, 96
    lo, hi = probe(lo_i), probe(hi_i)
    slope = max((hi - lo) / (hi_i - lo_i), 1e-15)
    intercept = lo - slope * lo_i
    want = target_s / n_calls
    iters = max(1, int((want - intercept) / slope))
    for _ in range(3):
        obs = probe(iters)
        if 0.97 <= obs / want <= 1.03:
            break
        if iters != lo_i:
            slope = max((obs - lo) / (iters - lo_i), 1e-15)
            intercept = lo - slope * lo_i
        iters = max(1, int((want - intercept) / slope))
    return iters


FETCH_ITERS = _calibrate_fetch(TARGET_S["price_line_items"], N_LINE_ITEMS)


class GroundTruth:
    """Manual per-component wall-clock instrumentation: the answer key.

    Two perf_counter() calls per component per request -- about 200 ns on a
    900 ms request, which is why it can stay on while the profilers run.
    """

    def __init__(self) -> None:
        self.total: dict[str, float] = defaultdict(float)

    def time(self, name: str):
        return _Span(self, name)

    def reset(self) -> None:
        self.total = defaultdict(float)


class _Span:
    __slots__ = ("gt", "name", "t0")

    def __init__(self, gt: GroundTruth, name: str) -> None:
        self.gt, self.name = gt, name

    def __enter__(self):
        self.t0 = perf_counter()
        return self

    def __exit__(self, *exc):
        self.gt.total[self.name] += perf_counter() - self.t0
        return False


GT = GroundTruth()


def validate_cart(order: dict) -> None:
    """Cheap CPU: schema and stock checks."""
    _burn(TARGET_S["validate_cart"])


def price_line_items(order: dict) -> float:
    """The N+1: one price lookup per line item, 50,000 times."""
    total = 0.0
    for item_id in order["items"]:
        total += fetch_price(item_id, FETCH_ITERS)
    return total


def compute_tax(subtotal: float) -> float:
    """The genuinely CPU-hot function: one long block of arithmetic."""
    _burn(TARGET_S["compute_tax"])
    return subtotal * 0.19


def charge_payment(amount: float) -> str:
    """Blocking I/O: the call to the payments API. Zero CPU, half a second gone."""
    time.sleep(TARGET_S["charge_payment"])
    return "ch_ok"


def serialize_response(order: dict, total: float) -> int:
    """The red herring. Looks expensive, everyone blames it, it is 2%."""
    _burn(TARGET_S["serialize_response"])
    return int(total)


def checkout(order: dict) -> int:
    """POST /checkout -- the endpoint everyone has a theory about."""
    with GT.time("validate_cart"):
        validate_cart(order)
    with GT.time("price_line_items"):
        subtotal = price_line_items(order)
    with GT.time("compute_tax"):
        tax = compute_tax(subtotal)
    with GT.time("charge_payment"):
        charge_payment(subtotal + tax)
    with GT.time("serialize_response"):
        return serialize_response(order, subtotal + tax)


ORDER = {"id": "ord_8812", "items": list(range(N_LINE_ITEMS))}


def run_requests(n: int = 1) -> float:
    t0 = perf_counter()
    for _ in range(n):
        checkout(ORDER)
    return perf_counter() - t0


# ─── The sampling profilers ──────────────────────────────────────────────────

def stack_of(frame, root: str | None = "checkout", depth: int = 6) -> tuple[str, ...]:
    """Walk f_back to the root, keeping function names, outermost first.

    With `root` set, a stack that is not inside the endpoint returns () and is
    dropped -- so attribution is over endpoint samples only. This ~10-line
    function is the entire "read a stack" primitive; py-spy's version does the
    same walk over another process's memory through process_vm_readv(2).
    """
    names: list[str] = []
    found = root is None
    while frame is not None and len(names) < 64:
        names.append(frame.f_code.co_name)
        if root is not None and frame.f_code.co_name == root:
            found = True
            break
        frame = frame.f_back
    if not found:
        return ()
    names.reverse()
    return tuple(names[-depth:])


class WallClockSampler:
    """py-spy in twenty lines: a thread that snapshots another thread's stack.

    Samples on a WALL-CLOCK schedule, so a target blocked in time.sleep() is
    sampled exactly as often as one burning CPU. That is the only difference
    from the on-CPU sampler below, and it changes every conclusion.
    """

    def __init__(self, target_tid: int, interval: float = 0.001,
                 root: str | None = "checkout",
                 switch_interval: float | None = 0.0002) -> None:
        self.target_tid = target_tid
        self.interval = interval
        self.root = root
        self.switch_interval = switch_interval
        self.counts: dict[tuple[str, ...], int] = defaultdict(int)
        self.samples = 0
        self.dropped = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._old_switch = sys.getswitchinterval()

    def _loop(self) -> None:
        nxt = perf_counter()
        while not self._stop.is_set():
            frame = sys._current_frames().get(self.target_tid)
            if frame is not None:
                st = stack_of(frame, self.root)
                if st:
                    self.counts[st] += 1
                    self.samples += 1
                else:
                    self.dropped += 1
            nxt += self.interval
            time.sleep(max(0.0, nxt - perf_counter()))

    def __enter__(self):
        # A sampler thread has to win the GIL (Global Interpreter Lock) to take
        # a sample. The default 5 ms switch interval starves it exactly while
        # the target is burning CPU, which biases the profile toward the
        # sleeping parts. Real samplers live outside the process and never have
        # this problem -- this line is the price of sampling from inside.
        if self.switch_interval is not None:
            sys.setswitchinterval(self.switch_interval)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join(timeout=2.0)
        sys.setswitchinterval(self._old_switch)
        return False


class OnCpuSampler:
    """A classical on-CPU profiler: SIGPROF driven by ITIMER_PROF.

    ITIMER_PROF counts down in *process CPU time*, so the signal simply does not
    arrive while the process is blocked. Nothing here filters I/O out -- the
    kernel never wakes us for it. That is why a CPU profiler is blind to
    waiting: not a bug, the definition.
    """

    def __init__(self, interval: float = 0.001, root: str | None = "checkout") -> None:
        self.interval = interval
        self.root = root
        self.counts: dict[tuple[str, ...], int] = defaultdict(int)
        self.samples = 0

    def _handler(self, signum, frame) -> None:
        st = stack_of(frame, self.root)
        if st:
            self.counts[st] += 1
            self.samples += 1

    def __enter__(self):
        self._old = signal.signal(signal.SIGPROF, self._handler)
        signal.setitimer(signal.ITIMER_PROF, self.interval, self.interval)
        return self

    def __exit__(self, *exc):
        signal.setitimer(signal.ITIMER_PROF, 0.0)
        signal.signal(signal.SIGPROF, self._old)
        return False


def attribute(counts: dict[tuple[str, ...], int]) -> dict[str, int]:
    """Roll stacks up to the endpoint component they were inside."""
    out: dict[str, int] = defaultdict(int)
    for stack, n in counts.items():
        for name in stack:
            if name in COMPONENTS:
                out[name] += n
                break
    return out


def pct(part: float, whole: float) -> float:
    return 100.0 * part / whole if whole else 0.0


# ─── Folded stacks and a text flame graph ────────────────────────────────────

def fold(counts: dict[tuple[str, ...], int]) -> list[str]:
    """The folded-stack format: `a;b;c 42`. That is the entire file format."""
    return [f"{';'.join(st)} {n}" for st, n in sorted(counts.items())]


def _tree(counts: dict[tuple[str, ...], int]) -> dict:
    root: dict = {"n": 0, "kids": {}}
    for stack, n in counts.items():
        node = root
        node["n"] += n
        for name in stack:
            node = node["kids"].setdefault(name, {"n": 0, "kids": {}})
            node["n"] += n
    return root


def render_flame(counts: dict[tuple[str, ...], int], width: int = 72) -> list[str]:
    """A flame graph in the console. Width = share of samples, y = stack depth.

    Children are laid out in ALPHABETICAL order, exactly as a real flame graph
    does it, because that is what lets identical stacks merge. It is also why
    the x-axis is not time.
    """
    root = _tree(counts)
    if not root["n"]:
        return []
    levels: list[list[tuple[float, float, str, int]]] = []

    def walk(node: dict, depth: int, x0: float) -> None:
        cursor = x0
        for name in sorted(node["kids"]):
            kid = node["kids"][name]
            w = width * kid["n"] / root["n"]
            while len(levels) <= depth:
                levels.append([])
            levels[depth].append((cursor, w, name, kid["n"]))
            walk(kid, depth + 1, cursor)
            cursor += w

    walk(root, 0, 0.0)
    out = []
    for depth in reversed(range(len(levels))):
        row = [" "] * width
        for x0, w, name, _n in levels[depth]:
            a, b = int(round(x0)), int(round(x0 + w))
            cw = b - a
            if cw <= 0:
                continue
            if cw >= 4:
                label = name if len(name) <= cw - 2 else name[: cw - 3] + "~"
                cell = "[" + label.center(cw - 2) + "]"
            else:
                cell = "|" * cw
            for i, ch in enumerate(cell):
                if a + i < width:
                    row[a + i] = ch
        share = pct(sum(n for _, _, _, n in levels[depth]), root["n"])
        out.append(f"  |{''.join(row)}|  depth {depth}  ({share:5.1f}%)")
    return out


# ─── Sections ────────────────────────────────────────────────────────────────

def section_1_ground_truth() -> tuple[dict[str, float], float]:
    banner(1, "THE ENDPOINT, AND ITS GROUND TRUTH")
    run_requests(1)                       # warm caches and branch predictors
    best = (float("inf"), {})
    for _ in range(3):
        GT.reset()
        wall = run_requests(1)
        if wall < best[0]:
            best = (wall, dict(GT.total))
    wall, truth = best
    print(f"  POST /checkout -> {wall * 1000:7.1f} ms wall clock, best of 3 "
          f"({N_LINE_ITEMS:,} line items)")
    print("  component               wall ms    share   kind")
    for name in COMPONENTS:
        kind = "waiting (0 CPU)" if name == "charge_payment" else "on-CPU"
        print(f"  {name:<22} {truth[name] * 1000:8.1f}  {pct(truth[name], wall):5.1f}%   {kind}")
    cpu = sum(v for k, v in truth.items() if k != "charge_payment")
    off = truth["charge_payment"]
    print(f"  ---- on-CPU {cpu * 1000:6.1f} ms ({pct(cpu, wall):.1f}%)   "
          f"off-CPU {off * 1000:6.1f} ms ({pct(off, wall):.1f}%)")
    print("  Every profiler below is graded against this table.")
    return truth, wall


def _tiny(x: int) -> int:
    """A function so cheap that the profiler costs more than the body."""
    return x + 1


def _cprofile_per_call_cost(n: int = 200_000) -> tuple[float, float]:
    """Time n calls to _tiny with and without the deterministic profiler."""
    t0 = perf_counter()
    for i in range(n):
        _tiny(i)
    plain = (perf_counter() - t0) / n
    prof = cProfile.Profile()
    prof.enable()
    t0 = perf_counter()
    for i in range(n):
        _tiny(i)
    traced = (perf_counter() - t0) / n
    prof.disable()
    return plain, traced


def section_2_cprofile(baseline: float, truth: dict[str, float]) -> tuple[dict, dict]:
    banner(2, "cProfile: EXACT COUNTS, DISTORTED TIME")
    GT.reset()
    prof = cProfile.Profile()
    t0 = perf_counter()
    prof.enable()
    checkout(ORDER)
    prof.disable()
    under = perf_counter() - t0
    run_truth = dict(GT.total)

    def table(sort: str, n: int) -> list[str]:
        buf = io.StringIO()
        pstats.Stats(prof, stream=buf).strip_dirs().sort_stats(sort).print_stats(n)
        lines = [ln.rstrip() for ln in buf.getvalue().splitlines() if ln.strip()]
        head = next(i for i, ln in enumerate(lines) if ln.strip().startswith("ncalls"))
        return lines[head: head + n + 1]

    print("  --- sorted by CUMULATIVE time: every caller of the slow thing ---")
    for ln in table("cumulative", 6):
        print("   " + ln.strip())
    print("  --- sorted by TOTTIME (self time): where the work actually is ---")
    for ln in table("tottime", 6):
        print("   " + ln.strip())

    st = pstats.Stats(prof)
    cum: dict[str, float] = {}
    for (_f, _l, fn), (_cc, _nc, _tt, ct, _cal) in st.stats.items():
        if fn in COMPONENTS:
            cum[fn] = ct
    _f, nc, tt, ct, _c = next(v for (_a, _b, fn), v in st.stats.items()
                              if fn == "fetch_price")
    print(f"  fetch_price: ncalls={nc:,}  tottime={tt * 1000:6.1f} ms  "
          f"cumtime={ct * 1000:6.1f} ms  = {ct / nc * 1e6:.2f} us per call")
    print("  Nothing about that per-call number says 'bug'. The COUNT does.")
    print(f"  workload alone       {baseline * 1000:7.1f} ms   (best of 3, no profiler)")
    print(f"  workload + cProfile  {under * 1000:7.1f} ms   "
          f"= +{pct(under - baseline, baseline):.1f}% wall")
    print("  That total UNDERSTATES the damage, because a sleep and three")
    print("  deadline-driven burns cannot be slowed down. Look per component:")
    for name, shape in (("price_line_items", "50,000 calls"), ("compute_tax", "1 call")):
        drift = pct(run_truth[name] - truth[name], truth[name])
        print(f"    {name} ({shape})".ljust(38)
              + f"true {truth[name] * 1000:6.1f} ms  ->  under cProfile "
                f"{run_truth[name] * 1000:6.1f} ms  ({drift:+.1f}%)")
    plain, traced = _cprofile_per_call_cost()
    print(f"  the per-call tax, isolated: 200,000 calls to a one-line function")
    print(f"    plain {plain * 1e9:6.0f} ns/call   under cProfile {traced * 1e9:6.0f} ns/call"
          f"   = {traced / plain:.1f}x")
    print("  A deterministic profiler taxes CALLS, not time. It therefore makes")
    print("  many-small-calls code look hotter than it is: it distorts the very")
    print("  profile you are reading, and always in the same direction.")
    return cum, run_truth


def _run_sampled(sampler, reps: int) -> tuple[dict[str, float], float]:
    """Run `reps` requests under a sampler, keeping that run's ground truth."""
    GT.reset()
    t0 = perf_counter()
    with sampler:
        run_requests(reps)
    return dict(GT.total), (perf_counter() - t0) / reps


def _worst_error(attr: dict[str, int], run_truth: dict[str, float]) -> float:
    n, tot = sum(attr.values()), sum(run_truth.values())
    return max(abs(pct(attr.get(c, 0), n) - pct(run_truth[c], tot)) for c in COMPONENTS)


def section_3_samplers(truth: dict[str, float], baseline: float,
                       cum: dict[str, float], cum_truth: dict[str, float]):
    banner(3, "TWO SAMPLING PROFILERS, BUILT FROM SCRATCH")
    reps = 3
    tid = threading.get_ident()

    on_cpu = OnCpuSampler(interval=0.001)
    cpu_truth, cpu_wall = _run_sampled(on_cpu, reps)
    wall_s = WallClockSampler(tid, interval=0.001)
    wall_truth, wall_wall = _run_sampled(wall_s, reps)

    a_cpu, a_wall = attribute(on_cpu.counts), attribute(wall_s.counts)
    n_cpu, n_wall = sum(a_cpu.values()), sum(a_wall.values())
    tot = sum(truth.values())
    print(f"  on-CPU     (SIGPROF / ITIMER_PROF, 1 ms): {on_cpu.samples:5,} samples / "
          f"{reps} requests, +{pct(cpu_wall - baseline, baseline):.1f}% overhead")
    print(f"  wall-clock (thread + _current_frames, 1 ms): {wall_s.samples:5,} samples / "
          f"{reps} requests, +{pct(wall_wall - baseline, baseline):.1f}% overhead")
    print()
    print("  component               TRUTH   cProfile   on-CPU   wall-clock")
    for name in COMPONENTS:
        flag = "   <- INVISIBLE" if name == "charge_payment" else ""
        print(f"  {name:<22} {pct(truth[name], tot):6.1f}%   "
              f"{pct(cum.get(name, 0.0), sum(cum.values())):7.1f}%  "
              f"{pct(a_cpu.get(name, 0), n_cpu):7.1f}%  "
              f"{pct(a_wall.get(name, 0), n_wall):9.1f}%{flag}")
    cum_attr = {c: int(cum.get(c, 0.0) * 1e6) for c in COMPONENTS}
    print("  worst error against the ground truth measured DURING each run:")
    print(f"    cProfile {_worst_error(cum_attr, cum_truth):.2f} pts · "
          f"on-CPU {_worst_error(a_cpu, cpu_truth):.2f} pts · "
          f"wall-clock {_worst_error(a_wall, wall_truth):.2f} pts")
    print("  The on-CPU sampler is not wrong about CPU. It answers a question")
    print("  nobody asked when the complaint is 'checkout takes a second'.")

    # The same sampler, with the interpreter's default thread switch interval.
    old = sys.getswitchinterval()
    naive = WallClockSampler(tid, interval=0.001, switch_interval=None)
    naive_truth, _ = _run_sampled(naive, 2)
    a_naive = attribute(naive.counts)
    print(f"  Same sampler, default {old * 1000:.0f} ms GIL switch interval instead of 0.2 ms:")
    print(f"    charge_payment reads {pct(a_naive.get('charge_payment', 0), sum(a_naive.values())):.1f}% "
          f"(truth {pct(naive_truth['charge_payment'], sum(naive_truth.values())):.1f}%), "
          f"worst error {_worst_error(a_naive, naive_truth):.1f} pts")
    print("  A sampler that must win the GIL is starved exactly while the target")
    print("  burns CPU, so it over-counts the idle parts. Real samplers read the")
    print("  target from OUTSIDE the process for precisely this reason.")
    return wall_s.counts


def section_4_flame(counts: dict[tuple[str, ...], int]) -> None:
    banner(4, "FOLDED STACKS AND A FLAME GRAPH")
    folded = fold(counts)
    print(f"  {sum(counts.values()):,} samples collapsed into {len(folded)} unique "
          f"stacks. The folded format is the whole artifact:")
    for line in sorted(folded, key=lambda s: -int(s.rsplit(" ", 1)[1]))[:6]:
        print("    " + line)
    print("  Rendered (width = share of samples, y = stack depth):")
    for row in render_flame(counts):
        print(row)
    print("  Plateaus are where the time is. Children are ordered")
    print("  ALPHABETICALLY so identical stacks merge -- the x-axis is not time.")


def section_5_amdahl(truth: dict[str, float]) -> None:
    banner(5, "AMDAHL'S LAW: COMPUTE THE CEILING BEFORE YOU START")
    tot = sum(truth.values())
    print("  speedup = 1 / ((1-f) + f/k)     f = fraction of runtime, k = factor faster")
    print("  component                 f     k=2     k=10    k=inf   ms saved   verdict")
    for name in COMPONENTS:
        f = truth[name] / tot

        def sp(k: float) -> float:
            return 1.0 / ((1 - f) + (0.0 if k == float("inf") else f / k))
        saved = tot * 1000 - tot * 1000 / sp(float("inf"))
        verdict = "worth a sprint" if f >= 0.10 else "walk away unless free"
        print(f"  {name:<22} {f * 100:5.1f}%  {sp(2):5.2f}x  {sp(10):6.2f}x  "
              f"{sp(float('inf')):6.2f}x  {saved:8.0f}   {verdict}")
    f_ser = truth["serialize_response"] / tot
    f_wait = truth["charge_payment"] / tot
    print(f"  The senior engineer's rewrite of serialize_response: at k=INFINITY the")
    print(f"  endpoint gets {f_ser * 100:.1f}% faster. That is the whole prize. Two weeks for it.")
    print(f"  The wait is f={f_wait * 100:.1f}%: making it 10x faster is "
          f"{1 / ((1 - f_wait) + f_wait / 10):.2f}x end to end.")
    print("  Do this arithmetic BEFORE the sprint, not in the retro.")


def section_6_tracemalloc() -> None:
    banner(6, "tracemalloc: ONLY THE DIFF CAN FIND A LEAK")
    retained: list = []

    def leaky_cache_write(n: int) -> None:
        # An unbounded cache: nothing here ever evicts. This is the leak.
        for i in range(n):
            retained.append({"order": i, "blob": "x" * 96})

    def transient_report(n: int) -> int:
        # A big allocation that is entirely freed on return: a high-water mark.
        rows = [{"order": i, "blob": "y" * 96} for i in range(n)]
        return len(rows)

    tracemalloc.start(1)
    leaky_cache_write(200)                       # warm the allocator
    snap1 = tracemalloc.take_snapshot()
    for _ in range(10):
        leaky_cache_write(2_000)                 # genuine unbounded retention
        transient_report(20_000)                 # high-water mark, then freed
    snap2 = tracemalloc.take_snapshot()
    cur, peak = tracemalloc.get_traced_memory()

    print(f"  one snapshot at the end: current {cur / 1e6:6.2f} MB   peak {peak / 1e6:6.2f} MB")
    print("  A single number cannot tell a leak from a high-water mark. The diff can:")
    for stat in snap2.compare_to(snap1, "lineno")[:3]:
        fr = stat.traceback[0]
        src = linecache.getline(fr.filename, fr.lineno).strip()[:52]
        print(f"    {stat.size_diff / 1e6:+7.2f} MB  {stat.count_diff:+8,} blocks  "
              f"{fr.filename.rsplit('/', 1)[-1]}:{fr.lineno}  {src}")
    print(f"  retained now holds {len(retained):,} dicts and never shrinks: THE LEAK.")
    print(f"  transient_report allocated {(peak - cur) / 1e6:.2f} MB more at its peak and gave")
    print("  it all back -- it inflates RSS, it is not a leak, and the diff ignores it.")
    tracemalloc.stop()


def section_7_async() -> None:
    banner(7, "ASYNC: A SUSPENDED COROUTINE IS ON NO STACK AT ALL")
    AWAIT_S, BURN_S, N_REQ = 0.30, 0.05, 3
    durations: list[float] = []

    async def order_handler(idx: int) -> None:
        t0 = perf_counter()
        await asyncio.sleep(AWAIT_S)     # awaiting the payments API: suspended
        _burn(BURN_S)                    # a blocking call smuggled into a coroutine
        durations.append(perf_counter() - t0)

    async def loop_lag_monitor(stop: asyncio.Event, out: list[float]) -> None:
        while not stop.is_set():
            t0 = perf_counter()
            await asyncio.sleep(0.005)
            out.append(perf_counter() - t0 - 0.005)

    async def main() -> tuple[list[float], float]:
        stop, lag = asyncio.Event(), []
        mon = asyncio.create_task(loop_lag_monitor(stop, lag))
        t0 = perf_counter()
        await asyncio.gather(*(order_handler(i) for i in range(N_REQ)))
        wall = perf_counter() - t0
        stop.set()
        await mon
        return lag, wall

    sampler = WallClockSampler(threading.get_ident(), interval=0.001, root=None)
    with sampler:
        lag, wall = asyncio.run(main())

    total = max(1, sampler.samples)
    in_handler = sum(n for st, n in sampler.counts.items() if "order_handler" in st)
    logical = sum(durations)
    on_stack_ms = in_handler * sampler.interval * 1000
    print(f"  {N_REQ} concurrent requests, {wall * 1000:.0f} ms wall clock, "
          f"{sampler.samples} wall-clock samples")
    print(f"  logical request time actually elapsed: {logical * 1000:.0f} ms "
          f"({N_REQ} x {logical / N_REQ * 1000:.0f} ms)")
    print(f"  samples with order_handler anywhere on the stack: {in_handler} "
          f"({pct(in_handler, total):.1f}%) ~= {on_stack_ms:.0f} ms")
    print("  Where every sample went:")
    for st, n in sorted(sampler.counts.items(), key=lambda kv: -kv[1])[:3]:
        print(f"    {pct(n, total):5.1f}%  {';'.join(st[-4:])}")
    print(f"  The {AWAIT_S * 1000:.0f} ms await is on NO stack: a suspended coroutine has no")
    print(f"  frames to sample. The profiler accounts for {on_stack_ms:.0f} ms of "
          f"{logical * 1000:.0f} ms")
    print(f"  of request time -- {pct(on_stack_ms / 1000, logical):.0f}%. The other "
          f"{pct(1 - on_stack_ms / 1000 / logical, 1):.0f}% is charged to the event")
    print("  loop's own select() frame, which no engineer can act on.")
    print("  Loop lag finds what the stacks could not:")
    lag_ms = sorted(x * 1000 for x in lag)
    print(f"    {len(lag_ms)} probes: p50 {lag_ms[len(lag_ms) // 2]:.2f} ms   "
          f"p95 {lag_ms[int(len(lag_ms) * 0.95)]:.1f} ms   max {lag_ms[-1]:.0f} ms")
    print(f"  A p50 of {lag_ms[len(lag_ms) // 2]:.2f} ms and a max of {lag_ms[-1]:.0f} ms is the "
          f"signature of {N_REQ} x {BURN_S * 1000:.0f} ms")
    print("  of blocking CPU running back to back without yielding. That is the")
    print("  bug, and loop lag names it in one number.")


def main() -> None:
    print(f"Python {sys.version.split()[0]}  ·  spin rate {ITERS_PER_SEC / 1e6:.1f}M iters/s"
          f"  ·  fetch_price calibrated to {FETCH_ITERS} iters")
    truth, baseline = section_1_ground_truth()
    cum, cum_truth = section_2_cprofile(baseline, truth)
    wall_counts = section_3_samplers(truth, baseline, cum, cum_truth)
    section_4_flame(wall_counts)
    section_5_amdahl(truth)
    section_6_tracemalloc()
    section_7_async()
    print("\nDone. Measure, compute the ceiling, change one thing, measure again.")


if __name__ == "__main__":
    main()
