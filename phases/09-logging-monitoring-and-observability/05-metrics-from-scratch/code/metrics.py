#!/usr/bin/env python3
"""
Metrics from scratch: counters, gauges, histograms — and why histograms aggregate.

Companion to docs/en.md (Phase 10, Lesson 05). Builds what a real metrics client
library contains, standard library only: a Registry keyed by (name, sorted label
set) so {a=1,b=2} and {b=2,a=1} are the SAME series; a Counter (monotonic), a
Gauge (up and down) and a Histogram (cumulative `le` buckets + _sum + _count);
histogram_quantile() — the linear-interpolation algorithm Prometheus uses —
validated against the exact quantile of the raw observations; proof that SUMMING
bucket counts gives a correct fleet-wide p99 while AVERAGING three servers' p99s
gives a meaningless number; a cardinality demo; and a correct rendering of the
Prometheus/OpenMetrics text exposition format. Deterministic: every RNG is seeded.

Runs standalone on the Python standard library only:  python metrics.py
"""

from __future__ import annotations
import bisect
import math
import random
from typing import Iterator, Mapping, Sequence


# ─── Series identity: a name plus an order-independent label set ──────────────

LabelSet = tuple[tuple[str, str], ...]


def label_key(labels: Mapping[str, str]) -> LabelSet:
    """A series' identity is name + labels. Sorting makes label order irrelevant."""
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _fmt_labels(pairs: LabelSet) -> str:
    if not pairs:
        return ""
    esc = lambda v: v.replace("\\", r"\\").replace('"', r"\"").replace("\n", r"\n")
    return "{" + ",".join(f'{k}="{esc(v)}"' for k, v in pairs) + "}"


def _fmt_num(value: float) -> str:
    if value == math.inf:
        return "+Inf"
    if float(value).is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


# ─── The registry: every series the process will ever expose ──────────────────

class Registry:
    """Maps metric name -> family; each family maps a label set -> one series."""
    def __init__(self) -> None:
        self._metrics: dict[str, Metric] = {}

    def register(self, metric: "Metric") -> None:
        if metric.name in self._metrics:
            raise ValueError(f"metric {metric.name!r} already registered")
        self._metrics[metric.name] = metric

    def series_count(self) -> int:
        """Total stored time series — what the metrics backend actually pays for."""
        return sum(m.series_count() for m in self._metrics.values())

    def render(self) -> str:
        """Prometheus text exposition format — exactly what GET /metrics returns."""
        lines: list[str] = []
        for name in sorted(self._metrics):
            metric = self._metrics[name]
            lines.append(f"# HELP {name} {metric.documentation}")
            lines.append(f"# TYPE {name} {metric.typename}")
            for key in sorted(metric.children):
                for suffix, extra, value in metric.samples(metric.children[key]):
                    lines.append(f"{name}{suffix}{_fmt_labels(key + extra)} {_fmt_num(value)}")
        return "\n".join(lines) + "\n"


class Metric:
    """Base class for a metric FAMILY: one name, many label-set children."""
    typename = "untyped"

    def __init__(self, name: str, documentation: str,
                 labelnames: Sequence[str] = (), registry: Registry | None = None):
        self.name, self.documentation = name, documentation
        self.labelnames = tuple(sorted(labelnames))
        self.children: dict[LabelSet, object] = {}
        if registry is not None:
            registry.register(self)

    def labels(self, **kw: str):
        """Return the child series bound to this label set, creating it if new."""
        if set(kw) != set(self.labelnames):
            raise ValueError(f"{self.name} needs {self.labelnames}, got {tuple(sorted(kw))}")
        key = label_key(kw)
        if key not in self.children:
            self.children[key] = self._new_child()
        return self.children[key]

    def series_count(self) -> int:
        return len(self.children)

    def _new_child(self):
        raise NotImplementedError

    def samples(self, child) -> Iterator[tuple[str, LabelSet, float]]:
        raise NotImplementedError


# ─── Counter: only ever goes up, or back to zero when the process restarts ────

class CounterChild:
    def __init__(self) -> None:
        self.value = 0.0

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("counters are monotonic: inc() cannot be negative")
        self.value += amount


class Counter(Metric):
    typename = "counter"

    def __init__(self, name: str, documentation: str, labelnames: Sequence[str] = (),
                 registry: Registry | None = None):
        if not name.endswith("_total"):
            raise ValueError(f"counter {name!r} must end in '_total' (naming convention)")
        super().__init__(name, documentation, labelnames, registry)

    def _new_child(self) -> CounterChild:
        return CounterChild()

    def inc(self, amount: float = 1.0) -> None:
        self.labels().inc(amount)

    def samples(self, child: CounterChild):
        yield ("", (), child.value)


