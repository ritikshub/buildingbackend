"""
prometheus_mini.py -- the whole Prometheus loop in one standard-library file.

  1. A metric registry (counter + histogram) behind a real /metrics endpoint, served by
     http.server on an ephemeral port in the Prometheus text exposition format.
  2. A scraper that PULLS that endpoint on a fixed interval, parses the text format back
     into samples, stamps target labels on them, and stores them in a mini TSDB.
  3. A tiny PromQL evaluator: rate() with counter-reset handling and edge extrapolation,
     sum by (...), and histogram_quantile() over summed bucket rates.

Two instances are scraped. One fails a scrape (the synthetic `up` series goes to 0) and then
restarts, so its counters drop to zero -- exactly the case rate() exists to survive.
Follows the Prometheus text exposition format and its OpenMetrics successor
(github.com/OpenObservability/OpenMetrics, specification/OpenMetrics.md).
Deterministic: random is seeded and every timestamp derives from a fixed base.

Runs on the Python standard library only:  python prometheus_mini.py
"""

from __future__ import annotations

import http.server
import math
import random
import re
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

BASE_TS = 1_700_000_000        # fixed epoch base -> deterministic printed timestamps
SCRAPE_INTERVAL = 15           # seconds. Prometheus calls this `scrape_interval`
N_SCRAPES = 12
FAILING_SCRAPE = 7             # app-1 returns 503 on this scrape, then restarts
REQS_PER_INTERVAL = 40
BUCKETS: Tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)

LabelKey = Tuple[Tuple[str, str], ...]


# ─── The metric registry: what the application process owns ──────────────────

def _fmt_value(v: float) -> str:
    return str(int(v)) if float(v).is_integer() else "%.6f" % v


def _fmt_le(v: float) -> str:
    return "+Inf" if math.isinf(v) else "%g" % v


def _fmt_labels(labels: Dict[str, str], extra: Optional[Tuple[str, str]] = None) -> str:
    items = sorted(labels.items())
    if extra is not None:
        items.append(extra)
    return "{" + ",".join('%s="%s"' % (k, v) for k, v in items) + "}" if items else ""


class Registry:
    """Counters and histograms living in one process's memory."""

    def __init__(self) -> None:
        self.counters: Dict[Tuple[str, LabelKey], float] = {}
        self.hists: Dict[Tuple[str, LabelKey], Dict[str, object]] = {}
        self.help: Dict[str, str] = {}

    def describe(self, name: str, text: str) -> None:
        self.help[name] = text

    def inc(self, name: str, labels: Dict[str, str], amount: float = 1.0) -> None:
        key = (name, tuple(sorted(labels.items())))
        self.counters[key] = self.counters.get(key, 0.0) + amount

    def observe(self, name: str, labels: Dict[str, str], value: float) -> None:
        key = (name, tuple(sorted(labels.items())))
        h = self.hists.get(key)
        if h is None:
            h = self.hists[key] = {"buckets": [0] * len(BUCKETS), "sum": 0.0, "count": 0}
        for i, upper in enumerate(BUCKETS):       # buckets are CUMULATIVE: an observation
            if value <= upper:                    # lands in every bucket whose le >= value
                h["buckets"][i] += 1              # type: ignore[index]
        h["sum"] = float(h["sum"]) + value
        h["count"] = int(h["count"]) + 1

    def render(self) -> str:
        """Emit the Prometheus text exposition format, byte for byte."""
        out: List[str] = []
        for name in sorted({n for n, _ in self.counters}):
            out.append("# HELP %s %s" % (name, self.help.get(name, "")))
            out.append("# TYPE %s counter" % name)
            for (n, lk), v in sorted(self.counters.items()):
                if n == name:
                    out.append("%s%s %s" % (n, _fmt_labels(dict(lk)), _fmt_value(v)))
        for name in sorted({n for n, _ in self.hists}):
            out.append("# HELP %s %s" % (name, self.help.get(name, "")))
            out.append("# TYPE %s histogram" % name)
            for (n, lk), h in sorted(self.hists.items()):
                if n != name:
                    continue
                labels, counts = dict(lk), h["buckets"]
                for i, upper in enumerate(BUCKETS):
                    out.append("%s_bucket%s %d" % (
                        n, _fmt_labels(labels, ("le", _fmt_le(upper))), counts[i]))  # type: ignore[index]
                out.append("%s_bucket%s %d" % (n, _fmt_labels(labels, ("le", "+Inf")), h["count"]))
                out.append("%s_sum%s %s" % (n, _fmt_labels(labels), _fmt_value(float(h["sum"]))))
                out.append("%s_count%s %d" % (n, _fmt_labels(labels), h["count"]))
        return "\n".join(out) + "\n"


