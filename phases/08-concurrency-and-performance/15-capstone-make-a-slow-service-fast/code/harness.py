"""
The measuring instruments: an open-loop load generator and a sampling profiler.

Open-loop means arrivals are scheduled on a clock, not on the previous response,
and latency is measured from the INTENDED arrival time — the coordinated-omission
correction from Lesson 14.  Companion to docs/en.md (Phase 8, Lesson 15).

Also here: a stdlib sampling profiler built on sys._current_frames(), which
separates wall-clock time (where requests wait) from on-CPU time (where the
processor works) — the distinction Lesson 13 exists to make.
"""

from __future__ import annotations

import queue
import sys
import threading
import time
from dataclasses import dataclass

from slow_service import (
    N_ITEMS,
    SLO_MS,
    WATCHED,
    Request,
    Service,
    Stage,
    perf,
)


# --------------------------------------------------------------------------- #
# Percentiles: nearest-rank, no interpolation. Small samples, honest answers.
# --------------------------------------------------------------------------- #
def pctl(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round(q * len(s) + 0.5)) - 1))
    return s[k]


@dataclass
class Result:
    label: str
    offered: float = 0.0
    sent: int = 0
    ok: int = 0
    shed: int = 0
    expired: int = 0
    aborted: int = 0
    wall: float = 0.0
    throughput: float = 0.0     # completed responses per second
    goodput: float = 0.0        # completed AND inside the SLO, per second
    p50: float = 0.0
    p99: float = 0.0
    naive_p99: float = 0.0      # what a timer started after the lock would report
    err_pct: float = 0.0
    lockwait_p99: float = 0.0
    poolwait_p99: float = 0.0
    up_peak: int = 0
    inflight_peak: int = 0
    calls_seen: int = 0
    calls_real: int = 0
    index_rows: int = 0
    correct: bool = True
    capacity: float = 0.0
    lat: list = None            # every latency, kept so we can draw the shape
    series: list = None         # (seconds since start, latency ms) per response

    def correctness(self) -> str:
        return "ok" if self.correct else "WRONG"


LAT_EDGES = [10, 15, 25, 40, 60, 100, 160, 250, 400, 630,
             1000, 1600, 2500, 4000, 6300, 10000]


def histogram(xs: list[float], edges: list[float] = None) -> list[int]:
    """Counts per bucket, last bucket is everything above the top edge."""
    edges = edges or LAT_EDGES
    out = [0] * (len(edges) + 1)
    for x in xs:
        i = 0
        while i < len(edges) and x > edges[i]:
            i += 1
        out[i] += 1
    return out


def goodput_series(res: Result, slo_ms: float, bin_s: float = 0.2) -> tuple[list, list]:
    """(goodput per second, throughput per second) in bin_s windows."""
    if not res.series:
        return [], []
    n = int(max(t for t, _ in res.series) / bin_s) + 1
    good, tot = [0] * n, [0] * n
    for t, lat in res.series:
        i = min(n - 1, int(t / bin_s))
        tot[i] += 1
        if lat <= slo_ms:
            good[i] += 1
    return [round(g / bin_s) for g in good], [round(t / bin_s) for t in tot]


def _finish(svc: Service, res: Result, t0: float, sent: int) -> Result:
    lat = [s.latency_ms for s in svc.samples]
    res.lat = lat
    res.series = [(s.done_at - t0, s.latency_ms) for s in svc.samples]
    svc_ms = [s.service_ms for s in svc.samples]
    res.sent = sent
    res.ok = len(lat)
    res.shed = svc.shed
    res.expired = svc.expired
    res.aborted = svc.aborted
    res.wall = perf() - t0
    res.throughput = res.ok / res.wall if res.wall else 0.0
    inside = sum(1 for x in lat if x <= SLO_MS)
    res.goodput = inside / res.wall if res.wall else 0.0
    res.p50 = pctl(lat, 0.50)
    res.p99 = pctl(lat, 0.99)
    res.naive_p99 = pctl(svc_ms, 0.99)
    bad = res.shed + res.expired + res.aborted
    res.err_pct = 100.0 * bad / sent if sent else 0.0
    res.lockwait_p99 = pctl(svc.lock_waits, 0.99) * 1000.0 if svc.lock_waits else 0.0
    res.poolwait_p99 = (
        pctl(svc.pool.waits, 0.99) * 1000.0 if svc.pool and svc.pool.waits else 0.0
    )
    res.up_peak = svc.up.peak
    res.inflight_peak = svc.inflight_peak
    res.calls_seen = svc.stats.calls
    res.calls_real = svc.stats.true_calls
    res.index_rows = svc.index.total()
    res.correct = res.calls_seen == res.calls_real
    return res


def make_requests(n: int) -> list[Request]:
    ids = tuple(range(1, N_ITEMS + 1))
    return [Request(i=i, key=i % 64, ids=ids) for i in range(n)]


