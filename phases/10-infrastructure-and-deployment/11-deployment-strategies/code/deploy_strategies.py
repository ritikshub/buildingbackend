#!/usr/bin/env python3
"""Deployment strategies measured: recreate, rolling, blue-green, canary.

Lesson: phases/10-infrastructure-and-deployment/11-deployment-strategies/docs/en.md
Model: N instances behind a weighted router, stepped one simulated second at a
time. Burn-rate alerting follows the multiwindow burn-rate method in the Google
SRE Workbook ch. 5 ("Alerting on SLOs"); rounding of maxSurge/maxUnavailable
follows the Kubernetes Deployment API reference (RollingUpdateDeployment).
Sample sizing is the standard normal-approximation power calculation for a
one-sided test of a proportion against a known baseline. Stdlib only, seeded.
"""

from __future__ import annotations

import math
import random
from collections import deque
from statistics import NormalDist

SEED = 7

# ---------------------------------------------------------------- the fleet --
N = 10  # instances in the fleet
PER_INSTANCE = 40  # req/s one instance can serve before it drops work
FLEET_CAP = N * PER_INSTANCE  # 400 req/s
OFFERED = 240  # req/s of steady user traffic  -> 60% utilisation
STARTUP = 20  # seconds from "launch" to "ready to serve"

P_BASE = 0.0005  # 0.05% - the old version's error rate
P_BAD = 0.0600  # 6.00% - the new version's error rate. This deploy is bad.

# --------------------------------------------------------- the abort signal --
SLO = 0.999  # availability objective
BUDGET = 1 - SLO  # 0.1% of requests may fail
BURN = 14.4  # "fast burn": consume a 30-day budget in ~2 days
THRESHOLD = BUDGET * BURN  # 1.44% error rate over the window
WINDOW = 30  # seconds of trailing data the alert looks at
EVAL_EVERY = 5  # seconds between evaluations
MIN_SAMPLES = 200  # refuse to decide on fewer requests than this
ROLLBACK_LAG = 2  # seconds from decision to the router/controller acting

CANARY_PCT = 0.05  # 5% of traffic to the canary
WARMUP = 60  # seconds of healthy traffic before the deploy starts
HORIZON = 400  # seconds of observation after the deploy starts

rng = random.Random(SEED)


def binom(n: float, p: float) -> int:
    """Count of failures in n Bernoulli trials. Seeded, so re-runs match."""
    n = int(round(n))
    if n <= 0:
        return 0
    return rng.binomialvariate(n, p)


def hms(t: float | None) -> str:
    return "     -" if t is None else f"{t:5.0f}s"


# ============================================================================
# The rollout controllers. Each one answers three questions every second:
# how many old instances are ready, how many new ones are, and what fraction
# of user traffic the router is currently sending to the new version.
# ============================================================================


class Rollout:
    label = "rollout"

    def tick(self, t: int) -> None: ...
    def abort(self, t: int) -> None: ...

    def state(self) -> tuple[int, int, int]:
        """(old_ready, new_ready, instances_you_are_billed_for)"""
        raise NotImplementedError

    def frac_new(self) -> float:
        """Router weight on the new version. Default: spread over ready pods."""
        old, new, _ = self.state()
        total = old + new
        return new / total if total else 0.0


class Recreate(Rollout):
    """Stop all, start all. Downtime == startup time, by construction."""

    label = "recreate"

    def __init__(self) -> None:
        self.old, self.new, self.booting = N, 0, 0
        self.phase, self.ready_at = "pending", 0

    def tick(self, t: int) -> None:
        if self.phase == "pending" and t >= 0:
            self.old, self.booting = 0, N  # everything dies at once
            self.ready_at, self.phase = t + STARTUP, "boot-new"
        elif self.phase == "boot-new" and t >= self.ready_at:
            self.booting, self.new, self.phase = 0, N, "serving-new"
        elif self.phase == "boot-old" and t >= self.ready_at:
            self.booting, self.old, self.phase = 0, N, "rolled-back"

    def abort(self, t: int) -> None:
        # Rolling back a recreate is another recreate: a second full outage.
        self.new, self.booting = 0, N
        self.ready_at, self.phase = t + STARTUP, "boot-old"

    def state(self) -> tuple[int, int, int]:
        return self.old, self.new, self.old + self.new + self.booting


