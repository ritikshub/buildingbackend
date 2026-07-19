#!/usr/bin/env python3
"""
Chaos engineering measured rather than argued: a discrete-event simulation of a
four-service dependency graph with connection pools, timeouts, retries and
circuit breakers. It states a steady-state hypothesis, hard-kills a dependency
versus making it 5x slower, drives a retry storm into a metastable failure and
back out, prices five defence configurations against one fault, sweeps the
blast radius from 1% to 100% with an SLO-tied abort, and treats canary analysis
as a statistical test rather than a threshold.

Companion to docs/en.md (Phase 12, Lesson 14). Standard library only, every RNG
seeded from SEED = 20260718, no network, no files written, self-terminating in
about ten seconds. Sources: Basiri, Behnam, de Rooij, Hochstein, Kosewski,
Reynolds & Rosenthal, *Chaos Engineering*, IEEE Software 33(3), 2016; Bronson,
Aghayev, Charapko & Zhu, *Metastable Failures in Distributed Systems*, HotOS
2021; Little, *A Proof for the Queuing Formula L = lambda W*, Operations
Research 9(3), 1961; Mann & Whitney, *On a Test of Whether one of Two Random
Variables is Stochastically Larger than the Other*, Annals of Mathematical
Statistics 18(1), 1947; Wald, *Sequential Analysis*, Wiley, 1947.

Run:  python3 chaos.py
"""

from __future__ import annotations

import heapq
import math
import random
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Generator, List, Optional, Sequence, Tuple

SEED = 20260718

# Outcomes a call can end with. Everything that is not OK burns error budget.
OK = "ok"
ERR = "err"                  # the dependency answered with an error
TIMED_OUT = "timeout"        # we gave up waiting
REFUSED = "refused"          # nothing was listening (a hard kill)
BREAKER = "breaker_open"     # we refused to try
NO_BUDGET = "retry_budget"   # we were allowed one attempt, not three
SHED = "shed"                # we refused the work on purpose

# The service level objective the whole lesson hypothesises on. A user request
# is GOOD if it returns a non-error answer within LATENCY_SLI_MS. Anything else
# spends error budget. See Phase 9 Lesson 9 for why a latency SLI needs a
# threshold rather than an average.
SLO_TARGET = 0.995
LATENCY_SLI_MS = 400.0
BUDGET_WINDOW_DAYS = 28

Cmd = Tuple[Any, ...]
Proc0 = Generator[Cmd, Any, Any]


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def pctl(xs: Sequence[float], p: float) -> float:
    """Nearest-rank percentile on an already-collected sample."""
    if not xs:
        return float("nan")
    ys = sorted(xs)
    k = max(0, min(len(ys) - 1, int(math.ceil(p / 100.0 * len(ys))) - 1))
    return ys[k]


# ══ 1 · A DISCRETE-EVENT SIMULATOR IN ABOUT A HUNDRED LINES ══════════════════
# Nothing here sleeps. `now` is a number that jumps to the next scheduled event,
# so 80 seconds of a saturated fleet costs a fraction of a real second. Every
# tie in the event heap is broken by an incrementing sequence number, which is
# what makes two runs of this file byte-identical.

class Future:
    """A value that will exist later. Fired at most once."""
    __slots__ = ("done", "value", "waiters")

    def __init__(self) -> None:
        self.done = False
        self.value: Any = None
        self.waiters: List["Proc"] = []


class Sim:
    def __init__(self) -> None:
        self.now = 0.0
        self._heap: List[Tuple[float, int, Callable[[], None]]] = []
        self._seq = 0

    def at(self, delay: float, fn: Callable[[], None]) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (self.now + delay, self._seq, fn))

    def spawn(self, gen: Proc0) -> Future:
        proc = Proc(self, gen)
        self.at(0.0, proc.start)
        return proc.future

    def fire(self, fut: Future, value: Any) -> None:
        if fut.done:
            return
        fut.done, fut.value = True, value
        waiters, fut.waiters = fut.waiters, []
        for w in waiters:
            self.at(0.0, lambda w=w, v=value: w.resume(v))

    def run(self, until: float) -> None:
        heap = self._heap
        while heap and heap[0][0] <= until:
            t, _, fn = heapq.heappop(heap)
            self.now = t
            fn()
        self.now = until


class Proc:
    """A request, expressed as a generator that yields what it is waiting for."""
    __slots__ = ("sim", "gen", "future")

    def __init__(self, sim: Sim, gen: Proc0) -> None:
        self.sim, self.gen, self.future = sim, gen, Future()

    def start(self) -> None:
        self.resume(None)

    def resume(self, value: Any) -> None:
        try:
            cmd = self.gen.send(value)
        except StopIteration as stop:
            self.sim.fire(self.future, stop.value)
            return
        kind = cmd[0]
        if kind == "sleep":
            self.sim.at(cmd[1], lambda: self.resume(None))
        elif kind == "wait":
            fut: Future = cmd[1]
            if fut.done:
                self.sim.at(0.0, lambda: self.resume(fut.value))
            else:
                fut.waiters.append(self)
        elif kind == "acquire":
            cmd[1].acquire(self)
        else:  # pragma: no cover - programming error
            raise AssertionError(f"unknown command {kind!r}")


class Pool:
    """A bounded set of slots: a connection pool, or a service's worker threads.

    `queue_limit=None` is the default almost every real client ships with — an
    unbounded wait queue. Section 4 measures what bounding it is worth.
    """

    def __init__(self, sim: Sim, size: int, queue_limit: Optional[int] = None) -> None:
        self.sim, self.size, self.free = sim, size, size
        self.queue_limit = queue_limit
        self.waiters: deque = deque()
        self.peak_queue = 0
        self.shed = 0
        self.util_samples: List[float] = []

    def acquire(self, proc: Proc) -> None:
        if self.free > 0:
            self.free -= 1
            self.sim.at(0.0, lambda: proc.resume(True))
        elif self.queue_limit is not None and len(self.waiters) >= self.queue_limit:
            self.shed += 1
            self.sim.at(0.0, lambda: proc.resume(False))
        else:
            self.waiters.append(proc)
            if len(self.waiters) > self.peak_queue:
                self.peak_queue = len(self.waiters)

    def release(self) -> None:
        if self.waiters:
            nxt = self.waiters.popleft()
            self.sim.at(0.0, lambda: nxt.resume(True))
        else:
            self.free += 1

    def sample(self) -> None:
        self.util_samples.append((self.size - self.free) / self.size)


