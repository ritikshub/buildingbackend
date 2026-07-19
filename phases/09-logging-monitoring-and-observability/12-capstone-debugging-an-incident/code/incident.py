#!/usr/bin/env python3
"""
incident.py -- a fully instrumented four-service checkout path, deliberately
broken, plus the tooling you need to find the fault from its telemetry alone.

Companion to docs/en.md (Phase 10, Lesson 12 -- the phase capstone).
  PART 1  THE SYSTEM.  gateway -> orders -> payments -> bank-api over a shared
          postgres, on a simulated clock, with a real FIFO connection-pool queue
          in payments, retries in orders, and metric/log/trace stores.
  PART 2  THE TOOLING. promql_rate, promql_error_ratio, histogram_quantile,
          burn_rate, a LogQL-shaped log query, trace search, exemplar lookup and
          a waterfall renderer.
  PART 3  THE INVESTIGATION. Eight steps -- detect, triage, localize, explain,
          correlate, confirm, mitigate, learn -- that only ever QUERY the stores.

Metrics follow the Prometheus/OpenMetrics model (cumulative counters, cumulative
`le` buckets, exemplars); the alert follows the multiwindow burn-rate method of
the Google SRE Workbook, chapter 5. Deterministic: seeded RNG, simulated clock.

Runs on the Python standard library only:  python incident.py
"""

from __future__ import annotations

import heapq
import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Optional

# ─── Constants: the world, and the shape of the incident ─────────────────────

SEED = 20260718
BASE = 3 * 3600                    # 03:00:00, in simulated seconds since midnight
T_START = BASE + 5 * 60            # 03:05:00  observation window opens
T_DEPLOY = BASE + 7 * 60           # 03:07:00  payments v2.4.1 rolls out
T_RAMP = BASE + 9 * 60             # 03:09:00  traffic begins to climb
T_PEAK = BASE + 10 * 60            # 03:10:00  traffic plateaus
T_END = BASE + 16 * 60             # 03:16:00  observation window closes
T_ROLLBACK = BASE + 16 * 60        # 03:16:00  the rollback is triggered
T_RECOVERED = BASE + 19 * 60 + 30  # 03:19:30  the SLI is healthy again

BASE_RPS, PEAK_RPS = 40.0, 100.0
POOL_SIZE = 4                      # connections in the payments -> postgres pool
DB_HOLD_S = 0.010                  # the transactional write, always inside the pool
FRAUD_LOOKUP_S = 0.030             # what v2.4.1 added -- also inside the pool
BANK_AUTH_S = 0.020                # the card authorization, outside the pool
ORDERS_TIMEOUT_S = 3.0             # orders' client deadline on the payments call
MAX_ATTEMPTS = 2                   # orders: one original attempt + one retry
POOL_TIMEOUT_S = 2.0               # payments gives up waiting for a connection
SLO_AVAILABILITY = 0.999           # 99.9% of checkouts succeed, over 30 days
FAST_BURN_THRESHOLD = 14.4         # SRE Workbook: 14.4x burn = 2% of budget in 1h
SCRAPE_INTERVAL = 15               # seconds between metric snapshots
TRACE_SAMPLE_RATE = 10             # head sampling: keep 1 trace in 10
BUCKETS = (.005, .01, .025, .05, .1, .25, .5, .75, 1., 1.5, 2., 3., 5., 10.)

DEPLOYS = [(T_DEPLOY, "payments", "v2.4.1", "add fraud-score lookup to charge path")]


def clock(t: float) -> str:
    """A simulated wall clock: 11227.482 -> '03:07:07.482'."""
    total = int(t)
    return "%02d:%02d:%02d.%03d" % (total // 3600 % 24, total // 60 % 60,
                                    total % 60, int(round((t % 1) * 1000)) % 1000)


def lognorm(rng: random.Random, median: float, sigma: float) -> float:
    return rng.lognormvariate(math.log(median), sigma)


# ─── Part 1 · Telemetry stores: the three pillars, in memory ─────────────────

Labels = tuple[tuple[str, str], ...]


_LK_CACHE: dict[tuple, Labels] = {}


def lk(**kw: str) -> Labels:
    """A series identity is name + a SORTED label set, so {a,b} == {b,a} (Lesson 5).

    Memoized because the simulation asks for the same few label sets millions of
    times -- exactly what a real client library does with its child-series cache.
    """
    key = tuple(kw.items())
    hit = _LK_CACHE.get(key)
    if hit is None:
        hit = _LK_CACHE[key] = tuple(sorted(kw.items()))
    return hit


def _fmt_le(v: float) -> str:
    return "+Inf" if math.isinf(v) else "%g" % v