class Rolling(Rollout):
    """Batches governed by maxSurge and maxUnavailable.

    Simplified from the real Deployment controller, but it holds the two
    invariants that decide whether a deploy hurts:
        available  >=  N - maxUnavailable      (the capacity floor)
        total      <=  N + maxSurge            (the cost ceiling)
    """

    label = "rolling"

    def __init__(self, surge: int = 3, unavail: int = 2) -> None:
        self.surge, self.unavail = surge, unavail
        self.old, self.new, self.booting = N, 0, 0
        self.boot_kind: str | None = None
        self.ready_at = 0
        self.direction = "forward"
        self.started = False

    def _wave(self, t: int) -> bool:
        w = self.surge if self.surge > 0 else self.unavail
        want = (N - self.new) if self.direction == "forward" else (N - self.old)
        k = min(w, want)
        if k <= 0:
            self.booting, self.boot_kind = 0, None
            return False
        self.booting = k
        self.boot_kind = "new" if self.direction == "forward" else "old"
        # Terminate old capacity only while we stay above the availability floor.
        headroom = max(0, (self.old + self.new) - (N - self.unavail))
        if self.direction == "forward":
            self.old -= min(self.unavail, k, self.old, headroom)
        else:
            self.new -= min(self.unavail, k, self.new, headroom)
        self.ready_at = t + STARTUP
        return True

    def tick(self, t: int) -> None:
        if not self.started and t >= 0:
            self.started = True
            self._wave(t)
            return
        if self.booting and t >= self.ready_at:
            if self.boot_kind == "new":
                self.new += self.booting
            else:
                self.old += self.booting
            self.booting = 0
            surplus = (self.old + self.new) - N  # scale back to the replica count
            if surplus > 0:
                if self.direction == "forward":
                    self.old -= min(surplus, self.old)
                else:
                    self.new -= min(surplus, self.new)
            self._wave(t)

    def abort(self, t: int) -> None:
        if self.boot_kind == "new":
            self.booting = 0  # in-flight replacements never served a user
        self.direction = "backward"
        self._wave(t)

    def state(self) -> tuple[int, int, int]:
        return self.old, self.new, self.old + self.new + self.booting


class BlueGreen(Rollout):
    """Two complete environments; the deploy is a router change."""

    label = "blue-green"

    def __init__(self) -> None:
        self.blue, self.green, self.booting = N, 0, 0
        self.weight = 0.0
        self.phase, self.ready_at = "pending", 0

    def tick(self, t: int) -> None:
        if self.phase == "pending" and t >= 0:
            self.booting, self.ready_at, self.phase = N, t + STARTUP, "boot-green"
        elif self.phase == "boot-green" and t >= self.ready_at:
            self.green, self.booting = N, 0
            self.weight = 1.0  # cut over: 100% of users, in one step
            self.phase = "cut-over"

    def abort(self, t: int) -> None:
        self.weight = 0.0  # cut back: 100% of users, in one step
        self.phase = "rolled-back"

    def state(self) -> tuple[int, int, int]:
        return self.blue, self.green, self.blue + self.green + self.booting

    def frac_new(self) -> float:
        return self.weight


class CanaryRollout(Rollout):
    """One new instance, a small traffic weight, and a decision to make."""

    label = "canary"

    def __init__(self, pct: float = CANARY_PCT) -> None:
        self.pct = pct
        self.old, self.new, self.booting = N, 0, 0
        self.weight = 0.0
        self.phase, self.ready_at = "pending", 0

    def tick(self, t: int) -> None:
        if self.phase == "pending" and t >= 0:
            self.booting, self.ready_at, self.phase = 1, t + STARTUP, "boot-canary"
        elif self.phase == "boot-canary" and t >= self.ready_at:
            self.new, self.booting, self.weight = 1, 0, self.pct
            self.phase = "canary-serving"

    def abort(self, t: int) -> None:
        self.weight = 0.0
        self.phase = "aborted"

    def state(self) -> tuple[int, int, int]:
        return self.old, self.new, self.old + self.new + self.booting

    def frac_new(self) -> float:
        return self.weight