def counter_increase(scrapes: Sequence[float]) -> float:
    """Total increase across scrapes, correcting for resets — what rate() does.

    A DROP means the process restarted, so everything since the restart is the
    new value itself, not a negative delta.
    """
    return sum(cur - prev if cur >= prev else cur for prev, cur in zip(scrapes, scrapes[1:]))


# ─── Gauge: a snapshot of "now" — goes up and down ────────────────────────────

class GaugeChild:
    def __init__(self) -> None:
        self.value = 0.0

    def set(self, value: float) -> None:
        self.value = float(value)

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        self.value -= amount


class Gauge(Metric):
    typename = "gauge"

    def _new_child(self) -> GaugeChild:
        return GaugeChild()

    def samples(self, child: GaugeChild):
        yield ("", (), child.value)


# ─── Histogram: cumulative `le` buckets, plus _sum and _count ─────────────────

DEFAULT_BUCKETS = (.005, .01, .025, .05, .1, .25, .5, 1., 2.5, 5., 10.)   # Prometheus' default
GOOD_BUCKETS = (.005, .01, .025, .05, .075, .1, .25, .5, .75, 1., 1.5, 2., 3., 5., 7.5, 10.)
BAD_BUCKETS = (.01, .1, 1., 10.)


class HistogramChild:
    def __init__(self, upper_bounds: Sequence[float]) -> None:
        self.upper_bounds = tuple(upper_bounds)
        self.bucket_counts = [0] * (len(self.upper_bounds) + 1)   # last slot = the +Inf overflow
        self.sum, self.count = 0.0, 0

    def observe(self, value: float) -> None:
        self.sum += value
        self.count += 1
        # bisect_left finds the first bound with value <= bound: that is the `le` bucket.
        self.bucket_counts[bisect.bisect_left(self.upper_bounds, value)] += 1

    def cumulative(self) -> list[tuple[float, int]]:
        """[(le, how many observations were <= le)] — the aggregatable form."""
        out, running = [], 0
        for i, bound in enumerate(self.upper_bounds):
            running += self.bucket_counts[i]
            out.append((bound, running))
        out.append((math.inf, self.count))          # +Inf always holds every observation
        return out


class Histogram(Metric):
    typename = "histogram"

    def __init__(self, name: str, documentation: str, labelnames: Sequence[str] = (),
                 buckets: Sequence[float] = DEFAULT_BUCKETS, registry: Registry | None = None):
        self.upper_bounds = tuple(sorted(buckets))
        super().__init__(name, documentation, labelnames, registry)

    def _new_child(self) -> HistogramChild:
        return HistogramChild(self.upper_bounds)

    def series_count(self) -> int:
        # every bucket is its own series, plus +Inf, plus _sum and _count
        return len(self.children) * (len(self.upper_bounds) + 3)

    def samples(self, child: HistogramChild):
        for bound, cum in child.cumulative():
            yield ("_bucket", (("le", _fmt_num(bound)),), cum)
        yield ("_sum", (), child.sum)
        yield ("_count", (), float(child.count))


def merge_cumulative(hists: Sequence[list[tuple[float, int]]]) -> list[tuple[float, int]]:
    """Add bucket counts across instances. THIS is why histograms aggregate."""
    bounds = [b for b, _ in hists[0]]
    if any([b for b, _ in h] != bounds for h in hists[1:]):
        raise ValueError("bucket ladders must match before they can be summed")
    return [(bounds[i], sum(h[i][1] for h in hists)) for i in range(len(bounds))]


# ─── Quantile estimation from cumulative buckets ──────────────────────────────

def histogram_quantile(q: float, buckets: Sequence[tuple[float, int]]) -> float:
    """Estimate the q-quantile from cumulative `le` buckets (Prometheus' algorithm).

    Find the bucket holding the target rank, then interpolate linearly inside it,
    assuming observations are spread evenly across the bucket's width.
    """
    total = buckets[-1][1]
    if total == 0:
        return float("nan")
    rank = q * total
    idx = next(i for i, (_, cum) in enumerate(buckets) if cum >= rank)
    if idx == len(buckets) - 1:
        return buckets[-2][0]        # inside +Inf: unbounded above, so report the last bound
    lower_bound = buckets[idx - 1][0] if idx > 0 else 0.0
    lower_count = buckets[idx - 1][1] if idx > 0 else 0
    in_bucket = buckets[idx][1] - lower_count
    if in_bucket == 0:
        return buckets[idx][0]
    return lower_bound + (buckets[idx][0] - lower_bound) * ((rank - lower_count) / in_bucket)


