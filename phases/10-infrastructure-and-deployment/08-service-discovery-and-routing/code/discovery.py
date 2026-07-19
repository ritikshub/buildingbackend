#!/usr/bin/env python3
"""Service discovery & health-aware routing — measuring the blackhole window.

Lesson: phases/10-infrastructure-and-deployment/08-service-discovery-and-routing/docs/en.md
Builds a lease-based registry, decomposes the delay between an instance dying and
its callers stopping traffic to it, compares active health checking with passive
outlier ejection, caps ejection during a global fault, and measures three
graceful-shutdown orderings.

Time is SIMULATED in discrete 50 ms ticks — deterministic, reproducible, no sleeping.
Sources: RFC 1035 sec. 3.2.1 (DNS TTL semantics); RFC 9110 sec. 15.6.4 (503);
Kubernetes API reference (EndpointSlice, lifecycle.preStop).
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Tuple

TICK = 0.05  # 50 ms of simulated time per step

# ---------------------------------------------------------------- knobs
HEARTBEAT_INTERVAL = 10.0  # instance -> registry, every 10 s
LEASE_TTL = 30.0           # 3 missed heartbeats before the lease expires
SWEEP_INTERVAL = 10.0      # how often the registry scans for expired leases
PROPAGATION_DELAY = 2.0    # registry -> every routing layer / watcher
CLIENT_CACHE_TTL = 30.0    # how often the caller re-reads the instance list
CONN_MAX_LIFETIME = 60.0   # max age of a pooled keep-alive connection
CLIENT_TIMEOUT = 2.0       # a request into a blackhole fails after this
PROBE_INTERVAL = 1.0       # active health check period
PROBE_TIMEOUT = 1.0        # active health check timeout
PROBE_THRESHOLD = 3        # consecutive probe failures before ejection
PASSIVE_THRESHOLD = 5      # consecutive request failures before ejection
OFFERED_RATE = 40.0        # req/s offered by the caller
N_INSTANCES = 6
DEATH_AT = 60.0            # when orders-3 stops answering
HORIZON = 220.0
TRIALS = 2000              # seeds used for the window distribution


def rule(width: int = 74, ch: str = "=") -> str:
    return ch * width


def head(n: int, title: str) -> None:
    print("\n== %d %s %s ==" % (n, "·", title))


def pct(values: List[float], p: float) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(p * (len(s) - 1)))]


# ================================================================ 1 · REGISTRY
@dataclass
class Lease:
    instance: str
    addr: str
    last_heartbeat: float
    state: str = "UP"          # UP | EXPIRED | DEREGISTERED


class Registry:
    """A registry is a set of leases. A lease says 'I am here, and I will keep
    saying so'. Silence for longer than the TTL revokes it."""

    def __init__(self, ttl: float, sweep: float, log: Optional[List[str]] = None):
        self.ttl = ttl
        self.sweep_interval = sweep
        self.leases: Dict[str, Lease] = {}
        self.log = log
        self.history: List[Tuple[float, FrozenSet[str]]] = [(0.0, frozenset())]

    def _say(self, now: float, msg: str) -> None:
        if self.log is not None:
            self.log.append("  t=%6.2fs  %s" % (now, msg))

    def _snapshot(self, now: float) -> None:
        self.history.append((now, frozenset(self.view())))

    def register(self, iid: str, addr: str, now: float) -> None:
        self.leases[iid] = Lease(iid, addr, now)
        self._say(now, "REGISTER    %-10s %-16s lease ttl=%.0fs" % (iid, addr, self.ttl))
        self._snapshot(now)

    def heartbeat(self, iid: str, now: float) -> None:
        lease = self.leases.get(iid)
        if lease is not None and lease.state == "UP":
            lease.last_heartbeat = now

    def deregister(self, iid: str, now: float) -> None:
        lease = self.leases.get(iid)
        if lease is None or lease.state != "UP":
            return
        lease.state = "DEREGISTERED"
        self._say(now, "DEREGISTER  %-10s removed at once — no TTL wait" % iid)
        self._snapshot(now)

    def sweep(self, now: float) -> List[str]:
        """Expire every lease whose last heartbeat is older than the TTL."""
        expired = []
        for lease in self.leases.values():
            if lease.state == "UP" and now - lease.last_heartbeat > self.ttl:
                lease.state = "EXPIRED"
                expired.append(lease.instance)
                self._say(now, "EXPIRE      %-10s silent %.1fs > ttl %.0fs"
                          % (lease.instance, now - lease.last_heartbeat, self.ttl))
        if expired:
            self._snapshot(now)
        return expired

    def view(self) -> List[str]:
        return sorted(i for i, l in self.leases.items() if l.state == "UP")

    def view_as_of(self, when: float) -> FrozenSet[str]:
        """What a watcher PROPAGATION_DELAY behind the registry currently believes."""
        seen = self.history[0][1]
        for stamp, snap in self.history:
            if stamp <= when:
                seen = snap
            else:
                break
        return seen