# ══ 2 · THE SYSTEM UNDER EXPERIMENT ══════════════════════════════════════════
# api -> orders -> {payments (required), inventory (optional, has a fallback)}.
# Four services, three call edges, each edge with its own pool, timeout, retry
# policy, retry budget and circuit breaker.

@dataclass
class Policy:
    pool_size: int
    timeout_ms: float = 1e9          # 1e9 ms == "no timeout", the default nobody sets
    attempts: int = 1                # 1 == no retry
    backoff_ms: float = 25.0
    jitter: bool = False
    budget_ratio: Optional[float] = None   # retries allowed per primary request
    breaker: bool = False
    queue_limit: Optional[int] = None
    required: bool = True            # False == the caller has a fallback


class Breaker:
    """Error-counting circuit breaker. Note what it counts: ERRORS. A dependency
    that has become slow but still answers correctly produces none, which is the
    entire reason section 2 exists."""

    def __init__(self, window: int = 20, threshold: float = 0.5,
                 open_ms: float = 2000.0, min_samples: int = 8) -> None:
        self.results: deque = deque(maxlen=window)
        self.threshold, self.open_ms, self.min_samples = threshold, open_ms, min_samples
        self.opened_at: Optional[float] = None
        self.trips: List[float] = []

    def blocked(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= self.open_ms:
            self.opened_at = None      # half-open: the next call is a probe
            self.results.clear()
            return False
        return True

    def record(self, ok: bool, now: float) -> None:
        self.results.append(1 if ok else 0)
        if self.opened_at is None and len(self.results) >= self.min_samples:
            bad = len(self.results) - sum(self.results)
            if bad / len(self.results) > self.threshold:
                self.opened_at = now
                self.trips.append(now)
                self.results.clear()


class RetryBudget:
    """A token bucket: each primary request mints `ratio` tokens, each retry
    spends one. This is what caps amplification at (1 + ratio) instead of
    `attempts`, and it is the single defence section 3 turns on."""

    def __init__(self, ratio: float, capacity: float = 20.0) -> None:
        self.ratio, self.capacity, self.tokens = ratio, capacity, capacity
        self.denied = 0

    def credit(self) -> None:
        self.tokens = min(self.capacity, self.tokens + self.ratio)

    def take(self) -> bool:
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True
        self.denied += 1
        return False


@dataclass
class Req:
    rid: int
    cohort: int                # 0..99, the blast-radius bucket
    t_start: float
    t_end: float = -1.0
    outcome: str = "in_flight"
    degraded: bool = False

    @property
    def latency(self) -> float:
        return 1e9 if self.t_end < 0 else self.t_end - self.t_start

    @property
    def good(self) -> bool:
        return self.outcome == OK and self.latency <= LATENCY_SLI_MS


@dataclass
class Fault:
    target: str = ""
    kind: str = "none"         # "kill" | "slow"
    factor: float = 1.0
    start: float = 0.0
    end: float = 0.0
    cohort_pct: int = 100      # inject only into requests with cohort < this


class Service:
    def __init__(self, sim: Sim, name: str, workers: int, local_ms: float,
                 rng: random.Random, queue_limit: Optional[int] = None) -> None:
        self.sim, self.name, self.local_ms, self.rng = sim, name, local_ms, rng
        self.pool = Pool(sim, workers, queue_limit)
        self.edges: List["Edge"] = []
        self.fault = Fault()

    def _faulted(self, req: Req) -> bool:
        f = self.fault
        return (f.kind != "none" and f.start <= self.sim.now < f.end
                and req.cohort < f.cohort_pct)

    def refuses(self, req: Req) -> bool:
        """A hard kill: nothing is listening, so the caller learns instantly."""
        return self._faulted(req) and self.fault.kind == "kill"

    def handle(self, req: Req) -> Proc0:
        got = yield ("acquire", self.pool)
        if not got:
            return SHED
        work = self.local_ms * math.exp(self.rng.gauss(0.0, 0.30))
        if self._faulted(req) and self.fault.kind == "slow":
            work *= self.fault.factor
        yield ("sleep", work)
        result = OK
        for edge in self.edges:
            r = yield from edge.call(req)
            if r != OK:
                if edge.policy.required:
                    result = r
                    break
                req.degraded = True
        self.pool.release()
        return result


class Edge:
    """One caller-side dependency: its pool, its timeout, its retry policy, its
    budget and its breaker. This object is where every defence in the lesson
    lives, and where every ablation switch turns off."""

    def __init__(self, sim: Sim, dep: Service, policy: Policy, rng: random.Random) -> None:
        self.sim, self.dep, self.policy, self.rng = sim, dep, policy, rng
        self.pool = Pool(sim, policy.pool_size, policy.queue_limit)
        self.breaker = Breaker() if policy.breaker else None
        self.budget = RetryBudget(policy.budget_ratio) if policy.budget_ratio else None
        self.attempt_times: List[float] = []           # one entry per WIRE attempt
        self.primary_sent = 0
        self.outcomes: List[Tuple[float, bool]] = []   # (t, ok) per primary call
        self.lat_samples: List[Tuple[float, float]] = []
        self.wait_samples: List[Tuple[float, float]] = []   # time spent in the pool
        self.refused = 0            # calls we declined to make: breaker or budget

    def attempt_log_count(self, lo: float, hi: float) -> int:
        return sum(1 for t in self.attempt_times if lo <= t < hi)

    def call(self, req: Req) -> Proc0:
        t0 = self.sim.now
        self.primary_sent += 1
        if self.budget:
            self.budget.credit()
        outcome = ERR
        for attempt in range(self.policy.attempts):
            if self.breaker and self.breaker.blocked(self.sim.now):
                outcome = BREAKER
                self.refused += 1
                break
            if attempt:
                if self.budget and not self.budget.take():
                    outcome = NO_BUDGET
                    self.refused += 1
                    break
                delay = self.policy.backoff_ms * (2 ** (attempt - 1))
                if self.policy.jitter:
                    delay = self.rng.random() * delay     # full jitter
                yield ("sleep", delay)
            t_acq = self.sim.now
            got = yield ("acquire", self.pool)
            self.wait_samples.append((t_acq, self.sim.now - t_acq))
            if not got:
                outcome = SHED
                break
            # NOTE: the request timeout starts HERE, after a connection was
            # obtained — which is what almost every real HTTP client does. Time
            # spent waiting for a pool slot is governed by a separate acquire
            # timeout that is usually unset. Section 2 measures what that costs.
            self.attempt_times.append(self.sim.now)
            if self.dep.refuses(req):
                self.pool.release()
                outcome = REFUSED
            else:
                fut = self.sim.spawn(self.dep.handle(req))
                # The timeout fires the SAME future. Whichever happens first
                # wins — and note that losing does not stop the downstream work.
                self.sim.at(self.policy.timeout_ms,
                            lambda f=fut: self.sim.fire(f, TIMED_OUT))
                outcome = yield ("wait", fut)
                self.pool.release()
            if self.breaker:
                self.breaker.record(outcome == OK, self.sim.now)
            if outcome == OK:
                break
        self.outcomes.append((t0, outcome == OK))
        self.lat_samples.append((t0, self.sim.now - t0))
        return outcome


@dataclass
class Topology:
    sim: Sim
    services: Dict[str, Service]
    edges: Dict[str, Edge]
    entry: Service


def build(sim: Sim, cfg: Dict[str, Policy], rng: random.Random) -> Topology:
    """Four services. Sized from Little's law (L = lambda x W, Little 1961) so
    that at the baseline rate every pool sits under half full."""
    api = Service(sim, "api", workers=64, local_ms=3.0, rng=random.Random(rng.random()))
    orders = Service(sim, "orders", workers=16, local_ms=8.0, rng=random.Random(rng.random()))
    payments = Service(sim, "payments", workers=4, local_ms=35.0, rng=random.Random(rng.random()))
    inventory = Service(sim, "inventory", workers=8, local_ms=40.0, rng=random.Random(rng.random()))

    e_orders = Edge(sim, orders, cfg["api->orders"], random.Random(rng.random()))
    e_pay = Edge(sim, payments, cfg["orders->payments"], random.Random(rng.random()))
    e_inv = Edge(sim, inventory, cfg["orders->inventory"], random.Random(rng.random()))
    api.edges = [e_orders]
    orders.edges = [e_pay, e_inv]

    return Topology(sim, {"api": api, "orders": orders, "payments": payments,
                          "inventory": inventory},
                    {"api->orders": e_orders, "orders->payments": e_pay,
                     "orders->inventory": e_inv}, api)


# ══ 3 · THE WORKLOAD, THE SLI AND THE ABORT CONDITION ════════════════════════

BASE_POLICIES: Dict[str, Policy] = {
    # The "well-configured" system from The Problem: every edge has a timeout,
    # a retry, jitter, a budget and a breaker. All reviewed. None ever executed.
    "api->orders": Policy(pool_size=48, timeout_ms=800.0, attempts=1),
    "orders->payments": Policy(pool_size=10, timeout_ms=300.0, attempts=3,
                               backoff_ms=25.0, jitter=True, budget_ratio=0.10,
                               breaker=True),
    "orders->inventory": Policy(pool_size=6, timeout_ms=250.0, attempts=3,
                                backoff_ms=25.0, jitter=True, budget_ratio=0.10,
                                breaker=True, required=False),
}


@dataclass
class Result:
    name: str
    reqs: List[Req]
    topo: Topology
    aborted_at: Optional[float] = None
    windows: List[Tuple[float, int, int, float]] = field(default_factory=list)

    def slice(self, t0: float, t1: float) -> List[Req]:
        return [r for r in self.reqs if t0 <= r.t_start < t1]

    def summary(self, t0: float, t1: float) -> Tuple[int, float, float, float]:
        rs = self.slice(t0, t1)
        if not rs:
            return 0, float("nan"), float("nan"), float("nan")
        good = sum(1 for r in rs if r.good)
        lats = [min(r.latency, 60000.0) for r in rs]
        return len(rs), good / len(rs), pctl(lats, 50), pctl(lats, 99)

    def budget_burned(self, t0: float, t1: float) -> Tuple[int, float, float]:
        """Bad requests; the MINUTES of error budget they cost; and that as a
        share of a 28-day budget. The SLO allows RATE*(1-target) bad requests
        per second, so dividing by that rate converts a count into the wall time
        the budget was meant to cover — which is the number that makes an
        experiment's price legible."""
        rs = self.slice(t0, t1)
        bad = sum(1 for r in rs if not r.good)
        per_s = RATE * (1 - SLO_TARGET)
        minutes = bad / per_s / 60.0
        allowed = RATE * 86400 * BUDGET_WINDOW_DAYS * (1 - SLO_TARGET)
        return bad, minutes, 100.0 * bad / allowed


RATE = 70.0            # user requests per second, open loop
WARMUP_S = 10.0        # the steady state we measure the hypothesis on
MONITOR_LAG_MS = 3000.0  # a monitor cannot score a second until it has closed


def arrivals(sim: Sim, topo: Topology, reqs: List[Req], duration_s: float,
             rng: random.Random) -> Proc0:
    gap_ms = 1000.0 / RATE
    rid = 0
    while sim.now < duration_s * 1000.0:
        yield ("sleep", rng.expovariate(1.0 / gap_ms))
        if sim.now >= duration_s * 1000.0:
            return
        rid += 1
        req = Req(rid=rid, cohort=(rid * 37) % 100, t_start=sim.now)
        reqs.append(req)
        sim.spawn(_user(sim, topo, req))


def _user(sim: Sim, topo: Topology, req: Req) -> Proc0:
    out = yield from topo.edges["api->orders"].call(req)
    req.outcome = out
    req.t_end = sim.now


def monitor(sim: Sim, topo: Topology, reqs: List[Req], result: Result,
            abort_after: Optional[int], fault: Fault) -> Proc0:
    """The steady-state monitor. Every second it scores one second of user
    traffic against the SLO, and — if this is a blast-radius-controlled
    experiment — halts the fault when the SLO has been breached for
    `abort_after` consecutive windows.

    Note the LAG. A request that has not answered yet has not yet failed, so a
    monitor reading the current second always reads it as healthy. Scoring a
    window that closed MONITOR_LAG_MS ago is the honest version, and that lag is
    a floor under every time-to-detect number in this file."""
    breaches = 0
    while True:
        yield ("sleep", 1000.0)
        t1 = sim.now - MONITOR_LAG_MS
        if t1 <= 0.0:
            continue
        t0 = t1 - 1000.0
        window = [r for r in reqs if t0 <= r.t_start < t1]
        n = len(window)
        good = sum(1 for r in window if r.good)
        rate = good / n if n else 1.0
        lats = [min(r.latency, 60000.0) for r in window]
        result.windows.append((t1, n, good, pctl(lats, 99) if lats else 0.0))
        for pool in _all_pools(topo):
            pool.sample()
        if abort_after is not None and result.aborted_at is None:
            breaches = breaches + 1 if rate < SLO_TARGET else 0
            if breaches >= abort_after:
                result.aborted_at = sim.now
                fault.end = min(fault.end, sim.now)


def _all_pools(topo: Topology) -> List[Pool]:
    return ([s.pool for s in topo.services.values()]
            + [e.pool for e in topo.edges.values()])


def run(name: str, policies: Dict[str, Policy], fault: Fault,
        duration_s: float, drain_s: float = 25.0,
        abort_after: Optional[int] = None, seed: int = SEED) -> Result:
    rng = random.Random(seed)
    sim = Sim()
    topo = build(sim, policies, rng)
    if fault.target:
        topo.services[fault.target].fault = fault
    reqs: List[Req] = []
    result = Result(name=name, reqs=reqs, topo=topo)
    sim.spawn(arrivals(sim, topo, reqs, duration_s, random.Random(rng.random())))
    sim.spawn(monitor(sim, topo, reqs, result, abort_after, fault))
    sim.run((duration_s + drain_s) * 1000.0)
    for r in reqs:                       # never finished: that is a failure
        if r.t_end < 0:
            r.outcome = TIMED_OUT
    return result


def detect(result: Result, edge: str, inject_ms: float,
           avail_thresh: float = 0.99, lat_thresh: float = 400.0) -> Tuple[Any, Any]:
    """When would a dependency-level SLI have noticed? Two detectors, one on
    error rate and one on latency, both on 1-second windows."""
    e = result.topo.edges[edge]
    t_avail = t_lat = None
    end = math.floor(max([t for t, _ in e.outcomes], default=0.0) / 1000.0) + 1
    for w in range(int(inject_ms // 1000), end):
        lo, hi = w * 1000.0, (w + 1) * 1000.0
        outs = [ok for t, ok in e.outcomes if lo <= t < hi]
        lats = [d for t, d in e.lat_samples if lo <= t < hi]
        if outs and t_avail is None and sum(outs) / len(outs) < avail_thresh:
            t_avail = hi - inject_ms
        if lats and t_lat is None and pctl(lats, 99) > lat_thresh:
            t_lat = hi - inject_ms
    return t_avail, t_lat


def first_user_impact(result: Result, inject_ms: float) -> Any:
    bad = [r.t_start for r in result.reqs if r.t_start >= inject_ms and not r.good]
    return (min(bad) - inject_ms) if bad else None


def recovery_time(result: Result, fault_end_ms: float) -> Any:
    """How long after the trigger is removed until three consecutive good
    seconds. `None` means it never came back inside the run."""
    ok_run = 0
    for t1, n, good, _ in result.windows:
        if t1 <= fault_end_ms or n == 0:
            continue          # an empty window is not evidence of health
        ok_run = ok_run + 1 if good / n >= SLO_TARGET else 0
        if ok_run >= 3:
            return (t1 - 2000.0) - fault_end_ms
    return None


def fmt_ms(x: Any) -> str:
    if x is None:
        return "never"
    return f"{x / 1000.0:.1f} s"


# ══ 4 · SECTION 1 — THE STEADY-STATE HYPOTHESIS ══════════════════════════════

def section1() -> Result:
    banner(1, "THE STEADY STATE: THE HYPOTHESIS YOU CANNOT EXPERIMENT WITHOUT")
    base = run("steady", BASE_POLICIES, Fault(), duration_s=40.0)
    n, good, p50, p99 = base.summary(WARMUP_S * 1000.0, 40000.0)
    print(f"  4 services · 3 call edges · open-loop arrivals at {RATE:.0f} req/s")
    print(f"  SLO: {SLO_TARGET:.1%} of user requests answer OK within "
          f"{LATENCY_SLI_MS:.0f} ms (a request-based SLI, Phase 9 Lesson 9)")
    print(f"\n  hypothesis: over any 30-second window the system serves "
          f">= {SLO_TARGET:.1%} good")
    print(f"  measured  : {n} requests, {good:.4%} good, "
          f"p50 {p50:.0f} ms, p99 {p99:.0f} ms  ->  "
          f"{'HOLDS' if good >= SLO_TARGET else 'REFUTED'}")

    print("\n  the pools, and the headroom that is about to be spent:")
    print("    pool                    size   mean util   peak queue   "
          "L = lambda x W   slowdown it survives")
    rows = [
        ("edge orders->payments", base.topo.edges["orders->payments"].pool,
         RATE * 0.035),
        ("edge orders->inventory", base.topo.edges["orders->inventory"].pool,
         RATE * 0.040),
        ("edge api->orders", base.topo.edges["api->orders"].pool, RATE * 0.090),
        ("svc payments workers", base.topo.services["payments"].pool, RATE * 0.035),
        ("svc inventory workers", base.topo.services["inventory"].pool, RATE * 0.040),
        ("svc orders workers", base.topo.services["orders"].pool, RATE * 0.090),
    ]
    for label, pool, little in rows:
        util = sum(pool.util_samples) / max(1, len(pool.util_samples))
        head = pool.size / little
        print(f"    {label:<22} {pool.size:>4}   {util:>8.1%}   {pool.peak_queue:>10}"
              f"   {little:>9.2f}   {head:>16.1f}x")
    print("\n  the defences under experiment — all configured, all reviewed, none ever run:")
    print("    edge                 pool  timeout  attempts  jitter  budget  breaker  required")
    for name, pol in BASE_POLICIES.items():
        to = "none" if pol.timeout_ms > 1e8 else f"{pol.timeout_ms:.0f} ms"
        bud = f"{pol.budget_ratio:.2f}" if pol.budget_ratio else "none"
        print(f"    {name:<20} {pol.pool_size:>4}  {to:>7}  {pol.attempts:>8}"
              f"  {str(pol.jitter):>6}  {bud:>6}  {str(pol.breaker):>7}"
              f"  {str(pol.required):>8}")

    print("\n  Read the headroom column as a LATENCY budget. Little's law (Little 1961)")
    print("  says concurrency = arrival rate x hold time, so a pool with 2.1x")
    print("  headroom survives a dependency that gets 2.1x slower and nothing worse.")
    print("  Every one of those pools is under a third full. Nothing here looks fragile.")
    return base


# ══ 5 · SECTION 2 — GREY FAILURE: DOWN VERSUS SLOW ═══════════════════════════

GREY_INJECT_S = 15.0
GREY_HOLD_S = 20.0
GREY_TOTAL_S = 75.0        # 40 s of live traffic AFTER the fault is removed


def section2() -> Dict[str, Result]:
    banner(2, "GREY FAILURE: A HARD KILL VERSUS THE SAME DEPENDENCY 5x SLOWER")
    inject = GREY_INJECT_S * 1000.0
    end = (GREY_INJECT_S + GREY_HOLD_S) * 1000.0
    out: Dict[str, Result] = {}
    print(f"  identical experiment window: fault at t={GREY_INJECT_S:.0f} s, "
          f"removed at t={GREY_INJECT_S + GREY_HOLD_S:.0f} s, observed to "
          f"t={GREY_TOTAL_S:.0f} s")
    print(f"  inventory is OPTIONAL to the order (a fallback exists); "
          f"payments is REQUIRED.")
    print("\n    target      fault    dependency  dependency   first user    bad"
          "     error budget   good AFTER  recovers")
    print("                        SLI: errors  SLI: latency   impact     requests"
          "     burned       restored     after")
    for target, edge in (("inventory", "orders->inventory"),
                         ("payments", "orders->payments")):
        for kind, factor in (("kill", 1.0), ("slow", 5.0)):
            f = Fault(target=target, kind=kind, factor=factor, start=inject, end=end)
            r = run(f"{target}-{kind}", BASE_POLICIES, f,
                    duration_s=GREY_TOTAL_S, drain_s=30.0)
            out[f"{target}-{kind}"] = r
            t_av, t_lat = detect(r, edge, inject)
            imp = first_user_impact(r, inject)
            bad, mins, _ = r.budget_burned(inject, GREY_TOTAL_S * 1000.0)
            _, after, _, _ = r.summary(end, GREY_TOTAL_S * 1000.0)
            rec = recovery_time(r, end)
            label = "KILL" if kind == "kill" else "5x SLOW"
            print(f"    {target:<11} {label:<8} {fmt_ms(t_av):>10}    "
                  f"{fmt_ms(t_lat):>9}    {fmt_ms(imp):>8}   {bad:>7}"
                  f"   {mins:>7.1f} min      {after:>6.1%}    {fmt_ms(rec):>7}")
    print(f"\n  'error budget burned' is wall time: the SLO allows "
          f"{RATE * (1 - SLO_TARGET):.2f} bad requests")
    print("  per second, so N bad requests cost N/0.35 seconds of the month's budget.")

    print("\n  the mechanism — where the queue formed, and whether anything noticed:")
    print("    scenario           peak queue depth       breaker trips      user p50/p99")
    print("                   inv pool  pay pool  orders  inv-edge pay-edge  while faulted")
    for key in ("inventory-kill", "inventory-slow", "payments-kill", "payments-slow"):
        r = out[key]
        _, _, p50, p99 = r.summary(inject, end)
        print(f"    {key:<16} {r.topo.edges['orders->inventory'].pool.peak_queue:>7}"
              f"  {r.topo.edges['orders->payments'].pool.peak_queue:>8}"
              f"  {r.topo.services['orders'].pool.peak_queue:>6}"
              f"  {len(r.topo.edges['orders->inventory'].breaker.trips):>8}"
              f"  {len(r.topo.edges['orders->payments'].breaker.trips):>7}"
              f"   {p50:>6.0f} / {p99:<6.0f} ms")
    print("\n  Read the breaker columns against the fault kind. A breaker counts")
    print("  ERRORS, and a dependency that is merely slow produces none until a")
    print("  timeout converts one into the other.")
    return out


# ══ 6 · SECTION 3 — THE RETRY STORM AND THE METASTABLE FAILURE ═══════════════

STORM_INJECT_S = 15.0
STORM_HOLD_S = 30.0
STORM_TOTAL_S = 95.0


def storm_policies(mode: str) -> Dict[str, Policy]:
    """`naive` is three attempts, fixed backoff, no budget, no breaker — the
    default of every HTTP client library that offers retries at all."""
    p = dict(BASE_POLICIES)
    if mode == "naive":
        p["orders->payments"] = Policy(pool_size=10, timeout_ms=300.0, attempts=3,
                                       backoff_ms=25.0, jitter=False,
                                       budget_ratio=None, breaker=False)
    return p


def section3() -> Dict[str, Result]:
    banner(3, "THE RETRY STORM: A TRIGGER THAT LEAVES AND AN OUTAGE THAT STAYS")
    inject = STORM_INJECT_S * 1000.0
    end = (STORM_INJECT_S + STORM_HOLD_S) * 1000.0
    print(f"  payments runs 6x slower from t={STORM_INJECT_S:.0f} s to "
          f"t={STORM_INJECT_S + STORM_HOLD_S:.0f} s, then is FULLY RESTORED.")
    print("  Offered user load never changes. Watch what happens after t=45 s.")
    out: Dict[str, Result] = {}
    print("\n    retry policy          good WHILE   good AFTER    peak load     recovery"
          "     error budget")
    print("                            degraded     restored    amplification    time"
          "         burned")
    for mode in ("naive", "budgeted"):
        f = Fault(target="payments", kind="slow", factor=6.0, start=inject, end=end)
        r = run(f"storm-{mode}", storm_policies(mode), f,
                duration_s=STORM_TOTAL_S, drain_s=30.0)
        out[mode] = r
        _, during, _, _ = r.summary(inject, end)
        _, after, _, _ = r.summary(end, STORM_TOTAL_S * 1000.0)
        e = r.topo.edges["orders->payments"]
        amp = _peak_amplification(e, end, STORM_TOTAL_S * 1000.0)
        rec = recovery_time(r, end)
        bad, mins, _ = r.budget_burned(inject, STORM_TOTAL_S * 1000.0)
        label = "naive retry x3" if mode == "naive" else "budget+jitter+breaker"
        print(f"    {label:<21} {during:>9.1%}    {after:>9.1%}     "
              f"{amp:>8.2f}x     {fmt_ms(rec):>8}     {mins:>8.1f} min")

    print("\n  the sustaining effect, second by second. 'attempts' are wire calls to")
    print("  payments; 'good' is user requests meeting the SLI. Demand is a flat 70/s.")
    print("\n    t(s)      naive: attempts  good/s      budgeted: attempts  good/s")
    for sec in (12, 20, 30, 40, 44, 46, 50, 60, 75, 90):
        lo, hi = sec * 1000.0, (sec + 1) * 1000.0
        row = []
        for mode in ("naive", "budgeted"):
            r = out[mode]
            att = r.topo.edges["orders->payments"].attempt_log_count(lo, hi)
            good = sum(1 for x in r.reqs if lo <= x.t_start < hi and x.good)
            row += [att, good]
        mark = "   <- trigger removed at t=45" if sec == 46 else ""
        print(f"    {sec:>4}   {row[0]:>16}  {row[1]:>6}      "
              f"{row[2]:>16}  {row[3]:>6}{mark}")
    print("\n  Bronson, Aghayev, Charapko & Zhu, Metastable Failures in Distributed")
    print("  Systems, HotOS 2021: a TRIGGER pushes the system into a bad state, and a")
    print("  SUSTAINING EFFECT then holds it there after the trigger is gone.")
    return out


def _peak_amplification(edge: Edge, t0: float, t1: float) -> float:
    peak = 0.0
    for sec in range(int(t0 // 1000), int(t1 // 1000)):
        lo, hi = sec * 1000.0, (sec + 1) * 1000.0
        att = edge.attempt_log_count(lo, hi)
        peak = max(peak, att / RATE)
    return peak


# ══ 7 · SECTION 4 — ABLATION: WHAT EACH DEFENCE IS WORTH ═════════════════════

def ablation_policies(level: int) -> Dict[str, Policy]:
    """Five configurations against one fault. Level 0 is a system with no
    defences at all; each level adds exactly one thing."""
    inv = Policy(pool_size=6, timeout_ms=250.0, attempts=3, backoff_ms=25.0,
                 jitter=True, budget_ratio=0.10, breaker=True, required=False)
    if level == 0:      # nothing: no timeout, no retry, no breaker
        pay = Policy(pool_size=10)
        api = Policy(pool_size=48)
    elif level == 1:    # a timeout, and nothing else
        pay = Policy(pool_size=10, timeout_ms=300.0)
        api = Policy(pool_size=48, timeout_ms=800.0)
    elif level == 2:    # + naive retry
        pay = Policy(pool_size=10, timeout_ms=300.0, attempts=3, backoff_ms=25.0)
        api = Policy(pool_size=48, timeout_ms=800.0)
    elif level == 3:    # + full jitter and a retry budget
        pay = Policy(pool_size=10, timeout_ms=300.0, attempts=3, backoff_ms=25.0,
                     jitter=True, budget_ratio=0.10)
        api = Policy(pool_size=48, timeout_ms=800.0)
    else:               # + a circuit breaker and a bounded queue that sheds
        pay = Policy(pool_size=10, timeout_ms=300.0, attempts=3, backoff_ms=25.0,
                     jitter=True, budget_ratio=0.10, breaker=True, queue_limit=20)
        api = Policy(pool_size=48, timeout_ms=800.0, queue_limit=200)
    return {"api->orders": api, "orders->payments": pay, "orders->inventory": inv}


ABLATION_NAMES = ["no defence at all", "timeout only", "+ retry (naive)",
                  "+ jitter + budget", "+ breaker + shed"]


def section4() -> List[Tuple[str, float, float, float, Any]]:
    banner(4, "ABLATION: THE SAME FAULT AGAINST FIVE DEFENCE CONFIGURATIONS")
    inject = STORM_INJECT_S * 1000.0
    end = (STORM_INJECT_S + STORM_HOLD_S) * 1000.0
    seeds = (SEED, SEED + 101, SEED + 202)
    print("  identical fault: payments 6x slower for 30 s, then fully restored.")
    print(f"  Each row adds exactly one defence to the row above it. Averaged over "
          f"{len(seeds)} seeds,")
    print("  because a single run of a saturated system is one draw, not a result.")
    print("\n    configuration          good WHILE   good AFTER   post-trigger   error budget"
          "   recovery")
    print("                            degraded     restored    amplification     burned"
          "        time")
    rows = []
    for level, name in enumerate(ABLATION_NAMES):
        during = after = mins = amp = 0.0
        recs: List[Any] = []
        for sd in seeds:
            f = Fault(target="payments", kind="slow", factor=6.0, start=inject, end=end)
            r = run(f"ablate-{level}", ablation_policies(level), f,
                    duration_s=STORM_TOTAL_S, drain_s=30.0, seed=sd)
            _, d, _, _ = r.summary(inject, end)
            _, a, _, _ = r.summary(end, STORM_TOTAL_S * 1000.0)
            during += d / len(seeds)
            after += a / len(seeds)
            amp += _peak_amplification(r.topo.edges["orders->payments"], end,
                                       STORM_TOTAL_S * 1000.0) / len(seeds)
            mins += r.budget_burned(inject, STORM_TOTAL_S * 1000.0)[1] / len(seeds)
            recs.append(recovery_time(r, end))
        rec = None if any(x is None for x in recs) else sum(recs) / len(recs)
        rows.append((name, during, after, mins, rec, amp))
        print(f"    {name:<22} {during:>9.1%}    {after:>9.1%}    {amp:>9.2f}x"
              f"   {mins:>10.1f} min   {fmt_ms(rec):>8}")
    base = rows[0][3]
    print("\n    configuration          error budget vs NO DEFENCE AT ALL")
    for name, _, _, mins, _, _ in rows:
        delta = mins - base
        sign = "+" if delta > 0 else " "
        bar = "#" * min(46, int(abs(delta) / max(1e-9, base) * 46))
        print(f"    {name:<22} {sign}{delta:>8.1f} min   {bar}")
    worst = max(rows, key=lambda r: r[3])
    print(f"\n  worst configuration on this fault: {worst[0]!r} at "
          f"{worst[3]:.1f} min of budget —")
    print("  worse than having no defence at all, which is the result that matters.")
    f = Fault(target="payments", kind="slow", factor=6.0, start=inject, end=end)
    r = run("ablate-shed-count", ablation_policies(4), f,
            duration_s=STORM_TOTAL_S, drain_s=30.0)
    shed = sum(p.shed for p in _all_pools(r.topo))
    refused = sum(e.refused for e in r.topo.edges.values())
    print(f"\n  how the last row won: it declined {refused:,} calls at the circuit")
    print(f"  breaker and the retry budget, and shed {shed:,} at the bounded queue.")
    print("  The configuration that deliberately did the least work served the most")
    print("  users — and the queue limit never fired, because the breaker got there")
    print("  first. That is an ablation telling you which defence you actually own.")
    return rows


# ══ 8 · SECTION 5 — BLAST RADIUS ═════════════════════════════════════════════

def section5() -> None:
    banner(5, "BLAST RADIUS: THE SAME EXPERIMENT AT 1%, 5%, 25% AND 100%")
    inject = GREY_INJECT_S * 1000.0
    end = (GREY_INJECT_S + GREY_HOLD_S) * 1000.0
    print("  inventory 5x slower, injected into a percentage of user requests,")
    print("  with an abort that halts the fault after 3 consecutive SLO-breaching")
    print("  seconds. Cohorts are stable, so the injected slice is comparable.")
    blast_rows: List[Tuple[Any, ...]] = []
    print("\n    inject   injected cohort      control cohort     signal    whole service"
          "     bad     budget    aborted")
    print("             n    p50    p99      n    p50   p99     M-W z      good   p99"
          "     reqs    burned      at")
    for pct in (1, 5, 25, 100):
        f = Fault(target="inventory", kind="slow", factor=5.0, start=inject,
                  end=end, cohort_pct=pct)
        r = run(f"blast-{pct}", BASE_POLICIES, f, duration_s=55.0, abort_after=3)
        stop = min(end, r.aborted_at) if r.aborted_at else end
        window = r.slice(inject, stop)
        inj = [min(x.latency, 60000.0) for x in window if x.cohort < pct]
        ctl = [min(x.latency, 60000.0) for x in window if x.cohort >= pct]
        # The control cohort during the experiment is the honest baseline; at
        # 100% injection there is none, so fall back to the pre-fault window.
        ref = ctl if ctl else [min(x.latency, 60000.0)
                               for x in r.slice(inject - 5000.0, inject)]
        z = mann_whitney_z(ref, inj) if inj and ref else float("nan")
        n_all, good, _, p99all = r.summary(inject, 55000.0)
        bad, mins, _ = r.budget_burned(inject, 55000.0)
        cs = f"{len(ctl):>5} {pctl(ctl, 50):>6.0f} {pctl(ctl, 99):>5.0f}" if ctl \
            else f"{0:>5} {'-':>6} {'-':>5}"
        print(f"    {pct:>5}%  {len(inj):>4} {pctl(inj, 50):>6.0f} {pctl(inj, 99):>6.0f}"
              f"   {cs}   {z:>7.1f}   {good:>7.1%} {p99all:>5.0f}"
              f"   {bad:>6}  {mins:>6.1f} min   "
              f"{fmt_ms(None if r.aborted_at is None else r.aborted_at - inject)}")
        blast_rows.append((pct, pctl(inj, 50), pctl(inj, 99), z, good, bad, mins,
                           r.topo.services["orders"].pool.peak_queue,
                           r.topo.edges["orders->inventory"].pool.peak_queue))
    print("\n  and the EMERGENT effect — queueing, which is a property of AGGREGATE")
    print("  load and therefore not linear in the injected fraction:")
    print("    inject   peak queue on the inventory pool   peak queue on orders' workers")
    for pct, _, _, _, _, _, _, oq, iq in blast_rows:
        print(f"    {pct:>5}%   {iq:>31}   {oq:>29}")


# ══ 9 · SECTION 6 — CANARY ANALYSIS AS A STATISTICAL TEST ════════════════════

def binomial(rng: random.Random, n: int, p: float) -> int:
    """Exact Binomial(n, p) in O(n*p) using geometric gaps between successes."""
    if p <= 0.0:
        return 0
    k, i, lq = 0, -1, math.log1p(-p)
    while True:
        i += 1 + int(math.log(1.0 - rng.random()) / lq)
        if i >= n:
            return k
        k += 1


def two_prop_z(k1: int, n1: int, k2: int, n2: int) -> float:
    """One-sided two-proportion z statistic for 'canary is worse'."""
    p_pool = (k1 + k2) / (n1 + n2)
    if p_pool <= 0.0 or p_pool >= 1.0:
        return 0.0
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    return ((k2 / n2) - (k1 / n1)) / se if se > 0 else 0.0


def mann_whitney_z(a: Sequence[float], b: Sequence[float]) -> float:
    """Mann & Whitney (1947) rank-sum statistic, normal approximation with a tie
    correction. Tests whether b is stochastically larger than a."""
    n1, n2 = len(a), len(b)
    merged = sorted([(v, 0) for v in a] + [(v, 1) for v in b])
    ranks = [0.0] * len(merged)
    i = 0
    tie_term = 0.0
    while i < len(merged):
        j = i
        while j + 1 < len(merged) and merged[j + 1][0] == merged[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        t = j - i + 1
        tie_term += t ** 3 - t
        i = j + 1
    r2 = sum(rk for rk, (_, grp) in zip(ranks, merged) if grp == 1)
    u2 = r2 - n2 * (n2 + 1) / 2.0
    n = n1 + n2
    mu = n1 * n2 / 2.0
    var = n1 * n2 / 12.0 * ((n + 1) - tie_term / (n * (n - 1)))
    return (u2 - mu) / math.sqrt(var) if var > 0 else 0.0


def sprt(rng: random.Random, p0: float, p1: float, true_p: float,
         alpha: float, beta: float, n_max: int) -> Tuple[bool, int]:
    """Wald's sequential probability ratio test (Wald, Sequential Analysis,
    1947). Returns (rejected H0, samples consumed)."""
    log_a = math.log((1 - beta) / alpha)
    log_b = math.log(beta / (1 - alpha))
    l1, l0 = math.log(p1 / p0), math.log((1 - p1) / (1 - p0))
    llr = 0.0
    for i in range(1, n_max + 1):
        llr += l1 if rng.random() < true_p else l0
        if llr >= log_a:
            return True, i
        if llr <= log_b:
            return False, i
    return False, n_max


Z_95 = 1.6449          # one-sided alpha = 0.05


def section6() -> None:
    banner(6, "CANARY ANALYSIS IS A STATISTICAL TEST, NOT A THRESHOLD")
    rng = random.Random(SEED + 1)
    p0, p1 = 0.004, 0.014          # a 1.0-percentage-point error regression
    trials = 4000
    power_trials, mtrials = 3000, 800
    print(f"  baseline error rate {p0:.1%}; the bad canary is {p1:.1%} "
          f"(a 1.0-point regression).")
    print("  naive rule: fail the canary if its error rate exceeds the baseline's by 50%.")
    print("  proper rule: one-sided two-proportion z test at alpha = 0.05.")
    print(f"  {trials:,} trials per point; {power_trials:,} per power estimate; "
          f"{mtrials:,} per latency estimate.")
    print("\n    requests per arm      naive rule                 z test")
    print("                       false alarm   missed      false alarm   missed")
    for n in (200, 1000, 5000, 20000, 100000):
        nf = nm = zf = zm = 0
        for _ in range(trials):
            kb = binomial(rng, n, p0)
            kg = binomial(rng, n, p0)          # a good canary
            kbad = binomial(rng, n, p1)        # a bad canary
            if kg / n > 1.5 * (kb / n):
                nf += 1
            if not (kbad / n > 1.5 * (kb / n)):
                nm += 1
            if two_prop_z(kb, n, kg, n) > Z_95:
                zf += 1
            if not two_prop_z(kb, n, kbad, n) > Z_95:
                zm += 1
        print(f"    {n:>10,}         {nf / trials:>9.1%}   {nm / trials:>7.1%}"
              f"      {zf / trials:>9.1%}   {zm / trials:>7.1%}")

    print("\n  traffic to detect the 1.0-point regression with 80% power at alpha=0.05:")
    need = None
    for n in (200, 400, 600, 800, 1000, 1200, 1400, 1600, 2000, 3000, 5000):
        hits = 0
        for _ in range(power_trials):
            kb = binomial(rng, n, p0)
            kbad = binomial(rng, n, p1)
            if two_prop_z(kb, n, kbad, n) > Z_95:
                hits += 1
        power = hits / power_trials
        if power >= 0.80 and need is None:
            need = n
        print(f"    n = {n:>5,} per arm  ->  power {power:>6.1%}"
              + ("   <- 80% power" if need == n else ""))
    print(f"    smallest n on this grid reaching 80% power: {need:,} per arm.")
    print(f"    At {RATE:.0f} req/s split 50/50 that is "
          f"{2 * need / RATE / 60:.1f} minutes of canary exposure.")

    print("\n  sequential (Wald SPRT, alpha=beta=0.05) versus that fixed sample:")
    good_stops, bad_stops, fp, fn = [], [], 0, 0
    for _ in range(1500):
        rej, k = sprt(rng, p0, p1, p0, 0.05, 0.05, 60000)
        good_stops.append(k)
        fp += int(rej)
        rej, k = sprt(rng, p0, p1, p1, 0.05, 0.05, 60000)
        bad_stops.append(k)
        fn += int(not rej)
    print(f"    false alarm {fp / 1500:.1%}   missed {fn / 1500:.1%}")
    print(f"    samples to a verdict: median {pctl(bad_stops, 50):,.0f} on a bad "
          f"canary, {pctl(good_stops, 50):,.0f} on a good one (p90 "
          f"{pctl(good_stops, 90):,.0f})")

    print("\n  the same question on LATENCY, where the distribution has a long tail.")
    print("  A fixed threshold is a test with an UNCALIBRATED alpha, so compare it")
    print("  honestly: calibrate the threshold to a 5% false-alarm rate at each")
    print("  traffic volume, then compare what each one misses.")
    print("\n    requests   calibrated 'mean is    naive fixed    calibrated    "
          "Mann-Whitney")
    print("    per arm    worse by X%' rule      +5% rule:      mean rule:    "
          "U at a=0.05:")
    print("               that gives 5% alarms   false alarm    missed        missed")
    mrng = random.Random(SEED + 2)
    for m in (200, 800, 3200):
        null_ratio, null_z, alt_ratio, alt_z = [], [], [], []
        for _ in range(mtrials):
            base = [math.exp(mrng.gauss(math.log(60.0), 0.55)) for _ in range(m)]
            good = [math.exp(mrng.gauss(math.log(60.0), 0.55)) for _ in range(m)]
            bad = [math.exp(mrng.gauss(math.log(66.0), 0.55)) for _ in range(m)]
            mb = sum(base) / m
            null_ratio.append(sum(good) / m / mb)
            alt_ratio.append(sum(bad) / m / mb)
            null_z.append(mann_whitney_z(base, good))
            alt_z.append(mann_whitney_z(base, bad))
        cal = pctl(null_ratio, 95)
        fixed_fp = sum(1 for x in null_ratio if x > 1.05) / mtrials
        cal_miss = sum(1 for x in alt_ratio if x <= cal) / mtrials
        mw_miss = sum(1 for z in alt_z if z <= Z_95) / mtrials
        mw_fp = sum(1 for z in null_z if z > Z_95) / mtrials
        print(f"    {m:>7,}          +{(cal - 1) * 100:>5.1f}%           "
              f"{fixed_fp:>7.1%}       {cal_miss:>7.1%}       {mw_miss:>7.1%}"
              f"   (alarms {mw_fp:.1%})")
    print("\n  The calibrated threshold MOVES with traffic volume. A number hard-coded")
    print("  in a deploy pipeline is therefore right at one hour of the day.")


def main() -> None:
    print("CHAOS ENGINEERING: THE DISCIPLINE, MEASURED")
    print(f"seed={SEED} · discrete-event simulation · stdlib only · no network")
    section1()
    section2()
    section3()
    section4()
    section5()
    section6()
    print("\ndone.")


if __name__ == "__main__":
    main()
