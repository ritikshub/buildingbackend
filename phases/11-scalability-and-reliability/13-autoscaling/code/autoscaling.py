#!/usr/bin/env python3
"""
Phase 11, Lesson 13 - Autoscaling: Control Loops That Don't Oscillate.
Companion to ../docs/en.md. Standard library only, seeded (random.Random(7)), exits 0.

An autoscaler is a feedback control loop. This file simulates one with dead time as an
explicit knob and measures every pathology the lesson claims. Sources:
K. J. Astrom & R. M. Murray, "Feedback Systems", Princeton 2008, ch. 10 (dead time, phase
margin, the period-2*D limit cycle); N. J. Gunther, "Guerrilla Capacity Planning", Springer
2007 (the Universal Scalability Law used for database connection contention);
N. Bronson et al., "Metastable Failures in Distributed Systems", HotOS 2021;
J. D. C. Little, "A Proof for the Queuing Formula L = lambda W", Oper. Res. 9(3), 1961.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

SEED = 7

# ---------------------------------------------------------------------------
# The modelled service. One instance, one core.
#   6 ms of CPU per request   -> 166.7 req/s at 100% CPU
#   8 concurrent request slots (worker threads) per instance
#   12 ms service time when the dependency is healthy (6 ms CPU + 6 ms waiting)
# The SLO is derived, not asserted. Phase 8 L11 measured W = S/(1-rho) to within
# 3%: at rho = 0.90 the response time is 10 x service time = 120 ms, which is the
# latency objective. An instance running above rho = 0.90 is therefore missing it.
# ---------------------------------------------------------------------------
CPU_RPS = 166.7
SLOTS = 8.0
S_FAST = 0.012
SLO_RHO = 0.90
DEADLINE = 1.0        # a queued request older than this is abandoned by its caller

# The stabiliser preset that section 2 arrives at. Sections 3-7 all use it, so
# every later comparison is about the thing being compared and nothing else.
STABLE = dict(normalize=True, cooldown_in=300.0, hyst_out=1.10, hyst_in=0.70,
              max_out_ratio=2.0, max_in_frac=0.10)


# ---------------------------------------------------------------------------
@dataclass
class Cfg:
    name: str = ""
    horizon: float = 4200.0
    dt: float = 10.0
    traffic: Optional[Callable[[float], float]] = None
    service_time: Optional[Callable[[float], float]] = None
    outage: Optional[Callable[[float], bool]] = None

    metric: str = "cpu"                 # cpu | conc | qage | max
    sp_cpu: float = 0.60
    sp_conc: float = 0.60               # slot utilisation
    sp_inflight: float = 1.20           # in-flight requests per instance
    sp_qage: float = 0.30               # seconds of backlog
    normalize: bool = False             # divide by the fleet that produced the metric
    metric_noise: float = 0.08          # scrape-to-scrape jitter on the observed metric

    metric_delay: float = 60.0          # scrape + pipeline lag
    metric_window: float = 60.0         # averaging window
    decision_interval: float = 60.0     # how often the controller runs
    boot_s: float = 90.0                # launch -> process listening
    warm_s: float = 60.0                # listening -> caches and JIT warm

    gated: bool = True                  # instance joins the LB only once warm
    slow_start: bool = True             # LB weight proportional to capacity
    warm_frac: float = 0.25             # capacity of a warming instance

    min_size: int = 4
    max_size: int = 400
    start_n: int = 0                    # 0 -> size to the opening traffic

    cooldown_out: float = 0.0
    cooldown_in: float = 0.0
    hyst_out: float = 1.0               # act only if metric > setpoint * hyst_out
    hyst_in: float = 1.0                # act only if metric < setpoint * hyst_in
    max_out_ratio: float = 1e9          # cap on multiplicative growth per decision
    max_in_frac: float = 1.0            # cap on fraction removed per decision
    error_guard: bool = False           # never scale in while errors are elevated
    schedule: List[Tuple[float, float, int]] = field(default_factory=list)


@dataclass
class Res:
    name: str
    series: List[Dict[str, float]]
    total_req: float
    viol_req: float
    inst_min: float
    reversals: int
    launches: int

    def slo(self) -> float:
        return 100.0 * (1.0 - self.viol_req / max(1.0, self.total_req))

    def band(self, lo: float, hi: float) -> Tuple[int, int]:
        n = [int(p["n"]) for p in self.series if lo <= p["t"] <= hi]
        return (min(n), max(n)) if n else (0, 0)


# ---------------------------------------------------------------------------
def simulate(cfg: Cfg, noise: List[float]) -> Res:
    mrng = random.Random(SEED)              # identical metric jitter for every config
    st = cfg.service_time or (lambda t: S_FAST)
    outage = cfg.outage or (lambda t: False)

    lam0 = cfg.traffic(0.0)
    n0 = cfg.start_n or max(cfg.min_size, int(math.ceil(lam0 / (CPU_RPS * cfg.sp_cpu))))
    fleet: List[float] = [-1e6] * n0          # launch timestamp per instance
    launches = n0

    hist: List[Tuple[float, float, float, float, float, float]] = []
    # t, cpu, slot-util, in-flight/instance, backlog age, ready count
    series: List[Dict[str, float]] = []
    backlog = 0.0
    total_req = viol_req = inst_min = 0.0
    next_decision = cfg.decision_interval
    last_out = last_in = last_err = -1e6
    reversals = 0
    last_dir = 0

    t = 0.0
    k = 0
    while t < cfg.horizon:
        # ---- physics of this tick ---------------------------------------
        down = outage(t)
        s_eff = 0.005 if down else st(t)
        cpu_rps = 1000.0 if down else CPU_RPS       # failing fast is cheap
        err = 1.0 if down else 0.0
        if err > 0.05:
            last_err = t

        fracs: List[float] = []
        for launch in fleet:
            age = t - launch
            if age < cfg.boot_s:
                continue                            # booting: billed, serves nothing
            if age < cfg.boot_s + cfg.warm_s:
                if cfg.gated:
                    continue                        # not in the load balancer yet
                fracs.append(cfg.warm_frac)
            else:
                fracs.append(1.0)
        caps = [min(cpu_rps * f, SLOTS * f / s_eff) for f in fracs]

        lam = cfg.traffic(t) * noise[k % len(noise)]
        offered_rate = lam + backlog / cfg.dt
        cap_total = sum(caps)
        arrivals = lam * cfg.dt
        total_req += arrivals

        if cap_total <= 0.0:
            served = 0.0
            rho = 9.99
            cpu = conc = inflight = 0.0
            viol_req += arrivals
        else:
            if cfg.slow_start:
                shares = [c / cap_total for c in caps]
            else:
                shares = [1.0 / len(caps)] * len(caps)
            served = 0.0
            cpu_s: List[float] = []
            conc_s: List[float] = []
            hot = 0.0                               # traffic share on saturated hosts
            for f, c, sh in zip(fracs, caps, shares):
                off_i = offered_rate * sh
                got = min(off_i, c)
                served += got
                if off_i / c > SLO_RHO:
                    hot += sh
                cpu_s.append(min(1.0, got / (cpu_rps * f)))
                conc_s.append(min(1.0, got * s_eff / (SLOTS * f)))
            cpu = sum(cpu_s) / len(cpu_s)
            conc = sum(conc_s) / len(conc_s)
            inflight = conc * SLOTS
            rho = offered_rate / cap_total
            viol_req += arrivals * hot

        # A queue older than the caller's deadline is abandoned (Phase 8 L11).
        backlog = max(0.0, (offered_rate - served) * cfg.dt)
        backlog = min(backlog, cap_total * DEADLINE)
        qage = backlog / cap_total if cap_total > 0 else DEADLINE
        inst_min += len(fleet) * cfg.dt / 60.0

        hist.append((t, cpu, conc, inflight, qage, float(len(fracs))))
        series.append({"t": t, "n": float(len(fleet)), "ready": float(len(fracs)),
                       "lam": lam, "cap": cap_total, "rho": min(rho, 9.99),
                       "cpu": cpu, "conc": conc, "qage": qage, "err": err})

        # ---- the controller ---------------------------------------------
        if t >= next_decision:
            next_decision += cfg.decision_interval
            lo = t - cfg.metric_delay - cfg.metric_window
            hi = t - cfg.metric_delay
            win = [h for h in hist if lo <= h[0] <= hi] or [hist[0]]
            m_cpu = sum(h[1] for h in win) / len(win)
            m_slot = sum(h[2] for h in win) / len(win)
            m_infl = sum(h[3] for h in win) / len(win)
            m_qage = sum(h[4] for h in win) / len(win)
            m_ready = sum(h[5] for h in win) / len(win)

            if cfg.metric == "cpu":
                ratio = m_cpu / cfg.sp_cpu
            elif cfg.metric == "conc":
                ratio = m_infl / cfg.sp_inflight
            elif cfg.metric == "qage":
                ratio = (m_qage + 0.05) / (cfg.sp_qage + 0.05)
            else:                                    # max(cpu, slot utilisation)
                ratio = max(m_cpu / cfg.sp_cpu, m_slot / cfg.sp_conc)

            ratio *= 1.0 + mrng.gauss(0.0, cfg.metric_noise)
            n_now = len(fleet)
            # Kubernetes HPA: desired = ceil(replicas * metric / target). `replicas`
            # is what you have NOW; the metric came from the fleet you had a dead
            # time ago. That mismatch is the overshoot. `normalize` fixes it by
            # dividing by the fleet size that actually produced the measurement.
            base = max(1.0, m_ready) if cfg.normalize else float(max(1, n_now))
            want = int(math.ceil(base * ratio))

            if want > n_now:                         # scale out
                if ratio < cfg.hyst_out or t - last_out < cfg.cooldown_out:
                    want = n_now
                else:
                    want = min(want, int(math.ceil(n_now * cfg.max_out_ratio)))
            elif want < n_now:                       # scale in
                # The error guard also has to outlast the metric pipeline: the
                # samples taken during the outage are still inside the window.
                stale = cfg.metric_delay + cfg.metric_window + cfg.decision_interval
                blocked = (ratio > cfg.hyst_in
                           or t - last_in < cfg.cooldown_in
                           or (cfg.error_guard and t - last_err < stale))
                if blocked:
                    want = n_now
                else:
                    want = max(want, int(math.floor(n_now * (1.0 - cfg.max_in_frac))))

            for (a, b, m) in cfg.schedule:           # scheduled floor
                if a <= t < b:
                    want = max(want, m)
            want = max(cfg.min_size, min(cfg.max_size, want))

            if want != n_now:
                d = 1 if want > n_now else -1
                if abs(want - n_now) >= 2:           # ignore +-1 noise chasing
                    if last_dir != 0 and d != last_dir:
                        reversals += 1
                    last_dir = d
                if d > 0:
                    last_out = t
                    launches += want - n_now
                    for _ in range(want - n_now):
                        fleet.append(t)
                else:
                    last_in = t
                    fleet.sort(key=lambda x: -x)     # terminate the youngest first
                    del fleet[: n_now - want]

        t += cfg.dt
        k += 1

    return Res(cfg.name, series, total_req, viol_req, inst_min, reversals, launches)


# ---------------------------------------------------------------------------
def ramp(t: float) -> float:
    """A trackable morning ramp: +1.5 req/s per second = 1 instance per 67 s."""
    if t < 300:
        return 600.0
    if t < 1500:
        return 600.0 + 1800.0 * (t - 300) / 1200.0
    if t < 3000:
        return 2400.0
    if t < 3600:
        return 2400.0 - 1600.0 * (t - 3000) / 600.0
    return 800.0


def spiky(t: float) -> float:
    """The same ramp with a 150 s flash crowd on the plateau."""
    return ramp(t) + (2000.0 if 2000.0 <= t < 2150.0 else 0.0)


def flat(t: float) -> float:
    return 1800.0


def diurnal(t: float) -> float:
    """A 24 h day with a known 12:00 campaign spike."""
    hour = 24.0 * t / 86400.0
    base = 400.0 + 1500.0 * max(0.0, math.sin(math.pi * (hour - 6.0) / 15.0)) ** 1.6
    if 12.0 <= hour < 12.5:
        base += 2200.0
    return base


def bar(v: float, hi: float, w: int = 22) -> str:
    return "#" * max(0, min(w, int(round(w * v / hi))))


def flips(r: Res, lo: float, hi: float) -> int:
    """Direction reversals of the fleet size, ignoring +-1 noise chasing."""
    n = [p["n"] for p in r.series if lo <= p["t"] <= hi]
    out, last = 0, 0
    for i in range(1, len(n)):
        d = n[i] - n[i - 1]
        if abs(d) < 2:
            continue
        sign = 1 if d > 0 else -1
        if last and sign != last:
            out += 1
        last = sign
    return out


def measure_period(r: Res, lo: float, hi: float) -> float:
    """Mean peak-to-peak period of the fleet-size limit cycle, in minutes."""
    pts = [p for p in r.series if lo <= p["t"] <= hi]
    if not pts:
        return 0.0
    span = max(p["n"] for p in pts) - min(p["n"] for p in pts)
    if span < 4:
        return 0.0
    thresh = min(p["n"] for p in pts) + 0.6 * span
    peaks, above = [], False
    for p in pts:
        if p["n"] >= thresh and not above:
            peaks.append(p["t"])
            above = True
        elif p["n"] < thresh - 1:
            above = False
    if len(peaks) < 2:
        return 0.0
    return (peaks[-1] - peaks[0]) / (len(peaks) - 1) / 60.0


def breach_after(r: Res, after: float) -> float:
    bad = [p["t"] for p in r.series if p["t"] >= after and p["rho"] > SLO_RHO]
    return (max(bad) - after + r.series[1]["t"]) if bad else 0.0


# ---------------------------------------------------------------------------
def section1(noise: List[float]) -> List[Tuple[float, Res]]:
    print("== 1 · DEAD TIME IS WHAT MAKES AN AUTOSCALER OSCILLATE ==")
    print("  identical traffic, identical target-tracking controller (hold CPU at 60%),")
    print("  decision interval 60 s, no stabilisers. The only variable is total dead")
    print("  time: metric pipeline + boot + warmup, split 60:90:60 like a real fleet.")
    print("  the plateau needs exactly %d instances (2400 req/s / 100 req/s each)."
          % int(math.ceil(2400.0 / (CPU_RPS * 0.60))))
    print()
    print("   dead time  metric boot warm |  plateau min/max  swing  flips  launches |"
          "   SLO%   inst-min")
    split = (60.0, 90.0, 60.0)
    out: List[Tuple[float, Res]] = []
    for D in (0.0, 60.0, 120.0, 210.0, 360.0):
        f = D / sum(split)
        md, bt, wm = (round(x * f / 10) * 10 for x in split)
        r = simulate(Cfg(name="D=%d" % D, traffic=ramp, metric_delay=md,
                         boot_s=bt, warm_s=wm, metric_noise=0.0), noise)
        out.append((D, r))
        lo, hi = r.band(1800.0, 3000.0)
        tag = "  <- cloud default" if D == 210 else ""
        print("   %5.0f s     %4.0f %4.0f %4.0f |      %3d / %-3d    %4d  %5d  %8d |"
              "  %5.1f   %8.0f%s"
              % (D, md, bt, wm, lo, hi, hi - lo, flips(r, 1800.0, 3000.0), r.launches,
                 r.slo(), r.inst_min, tag))
    print()
    z, prod, worst = out[0][1], out[3][1], out[4][1]
    print("  at D = 0 the loop parks on 24 and stays there: swing %d, zero flips,"
          % (z.band(1800, 3000)[1] - z.band(1800, 3000)[0]))
    print("  %d launches for the whole hour. Target-tracking is EXACT with no lag:"
          % z.launches)
    print("  desired = replicas x (metric / setpoint), and with no lag the replicas")
    print("  that produced the metric ARE the replicas you have, so it cancels to")
    print("  demand / per-instance-capacity. Every row below breaks that identity.")
    print("  at D = 210 s - the number you actually get from a cloud provider - the")
    print("  same controller swings %d instances on a plateau of CONSTANT traffic,"
          % (prod.band(1800, 3000)[1] - prod.band(1800, 3000)[0]))
    print("  launches %d instances instead of %d, and misses the SLO for %.1f%% of"
          % (prod.launches, z.launches, 100.0 - prod.slo()))
    print("  requests. At D = 360 s it swings %d and misses %.1f%%."
          % (worst.band(1800, 3000)[1] - worst.band(1800, 3000)[0], 100.0 - worst.slo()))
    print()
    print("  RULE: a control loop cannot stabilise a plant whose dead time exceeds its")
    print("  reaction period. The reaction period here is 60 s. At 60 s of dead time")
    print("  the loop still settles: swing %d, %d flips, %.1f%% SLO. At 120 s it starts"
          % (out[1][1].band(1800, 3000)[1] - out[1][1].band(1800, 3000)[0],
             flips(out[1][1], 1800.0, 3000.0), out[1][1].slo()))
    print("  hunting: swing %d, %d flips - still no SLO damage, but the fleet is never"
          % (out[2][1].band(1800, 3000)[1] - out[2][1].band(1800, 3000)[0],
             flips(out[2][1], 1800.0, 3000.0)))
    print("  still. Past 2x the reaction period it is a limit cycle, not a controller.")
    print("  the two unstable rows are not 'worse and worse': at 210 s the loop misses")
    print("  %.1f%% of requests, at 360 s it misses %.1f%% only because it slammed into"
          % (100 - prod.slo(), 100 - worst.slo()))
    print("  the 400-instance ceiling and stayed there. It bought the SLO back at")
    print("  %.1fx the bill (%.0f vs %.0f instance-minutes). Neither is a controller."
          % (worst.inst_min / z.inst_min, worst.inst_min, z.inst_min))
    print("  Astrom & Murray predict a limit cycle of period ~2 x dead time:")
    for D, r in out[3:]:
        m = measure_period(r, 1500.0, 3000.0)
        print("    D = %3.0f s -> predicted %.1f min, measured %s"
              % (D, 2 * D / 60.0,
                 ("%.1f min" % m) if m else "n/a (clipped at max_size)"))
    print()
    return out


def section2(noise: List[float]) -> None:
    print("== 2 · THE STABILISERS, ADDED ONE AT A TIME ==")
    print("  same controller and the same 360 s of dead time, now against traffic")
    print("  with a 150 s flash crowd on the plateau (2400 -> 4400 req/s at t=2000 s).")
    print()
    print("   configuration                        plateau min/max  swing  flips"
          "  launches    SLO%   inst-min")
    d360 = dict(metric_delay=100.0, boot_s=150.0, warm_s=100.0)
    acc = {}
    ladder = []
    ladder.append(("naive HPA formula", dict(acc)))
    acc.update(normalize=True)
    ladder.append(("+ divide by the fleet you measured", dict(acc)))
    acc.update(cooldown_in=300.0)
    ladder.append(("+ scale-in cooldown 300 s", dict(acc)))
    acc.update(hyst_out=1.10, hyst_in=0.70)
    ladder.append(("+ hysteresis out>1.10 in<0.70", dict(acc)))
    acc.update(max_out_ratio=2.0, max_in_frac=0.10)
    ladder.append(("+ asymmetric rates out x2 in 10%", dict(acc)))
    acc.update(metric_window=300.0)
    ladder.append(("+ 300 s metric smoothing", dict(acc)))
    ladder.append(("naive HPA + rate limits ONLY",
                   dict(max_out_ratio=2.0, max_in_frac=0.10)))
    rows = []
    for label, extra in ladder:
        kw = dict(d360)
        kw.update(extra)
        r = simulate(Cfg(name=label, traffic=spiky, **kw), noise)
        rows.append((label, r))
        lo, hi = r.band(1800.0, 3000.0)
        print("   %-35s   %3d / %-3d    %4d  %5d  %8d   %5.1f   %8.0f"
              % (label, lo, hi, hi - lo, flips(r, 1800.0, 3000.0), r.launches,
                 r.slo(), r.inst_min))
    print()
    a, b, e, f = rows[0][1], rows[1][1], rows[4][1], rows[5][1]
    print("  row 1 is the formula Kubernetes actually uses:")
    print("      desired = ceil(replicas x currentMetric / targetMetric)")
    print("  `replicas` is what you have NOW. `currentMetric` came off the fleet you")
    print("  had a dead time ago. When 15 instances are still booting, that ratio is")
    print("  applied to a number that already contains them, and you order them twice.")
    print("  row 2 divides by the fleet size that produced the measurement instead.")
    print("  it is free - no lag, no cooldown - and it takes the swing from %d to %d,"
          % (a.band(1800, 3000)[1] - a.band(1800, 3000)[0],
             b.band(1800, 3000)[1] - b.band(1800, 3000)[0]))
    print("  launches from %d to %d and the SLO from %.1f%% to %.1f%%."
          % (a.launches, b.launches, a.slo(), b.slo()))
    print("  the cooldown, hysteresis and rate limits are what you have left for the")
    print("  residual: %.1f%% SLO, %d launches, %.0f instance-minutes, %d flips."
          % (e.slo(), e.launches, e.inst_min, flips(e, 1800.0, 3000.0)))
    print("  smoothing the input is the knob that BUYS SWING WITH LAG. A 300 s average")
    print("  adds ~150 s of dead time - the exact thing that caused the oscillation.")
    print("  here it moved the SLO %+.1f points and the bill %+.0f%%. Reach for it last."
          % (f.slo() - e.slo(), 100.0 * (f.inst_min / e.inst_min - 1.0)))
    print()


def section3(noise: List[float]) -> None:
    print("== 3 · THE METRIC IS THE DECISION, AND CPU IS THE WRONG ONE ==")
    print("  same traffic, stabilised controller, dead time 210 s. From t=1200 s the")
    print("  database degrades over 10 min: service time 12 ms -> 120 ms, recovering")
    print("  by t=3000 s. The CPU cost of a request never changes: 6 ms throughout.")
    print("  an instance then saturates at 8 slots / 0.120 s = %.0f req/s," % (SLOTS / 0.12))
    print("  and at %.0f req/s its CPU reads %.0f%%. It is FULL and it looks IDLE."
          % (SLOTS / 0.12, 100.0 * (SLOTS / 0.12) / CPU_RPS))
    print()

    def io_service(t: float) -> float:
        """The dependency degrades over 10 minutes and recovers in 5."""
        if t < 1200.0 or t >= 3000.0:
            return S_FAST
        ramp_in = min(1.0, (t - 1200.0) / 600.0)
        ramp_out = min(1.0, max(0.0, (3000.0 - t) / 300.0))
        return S_FAST + (0.120 - S_FAST) * min(ramp_in, ramp_out)

    print("   scaling metric                fleet in slow phase  worst rho   SLO%"
          "   inst-min")
    for key, label in (("cpu", "CPU 60%  (the default)"),
                       ("conc", "in-flight per instance = 1.2"),
                       ("qage", "backlog age 0.30 s"),
                       ("max", "max(CPU, in-flight)")):
        r = simulate(Cfg(name=label, traffic=ramp, service_time=io_service,
                         metric=key, **STABLE), noise)
        lo, hi = r.band(1800.0, 3000.0)
        peak = max(p["rho"] for p in r.series if 1200 <= p["t"] <= 3000)
        star = "  <- ship this" if key == "max" else ""
        print("   %-30s   %4d / %-4d        %5.2f  %5.1f   %8.0f%s"
              % (label, lo, hi, peak, r.slo(), r.inst_min, star))
    print()
    print("  CPU does not merely lag in the slow phase - it points the wrong way.")
    print("  utilisation falls because the CPU is WAITING, so the controller reads")
    print("  'idle' and scales in while every worker slot is occupied.")
    print("  in-flight requests per instance is Little's Law read off the box,")
    print("  L = lambda x W (Phase 8 L01): it is proportional to load in BOTH regimes.")
    print("  backlog age is the same truth one step later - it says nothing until you")
    print("  are already behind, which is why it belongs on worker fleets, not on a")
    print("  user-facing request path. max(CPU, in-flight) scales on whichever")
    print("  resource is actually the bottleneck, and the bottleneck moved.")
    print()


def section4(noise: List[float]) -> None:
    print("== 4 · THE AUTOSCALER SCALES IN DURING THE OUTAGE ==")
    print("  constant 1800 req/s, stabilised controller. At t=900 s the dependency")
    print("  dies: requests now fail in 5 ms instead of succeeding in 12 ms, and")
    print("  failing fast is CHEAP, so CPU per instance collapses to a few percent.")
    print("  the controller reads 'idle'. The dependency returns at t=2400 s.")
    print()

    def dead(t: float) -> bool:
        return 900.0 <= t < 2400.0

    runs = []
    for guard in (False, True):
        kw = dict(STABLE)
        r = simulate(Cfg(name="guard=%s" % guard, traffic=flat, outage=dead,
                         horizon=3900.0, error_guard=guard, **kw), noise)
        runs.append(r)
    print("      t | dep  |  no guard                 |  error-guarded")
    for tt in (600, 900, 1140, 1440, 1740, 2040, 2340, 2460, 2640, 2940, 3600):
        a = next(p for p in runs[0].series if p["t"] >= tt)
        b = next(p for p in runs[1].series if p["t"] >= tt)
        print("   %4d | %-4s |  %3d %-22s|  %3d %s"
              % (tt, "DOWN" if dead(tt) else "up", a["n"], bar(a["n"], 40),
                 b["n"], bar(b["n"], 40)))
    lo_a = min(p["n"] for p in runs[0].series if 900 <= p["t"] < 2400)
    lo_b = min(p["n"] for p in runs[1].series if 900 <= p["t"] < 2400)
    print()
    print("  unguarded: the fleet fell from %d to %d during the outage. When the"
          % (runs[0].series[0]["n"], lo_a))
    print("             dependency came back, real traffic met a fleet %.1fx too small:"
          % (runs[0].series[0]["n"] / max(1.0, lo_a)))
    print("             SLO breached for a further %.0f s AFTER recovery, and %.1f%%"
          % (breach_after(runs[0], 2400.0), 100.0 - runs[0].slo()))
    print("             of all requests in the run missed it.")
    print("  guarded:   floor held at %d, %.0f s of post-recovery breach, %.1f%% missed."
          % (lo_b, breach_after(runs[1], 2400.0), 100.0 - runs[1].slo()))
    print("  note what stopped it from reaching min_size (4): the 10%-per-interval")
    print("  scale-in rate limit from section 2. The knob you added for oscillation is")
    print("  the only thing standing between an outage and an empty fleet.")
    print("  the guard is two clauses: never scale IN while the error rate is elevated,")
    print("  and keep the block for metric_delay + window + interval afterwards,")
    print("  because the outage's cheap samples are still inside the averaging window.")
    print()


# ---------------------------------------------------------------------------
# Section 5: the retry storm that autoscaling pays the running costs of.
# ---------------------------------------------------------------------------
DB_ALPHA = 0.05          # USL contention (serialisation)
DB_BETA = 0.0005         # USL coherency (crosstalk between connections)
DB_CONN_QPS = 50.0       # one connection, uncontended: 20 ms per query
DB_MAX_CONN = 300        # postgresql.conf max_connections
POOL = 20                # connections opened by every app instance
TIMEOUT = 1.0
DEMAND = 400.0           # real user demand, req/s
ATTEMPTS = 3


def db_capacity(conns: int) -> float:
    """Universal Scalability Law (Gunther 2007). It peaks, then it goes DOWN."""
    n = max(1, min(conns, DB_MAX_CONN))
    return DB_CONN_QPS * n / (1.0 + DB_ALPHA * (n - 1) + DB_BETA * n * (n - 1))


def metastable_run(mode: str) -> Tuple[List[Tuple[float, float, int, int, float,
                                                   float, float]], float]:
    """One 600 s run. mode='scale' autoscales the app tier; 'shed' pins it and
    admits only what the database is actually delivering."""
    dt, horizon = 5.0, 600.0
    n_inst = 6
    pend: List[Tuple[float, float, int]] = []
    q = 0.0
    cost = 0.0
    rows = []
    t = 0.0
    while t < horizon:
        hiccup = 120.0 <= t < 180.0
        want_conn = n_inst * POOL
        conns = min(DB_MAX_CONN, want_conn)
        refused = max(0.0, want_conn - DB_MAX_CONN) / max(1.0, want_conn)
        cap = db_capacity(conns) * (0.5 if hiccup else 1.0)

        due = [p for p in pend if p[0] <= t]
        pend = [p for p in pend if p[0] > t]
        a = [DEMAND] + [sum(p[1] for p in due if p[2] == k)
                        for k in range(2, ATTEMPTS + 1)]
        offered = sum(a)

        admitted, shed = offered, 0.0
        if mode == "shed":
            # An adaptive concurrency limit (Phase 8 L11): admit only what the
            # database is actually delivering right now, reject the rest in 0 ms.
            limit = cap
            if admitted > limit:
                shed = admitted - limit
                admitted = limit
        admitted *= (1.0 - refused)              # "too many clients already"

        q = max(0.0, min(q + (admitted - cap) * dt, 20000.0))
        wait = q / max(1.0, cap)
        served = min(admitted, cap)
        good = served if wait < TIMEOUT else 0.0
        fail_frac = (offered - good) / max(1.0, offered)
        for k in range(1, ATTEMPTS):
            if a[k - 1] * fail_frac > 0.0:
                pend.append((t + dt * 0.5, a[k - 1] * fail_frac, k + 1))

        cost += n_inst * dt / 60.0
        rows.append((t, offered, n_inst, want_conn, cap, good, shed))

        if mode == "scale" and abs(t % 30.0) < 1e-9 and t >= 60.0:
            n_inst = max(6, min(30, int(math.ceil(offered / 60.0))))
        t += dt
    return rows, cost


def section5() -> None:
    print("== 5 · AUTOSCALING INTO A METASTABLE FAILURE ==")
    peak_n = int(round(math.sqrt((1.0 - DB_ALPHA) / DB_BETA)))
    print("  one database behind the app tier, max_connections = %d." % DB_MAX_CONN)
    print("  its throughput follows the Universal Scalability Law (Phase 11 L02):")
    for n in (peak_n, 100, 200, 300):
        tag = "   <- peak" if n == peak_n else ""
        print("    %3d connections -> %5.0f q/s  (%3.0f%% of peak)%s"
              % (n, db_capacity(n), 100 * db_capacity(n) / db_capacity(peak_n), tag))
    print("  every app instance opens a pool of %d. Adding instances does not add" % POOL)
    print("  database capacity. Past %d connections it SUBTRACTS it." % peak_n)
    print("  real user demand %.0f req/s, client timeout %.1f s, %d attempts, jitter."
          % (DEMAND, TIMEOUT, ATTEMPTS))
    print("  trigger: a 60 s database hiccup at t=120 s (per-connection q/s halved).")
    print()

    summary = {}
    for mode in ("scale", "shed"):
        rows, cost = metastable_run(mode)

        label = ("A · REACTIVE AUTOSCALING (the default)" if mode == "scale"
                 else "B · LOAD SHEDDING, AUTOSCALER PINNED AT 6")
        print("  --- %s ---" % label)
        print("      t | offered  inst  db-conn   db q/s  goodput   shed | goodput")
        for tt in (60, 115, 150, 185, 215, 260, 350, 450, 595):
            row = next(r for r in rows if r[0] >= tt)
            print("   %4d | %7.0f  %4d  %7d  %7.0f  %7.0f  %5.0f | %s"
                  % (row[0], row[1], row[2], row[3], row[4], row[5], row[6],
                     bar(row[5], 450.0, 18)))
        tail = [r for r in rows if r[0] >= 300.0]
        gp = sum(r[5] for r in tail) / len(tail)
        rec = [r[0] for r in rows if r[0] > 180.0 and r[5] >= 0.9 * DEMAND]
        rec_s = ("%.0f s after the hiccup ended" % (rec[0] - 180.0)) if rec else "NEVER"
        summary[mode] = (gp, max(r[1] for r in rows), max(r[3] for r in rows),
                         cost, min(r[4] for r in rows if r[0] >= 300.0))
        print("    after the trigger cleared (t > 300 s):")
        print("      goodput          %6.0f req/s of %.0f real demand" % (gp, DEMAND))
        print("      peak offered     %6.0f req/s = %.1fx real demand (retries)"
              % (summary[mode][1], summary[mode][1] / DEMAND))
        print("      peak connections %6d wanted, %d granted"
              % (summary[mode][2], min(DB_MAX_CONN, summary[mode][2])))
        print("      database q/s     %6.0f  (healthy baseline %.0f)"
              % (summary[mode][4], db_capacity(120)))
        print("      instance-minutes %6.0f" % summary[mode][3])
        print("      recovery         %s" % rec_s)
        print()
    a, b = summary["scale"], summary["shed"]
    print("  the autoscaler did exactly what it was told. It added capacity to serve")
    print("  RETRIES - and a retry is not satisfied by being served quickly, it is")
    print("  satisfied by SUCCEEDING. Every instance it added opened %d more" % POOL)
    print("  connections to the one tier it could not scale, and the USL curve turned")
    print("  those connections into LESS database: %.0f q/s instead of %.0f, a %.0f%% cut."
          % (a[4], db_capacity(120), 100 * (1 - a[4] / db_capacity(120))))
    print("  result: %.0f req/s of goodput for %.0f instance-minutes, versus %.0f req/s"
          % (a[0], a[3], b[0]))
    print("  for %.0f instance-minutes when the app shed instead. %.1fx the bill,"
          % (b[3], a[3] / b[3]))
    print("  and the arithmetic on goodput is a division by zero.")
    print("  autoscaling did not cause the metastable failure (Bronson et al., HotOS")
    print("  2021). It paid the loop's running costs so the loop never had to end.")
    print("  the exit is load shedding - Phase 8 L11 built it.")
    print()


def section6(noise: List[float]) -> None:
    print("== 6 · A NEW INSTANCE IS NOT CAPACITY FOR 60 SECONDS ==")
    print("  identical scale-out events. A booted instance needs 60 s to warm its")
    print("  page cache, connection pool and JIT; during that window it runs at %.0f%%"
          % (100 * 0.25))
    print("  of capacity. The only variable is what the load balancer sends it.")
    print()
    print("   traffic policy for a warming instance        SLO%   missed req   inst-min")
    for gated, slow, label in (
            (False, False, "full share the moment it listens"),
            (False, True, "slow start: LB weight ~ capacity"),
            (True, True, "gated: no traffic at all until warm")):
        r = simulate(Cfg(name=label, traffic=ramp, gated=gated, slow_start=slow,
                         **STABLE), noise)
        print("   %-40s  %5.1f  %10.0f   %8.0f"
              % (label, r.slo(), r.viol_req, r.inst_min))
    print()
    print("   second since launch   state      capacity the LB can actually use")
    for sec in (0, 30, 60, 90, 120, 145, 150, 180):
        if sec < 90:
            state, frac = "booting ", 0.0
        elif sec < 150:
            state, frac = "warming ", 0.25
        else:
            state, frac = "in service", 1.0
        print("   %6d s              %-10s %5.1f req/s  %s"
              % (sec, state, CPU_RPS * 0.60 * frac, bar(frac, 1.0, 20)))
    print("  the autoscaler counted this instance as 1 the moment it launched and the")
    print("  bill started at the same instant. It delivered 0 req/s for 90 s and")
    print("  %.0f req/s for the next 60 s. Averaged over its first 150 s it is worth"
          % (CPU_RPS * 0.60 * 0.25))
    print("  %.0f%% of an instance. Plan capacity in instance-SECONDS, not instances."
          % (100 * (0 * 90 + 0.25 * 60) / 150.0))
    print()


def section7(noise: List[float]) -> None:
    print("== 7 · SCHEDULED FOR THE ENVELOPE, REACTIVE FOR THE RESIDUAL ==")
    print("  a 24 h diurnal curve with a 12:00 campaign send (+2200 req/s for 30 min)")
    print("  that marketing told you about three weeks ago. Both runs use the identical")
    print("  stabilised reactive controller with 210 s of dead time.")
    print()
    sched = [(6.0 * 3600, 21.0 * 3600, 14), (11.75 * 3600, 13.0 * 3600, 42)]
    day = dict(traffic=diurnal, horizon=86400.0, dt=60.0, metric_delay=60.0,
               boot_s=90.0, warm_s=60.0)
    day.update(STABLE)
    r_re = simulate(Cfg(name="reactive only", **day), noise)
    r_sc = simulate(Cfg(name="scheduled + reactive", schedule=sched, **day), noise)
    print("   policy                  SLO%   missed req   inst-min   peak fleet")
    for r in (r_re, r_sc):
        pk = max(p["n"] for p in r.series)
        print("   %-20s  %6.2f   %10.0f   %8.0f   %10d"
              % (r.name, r.slo(), r.viol_req, r.inst_min, int(pk)))
    print()
    print("   hour  demand   reactive only              scheduled + reactive")
    for h in (5, 6, 7, 8, 11, 12, 12.5, 13, 18, 23):
        tt = h * 3600.0
        a = next(p for p in r_re.series if p["t"] >= tt)
        b = next(p for p in r_sc.series if p["t"] >= tt)
        print("   %4.1f  %6.0f   %3d %-22s   %3d %s"
              % (h, a["lam"], a["n"], bar(a["n"], 60), b["n"], bar(b["n"], 60)))
    print()
    dc = 100.0 * (r_sc.inst_min / r_re.inst_min - 1.0)
    dv = 100.0 * (1.0 - r_sc.viol_req / max(1.0, r_re.viol_req))
    print("  the schedule removes the lag for the part of the day you can predict, and")
    print("  the reactive loop handles only the residual. Cost %+.1f%% instance-minutes,"
          % dc)
    print("  requests missing the SLO down %.0f%%. It is the highest-value, lowest-" % dv)
    print("  technology fix in this lesson, and it is a cron entry.")
    print()
    print("  THESIS: every column above is a cost column. Autoscaling is an")
    print("  optimisation for SPEND. It is itself a dependency - a control plane, a")
    print("  capacity pool, a quota - and it is slowest at exactly the moment you need")
    print("  it fastest. Buy reliability with a floor you have already paid for.")


def main() -> None:
    rng = random.Random(SEED)
    noise = [1.0 + rng.gauss(0.0, 0.03) for _ in range(4000)]   # shared by every run
    section1(noise)
    section2(noise)
    section3(noise)
    section4(noise)
    section5()
    section6(noise)
    section7(noise)


if __name__ == "__main__":
    main()