def exact_quantile(values: Sequence[float], q: float) -> float:
    """The TRUE quantile, computed from every raw observation (nearest-rank)."""
    ordered = sorted(values)
    return ordered[min(max(1, math.ceil(q * len(ordered))), len(ordered)) - 1]


def err_pct(estimate: float, truth: float) -> float:
    return (estimate - truth) / truth * 100.0


# ─── Simulated traffic: a fast body, a slower shoulder, a long tail ───────────

def sample_latency(rng: random.Random, degraded: bool = False) -> float:
    r = rng.random()
    if degraded:
        if r < 0.70:
            return rng.lognormvariate(math.log(0.070), 0.40)
        if r < 0.85:
            return rng.lognormvariate(math.log(0.50), 0.50)
        return rng.uniform(2.0, 9.0)
    if r < 0.90:
        return rng.lognormvariate(math.log(0.045), 0.35)
    if r < 0.985:
        return rng.lognormvariate(math.log(0.16), 0.40)
    return rng.uniform(0.5, 1.5)


def server_latencies(seed: int, n: int, degraded: bool = False) -> list[float]:
    rng = random.Random(seed)
    return [sample_latency(rng, degraded) for _ in range(n)]


# ─── Demos ────────────────────────────────────────────────────────────────────

def demo_averages_lie() -> None:
    print("== 1 · WHY AVERAGES LIE ==")
    latencies = [0.050] * 950 + [6.000] * 50
    mean = sum(latencies) / len(latencies)
    print("  1000 requests: 950 at 50ms, 50 at 6s")
    print(f"  mean = {mean * 1000:7.1f} ms   <- looks fine on a dashboard")
    for q in (0.50, 0.95, 0.99):
        print(f"  p{int(q * 100):<3d} = {exact_quantile(latencies, q) * 1000:7.1f} ms")
    near = sum(1 for v in latencies if abs(v - mean) < 0.100)
    print(f"  requests within 100ms of the mean: {near}/1000  <- the mean describes nobody")


def demo_counters_and_gauges(registry: Registry) -> None:
    print("\n== 2 · COUNTERS, GAUGES AND THE RESET PROBLEM ==")
    requests = Counter("http_requests_total", "Total HTTP requests.",
                       ["route", "status"], registry=registry)
    in_flight = Gauge("http_requests_in_flight", "Requests being served right now.",
                      ["route"], registry=registry)
    duration = Histogram("http_request_duration_seconds", "HTTP request latency.",
                         ["route"], buckets=GOOD_BUCKETS, registry=registry)
    rng = random.Random(11)
    for _ in range(4000):
        route = "/checkout" if rng.random() < 0.4 else "/search"
        status = "500" if rng.random() < 0.012 else "200"
        in_flight.labels(route=route).inc()
        requests.labels(route=route, status=status).inc()
        duration.labels(route=route).observe(sample_latency(rng))
        in_flight.labels(route=route).dec()
    in_flight.labels(route="/checkout").set(7)
    in_flight.labels(route="/search").set(2)
    same = (requests.labels(status="200", route="/checkout")
            is requests.labels(route="/checkout", status="200"))
    print(f"  label order independence: {{route,status}} is {{status,route}} -> {same}")
    for key in sorted(requests.children):
        print(f"  {requests.name}{_fmt_labels(key)} = {_fmt_num(requests.children[key].value)}")
    print('  http_requests_in_flight{route="/checkout"} = 7   (a gauge: a snapshot of now)')
    scrapes = [1_240, 1_402, 1_559, 118, 297]     # the process restarted before scrape #4
    naive = sum(b - a for a, b in zip(scrapes, scrapes[1:]))
    fixed = counter_increase(scrapes)
    print(f"  counter scrapes 15s apart: {scrapes}  (restart before the 4th)")
    print(f"  naive sum of deltas      = {naive:7.0f}  <- nonsense: one interval is -1441")
    print(f"  reset-aware increase()   = {fixed:7.0f}  = {fixed / 60:.2f} req/s over 60s")
    try:
        requests.labels(route="/search", status="200").inc(-5)
    except ValueError as exc:
        print(f"  inc(-5) on a counter -> ValueError: {exc}")