class NoDeploy(Rollout):
    """The counterfactual: what the same window costs with no deploy at all."""

    label = "no deploy"

    def state(self) -> tuple[int, int, int]:
        return N, 0, N


# ============================================================================
# One simulator, four rollouts. Nothing changes between runs except the path.
# ============================================================================


def run(rollout: Rollout, scope: str = "fleet", human_lag: int | None = None,
        horizon: int = HORIZON) -> dict:
    """Step the fleet a second at a time and count what users actually saw.

    scope='fleet'  : the alert reads the whole fleet's error ratio (diluted).
    scope='canary' : the alert reads only requests the canary served.
    human_lag      : if set, the rollback waits this many extra seconds after
                     detection (page -> ack -> diagnose -> decide -> execute).
    """
    win: deque[tuple[int, float, int]] = deque()
    errors = dropped = bad_served = caused = 0
    peak_billed, min_serving, peak_exposure = N, N, 0.0
    detect_at = abort_at = mitigated_at = None
    lag = ROLLBACK_LAG + (human_lag or 0)

    for t in range(-WARMUP, horizon + 1):
        rollout.tick(t)
        if abort_at is not None and t == abort_at:
            rollout.abort(t)
        old, new, billed = rollout.state()
        w = rollout.frac_new()

        srv_new = min(OFFERED * w, new * PER_INSTANCE)
        srv_old = min(OFFERED * (1 - w), old * PER_INSTANCE)
        miss = OFFERED - srv_new - srv_old
        e_new, e_old = binom(srv_new, P_BAD), binom(srv_old, P_BASE)

        if t >= 0:
            errors += e_new + e_old + int(round(miss))
            caused += e_new + int(round(miss))  # errors this DEPLOY is responsible for
            dropped += int(round(miss))
            bad_served += int(round(srv_new))
            peak_billed = max(peak_billed, billed)
            min_serving = min(min_serving, old + new)
            peak_exposure = max(peak_exposure, w)
            if abort_at is not None and t >= abort_at and w == 0.0:
                if mitigated_at is None and (old + new) * PER_INSTANCE >= OFFERED:
                    mitigated_at = t

        obs, err = (srv_new, e_new) if scope == "canary" else (srv_new + srv_old,
                                                              e_new + e_old)
        win.append((t, obs, err))
        while win and win[0][0] <= t - WINDOW:
            win.popleft()

        if t >= 0 and t % EVAL_EVERY == 0 and detect_at is None:
            n = sum(o for _, o, _ in win)
            k = sum(e for _, _, e in win)
            if n >= MIN_SAMPLES and k / n > THRESHOLD:
                detect_at = t
                abort_at = t + lag

    return {
        "label": rollout.label,
        "errors": errors,
        "caused": caused,
        "dropped": dropped,
        "bad_served": bad_served,
        "detect": detect_at,
        "mitigate": mitigated_at,
        "peak_exposure": peak_exposure,
        "min_cap": min_serving / N,
        "peak_inst": peak_billed,
    }


# ============================================================================
# 1 - the fleet, the traffic, the bad version
# ============================================================================

print("== 1 · THE FLEET, THE TRAFFIC, AND THE BAD VERSION ==")
print(f"  fleet          {N} instances x {PER_INSTANCE} req/s = {FLEET_CAP} req/s capacity")
print(f"  offered load   {OFFERED} req/s  ->  utilisation {OFFERED / FLEET_CAP:.2f}")
print(f"  instance boot  {STARTUP} s from launch to ready (identical for every strategy)")
print(f"  old version    error rate {P_BASE:.4%}")
print(f"  NEW version    error rate {P_BAD:.4%}   <-- {P_BAD / P_BASE:.0f}x worse. Nobody knows yet.")
print(f"  SLO {SLO:.1%} availability -> error budget {BUDGET:.2%}")
print(f"  abort signal   {BURN}x burn rate = error ratio > {THRESHOLD:.2%} over a "
      f"{WINDOW}s window,")
print(f"                 evaluated every {EVAL_EVERY}s, minimum {MIN_SAMPLES} requests, "
      f"{ROLLBACK_LAG}s to act")
base = run(NoDeploy())
print(f"  counterfactual: the same {HORIZON}s window with NO deploy costs "
      f"{base['errors']} errors")
print()


# ============================================================================
# 2 - blast radius, measured four ways
# ============================================================================

