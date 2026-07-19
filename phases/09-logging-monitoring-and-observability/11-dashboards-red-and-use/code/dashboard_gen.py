#!/usr/bin/env python3
"""Generate a real Grafana dashboard from a declarative RED/USE spec -- dashboards as code.

Builds, with nothing but the standard library: a spec layer (Service, Resource);
red_panels() emitting Rate/Errors/Duration panels with real PromQL; use_panels()
emitting Utilization/Saturation/Errors panels; an SLO error-budget stat derived
from the target; a packing layout engine that assigns Grafana gridPos on the
24-column grid so the highest-importance panel lands top-left; a valid dashboard
JSON model with $service/$route templating, a deploy-annotation query and
exemplars; a linter that runs this lesson's design rules over both the generated
dashboard and a deliberately awful legacy fixture; and a text wireframe of the
packed grid.

Follows the Grafana dashboard JSON model (schemaVersion 39), the RED method
(Wilkie), the USE method (Gregg) and the Four Golden Signals (Google SRE book).
Deterministic: no clocks, no randomness, no network.

Runs on the Python standard library only:  python dashboard_gen.py
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field

GRID_COLUMNS = 24          # Grafana's grid is always 24 columns wide
MAX_PANELS = 16            # a dashboard you can read under stress
DS = {"type": "prometheus", "uid": "${datasource}"}


# ─── The spec layer: what you declare ────────────────────────────────────────

@dataclass(frozen=True)
class Service:
    """A request-driven service. RED applies to these."""
    name: str
    routes: tuple[str, ...]
    slo_target: float               # e.g. 0.999 = three nines of successful requests
    slo_window: str = "30d"


@dataclass(frozen=True)
class Resource:
    """A thing a service consumes and can run out of. USE applies to these."""
    name: str
    kind: str                       # "cpu" | "pool" | "queue"


@dataclass
class Target:
    """One query on a panel. Grafana calls these targets."""
    expr: str
    legend: str
    exemplar: bool = False


@dataclass
class Panel:
    title: str                                  # a QUESTION, always
    targets: list[Target]
    unit: str                                   # a Grafana unit id: s, percentunit, reqps...
    kind: str = "timeseries"
    w: int = 8
    h: int = 8
    importance: int = 50                        # higher sorts earlier -> nearer top-left
    thresholds: list[tuple[float | None, str]] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    description: str = ""

    def to_json(self, pid: int, grid_pos: dict) -> dict:
        steps = [{"color": c, "value": v} for v, c in self.thresholds] \
            or [{"color": "text", "value": None}]
        custom = {} if self.kind == "stat" else \
            {"custom": {"drawStyle": "line", "lineWidth": 2, "fillOpacity": 8}}
        return {
            "id": pid, "type": self.kind, "title": self.title,
            "description": self.description, "datasource": DS, "gridPos": grid_pos,
            "fieldConfig": {"overrides": [], "defaults": {
                "unit": self.unit, **custom,
                "thresholds": {"mode": "absolute", "steps": steps}}},
            "options": {"tooltip": {"mode": "multi", "sort": "desc"},
                        "legend": {"displayMode": "table", "placement": "bottom",
                                   "calcs": ["lastNotNull", "max"]}},
            "links": [{"title": t, "url": u, "targetBlank": True} for t, u in self.links],
            "targets": [{"refId": chr(65 + i), "editorMode": "code", "range": True,
                         "expr": t.expr, "legendFormat": t.legend, "exemplar": t.exemplar}
                        for i, t in enumerate(self.targets)],
        }


# ─── RED: Rate, Errors, Duration -- for request-driven services ──────────────

SEL = 'service="$service", route=~"$route"'


def red_panels(svc: Service) -> list[Panel]:
    rate_expr = f'sum by (route) (\n  rate(http_requests_total{{{SEL}}}[5m])\n)'
    # The error ratio divides two vectors. Both sides are grouped `by (route)`, so
    # every label set on the left has exactly one partner on the right: PromQL's
    # one-to-one vector matching. Drop `by (route)` from one side and you get an
    # empty result, silently.
    err_expr = (f'sum by (route) (rate(http_requests_total{{{SEL}, status=~"5.."}}[5m]))\n'
                f'  /\n'
                f'sum by (route) (rate(http_requests_total{{{SEL}}}[5m]))')

    def quantile(q: float, extra: str = "") -> str:
        sel = SEL + extra
        return (f'histogram_quantile({q},\n'
                f'  sum by (le) (rate(http_request_duration_seconds_bucket{{{sel}}}[5m]))\n)')

    runbook = (f"Runbook: {svc.name}", f"https://runbooks.internal/{svc.name}")
    return [
        Panel(
            title="What fraction of requests are failing?",
            description="RED · Errors. Ratio, not a count: 50 errors means nothing "
                        "without the denominator.",
            targets=[Target(err_expr, "{{route}}")],
            unit="percentunit", w=9, h=8, importance=90,
            thresholds=[(None, "green"), (0.001, "orange"), (0.01, "red")],
            links=[runbook],
        ),
        Panel(
            title="How slow is a request, at each percentile?",
            description="RED · Duration. p50/p90/p99 on one axis shows the SHAPE of the "
                        "distribution. Exemplars link a bucket to a trace.",
            targets=[Target(quantile(0.50), "p50", exemplar=True),
                     Target(quantile(0.90), "p90", exemplar=True),
                     Target(quantile(0.99), "p99", exemplar=True)],
            unit="s", w=9, h=8, importance=80,
            thresholds=[(None, "green"), (0.3, "orange"), (1.0, "red")],
            links=[("Traces for this window", "/explore?left=%7B%22datasource%22:%22tempo%22%7D")],
        ),
        Panel(
            title="How many requests per second, by route?",
            description="RED · Rate. Context for the other two: 3 errors out of 4 requests "
                        "and 3 out of 40,000 look identical on an error COUNT panel.",
            targets=[Target(rate_expr, "{{route}}")],
            unit="reqps", w=12, h=8, importance=70,
        ),
        Panel(
            title="How slow are the requests that FAILED?",
            description="A fast 500 flatters the main latency panel during an outage. "
                        "Requires an `outcome` label on the duration histogram.",
            targets=[Target(quantile(0.99, ', outcome="failure"'), "p99 failed"),
                     Target(quantile(0.99, ', outcome="success"'), "p99 succeeded")],
            unit="s", w=12, h=8, importance=60,
        ),
    ]


def slo_panel(svc: Service) -> Panel:
    budget = 1.0 - svc.slo_target                      # the allowed bad-event ratio
    expr = (f'1 - (\n'
            f'    sum(increase(http_requests_total{{service="$service", status=~"5.."}}'
            f'[{svc.slo_window}]))\n'
            f'  / sum(increase(http_requests_total{{service="$service"}}[{svc.slo_window}]))\n'
            f') / {budget:.5f}')
    return Panel(
        title="Is the error budget still healthy?",
        description=f"SLO {svc.slo_target:.3%} over {svc.slo_window}. Budget = "
                    f"{budget:.3%} of requests may fail. 0% left means stop shipping.",
        targets=[Target(expr, "budget remaining")],
        unit="percentunit", kind="stat", w=6, h=8, importance=100,
        thresholds=[(None, "red"), (0.0, "orange"), (0.25, "green")],
        links=[("SLO policy", f"https://runbooks.internal/slo/{svc.name}")],
    )


# ─── USE: Utilization, Saturation, Errors -- for resources ──────────────────

USE_TEMPLATES: dict[str, list[tuple[str, str, str, str]]] = {
    # kind: [(signal, question, promql, unit), ...]
    "cpu": [
        ("Utilization", "How much CPU is in use?",
         'max(1 - rate(node_cpu_seconds_total{service="$service", mode="idle"}[5m]))\n'
         '  # busiest instance -- NOT one line per instance', "percentunit"),
        ("Saturation", "Is work waiting for a CPU?",
         'max(node_load1{service="$service"})\n'
         '  / min(machine_cpu_cores{service="$service"})', "short"),
        ("Errors", "Is the CPU being throttled?",
         'sum(rate(container_cpu_cfs_throttled_seconds_total{service="$service"}[5m]))',
         "percentunit"),
    ],
    "pool": [
        ("Utilization", "How much of the pool is checked out?",
         'sum(db_pool_connections_in_use{service="$service"})\n'
         '  / sum(db_pool_connections_max{service="$service"})', "percentunit"),
        ("Saturation", "How many callers are waiting for a connection?",
         'sum(db_pool_waiters{service="$service"})', "short"),
        ("Errors", "How often does acquiring a connection fail?",
         'sum(rate(db_pool_acquire_timeouts_total{service="$service"}[5m]))', "ops"),
    ],
    "queue": [
        ("Utilization", "How busy are the queue consumers?",
         'sum(rate(queue_consumer_busy_seconds_total{service="$service"}[5m]))\n'
         '  / sum(queue_consumers{service="$service"})', "percentunit"),
        ("Saturation", "How deep is the backlog?",
         'sum(queue_depth{service="$service"})', "short"),
        ("Errors", "How many messages are dead-lettering?",
         'sum(rate(queue_dead_lettered_total{service="$service"}[5m]))', "ops"),
    ],
}

SATURATION_NOTE = ("Saturation is the predictive one: 100% utilization with an empty "
                   "queue is fine, 70% with a growing queue is about to fall over.")


def use_panels(res: Resource) -> list[Panel]:
    panels = []
    for i, (signal, question, expr, unit) in enumerate(USE_TEMPLATES[res.kind]):
        panels.append(Panel(
            title=question,
            description=f"USE · {signal} for {res.name}."
                        + (f" {SATURATION_NOTE}" if signal == "Saturation" else ""),
            targets=[Target(expr, res.name)],
            unit=unit, w=8, h=6,
            importance=90 if signal == "Saturation" else 80 - i,
        ))
    return panels


# ─── The layout engine: pack panels onto the 24-column grid ─────────────────

@dataclass
class Section:
    title: str
    panels: list[Panel]


def layout(sections: list[Section]) -> list[dict]:
    """Assign gridPos by packing left-to-right, wrapping at column 24.

    Panels are sorted by descending importance first, so the panel you most need
    under stress lands at x=0, y=top -- where the eye starts (F-pattern reading).
    Python's sort is stable, so equal-importance panels keep declaration order.
    """
    out: list[dict] = []
    pid, y = 1, 0
    for sec in sections:
        out.append({"id": pid, "type": "row", "title": sec.title, "collapsed": False,
                    "gridPos": {"h": 1, "w": GRID_COLUMNS, "x": 0, "y": y}, "panels": []})
        pid, y = pid + 1, y + 1
        x = row_h = 0
        for panel in sorted(sec.panels, key=lambda p: -p.importance):
            if x + panel.w > GRID_COLUMNS:              # wrap to a new shelf
                y, x, row_h = y + row_h, 0, 0
            out.append(panel.to_json(pid, {"h": panel.h, "w": panel.w, "x": x, "y": y}))
            pid, x, row_h = pid + 1, x + panel.w, max(row_h, panel.h)
        y += row_h
    return out


def build_dashboard(title: str, uid: str, sections: list[Section]) -> dict:
    return {
        "uid": uid, "title": title, "tags": ["generated", "red", "use", "phase-10"],
        "schemaVersion": 39, "version": 1, "editable": True, "timezone": "utc",
        "graphTooltip": 1,                              # 1 = shared crosshair across panels
        "time": {"from": "now-6h", "to": "now"}, "refresh": "30s",
        "templating": {"list": [
            {"name": "datasource", "type": "datasource", "query": "prometheus",
             "current": {"text": "Prometheus", "value": "Prometheus"}, "hide": 0},
            {"name": "service", "type": "query", "label": "Service", "datasource": DS,
             "query": "label_values(http_requests_total, service)", "refresh": 1,
             "includeAll": False, "multi": False},
            {"name": "route", "type": "query", "label": "Route", "datasource": DS,
             "query": 'label_values(http_requests_total{service="$service"}, route)',
             "refresh": 2, "includeAll": True, "allValue": ".*", "multi": True},
        ]},
        "annotations": {"list": [
            {"builtIn": 1, "name": "Annotations & Alerts", "type": "dashboard",
             "enable": True, "hide": True},
            {"name": "Deploys", "enable": True, "iconColor": "purple", "datasource": DS,
             "expr": 'changes(process_start_time_seconds{service="$service"}[$__interval]) > 0',
             "titleFormat": "deploy", "textFormat": "{{version}}", "step": "60s"},
        ]},
        "links": [{"title": "Runbooks", "type": "link",
                   "url": "https://runbooks.internal/", "targetBlank": True}],
        "panels": layout(sections),
    }


# ─── The linter: the lesson's design rules, made executable ─────────────────

@dataclass
class Finding:
    rule: str
    where: str
    detail: str


DURATION_UNITS = {"s", "ms", "us", "ns"}
AVG_LATENCY_SIGNS = ("avg(", "avg_over_time(", "_sum[", "_sum{")
HIGH_CARD_GROUPING = ("by (instance)", "by (pod)", "by (container_id)")


def lint(dash: dict) -> list[Finding]:
    findings: list[Finding] = []
    panels = [p for p in dash["panels"] if p["type"] != "row"]

    for p in panels:
        title, unit = p["title"], p["fieldConfig"]["defaults"]["unit"]
        exprs = " ".join(t["expr"] for t in p.get("targets", []))
        if not title.strip().endswith("?"):
            findings.append(Finding("title-is-a-question", title,
                                    "a panel with no question is decoration"))
        if not unit:
            findings.append(Finding("unit-declared", title,
                                    "a bare number means nothing at 03:00"))
        if unit in DURATION_UNITS and any(s in exprs for s in AVG_LATENCY_SIGNS):
            findings.append(Finding("no-average-latency", title,
                                    "averages hide the tail -- use histogram_quantile"))
        if any(g in exprs for g in HIGH_CARD_GROUPING):
            findings.append(Finding("no-per-instance-fanout", title,
                                    "one line per instance is spaghetti at fleet scale"))
        if "timeFrom" in p:
            findings.append(Finding("consistent-time-range", title,
                                    f'panel overrides the dashboard range (timeFrom='
                                    f'{p["timeFrom"]!r}) -- spikes stop lining up'))
        if not p.get("targets"):
            findings.append(Finding("panel-has-a-query", title, "panel queries nothing"))

    if len(panels) > MAX_PANELS:
        findings.append(Finding("panel-budget", dash["title"],
                                f"{len(panels)} panels (limit {MAX_PANELS}) -- built by "
                                f"accretion, nobody ever deleted one"))

    # Occupancy: every cell of the bounding box claimed exactly once.
    claimed: dict[tuple[int, int], str] = {}
    overlaps, max_y = 0, 0
    for p in dash["panels"]:
        g = p["gridPos"]
        max_y = max(max_y, g["y"] + g["h"])
        for cx in range(g["x"], g["x"] + g["w"]):
            for cy in range(g["y"], g["y"] + g["h"]):
                if (cx, cy) in claimed:
                    overlaps += 1
                claimed[(cx, cy)] = p["title"]
    gaps = GRID_COLUMNS * max_y - len(claimed)
    if overlaps:
        findings.append(Finding("grid-no-overlap", dash["title"],
                                f"{overlaps} grid cells claimed twice -- panels stack "
                                f"unpredictably when the browser is narrow"))
    if gaps:
        findings.append(Finding("grid-no-gaps", dash["title"],
                                f"{gaps} empty grid cells inside the layout"))
    return findings


def report(dash: dict) -> None:
    findings = lint(dash)
    print(f"  dashboard: {dash['title']}")
    if not findings:
        print("  PASS -- 0 findings against 9 rules\n")
        return
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.rule, []).append(f)
    n = len(findings)
    print(f"  FAIL -- {n} finding{'s' if n != 1 else ''} across {len(by_rule)} rules")
    for rule, group in by_rule.items():
        print(f"    [{rule}]  x{len(group)}  {group[0].detail}")
        for f in group[:3]:
            print(f"        - {f.where[:58]}")
        if len(group) > 3:
            print(f"        - ... and {len(group) - 3} more")
    print()


# ─── The wireframe renderer: see what the packer packed ─────────────────────

CELL = 4                                # characters per grid column
BAND = 3                                # text lines per vertical band


def wireframe(dash: dict) -> None:
    buf: list[dict] = []

    def flush() -> None:
        if not buf:
            return
        top = min(p["gridPos"]["y"] for p in buf)
        bounds = sorted({p["gridPos"]["y"] - top for p in buf} |
                        {p["gridPos"]["y"] - top + p["gridPos"]["h"] for p in buf})
        line_of = {b: i * BAND for i, b in enumerate(bounds)}
        w, h = GRID_COLUMNS * CELL + 1, line_of[bounds[-1]] + 1
        canvas = [[" "] * w for _ in range(h)]
        for p in buf:
            g = p["gridPos"]
            x0, x1 = g["x"] * CELL, (g["x"] + g["w"]) * CELL
            y0, y1 = line_of[g["y"] - top], line_of[g["y"] - top + g["h"]]
            for x in range(x0, x1 + 1):
                canvas[y0][x] = canvas[y1][x] = "-"
            for y in range(y0, y1 + 1):
                canvas[y][x0] = canvas[y][x1] = "|"
            for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
                canvas[y][x] = "+"
            inner = x1 - x0 - 3
            lines = textwrap.wrap(p["title"], inner)[:y1 - y0 - 1]
            for i, text in enumerate(lines):
                for j, ch in enumerate(text[:inner]):
                    canvas[y0 + 1 + i][x0 + 2 + j] = ch
        for row in canvas:
            print("  " + "".join(row).rstrip())
        buf.clear()

    for p in dash["panels"]:
        if p["type"] == "row":
            flush()
            print(f"\n  == {p['title']} " + "=" * max(0, 70 - len(p["title"])))
        else:
            buf.append(p)
    flush()


# ─── A legacy dashboard nobody ever deleted a panel from ────────────────────

def legacy_dashboard() -> dict:
    raw = [
        ("CPU", "avg(node_cpu_utilization)", "", 12, 8, 0, 0, {}),
        ("Average latency",
         "avg(rate(http_request_duration_seconds_sum[5m])\n"
         "    / rate(http_request_duration_seconds_count[5m]))", "s", 12, 8, 6, 0, {}),
        ("Requests by pod", "sum by (pod) (rate(http_requests_total[5m]))",
         "reqps", 8, 8, 0, 8, {}),
        ("Errors last 24h", "sum(increase(http_requests_total{status=~'5..'}[24h]))",
         "short", 8, 8, 8, 8, {"timeFrom": "24h"}),
        ("p99 latency", "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))",
         "s", 8, 8, 16, 8, {}),
    ]
    filler = ["JVM heap", "GC pause time", "Thread count", "Disk read IOPS",
              "Network in", "Network out", "Open file descriptors", "Kafka consumer lag",
              "Redis hit ratio", "Total signups all time", "Build number", "Uptime"]
    for i, name in enumerate(filler):
        raw.append((name, f'sum({name.lower().replace(" ", "_")})', "short",
                    6, 4, (i % 4) * 6, 16 + (i // 4) * 4, {}))
    panels = []
    for pid, (title, expr, unit, w, h, x, y, extra) in enumerate(raw, start=1):
        panel = {"id": pid, "type": "timeseries", "title": title, "datasource": DS,
                 "gridPos": {"h": h, "w": w, "x": x, "y": y},
                 "fieldConfig": {"defaults": {"unit": unit, "thresholds":
                                              {"mode": "absolute", "steps": []}},
                                 "overrides": []},
                 "targets": [{"refId": "A", "expr": expr, "legendFormat": ""}]}
        panel.update(extra)
        panels.append(panel)
    return {"uid": "legacy-overview", "title": "Service Overview (legacy)",
            "schemaVersion": 39, "panels": panels}


# ─── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    checkout = Service("checkout-service", ("/checkout", "/cart", "/health"), slo_target=0.999)
    resources = [Resource("db connection pool", "pool"), Resource("cpu", "cpu")]

    red = red_panels(checkout)
    sections = [
        Section("Is the service healthy right now?  (RED + SLO)",
                [slo_panel(checkout)] + red[:2]),
        Section("Traffic and failure latency  (RED)", red[2:]),
    ] + [Section(f"Dependency: {r.name}  (USE)", use_panels(r)) for r in resources]

    dash = build_dashboard(f"{checkout.name} · RED + USE", "svc-red-use", sections)

    print("== 1 · THE SPEC (what a human writes) ==")
    print(f"  {checkout}")
    for r in resources:
        print(f"  {r}")
    counted = [p for p in dash['panels'] if p['type'] != 'row']
    print(f"  -> {len(counted)} panels, {len(dash['panels']) - len(counted)} rows, "
          f"{len(json.dumps(dash))} bytes of dashboard JSON")

    print("\n== 2 · PANELS THE GENERATOR PRODUCED ==")
    print(f"  {'gridPos (h,w,x,y)':<20} {'unit':<12} title")
    for p in dash["panels"]:
        g = p["gridPos"]
        if p["type"] == "row":
            print(f"  {'':<20} {'':<12} [row] {p['title']}")
            continue
        pos = f"{g['h']},{g['w']},{g['x']},{g['y']}"
        print(f"  {pos:<20} {p['fieldConfig']['defaults']['unit']:<12} {p['title']}")

    print("\n== 3 · THE PACKED GRID (24 columns, most important panel top-left) ==")
    wireframe(dash)

    print("\n== 4 · GRAFANA JSON: the top-left panel, verbatim ==")
    top_left = next(p for p in dash["panels"]
                    if p["type"] != "row" and p["gridPos"]["x"] == 0)
    print(textwrap.indent(json.dumps(top_left, indent=2), "  "))

    print("\n== 5 · GRAFANA JSON: the $route variable and the deploy annotation ==")
    print(textwrap.indent(json.dumps(
        {"templating": {"list": dash["templating"]["list"][2:]},
         "annotations": {"list": dash["annotations"]["list"][1:]}}, indent=2), "  "))

    print("\n== 6 · LINT ==")
    report(dash)
    report(legacy_dashboard())


if __name__ == "__main__":
    main()
