#!/usr/bin/env python3
"""Phase 11 · Lesson 04 — Layer 4 vs Layer 7, Health Checks & Outlier Ejection.

Companion to docs/en.md. Pure simulation: no sockets, no network, stdlib only, seeded.
Sources: Eisenbud et al., "Maglev: A Fast and Reliable Software Network Load Balancer",
NSDI 2016 (L4 connection-tracking + direct server return); RFC 9113 §5 (HTTP/2 streams
multiplexed over one connection); Envoy health-check / outlier-detection reference for
knob names and defaults; Bronson et al., "Metastable Failures in Distributed Systems",
HotOS 2021 (the sustaining feedback loop the death spiral is an instance of).
"""

from __future__ import annotations

import math
import random
import time
from typing import Dict, List, Optional, Tuple

WALL0 = time.perf_counter()


def banner(text: str) -> None:
    print(f"\n== {text} ==")


def poisson(rng: random.Random, lam: float) -> int:
    """Knuth's method; normal approximation once lam is large enough to matter."""
    if lam <= 0.0:
        return 0
    if lam > 30.0:
        return max(0, int(rng.gauss(lam, math.sqrt(lam)) + 0.5))
    target, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= target:
            return k
        k += 1


def small(x: float, width: int = 9) -> str:
    """Rates in this lesson span 1e8; render them all legibly in one column."""
    if x == 0.0:
        return f"{'0':>{width}s}"
    if x >= 0.01:
        return f"{x:{width}.4f}"
    return f"{x:{width}.1e}"


def pct(sorted_vals: List[float], q: float) -> float:
    if not sorted_vals:
        return float("nan")
    idx = min(len(sorted_vals) - 1, max(0, int(q * len(sorted_vals))))
    return sorted_vals[idx]


# ---------------------------------------------------------------------------
# 1 · L4 vs L7 over long-lived connections
# ---------------------------------------------------------------------------

RUN_S = 900          # simulated seconds
N_CONNS = 24         # client connections, all established at t=0 (a client redeploy)
N_BACKENDS = 8       # backends at t=0
NEW_AT = 300         # a ninth backend joins the pool here
MEAN_RPS = 8.0       # mean requests/second per connection
RATE_SIGMA = 1.0     # spread of per-connection request rates


def conn_rates(rng: random.Random) -> List[float]:
    """Real clients are not identical. Rates are lognormal: a few chatty, many quiet."""
    return [MEAN_RPS * math.exp(rng.gauss(0.0, RATE_SIGMA) - RATE_SIGMA ** 2 / 2)
            for _ in range(N_CONNS)]


def run_fleet(
    mode: str,
    rates: List[float],
    seed: int,
    conn_lifetime: Optional[float] = None,
    max_age: Optional[float] = None,
    age_jitter: float = 0.0,
) -> Tuple[List[int], List[int], int, int]:
    """Return (reqs per backend over the whole run, reqs per backend after NEW_AT,
    peak reconnects landing in any one second, first second the new backend saw work).

    mode "l4": the balancer picks a backend once, at connection setup, and every
    request on that connection follows it. mode "l7": it picks per request.
    conn_lifetime: mean seconds before the client closes and reopens (None = never).
    max_age: server-side max_connection_age, in seconds (None = disabled).
    """
    rng = random.Random(seed)
    total = [0] * (N_BACKENDS + 1)
    after = [0] * (N_BACKENDS + 1)
    reconnects_per_s = [0] * (RUN_S + 1)
    first_seen = -1

    def live_backends(t: int) -> int:
        return N_BACKENDS + 1 if t >= NEW_AT else N_BACKENDS

    def expiry(t: float) -> float:
        if max_age is None:
            return float("inf")
        # gRPC multiplies MAX_CONNECTION_AGE by a random factor in [1-j, 1+j].
        return t + max_age * (1.0 + rng.uniform(-age_jitter, age_jitter))

    def natural_close(t: float) -> float:
        if conn_lifetime is None:
            return float("inf")
        return t + rng.expovariate(1.0 / conn_lifetime)

    rr_conn = 0          # the balancer's round-robin cursor over connections (L4)
    rr_req = 0           # ... and over requests (L7)
    assigned = [0] * N_CONNS
    deadline = [0.0] * N_CONNS
    for c in range(N_CONNS):
        assigned[c] = rr_conn % N_BACKENDS
        rr_conn += 1
        deadline[c] = min(expiry(0.0), natural_close(0.0))

    for t in range(RUN_S):
        n_live = live_backends(t)
        for c in range(N_CONNS):
            if t >= deadline[c]:
                # The connection went away and the client immediately reopened it.
                # THIS is the only moment an L4 balancer gets to make a decision.
                reconnects_per_s[t] += 1
                assigned[c] = rr_conn % n_live      # n_live now includes the new backend
                rr_conn += 1
                deadline[c] = min(expiry(float(t)), natural_close(float(t)))
            k = poisson(rng, rates[c])
            if k == 0:
                continue
            if mode == "l4":
                b = assigned[c]          # decided at connection setup, frozen since
                total[b] += k
                if t >= NEW_AT:
                    after[b] += k
                if b == N_BACKENDS and first_seen < 0:
                    first_seen = t
            else:
                for _ in range(k):       # a fresh decision, every single request
                    b = rr_req % n_live
                    rr_req += 1
                    total[b] += 1
                    if t >= NEW_AT:
                        after[b] += 1
                    if b == N_BACKENDS and first_seen < 0:
                        first_seen = t
    return total, after, max(reconnects_per_s), first_seen