def section_registry() -> None:
    head(1, "A REGISTRY WITH LEASES")
    log: List[str] = []
    reg = Registry(ttl=LEASE_TTL, sweep=SWEEP_INTERVAL, log=log)
    print("  heartbeat every %.0fs | lease ttl %.0fs (= %d missed heartbeats) |"
          % (HEARTBEAT_INTERVAL, LEASE_TTL, int(LEASE_TTL / HEARTBEAT_INTERVAL)))
    print("  expiry sweep every %.0fs\n" % SWEEP_INTERVAL)

    # (id, addr, born, wedges_at, deregisters_at)
    plan = [("orders-a", "10.0.1.7:8080", 0.0, None, None),
            ("orders-b", "10.0.1.9:8080", 0.0, 22.0, None),
            ("orders-c", "10.0.2.4:8080", 6.0, None, 30.0)]

    next_hb = {p[0]: p[2] + HEARTBEAT_INTERVAL for p in plan}
    next_sweep = SWEEP_INTERVAL
    died_at: Dict[str, float] = {}
    gone_at: Dict[str, float] = {}

    t = 0.0
    while t < 75.0:
        for iid, addr, born, wedge, dereg in plan:
            if abs(t - born) < TICK / 2:
                reg.register(iid, addr, t)
            if wedge is not None and abs(t - wedge) < TICK / 2:
                log.append("  t=%6.2fs  WEDGES      %-10s stops answering AND stops "
                           "heartbeating —\n                        but its listening "
                           "socket stays open" % (t, iid))
                died_at[iid] = t
            if dereg is not None and abs(t - dereg) < TICK / 2:
                reg.deregister(iid, t)
                died_at[iid] = t
                gone_at[iid] = t
        for iid, addr, born, wedge, dereg in plan:
            if t >= next_hb[iid] - TICK / 2:
                if wedge is None or t < wedge:
                    reg.heartbeat(iid, t)
                next_hb[iid] += HEARTBEAT_INTERVAL
        if t >= next_sweep - TICK / 2:
            for gone in reg.sweep(t):
                gone_at[gone] = t
            next_sweep += SWEEP_INTERVAL
        t = round(t + TICK, 6)

    for line in log:
        print(line)
    print("\n  final registry view: %s" % ", ".join(reg.view()))
    by_ttl = gone_at["orders-b"] - died_at["orders-b"]
    by_dereg = gone_at["orders-c"] - died_at["orders-c"]
    print("  orders-b left by TTL EXPIRY:    %5.1fs after it stopped answering." % by_ttl)
    print("  orders-c left by DEREGISTERING: %5.1fs." % by_dereg)
    print("  Same registry, same knobs. That %.1fs is a decision you make in your"
          % (by_ttl - by_dereg))
    print("  shutdown handler — and it is only the FIRST of six delays.")