print("== 2 · BLAST RADIUS: THE SAME BAD VERSION, FOUR ROLLOUT PATHS ==")
print("  identical fleet, identical traffic, identical bad version.")
print("  the only difference is the path the deploy takes through the fleet.")
print()
rows = [
    run(Recreate()),
    run(Rolling(surge=3, unavail=2)),
    run(BlueGreen()),
    run(CanaryRollout(), scope="canary"),
]
print("  strategy      user errors   dropped   detect  mitigate   peak exp"
      "   min cap   peak inst")
for r in rows:
    print(f"  {r['label']:<12}    {r['caused']:>8}  {r['dropped']:>8}"
          f"   {hms(r['detect'])}    {hms(r['mitigate'])}"
          f"     {r['peak_exposure']:>5.0%}     {r['min_cap']:>5.0%}"
          f"      {r['peak_inst']:>3}")
print("  'user errors' = requests the DEPLOY broke: dropped for want of capacity,")
print(f"  plus failures served by the new version. ({base['errors']} more happened in")
print("  the same window at the old version's baseline rate, deploy or no deploy.)")
print()

by = {r["label"]: r for r in rows}
can = by["canary"]
print("  requests SERVED BY THE BAD VERSION before it was pulled:")
for r in rows:
    print(f"    {r['label']:<12} {r['bad_served']:>7}")
print()
print("  blast radius is exposure x time, and strategies trade one for the other:")
print(f"    blue-green detected in {by['blue-green']['detect']}s "
      f"— fastest of the three that got a signal, at 100% of users exposed")
print(f"    canary     detected in {can['detect']}s "
      f"— slower, at {CANARY_PCT:.0%} of users exposed")
print(f"    and the canary still wins, because {can['detect']}s x 5% beats "
      f"{by['blue-green']['detect']}s x 100%:")
for name in ("recreate", "rolling", "blue-green"):
    ex, ce = by[name]["caused"], can["caused"]
    print(f"    canary vs {name:<11} {ex:>6} user errors -> {ce:>4}"
          f"   = {ex / max(ce, 1):>6.1f}x smaller blast radius")
print()
print(f"  recreate detected fastest of all ({by['recreate']['detect']}s) and it "
      f"bought nothing:")
print(f"  {by['recreate']['dropped']} of its {by['recreate']['caused']} errors came "
      f"from having ZERO instances, and")
print(f"  rolling back a recreate is another recreate — a second {STARTUP}s outage.")
print(f"  during those first {STARTUP}s the fleet served 0 requests, so the error RATIO")
print("  had a zero denominator and the alert could not fire at all: a ratio-based")
print("  SLI can stay silent through the worst minute of your year.")
print()


# ============================================================================
# 3 - rolling capacity arithmetic
# ============================================================================

print("== 3 · ROLLING CAPACITY ARITHMETIC: THE DEPLOY IS THE OVERLOAD ==")
print(f"  Kubernetes rounds maxUnavailable DOWN and maxSurge UP, both from "
      f"replicas={N}.")
print(f"  invariants: available >= replicas - maxUnavailable;  total <= replicas + maxSurge")
print()
configs = [
    ("0%", "25%", 0, math.ceil(0.25 * N)),
    ("10%", "0%", math.floor(0.10 * N), 0),
    ("25%", "0%", math.floor(0.25 * N), 0),
    ("25%", "25%", math.floor(0.25 * N), math.ceil(0.25 * N)),
    ("50%", "0%", math.floor(0.50 * N), 0),
]
print("  maxUnav  maxSurge   min avail   serving cap   peak inst   waves   rollout")
plans = []
for u_s, s_s, u, s in configs:
    w = s if s > 0 else u
    waves = math.ceil(N / w)
    min_avail = N - u
    peak = N - u + s if s > 0 else N
    plans.append((u_s, s_s, min_avail, peak, waves))
    print(f"  {u_s:>7}  {s_s:>8}      {min_avail:>2}/{N}     {min_avail * PER_INSTANCE:>4} req/s"
          f"          {peak:>3}     {waves:>3}    {waves * STARTUP:>4} s")
print("  (maxUnavailable: 0 and maxSurge: 0 together is rejected by the API — you")
print("   cannot make progress without either spare capacity or lost capacity.)")
print()

