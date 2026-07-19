---
name: checklist-autoscaling-policy-review
description: Paste this into the wiki.
phase: 11
lesson: 13
---

# Autoscaling Policy Review Checklist

Paste this into the wiki. Run it against one autoscaling policy at a time. Every number
below came from the measured runs in `code/autoscaling.py`; substitute your own once you
have measured them.

A policy that fails items 1, 2, 5 or 8 is an incident with a delay fuse.

## 0 · Fill this in before reviewing anything

| Field | Your value | Where to get it |
|---|---|---|
| Service / ASG / Deployment | | |
| Scaling metric(s), setpoint, `min`/`max` | | policy config |
| Metric scrape interval + averaging window | | agent config, query |
| Decision (evaluation) interval | | `--horizontal-pod-autoscaler-sync-period`, alarm period |
| Boot to *listening*, listening to *warm* | | measure both, do not guess |
| Pool size per instance | | app config |
| Downstream `max_connections` | | `SHOW max_connections;` |

**Total dead time** = scrape + (window / 2) + (interval / 2) + boot + warm = `______ s`

**Reaction period** = decision interval = `______ s`

> If total dead time > 2 x reaction period, this loop is oscillating right now whether or
> not anyone has noticed. Reference measurement: 60 s dead time against a 60 s reaction
> period settled (swing 2, 100.0% SLO); 210 s produced a swing of 139 instances on flat
> traffic, 539 launches instead of 33, and 57.3% SLO.

## 1 · The metric

- [ ] **Does the metric go UP when the service is in trouble?** If it is CPU, no — errors
      are cheap, CPU falls during an incident, and the loop scales in.
- [ ] **Is there a concurrency or queue metric alongside CPU, with the autoscaler taking the
      MAXIMUM?** This is the single highest-value change available.
- [ ] **Latency is not a primary signal.** It is not monotonic in capacity — it rises for
      slow dependencies, locks, bad plans and GC pauses, none of which more instances fix.
      Use it as a veto on scale-in only.
- [ ] **If scaling on RPS: is request cost uniform across this group's endpoints?**

| Workload | Primary | Secondary | Never |
|---|---|---|---|
| CPU-bound HTTP (render, compress, crypto) | CPU 50-60% | in-flight per instance | latency |
| I/O-bound HTTP (calls a DB or another service) | in-flight per instance | CPU as a `max()` partner | CPU alone |
| Queue worker | queue depth or oldest-message age per replica | | CPU |
| Mixed / unknown | `max(CPU, in-flight)` | | any single signal |

Measured, same workload, dependency degrading 12 ms -> 120 ms:

```text
metric                        fleet in slow phase   worst rho    SLO     cost
CPU 60%                             15 / 25            2.33     45.1%    1251
in-flight = 1.2 per instance       200 / 266           0.87     98.7%    9857
backlog age 0.30 s                  52 / 86            1.63     76.3%    2809
max(CPU, in-flight)                 42 / 64            1.42     86.4%    2627   <- ship this
```

## 2 · The controller arithmetic

- [ ] **Does the policy exclude still-warming instances from the metric aggregation?**
      `desired = ceil(replicas x metric / target)` uses the `replicas` you have now against a
      metric from the fleet you had a dead time ago, so booting instances get ordered twice.
      AWS ASG: `--estimated-instance-warmup` = measured boot + warm. Kubernetes: make
      `readinessProbe` mean *warm*, not *listening*.
      Fixing only this took swing 395 -> 19, launches 1216 -> 60, SLO 49.4% -> 80.0%.

## 3 · Asymmetry — out fast, in slow