class MetricStore:
    """Cumulative counters, gauges and `le` histograms, snapshotted on a scrape."""

    def __init__(self) -> None:
        self.counters: dict[tuple[str, Labels], float] = {}
        self.gauges: dict[tuple[str, Labels], float] = {}
        self.hists: dict[tuple[str, Labels], list[float]] = {}
        self.series: dict[tuple[str, Labels], list[tuple[float, float]]] = {}
        self.exemplars: dict[tuple[str, Labels, float], list[tuple[float, str, float]]] = {}

    def inc(self, name: str, labels: Labels, amount: float = 1.0) -> None:
        self.counters[(name, labels)] = self.counters.get((name, labels), 0.0) + amount

    def set_gauge(self, name: str, labels: Labels, value: float) -> None:
        self.gauges[(name, labels)] = value

    def observe(self, name: str, labels: Labels, value: float,
                ts: float = 0.0, trace_id: Optional[str] = None) -> None:
        h = self.hists.setdefault((name, labels), [0.0] * (len(BUCKETS) + 2))
        for i, upper in enumerate(BUCKETS):        # cumulative: one observation
            if value <= upper:                     # lands in every bucket le >= value
                h[i] += 1
        h[-2] += value                             # _sum
        h[-1] += 1                                 # _count
        if trace_id is not None:                   # OpenMetrics exemplar: pin a trace
            le = next((b for b in BUCKETS if value <= b), math.inf)
            self.exemplars.setdefault((name, labels, le), []).append((ts, trace_id, value))

    def scrape(self, ts: float) -> None:
        """One snapshot of every series -- exactly what a Prometheus pull stores."""
        for (name, labels), v in self.counters.items():
            self.series.setdefault((name, labels), []).append((ts, v))
        for (name, labels), v in self.gauges.items():
            self.series.setdefault((name, labels), []).append((ts, v))
        for (name, labels), h in self.hists.items():
            for i, upper in enumerate(BUCKETS):
                key = (name + "_bucket", labels + (("le", _fmt_le(upper)),))
                self.series.setdefault(key, []).append((ts, h[i]))
            inf = (name + "_bucket", labels + (("le", "+Inf"),))
            self.series.setdefault(inf, []).append((ts, h[-1]))
            self.series.setdefault((name + "_sum", labels), []).append((ts, h[-2]))
            self.series.setdefault((name + "_count", labels), []).append((ts, h[-1]))

    def select(self, name: str, **matchers: str) -> list[tuple[str, Labels]]:
        out = []
        for key in self.series:
            if key[0] != name:
                continue
            d = dict(key[1])
            if all(d.get(k) == v for k, v in matchers.items()):
                out.append(key)
        return sorted(out)


@dataclass
class LogRecord:
    ts: float
    service: str
    level: str
    event: str
    trace_id: str
    fields: dict[str, Any]


class LogStore:
    """A log backend: labels are indexed, the JSON body is filtered on read."""

    def __init__(self) -> None:
        self.records: list[LogRecord] = []

    def emit(self, ts: float, service: str, level: str, event: str,
             trace_id: str, **fields: Any) -> None:
        self.records.append(LogRecord(ts, service, level, event, trace_id, fields))

    def query(self, service: Optional[str] = None, level: Optional[str] = None,
              event: Optional[str] = None, trace_id: Optional[str] = None,
              start: float = -1e18, end: float = 1e18) -> list[LogRecord]:
        return [r for r in self.records
                if start <= r.ts <= end
                and (service is None or r.service == service)
                and (level is None or r.level == level)
                and (event is None or r.event == event)
                and (trace_id is None or r.trace_id == trace_id)]


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: Optional[str]
    service: str
    name: str
    kind: str                       # server | client | internal
    start: float
    duration: float
    status: str
    depth: int
    attrs: dict[str, Any] = field(default_factory=dict)


class TraceStore:
    """Traces, head-sampled at 1-in-N -- the same trade-off Lesson 7 made."""

    def __init__(self) -> None:
        self.traces: dict[str, list[Span]] = {}

    def add(self, trace_id: str, spans: list[Span]) -> None:
        self.traces[trace_id] = sorted(spans, key=lambda s: (s.start, s.depth))

    def root(self, trace_id: str) -> Span:
        return self.traces[trace_id][0]

    def find_traces(self, min_duration: float = 0.0, status: Optional[str] = None,
                    start: float = -1e18, end: float = 1e18,
                    limit: int = 5) -> list[str]:
        hits = []
        for tid, spans in self.traces.items():
            r = spans[0]
            if r.duration >= min_duration and start <= r.start <= end \
                    and (status is None or r.status == status):
                hits.append((r.duration, tid))
        hits.sort(reverse=True)
        return [tid for _, tid in hits[:limit]]


# ─── Part 1 · The simulated system ───────────────────────────────────────────

class Pool:
    """A fixed-size FIFO connection pool. Every acquire reports the wait it paid."""

    def __init__(self, size: int) -> None:
        self.size = size
        self.free_at = [0.0] * size
        heapq.heapify(self.free_at)

    def acquire(self, t: float, hold: float) -> Optional[tuple[float, float]]:
        """Return (wait, acquired_at), or None if the caller gave up waiting."""
        earliest = heapq.heappop(self.free_at)
        acquired_at = max(t, earliest)
        wait = acquired_at - t
        if wait > POOL_TIMEOUT_S:
            heapq.heappush(self.free_at, earliest)      # untouched: nobody was served
            return None
        heapq.heappush(self.free_at, acquired_at + hold)
        return wait, acquired_at


