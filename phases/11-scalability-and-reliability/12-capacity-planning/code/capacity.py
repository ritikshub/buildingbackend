#!/usr/bin/env python3
"""
Phase 11, Lesson 12 — Capacity Planning: Headroom, Peak & What to Actually Buy.
Companion to phases/11-scalability-and-reliability/12-capacity-planning/docs/en.md

Builds a real capacity model: a generated diurnal+weekly demand history, a measured
usable-throughput ceiling from an M/G/c queue, the composed headroom stack, the
(N-1)/N availability-zone arithmetic, Little's Law sizing, a trend+seasonality
forecast validated on held-out data, and cost per million requests per instance family.

Sources: J. D. C. Little, "A Proof for the Queuing Formula L = lambda W",
Operations Research 9(3), 1961; N. J. Gunther, *Guerrilla Capacity Planning*,
Springer 2007 (the Universal Scalability Law); F. Pollaczek (1930) and
A. Khinchine (1932) for the mean-wait relation used as the variability penalty.
"""

from __future__ import annotations

import heapq
import math
import random
import statistics
from collections import deque

# ------------------------------------------------------------------ constants

SEED = 7

# One instance, as it would come off a load test (Phase 8, Lesson 14).
WORKERS = 4  # request slots per instance = vCPUs on a 4-vCPU box
MEAN_SERVICE_S = 0.040  # 40 ms mean service time
MAX_PER_INSTANCE = WORKERS / MEAN_SERVICE_S  # 100 req/s — the saturation ceiling
P99_SLO_S = 0.320  # the latency objective: 8x mean service time
DEADLINE_S = 1.000  # client timeout; work older than this is shed at dequeue
CV2_STEADY = 1.0  # textbook exponential service (the M/M/c assumption)
CV2_VARIABLE = 2.0  # a real endpoint: cache hits, cache misses, variable result sets

# The business -> technical conversion. This is step 3 of the capacity model and
# the step teams skip; without it there is nothing to forecast.
DAILY_ACTIVES = 4_200_000
REQ_PER_ACTIVE_PER_DAY = 28.0

# Demand history.
DAYS = 126  # 18 weeks
BUCKETS_PER_DAY = 96  # 15-minute buckets
BUCKET_S = 86400 / BUCKETS_PER_DAY
FIT_DAYS = 84  # fit the forecast on the first 12 weeks
LEAD_TIME_DAYS = 42  # 6 weeks to get new capacity — the validation horizon
TRUE_GROWTH = 0.012  # the growth rate the history is generated with, per week
GROWTH_AFTER = 0.020  # the "trend breaks" scenario's growth after FIT_DAYS

# Headroom inputs.
AZS = 3  # availability zones
DEPLOY_SURGE = 0.25  # fraction of the fleet unavailable during a rolling deploy

# One-off demand events injected into the history (day, start hour, end hour, factor).
EVENTS = [
    (104, 19.0, 21.0, 1.55, "marketing push notification"),
    (117, 20.0, 23.5, 1.90, "live sports final"),
]


def banner(n: int, title: str) -> None:
    print(f"\n== {n} · {title} ==")


def num(x: float, w: int = 0, d: int = 0) -> str:
    """Thousands-separated fixed-width number."""
    return f"{x:>{w},.{d}f}"


# ------------------------------------------------- 0. the demand history

def _diurnal(hour: float) -> float:
    """Consumer web shape: a commute bump, a lunch bump, a big evening peak."""
    def g(mu: float, sd: float) -> float:
        return math.exp(-0.5 * ((hour - mu) / sd) ** 2)

    return 0.16 + 1.00 * g(20.6, 2.3) + 0.52 * g(13.0, 2.4) + 0.22 * g(8.2, 1.4)


_DIURNAL_MEAN = statistics.fmean(
    _diurnal(b * 24.0 / BUCKETS_PER_DAY) for b in range(BUCKETS_PER_DAY)
)

_DOW = [0.97, 0.99, 1.00, 1.02, 1.06, 1.14, 1.10]  # Mon..Sun, consumer weekend lift
_DOW_MEAN = statistics.fmean(_DOW)