def section1() -> Dict[str, float]:
    banner("1 · L4 BALANCES CONNECTIONS. L7 BALANCES REQUESTS.")
    rng = random.Random(7)
    rates = conn_rates(rng)
    offered = sum(rates)
    print(f"  {N_CONNS} client connections, {N_BACKENDS} backends, a 9th joins at t={NEW_AT}s.")
    print(f"  per-connection request rate is lognormal: min {min(rates):.2f}/s, "
          f"median {sorted(rates)[N_CONNS // 2]:.2f}/s, max {max(rates):.2f}/s")
    print(f"  offered load {offered:.0f} req/s for {RUN_S}s; the balancer is round-robin in both modes.")

    configs = [
        ("L4  gRPC: connections never close", "l4", dict(conn_lifetime=None, max_age=None)),
        ("L4  HTTP/1.1 churn: conn ~15s", "l4", dict(conn_lifetime=15.0, max_age=None)),
        ("L4  max_connection_age 300s, NO jitter", "l4", dict(conn_lifetime=None, max_age=300.0)),
        ("L4  max_connection_age 300s, +/-10% jitter", "l4",
         dict(conn_lifetime=None, max_age=300.0, age_jitter=0.10)),
        ("L7  proxy: decide per request", "l7", dict(conn_lifetime=None, max_age=None)),
    ]

    print()
    print("  config                                     hottest  coldest  spread   new-inst   burst")
    print("                                              share    share    x        share      /s")
    out: Dict[str, float] = {}
    rows = []
    for label, mode, kw in configs:
        total, after, burst, first = run_fleet(mode, rates, seed=11, **kw)
        n_after = sum(after)
        shares = [100.0 * a / n_after for a in after]
        # hottest/coldest are measured over the eight ORIGINAL backends, so every row
        # is comparable; the ninth gets its own column.
        hot, cold = max(shares[:N_BACKENDS]), min(shares[:N_BACKENDS])
        spread = hot / cold if cold > 0 else float("inf")
        new_share = shares[N_BACKENDS]
        print(f"  {label:<42s} {hot:5.1f}%   {cold:5.1f}%  {spread:5.1f}    {new_share:5.1f}%   {burst:5d}")
        rows.append((label, hot, cold, new_share, burst, first, total))
        out[label] = new_share

    l4_hot, l4_cold, l4_new = rows[0][1], rows[0][2], rows[0][3]
    l7_hot, l7_cold = rows[4][1], rows[4][2]
    print()
    print(f"  L4 over never-closing connections: hottest backend takes {l4_hot:.1f}% of requests,")
    print(f"  coldest takes {l4_cold:.1f}% — a {l4_hot / l4_cold:.1f}x spread, from a balancer that")
    print(f"  divided the CONNECTIONS perfectly evenly ({N_CONNS}/{N_BACKENDS} = {N_CONNS // N_BACKENDS} each).")
    print(f"  The new instance received {rows[0][6][N_BACKENDS]} requests in {RUN_S - NEW_AT}s of being healthy and in the pool.")
    print(f"  Same balancer, same algorithm, connections lasting ~15s: spread {rows[1][1] / rows[1][2]:.2f}x, "
          f"new instance {rows[1][3]:.1f}%.")
    print(f"  L7: spread {l7_hot / l7_cold:.2f}x, new instance {rows[4][3]:.1f}%. Nothing about the")
    print("  ALGORITHM changed between those rows. Only the layer the decision is made at.")
    print()
    print(f"  max_connection_age without jitter: every connection was opened in the same second,")
    print(f"  so every connection expires in the same second — {rows[2][4]} simultaneous reconnects,")
    print(f"  {rows[2][4] / max(1, rows[3][4]):.0f}x the {rows[3][4]}/s peak with +/-10% jitter. The fix and the")
    print("  outage are the same feature; the jitter is the entire difference.")
    out["l4_hot"], out["l4_cold"], out["l4_new"] = l4_hot, l4_cold, l4_new
    out["l4_new_reqs"] = float(rows[0][6][N_BACKENDS])
    out["churn_spread"] = rows[1][1] / rows[1][2]
    out["churn_new"] = rows[1][3]
    out["l7_spread"] = l7_hot / l7_cold
    out["l7_new"] = rows[4][3]
    out["burst_nojit"], out["burst_jit"] = float(rows[2][4]), float(rows[3][4])
    out["age_new"], out["jit_new"] = rows[2][3], rows[3][3]
    out["l4_spread"] = l4_hot / l4_cold
    return out