@dataclass
class Req:
    tid: str
    sampled: bool
    t0: float
    gw: float
    ovh: float
    odb: float
    issued: float
    pay_over: float
    spans: list[Span] = field(default_factory=list)


def rps_at(t: float, peak: float) -> float:
    if t < T_RAMP:
        return BASE_RPS
    if t < T_PEAK:
        return BASE_RPS + (peak - BASE_RPS) * (t - T_RAMP) / (T_PEAK - T_RAMP)
    return peak


def add_interval(acc: dict[int, float], start: float, end: float) -> None:
    s = int(start)
    while s < end:
        acc[s] += min(end, s + 1) - max(start, s)
        s += 1


@dataclass
class Sim:
    metrics: MetricStore
    logs: LogStore
    traces: TraceStore
    requests: int
    attempts: int
    retries: int


def simulate(deployed: bool = True, pool_size: int = POOL_SIZE, peak: float = PEAK_RPS,
             record: bool = True, attempts: int = MAX_ATTEMPTS) -> Sim:
    """Run the whole timeline once and return everything it emitted."""
    rng = random.Random(SEED)
    metrics, logs, traces = MetricStore(), LogStore(), TraceStore()
    pool = Pool(pool_size)
    events: list[tuple[float, str, str, Labels, float, Optional[str]]] = []
    inuse: dict[int, float] = defaultdict(float)
    waiters: dict[int, float] = defaultdict(float)
    done: dict[str, dict[int, int]] = {s: defaultdict(int)
                                       for s in ("gateway", "orders", "payments")}
    sid = lambda: "%016x" % rng.getrandbits(64)

    def count(ts: float, service: str, route: str, status: str) -> None:
        events.append((ts, "c", "http_requests_total",
                       lk(service=service, route=route, status=status), 1.0, None))

    def timing(ts: float, name: str, labels: Labels, v: float,
               tid: Optional[str] = None) -> None:
        events.append((ts, "h", name, labels, v, tid))

    # --- generate the arrival stream (exponential gaps = a bursty Poisson process)
    heap: list[tuple[float, int, Req, int]] = []
    seq, t = 0, float(T_START)
    while True:
        t += rng.expovariate(rps_at(t, peak))
        if t >= T_END:
            break
        tid = "%032x" % rng.getrandbits(128)
        req = Req(tid=tid, sampled=(int(tid[:8], 16) % TRACE_SAMPLE_RATE == 0), t0=t,
                  gw=lognorm(rng, 0.0010, 0.30), ovh=lognorm(rng, 0.0015, 0.30),
                  odb=lognorm(rng, 0.0040, 0.35), issued=0.0,
                  pay_over=lognorm(rng, 0.0015, 0.30))
        req.issued = t + req.gw + req.ovh + req.odb
        seq += 1
        heapq.heappush(heap, (req.issued + req.pay_over, seq, req, 1))

    n_requests, n_attempts, n_retries = seq, 0, 0

    # --- drain the queue of payment attempts, in pool-arrival order
    while heap:
        pool_arrival, _, r, attempt = heapq.heappop(heap)
        n_attempts += 1
        live = deployed and pool_arrival >= T_DEPLOY
        db_ms = lognorm(rng, DB_HOLD_S, 0.25)
        fraud = lognorm(rng, FRAUD_LOOKUP_S, 0.30) if live else 0.0
        hold = db_ms + fraud
        bank = lognorm(rng, BANK_AUTH_S, 0.30)
        got = pool.acquire(pool_arrival, hold)
        pay_start = r.issued

        if got is None:                                    # pool acquire timed out
            wait, acquired = POOL_TIMEOUT_S, pool_arrival + POOL_TIMEOUT_S
            pay_dur = r.pay_over + POOL_TIMEOUT_S
            pay_status, hold, bank = "500", 0.0, 0.0
        else:
            wait, acquired = got
            pay_dur = r.pay_over + wait + hold + bank
            pay_status = "200"
        pay_end = pay_start + pay_dur

        add_interval(waiters, pool_arrival, acquired)
        if got is not None:
            add_interval(inuse, acquired, acquired + hold)
        done["payments"][int(pay_end)] += 1

        count(pay_end, "payments", "/charge", pay_status)
        timing(pay_end, "http_request_duration_seconds",
               lk(service="payments", route="/charge"), pay_dur)
        timing(acquired, "pool_wait_seconds", lk(service="payments", pool="postgres"), wait)
        if got is not None:
            count(acquired + db_ms + fraud, "bank-api", "/authorize", "200")
            timing(acquired + db_ms + fraud + bank, "http_request_duration_seconds",
                   lk(service="bank-api", route="/authorize"), bank)
            if live:
                count(acquired + db_ms + fraud, "bank-api", "/fraud-score", "200")
                timing(acquired + db_ms + fraud, "http_request_duration_seconds",
                       lk(service="bank-api", route="/fraud-score"), fraud)

        if record and wait > 0.25:
            logs.emit(acquired, "payments", "WARN", "pool_acquire_slow", r.tid,
                      pool="postgres", wait_ms=round(wait * 1000, 1),
                      pool_size=pool_size, attempt=attempt)
        if record and r.sampled:
            ps = sid()
            r.spans.append(Span(r.tid, ps, None, "payments", "POST /charge", "server",
                                pay_start, pay_dur, "ok" if got else "error", 3,
                                {"attempt": attempt}))
            r.spans.append(Span(r.tid, sid(), ps, "payments", "pool.acquire", "internal",
                                pool_arrival, wait, "ok", 4,
                                {"pool": "postgres", "size": pool_size}))
            if got is not None:
                r.spans.append(Span(r.tid, sid(), ps, "postgres", "db.query charge_txn",
                                    "client", acquired, db_ms, "ok", 4, {}))
                if live:
                    r.spans.append(Span(r.tid, sid(), ps, "bank-api", "GET /fraud-score",
                                        "client", acquired + db_ms, fraud, "ok", 4, {}))
                r.spans.append(Span(r.tid, sid(), ps, "bank-api", "POST /authorize",
                                    "client", acquired + hold, bank, "ok", 4, {}))
            r.spans.append(Span(r.tid, sid(), None, "orders", "POST payments/charge",
                                "client", pay_start, min(pay_dur, ORDERS_TIMEOUT_S),
                                "ok" if pay_dur <= ORDERS_TIMEOUT_S else "timeout", 2,
                                {"attempt": attempt}))

        # --- orders decides: accept, retry, or give up
        timed_out = pay_dur > ORDERS_TIMEOUT_S
        if timed_out or pay_status != "200":
            gave_up = pay_start + min(pay_dur, ORDERS_TIMEOUT_S)
            reason = "deadline_exceeded" if timed_out else "upstream_5xx"
            if record:
                logs.emit(gave_up, "orders", "WARN", "payment_call_failed", r.tid,
                          upstream="payments", reason=reason, upstream_status=pay_status,
                          attempt=attempt, will_retry=attempt < attempts)
            if attempt < attempts:
                n_retries += 1
                seq += 1
                r.issued = gave_up + 0.050 + rng.random() * 0.050   # jittered backoff
                r.pay_over = lognorm(rng, 0.0015, 0.30)
                heapq.heappush(heap, (r.issued + r.pay_over, seq, r, attempt + 1))
                continue
            end, status = gave_up, "504" if timed_out else "502"
        else:
            end, status = pay_end, "200"

        # --- the request finishes; gateway and orders record it
        gw_end = end + r.gw
        total = gw_end - r.t0
        done["gateway"][int(gw_end)] += 1
        done["orders"][int(end)] += 1
        count(gw_end, "gateway", "/checkout", status)
        count(end, "orders", "/orders", status)
        timing(gw_end, "http_request_duration_seconds", lk(service="gateway", route="/checkout"),
               total, r.tid if r.sampled else None)
        timing(end, "http_request_duration_seconds", lk(service="orders", route="/orders"),
               end - (r.t0 + r.gw))
        if record and status != "200":
            logs.emit(gw_end, "gateway", "ERROR", "checkout_failed", r.tid,
                      route="/checkout", status=int(status),
                      duration_ms=round(total * 1000, 1))
        if record and r.sampled:
            gs, os_ = sid(), sid()
            r.spans.append(Span(r.tid, gs, None, "gateway", "POST /checkout", "server",
                                r.t0, total, "ok" if status == "200" else "error", 0,
                                {"status": status}))
            r.spans.append(Span(r.tid, os_, gs, "orders", "POST /orders", "server",
                                r.t0 + r.gw, end - (r.t0 + r.gw),
                                "ok" if status == "200" else "error", 1, {}))
            r.spans.append(Span(r.tid, sid(), os_, "postgres", "db.query order_insert",
                                "client", r.t0 + r.gw + r.ovh, r.odb, "ok", 2, {}))
            traces.add(r.tid, r.spans)
            logs.emit(pay_end, "payments", "INFO", "charge_completed", r.tid,
                      pool_wait_ms=round(wait * 1000, 1), db_ms=round(db_ms * 1000, 1),
                      fraud_lookup_ms=round(fraud * 1000, 1), bank_ms=round(bank * 1000, 1),
                      duration_ms=round(pay_dur * 1000, 1))
            logs.emit(end, "orders", "INFO" if status == "200" else "ERROR",
                      "order_completed" if status == "200" else "order_failed", r.tid,
                      status=int(status), attempts=attempt,
                      duration_ms=round((end - (r.t0 + r.gw)) * 1000, 1))
            logs.emit(gw_end, "gateway", "INFO", "http_request", r.tid, route="/checkout",
                      method="POST", status=int(status), duration_ms=round(total * 1000, 1))

    # --- replay every metric event in timestamp order, scraping every 15s
    events.sort(key=lambda e: e[0])
    next_scrape = float(T_START)
    for ts, kind, name, labels, value, tid in events:
        while ts >= next_scrape:
            _gauges(metrics, next_scrape, inuse, waiters, done, pool_size)
            metrics.scrape(next_scrape)
            next_scrape += SCRAPE_INTERVAL
        if kind == "c":
            metrics.inc(name, labels, value)
        else:
            metrics.observe(name, labels, value, ts=ts, trace_id=tid)
    while next_scrape <= T_END:
        _gauges(metrics, next_scrape, inuse, waiters, done, pool_size)
        metrics.scrape(next_scrape)
        next_scrape += SCRAPE_INTERVAL
    return Sim(metrics, logs, traces, n_requests, n_attempts, n_retries)