- [ ] Scale-out stabilisation / cooldown is **0 s** or near it.
- [ ] Scale-in stabilisation / cooldown is **>= 300 s**.
- [ ] Scale-out rate limit exists (bounds one bad scrape), e.g. **2x or +4 per 60 s**.
- [ ] Scale-in rate limit exists, e.g. **10% of the fleet per 60 s**.
- [ ] Hysteresis / tolerance is **+/- 10%** around the setpoint (HPA's default; keep it).

The cost of being too small is an outage; the cost of being too large is money. Never give
them the same time constant.

### Starting values

```text
target                    50-60% CPU, or 60-70% of the concurrency limit
scale-out stabilisation   0 s
scale-in stabilisation    300 s
scale-out rate limit      100% per 60 s, or +4 instances per 60 s, whichever is larger
scale-in rate limit       10% per 60 s
tolerance / dead band     +/- 10%
metric window             60 s     <- longer ONLY if the signal is genuinely noisy
```

- [ ] **Metric averaging window is not being used to hide oscillation.** Smoothing is lag,
      and lag is the disease. A 300 s window adds ~150 s of dead time; measured, it removed
      6 instances of swing and cost **13.3 points of SLO**. Reach for it last.

## 4 · Guards

- [ ] **Never scale in while the error rate is elevated**, and **keep the block for
      `metric_delay + window + interval` after errors clear** — the cheap low-CPU samples
      from the outage are still inside the averaging window. Without a guard, a 25-minute
      dependency outage took a fleet from 18 to 9 and cost **270 s of further SLO breach
      after the dependency recovered** (6.9% of all requests). With the guard: 0 s, 0.0%.
- [ ] **Scale-in protection** is set by workers that have picked up long-running jobs, and
      cleared when the job finishes.
- [ ] **Termination grace period > slowest request**, with connection draining at the LB and
      graceful shutdown in the process. Otherwise every scale-in drops in-flight work.

## 5 · The wrong-tier check (do this multiplication now, on real numbers)

```text
max_replicas  x  pool_size_per_instance   =   ______ connections wanted
downstream max_connections                =   ______ granted
```

- [ ] Wanted <= granted, with headroom for migrations, admin sessions and replicas.
- [ ] You know where the downstream throughput curve **peaks**, not just where it errors:
      past the Universal Scalability Law peak, more connections mean LESS throughput.

```text
 44 connections ->  537 q/s   <- peak
100 connections ->  459 q/s   (85% of peak)
200 connections ->  324 q/s   (60% of peak)
300 connections ->  247 q/s   (46% of peak)  <- max_connections
```

- [ ] If wanted > granted, or if the fleet can push past the peak, a connection proxy
      (PgBouncer, RDS Proxy) is in the path — or `max_replicas` is lowered until it is.
- [ ] **Serverless**: reserved concurrency is set to a number the data tier survives. A
      function at 1,000 concurrent executions opens 1,000 connections and there is no pool.

## 6 · Cold start

- [ ] The load balancer uses **slow start** (weight proportional to capacity), not an equal
      share the moment the port opens. Measured: slow start 99.3% SLO, full share 97.3%,
      gated-until-warm 98.7% — gating discards the quarter-instance you had exactly when you
      needed it. The readiness check must assert warm, not listening.
- [ ] Where boot time dominates dead time, one of these is in place: warm pools, a smaller
      image, or overprovisioning with low-priority placeholder pods.
- [ ] Capacity is planned in **instance-seconds**. An instance that boots 90 s at 0 req/s and
      warms 60 s at 25% is worth **10% of an instance over its first 150 s**, billed at 100%.

## 7 · The floor and the ceiling

- [ ] `max_size` is set (spend limit + blast-radius limit) and reconciled with section 5.
- [ ] **`min_size` survives the loss of one failure domain, at peak, with NO scaling action.**
      Work it: `peak_rps / per_instance_rps / (zones - 1)` rounded up, per zone.
- [ ] `min_size` keeps you below the utilisation knee with enough headroom to absorb a spike
      while the loop catches up over its full dead time.
- [ ] Nobody's failover runbook contains the words "the autoscaler will handle it." During a
      zone or region event the control plane is saturated, the capacity pool is contended
      and quotas bind. `InsufficientInstanceCapacity` is a real answer.

> **Autoscaling is for cost, not for reliability.** Tune `max_size` to bound the bill; tune
> `min_size` to bound the outage.

## 8 · Scheduled + reactive

- [ ] Known, recurring shape (daily ramp, weekly peak) has a **scheduled floor**, so the
      reactive loop only ever handles the residual. Measured over a simulated day with a
      known campaign send: reactive alone 98.56% SLO and 1,187,371 requests outside the
      objective; two scheduled floors took that to **100.00% and zero, for 20.1% more spend**.
- [ ] Known one-off events (campaign, launch, sale, migration) have a scheduled action in the
      calendar, created when the event was scheduled and not the morning of.
- [ ] Predictive scaling, if enabled, ran in forecast-only mode long enough to confirm the
      forecast would have been right.

## 9 · Observability of the loop itself

- [ ] Fleet size and demand are graphed **on the same axes**, for a full week. Oscillation is
      invisible on a utilisation dashboard and obvious the moment the two are overlaid.
- [ ] Launches per hour is graphed — the cheapest oscillation detector there is (33/hour
      stable vs 539/hour oscillating, same traffic). Scaling events annotate the latency
      dashboard.
- [ ] Alert on "fleet at `max_size` for more than N minutes" and on "scale-in occurred while
      error rate was elevated" — the second should be impossible; if it fires, the guard is
      broken.

## 10 · The retry-storm rule

- [ ] Ops know that **adding capacity during a retry storm is the wrong direction.** A retry
      ends by succeeding, not by being served quickly, and new instances open new connections
      to the tier that is already the bottleneck.
- [ ] There is a load-shedding switch, it is documented in the runbook, and it has been
      exercised under load. Measured: autoscaling through a retry storm produced **0 req/s of
      goodput, never recovering, for 172 instance-minutes**; shedding with the fleet pinned
      produced **400 req/s and recovery 5 s after the trigger cleared, for 60**.
- [ ] The incident runbook's first scaling instruction is "pin the fleet," not "scale out."

## Quick commands

```bash
# Kubernetes: what did the HPA see, and what did it decide?
kubectl describe hpa <name>                     # read the Events and Conditions
kubectl get hpa <name> -o jsonpath='{.spec.behavior}' | jq

# How long does a pod really take to become Ready?
kubectl get pod <pod> -o json | jq '[.status.conditions[] | {type, lastTransitionTime}]'

# AWS: every scaling action today, with the reason; and is the warmup set?
aws autoscaling describe-scaling-activities --auto-scaling-group-name <asg> \
  --max-items 50 --query 'Activities[].{t:StartTime,cause:Cause}' --output table
aws autoscaling describe-policies --auto-scaling-group-name <asg> \
  --query 'ScalingPolicies[].{name:PolicyName,warmup:EstimatedInstanceWarmup}'

# Postgres: the wrong-tier check, live
psql -c "SHOW max_connections;"
psql -c "SELECT count(*), state FROM pg_stat_activity GROUP BY state;"
```