# ============================================== 2 & 3 · THE BLACKHOLE WINDOW
@dataclass
class Draws:
    hb_phase: Dict[str, float]
    sweep_phase: float
    cache_phase: float
    probe_phase: Dict[str, float]
    conn_expiry: Dict[str, float]


IDS = ["orders-%d" % i for i in range(1, N_INSTANCES + 1)]
DEAD = "orders-3"


def draw(seed: int) -> Draws:
    """Every source of phase in the system, drawn once. Order matters: the
    closed-form model and the tick simulation must consume the same stream."""
    rng = random.Random(seed)
    return Draws(
        hb_phase={i: rng.uniform(0.0, HEARTBEAT_INTERVAL) for i in IDS},
        sweep_phase=rng.uniform(0.0, SWEEP_INTERVAL),
        cache_phase=rng.uniform(0.0, CLIENT_CACHE_TTL),
        probe_phase={i: rng.uniform(0.0, PROBE_INTERVAL) for i in IDS},
        conn_expiry={i: DEATH_AT + rng.uniform(0.0, CONN_MAX_LIFETIME) for i in IDS})


def layers_for(d: Draws) -> List[Tuple[str, float]]:
    """Closed form for the six delays. Validated tick-for-tick against the
    simulation below."""
    hb = d.hb_phase[DEAD]
    n = 0
    last_hb = hb
    while hb + (n + 1) * HEARTBEAT_INTERVAL < DEATH_AT:
        n += 1
        last_hb = hb + n * HEARTBEAT_INTERVAL
    hb_due = last_hb + HEARTBEAT_INTERVAL
    ttl_ok = last_hb + LEASE_TTL
    k = 0
    while d.sweep_phase + k * SWEEP_INTERVAL <= ttl_ok:
        k += 1
    reg_gone = d.sweep_phase + k * SWEEP_INTERVAL
    seen_at = reg_gone + PROPAGATION_DELAY
    j = 0
    while d.cache_phase + j * CLIENT_CACHE_TTL < seen_at:
        j += 1
    list_gone = d.cache_phase + j * CLIENT_CACHE_TTL
    stop = max(list_gone, d.conn_expiry[DEAD])
    return [
        ("1  heartbeat interval", hb_due - DEATH_AT),
        ("2  registry lease grace", ttl_ok - hb_due),
        ("3  expiry sweep granularity", reg_gone - ttl_ok),
        ("4  propagation to the caller", PROPAGATION_DELAY),
        ("5  caller list cache TTL", list_gone - seen_at),
        ("6  pooled connection reuse", stop - list_gone),
    ]


@dataclass
class Result:
    label: str
    total: float
    failed: int
    probes: int
    probe_rate: float
    stop_reason: str
    stopped: bool


