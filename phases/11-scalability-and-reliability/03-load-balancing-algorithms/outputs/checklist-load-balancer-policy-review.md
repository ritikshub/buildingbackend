---
name: checklist-load-balancer-policy-review
description: For the engineer choosing or auditing a routing policy — at design review, during a migration, or at 03:00 when the p99 is up and the request-rate graph is flat.
phase: 11
lesson: 03
---

# Checklist: Load-Balancer Policy Review

For the engineer choosing or auditing a routing policy — at design review, during a
migration, or at 03:00 when the p99 is up and the request-rate graph is flat. Every number
below was measured by this lesson's `code/load_balancing.py`; the run parameters are printed
by the program itself.

**Scope:** which backend a request is sent to. Not health-check design (Lesson 4), not
service discovery (Lesson 5), not proxy deployment (Phase 10 L09).

---

## 0. Is the balancer implicated? — 90 seconds

Round-robin's signature is that **nothing looks wrong**. Three or more of these means yes.

- [ ] **Per-instance request rate is flat, and latency is not.** Equal counts prove nothing;
      measured, identical counts (0.04% spread) hid a **24.14% spread in actual work**.
- [ ] **p99 is a large multiple of p50 while the fleet is far from saturated.** Measured:
      **538 ms p99 against a 16.8 ms p50 (32×)** with the fleet at **33% of capacity**.
- [ ] **CPU or busy-time is bimodal across instances.** Measured: one instance at **87.9%**
      while the other seven averaged **30.4%**.
- [ ] **Queue depth is non-zero on one instance and zero on the rest.** Under least-conn on
      the identical stream, max queue depth anywhere was **0**.
- [ ] **Requests wait while capacity is idle.** The direct test:
      `queued_while_another_backend_idle / total`. Measured under RR: **31.1%** (6,271 of
      20,174). Under least-connections on the same stream: **0**.

```bash
# per-instance skew — if these diverge, count is not load
promtool query instant $PROM 'sum by (pod) (rate(http_requests_total[1m]))'
promtool query instant $PROM 'sum by (pod) (rate(container_cpu_usage_seconds_total[1m]))'
promtool query instant $PROM 'max by (pod) (envoy_cluster_upstream_rq_active)'
# the ratio that matters more than either
promtool query instant $PROM 'histogram_quantile(0.99, ...) / histogram_quantile(0.50, ...)'
```

**If per-instance request rate is flat and per-instance CPU is not, stop looking at the
application.** That gap is the balancer, and it is arithmetic, not opinion.

---

## 1. Pick the policy — decision table

| What signal you actually have | Policy | Its failure mode | Measured |
|---|---|---|---|
| Nothing; no shared state | random | max load ~ log n / log log n | **6.50×** mean at n=10,000; 36.8% idle |
| A local counter | round-robin / WRR | equalises COUNT, not load | 24.14% work spread; p99 **900 ms** |
| Your own outstanding requests | least-connections | lags; rewards fast failure; herds | **50.3%** into a black hole |
| Observed latency | peak EWMA | an instant 500 is the best score | **90.6%** into a black hole |
| Two random samples | **P2C / least-request** | needs error awareness; capped at d/n | **3.50 vs 7.92** max load at n=100k |
| The request's key | consistent hash | traffic skew; no load awareness | **1.41×** plain, **1.25×** bounded |

- [ ] **Default: least-request with `choice_count: 2`.** Measures load, no global state,
      degrades gracefully on stale data, bounds any single bad backend at `d/n`.
- [ ] **Never round-robin when request costs vary or instances are heterogeneous.** Both are
      always true above a handful of machines.
- [ ] **Never a global argmin ("least loaded") across many balancers.** See §3.
- [ ] **Hashing only when you can name what breaks without affinity** — cache hit rate,
      in-memory session, shard lock. Then take the load bound with it.

---

## 2. Every load-aware policy needs an error signal — non-negotiable

A backend that fails instantly has the fewest outstanding requests and the lowest latency in
the fleet. It will win every comparison it enters.

- [ ] **Outlier detection is enabled** alongside the load-aware policy. Without it, measured
      traffic into a black hole was **50.3%** (least-conn) and **90.6%** (peak EWMA) versus
      round-robin's blind 12.5%.
- [ ] **Failures are scored as slow, not fast.** Recording a failure as a 2,000 ms sample
      took 90.6% → **1.1%**. Adding passive ejection took it to **0.5%**.
- [ ] **`max_ejection_percent` is set** so ejection cannot remove the fleet (Envoy default
      10%). Ejecting everything is a self-inflicted outage.
- [ ] **A panic threshold exists.** Below ~50% healthy, route to all hosts: a fleet you
      believe is 90% dead is usually a broken health check.
- [ ] **Fast 5xx are counted.** A 3 ms error and a 3 s timeout are both failures; only one of
      them looks like a failure to a latency-based signal.

---

## 3. Staleness and herding

- [ ] **Know how old your load view is.** Local in-flight counters are current; xDS load
      reports, control-plane metrics and scraped gauges are not.
- [ ] **If the view is shared and periodic, do not use a deterministic argmin.** Measured
      with 32 backends and a 250 ms view (475 requests per interval):

