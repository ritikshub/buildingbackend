---
name: checklist-capacity-math
description: A capacity and concurrency sizing worksheet — measure lambda and W from your existing RED metrics, derive real concurrency with Little's Law, size thread and connection pools, check utilization headroom against the knee, and sanity-check scale-out against Amdahl and the USL
phase: 08
lesson: 01
---

# Capacity & Concurrency Sizing Worksheet

Fill this in before you change a pool size, add replicas, promise an SLO, or sign off a load
test. Every number here already exists in your metrics; almost nobody multiplies them together.
Twenty minutes with this sheet routinely finds a pool that caps throughput at a quarter of the
target, or "headroom" that is actually a 5x latency multiplier.

**The five formulas. Everything below is these.**

```text
L = λ × W                  concurrency = throughput × latency          (Little's Law)
X = L / W                  throughput  = concurrency / latency          (the same law)
ρ = λ / capacity           utilization
W = S / (1 − ρ)            response time vs utilization                 (the knee)
X(N) = N / (1 + σ(N−1) + κN(N−1))    scale-out ceiling                  (the USL)
```

## Step 0 — Scope the system

- [ ] Name the **boundary** you are sizing: one service? one endpoint? one downstream pool?
      Every λ, W and ρ below must be measured at the **same** boundary.
- [ ] Decide whether **W includes queue wait**. Latency at the load balancer and latency inside
      the handler are different numbers; mixing them silently corrupts every result on this page.
- [ ] Name the **bottleneck resource** you are sizing against: worker slots, DB connections,
      CPU, an upstream rate limit, or a downstream dependency's own pool.
- [ ] Confirm the system is **stable** over the measurement window (queue not growing, no
      sustained 503s, no autoscaling event). Little's Law needs stability; a growing queue means
      λ_in > λ_out and the arithmetic below describes a system you no longer have.

## Step 1 — Measure λ and W

Take a busy-but-representative window (peak hour, not the weekly average).

- [ ] **λ — throughput, requests/second.** `rate(http_requests_total{...}[5m])`
      → λ = `________` req/s
- [ ] **W — mean time in system, seconds.** Use the **mean**, not the p50 and not the p99:
      `rate(http_request_duration_seconds_sum[5m]) / rate(http_request_duration_seconds_count[5m])`
      → W = `________` s
- [ ] **W_p99 for headroom judgement** (not for the arithmetic):
      `histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[5m]))`
      → p99 = `________` s   ·   **tail ratio p99/mean = `______`**
- [ ] **CPU seconds per request.** Total process CPU / requests served, or APM on-CPU time.
      → C = `________` s/req
- [ ] **Workload class:** `C / W` = `______`.
      Near **1.0 → CPU-bound** (needs cores/processes). Near **0 → I/O-bound** (needs concurrency).
      Below ~0.2, adding threads is the right move; above ~0.8 it is not.

## Step 2 — Derive real concurrency

- [ ] **L = λ × W** = `______` × `______` = **`______` requests in flight.**
- [ ] Compare against your **configured pool** (`workers`, `gunicorn -w`, `maxPoolSize`,
      `max_connections`, `maxConcurrentRequests`): configured = `______`.
- [ ] If **configured < L**, you are already shedding or queueing. Your real ceiling is
      `configured / W` = `______` req/s, regardless of what the CPU graph shows.
- [ ] Do this for **every** pool in the request path, not just the web workers: DB connections,
      HTTP client connections, Redis connections, thread pools for blocking calls. **The smallest
      pool in the chain is your actual capacity**, and it is usually not the one you tuned.

## Step 3 — Size the pools