def _gauges(m: MetricStore, ts: float, inuse: dict[int, float], waiters: dict[int, float],
            done: dict[str, dict[int, int]], pool_size: int) -> None:
    """CPU, memory and pool occupancy, averaged over the scrape interval."""
    secs = range(int(ts) - SCRAPE_INTERVAL, int(ts))
    for service, cpu_base, cpu_per_rps in (("gateway", 0.22, 0.0012),
                                           ("orders", 0.25, 0.0015),
                                           ("payments", 0.24, 0.0016)):
        rps = sum(done[service][s] for s in secs) / SCRAPE_INTERVAL
        m.set_gauge("process_cpu_usage_ratio", lk(service=service), cpu_base + cpu_per_rps * rps)
        m.set_gauge("process_memory_usage_ratio", lk(service=service),
                    0.56 + 0.0002 * rps)
    used = sum(inuse[s] for s in secs) / SCRAPE_INTERVAL
    m.set_gauge("db_pool_connections_in_use", lk(service="payments", pool="postgres"), used)
    m.set_gauge("db_pool_utilization_ratio", lk(service="payments", pool="postgres"),
                used / pool_size)
    m.set_gauge("db_pool_waiters", lk(service="payments", pool="postgres"),
                sum(waiters[s] for s in secs) / SCRAPE_INTERVAL)


