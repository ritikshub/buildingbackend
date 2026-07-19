---
name: checklist-capacity-review
description: A quarterly capacity review worksheet — measure the per-instance number, compose the headroom stack, validate last quarter's forecast, and produce a fleet size and a dollar figure you can defend in a budget meeting.
phase: 11
lesson: 12
---

# Checklist: the quarterly capacity review

In the room: the engineer who owns the service, whoever carries the pager, whoever signs for
the cloud bill. Ninety minutes, no slides. You are producing **one number and the assumptions
it rests on**. If you cannot fill in Step 2, stop and go run a load test — everything below is
arithmetic on top of that one measurement.

## Step 0 — Write down the objective (5 min)

- [ ] Latency SLO, as a percentile and a threshold: `p99 <= ___ ms`.
- [ ] Availability SLO and its window (Phase 9 Lesson 09).
- [ ] The failure you must survive, as a sentence:
      *"Lose any one availability zone, at peak, without breaching the SLO."*

> Without Step 0 you do not have a capacity target, you have a preference. Every number below
> derives from these three lines; if they change, the fleet changes.

## Step 1 — Convert the business metric to technical load (10 min)

The step teams skip. Without it you cannot forecast, because nobody forecasts req/s.

```text
active users (daily or monthly)      = ____________
requests per active user per period  = ____________     <- MEASURE, do not estimate
-------------------------------------------------------
average req/s = users x requests / period_seconds  =  ____________

  worked example
  4,200,000 daily actives x 28 requests each = 117.6M req/day = 1,661 req/s average
```

- [ ] Both sides use the **same definition of "active"** (analytics DAU and your metrics
      backend disagree by 10-30% at most companies). Record queries-per-request too.

## Step 2 — Measure the per-instance number (20 min, mostly waiting)

**Not** the load test's maximum. The highest rate whose p99 still meets Step 0.

```bash
# Open loop, ONE instance, >= 120 s per step. Record p99 at each rate.
for rate in 20 30 40 50 55 60 65 70 75 80 85 90; do
  echo -n "$rate req/s -> "
  vegeta attack -rate="${rate}/1s" -duration=120s -targets=targets.txt \
    | vegeta report -type=json | jq -r '.latencies.p99 / 1000000 | floor'
done
```

| record | value | note |
|---|---|---|
| saturation throughput | ____ req/s | where throughput stops rising — **do not plan on this** |
| **usable throughput** | ____ req/s | highest rate with p99 inside the SLO — **the input** |
| usable fraction | ____ | usable / saturation; expect **0.6–0.8** |
| binding resource | CPU / mem / IO / conns / downstream | Lesson 01 |
| cold-instance penalty | ____% for ____ s | run the sweep again on a cold box |

- [ ] Steps ran **>= 120 s** each (30 s flatters you — queues need time to reach steady
      state), **open-loop** (closed-loop harnesses hide queueing; Phase 8 Lesson 14), against
      the **current** build.

> Usable fraction above 0.85 means your SLO is too loose or your service-time distribution is
> unrealistically tight. Check the shape, not the mean: CV² = 1 → CV² = 2 at an identical mean
> cost 14% of usable capacity in the reference model.

## Step 3 — Establish peak, not average (10 min)

| record | value |
|---|---|
| average req/s (Step 1) | ____ |
| **routine peak** req/s (worst 15-min bucket, events excluded) | ____ |
| peak-to-average ratio | ____ (**2–4x** consumer; higher if regionally concentrated) |
| event peak req/s (marketing sends, launches, media events) | ____ |
| retry amplification seen in the last incident | ____x |

- [ ] Peak measured over **>= 28 days** at **<= 15-minute** resolution — hourly averages hide
      the spike. p95 is not peak: 5% of buckets is ~21 hours a month.
- [ ] Known one-off events **excluded from the routine peak** and listed separately.
- [ ] A shared calendar with marketing/product for scheduled demand events exists.
      *(The single highest-value capacity artifact at most companies.)*

## Step 4 — Compose the headroom stack (15 min)

Each row **divides the per-instance budget**. Never multiply the demand — keeping the factors
separate is what makes each independently arguable.

```text
required throughput R = <routine peak>                            = ______ req/s

  step                        per-instance budget    typical   instances
  0  naive (saturation)       U_sat                  --        ceil(R/U_sat) = ____
  1  + latency knee           U_safe                 0.6-0.8   ceil(R/...)   = ____
  2  + survive 1 of N         U_safe x (N-1)/N       0.67 @ 3  ceil(R/...)   = ____
  3  + deploy surge           ... x (1 - surge)      0.75-0.90 ceil(R/...)   = ____
  4  + forecast p90           R x p90/p50            1.03-1.15 ceil(R'/...)  = ____
  5  + balance across N       round up to a multiple of N                    = ____

  knee from Step 2 (measured) · surge from your rollout's maxUnavailable
  p90/p50 from Step 5 (measured) · survival from Step 0's sentence

  reference model: 45 -> 63 -> 95 -> 126 -> 133 -> 135   (a 3.00x multiplier, 33% util)
```