def run_discovery(label: str, seed: int, active: bool = False, passive: bool = False,
                  conn_lifetime: Optional[float] = CONN_MAX_LIFETIME) -> Result:
    """orders-3 of a 6-instance pool stops answering at DEATH_AT. Tick forward
    and measure when the caller actually stops sending it traffic."""
    d = draw(seed)
    conn_expiry = dict(d.conn_expiry)
    if conn_lifetime is None:                      # the common default: none set
        conn_expiry = {i: float("inf") for i in IDS}

    reg = Registry(ttl=LEASE_TTL, sweep=SWEEP_INTERVAL)
    for n, i in enumerate(IDS):
        reg.register(i, "10.0.1.%d:8080" % (10 + n), 0.0)

    next_hb = dict(d.hb_phase)
    next_probe = dict(d.probe_phase)
    next_sweep = d.sweep_phase
    next_refresh = d.cache_phase

    resolved: FrozenSet[str] = frozenset(IDS)
    ejected = {i: False for i in IDS}
    consec_probe_fail = {i: 0 for i in IDS}
    consec_req_fail = {i: 0 for i in IDS}
    pending: List[Tuple[float, str, bool, bool]] = []   # (observe_at, id, ok, is_probe)

    stop_at: Optional[float] = None
    stop_reason = ""
    failed = probes = 0
    rr = 0
    carry = 0.0
    t = 0.0

    while t < HORIZON:
        # 1. instances heartbeat; a wedged one simply stops
        for i in IDS:
            if t >= next_hb[i] - TICK / 2:
                if not (i == DEAD and t >= DEATH_AT):
                    reg.heartbeat(i, t)
                next_hb[i] += HEARTBEAT_INTERVAL

        # 2. the registry sweeps for expired leases
        if t >= next_sweep - TICK / 2:
            reg.sweep(t)
            next_sweep += SWEEP_INTERVAL

        # 3. the caller refreshes its cached list, PROPAGATION_DELAY behind
        if t >= next_refresh - TICK / 2:
            resolved = reg.view_as_of(t - PROPAGATION_DELAY)
            next_refresh += CLIENT_CACHE_TTL

        # 4. active health checks probe on a schedule
        if active:
            for i in IDS:
                if t >= next_probe[i] - TICK / 2:
                    if not ejected[i]:
                        probes += 1
                        ok = not (i == DEAD and t >= DEATH_AT)
                        pending.append((t + (PROBE_TIMEOUT if not ok else 0.01),
                                        i, ok, True))
                    next_probe[i] += PROBE_INTERVAL

        # 5. the caller dispatches over its pooled connections
        selectable = [i for i in IDS
                      if not ejected[i] and (i in resolved or t < conn_expiry[i])]
        carry += OFFERED_RATE * TICK
        n = int(carry)
        carry -= n
        for _ in range(n):
            if not selectable:
                break
            target = selectable[rr % len(selectable)]
            rr += 1
            ok = not (target == DEAD and t >= DEATH_AT)
            if not ok:
                failed += 1
            pending.append((t + (CLIENT_TIMEOUT if not ok else 0.02), target, ok, False))

        # 6. outcomes land; passive detection learns only from these
        ripe = [p for p in pending if p[0] <= t + 1e-9]
        if ripe:
            pending = [p for p in pending if p[0] > t + 1e-9]
            ripe.sort()
            for _obs, i, ok, is_probe in ripe:
                if is_probe:
                    consec_probe_fail[i] = 0 if ok else consec_probe_fail[i] + 1
                    if active and not ejected[i] and consec_probe_fail[i] >= PROBE_THRESHOLD:
                        ejected[i] = True
                        conn_expiry[i] = t       # ejection CLOSES the pooled socket
                        if i == DEAD and not stop_reason:
                            stop_reason = ("active health check — %d failed probes"
                                           % PROBE_THRESHOLD)
                else:
                    consec_req_fail[i] = 0 if ok else consec_req_fail[i] + 1
                    if passive and not ejected[i] and consec_req_fail[i] >= PASSIVE_THRESHOLD:
                        ejected[i] = True
                        conn_expiry[i] = t
                        if i == DEAD and not stop_reason:
                            stop_reason = ("passive outlier ejection — %d failed requests"
                                           % PASSIVE_THRESHOLD)

        # has traffic to the dead instance actually stopped?
        if stop_at is None and t >= DEATH_AT:
            still = (not ejected[DEAD]) and (DEAD in resolved or t < conn_expiry[DEAD])
            if not still:
                stop_at = t
                if not stop_reason:
                    stop_reason = "pooled connection hit its max lifetime"

        t = round(t + TICK, 6)

    stopped = stop_at is not None
    total = (stop_at - DEATH_AT) if stopped else (HORIZON - DEATH_AT)
    span = HORIZON - DEATH_AT
    return Result(label=label, total=total, failed=failed, probes=probes,
                  probe_rate=probes / span, stop_reason=stop_reason, stopped=stopped)