# ─── Part 2 · The query tools ────────────────────────────────────────────────

def _delta(points: list[tuple[float, float]], start: float, end: float) -> Optional[tuple[float, float]]:
    pts = [(t, v) for t, v in points if start <= t <= end]
    if len(pts) < 2 or pts[-1][0] == pts[0][0]:
        return None
    return pts[-1][1] - pts[0][1], pts[-1][0] - pts[0][0]


def promql_rate(m: MetricStore, name: str, start: float, end: float, **matchers: str) -> float:
    """sum(rate(name{matchers}[window])) -- per-second increase of a counter."""
    total = 0.0
    for key in m.select(name, **matchers):
        d = _delta(m.series[key], start, end)
        if d:
            total += d[0] / d[1]
    return total


def promql_gauge(m: MetricStore, name: str, start: float, end: float, **matchers: str) -> float:
    """avg_over_time(name{matchers}[window]) -- a gauge is read, not differentiated."""
    vals = [v for key in m.select(name, **matchers) for t, v in m.series[key]
            if start <= t <= end]
    return sum(vals) / len(vals) if vals else float("nan")


def promql_error_ratio(m: MetricStore, service: str, start: float, end: float) -> float:
    """The availability SLI: the share of requests that did not return 5xx."""
    total = promql_rate(m, "http_requests_total", start, end, service=service)
    if total == 0:
        return 0.0
    bad = sum(promql_rate(m, "http_requests_total", start, end, service=service, status=s)
              for s in ("500", "502", "503", "504"))
    return bad / total


def histogram_quantile(q: float, m: MetricStore, name: str, start: float, end: float,
                       **matchers: str) -> float:
    """histogram_quantile(q, sum by (le) (rate(name_bucket[window]))) -- Lesson 5's algorithm."""
    by_le: dict[float, float] = {}
    for key in m.select(name + "_bucket", **matchers):
        d = _delta(m.series[key], start, end)
        if not d:
            continue
        raw = dict(key[1])["le"]
        le = math.inf if raw == "+Inf" else float(raw)
        by_le[le] = by_le.get(le, 0.0) + d[0]
    items = sorted(by_le.items())
    if not items or items[-1][1] <= 0:
        return float("nan")
    rank, lower, lower_count = q * items[-1][1], 0.0, 0.0
    for le, cum in items:
        if cum >= rank:
            if math.isinf(le):
                return lower
            if cum == lower_count:
                return lower
            return lower + (le - lower) * (rank - lower_count) / (cum - lower_count)
        lower, lower_count = le, cum
    return items[-1][0]


def burn_rate(m: MetricStore, start: float, end: float,
              slo: float = SLO_AVAILABILITY) -> float:
    """How many times faster than 'even' the error budget is being spent."""
    return promql_error_ratio(m, "gateway", start, end) / (1.0 - slo)


def exemplar(m: MetricStore, name: str, le: float, start: float, end: float,
             **matchers: str) -> Optional[tuple[float, str, float]]:
    """Given a latency bucket and a window, hand back one trace that landed in it.

    Prometheus keeps the MOST RECENT exemplar per bucket, so that is what we return:
    a single representative request, not a hand-picked worst case.
    """
    best = None
    for (n, labels, bucket), rows in m.exemplars.items():
        if n != name or bucket != le:
            continue
        d = dict(labels)
        if any(d.get(k) != v for k, v in matchers.items()):
            continue
        for row in rows:
            if start <= row[0] <= end and (best is None or row[0] > best[0]):
                best = row
    return best