loads = [(160, "40%"), (240, "60%"), (340, "85%")]
print("  utilisation DURING the deploy = offered / (min available x per-instance cap)")
print("  offered   steady   " + "".join(f"{'u' + u + '/s' + s:>11}" for u, s, *_ in configs))
for lam, util in loads:
    cells = []
    for _, _, min_avail, _, _ in plans:
        rho = lam / (min_avail * PER_INSTANCE)
        cells.append(f"{rho:>8.2f}   " if rho < 1.0 else f"{rho:>8.2f}!! ")
    print(f"  {lam:>4}/s    {util:>5}   " + "".join(cells))
print("  !! = rho >= 1.0: the deploy itself pushes the fleet into overload.")
print()
print("  W/S = 1/(1-rho), the queueing multiplier from Phase 8, at 85% steady load:")
for u_s, s_s, min_avail, _, waves in plans:
    rho = 340 / (min_avail * PER_INSTANCE)
    if rho < 1.0:
        tail = f"latency x{1 / (1 - rho):>5.1f} for {waves * STARTUP:>3} s"
    else:
        deficit = 340 - min_avail * PER_INSTANCE
        tail = (f"UNBOUNDED: {deficit:>3} req/s deficit x {waves * STARTUP:>3} s"
                f" = {deficit * waves * STARTUP:>4} shed")
    print(f"    maxUnavailable {u_s:>4}, maxSurge {s_s:>4}:  rho {rho:>5.2f}   {tail}")
print()
print("  the rule: at high utilisation, maxUnavailable > 0 means every deploy is a")
print("  self-inflicted overload. maxSurge buys the capacity back — for money.")
print()


# ============================================================================
# 4 - canary statistical power
# ============================================================================

print("== 4 · CANARY STATISTICAL POWER: THE 1% CANARY THAT DETECTS NOTHING ==")

SVC_RATE = 60.0  # req/s - a normal internal service, not a front page
Q_BASE = 0.002  # 0.20% baseline error rate
Q_BAD = 0.008  # 0.80% - 4x worse, and it will burn a 99.9% budget 8x over
ALPHA, POWER = 0.05, 0.80
TRIALS = 4000

nd = NormalDist()
z_a, z_b = nd.inv_cdf(1 - ALPHA), nd.inv_cdf(POWER)
need = math.ceil(
    (z_a * math.sqrt(Q_BASE * (1 - Q_BASE)) + z_b * math.sqrt(Q_BAD * (1 - Q_BAD))) ** 2
    / (Q_BAD - Q_BASE) ** 2
)

print(f"  service {SVC_RATE:.0f} req/s;  baseline errors {Q_BASE:.2%};  "
      f"new version {Q_BAD:.2%} ({Q_BAD / Q_BASE:.0f}x)")
print(f"  test: one-sided, alpha={ALPHA}, target power={POWER:.0%}, "
      f"z_alpha={z_a:.3f}, z_beta={z_b:.3f}")
print("  n >= (z_a*sqrt(p0*q0) + z_b*sqrt(p1*q1))^2 / (p1-p0)^2")
print(f"  REQUIRED CANARY SAMPLE SIZE = {need} requests")
one_pct_mins = math.ceil(need / (0.01 * SVC_RATE) / 60)
print(f"  at 1% of {SVC_RATE:.0f} req/s that is {need / (0.01 * SVC_RATE) / 60:.1f} "
      f"minutes of bake time. Nobody waits that long.")
print()


def analyse(observed_n: int, observed_k: int) -> tuple[float, bool]:
    """One-sided z-test of an observed error count against the known baseline."""
    if observed_n == 0:
        return 0.0, False
    p_hat = observed_k / observed_n
    se = math.sqrt(Q_BASE * (1 - Q_BASE) / observed_n)
    z = (p_hat - Q_BASE) / se
    return z, z > z_a


plans4 = [
    ("1%", 0.01, 5),
    ("1%", 0.01, one_pct_mins),
    ("5%", 0.05, 4),
    ("10%", 0.10, 5),
]


def trip_count(n: int) -> int:
    """Smallest error count that trips the test at this sample size."""
    limit = n * (Q_BASE + z_a * math.sqrt(Q_BASE * (1 - Q_BASE) / n))
    return math.floor(limit) + 1