# --------------------------------------------------------------------------- #
# Open loop: arrivals on a clock, latency from the intended start.
# --------------------------------------------------------------------------- #
def run_open_loop(
    stage: Stage,
    rate: float,
    seconds: float,
    label: str | None = None,
    budget: float = 12.0,
    profiler: "SamplingProfiler | None" = None,
) -> Result:
    svc = Service(stage)
    if profiler is not None:
        svc.count_calls = True
    svc.start()
    n = int(rate * seconds)
    reqs = make_requests(n)
    res = Result(label=label or stage.name, offered=rate)

    if profiler is not None:
        profiler.start()
    t0 = perf()
    for i, r in enumerate(reqs):
        r.intended = t0 + i / rate          # the schedule, fixed before we start
    # One dispatcher thread cannot reliably emit more than a few hundred
    # arrivals a second; past that the generator becomes the bottleneck and
    # silently understates the load. Split the schedule across several.
    nd = max(1, min(8, int(rate // 250)))
    threads = [
        threading.Thread(target=_dispatch, args=(svc, stage, reqs, lo, nd), daemon=True)
        for lo in range(nd)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    svc.drain(expected=n - svc.shed, budget=budget)
    if profiler is not None:
        profiler.stop()
        profiler.call_counts = dict(svc.call_counts)
        profiler.requests = len(svc.samples)
    out = _finish(svc, res, t0, n)
    svc.stop()
    return out


def _dispatch(svc: Service, stage: Stage, reqs, lo: int, step: int) -> None:
    for i in range(lo, len(reqs), step):
        r = reqs[i]
        gap = r.intended - perf()
        if gap > 0:
            time.sleep(gap)
        if stage.bounded:
            try:
                svc.q.put_nowait(r)
            except queue.Full:
                with svc._rl:
                    svc.shed += 1      # load shed at the door: an instant 503
        else:
            svc.q.put(r)               # unbounded queue: everything is accepted


# --------------------------------------------------------------------------- #
# Closed loop: the WRONG way to measure, kept so we can show what it hides.
# --------------------------------------------------------------------------- #
def run_closed_loop(
    stage: Stage,
    clients: int,
    requests: int,
    profiler: "SamplingProfiler | None" = None,
) -> tuple[float, float, float]:
    """Returns (p50_ms, p99_ms, throughput). Each client waits for its own reply."""
    svc = Service(stage)
    if profiler is not None:
        svc.count_calls = True
    svc.start()
    lat: list[float] = []
    lock = threading.Lock()
    done = threading.Semaphore(0)
    ids = tuple(range(1, N_ITEMS + 1))

    def client(cid: int) -> None:
        WATCHED.add(threading.get_ident())
        for k in range(requests // clients):
            r = Request(i=k, key=k % 64, ids=ids, intended=perf())
            t = perf()
            svc.handle(r)
            with lock:
                lat.append((perf() - t) * 1000.0)
        done.release()

    if profiler is not None:
        profiler.start()
    t0 = perf()
    for c in range(clients):
        threading.Thread(target=client, args=(c,), daemon=True).start()
    for _ in range(clients):
        done.acquire()
    wall = perf() - t0
    if profiler is not None:
        profiler.stop()
        profiler.call_counts = dict(svc.call_counts)
        profiler.requests = len(lat)
    svc.stop()
    return pctl(lat, 0.50), pctl(lat, 0.99), len(lat) / wall


# --------------------------------------------------------------------------- #
# Capacity: saturate it and see what falls out the other end.
# --------------------------------------------------------------------------- #
@dataclass
class Probe:
    """What a saturating run tells you. Latency here is service time, not
    end-to-end: under saturation everything queues, so only the server's own
    view of a request is meaningful."""

    rps: float = 0.0
    p99_service: float = 0.0
    up_peak: int = 0
    inflight_peak: int = 0
    lockwait_p99: float = 0.0
    poolwait_p99: float = 0.0
    runs: list = None


def capacity_probe(stage: Stage, n: int = 240, budget: float = 9.0,
                   min_seconds: float = 1.0) -> Probe:
    """Saturate the service and measure the drain rate.

    A probe that finishes in a fraction of a second measures the opening burst,
    not the steady state: the first `workers` requests all start at once, so a
    short probe reports a number the service could never sustain. If the run
    came in under min_seconds, scale n up and do it again.
    """
    for _ in range(3):
        pr, wall = _probe_once(stage, n, budget)
        if wall >= min_seconds or n >= 5000:
            return pr
        n = min(5000, int(n * max(2.0, min_seconds / max(wall, 1e-3))))
    return pr


def _probe_once(stage: Stage, n: int, budget: float) -> tuple[Probe, float]:
    svc = Service(stage)
    svc.start()
    reqs = make_requests(n)
    t0 = perf()
    for r in reqs:
        r.intended = t0
        svc.q.put(r)
    svc.drain(expected=n, budget=budget)
    wall = perf() - t0
    ok = len(svc.samples)
    pr = Probe(
        rps=ok / wall if wall else 0.0,
        p99_service=pctl([s.service_ms for s in svc.samples], 0.99),
        up_peak=svc.up.peak,
        inflight_peak=svc.inflight_peak,
        lockwait_p99=pctl(svc.lock_waits, 0.99) * 1000.0 if svc.lock_waits else 0.0,
        poolwait_p99=(pctl(svc.pool.waits, 0.99) * 1000.0
                      if svc.pool and svc.pool.waits else 0.0),
    )
    svc.stop()
    return pr, wall


def measure_capacity(stage: Stage, n, tries: int = 1, budget: float = 12.0) -> Probe:
    """Report the MEDIAN of a few probes, not the best one.

    A single saturating probe on a shared machine has a spread of tens of percent,
    and the maximum is the most optimistic thing you can report. The median of
    three is the smallest honest summary; the individual runs are kept in .runs
    so the spread can be printed next to the headline."""
    runs = sorted((capacity_probe(stage, n=int(n), budget=budget) for _ in range(tries)),
                  key=lambda p: p.rps)
    med = runs[len(runs) // 2]
    return Probe(
        rps=med.rps,
        p99_service=med.p99_service,
        up_peak=max(p.up_peak for p in runs),
        inflight_peak=max(p.inflight_peak for p in runs),
        lockwait_p99=med.lockwait_p99,
        poolwait_p99=med.poolwait_p99,
        runs=[p.rps for p in runs],
    )


# --------------------------------------------------------------------------- #
# The sampling profiler.  Every INTERVAL seconds, look at what every request
# thread is doing.  A thread blocked in time.sleep() still burns wall-clock time
# and no CPU — that gap is the entire point.
# --------------------------------------------------------------------------- #
LABELS = {
    "connect_upstream": "connect  (TCP+TLS handshake)",
    "fetch_profile": "GET /profile",
    "fetch_settings": "GET /settings",
    "fetch_list": "GET /items",
    "fetch_item": "GET /item/{id}",
    "fetch_items_batch": "POST /items:batch",
    "score_items": "score_items()  [CPU]",
    "_widen": "stats.record()  [race window]",
    "_acquire_global": "WAIT  global lock",
    "lease": "WAIT  connection pool",
    "_queue_get": "IDLE  waiting for work",
}
BLOCKED = {"_sleep_io", "_acquire_global", "_queue_get", "_widen", "lease"}


class SamplingProfiler(threading.Thread):
    """A profiler written in Python is itself a thread competing for the GIL.

    While a CPU-bound function runs, the sampler cannot be scheduled until the
    interpreter's switch interval expires (5 ms by default) — so it systematically
    UNDER-reports on-CPU time and over-reports blocked time. Shortening the switch
    interval for the duration of the profile removes most of that bias: measured
    here, score_items() went from 0.3% to 2.8% of the wall clock, against a
    directly-timed truth of ~2.9%.
    """

    def __init__(self, interval: float = 0.003) -> None:
        super().__init__(daemon=True, name="profiler")
        self.interval = interval
        self._switch = sys.getswitchinterval()
        self._done = threading.Event()
        self.wall: dict[str, int] = {}
        self.cpu: dict[str, int] = {}
        self.samples = 0
        self.call_counts: dict[str, int] = {}
        self.requests = 0

    def start(self) -> None:
        sys.setswitchinterval(0.0005)
        super().start()

    def run(self) -> None:
        while not self._done.is_set():
            frames = sys._current_frames()
            for tid, frame in frames.items():
                if tid not in WATCHED:
                    continue
                label, on_cpu = self._classify(frame)
                self.wall[label] = self.wall.get(label, 0) + 1
                if on_cpu:
                    self.cpu[label] = self.cpu.get(label, 0) + 1
                self.samples += 1
            self._done.wait(self.interval)

    @staticmethod
    def _classify(frame) -> tuple[str, bool]:
        on_cpu = frame.f_code.co_name not in BLOCKED
        f = frame
        while f is not None:
            name = f.f_code.co_name
            if name in LABELS:
                return LABELS[name], on_cpu
            f = f.f_back
        return "other Python", on_cpu

    def stop(self) -> None:
        self._done.set()
        self.join(timeout=2.0)
        sys.setswitchinterval(self._switch)

    def table(self) -> list[tuple[str, float, float, int]]:
        """[(label, wall %, cpu %, calls/request)], busiest first, idle excluded."""
        busy_wall = {k: v for k, v in self.wall.items() if not k.startswith("IDLE")}
        tw = sum(busy_wall.values()) or 1
        tc = sum(v for k, v in self.cpu.items() if not k.startswith("IDLE")) or 1
        rows = []
        for label, w in busy_wall.items():
            c = self.cpu.get(label, 0)
            key = label.split("  ")[0].strip()
            calls = self.call_counts.get(key, 0)
            per_req = calls / self.requests if self.requests else 0.0
            rows.append((label, 100.0 * w / tw, 100.0 * c / tc, per_req))
        rows.sort(key=lambda r: -r[1])
        return rows