def section_window() -> Tuple[int, Result]:
    head(2, "THE BLACKHOLE WINDOW IS A SUM")
    print("  %d instances, caller offers %.0f req/s round-robin over pooled connections."
          % (N_INSTANCES, OFFERED_RATE))
    print("  orders-3 stops answering at t=%.0fs. Nothing is misconfigured; every layer"
          % DEATH_AT)
    print("  below is behaving exactly as documented.\n")

    # the window is a distribution, not a number: where in its own cycle each
    # layer happens to be when the instance dies decides your day.
    totals = []
    profiles = []
    per_layer: List[List[float]] = [[] for _ in range(6)]
    for s in range(1, TRIALS + 1):
        ls = layers_for(draw(s))
        profiles.append([v for _n, v in ls])
        totals.append(sum(v for _n, v in ls))
        for idx, (_n, v) in enumerate(ls):
            per_layer[idx].append(v)
    means = [sum(col) / TRIALS for col in per_layer]
    # The representative run is the one closest to the AVERAGE PROFILE — every
    # layer near its own mean — not merely the one with a median total.
    typical_seed = 1 + min(range(TRIALS),
                           key=lambda k: sum(abs(profiles[k][i] - means[i])
                                             for i in range(6)))
    chosen = layers_for(draw(typical_seed))
    chosen_total = sum(v for _n, v in chosen)
    mean_total = sum(totals) / TRIALS

    print("  The most REPRESENTATIVE of %d simulated deaths (seed %d — every layer"
          % (TRIALS, typical_seed))
    print("  closest to its own average; the numbers below are not a lucky draw):\n")
    print("  layer                              this run   cumulative   mean over %d" % TRIALS)
    print("  %s" % ("-" * 72))
    cum = 0.0
    for idx, (name, secs) in enumerate(chosen):
        cum += secs
        print("  %-32s %7.2fs %11.2fs %13.2fs" % (name, secs, cum, means[idx]))
    print("  %s" % ("-" * 72))
    print("  %-32s %7s %11.2fs %13.2fs  <-- TOTAL"
          % ("caller stops sending", "", chosen_total, mean_total))
    print()
    print("  assumed window (everyone quotes the lease TTL):  %6.2f s" % LEASE_TTL)
    print("  measured, this run:                             %6.2f s" % chosen_total)
    print("  measured, mean of %-4d deaths:                   %6.2f s" % (TRIALS, mean_total))
    print("  measured, p95:                                  %6.2f s" % pct(totals, 0.95))
    print("  measured, worst:                                %6.2f s" % max(totals))
    print("  reality / assumption:   this run %5.2fx   mean %5.2fx   p95 %5.2fx"
          % (chosen_total / LEASE_TTL, mean_total / LEASE_TTL,
             pct(totals, 0.95) / LEASE_TTL))

    sim = run_discovery("registry heartbeats only", seed=typical_seed)
    agree = abs(sim.total - chosen_total) < TICK * 1.5
    print("\n  tick simulation of the same run: %.2fs — closed form and simulation %s."
          % (sim.total, "AGREE" if agree else "DISAGREE"))
    print("  requests sent into the blackhole: %d — every one of them failed." % sim.failed)
    print("  traffic stopped because: %s" % sim.stop_reason)
    return typical_seed, sim


def section_pinned(seed: int, bounded: Result) -> Result:
    print("\n  -- layer 6, on its own: connection reuse defeats discovery --")
    unbounded = run_discovery("no max connection lifetime", seed=seed,
                              conn_lifetime=None)
    print("  Same fault, same seed. The only change: the client has no max connection")
    print("  lifetime configured — which is the DEFAULT in most HTTP clients.")
    print("  max lifetime %5.0fs -> traffic stopped after %6.2fs — %4d failed requests"
          % (CONN_MAX_LIFETIME, bounded.total, bounded.failed))
    print("  max lifetime  unset -> %-14s in %6.0fs — %4d failed requests"
          % ("NEVER stopped" if not unbounded.stopped else "stopped",
             unbounded.total, unbounded.failed))
    print("  The registry expired the lease. The caller's list dropped the address.")
    print("  The caller kept sending anyway, for the entire %.0fs run, because a"
          % (HORIZON - DEATH_AT))
    print("  keep-alive connection is pinned to an ADDRESS and discovery closes no")
    print("  sockets. 'We updated DNS' is not a rollout.")
    return unbounded