print("  canary  bake   samples  vs need   trips at   power on BAD   false alarm   verdict")
measured = {}
for pct_s, pct, mins in plans4:
    n = int(pct * SVC_RATE * mins * 60)
    hits = sum(1 for _ in range(TRIALS) if analyse(n, binom(n, Q_BAD))[1])
    fps = sum(1 for _ in range(TRIALS) if analyse(n, binom(n, Q_BASE))[1])
    ok = "ADEQUATE" if n >= need else "UNDER-POWERED"
    measured[(pct_s, mins)] = (hits / TRIALS, fps / TRIALS)
    print(f"  {pct_s:>6}  {mins:>2}min  {n:>7}   {n / need:>6.0%}   {trip_count(n):>4} errs"
          f"        {hits / TRIALS:>6.1%}        {fps / TRIALS:>6.1%}     {ok}")
print(f"  'power on BAD' is the detection rate over {TRIALS} simulated canaries against")
print(f"  a version that really is {Q_BAD / Q_BASE:.0f}x worse; 'false alarm' is the same "
      f"test against")
print("  a version identical to baseline. Both are measured, not assumed.")
_p18, _ = measured[(plans4[1][0], plans4[1][2])]
_, _fp10 = measured[(plans4[3][0], plans4[3][2])]
print(f"  note two ways the arithmetic lies to you: the {plans4[1][0]}/{plans4[1][2]}min "
      f"row clears the required n")
print(f"  and still reaches only {_p18:.1%} power, and the false-alarm rate drifts to "
      f"{_fp10:.1%} at large n")
print(f"  against a nominal {ALPHA:.0%}. Error counts are integers; the normal "
      f"approximation is a")
print("  convenience, not a fact. Validate an analysis config by simulating it.")
print(f"  a {plans4[0][0]} canary for {plans4[0][2]} minutes is a coin flip on a "
      f"genuinely broken release.")
print()

n_small = int(plans4[0][1] * SVC_RATE * plans4[0][2] * 60)
n_large = int(plans4[2][1] * SVC_RATE * plans4[2][2] * 60)
print("  eight independent canaries of each shape, same bad version, same analysis:")
print(f"   trial    1% / 5 min  (n={n_small})              "
      f"5% / 4 min  (n={n_large})")
missed_s = missed_l = 0
for i in range(1, 9):
    ks, kl = binom(n_small, Q_BAD), binom(n_large, Q_BAD)
    zs, rs = analyse(n_small, ks)
    zl, rl = analyse(n_large, kl)
    missed_s += not rs
    missed_l += not rl
    ds = ("ABORT" if rs else "PROMOTE <-MISSED IT")
    dl = ("ABORT" if rl else "PROMOTE <-MISSED IT")
    print(f"   {i:>5}    {ks:>2} err {ks / n_small:>6.3%} z={zs:>5.2f} {ds:<20}"
          f"{kl:>2} err {kl / n_large:>6.3%} z={zl:>5.2f} {dl}")
print(f"  the version is BAD in all sixteen runs. The 1% canary promoted it "
      f"{missed_s} of 8 times;")
print(f"  the 5% canary promoted it {missed_l} of 8. Neither test changed — only n did.")
print(f"  expected errors at {Q_BAD:.2%}: {n_small * Q_BAD:.2f} in the small canary, "
      f"{n_large * Q_BAD:.2f} in the large one.")
print("  when the expected number of errors is near 1, a clean run is the MOST LIKELY")
print("  outcome for a broken release. That is the whole failure mode.")
print()
print("  RULE: canary percentage and bake time are DERIVED from traffic volume and")
print("  the effect size you need to catch. A round number like '1% for 5 minutes'")
print("  is not a policy, it is a wish.")
print()


# ============================================================================
# 5 - automated analysis and abort
# ============================================================================

print("== 5 · AUTOMATED ANALYSIS AND ABORT vs A HUMAN LOOKING AT A GRAPH ==")

LAT_BASE, LAT_BAD = 120.0, 310.0  # ms, p99 per version
LAT_RATIO_LIMIT = 1.5

print(f"  the analysis job compares the canary against the baseline every "
      f"{EVAL_EVERY}s:")