# ---------------------------------------------------------------------------
# 2 · Detection latency vs flapping
# ---------------------------------------------------------------------------

class Checker:
    """One backend's active-health-check state machine, exactly as a balancer runs it."""

    def __init__(self, interval: float, timeout: float, unhealthy_th: int, healthy_th: int):
        self.interval = interval
        self.timeout = timeout
        self.unhealthy_th = unhealthy_th
        self.healthy_th = healthy_th
        self.healthy = True
        self.fails = 0
        self.oks = 0
        self.ejections = 0
        self.ejected_time = 0.0
        self._ejected_at = 0.0

    def probe(self, t: float, ok: bool) -> None:
        # A failing probe is only KNOWN to have failed once the timeout expires.
        decided = t + (0.0 if ok else self.timeout)
        if ok:
            self.fails = 0
            self.oks += 1
            if not self.healthy and self.oks >= self.healthy_th:
                self.healthy = True
                self.ejected_time += decided - self._ejected_at
        else:
            self.oks = 0
            self.fails += 1
            if self.healthy and self.fails >= self.unhealthy_th:
                self.healthy = False
                self.ejections += 1
                self._ejected_at = decided


CONFIGS = [
    # label, interval, timeout, unhealthy_threshold, healthy_threshold
    ("k8s readiness default   10s/1s   3 / 1", 10.0, 1.0, 3, 1),
    ("AWS ALB default         30s/5s   2 / 5", 30.0, 5.0, 2, 5),
    ("twitchy                  1s/1s   1 / 1", 1.0, 1.0, 1, 1),
    ("fast poll, same count    2s/1s   3 / 2", 2.0, 1.0, 3, 2),
    ("ASYMMETRIC               2s/1s   5 / 5", 2.0, 1.0, 5, 5),
]

JITTERY_P = 0.03      # 3% of probes to the jittery backend exceed the timeout
TRIALS_H = 300        # backend-hours simulated for the validation run
FLEET_M, FLEET_N = 6, 200   # M balancers, N backends — the probe-cost multiplier