| policy | p50 | p99 | max queue |
|---|---|---|---|
| least-connections, fresh | 14.2 ms | 93.0 ms | 0 |
| least-connections, 250 ms stale | 77.4 ms | **1,501.9 ms** | **230** |
| P2C, fresh | 15.9 ms | 96.0 ms | 3 |
| P2C, 250 ms stale | 29.1 ms | **162.2 ms** | 21 |

- [ ] **Do not look for herding in averages.** The busiest backend still took **3.89%** of
      traffic against an even 3.12%. Herding is an instant, not a total.
- [ ] **Randomise anything periodic and fleet-wide** — health-check intervals, retry backoff,
      cache TTLs, cron. Correlation is the hazard; jitter is the fix.

---

## 4. Config reference — the knob and its default

```text
envoy     lb_policy: LEAST_REQUEST                 # least_request_lb_config.choice_count = 2
          ^ Envoy's "least request" IS power-of-two-choices. choice_count 1 = plain random.
          outlier_detection.consecutive_5xx 5, base_ejection_time 30s,
                            max_ejection_percent 10, interval 10s
          common_lb_config.healthy_panic_threshold 50
          RING_HASH + common_lb_config.consistent_hashing_lb_config.hash_balance_factor 125
          ^ 125 = cap each host at 1.25x the mean. Unset = plain ring, no bound.
          MAGLEV — prefer over RING_HASH: fewer keys disrupted for the same memory.

nginx     default                = smooth weighted round-robin (not naive WRR)
          least_conn;            = least outstanding requests
          random two least_conn; = P2C  (nginx >= 1.15.1)
          hash $key consistent;  = ring, NO load bound
          least_time             = nginx Plus only

haproxy   balance roundrobin (default) | leastconn | random(2) | first
          balance uri + hash-type consistent
          ^ random(2): the 2 is d. `first` is deliberately unbalanced (scale-down).

grpc      pick_first (DEFAULT — one connection to one backend; a trap behind L4)
          round_robin | weighted_round_robin (xDS + ORCA utilization reports)

ipvs      -s rr | wrr | lc | wlc | sh
aws alb   load_balancing.algorithm.type = round_robin (default)
                                        | least_outstanding_requests
finagle   P2CLeastLoaded (default) | P2CPeakEwma
```

---

## 5. Mitigations during an incident

- [ ] **Switch round-robin → least-request(2).** Measured p99 **538 ms → 136 ms** on a fleet
      with one degraded instance, with no other change.
- [ ] **Force-eject a suspected grey-failure host** rather than reasoning about it. Confirm
      `max_ejection_percent` first.
- [ ] **Do not add instances to fix a slow instance.** Under round-robin the ceiling is
      `n × slowest_capacity`: measured **267 req/s out of 733 req/s of real capacity, 64%
      unreachable**, and a ninth instance leaves that share unchanged.
- [ ] **Do not raise timeouts.** A doomed request then occupies a worker for longer
      (Phase 8 L11).
- [ ] **If you just enabled hashing, check for a hot key before blaming the ring.** One key
      at **9.6%** of traffic cannot be balanced by any number of virtual nodes.
- [ ] **Set `hash_balance_factor` (or equivalent) rather than removing affinity.** Bounded
      loads gave exactly **1.25×** for about **2%** of key affinity.

---

## 6. Permanent fixes — file before closing

- [ ] **Least-request with `choice_count: 2` as the fleet default**, outlier detection on.
- [ ] **Failures scored as slow samples** in any latency-weighted policy.
- [ ] **Delete static weights**, or add a job that reconciles them with measured capacity.
      Weights rot silently; nothing checks them against reality.
- [ ] **Instrument the two signals nobody graphs:** per-instance *busy time* (not request
      rate) and `queued_while_another_backend_idle`. The first exposes §0; the second is the
      direct measurement of a routing failure.
- [ ] **Alert on the p99/p50 ratio per instance**, not on p99 alone. A slow member moves the
      ratio long before it moves the aggregate.
- [ ] **Load-test with a heterogeneous fleet.** A test where every backend is identical
      cannot reproduce any failure in this checklist. Deliberately slow one instance by 3×
      and assert the policy routes around it.
- [ ] **Load-test with a fast-failing backend.** Make one instance return 500 in 0 ms and
      assert its traffic share falls. This is the test that catches the death spiral, and
      almost nobody runs it.

---

## 7. Post-incident questions

1. What was the per-instance *busy-time* spread when the alert fired? If you cannot answer,
   the first fix is instrumentation, not capacity.
2. Was the balancer's load view local or shared, and how old was it? Multiply staleness by
   arrival rate: that is how many requests one wrong decision commits.
3. If a backend had failed *fast* instead of slowly, would traffic have moved toward it or
   away from it? Prove it in a load test this week.
4. Which policy is actually configured in production — not which one is in the design doc?

---

**Sources:** Mitzenmacher, *The Power of Two Choices in Randomized Load Balancing*, IEEE TPDS
12(10), 2001 · Azar, Broder, Karlin & Upfal, *Balanced Allocations*, SIAM J. Comput. 29(1),
1999 · Karger et al., *Consistent Hashing and Random Trees*, STOC 1997 · Mirrokni, Thorup &
Zadimoghaddam, *Consistent Hashing with Bounded Loads*, SIAM J. Comput. 47(3), 2018 ·
Eisenbud et al., *Maglev*, NSDI 2016.