def waterfall(traces: TraceStore, trace_id: str, width: int = 46) -> list[str]:
    """Render a trace as proportional bars -- what Jaeger and Tempo draw for you."""
    spans = traces.traces[trace_id]
    root = spans[0]
    span_w = 38
    head = "0" + " " * (width - 6) + "%.2fs" % root.duration
    lines = ["  %-*s %8s  %s" % (span_w, "SPAN", "ms", head)]
    for s in spans:
        off = int((s.start - root.start) / root.duration * width)
        length = max(1, int(round(s.duration / root.duration * width)))
        off = min(off, width - 1)
        length = min(length, width - off)
        bar = "." * off + "#" * length
        mark = "  <--" if s.name == "pool.acquire" and s.duration > 0.25 else ""
        label = "  " * s.depth + s.service + " " + s.name
        lines.append("  %-*s %8.1f  %s%s" % (span_w, label[:span_w], s.duration * 1000, bar, mark))
    return lines


# ─── Part 3 · The investigation ──────────────────────────────────────────────

def step1_detect(sim: Sim) -> float:
    print("== STEP 1 . DETECT ==")
    print("  SLO   99.9% of POST /checkout requests succeed, 30-day window")
    print("  rule  sum(rate(http_requests_total{service=\"gateway\",status=~\"5..\"}[5m]))")
    print("          / sum(rate(http_requests_total{service=\"gateway\"}[5m])) / 0.001 > 14.4")
    print("  %-14s %11s %11s" % ("evaluated at", "err ratio", "burn rate"))
    fired = None
    for ts in range(T_START + 300, T_END + 1, 30):
        br = burn_rate(sim.metrics, ts - 300, ts)
        er = promql_error_ratio(sim.metrics, "gateway", ts - 300, ts)
        first = fired is None and br > FAST_BURN_THRESHOLD
        if first:
            fired = float(ts)
        if ts % 60 == 0 or first:
            print("  %-14s %10.3f%% %10.1fx%s" % (clock(ts), er * 100, br,
                                                  "   <-- FIRING" if first else ""))
    assert fired is not None
    br = burn_rate(sim.metrics, fired - 300, fired)
    print()
    print("  [PAGE]  SLOErrorBudgetFastBurn                     severity=critical")
    print("          fired      %s  ->  primary on-call" % clock(fired))
    print("          slo        checkout-availability  99.9% over 30d")
    print("          burn_rate  %.1fx   (>14.4x = 2%% of a 30-day budget in one hour)" % br)
    print("          exhausts   the whole 30-day error budget in %.1f hours at this rate"
          % (30 * 24 / br))
    print("          runbook    /runbooks/checkout-availability")
    return fired


def step2_triage(sim: Sim, w0: float, w1: float) -> None:
    m = sim.metrics
    print("\n== STEP 2 . TRIAGE ==")
    print("  RED per service, window %s -> %s" % (clock(w0), clock(w1)))
    print("  %-10s %9s %9s %9s %9s" % ("service", "req/s", "errors", "p50", "p99"))
    for svc in ("gateway", "orders", "payments", "bank-api"):
        print("  %-10s %9.1f %8.2f%% %8.0fms %8.0fms" % (
            svc, promql_rate(m, "http_requests_total", w0, w1, service=svc),
            promql_error_ratio(m, svc, w0, w1) * 100,
            histogram_quantile(0.50, m, "http_request_duration_seconds", w0, w1,
                               service=svc) * 1000,
            histogram_quantile(0.99, m, "http_request_duration_seconds", w0, w1,
                               service=svc) * 1000))
    print("\n  the same table for the baseline %s -> %s" % (clock(T_START), clock(T_DEPLOY)))
    print("  %-10s %9s %9s %9s %9s" % ("service", "req/s", "errors", "p50", "p99"))
    for svc in ("gateway", "payments"):
        print("  %-10s %9.1f %8.2f%% %8.0fms %8.0fms" % (
            svc, promql_rate(m, "http_requests_total", T_START, T_DEPLOY, service=svc),
            promql_error_ratio(m, svc, T_START, T_DEPLOY) * 100,
            histogram_quantile(0.50, m, "http_request_duration_seconds", T_START, T_DEPLOY,
                               service=svc) * 1000,
            histogram_quantile(0.99, m, "http_request_duration_seconds", T_START, T_DEPLOY,
                               service=svc) * 1000))
    print("\n  the usual suspects -- avg_over_time(...[5m]), now vs baseline")
    print("  %-10s %10s %10s %10s %10s" % ("service", "cpu", "cpu base", "mem", "mem base"))
    for svc in ("gateway", "orders", "payments"):
        print("  %-10s %9.1f%% %9.1f%% %9.1f%% %9.1f%%" % (
            svc, promql_gauge(m, "process_cpu_usage_ratio", w0, w1, service=svc) * 100,
            promql_gauge(m, "process_cpu_usage_ratio", T_START, T_DEPLOY, service=svc) * 100,
            promql_gauge(m, "process_memory_usage_ratio", w0, w1, service=svc) * 100,
            promql_gauge(m, "process_memory_usage_ratio", T_START, T_DEPLOY,
                         service=svc) * 100))