# ─── The /metrics endpoint: an HTTP server the scraper can pull ──────────────

@dataclass
class App:
    name: str
    url: str = ""
    down: bool = False
    registry: Registry = field(default_factory=Registry)


def _make_handler(app: App):
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:                       # noqa: N802 (stdlib naming)
            if self.path != "/metrics":
                body, code = b"not found\n", 404
            elif app.down:
                body, code = b"service unavailable\n", 503
            else:
                body, code = app.registry.render().encode("utf-8"), 200
            self.send_response(code)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args) -> None:           # keep the console clean
            pass

    return Handler


def fresh_registry() -> Registry:
    r = Registry()
    r.describe("http_requests_total", "Total HTTP requests served.")
    r.describe("http_request_duration_seconds", "Request duration in seconds.")
    return r


def start_app(name: str) -> App:
    app = App(name=name, registry=fresh_registry())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(app))
    app.url = "http://127.0.0.1:%d/metrics" % server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return app


def simulate_traffic(app: App, n: int) -> None:
    for _ in range(n):
        route = random.choice(["/checkout", "/cart"])
        status = "500" if random.random() < 0.03 else "200"
        slow = random.random() < 0.05
        latency = random.uniform(0.9, 3.0) if slow else max(0.001, random.gauss(0.06, 0.02))
        app.registry.inc("http_requests_total", {"route": route, "status": status})
        app.registry.observe("http_request_duration_seconds", {"route": route}, latency)


# ─── Parsing the exposition format back into samples ─────────────────────────