- [ ] **Target λ** (peak + growth, not today's average) = `______` req/s.
- [ ] **Target W** (your SLO, or measured W if it is already acceptable) = `______` s.
- [ ] **L_target = λ_target × W_target** = `______` slots.
- [ ] **Headroom factor.** 1.5x is a normal default. Use 2x or more if the p99/mean tail ratio
      from Step 1 is above ~5, or if a downstream dependency is known to degrade.
      → **pool = ceil(L_target × headroom) = `______`**
- [ ] **Cores — a separate calculation.** `cores = λ_target × C` = `______`.
      Threads are for waiting; cores are for working. Do not derive one from the other.
- [ ] **Memory check.** pool × per-worker footprint = `______`. A thread stack, a connection
      buffer, and a request body all multiply by the pool size; confirm it fits the container
      limit at peak, not at idle.
- [ ] **Downstream check.** Your pool of N will offer up to N concurrent calls to every
      dependency. Confirm each dependency (and its DB) can accept `______` concurrent calls, or
      you have just moved the bottleneck one hop and made it someone else's incident.

## Step 4 — Check utilization headroom against the knee

`W = S/(1 − ρ)`. Latency multipliers, confirmed by simulation to within 2%:

| ρ    | W/S   | meaning                                        |
|------|-------|------------------------------------------------|
| 0.50 | 2.0x  | half of every request's life is already queue   |
| 0.70 | 3.3x  | comfortable operating point                     |
| 0.80 | 5.0x  | alerting threshold — not "20% headroom"         |
| 0.90 | 10.0x | +12.5% work over 0.80 bought +100% latency      |
| 0.95 | 20.0x | one spike from an incident                      |
| 0.99 | 100x  | +10% work over 0.90 bought +900% latency        |

- [ ] **ρ = λ / capacity** for the bottleneck resource = `______`.
- [ ] Target steady-state **ρ ≤ 0.70** for anything latency-sensitive; alert at **0.80**.
- [ ] **Spot the knee on the graph**: plot traffic and p99 on one time axis and compare slopes.
      - Traffic +10% → p99 +10%: on the flat part, headroom is real.
      - Traffic +10% → p99 +80%: **past the knee**, the stated headroom does not exist.
- [ ] Recompute ρ for a **degraded** dependency: if W doubles, your effective capacity halves.
      → capacity at 2×W = `______` req/s. Is that still above target λ?
- [ ] Recompute ρ during a **deploy** or an AZ loss (fewer replicas serving the same λ).
      → ρ with N−1 replicas = `______`. If that crosses 0.9, your rollout *is* the incident.
- [ ] Every queue and pool in the path is **bounded**, and shedding load (fast 503 / 429) is
      preferred over unbounded growth. Past saturation, extra concurrency adds only latency.

## Step 5 — Sanity-check scale-out (Amdahl + USL)

Only worth doing if the plan is "add workers/replicas/shards".

- [ ] Estimate the **serial fraction σ**: what part of each unit of work is genuinely
      serialized? A global lock, a single-writer table, a leader, a sequential startup phase,
      one shared counter. σ = `______`.
- [ ] **Amdahl ceiling = 1/σ = `______`x.** Compare with the speedup you are promising.
      Reference: σ = 5% caps you at 20x, and 1,024 workers reach only 19.6x — 1.9% efficiency.
- [ ] Take **three load-test points** at different worker counts (e.g. N = 4, 16, 64) and fit
      σ and κ, or at minimum check the shape: is throughput per worker falling faster than
      Amdahl predicts? → κ ≈ `______`.
- [ ] **USL peak = sqrt((1 − σ)/κ) = `______` workers.** Scaling past it *reduces* throughput.
- [ ] **The alarm:** if measured throughput ever **falls** as you add capacity, stop adding
      capacity. That is coherency cost, and the fix is to remove the shared thing — a hot row,
      a distributed lock, a leader, a cache everyone invalidates — not to add more workers.

## Step 6 — Write it down

- [ ] Record in the service's README or runbook: measured λ, W (mean and p99), C, derived L,
      chosen pool sizes with the arithmetic that produced them, target ρ, and the date.
- [ ] Add an alert on **ρ > 0.80** for the bottleneck resource, and on **L approaching pool
      size** (in-flight requests / pool size), which fires earlier than latency does.
- [ ] Export **in-flight requests** as a gauge if you do not already. It is the one term of
      Little's Law that most services never publish, and it is the fastest saturation signal
      you can have.
- [ ] Re-run this sheet when λ grows 2x, when W changes by more than 30%, or when a
      dependency is added to the request path.

## Decision shortcut

> Measure λ and W from the metrics you already have; **L = λW** is your real concurrency and
> almost nobody knows theirs. Size pools from `L × headroom` and cores from `λ × CPU-per-request`
> — two separate numbers. Keep the bottleneck under **70% utilization**, because at 80% you are
> already at a 5x latency multiplier and 10% more traffic doubles it. Bound every queue.
> And if throughput falls when you add workers, the problem is coordination, not capacity.