def section2() -> Dict[str, float]:
    banner("2 · DETECTION LATENCY VS FLAPPING: TWO DIALS, NOT ONE")
    print("  Backend A dies hard at a uniformly random moment inside a probe interval")
    print("  (2,000 trials per config), so 'detect' is measured, not best-cased.")
    print(f"  Backend B is merely jittery: p={JITTERY_P:.2f} of its probes exceed the timeout — a periodic")
    print("  GC pause, a noisy neighbour, a log rotation. Nothing about it is broken.")
    print(f"  False ejections are exact: (probes/hr - k + 1) x p^k. Probe cost prices M={FLEET_M}")
    print(f"  balancers x N={FLEET_N} backends, every balancer probing every backend.")
    print()
    print("  config                                  detect     worst   false ej   re-add   probes/s")
    print("                                          mean       case    /hr        after    fleet-wide")
    out: Dict[str, float] = {}
    rows = []
    rng = random.Random(1234)
    for label, interval, timeout, uth, hth in CONFIGS:
        # (a) a genuinely dead backend: how long does the balancer keep routing to it?
        detects = []
        for _ in range(2000):
            offset = rng.random() * interval          # the failure starts mid-interval
            c = Checker(interval, timeout, uth, hth)
            t = 0.0
            while t < 10 * interval * (uth + 2):
                c.probe(t, ok=(t < offset))
                if not c.healthy:
                    detects.append(t + timeout - offset)
                    break
                t += interval
        mean_detect = sum(detects) / len(detects)
        worst = interval * (uth + 1) + timeout

        # (b) a jittery backend: how often is it ejected for nothing?
        probes_hr = 3600.0 / interval
        fe = max(0.0, probes_hr - uth + 1) * (JITTERY_P ** uth)
        # (c) once wrongly ejected, how long until it is trusted again?
        q = 1.0 - JITTERY_P
        readd = interval * (1.0 - q ** hth) / ((1.0 - q) * q ** hth)
        cost = FLEET_M * FLEET_N / interval
        print(f"  {label:<38s} {mean_detect:6.1f}s  {worst:6.1f}s {small(fe)}   {readd:5.1f}s   {cost:7.0f}")
        rows.append((label, mean_detect, worst, fe, readd, cost))

    # Validate the arithmetic in column 4 against a straight simulation.
    label, interval, timeout, uth, hth = CONFIGS[0]
    rng2 = random.Random(77)
    ejections = 0
    for _ in range(TRIALS_H):
        c = Checker(interval, timeout, uth, hth)
        t = 0.0
        while t < 3600.0:
            c.probe(t, ok=(rng2.random() >= JITTERY_P))
            t += interval
        ejections += c.ejections
    sim = ejections / TRIALS_H

    k8s, alb, twitchy, fast, asym = rows
    print()
    print(f"  Validation: {TRIALS_H} simulated backend-hours of the k8s default gave {ejections} false")
    print(f"  ejections = {sim:.4f}/hr; the arithmetic said {k8s[3]:.4f}/hr.")
    print()
    print(f"  Read row 1 as arithmetic, not a default: 10s interval x 3 consecutive failures")
    print(f"  + a 1s timeout is {k8s[2]:.0f}s worst case, {k8s[1]:.1f}s on average, of routing live traffic")
    print(f"  into a backend that is already dead. AWS's out-of-the-box target group is worse:")
    print(f"  {alb[1]:.1f}s mean, {alb[2]:.0f}s worst. Nobody chose those numbers; they are what you get.")
    print(f"  Turning the threshold down to 1 (row 3) detects in {twitchy[1]:.1f}s and costs {twitchy[3]:.1f} false")
    print(f"  ejections/hr/backend = {twitchy[3] * FLEET_N:.0f} spurious ejections an hour across 200 backends.")
    print()
    print(f"  The ASYMMETRIC row wins BOTH columns against every default above:")
    print(f"    detect  {asym[1]:.1f}s   vs {k8s[1]:.1f}s (k8s) and {alb[1]:.1f}s (ALB)  -> {k8s[1] / asym[1]:.1f}x faster")
    print(f"    false  {small(asym[3], 8).strip()}/hr vs {k8s[3]:.5f} and {alb[3]:.5f}      -> {k8s[3] / asym[3]:.0f}x fewer")
    print("  because interval and threshold are DIFFERENT dials. Detection time is linear in")
    print("  both (interval x threshold), but the false-ejection rate is p^threshold — exponential")
    print(f"  in the threshold and only linear in 1/interval. Shortening the interval 5x and")
    print(f"  raising the threshold from 3 to 5 buys {k8s[1] / asym[1]:.1f}x faster detection AND {k8s[3] / asym[3]:.0f}x fewer false")
    print(f"  ejections. The bill is probe traffic: {asym[5]:.0f}/s fleet-wide vs {k8s[5]:.0f}/s, the cheapest")
    print("  thing on this page.")
    print(f"  healthy_threshold is the asymmetry: a jittery host is re-added after {asym[4]:.1f}s at")
    print(f"  healthy_threshold=5 but {twitchy[4]:.1f}s at 1 — fail fast, recover slow, so a host that is")
    print("  genuinely marginal cannot flap back into rotation on one lucky probe.")
    out["k8s_detect"], out["k8s_worst"], out["k8s_fe"] = k8s[1], k8s[2], k8s[3]
    out["alb_detect"], out["alb_worst"], out["alb_fe"] = alb[1], alb[2], alb[3]
    out["tw_detect"], out["tw_fe"], out["tw_readd"] = twitchy[1], twitchy[3], twitchy[4]
    out["asym_detect"], out["asym_fe"], out["asym_readd"] = asym[1], asym[3], asym[4]
    out["asym_cost"], out["k8s_cost"] = asym[5], k8s[5]
    out["sim_fe"], out["sim_n"] = sim, float(ejections)
    return out


# ---------------------------------------------------------------------------
# 3 · A probe timeout below p99 guarantees false ejections
# ---------------------------------------------------------------------------

