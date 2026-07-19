---
name: runbook-fit-your-scalability-curve
description: For a team that scales a service horizontally and has never measured what the next doubling actually buys.
phase: 11
lesson: 02
---

# Runbook: Fit Your Scalability Curve and Find N*

For a team that scales a service horizontally and has never measured what the next
doubling actually buys. Produces two numbers — **σ** and **κ** — and one decision: the
fleet size **N\*** past which adding machines *subtracts* throughput.

`C(N) = N / (1 + σ(N−1) + κN(N−1))`   ·   `N* = sqrt((1 − σ) / κ)`

**Scope:** anything you scale by count — app instances, worker replicas, consumer group
members, shards, connections. **Not** for diagnosing a single saturated resource; if one
thing is at 100% and everything queues behind it, fix that first and come back.

---

## 0. Do you have a κ problem right now? — 5 minutes

Three or more means yes. Check these before scheduling any load test.

- [ ] **Throughput fell after a scale-out.** Total req/s down while instance count up.
- [ ] **Per-instance utilization fell too.** The discriminator. σ-limited systems pin a
      shared resource at ~100%; κ-limited systems make it **less** busy as you scale.
      Measured reference: 80.5% busy at the peak → 67.4% at 2× the fleet, −17.8% throughput.
- [ ] **Latency up, no queue found.** p99 climbing with no saturated hop to point at.
- [ ] **Nothing is erroring.** Error rate flat at baseline. No restarts, no OOM, no 5xx.
- [ ] **A previous scale-in "mysteriously helped"** and nobody wrote down why.

```bash
# throughput per instance, over the last scale event — the one plot nobody has
promtool query range $PROM 'sum(rate(http_requests_total[5m])) / count(up{job="app"})' \
  --start=$(date -u -d '-6 hours' +%s) --end=$(date -u +%s) --step=60
# fleet-wide connection count to the DB: the most common kappa term
psql -c "SELECT count(*) FROM pg_stat_activity;"   # compare to instances x pool_size
```

**If you are in an incident, jump to §6 now.** Come back for the sweep afterwards.

---

## 1. Define N. Vary one thing.

| If you scale…            | N is…                    | Hold fixed                                  |
|--------------------------|--------------------------|---------------------------------------------|
| stateless app instances  | replica count            | instance type, pool size per instance, data  |
| queue consumers          | consumer count           | partition count, batch size, prefetch        |
| DB connections           | pool_size × instances    | instance count OR pool size, not both        |
| shards                   | shard count              | rows per shard, request mix                  |

Write down what N is in one sentence before you start. If two things change between
points, you have measured nothing.

---

## 2. Design the sweep

**Rule: at least 8 levels, and the top level must be at least 2× your production fleet.**
A sweep that stops at your current size cannot find your peak — and it will fit
beautifully anyway. Measured failure: 7 well-fitted points below the knee predicted
70.2 req/s at N=64 where the truth was 83.7 — **16% wrong, in the direction that buys
hardware.**

| Production fleet | Sweep these levels                          |
|------------------|---------------------------------------------|
| 8                | 1, 2, 4, 6, 8, 12, 16, 24, 32               |
| 24               | 1, 2, 4, 8, 16, 24, 32, 48, 64              |
| 100              | 1, 4, 8, 16, 32, 50, 75, 100, 150, 200      |
| 500              | 1, 8, 32, 64, 128, 250, 500, 750, 1000      |

- Always include **N = 1**. Every ratio is normalised by it.
- Cluster extra points **around your expected knee**, not at the low end.
- Budget: `levels × repeats × (warmup + measure)`. At 3 repeats and 5 min/point,
  a 9-level sweep is about 2¼ hours of machine time.

---

## 3. Run each point

Use the load-test methodology from Phase 8 L14. Do not improvise it. Per level:

- [ ] **Load generator has ≥3× headroom.** Verify the *generator* is not the bottleneck —
      if its CPU is above ~50%, you are measuring the generator.
- [ ] **Open-loop generator**, fixed arrival rate, so a slow server cannot throttle
      your offered load (coordinated omission).
- [ ] **Warm-up discarded.** JIT, caches, pools, autoscalers. 60–120 s minimum.
- [ ] **Steady state ≥ 3 min** after warm-up. Confirm queue depth is stable, not growing.
- [ ] **≥3 repeats per level**, means reported. If repeats disagree by >5%, the harness
      is what you are measuring — fix it before fitting.
- [ ] **Autoscaling disabled** for the duration. It will fight you.
- [ ] Record per level: `N, throughput, p50, p99, shared-resource utilization`.

```text
N,throughput_rps,p50_ms,p99_ms,db_busy_pct
1,9.3,107,151,7.5
2,18.2,110,168,14.8
...
```

Keep the utilization column. It is how you tell σ from κ in §5.

---

## 4. Fit

Two parameters, bounded surface — a grid search is sufficient and auditable. Drop your
CSV into the `fit()` function from `code/scalability_law.py`; it is unchanged for real data.

```python
meas = {1: 9.3, 2: 18.2, 4: 34.9, 8: 61.4, 16: 91.3,
        24: 99.7, 32: 101.9, 48: 94.6, 64: 83.7}       # N -> req/s
sigma, kappa, _ = fit(meas)                            # 4 narrowing grid passes
n_star = math.sqrt((1 - sigma) / kappa)
```

**Reject the fit if any of these hold:**