def generate_history(weekly_growth: float, break_at: int | None = None,
                     growth_after: float = 0.0, with_events: bool = True
                     ) -> tuple[list[float], list[bool]]:
    """Return (req/s per 15-min bucket, is_event_bucket) for DAYS days.

    Mean demand is pinned to the business math: DAILY_ACTIVES users each making
    REQ_PER_ACTIVE_PER_DAY requests. Everything else is shape.
    """
    rng = random.Random(SEED)
    base = DAILY_ACTIVES * REQ_PER_ACTIVE_PER_DAY / 86400.0
    series: list[float] = []
    events: list[bool] = []
    for day in range(DAYS):
        day_noise = math.exp(rng.gauss(0.0, 0.030))
        if break_at is not None and day >= break_at:
            g = ((1 + weekly_growth) ** (break_at / 7.0)) * (
                (1 + growth_after) ** ((day - break_at) / 7.0))
        else:
            g = (1 + weekly_growth) ** (day / 7.0)
        dow = _DOW[day % 7] / _DOW_MEAN
        for b in range(BUCKETS_PER_DAY):
            hour = b * 24.0 / BUCKETS_PER_DAY
            shape = _diurnal(hour) / _DIURNAL_MEAN
            bucket_noise = math.exp(rng.gauss(0.0, 0.045))
            lam = base * shape * dow * g * day_noise * bucket_noise
            is_event = False
            if with_events:
                for e_day, h0, h1, factor, _label in EVENTS:
                    if day == e_day and h0 <= hour < h1:
                        lam *= factor
                        is_event = True
            series.append(lam)
            events.append(is_event)
    return series, events


# ------------------------------------------------- queueing simulator

def _sampler(mean_s: float, cv2: float, rng: random.Random):
    """Lognormal service times with the requested mean and squared CV.

    Lognormal because that is the shape real request handlers have: a body of
    fast responses and a multiplicative tail from cache misses, retries inside
    the handler and result sets of varying size.
    """
    if cv2 < 1e-9:
        return lambda: mean_s
    s2 = math.log(1.0 + cv2)
    mu = math.log(mean_s) - s2 / 2.0
    sd = math.sqrt(s2)
    return lambda: math.exp(rng.gauss(mu, sd))