| domains N | max steady util | you buy | combined with a 0.71 knee |
|---|---|---|---|
| 2 | 50.0% | 2.00x | 35.5% |
| **3** | **66.7%** | **1.50x** | **47.3%** |
| 4 | 75.0% | 1.33x | 53.2% |
| 6 | 83.3% | 1.20x | 59.2% |

- [ ] Decide explicitly: **multiply** steps 2 and 3, or take `max()`? Multiplying costs more
      and assumes an AZ can fail during a deploy. Deploys are when instances die, so these
      events are **not** independent. Write down which you chose and why.
- [ ] Regions (Lesson 10): active-active across 2 regions means each carries **everything** —
      a 2x on top of the above. Say which model you are buying.
- [ ] Cross-check with Little's Law: `busy workers = peak x mean_service_seconds` divided by
      `workers_per_instance x U_safe/U_sat` must reproduce row 1.

## Step 5 — Validate last quarter's forecast (10 min)

The only agenda item that improves the model. Do this **before** producing a new forecast.

- [ ] Chart last quarter's forecast against actual; say the error out loud as a percentage.
- [ ] Fit trend + weekly seasonality on `log(daily peak)`; **exclude known one-off events** or
      they become permanent phantom growth. Residual sd gives `p90/p50 = exp(1.2816 x sd)`,
      which is Step 4's row 4.
- [ ] **Forecast horizon must exceed lead time:**

| capacity type | lead time | notes |
|---|---|---|
| on-demand instances | minutes | what autoscaling handles (Lesson 13) |
| **service quota increase** | days–weeks | support ticket + a human; **audit quarterly** |
| committed-use / reserved term | weeks | a forecast you signed your name to |
| scarce hardware (GPU, specific families) | weeks–months | plan two quarters out |

- [ ] Audit quotas every quarter, **in the failover region too**, and raise each to what a
      full regional failover would need:
      `aws service-quotas list-service-quotas --service-code ec2 --output table`

## Step 6 — Price it, and test the correlated failure (10 min)

- [ ] Tabulate each candidate family: vCPU, usable req/s, instances, $/month, $/M requests.
- [ ] Compare families on **cost per unit of your work**, never vCPU count or sticker price.
- [ ] Expect an **interior optimum**: tiny instances waste a fixed platform tax (runtime, log
      shipper, sidecar) per box; large ones lose throughput to USL coherency (Lesson 02).
- [ ] Commit to your **floor** (reserved/savings plans), buy the peak on demand.
      Over-committing is worse than under-committing — you pay either way.
- [ ] Spot share: ____%. **Simulate AZ loss AND reclamation together**, not each alone:

```text
instances after losing 1 of N zones     = ____
              after reclamation as well = ____
capacity they carry                     = ____ req/s
margin against peak                     = ____%   <- must be comfortably positive
```

> Spot reclamation is a **correlated** failure: one pool, one price signal, every instance in
> it leaves inside the same two minutes. Spreading spot across zones does not decorrelate it —
> the correlation runs along the pool axis. Count it as a failure domain, not a discount.

## Step 7 — Kubernetes fleets only (5 min)

- [ ] Cluster capacity is the **sum of `requests`**, not of usage — a cluster at 40% usage can
      be 100% *scheduled*. Set `requests` to the p95 of actual usage.
- [ ] `limits` is where the kernel **throttles**: check
      `container_cpu_cfs_throttled_seconds_total` before blaming a slow dependency. Memory has
      no throttling, only OOMKill — set `requests == limits` for latency-sensitive services.

## Step 8 — The four artifacts you leave with

1. [ ] **Forecast vs actual** for last quarter, error stated as a percentage.
2. [ ] **The headroom stack table**, with any changed factor flagged and explained.
3. [ ] **Cost per million requests**, quarter over quarter. *A rise with flat traffic is a code
       regression nobody caught — treat it like a failing test.*
4. [ ] **The ask**, with the business metric attached: *"We forecast 5.1M daily actives at p90
       = 168 instances = $20,800/month, and our failover-region quota tops out at 140."*

## Red flags — stop the meeting if you see these

| symptom | what it actually means |
|---|---|
| per-instance number came from a spec sheet or a guess | no model; go to Step 2 |
| usable fraction > 0.85 | SLO too loose, or you measured a mean and ignored the shape |
| fleet sized to "the knee at peak" | latency modelled, failure ignored — this is the incident |
| deploy surge not in the stack | your rollout removes capacity you never bought |
| forecast horizon < lead time | cannot trigger an order in time; the forecast is decorative |
| spot > 0, no combined-failure test | an untested correlated failure domain |

> ## Decision shortcut
>
> **Headroom is set by the failure you must survive, not by average load.** Measure the
> throughput at which your SLO still holds — not the maximum — then divide by `(N-1)/N` for the
> domain you must lose, again for deploy surge, once more for forecast error. The product is
> typically **2.5–3.5x** naive sizing, landing steady state near **45-50%** utilization. That is
> not waste; it is the zone you are going to lose. If you cannot show this table you cannot
> defend the number, and the fleet gets cut by someone holding half the model.
