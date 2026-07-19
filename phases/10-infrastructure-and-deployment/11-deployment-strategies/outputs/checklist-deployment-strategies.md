---
name: checklist-deployment-strategies
description: Choose a rollout strategy from your utilisation and traffic volume rather than from habit — capacity arithmetic, canary sample sizing, automated abort criteria, and the rollback questions you must answer before you start.
phase: 10
lesson: 11
---

# Deployment strategy — pre-rollout checklist

Work through this once per service, and again whenever traffic grows, the fleet is
resized, or you add a schema change to a release. Every item is here because
skipping it has produced a real outage.

Keep the four numbers from the measured comparison in view. Identical fleet,
identical traffic, identical bad version, four rollout paths:

```text
strategy      user errors   detect  mitigate   peak exposure   min capacity   peak inst
recreate            9,689      25s       47s            100%             0%          10
rolling               452      40s       82s             75%            80%          11
blue-green            162      30s       32s            100%           100%          20
canary                 20      40s       42s              5%           100%          11
```

Blue-green detected fastest of the three that got a signal and still cost 8.1x more
than the canary. **Blast radius is exposure x time.**

---

## 1 · Before you choose a strategy

- [ ] Write down **steady-state utilisation at peak** — offered req/s divided by fleet
      capacity req/s. Not average. Peak. Everything below depends on this number and
      almost nobody has it written down.
- [ ] Write down **instance startup time**: process start to first Ready probe passing,
      including config load, pool warm and cache prime. This is your downtime under
      recreate and your wave duration under rolling.
- [ ] Write down **request rate on the endpoint you care about**, not fleet-wide. Canary
      sizing uses this and it is usually much smaller than the headline number.
- [ ] Write down your **error budget** (1 − SLO) and the **burn rate** you alert on. If
      you do not have an SLO, you cannot have an automated abort, and everything below
      degrades to a human watching a graph.
- [ ] Decide whether **two versions may run at once**. If a lock, a singleton scheduler
      or an exclusive file makes that unsafe, `Recreate` is correct and you are buying
      downtime deliberately. Write down why.

## 2 · Capacity arithmetic (do this before touching a config)

```text
capacity during deploy = (replicas − maxUnavailable) × per-instance capacity
rho during deploy      = offered load / capacity during deploy
latency multiplier     = 1 / (1 − rho)          for rho < 1
requests with nowhere to go = (offered − capacity) × rollout duration   for rho >= 1
```

- [ ] Compute `rho` during the deploy at **peak** offered load. If it is above ~0.8, you
      have a latency event on every deploy. If it is above 1.0, you have an outage.
- [ ] `maxUnavailable` rounds **DOWN**, `maxSurge` rounds **UP**, both from the replica
      count. 25% of 10 replicas is maxUnavailable 2 and maxSurge 3. Check the rounding
      on small fleets — 25% of 3 replicas is maxUnavailable 0.
- [ ] **Above ~70% utilisation, set `maxUnavailable: 0`** and pay for `maxSurge`. It
      holds capacity at 100%, and with a larger wave size it is often *faster* as well.
- [ ] `maxUnavailable: 0` with `maxSurge: 0` is rejected by the API. There is no free
      option — you spend either capacity or money. Choose on purpose.
- [ ] Confirm the cluster has room for the surge pods. A `maxSurge` that cannot be
      scheduled turns a rolling update into a stalled one.
- [ ] Re-run this arithmetic after any traffic growth. A config that was safe at 45%
      utilisation is an outage generator at 85%, and nothing will tell you it changed.

## 3 · Canary sizing (the step that is usually skipped)

- [ ] State `p0`, the **baseline error rate**, from real data — not from the SLO.
- [ ] State `p1`, the **smallest regression you insist on catching**. Derive it from the
      error budget: a rate that burns your budget faster than you can tolerate.
- [ ] Compute the required sample size:

```text
n >= (z_alpha*sqrt(p0*q0) + z_beta*sqrt(p1*q1))^2 / (p1 − p0)^2

z_alpha = 1.645  (one-sided, 5% false-abort rate)
z_beta  = 0.842  (80% power)
```

- [ ] Compute bake time: `n / (canary_fraction × req/s)`. If it is unacceptably long,
      **raise the canary percentage** — never shorten the bake.
- [ ] Sanity-check the **expected error count** at `p1`. If it is near 1, the analysis is
      noise. Measured: 180 samples with 1.44 expected errors gave 41.9% power and
      promoted a genuinely bad release 5 times out of 8.
- [ ] **Simulate the config** before trusting it. Run a few thousand synthetic canaries
      against a known-bad and a known-good version and read the actual power and
      false-alarm rate. Discreteness makes the closed-form numbers optimistic: one
      config that cleared the required `n` still reached only 76% power, and another
      showed a 7.8% false-alarm rate against a nominal 5%.