def section_reduce(results: List[Result]) -> None:
    head(3, "REDUCE IT, MEASURABLY")
    print("  Identical fault, identical seed. Only the detection mechanism changes.\n")
    print("  configuration                   window    failed   probes/s   what it costs")
    print("  %s" % ("-" * 90))
    base, act, pas, both = results
    costs = {
        base.label: "-          nothing — and it is by far the slowest",
        act.label: "%-10.0f steady probe load, healthy or not" % act.probe_rate,
        pas.label: "-          %d sacrificial failures before it acts" % PASSIVE_THRESHOLD,
        both.label: "%-10.0f both costs; the faster signal wins" % both.probe_rate,
    }
    for r in results:
        print("  %-30s %6.2fs %9d   %s" % (r.label, r.total, r.failed, costs[r.label]))
    print()
    print("  active : %.2fs, %d failed — %.0fx faster than the registry path and %.0fx"
          % (act.total, act.failed, base.total / act.total,
             base.failed / max(act.failed, 1)))
    print("           fewer failures. It costs %.0f probes/s across the pool, %.0f%% of"
          % (act.probe_rate, 100.0 * act.probe_rate / OFFERED_RATE))
    print("           production request rate, paid forever, healthy or not. Scale that")
    print("           to 200 instances and the probe traffic is a service of its own.")
    print("  passive: %.2fs, %d failed, ZERO probe traffic — and faster than active here,"
          % (pas.total, pas.failed))
    print("           because at %.1f req/s to that instance your own traffic is a"
          % (OFFERED_RATE / N_INSTANCES))
    print("           higher-frequency probe than your probes are. Its floor is hard:")
    print("           it can only learn from failures, so it must lose %d requests first,"
          % PASSIVE_THRESHOLD)
    print("           and it sees nothing at all on an instance nobody is calling.")
    print("  both   : %.2fs, %d failed — whichever signal arrives first."
          % (both.total, both.failed))
    print("  Every reduced configuration also CLOSED the pinned connection on ejection.")
    print("  That, not the registry update, is what finally ended layer 6.")