- [ ] Worst-point relative error **> 10%**. (A good fit looks like the measured
      reference: 3.0% worst case across 16 levels spanning 64×.)
- [ ] Either parameter landed **on a search boundary** — widen the bounds and rerun.
- [ ] `κ` fits to **0** *and* your top level is below the knee — that is not "no
      coherency cost", that is "no data about it".
- [ ] Residuals are **systematically signed** (all high at low N, all low at high N) —
      the model does not describe your system; do not quote N\*.

---

## 5. Read the answer

| Fitted result                          | What it means                              | Do this                                        |
|----------------------------------------|--------------------------------------------|------------------------------------------------|
| `N*` ≥ 4× fleet                        | Room to grow. κ is not your problem yet.   | Attack σ. Re-fit after any topology change.    |
| `N*` between 1.5× and 4× fleet         | Real but not urgent.                       | Cap `maxReplicas` below `N*`. Plan κ work.     |
| `N*` < 1.5× fleet                      | **One scale event from retrograde.**       | Cap the autoscaler today. κ work is P1.        |
| `N*` < fleet                           | **You are already past the peak.**         | §6. Scale in.                                  |
| `1/σ` close to current `C(N)`          | σ-limited: flat ceiling, not a cliff.      | Shard / replicate / remove the shared step.    |
| `κ` > 0.001                            | Coordination is ~0.1% of a request or more | Find the all-to-all. §7.                       |

Sanity anchors from the measured reference run: σ = 0.0247, κ = 0.001144, N\* = 29.2
against a measured peak of 32 (**within 9%**), worst-point residual 3.0%.

---

## 6. Incident mode: you are past N\* right now

Order matters. Do not add capacity.

1. [ ] **Freeze the autoscaler.** `kubectl patch hpa <name> -p '{"spec":{"maxReplicas":<current>}}'`
       Left alone it will respond to falling throughput by scaling further out.
2. [ ] **Scale in by 25%.** Measure for 5 minutes. Throughput up = confirmed retrograde.
       Measured reference, from 2×N\*: −25% instances → **+13.1%**, −37% → **+17.8%**,
       −50% (back to N\*) → **+21.7%**, at half the cost.
3. [ ] **Repeat until throughput stops improving.** That level is your empirical N\*.
       Record it in the incident channel; it is the most valuable number of the day.
4. [ ] **Do not roll back application code.** The change was the fleet size.
5. [ ] **Shed load if still short of demand** — Phase 8 L11. Complementary, not alternative.
6. [ ] **Post-incident:** schedule the §2 sweep, clustered around the knee you just found.

---

## 7. Attack table

| Symptom / source                                    | Term | Fix                                                | Expected effect          |
|-----------------------------------------------------|------|----------------------------------------------------|--------------------------|
| One primary DB at ~100%, curve flat                 | σ    | Shard (L8), read replicas (L7), batch writes       | Raises ceiling, peak stays |
| One leader / lock / single-partition topic          | σ    | Partition the lock space, more partitions          | Raises ceiling            |
| Config service read by every instance at boot       | σ    | Cache locally, stagger boots                       | Faster deploys            |
| `instances × pool_size` connections to the DB       | κ    | **Connection pooler** (`pool_mode = transaction`)   | N×M → N×const             |
| Cache invalidation broadcast to every instance      | κ    | Shared channel, shorter TTLs, coalesce             | Quadratic → linear        |
| Full-mesh service discovery / health checks         | κ    | **Subsetting** (L5), 20–100 backends per client    | Quadratic → linear        |
| Distributed locks, lease renewal traffic            | κ+σ  | Partition, or design the lock away                 | Both terms                |
| Everything talks to everything, no obvious owner    | κ    | **Cells** (L9) — hard-partition the fleet          | κ per cell, not per fleet |

**Order of attack: κ first.** σ costs you money on a plateau you can sit on for years; κ is
a cliff whose coordinate is your fleet size, and the standard response to load — scale out —
is what pushes you over it. Measured: halving σ bought **+13.7%** but left the peak at N=32;
cutting κ 69% moved N\* from **29 to 52**; both together reached 238.0 req/s at N=96, still
climbing (**3.7×** the baseline). Honest caveat: subsetting raised the fitted σ from 0.0249
to 0.0343 — it converts a quadratic cost into a linear one, a ceiling instead of a cliff.

---

## 8. Make it stick

- [ ] **`maxReplicas` < N\*.** Write the fitted N\* in a comment next to it, with the date
      and the commit of the load test. An autoscaler that can cross your peak is a machine
      for turning a traffic spike into an outage.
- [ ] **Dashboard panel: throughput ÷ instance count, over time.** The one plot that makes
      retrograde scaling visible. Nobody has it by default.
- [ ] **Alert:** `sum(rate(requests_total[5m]))` falling while `count(up)` rising, 10 min.
- [ ] **Re-fit after** any change to fanout, discovery, connection topology, cache
      invalidation, replica count, or instance type. σ and κ are properties of the
      *topology*, not of the code, and a topology change invalidates the number.
- [ ] **Put N\* in the capacity plan**, not just the load-test report. It is the input to
      "what do we buy" (L12) and "how far may the control loop go" (L13).

---

## References

- Amdahl, G. M. *Validity of the single processor approach to achieving large scale
  computing capabilities.* AFIPS Spring Joint Computer Conference, 1967.
- Gunther, N. J. *Guerrilla Capacity Planning.* Springer, 2007. (The USL.)