def section3() -> Dict[str, float]:
    banner("3 · A PROBE TIMEOUT BELOW YOUR p99 IS A SCHEDULED FALSE EJECTION")
    rng = random.Random(99)
    # Lognormal latency, tuned to p50 = 120 ms and p99 = 1400 ms.
    mu = math.log(0.120)
    sigma = math.log(1.400 / 0.120) / 2.3263
    lat = sorted(rng.lognormvariate(mu, sigma) for _ in range(200_000))
    p50, p90, p99, p999 = pct(lat, 0.50), pct(lat, 0.90), pct(lat, 0.99), pct(lat, 0.999)
    print(f"  A perfectly healthy backend, 200,000 sampled probe responses (lognormal):")
    print(f"    p50 {p50 * 1000:6.0f} ms   p90 {p90 * 1000:6.0f} ms   p99 {p99 * 1000:6.0f} ms   p99.9 {p999 * 1000:6.0f} ms")
    print(f"  Health checks at interval=2s, unhealthy_threshold=3 -> 1800 probes/hour/backend.")
    print()
    print("  probe     P(probe            expected false     ...across a 200-backend")
    print("  timeout   times out)         ejections/hr       fleet, per day")
    out: Dict[str, float] = {}
    per_hour = 3600.0 / 2.0
    rows = []
    for to in (0.5, 1.0, 1.5, 2.0, 3.0, 5.0):
        p = sum(1 for v in lat if v > to) / len(lat)
        ej = (per_hour - 2) * (p ** 3)
        fleet = ej * 200 * 24
        marker = ""
        if to < p99:
            marker = "  <- below p99"
        elif to > p999:
            marker = "  <- above p99.9"
        rows.append((to, p, ej, fleet))
        print(f"  {to * 1000:5.0f} ms   {p * 100:6.3f}%          {small(ej)}      {small(fleet, 10)}{marker}")

    # Confirm the 1.0 s row by direct simulation rather than arithmetic.
    to = 1.0
    rng2 = random.Random(4242)
    hours, ej = 600, 0
    for _ in range(hours):
        c = Checker(2.0, to, 3, 2)
        t = 0.0
        while t < 3600.0:
            c.probe(t, ok=(rng2.lognormvariate(mu, sigma) <= to))
            t += 2.0
        ej += c.ejections
    sim = ej / hours
    analytic = [r for r in rows if r[0] == 1.0][0]
    print()
    print(f"  Simulated {hours} backend-hours at a 1.0 s timeout: {ej} ejections = {sim:.3f}/hour")
    print(f"  (arithmetic said {analytic[2]:.3f}). Nothing was wrong with the backend in any of them.")
    print(f"  At a 1.0 s timeout, {analytic[1] * 100:.2f}% of probes to a HEALTHY backend fail, so three in a")
    print(f"  row happens {analytic[3]:.0f} times a day across 200 backends — and each one removes")
    print("  capacity from a fleet that was fine, which raises everyone else's utilization,")
    print("  which raises everyone else's latency. Section 4 is what happens next.")
    print(f"  Rule: probe timeout >= p99.9 of the probe path. Here that is {p999 * 1000:.0f} ms, so 3 s")
    print(f"  ({small(rows[4][3], 1).strip()} false ejections/fleet/day — one every {1 / max(rows[4][3], 1e-12):.0f} days) and never 1 s.")
    out["p50"], out["p99"], out["p999"] = p50, p99, p999
    out["p_1s"] = analytic[1]
    out["ej_1s"], out["fleet_1s"] = analytic[2], analytic[3]
    out["sim_1s"] = sim
    out["fleet_3s"] = [r for r in rows if r[0] == 3.0][0][3]
    out["fleet_05s"] = rows[0][3]
    return out


# ---------------------------------------------------------------------------
# 4 · The health-check death spiral, measured
# ---------------------------------------------------------------------------

FLEET = 20
PROBE_TIMEOUT = 0.400    # the probe fails if the instance answers slower than this
TICKS = 300
CALM_UNTIL = 30          # the fleet runs at 80% until here, then demand steps up
BASE_RHO, PEAK_RHO = 0.80, 0.92


def fleet_caps() -> List[float]:
    rng = random.Random(5)
    return [rng.uniform(88.0, 112.0) for _ in range(FLEET)]


DEADLINE = 1.0           # a caller waits this long; anything slower is wasted work