# ==================================================== 4 · CAP THE EJECTION
def section_cap() -> Tuple[float, float]:
    head(4, "CAP THE EJECTION — WHEN EVERY INSTANCE LOOKS BAD")
    pool = 8
    fault_at = 10.0
    fail_prob = 0.70
    horizon = 50.0
    print("  %d instances. At t=%.0fs a SHARED downstream dependency degrades and every"
          % (pool, fault_at))
    print("  instance starts failing %.0f%% of requests. No instance is broken; the pool"
          % (fail_prob * 100))
    print("  is uniformly degraded. Passive ejection is on: %d consecutive failures ->"
          % PASSIVE_THRESHOLD)
    print("  eject. This is the fault outlier detection was never designed for.\n")

    rows = []
    for cap_pct in (100, 50):
        rng = random.Random(11)
        ids = ["orders-%d" % i for i in range(1, pool + 1)]
        ejected = {i: False for i in ids}
        consec = {i: 0 for i in ids}
        pending: List[Tuple[float, str, bool]] = []
        sent = ok_n = no_upstream = 0
        rr = 0
        carry = 0.0
        t = 0.0
        full_at = None
        peak_ejected = 0
        while t < horizon:
            live = [i for i in ids if not ejected[i]]
            carry += OFFERED_RATE * TICK
            n = int(carry)
            carry -= n
            for _ in range(n):
                sent += 1
                if not live:
                    no_upstream += 1
                    continue
                target = live[rr % len(live)]
                rr += 1
                good = True if t < fault_at else (rng.random() > fail_prob)
                if good:
                    ok_n += 1
                pending.append((t + (CLIENT_TIMEOUT if not good else 0.02), target, good))
            ripe = [p for p in pending if p[0] <= t + 1e-9]
            if ripe:
                pending = [p for p in pending if p[0] > t + 1e-9]
                ripe.sort()
                for _o, i, good in ripe:
                    consec[i] = 0 if good else consec[i] + 1
                    if consec[i] >= PASSIVE_THRESHOLD and not ejected[i]:
                        if sum(ejected.values()) < int(pool * cap_pct / 100):
                            ejected[i] = True
                            peak_ejected = max(peak_ejected, sum(ejected.values()))
                            if peak_ejected == pool and full_at is None:
                                full_at = t
            t = round(t + TICK, 6)
        rows.append((cap_pct, peak_ejected, full_at, sent, ok_n, no_upstream))

    print("  max_ejection_percent  ejected  left in rotation  succeeded  no-healthy-upstream  success")
    print("  %s" % ("-" * 94))
    for cap_pct, ej, _full, sent, ok_n, nou in rows:
        print("  %-20s %8s %17d %10d %20d %8.1f%%"
              % ("%d%%" % cap_pct, "%d/%d" % (ej, pool), pool - ej, ok_n, nou,
                 100.0 * ok_n / sent))
    naive, capped = rows
    naive_rate = 100.0 * naive[4] / naive[3]
    capped_rate = 100.0 * capped[4] / capped[3]
    print()
    print("  Uncapped: ejection removed %d of %d instances by t=%.2fs and the pool went"
          % (naive[1], pool, naive[2]))
    print("  EMPTY. %d requests got 'no healthy upstream' — a total failure the instances"
          % naive[5])
    print("  themselves never had. A %.0f%%-failure partial fault became a %.1f%%-failure"
          % (fail_prob * 100, 100.0 - naive_rate))
    print("  outage, caused entirely by the protection mechanism.")
    print("  Capped at 50%%: %d instances stayed in rotation, %d requests succeeded instead"
          % (pool - capped[1], capped[4]))
    print("  of %d — %.1f%% success vs %.1f%%, and the pool never emptied. Ejection is a"
          % (naive[4], capped_rate, naive_rate))
    print("  bet that the REST of the pool is healthy. Cap the bet.")
    return naive_rate, capped_rate