- [ ] Confirm the analysis query is **scoped to the canary**. A fleet-wide query dilutes
      the signal by every instance still on the old version, and that dilution is the
      difference between detecting at 5% exposure and detecting at 40%.
- [ ] Enforce a **minimum-sample gate**. No decision below it, no matter how extreme the
      ratio looks — 12 requests can show a 166x burn rate on a healthy release.

## 4 · The abort must be automatic

- [ ] The abort criterion is a **query against an SLI with a threshold**, not a person.
      Tie it to the same error budget your alerts use so there is one definition of bad.
- [ ] Use at least two signals: **error-budget burn rate** and a **latency ratio** against
      the baseline. A release that fails fast can look healthy on latency alone; a
      release that hangs can look healthy on error rate alone.
- [ ] Measure **time from decision to traffic actually moving** — controller reconcile,
      config push, connection drain. That lag is part of your blast radius.
- [ ] Compare against your human loop. Modelled at 300 s page-to-ack plus 240 s to
      diagnose and decide, the same detection cost 19 errors automated versus 380 with a
      human on a 5% canary — and 182 versus 7,993 on a blue-green cutover.
- [ ] Test the abort path. An abort that has never run is an abort that will fail on a
      stale credential, a rate-limited API or a controller that is itself mid-upgrade.

## 5 · Bake time and give-up time

- [ ] Set **`minReadySeconds`** — a pod must stay Ready this long before the rollout
      proceeds. The default of 0 lets the controller march over a pod that passed one
      probe and then crashed.
- [ ] Set **`progressDeadlineSeconds`**. Note it marks the rollout Failed; it does not
      roll back. Automatic rollback is your controller's job.
- [ ] Bake time must cover the failure classes that need time: memory and file-descriptor
      leaks, cold caches warming, periodic work (cron, batch flush) firing at least once,
      connection-pool saturation, and the statistical floor from section 3.
- [ ] Bake at **every weight step**, not just the first. 5% healthy does not imply 50%
      healthy — saturation effects only appear at load.

## 6 · Rollback: answer these before you start

- [ ] **Does the rollback path include the database?** Blue-green and router flips give
      you instant *code* rollback and no schema rollback. If the release migrated the
      schema, "roll back" may have no meaning.
- [ ] Any schema change is **expand → migrate → contract**, with the contract step in a
      later release than the expand step. Never in the same deploy.
- [ ] Under rolling, **both versions serve simultaneously** — for minutes. Confirm N/N+1
      compatibility in both directions: old code must tolerate new data and new code must
      tolerate old data.
- [ ] Know your **point of no return** and when the rollout crosses it. Recreate: t=0.
      Rolling: when the old ReplicaSet reaches 0. Blue-green: when blue is deleted —
      so do not delete it on a timer shorter than your detection time. Canary: none.
- [ ] Know your **rollback duration**, separately from detection. Measured: a router flip
      mitigated in 2 seconds from decision; a rolling undo took 42 seconds because it had
      to boot replacement instances.
- [ ] Confirm the previous artifact is still **pullable by digest**. A rollback that has
      to rebuild is not a rollback.

## 7 · Routing and draining

- [ ] **Connection draining / deregistration delay** is set longer than your slowest
      request. Without it, `maxUnavailable` costs you the in-flight requests on the
      instances being replaced, on top of the capacity.
- [ ] `terminationGracePeriodSeconds` > drain window + longest request, with headroom.
- [ ] The process handles SIGTERM: fail readiness, **keep serving**, wait for the load
      balancer to notice, then stop accepting and finish in-flight work.
- [ ] Canary and baseline are **comparable**: same instance type, same zone spread, same
      warm-up state where possible. A canary on cold nodes with an empty connection pool
      is being compared against a warm fleet, and the bias runs both ways.

## 8 · Do not confuse these two

| | Canary | A/B test |
|---|---|---|
| Measures | system health: errors, latency, saturation | user behaviour: conversion, retention, revenue |
| Compares | new build vs old build | product variant B vs variant A |
| Duration | minutes | days to weeks |
| Decided by | an automated threshold on an SLI | a product decision on an experiment result |
| Outcomes | promote / abort | ship B / keep A |
| Assignment | may be arbitrary | must be sticky per user |

- [ ] They may share a router. They must not share a conclusion. A green A/B test says
      nothing about release safety; a green canary says nothing about whether the
      feature is any good.

## 9 · Shadow traffic, if you use it

- [ ] Every **write** is stubbed: database, cache, message publish, outbound HTTP, email,
      payment, metrics increment. The shadow copy will do whatever the request says.
- [ ] Dependency load is accounted for — shadowing doubles it on anything not stubbed.
- [ ] Understand what it cannot tell you: nobody received the response, so shadow traffic
      can never confirm correctness from the user's point of view. It is not a canary.