def spiral(guard: str, trace: bool = False) -> Tuple[float, float, List[int], int, int]:
    """Route a fixed offered load across a fleet whose health checks time out under load.

    Every instance has a real backlog. An instance removed from rotation does NOT
    become fast instantly — it has to drain what it already accepted first, which is
    the memory that turns a wobble into a spiral.

    guard: "none" | "panic50" | "maxeject10" | "both".
    Returns (served fraction, on-time fraction, healthy per tick, min healthy,
    ticks with nothing routed).
    """
    rng = random.Random(31)
    cap = fleet_caps()
    total_cap = sum(cap)
    backlog = [0.0] * FLEET
    checkers = [Checker(1.0, 0.0, 3, 5) for _ in range(FLEET)]
    served_sum, ontime_sum, offered_sum = 0.0, 0.0, 0.0
    healthy_trace: List[int] = []
    zero_ticks = 0

    for t in range(TICKS):
        offered = (BASE_RHO if t < CALM_UNTIL else PEAK_RHO) * total_cap
        healthy = [i for i in range(FLEET) if checkers[i].healthy]
        # --- guard 1: max_ejection_percent — the balancer refuses to eject more.
        if guard in ("maxeject10", "both"):
            keep = FLEET - int(FLEET * 0.10)
            if len(healthy) < keep:
                # least-recently-failing hosts are forced back into rotation
                ranked = sorted(range(FLEET),
                                key=lambda i: (not checkers[i].healthy, checkers[i].fails))
                healthy = sorted(ranked[:keep])
        # --- guard 2: panic mode — below the threshold, health status is ignored.
        routed, panic = healthy, False
        if guard in ("panic50", "both") and len(healthy) < 0.50 * FLEET:
            routed, panic = list(range(FLEET)), True

        share = offered / len(routed) if routed else 0.0
        served_tick, ontime_tick, arrived_tick = 0.0, 0.0, 0.0
        if not routed:
            # No backend is in rotation. The requests still arrive; they all get a 503.
            arrived_tick = float(poisson(rng, offered))
        for i in range(FLEET):
            arrivals = float(poisson(rng, share)) if i in routed else 0.0
            arrived_tick += arrivals
            wait = backlog[i] / cap[i]      # what a request arriving now must wait
            work = backlog[i] + arrivals
            done = min(cap[i], work)
            backlog[i] = work - done
            served_tick += done
            if wait <= DEADLINE:            # goodput: answers a caller is still waiting for
                ontime_tick += done
        served_sum += served_tick
        ontime_sum += ontime_tick
        offered_sum += arrived_tick
        healthy_trace.append(len(healthy))
        if not routed:
            zero_ticks += 1

        show = (t % 10 == 0) if t < CALM_UNTIL else (t % 2 == 0 if t < 52 else t % 6 == 0)
        if trace and show and t <= 96:
            flag = "  <-- PANIC: health ignored" if panic else ""
            if not routed:
                flag = "  <-- NOTHING HEALTHY: every request 503s"
            print(f"    {t:4d}    {len(healthy):3d}/{FLEET}   {len(routed):4d}   {share:7.1f}   "
                  f"{max(backlog):8.0f}   {100.0 * served_sum / offered_sum:5.1f}%  "
                  f"{100.0 * ontime_sum / offered_sum:5.1f}%{flag}")

        # Probe. The answer an instance gives is gated by the backlog in front of it.
        for i in range(FLEET):
            w = backlog[i] / cap[i]
            checkers[i].probe(float(t), ok=(w <= PROBE_TIMEOUT))

    return (served_sum / offered_sum, ontime_sum / offered_sum,
            healthy_trace, min(healthy_trace), zero_ticks)