print(f"    error burn rate  = canary error ratio / error budget ({BUDGET:.2%}), "
      f"abort above {BURN}x")
print(f"    latency ratio    = canary p99 / baseline p99 "
      f"({LAT_BASE:.0f}ms), abort above {LAT_RATIO_LIMIT}x")
print(f"    both need >= {MIN_SAMPLES} canary requests before they may decide")
print()

canary = CanaryRollout()
win: deque[tuple[int, float, int]] = deque()
decided = None
print("      t   canary req   errors   err rate   burn rate   p99      lat ratio   verdict")
for t in range(-WARMUP, 90):
    canary.tick(t)
    if decided is not None and t == decided + ROLLBACK_LAG:
        canary.abort(t)
    old, new, _ = canary.state()
    w = canary.frac_new()
    srv = min(OFFERED * w, new * PER_INSTANCE)
    err = binom(srv, P_BAD)
    win.append((t, srv, err))
    while win and win[0][0] <= t - WINDOW:
        win.popleft()
    if t < 0 or t % EVAL_EVERY or decided is not None:
        continue
    n = sum(o for _, o, _ in win)
    k = sum(e for _, _, e in win)
    if n == 0:
        print(f"  {t:>5}   {0:>10}   {0:>6}   {'-':>8}   {'-':>9}   {'-':>6}"
              f"   {'-':>9}   no canary traffic yet")
        continue
    rate = k / n
    burn = rate / BUDGET
    p99 = LAT_BAD if new else LAT_BASE
    ratio = p99 / LAT_BASE
    tripped = [w for w, hit in (("burn", burn > BURN), ("latency", ratio > LAT_RATIO_LIMIT))
               if hit]
    if n < MIN_SAMPLES:
        verdict = f"WAIT ({n:.0f} < {MIN_SAMPLES} samples)"
    elif tripped:
        verdict = "ABORT on " + " + ".join(tripped)
        decided = t
    else:
        verdict = "continue baking"
    print(f"  {t:>5}   {n:>10.0f}   {k:>6}   {rate:>7.2%}   {burn:>8.1f}x   "
          f"{p99:>4.0f}ms   {ratio:>8.2f}x   {verdict}")

HUMAN_ACK, HUMAN_DIAG = 300, 240  # modelled parameters, not measurements
LONG = 900  # a window long enough to contain the human loop
base_l = run(NoDeploy(), horizon=LONG)
auto_c = run(CanaryRollout(), scope="canary", horizon=LONG)
human_c = run(CanaryRollout(), scope="canary", human_lag=HUMAN_ACK + HUMAN_DIAG,
              horizon=LONG)
auto_bg = run(BlueGreen(), horizon=LONG)
human_bg = run(BlueGreen(), human_lag=HUMAN_ACK + HUMAN_DIAG, horizon=LONG)


print()
print("  detection is identical in every row — only the time from detection to ACTION")
print(f"  changes. Human loop MODELLED (substitute your own): page->ack {HUMAN_ACK}s +")
print(f"  diagnose/decide {HUMAN_DIAG}s = {HUMAN_ACK + HUMAN_DIAG}s on top of the "
      f"{ROLLBACK_LAG}s the controller takes.")
print()
print(f"  (re-run over a {LONG}s window so the human loop fits; the automated rows differ")
print("   from section 2 only by sampling noise.)")
print()
print("  rollout       abort path      detect   mitigated   user errors   vs automated")
for label, a, h in (("canary", auto_c, human_c), ("blue-green", auto_bg, human_bg)):
    print(f"  {label:<12}  automated      {hms(a['detect'])}   {hms(a['mitigate'])}"
          f"   {a['caused']:>11}   {'—':>12}")
    print(f"  {label:<12}  human-in-loop  {hms(h['detect'])}   {hms(h['mitigate'])}"
          f"   {h['caused']:>11}   {h['caused'] / max(a['caused'], 1):>11.0f}x")
print()
print(f"  time-to-abort automated: {auto_c['mitigate']}s. Human: {human_c['mitigate']}s "
      f"— {human_c['mitigate'] / auto_c['mitigate']:.0f}x longer.")
print("  a canary without automated analysis is a slow deploy: the exposure is small")
print("  but the clock runs at human speed, and blast radius = exposure x clock.")