# ============================================ 5 · GRACEFUL SHUTDOWN ORDERING
def section_shutdown(dereg_lag: float, detect_lag: float) -> Dict[str, int]:
    head(5, "GRACEFUL SHUTDOWN ORDERING, MEASURED")
    pool = 6
    req_duration = 0.4
    drain_wait = round(dereg_lag + 2.0, 1)
    spacing = 10.0
    print("  Rolling replacement of all %d instances, one at a time, %.0fs apart."
          % (pool, spacing))
    print("  Caller offers %.0f req/s; each request needs %.0f ms of server work."
          % (OFFERED_RATE, req_duration * 1000))
    print("  Failure DETECTION (active health checks) takes %.2fs." % detect_lag)
    print("  An explicit DEREGISTRATION reaches the caller in %.2fs — there is nothing"
          % dereg_lag)
    print("  to detect, only to propagate. The drain wait is set FROM that: %.1fs.\n"
          % drain_wait)

    def roll(mode: str) -> Tuple[int, int, int]:
        ids = ["orders-%d" % i for i in range(1, pool + 1)]
        unroute_at: Dict[str, float] = {}
        accept_until: Dict[str, float] = {}
        stop_at: Dict[str, float] = {}
        for k, i in enumerate(ids):
            t0 = 10.0 + k * spacing
            if mode == "a":                      # kill the process, tell nobody
                unroute_at[i] = t0 + detect_lag
                accept_until[i] = t0
                stop_at[i] = t0
            elif mode == "b":                    # deregister, then stop immediately
                unroute_at[i] = t0 + dereg_lag
                accept_until[i] = t0
                stop_at[i] = t0
            else:                                # deregister -> wait -> drain -> stop
                unroute_at[i] = t0 + dereg_lag
                accept_until[i] = t0 + drain_wait
                stop_at[i] = t0 + drain_wait + req_duration
        horizon = 10.0 + pool * spacing + 12.0
        inflight: List[Tuple[float, str]] = []
        sent = dropped = served = 0
        rr = 0
        carry = 0.0
        t = 0.0
        while t < horizon:
            for f, i in list(inflight):
                if f <= t + 1e-9:
                    inflight.remove((f, i))
                    served += 1
                elif t >= stop_at.get(i, 1e9) - 1e-9:
                    inflight.remove((f, i))
                    dropped += 1          # severed mid-request
            live = [i for i in ids if t < unroute_at.get(i, 1e9)]
            carry += OFFERED_RATE * TICK
            n = int(carry)
            carry -= n
            for _ in range(n):
                if not live:
                    break
                target = live[rr % len(live)]
                rr += 1
                sent += 1
                if t >= accept_until.get(target, 1e9) - 1e-9:
                    dropped += 1          # routed to a process that is already gone
                else:
                    inflight.append((t + req_duration, target))
            t = round(t + TICK, 6)
        dropped += len(inflight)
        return sent, served, dropped

    labels = {
        "a": "(a) stop the process immediately",
        "b": "(b) deregister, then stop immediately",
        "c": "(c) deregister -> wait %.1fs -> drain -> stop" % drain_wait,
    }
    print("  ordering                                       sent   served   DROPPED")
    print("  %s" % ("-" * 70))
    out: Dict[str, int] = {}
    for mode in ("a", "b", "c"):
        sent, served, dropped = roll(mode)
        out[mode] = dropped
        print("  %-45s %6d %8d %9d" % (labels[mode], sent, served, dropped))
    print()
    print("  (a) drops %d. For %.2fs after each process dies the caller is still routing"
          % (out["a"], detect_lag))
    print("      to it, and every request already in flight is severed.")
    print("  (b) drops %d. Deregistering deletes the whole DETECTION term — but the"
          % out["b"])
    print("      caller still needs %.2fs to hear about it, and you did not wait."
          % dereg_lag)
    print("  (c) drops %d. Same deregistration, plus the wait, plus the drain. The only"
          % out["c"])
    print("      new ingredient is patience. Deregistering is not a synchronous call.")
    return out


# ==================================================================== main
def main() -> None:
    print(rule())
    print("SERVICE DISCOVERY & HEALTH-AWARE ROUTING  (simulated in %d ms ticks)"
          % int(TICK * 1000))
    print(rule())

    section_registry()
    seed, base = section_window()
    unbounded = section_pinned(seed, base)

    act = run_discovery("+ active health checks", seed=seed, active=True)
    pas = run_discovery("+ passive outlier ejection", seed=seed, passive=True)
    both = run_discovery("+ both", seed=seed, active=True, passive=True)
    section_reduce([base, act, pas, both])

    section_cap()
    drops = section_shutdown(dereg_lag=PROPAGATION_DELAY, detect_lag=act.total)

    print("\n" + rule())
    print("HEADLINE  assumed %.0fs  |  measured %.2fs (%.1fx)  |  %d failed requests"
          % (LEASE_TTL, base.total, base.total / LEASE_TTL, base.failed))
    print("          with no max connection lifetime: never stopped, %d failed"
          % unbounded.failed)
    print("          shutdown ordering dropped %d / %d / %d requests (a / b / c)"
          % (drops["a"], drops["b"], drops["c"]))
    print(rule())


if __name__ == "__main__":
    main()