def section4() -> Dict[str, float]:
    banner("4 · THE HEALTH-CHECK DEATH SPIRAL, MEASURED")
    cap = fleet_caps()
    total = sum(cap)
    print(f"  {FLEET} instances, {min(cap):.0f}-{max(cap):.0f} req/s each ({total:.0f} req/s total). Round-robin.")
    print(f"  Demand is {BASE_RHO * 100:.0f}% of fleet capacity ({BASE_RHO * total:.0f} req/s) until t={CALM_UNTIL}s,")
    print(f"  then steps up to {PEAK_RHO * 100:.0f}% ({PEAK_RHO * total:.0f} req/s). That is the entire trigger:")
    print(f"  a {(PEAK_RHO - BASE_RHO) * 100:.0f}-point step in demand on a fleet with {100 - PEAK_RHO * 100:.0f}% headroom left.")
    print(f"  Each instance keeps a real backlog; a probe fails if the backlog in front of it")
    print(f"  exceeds {PROBE_TIMEOUT * 1000:.0f} ms of drain time. Health check 1s / 3 fails out / 5 oks in.")
    print(f"  'on time' = completed while the wait in front of it was under the {DEADLINE:.0f}s caller")
    print("  deadline. Both percentages are cumulative from t=0.")
    print()
    print("  NO GUARD:")
    print("    tick  healthy  routed  req/inst    backlog   served   on time")
    frac_none, good_none, trace_none, min_none, zero_none = spiral("none", trace=True)
    print("     ...")
    print()
    out: Dict[str, float] = {}
    results = [("none (the out-of-the-box config)", frac_none, good_none, min_none, zero_none)]
    for guard, label in (("panic50", "panic mode @ 50% healthy"),
                         ("maxeject10", "max_ejection_percent = 10%"),
                         ("both", "panic 50% + max_ejection 10%")):
        f, g, tr, mn, z = spiral(guard)
        results.append((label, f, g, mn, z))
    print("  guard                              served   on time   min healthy   sec with")
    print("                                                                      nothing routed")
    for label, f, g, mn, z in results:
        print(f"  {label:<34s} {f * 100:5.1f}%    {g * 100:5.1f}%      {mn:3d}/{FLEET}          {z:4d}")
    print()
    zero_at = next((i for i, h in enumerate(trace_none) if h == 0), None)
    print(f"  With no guard the fleet ejected itself to ZERO healthy instances at t={zero_at}s —")
    print(f"  {zero_at - CALM_UNTIL}s after a {(PEAK_RHO - BASE_RHO) * 100:.0f}-point step in demand — and spent {zero_none}s of the run with")
    print("  nothing in rotation at all. Nothing crashed. No dependency broke. No deploy went")
    print("  out. The health check measured the queueing delay it was itself creating, removed")
    print("  an instance, and thereby raised every remaining instance's share of the same")
    print(f"  unchanged load. The fleet always had 100% of the capacity the {PEAK_RHO * 100:.0f}% demand needed.")
    print()
    print(f"  Delivered on time:  {good_none * 100:5.1f}% with no guard")
    print(f"                      {results[1][2] * 100:5.1f}% with panic mode alone      (+{(results[1][2] - good_none) * 100:.1f} points)")
    print(f"                      {results[2][2] * 100:5.1f}% with max_ejection alone     (+{(results[2][2] - good_none) * 100:.1f} points)")
    print(f"                      {results[3][2] * 100:5.1f}% with both                   (+{(results[3][2] - good_none) * 100:.1f} points)")
    print("  Neither guard adds a single request per second of capacity. They only stop the")
    print("  balancer from throwing capacity away, and that was the entire gap.")
    out["frac_none"], out["good_none"] = frac_none, good_none
    out["good_panic"], out["good_maxej"], out["good_both"] = results[1][2], results[2][2], results[3][2]
    out["frac_panic"], out["frac_maxej"], out["frac_both"] = results[1][1], results[2][1], results[3][1]
    out["zero_at"] = float(zero_at if zero_at is not None else -1)
    out["zero_ticks"] = float(zero_none)
    out["min_panic"], out["min_maxej"] = float(results[1][3]), float(results[2][3])
    out["trace_none"] = trace_none  # type: ignore[assignment]
    return out


# ---------------------------------------------------------------------------
# 5 · Passive outlier ejection: fast, free, and easy to get wrong
# ---------------------------------------------------------------------------