def sim_latency(lam: float, cv2: float, n_req: int, seed: int,
                workers: int = WORKERS, mean_s: float = MEAN_SERVICE_S
                ) -> tuple[float, float, float]:
    """Exact FIFO M/G/c with an unbounded queue. Returns (mean, p50, p99) seconds."""
    rng = random.Random(seed)
    svc = _sampler(mean_s, cv2, rng)
    free = [0.0] * workers
    heapq.heapify(free)
    t = 0.0
    lat: list[float] = []
    warm = n_req // 10
    for i in range(n_req):
        t += rng.expovariate(lam)
        start = t if free[0] < t else free[0]
        finish = start + svc()
        heapq.heapreplace(free, finish)
        if i >= warm:
            lat.append(finish - t)
    lat.sort()
    return (statistics.fmean(lat),
            lat[len(lat) // 2],
            lat[min(len(lat) - 1, int(0.99 * len(lat)))])


def sim_shedding(lam: float, cv2: float, n_req: int, seed: int, queue_cap: int,
                 workers: int = WORKERS, mean_s: float = MEAN_SERVICE_S
                 ) -> tuple[float, float, float]:
    """M/G/c with a bounded queue and a dequeue-time deadline check.

    Returns (served_fraction, p99_of_served_seconds, late_fraction).
    """
    rng = random.Random(seed)
    svc = _sampler(mean_s, cv2, rng)
    dep: list[tuple[float, float]] = []  # (finish, arrival)
    wait: deque[float] = deque()
    busy = 0
    now = 0.0
    nxt = rng.expovariate(lam)
    horizon = n_req / lam
    offered = served = shed = late = 0
    lat: list[float] = []
    while True:
        t_dep = dep[0][0] if dep else math.inf
        t_arr = nxt if nxt < horizon else math.inf
        if math.isinf(t_dep) and math.isinf(t_arr):
            break
        if t_dep <= t_arr:
            now = t_dep
            _, arrived = heapq.heappop(dep)
            busy -= 1
            served += 1
            w = now - arrived
            lat.append(w)
            if w > DEADLINE_S:
                late += 1
            while wait:
                a = wait.popleft()
                if now - a > DEADLINE_S:
                    shed += 1  # expired before a worker was free: drop it free
                    continue
                busy += 1
                heapq.heappush(dep, (now + svc(), a))
                break
        else:
            now = t_arr
            nxt = now + rng.expovariate(lam)
            offered += 1
            if busy < workers:
                busy += 1
                heapq.heappush(dep, (now + svc(), now))
            elif len(wait) < queue_cap:
                wait.append(now)
            else:
                shed += 1
    lat.sort()
    p99 = lat[min(len(lat) - 1, int(0.99 * len(lat)))] if lat else 0.0
    return (served / offered if offered else 0.0, p99,
            late / served if served else 0.0)


SWEEP_N = 60_000  # requests per sweep point; the p99 estimate needs the samples
_SWEEP: dict[tuple[float, int], tuple[float, float]] = {}


def sweep_point(cv2: float, rho: float) -> tuple[float, float]:
    """(p50, p99) at this utilization, memoised so the printed table and the
    knee search are guaranteed to be the same measurement, not two noisy ones."""
    key = (cv2, round(rho * 100))
    if key not in _SWEEP:
        _, p50, p99 = sim_latency(max(rho, 1e-4) * MAX_PER_INSTANCE, cv2,
                                  SWEEP_N, SEED + 3)
        _SWEEP[key] = (p50, p99)
    return _SWEEP[key]


def safe_utilization(cv2: float) -> tuple[float, float]:
    """Largest rho whose measured p99 still meets the SLO. Returns (rho, p99_there)."""
    best_rho, best_p99 = 0.30, 0.0
    for step in range(30, 95):
        rho = step / 100.0
        _, p99 = sweep_point(cv2, rho)
        if p99 <= P99_SLO_S:
            best_rho, best_p99 = rho, p99
    return best_rho, best_p99


# =================================================================== 1

def section1(series: list[float], events: list[bool]) -> dict:
    banner(1, "PEAK, NOT AVERAGE — WHAT THE DASHBOARD AVERAGE HIDES")
    window = 28 * BUCKETS_PER_DAY
    recent = series[-window:]
    recent_ev = events[-window:]
    routine = [v for v, e in zip(recent, recent_ev) if not e]

    avg = statistics.fmean(recent)
    srt = sorted(routine)
    p95 = srt[int(0.95 * len(srt))]
    peak_routine = srt[-1]
    peak_all = max(recent)

    print(f"  business input : {DAILY_ACTIVES:,} daily actives"
          f" × {REQ_PER_ACTIVE_PER_DAY:.0f} requests each")
    print(f"  =              : {DAILY_ACTIVES * REQ_PER_ACTIVE_PER_DAY / 1e6:,.1f}M"
          f" requests/day = {avg:,.0f} req/s on average")
    print(f"  history        : {DAYS} days at {BUCKETS_PER_DAY} buckets/day"
          f" (last 28 shown); one instance"
          f" sustains {MAX_PER_INSTANCE:.0f} req/s")
    print()
    print("  provision to        req/s    x avg   instances (at the measured maximum)")
    rows = [("weekly average", avg), ("p95 bucket", p95),
            ("routine peak", peak_routine), ("peak incl. events", peak_all)]
    for label, v in rows:
        print(f"  {label:<18}{num(v, 7)}    {v / avg:5.2f}x"
              f"        {math.ceil(v / MAX_PER_INSTANCE):>4}")
    print()
    print(f"  peak-to-average ratio (routine) = {peak_routine / avg:.2f}x —"
          f" provisioning to the average")
    print(f"  buys"
          f" {math.ceil(peak_routine / MAX_PER_INSTANCE) - math.ceil(avg / MAX_PER_INSTANCE)}"
          f" too few instances, and the shortfall lands every single evening.")
    for e_day, h0, h1, factor, label in EVENTS:
        print(f"  event: day {e_day} {h0:04.1f}-{h1:04.1f}h  ×{factor:.2f}"
              f"  {label}")
    print(f"  the events push the worst bucket to {peak_all / avg:.2f}x average"
          f" — {math.ceil(peak_all / MAX_PER_INSTANCE)} instances for"
          f" {sum(1 for e in recent_ev if e) * BUCKET_S / 3600:.1f} hours of the month.")
    print("  that is a scheduled pre-scale, not standing capacity (see section 6).")
    return {"avg": avg, "p95": p95, "peak": peak_routine, "peak_all": peak_all,
            "recent": recent}


# =================================================================== 2

def section2() -> dict:
    banner(2, "THE KNEE, NOT 100% — USABLE CAPACITY IS NOT MEASURED MAXIMUM")
    print(f"  one instance: {WORKERS} workers × {MEAN_SERVICE_S * 1000:.0f} ms"
          f" mean service = {MAX_PER_INSTANCE:.0f} req/s saturation ceiling")
    print(f"  latency objective: p99 ≤ {P99_SLO_S * 1000:.0f} ms"
          f" ({P99_SLO_S / MEAN_SERVICE_S:.0f}× service time)")
    print()
    print("      rho    req/s |  textbook (CV^2=1)        |  measured shape (CV^2=2)")
    print("                   |    p50      p99   meets?  |    p50      p99   meets?")
    rho_steady, p99_steady = safe_utilization(CV2_STEADY)
    rho_var, p99_var = safe_utilization(CV2_VARIABLE)
    for rho in sorted({0.001, 0.50, 0.60, 0.70, rho_var, 0.75, 0.80,
                       rho_steady, 0.85, 0.90}):
        lam = rho * MAX_PER_INSTANCE
        cells = []
        for cv2 in (CV2_STEADY, CV2_VARIABLE):
            p50, p99 = sweep_point(cv2, rho)
            ok = "yes" if p99 <= P99_SLO_S else "NO "
            cells.append(f"{p50 * 1000:7.1f}ms {p99 * 1000:6.1f}ms   {ok}")
        tag = "  ~0 " if rho < 0.01 else f"{rho:4.2f}"
        mark = ""
        if abs(rho - rho_var) < 1e-9:
            mark = "  <- knee, measured shape"
        elif abs(rho - rho_steady) < 1e-9:
            mark = "  <- knee, textbook"
        print(f"     {tag}   {lam:6.0f} | {cells[0]} | {cells[1]}{mark}")
    print()
    for name, rho, p99 in ((f"textbook (CV^2={CV2_STEADY:.0f})", rho_steady, p99_steady),
                           (f"measured (CV^2={CV2_VARIABLE:.0f})", rho_var, p99_var)):
        usable = rho * MAX_PER_INSTANCE
        print(f"  {name}: max {MAX_PER_INSTANCE:.0f} req/s,"
              f" usable {usable:5.0f} req/s at p99 {p99 * 1000:5.1f} ms"
              f" → fraction {rho:.2f}")
    print(f"  variability alone costs"
          f" {(rho_steady - rho_var) * MAX_PER_INSTANCE:.0f} req/s per instance"
          f" ({(1 - rho_var / rho_steady) * 100:.0f}% of usable")
    print("  capacity), with no change whatsoever in the mean service time.")
    print(f"  every number after this uses rho_safe = {rho_var:.2f}, the measured shape,"
          f" not the textbook one.")
    print(f"  planning to the measured maximum would over-state each instance by"
          f" {MAX_PER_INSTANCE / (rho_var * MAX_PER_INSTANCE):.2f}x.")
    return {"rho_safe": rho_var, "rho_textbook": rho_steady,
            "usable": rho_var * MAX_PER_INSTANCE}


# =================================================================== 3

def section3(peak: float, rho_safe: float, forecast_factor: float) -> dict:
    banner(3, "THE HEADROOM STACK — WHERE EVERY MACHINE ACTUALLY GOES")
    print(f"  required throughput at the routine peak: {peak:,.0f} req/s")
    print()
    print("  step                          per-instance   instances   x naive    util at")
    print("                                  budget r/s                        routine peak")
    steps = []
    budget = MAX_PER_INSTANCE
    n_naive = math.ceil(peak / budget)
    steps.append(("0  naive: measured maximum", budget, n_naive, peak))

    budget = MAX_PER_INSTANCE * rho_safe
    steps.append((f"1  + latency knee (rho≤{rho_safe:.2f})", budget,
                  math.ceil(peak / budget), peak))

    surv = (AZS - 1) / AZS
    budget = MAX_PER_INSTANCE * rho_safe * surv
    steps.append((f"2  + survive 1 of {AZS} AZs", budget,
                  math.ceil(peak / budget), peak))

    budget = MAX_PER_INSTANCE * rho_safe * surv * (1 - DEPLOY_SURGE)
    steps.append((f"3  + deploy surge ({DEPLOY_SURGE:.0%})", budget,
                  math.ceil(peak / budget), peak))

    demand = peak * forecast_factor
    steps.append((f"4  + forecast p90 (×{forecast_factor:.2f})", budget,
                  math.ceil(demand / budget), demand))

    for label, b, n, _d in steps:
        print(f"  {label:<30}{b:9.1f}     {n:>7}   {n / n_naive:6.2f}x"
              f"      {peak / (n * MAX_PER_INSTANCE) * 100:5.1f}%")

    final = steps[-1][2]
    balanced = math.ceil(final / AZS) * AZS
    print(f"  {'5  + balance across ' + str(AZS) + ' AZs':<30}{'—':>9}"
          f"     {balanced:>7}   {balanced / n_naive:6.2f}x"
          f"      {peak / (balanced * MAX_PER_INSTANCE) * 100:5.1f}%")
    print()
    print(f"  total: {balanced} instances where naive sizing said {n_naive}"
          f" — a {balanced / n_naive:.2f}× multiplier.")
    print(f"  steady-state utilization at the routine peak:"
          f" {peak / (balanced * MAX_PER_INSTANCE) * 100:.1f}%.")
    print(f"  that is the number the budget review objects to, and every point of it"
          f" is spoken for.")
    either = math.ceil(peak * forecast_factor
                       / (MAX_PER_INSTANCE * rho_safe
                          * min(surv, 1 - DEPLOY_SURGE)))
    print(f"  honest caveat: steps 2 and 3 are multiplied here. Taking max() instead"
          f" of the product")
    print(f"  gives {either} instances and saves {balanced - either} machines —"
          f" it is a bet that an AZ never fails")
    print(f"  during a deploy. Deploys are when instances die, so the two events are"
          f" not independent.")
    return {"fleet": balanced, "naive": n_naive,
            "knee_only": math.ceil(peak / (MAX_PER_INSTANCE * rho_safe))}


# =================================================================== 4

def section4(peak: float, rho_safe: float, fleets: dict) -> None:
    banner(4, "THE AZ ARITHMETIC — AND WHAT AN AZ LOSS DOES AT PEAK")
    print("   AZs   max steady util   provisioning x   combined target with the knee")
    for n in range(2, 7):
        surv = (n - 1) / n
        print(f"   {n:>3}          {surv * 100:5.1f}%           {1 / surv:5.2f}x"
              f"                {rho_safe * surv * 100:5.1f}%")
    print(f"  with a latency-safe rho of {rho_safe:.2f} and {AZS} AZs, the steady-state"
          f" target is {rho_safe:.2f} × {(AZS - 1) / AZS:.2f} ="
          f" {rho_safe * (AZS - 1) / AZS * 100:.0f}%.")
    print("  a correctly sized fleet is SUPPOSED to look half idle.")
    print()
    print(f"  now lose one of {AZS} AZs at the {peak:,.0f} req/s routine peak.")
    print("  clients retry up to 3x, so shedding feeds back into offered load.")
    print()
    print("  fleet sizing                  N   left   offered x   per inst   served"
          "   p99(ok)   users OK")
    cases = [
        ("sized by the model", fleets["fleet"]),
        ("cut to the knee at peak", fleets["knee_only"]),
        ("sized to the average", math.ceil(
            fleets["avg_demand"] / (MAX_PER_INSTANCE * rho_safe))),
    ]
    for label, n in cases:
        left = n - math.ceil(n / AZS)  # lose the largest zone
        capacity = left * MAX_PER_INSTANCE
        offered = peak
        for _ in range(200):
            # Retry echo: with up to 3 attempts and a per-attempt failure rate f,
            # each real request is offered 1 + f + f^2 times. Solve the fixed point.
            f = max(0.0, 1.0 - capacity / offered)
            offered = peak * (1.0 + f + f * f)
        per_inst = offered / left
        served, p99, _ = sim_shedding(per_inst, CV2_VARIABLE, 30_000, SEED + 5,
                                      queue_cap=WORKERS * 4)
        user_ok = 1.0 - (1.0 - served) ** 3
        print(f"  {label:<26}{n:>4}   {left:>4}     {offered / peak:7.2f}x"
              f"   {per_inst:8.0f}    {served * 100:5.1f}%"
              f"   {p99 * 1000:6.1f}ms     {user_ok * 100:5.1f}%")
    print("  'served' is per ATTEMPT — it is your error rate. 'users OK' assumes 3 tries,")
    print("  and those extra tries are exactly what inflated 'offered x' in the first place")
    print("  (Phase 8 Lesson 11's retry storm, now with 3 AZs' worth of clients in it).")
    print("  every retried user also paid a full 1.0 s client timeout before trying again.")


# =================================================================== 5

def section5(peak: float, rho_safe: float, forecast_factor: float,
             fleets: dict) -> None:
    banner(5, "LITTLE'S LAW AS THE SIZING TOOL — L = lambda × W")
    mean_w, _, _ = sim_latency(rho_safe * MAX_PER_INSTANCE, CV2_VARIABLE,
                               25_000, SEED + 7)
    print(f"  lambda = {peak:,.0f} req/s (routine peak)")
    print(f"  W      = {mean_w * 1000:.1f} ms measured mean latency at rho={rho_safe:.2f}"
          f" (service {MEAN_SERVICE_S * 1000:.0f} ms + queueing)")
    print(f"  L      = lambda × W = {peak * mean_w:,.1f} requests in the system"
          f" at any instant")
    print()
    print("  turning concurrency into machines:")
    sized = []
    for regress_ms in (0.0, 20.0):
        s = MEAN_SERVICE_S + regress_ms / 1000.0
        busy_workers = peak * s  # Little's Law on the SERVICE stage only
        per_inst = WORKERS * rho_safe
        n = math.ceil(busy_workers / per_inst)
        stack = math.ceil(peak * forecast_factor
                          / (MAX_PER_INSTANCE * rho_safe * ((AZS - 1) / AZS)
                             * (1 - DEPLOY_SURGE) * (MEAN_SERVICE_S / s)))
        stack = math.ceil(stack / AZS) * AZS
        sized.append((n, stack))
        tag = "baseline" if regress_ms == 0 else f"+{regress_ms:.0f} ms regression"
        print(f"  {tag:<24} S={s * 1000:5.1f} ms"
              f"   busy workers = {peak:,.0f} × {s:.3f} = {busy_workers:6.1f}")
        print(f"  {'':<24} at {rho_safe:.2f} × {WORKERS} = {per_inst:.1f}"
              f" usable/instance → {n} bare, {stack} with headroom")
    (n1, st1), (n2, st2) = sized
    print()
    print(f"  a 20 ms regression costs"
          f" {(n2 / n1 - 1) * 100:.0f}% of the fleet: {n1} → {n2} instances bare")
    print(f"  (+{n2 - n1}), {st1} → {st2} with the full headroom stack (+{st2 - st1}).")
    print(f"  nothing alerts: p99 is still inside the {P99_SLO_S * 1000:.0f} ms SLO"
          f" and the error rate is zero.")
    print(f"  the invoice notices first. Cross-check: Little's Law says {n1}"
          f" instances and the knee-only")
    print(f"  row of section 3 said {fleets['knee_only']}."
          f" Two independent derivations, one number.")


# =================================================================== 6

def _fit_trend_dow(peaks: list[float]) -> tuple[float, float, list[float], float]:
    """OLS on log(daily peak): level + linear trend, then day-of-week residual means."""
    n = len(peaks)
    xs = list(range(n))
    ys = [math.log(v) for v in peaks]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sxy / sxx
    a = my - b * mx
    resid = [y - (a + b * x) for x, y in zip(xs, ys)]
    dow = [statistics.fmean([resid[i] for i in range(n) if i % 7 == d])
           for d in range(7)]
    resid2 = [resid[i] - dow[i % 7] for i in range(n)]
    sigma = statistics.pstdev(resid2)
    return a, b, dow, sigma


def _daily_peaks(series: list[float], evmask: list[bool]) -> list[float]:
    """Peak req/s per day, with known one-off event buckets excluded."""
    out = []
    for d in range(DAYS):
        lo, hi = d * BUCKETS_PER_DAY, (d + 1) * BUCKETS_PER_DAY
        out.append(max(v for v, e in zip(series[lo:hi], evmask[lo:hi]) if not e))
    return out


def forecast_factor(flat: list[float], evmask: list[bool]) -> float:
    """The p90/p50 ratio of the fitted forecast — a headroom multiplier."""
    _, _, _, sigma = _fit_trend_dow(_daily_peaks(flat, evmask)[:FIT_DAYS])
    return math.exp(1.2816 * sigma)


def section6(flat: list[float], broken: list[float], evmask: list[bool]) -> float:
    banner(6, "FORECASTING HONESTLY — FORECAST ERROR IS A HEADROOM INPUT")

    peaks_flat = _daily_peaks(flat, evmask)
    peaks_break = _daily_peaks(broken, evmask)

    a, b, dow, sigma = _fit_trend_dow(peaks_flat[:FIT_DAYS])
    weekly = (math.exp(b * 7) - 1) * 100
    z90 = 1.2816
    print(f"  fit on days 0-{FIT_DAYS - 1} (known one-off events excluded from the fit),")
    print(f"  validated on days {FIT_DAYS}-{DAYS - 1} — a {LEAD_TIME_DAYS}-day"
          f" (6-week) capacity lead time.")
    print(f"  trend      : {weekly:+.2f}% per week recovered"
          f" (the series was generated at {TRUE_GROWTH * 100:+.2f}%)")
    print(f"  seasonality: Mon..Sun"
          + "".join(f" {math.exp(d) * 100 - 100:+5.1f}%" for d in dow))
    print(f"  residual sd: {sigma * 100:.1f}%  → p90/p50 forecast ratio ="
          f" {math.exp(z90 * sigma):.3f}")
    print()
    print("  scenario      horizon        p50 fcst  p90 fcst |  days short of  days short of"
          "   worst")
    print("                                  req/s     req/s |   the p50 buy    the p90 buy"
          "     miss")
    shortfalls: dict[tuple[str, int], tuple[float, float]] = {}
    for label, act_peaks in (("trend holds", peaks_flat),
                             ("trend breaks", peaks_break)):
        for h_lo, h_hi, rng_lbl in (
                (FIT_DAYS, FIT_DAYS + 21, f"days {FIT_DAYS}-{FIT_DAYS + 20}"),
                (FIT_DAYS + 21, DAYS, f"days {FIT_DAYS + 21}-{DAYS - 1}")):
            p50s = [math.exp(a + b * d + dow[d % 7]) for d in range(h_lo, h_hi)]
            p90s = [p * math.exp(z90 * sigma) for p in p50s]
            act = act_peaks[h_lo:h_hi]
            s50 = sum(1 for x, c in zip(act, p50s) if x > c) / len(act)
            s90 = sum(1 for x, c in zip(act, p90s) if x > c) / len(act)
            worst = max(x / c for x, c in zip(act, p90s))
            shortfalls[(label, h_lo)] = (s50, s90)
            print(f"  {label:<14}{rng_lbl:<15}{statistics.fmean(p50s):8.0f}"
                  f"  {statistics.fmean(p90s):8.0f} |    {s50 * 100:5.1f}%"
                  f"         {s90 * 100:5.1f}%        {worst:5.2f}x")
    factor = math.exp(z90 * sigma)
    print()
    print(f"  read the first two rows: even with the trend holding exactly, the p50 buy is"
          f" short on")
    print(f"  {shortfalls[('trend holds', FIT_DAYS)][0] * 100:.0f}% of days in both"
          f" halves of the horizon. It is a coin flip by construction,")
    print(f"  and the fitted trend adds its own error on top ({weekly:+.2f}%/wk"
          f" recovered vs {TRUE_GROWTH * 100:+.2f}%/wk true,")
    print(f"  from an {FIT_DAYS}-day window).")
    print(f"  the last two rows are the same forecast against demand whose growth rose to"
          f" {GROWTH_AFTER * 100:+.1f}%/wk")
    print(f"  on day {FIT_DAYS}: the p50 buy is short"
          f" {shortfalls[('trend breaks', FIT_DAYS + 21)][0] * 100:.0f}% of the far"
          f" horizon and even the p90 buy fails"
          f" {shortfalls[('trend breaks', FIT_DAYS + 21)][1] * 100:.0f}%.")
    print(f"  the p90 buy costs {(factor - 1) * 100:.1f}% more capacity — that is the"
          f" forecast-error term in the")
    print(f"  headroom stack, and it is the cheapest term in it. Buying it is not"
          f" pessimism, it is pricing.")
    print(f"  lead time is what makes this binding: with {LEAD_TIME_DAYS} days between"
          f" 'we need capacity' and")
    print(f"  'capacity exists', your forecast horizon must exceed {LEAD_TIME_DAYS} days"
          f" or the forecast is decorative.")
    print("  cloud elasticity shortens that lead time to minutes for on-demand instances")
    print("  and changes nothing for quota increases, reserved terms or scarce hardware.")
    return factor


# =================================================================== 7

def _usl(n: float, sigma: float = 0.02, kappa: float = 0.0004) -> float:
    """Universal Scalability Law relative capacity of n workers (Lesson 02)."""
    return n / (1 + sigma * (n - 1) + kappa * n * (n - 1))


PLATFORM_TAX = 0.55  # USL units per instance consumed by the runtime + agents


def section7(peak: float, rho_safe: float, forecast_factor: float,
             monthly_requests: float) -> None:
    banner(7, "UNIT ECONOMICS — WHAT TO ACTUALLY BUY")
    unit = MAX_PER_INSTANCE / (_usl(WORKERS) - PLATFORM_TAX)
    print(f"  price: $0.0425 per vCPU-hour on demand; 1 worker = 1 vCPU."
          f"  730 hours/month.")
    print(f"  capacity per instance is USL-derated (Lesson 02, sigma=0.02,"
          f" kappa=0.0004) and pays a")
    print(f"  fixed {PLATFORM_TAX} vCPU platform tax for the runtime, log shipper"
          f" and mesh sidecar.")
    print()
    print("  family   vCPU    max r/s   safe r/s   inst   $/month    $/M req"
          "   $/user/mo   AZ-safe")
    best = None
    for vcpu in (2, 4, 8, 16, 32):
        cap = max(0.1, _usl(vcpu) - PLATFORM_TAX) * unit
        safe = cap * rho_safe
        need = math.ceil(peak * forecast_factor
                         / (safe * ((AZS - 1) / AZS) * (1 - DEPLOY_SURGE)))
        need = math.ceil(need / AZS) * AZS
        cost = need * vcpu * 0.0425 * 730
        per_m = cost / (monthly_requests / 1e6)
        per_user = cost / DAILY_ACTIVES
        left = need - need // AZS
        az_ok = "yes" if peak <= left * safe else "NO"
        print(f"  c-{vcpu:<5}{vcpu:>4}   {cap:8.1f}   {safe:8.1f}   {need:>4}"
              f"   {cost:8,.0f}   {per_m:7.3f}    {per_user:8.4f}     {az_ok:>3}")
        if az_ok == "yes" and (best is None or cost < best[1]):
            best = (vcpu, cost, need, per_m)
    print()
    v, cost, need, per_m = best
    print(f"  cheapest family that meets the p99 SLO and survives an AZ loss:"
          f" c-{v} × {need} = ${cost:,.0f}/month")
    print("  the 32-vCPU box is not cheaper per request: USL coherency loss outruns")
    print("  the platform tax it saves, and it makes your AZ rounding coarser too.")
    print()
    for label, mult, note in (
            ("on demand", 1.00, "no commitment"),
            ("1-yr savings plan", 0.62, "commitment = a capacity forecast you signed"),
            ("3-yr savings plan", 0.44, "cheaper than any code change you will ship"),
    ):
        print(f"  {label:<20}${cost * mult:9,.0f}/mo"
              f"   ${per_m * mult:6.3f}/M req   {note}")
    spot_share = 0.30
    blended = cost * ((1 - spot_share) + spot_share * 0.35)
    left_after_az = need - math.ceil(need / AZS)
    left_after_both = math.floor(left_after_az * (1 - spot_share))
    safe_here = max(0.1, _usl(v) - PLATFORM_TAX) * unit * rho_safe
    margin = left_after_both * safe_here / peak - 1.0
    print(f"  {f'{spot_share:.0%} spot':<20}${blended:9,.0f}/mo"
          f"   ${per_m * blended / cost:6.3f}/M req"
          f"   saves ${cost - blended:,.0f}/mo")
    print(f"  but count the domains: AZ loss leaves {left_after_az} instances;"
          f" AZ loss WHILE spot is being")
    print(f"  reclaimed leaves {left_after_both}, which carries"
          f" {left_after_both * safe_here:,.0f} req/s against a {peak:,.0f} req/s peak"
          f" — a {margin * 100:+.1f}% margin.")
    print("  spot reclamation is a CORRELATED failure: one capacity pool, one price")
    print("  signal, every instance in it leaves inside the same two minutes. It is a")
    print("  failure domain that happens to be cheap, not a discount on the fleet you have.")
    print()
    print(f"  the unit that makes this legible to people who do not read latency graphs:")
    print(f"    ${per_m:.3f} per million requests ·"
          f" ${cost / DAILY_ACTIVES:.4f} per active user per month")
    print(f"  a change that adds 20 ms of p50 (section 5) raises that to"
          f" ${per_m * (MEAN_SERVICE_S + 0.020) / MEAN_SERVICE_S:.3f}/M req — a"
          f" {(0.020 / MEAN_SERVICE_S) * 100:.0f}% cost regression,")
    print(f"  which is ${cost * (0.020 / MEAN_SERVICE_S) * 12:,.0f} a year for a"
          f" diff that passed code review.")


# =================================================================== main

def main() -> None:
    flat, events = generate_history(TRUE_GROWTH)
    broken, _ = generate_history(TRUE_GROWTH, break_at=FIT_DAYS,
                                 growth_after=GROWTH_AFTER)

    factor = forecast_factor(flat, events)

    s1 = section1(flat, events)
    s2 = section2()
    s3 = section3(s1["peak"], s2["rho_safe"], factor)
    s3["avg_demand"] = s1["avg"]
    section4(s1["peak"], s2["rho_safe"], s3)
    section5(s1["peak"], s2["rho_safe"], factor, s3)
    section6(flat, broken, events)
    monthly = statistics.fmean(s1["recent"]) * 86400 * 30
    section7(s1["peak"], s2["rho_safe"], factor, monthly)


if __name__ == "__main__":
    main()