def step3_localize(sim: Sim, w0: float, w1: float) -> str:
    m = sim.metrics
    print("\n== STEP 3 . LOCALIZE ==")
    ex = exemplar(m, "http_request_duration_seconds", 3.0, w0, w1,
                  service="gateway", route="/checkout")
    assert ex is not None
    ts, tid, value = ex
    print("  exemplar attached to bucket le=\"3\" of")
    print("    http_request_duration_seconds_bucket{service=\"gateway\",route=\"/checkout\"}")
    print("    -> %s  trace_id=%s  %.0f ms" % (clock(ts), tid, value * 1000))
    total = len([1 for t in sim.traces.traces.values() if w0 <= t[0].start <= w1])
    hits = sim.traces.find_traces(min_duration=1.0, start=w0, end=w1, limit=10 ** 6)
    print("  find_traces(min_duration=1s): %d of %d sampled traces in the window (%.0f%%)"
          % (len(hits), total, 100.0 * len(hits) / total))
    print("\n  WATERFALL  trace_id=%s" % tid)
    for line in waterfall(sim.traces, tid):
        print(line)
    return tid


def step4_explain(sim: Sim, tid: str, w0: float, w1: float) -> None:
    print("\n== STEP 4 . EXPLAIN ==")
    print("  {service=~\".+\"} | json | trace_id=\"%s\"" % tid)
    for r in sorted(sim.logs.query(trace_id=tid), key=lambda x: x.ts):
        body = " ".join("%s=%s" % (k, v) for k, v in r.fields.items())
        print("  %s %-8s %-5s %-19s %s" % (clock(r.ts), r.service, r.level, r.event, body))
    print("\n  one request proves nothing -- aggregate the same event over the window:")
    slow = sim.logs.query(event="pool_acquire_slow", start=w0, end=w1)
    charges = promql_rate(sim.metrics, "http_requests_total", w0, w1, service="payments")
    print("  sum(count_over_time({service=\"payments\"} | json"
          " | event=\"pool_acquire_slow\" [5m]))")
    print("    %d lines over %ds = %.1f/s, against %.1f charge attempts/s = %.0f%% of them"
          % (len(slow), int(w1 - w0), len(slow) / (w1 - w0), charges,
             100.0 * (len(slow) / (w1 - w0)) / charges))
    waits = sorted(r.fields["wait_ms"] for r in slow)
    print("    wait_ms among them:  p50 %.0f   p99 %.0f   max %.0f"
          % (waits[len(waits) // 2], waits[min(int(len(waits) * 0.99), len(waits) - 1)],
             waits[-1]))
    print("  the identical query over %s -> %s (before the ramp): %d lines"
          % (clock(T_START), clock(T_RAMP),
             len(sim.logs.query(event="pool_acquire_slow", start=T_START, end=T_RAMP))))


def step5_correlate(sim: Sim) -> None:
    m = sim.metrics
    print("\n== STEP 5 . CORRELATE WITH CHANGE ==")
    for ts, service, version, change in DEPLOYS:
        print("  deploy annotation  %s  %s %s  \"%s\"" % (clock(ts), service, version, change))
    print("  %-12s %8s %9s %10s %11s %11s"
          % ("t", "req/s", "p99 gw", "fraud p99", "pool used", "pool wait p99"))
    for ts in range(T_START + 60, T_END + 1, 60):
        note = {T_DEPLOY: "  <-- deploy", T_RAMP + 60: "  <-- ramp"}.get(ts, "")
        fraud = histogram_quantile(0.99, m, "http_request_duration_seconds", ts - 60, ts,
                                   service="bank-api", route="/fraud-score") * 1000
        print("  %-12s %8.1f %8.0fms %10s %11.2f %10.0fms%s" % (
            clock(ts),
            promql_rate(m, "http_requests_total", ts - 60, ts, service="gateway"),
            histogram_quantile(0.99, m, "http_request_duration_seconds", ts - 60, ts,
                               service="gateway") * 1000,
            "no route" if math.isnan(fraud) else "%.0fms" % fraud,
            promql_gauge(m, "db_pool_connections_in_use", ts - 60, ts),
            histogram_quantile(0.99, m, "pool_wait_seconds", ts - 60, ts) * 1000, note))


def step6_amplifier(sim: Sim, w0: float, w1: float) -> None:
    m = sim.metrics
    print("\n== STEP 6 . CONFIRM THE AMPLIFIER ==")
    orders_rate = promql_rate(m, "http_requests_total", w0, w1, service="orders")
    pay_rate = promql_rate(m, "http_requests_total", w0, w1, service="payments")
    failed = len(sim.logs.query(event="payment_call_failed", start=w0, end=w1))
    print("  sum(rate(http_requests_total{service=\"orders\"}[5m]))    %7.1f /s  "
          "one per checkout" % orders_rate)
    print("  sum(rate(http_requests_total{service=\"payments\"}[5m]))  %7.1f /s  "
          "one per ATTEMPT" % pay_rate)
    print("  amplification                                          %7.2fx"
          % (pay_rate / orders_rate))
    print("  the same ratio in the baseline window                  %7.2fx"
          % (promql_rate(m, "http_requests_total", T_START, T_DEPLOY, service="payments")
             / promql_rate(m, "http_requests_total", T_START, T_DEPLOY, service="orders")))
    print("  {service=\"orders\"} | event=\"payment_call_failed\"      %8d lines (%.1f/s)"
          % (failed, failed / (w1 - w0)))
    print("  whole run: %d checkouts -> %d attempts (%d retries)"
          % (sim.requests, sim.attempts, sim.retries))
    print("\n  what the retry budget buys, and what it costs -- same traffic, same fault:")
    global MAX_ATTEMPTS
    runs = [("1  (no retry)", simulate(record=False, attempts=1)),
            ("2  (as configured)", sim),
            ("4", simulate(record=False, attempts=4))]
    print("  %-20s %10s %8s %9s %10s" % ("max attempts", "attempts", "load", "errors", "p99"))
    for label, run in runs:
        print("  %-20s %10d %7.2fx %8.2f%% %9.0fms" % (
            label, run.attempts, run.attempts / run.requests,
            promql_error_ratio(run.metrics, "gateway", w0, w1) * 100,
            histogram_quantile(0.99, run.metrics, "http_request_duration_seconds", w0, w1,
                               service="gateway") * 1000))


def step7_mitigate(sim: Sim, w0: float, w1: float) -> None:
    print("\n== STEP 7 . MITIGATE ==")
    print("  re-run the identical timeline and traffic, one variable changed")
    print("  %-28s %9s %9s %9s %11s"
          % ("scenario", "errors", "p50", "p99", "pool used"))

    def row(label: str, s: Sim) -> None:
        m = s.metrics
        print("  %-28s %8.2f%% %8.0fms %8.0fms %11.2f" % (
            label, promql_error_ratio(m, "gateway", w0, w1) * 100,
            histogram_quantile(0.50, m, "http_request_duration_seconds", w0, w1,
                               service="gateway") * 1000,
            histogram_quantile(0.99, m, "http_request_duration_seconds", w0, w1,
                               service="gateway") * 1000,
            promql_gauge(m, "db_pool_connections_in_use", w0, w1)))

    row("as it happened", sim)
    row("roll back payments v2.4.1", simulate(deployed=False, record=False))
    row("keep v2.4.1, pool 4 -> 16", simulate(pool_size=16, record=False))
    print("  the hypothesis predicted both rows. Rolling back ships in one minute and")
    print("  needs no capacity review, so it is the MITIGATION; the pool size is the FIX.")


def step8_learn(sim: Sim, detected: float, w0: float, w1: float) -> None:
    print("\n== STEP 8 . LEARN ==")
    onset = next(float(ts) for ts in range(T_RAMP, T_END, 15)
                 if histogram_quantile(0.99, sim.metrics, "http_request_duration_seconds",
                                       ts - 60, ts, service="gateway") > 1.0)
    print("  %-26s %s" % ("deploy of payments v2.4.1", clock(T_DEPLOY)))
    print("  %-26s %s  (p99 crosses 1s)" % ("onset", clock(onset)))
    print("  %-26s %s  MTTD = %.0f s" % ("detected / paged", clock(detected),
                                         detected - onset))
    print("  %-26s %s" % ("rollback triggered", clock(T_ROLLBACK)))
    print("  %-26s %s  MTTR = %.0f s (%.1f min)"
          % ("SLI healthy again", clock(T_RECOVERED), T_RECOVERED - onset,
             (T_RECOVERED - onset) / 60))
    print("  localization -- the usual bulk of MTTR -- was STEP 3: one exemplar click.")
    print("\n  OBSERVABILITY GAPS FOUND (each becomes an action item)")
    util = promql_gauge(sim.metrics, "db_pool_utilization_ratio", w0, w1)
    base_util = promql_gauge(sim.metrics, "db_pool_utilization_ratio", T_START, T_DEPLOY)
    print("  1 db_pool_utilization_ratio read %.2f (baseline %.2f) with NO alert and NO"
          % (util, base_util))
    print("    dashboard panel. It was the first signal to move and nobody was watching.")
    print("  2 the RED dashboard has no saturation row: USE says every resource needs")
    print("    utilization + saturation + errors, and the pool is a resource.")
    print("  3 orders retries with no budget: %.2fx extra load onto the one resource"
          % (promql_rate(sim.metrics, "http_requests_total", w0, w1, service="payments")
             / promql_rate(sim.metrics, "http_requests_total", w0, w1, service="orders")))
    print("    that was already the bottleneck, and it doubled p99 (STEP 6). Add a")
    print("    retry budget and a circuit breaker so a slow dependency is not retried.")
    print("  4 no metric for time-a-connection-is-held per code path, so the deploy that")
    print("    quadrupled it looked identical to every other deploy on every dashboard.")


def main() -> None:
    sim = simulate()
    fired = step1_detect(sim)
    w0, w1 = float(T_PEAK), float(T_END)
    step2_triage(sim, w0, w1)
    tid = step3_localize(sim, w0, w1)
    step4_explain(sim, tid, w0, w1)
    step5_correlate(sim)
    step6_amplifier(sim, w0, w1)
    step7_mitigate(sim, w0, w1)
    step8_learn(sim, fired, w0, w1)


if __name__ == "__main__":
    main()