def section5() -> Dict[str, float]:
    banner("5 · PASSIVE OUTLIER EJECTION: THE 5xx YOUR PROBE NEVER SEES")
    out: Dict[str, float] = {}

    # (a) A backend whose /healthz is fine but whose real requests 500.
    rps = 500.0
    print(f"  A backend starts failing real requests at t=0. Its /healthz still returns 200 —")
    print(f"  it is a shallow check and does not touch the broken code path, so NO active health")
    print(f"  check will ever eject this host. Traffic to it: {rps:.0f} req/s.")
    print()
    print("  true error rate   consecutive_5xx=5 ejects after   errors served first")
    rng = random.Random(808)
    rows5a = []
    for err in (1.00, 0.80, 0.60, 0.40, 0.20):
        trials, tot_req, tot_err, never = 400, 0, 0, 0
        for _ in range(trials):
            run, n, errs = 0, 0, 0
            while run < 5 and n < 200_000:
                n += 1
                if rng.random() < err:
                    run += 1
                    errs += 1
                else:
                    run = 0
            if run < 5:
                never += 1
            tot_req += n
            tot_err += errs
        req = tot_req / trials
        errs = tot_err / trials
        print(f"       {err * 100:3.0f}%          {req:8.0f} req / {req / rps * 1000:8.1f} ms      {errs:8.0f}")
        rows5a.append((err, req, errs))
    print()
    print(f"  At a 100% error rate, passive detection ejects in {rows5a[0][1] / rps * 1000:.0f} ms after {rows5a[0][2]:.0f} bad responses —")
    print(f"  a detector no active probe can match, because the probe is testing a path that")
    print(f"  works. At a 20% error rate the same rule needs {rows5a[4][1]:.0f} requests — {rows5a[4][1] / rows5a[0][1]:.0f}x longer — and")
    print(f"  serves {rows5a[4][2]:.0f} users a 500 first, {rows5a[4][2] / rows5a[0][2]:.0f}x the damage. consecutive_5xx is a")
    print("  TOTAL-failure detector; it is nearly blind to the partial failure that is far")
    print("  more common.")
    print("  Partial failure is what the success-rate detector is for — and what part (c) shows")
    print("  goes wrong when you write that detector yourself.")
    print("  Passive detection is free and sees failures the probe path never touches. It also")
    print("  CANNOT see a backend receiving no traffic — exactly the starved backend from")
    print("  section 1. Active and passive fail in opposite directions. Run both.")
    out["p5a_full_req"], out["p5a_full_ms"] = rows5a[0][1], rows5a[0][1] / rps * 1000
    out["p5a_20_req"], out["p5a_20_err"] = rows5a[4][1], rows5a[4][2]

    # (b) Ejection backoff for a repeat offender.
    print()
    print("  Ejection backoff (Envoy: base_ejection_time x times-ejected, capped by max_ejection_time):")
    base, cap_s = 30.0, 300.0
    line, total = [], 0.0
    for n in range(1, 13):
        d = min(base * n, cap_s)
        total += d
        line.append(f"{d:.0f}")
    print(f"    ejection 1..12 -> {' '.join(line)} s   (total {total / 60:.0f} min out of rotation)")
    print(f"    A host that flaps 12 times is out for {total / 60:.0f} minutes, not {12 * base / 60:.0f}. The backoff is what")
    print("    stops a marginal host from being re-added every 30 s forever.")

    # (c) Small-sample noise: the reason minimum request volume exists.
    print()
    true_err = 0.01
    threshold = 0.10
    windows_per_hour = 360.0     # a 10 s evaluation interval
    print(f"  A rule everyone writes: 'eject if error rate > {threshold * 100:.0f}% in the evaluation window'.")
    print(f"  Every backend below has the SAME true error rate: {true_err * 100:.1f}%. None of them is broken.")
    print()
    print("  requests in     P(window looks       false ejections   ...per day across")
    print("  the window      >10% bad)           per hour          200 such backends")
    rows = []
    for vol in (5, 10, 20, 50, 100, 500):
        # Exact binomial tail: P(X > 0.10 n), X ~ Binomial(n, 0.01). No sampling noise.
        need = int(threshold * vol) + 1
        p = sum(math.comb(vol, k) * true_err ** k * (1 - true_err) ** (vol - k)
                for k in range(need, vol + 1))
        per_hr = p * windows_per_hour
        per_day = per_hr * 24 * 200
        flag = "  <- Envoy's default minimum" if vol == 100 else ""
        print(f"  {vol:8d}        {p * 100:8.4f}%       {small(per_hr)}      {small(per_day, 10)}{flag}")
        rows.append((vol, p, per_hr, per_day))
    lo, hi = rows[0], rows[4]
    print()
    print(f"  At {lo[0]} requests per window a single unlucky error reads as a {1 / lo[0] * 100:.0f}% error rate, so this")
    print(f"  perfectly healthy backend is ejected {lo[2]:.1f} times an hour — {lo[2] / hi[2]:.2e} times more often")
    print(f"  than the identical backend measured over {hi[0]} requests ({small(hi[2], 1).strip()}/hr). That is not health.")
    print("  It is sample size. This is why Envoy will not apply its success-rate rule until a")
    print("  host has served success_rate_request_volume (default 100) requests in the interval,")
    print("  and until success_rate_minimum_hosts (default 5) hosts qualify: below that, the rule")
    print("  is ejecting noise, and the quietest backend is always the most likely victim.")
    out["p_vol5"], out["hr_vol5"] = lo[1], lo[2]
    out["hr_vol100"], out["day_vol5"] = hi[2], lo[3]
    out["backoff_total_min"] = total / 60.0
    return out


def main() -> None:
    print("Layer 4 vs Layer 7, Health Checks & Outlier Ejection — Phase 11, Lesson 04")
    print("All numbers below are produced by this file. Seeded; rerunning reproduces them.")
    section1()
    section2()
    section3()
    section4()
    section5()
    print(f"\n  (total wall time {time.perf_counter() - WALL0:.1f} s)")


if __name__ == "__main__":
    main()