SAMPLE_RE = re.compile(r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>[^}]*)\})?\s+(?P<value>\S+)$")
LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse_exposition(text: str) -> List[Tuple[str, Dict[str, str], float]]:
    """text exposition format -> [(metric_name, labels, value)]. Comments are metadata."""
    samples: List[Tuple[str, Dict[str, str], float]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = SAMPLE_RE.match(line)
        if not m:
            continue
        raw = m.group("value")
        samples.append((m.group("name"),
                        dict(LABEL_RE.findall(m.group("labels") or "")),
                        math.inf if raw == "+Inf" else float(raw)))
    return samples


# ─── The mini TSDB: one list of (timestamp, value) points per series ─────────

def series_id(name: str, labels: Dict[str, str]) -> str:
    return name + _fmt_labels(labels)


class TSDB:
    def __init__(self) -> None:
        self.series: Dict[str, List[Tuple[int, float]]] = {}
        self.labels: Dict[str, Dict[str, str]] = {}
        self.names: Dict[str, str] = {}

    def append(self, name: str, labels: Dict[str, str], ts: int, value: float) -> None:
        sid = series_id(name, labels)
        self.series.setdefault(sid, []).append((ts, value))
        self.labels[sid] = labels
        self.names[sid] = name

    def select(self, name: str, matchers: Optional[Dict[str, str]] = None) -> List[str]:
        """The instant-vector selector: every series whose name and labels match."""
        return sorted(sid for sid, mname in self.names.items() if mname == name and all(
            self.labels[sid].get(k) == v for k, v in (matchers or {}).items()))

    def range_points(self, sid: str, start: int, end: int) -> List[Tuple[int, float]]:
        """A range vector: points in the half-open window (start, end]."""
        return [(t, v) for t, v in self.series[sid] if start < t <= end]


def scrape(app: App, ts: int, tsdb: TSDB, job: str) -> Tuple[bool, int, Optional[float]]:
    """One pull. Returns (up, samples stored, total request count seen)."""
    target = {"job": job, "instance": app.name}
    try:
        with urllib.request.urlopen(app.url, timeout=2.0) as resp:
            body = resp.read().decode("utf-8")
            ok = resp.status == 200
    except OSError:                     # HTTPError and connection refusal both land here
        ok, body = False, ""
    # `up` is SYNTHETIC: the scraper writes it, the target never sends it.
    tsdb.append("up", dict(target), ts, 1.0 if ok else 0.0)
    if not ok:
        return False, 1, None
    total, n = 0.0, 1
    for name, labels, value in parse_exposition(body):
        labels.update(target)          # target labels are attached at scrape time
        tsdb.append(name, labels, ts, value)
        n += 1
        if name == "http_requests_total":
            total += value
    return True, n, total


# ─── A tiny PromQL evaluator ─────────────────────────────────────────────────

def rate(points: Sequence[Tuple[int, float]], start: int, end: int) -> Optional[float]:
    """rate(metric[window]) -- per-second increase, correcting for counter resets."""
    if len(points) < 2:
        return None                                    # a rate needs two points, minimum
    correction, prev = 0.0, points[0][1]
    for _, v in points[1:]:
        if v < prev:                                   # a decrease can only mean a RESET;
            correction += prev                         # add back everything counted before it
        prev = v
    delta = (points[-1][1] + correction) - points[0][1]
    # Extrapolate from the first/last sample out to the window edges, the way Prometheus does.
    sampled = points[-1][0] - points[0][0]
    if sampled == 0:
        return None
    avg_gap = sampled / (len(points) - 1)
    to_start, to_end = points[0][0] - start, end - points[-1][0]
    if delta > 0 and points[0][1] >= 0:                # never extrapolate past where the
        to_start = min(to_start, sampled * (points[0][1] / delta))   # counter would be zero
    threshold = 1.1 * avg_gap
    if to_start >= threshold:
        to_start = avg_gap / 2                         # a big gap means the series started late
    if to_end >= threshold:
        to_end = avg_gap / 2
    delta *= (sampled + to_start + to_end) / sampled
    return delta / (end - start)


def naive_rate(points: Sequence[Tuple[int, float]], start: int, end: int) -> float:
    """What you get if you forget that counters restart: (last - first) / window."""
    return (points[-1][1] - points[0][1]) / (end - start)


def sum_by(tsdb: TSDB, values: Dict[str, float], by: Sequence[str]) -> Dict[Tuple[str, ...], float]:
    """sum by (labels)(vector) -- drop every label not in `by`, add what collides."""
    out: Dict[Tuple[str, ...], float] = {}
    for sid, v in values.items():
        key = tuple(tsdb.labels[sid].get(label, "") for label in by)
        out[key] = out.get(key, 0.0) + v
    return out


def histogram_quantile(q: float, bucket_rates: Dict[float, float]) -> float:
    """Estimate the q-quantile by interpolating inside the bucket that contains it."""
    items = sorted(bucket_rates.items())
    total = items[-1][1] if items else 0.0
    if total <= 0:
        return float("nan")
    rank, lower, lower_count = q * total, 0.0, 0.0
    for le, count in items:
        if count >= rank:
            if math.isinf(le):
                return lower                            # the tail is unbounded: report le
            if count == lower_count:
                return lower
            return lower + (le - lower) * (rank - lower_count) / (count - lower_count)
        lower, lower_count = le, count
    return items[-1][0]


# ─── main ────────────────────────────────────────────────────────────────────

def main() -> None:
    random.seed(20241118)
    apps = [start_app("app-1"), start_app("app-2")]
    for app in apps:
        simulate_traffic(app, REQS_PER_INTERVAL)

    print("== EXPOSITION FORMAT: the literal bytes of GET /metrics ==")
    with urllib.request.urlopen(apps[0].url, timeout=2.0) as resp:
        print("  HTTP %d  Content-Type: %s" % (resp.status, resp.headers["Content-Type"]))
        payload = resp.read().decode("utf-8")
    lines = payload.splitlines()
    for line in lines[:8] + ["..."] + lines[11:13] + ["..."] + lines[18:21]:
        print("  " + line)
    print("  ... %d more lines: buckets, and the same family for route=\"/checkout\""
          % (len(lines) - 21))
    print("  (%d lines, %d bytes total)" % (len(lines), len(payload)))

    tsdb = TSDB()
    print("\n== SCRAPE LOG: the scraper drives the clock, 15s interval ==")
    print("  %5s | %-27s | %-27s" % ("t", "app-1  up  samples    total", "app-2  up  samples    total"))
    for i in range(N_SCRAPES):
        ts = BASE_TS + i * SCRAPE_INTERVAL
        if i > 0:
            for app in apps:
                simulate_traffic(app, REQS_PER_INTERVAL)
        apps[0].down = (i == FAILING_SCRAPE)
        cells = []
        for app in apps:
            ok, n, total = scrape(app, ts, tsdb, job="api")
            cells.append("%9d %8d %8s" % (ok, n, "-" if total is None else "%.0f" % total))
        note = ("  <- app-1 scrape FAILED: only `up` stored" if i == FAILING_SCRAPE else
                "  <- app-1 restarted: counter back to zero" if i == FAILING_SCRAPE + 1 else "")
        print("  %+4ds | %s | %s%s" % (ts - BASE_TS, cells[0], cells[1], note))
        if i == FAILING_SCRAPE:
            apps[0].registry = fresh_registry()         # the process restarted: counters -> 0
    print("  series in the mini TSDB: %d" % len(tsdb.series))

    window, eval_ts = 120, BASE_TS + (N_SCRAPES - 1) * SCRAPE_INTERVAL
    start = eval_ts - window
    sid = series_id("http_requests_total",
                    {"instance": "app-1", "job": "api", "route": "/checkout", "status": "200"})
    pts = tsdb.range_points(sid, start, eval_ts)

    print("\n== rate() vs NAIVE last-minus-first, ACROSS THE RESET ==")
    print("  series: %s" % sid)
    print("  rate(...[2m]) @ t=+%ds  ->  samples in (+%ds, +%ds]" % (
        eval_ts - BASE_TS, start - BASE_TS, eval_ts - BASE_TS))
    shown, prev = [], None
    for t, v in pts:
        if prev is not None and v < prev:
            shown.append("|RESET|")
        shown.append("%d" % v)
        prev = v
    print("  raw values:  " + "  ".join(shown))
    print("  naive (last - first) / 120s  =  %+7.3f req/s   <- WRONG: the reset ate the traffic"
          % naive_rate(pts, start, eval_ts))
    print("  rate()  reset-aware          =  %+7.3f req/s   <- correct"
          % rate(pts, start, eval_ts))

    print("\n== sum by (route) (rate(http_requests_total[2m])) ==")
    rates = {}
    for s in tsdb.select("http_requests_total"):
        r = rate(tsdb.range_points(s, start, eval_ts), start, eval_ts)
        if r is not None:
            rates[s] = r
    grouped = sum_by(tsdb, rates, ["route"])
    for key in sorted(grouped):
        print("  %-22s %6.2f req/s" % ('{route="%s"}' % key[0], grouped[key]))
    print("  %-22s %6.2f req/s   (%d series -> %d groups, both instances folded in)"
          % ("fleet total", sum(grouped.values()), len(rates), len(grouped)))
    errs = sum_by(tsdb, {s: r for s, r in rates.items() if tsdb.labels[s]["status"] == "500"}, [])
    print("  %-22s %6.2f %%       (sum(rate(...{status=\"500\"})) / sum(rate(...)))"
          % ("error ratio", 100.0 * sum(errs.values()) / sum(grouped.values())))

    print("\n== histogram_quantile(0.99, sum by (le) (rate(..._bucket[2m]))) ==")
    bucket_rates: Dict[float, float] = {}
    for s in tsdb.select("http_request_duration_seconds_bucket"):
        r = rate(tsdb.range_points(s, start, eval_ts), start, eval_ts)
        if r is None:
            continue
        le = float(tsdb.labels[s]["le"].replace("+Inf", "inf"))
        bucket_rates[le] = bucket_rates.get(le, 0.0) + r
    for le in sorted(bucket_rates):
        bar = "#" * int(bucket_rates[le] * 4)
        print("  le=%-6s %6.2f obs/s  %s" % (_fmt_le(le), bucket_rates[le], bar))
    for q in (0.50, 0.90, 0.99):
        print("  p%-3d = %6.3f s" % (q * 100, histogram_quantile(q, bucket_rates)))


if __name__ == "__main__":
    main()