def demo_bucket_choice(latencies: Sequence[float]) -> None:
    print("\n== 3 · QUANTILES FROM BUCKETS: LADDER CHOICE IS THE ERROR BAR ==")
    cums = []
    for bounds in (GOOD_BUCKETS, BAD_BUCKETS):
        child = HistogramChild(bounds)
        for value in latencies:
            child.observe(value)
        cums.append(child.cumulative())
    print(f"  GOOD le = {' '.join(_fmt_num(b) for b in GOOD_BUCKETS)}")
    print(f"  BAD  le = {' '.join(_fmt_num(b) for b in BAD_BUCKETS)}")
    print(f"  {'q':<7}{'exact':>10}{'GOOD ladder':>21}{'BAD ladder':>21}")
    for q in (0.50, 0.90, 0.99, 0.999):
        truth = exact_quantile(latencies, q)
        g, b = histogram_quantile(q, cums[0]), histogram_quantile(q, cums[1])
        print(f"  {'p' + f'{q * 100:g}':<7}{truth * 1000:8.1f}ms{g * 1000:11.1f}ms"
              f"{'(' + f'{err_pct(g, truth):+.1f}' + '%)':>10}{b * 1000:11.1f}ms"
              f"{'(' + f'{err_pct(b, truth):+.1f}' + '%)':>10}")


def demo_aggregation() -> None:
    print("\n== 4 · HISTOGRAMS AGGREGATE · PERCENTILES DO NOT ==")
    fleet = {"web-1": server_latencies(101, 6000), "web-2": server_latencies(202, 3000),
             "web-3": server_latencies(303, 400, degraded=True)}
    per_server_p99, cumulatives, everything = [], [], []
    for name, values in fleet.items():
        child = HistogramChild(GOOD_BUCKETS)
        for value in values:
            child.observe(value)
        cum = child.cumulative()
        per_server_p99.append(histogram_quantile(0.99, cum))
        cumulatives.append(cum)
        everything.extend(values)
        print(f"  {name}: n={len(values):>5}  p99 = {per_server_p99[-1] * 1000:8.1f} ms")
    truth = exact_quantile(everything, 0.99)
    naive = sum(per_server_p99) / len(per_server_p99)
    merged = histogram_quantile(0.99, merge_cumulative(cumulatives))
    print(f"  TRUE fleet p99 (all {len(everything)} raw observations)   = {truth * 1000:8.1f} ms")
    print(f"  (a) average of the three p99s           = {naive * 1000:8.1f} ms  "
          f"error {err_pct(naive, truth):+7.1f}%   WRONG")
    print(f"  (b) sum the bucket counts, then estimate = {merged * 1000:8.1f} ms  "
          f"error {err_pct(merged, truth):+7.1f}%   correct")


def demo_cardinality() -> None:
    print("\n== 5 · CARDINALITY: SERIES COUNT IS A PRODUCT ==")
    routes = [f"/v1/r{i}" for i in range(8)]
    sane = Registry()
    hits = Counter("api_requests_total", "API requests.", ["route", "status", "region"],
                   registry=sane)
    for route in routes:
        for status in ("200", "400", "404", "500", "503"):
            for region in ("eu", "us", "ap"):
                hits.labels(route=route, status=status, region=region).inc()
    row = lambda label, n: print(f"  {label:<44}= {n:>10,} series")
    row("8 routes x 5 statuses x 3 regions", sane.series_count())
    hot = Registry()
    per_user = Counter("api_requests_total", "API requests.",
                       ["route", "status", "region", "user_id"], registry=hot)
    for route in routes[:2]:
        for status in ("200", "500"):
            for user in range(200):
                per_user.labels(route=route, status=status, region="eu", user_id=f"u{user}")
    row("2 routes x 2 statuses x 1 region x 200 users", hot.series_count())
    row("...the same shape at 50,000 real users", 8 * 5 * 3 * 50_000)
    lat = Registry()
    hist = Histogram("api_latency_seconds", "API latency.", ["route", "status", "region"],
                     buckets=GOOD_BUCKETS, registry=lat)
    for route in routes:
        for status in ("200", "500"):
            for region in ("eu", "us", "ap"):
                hist.labels(route=route, status=status, region=region)
    row("16-bucket histogram over 8 x 2 x 3 labels", lat.series_count())
    print("  (a histogram costs 19 series per label set: 16 buckets + Inf + _sum + _count)")


def demo_exposition(registry: Registry) -> None:
    print("\n== 6 · PROMETHEUS TEXT EXPOSITION FORMAT ==")
    lines = registry.render().splitlines()
    for line in lines[:4] + ["..."] + lines[37:40] + ["..."] + lines[-2:]:
        print(f"  {line}")
    print(f"  ({len(lines)} lines total, {registry.series_count()} series -- "
          "this is exactly what GET /metrics returns)")


def main() -> None:
    demo_averages_lie()
    registry = Registry()
    demo_counters_and_gauges(registry)
    demo_bucket_choice(server_latencies(77, 20_000))
    demo_aggregation()
    demo_cardinality()
    demo_exposition(registry)


if __name__ == "__main__":
    main()
