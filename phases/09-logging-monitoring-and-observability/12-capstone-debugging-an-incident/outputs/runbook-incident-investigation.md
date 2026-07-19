---
name: runbook-incident-investigation
description: The on-call funnel — what to query at each stage of a production incident, in Prometheus, Loki and Tempo, plus mitigation options and a postmortem template.
phase: 09
lesson: 12
---

# Incident investigation runbook

Open this when you are paged. Work top to bottom. **Mitigate before you understand** — the
goal of the first ten minutes is a healthy SLI, not a correct theory. Replace `$SVC`,
`$WIN` (usually `5m`) and `$TID` as you go.

## 0 · First 60 seconds

- [ ] **Acknowledge** the page. **Declare** in the channel: what is broken, since when, who
      is driving. **Fix nothing yet** — read the alert: which SLI, what burn rate.
- [ ] Open the SLO dashboard, the RED dashboard, and the deploy annotation feed.

## 1 · Detect — confirm it is real, size it, timestamp it

```text
# Error-budget burn rate. >14.4x on 5m AND 1h = page-worthy (2% of a 30-day budget per hour).
sum(rate(http_requests_total{service="gateway",status=~"5.."}[$WIN]))
  / sum(rate(http_requests_total{service="gateway"}[$WIN])) / (1 - 0.999)

# Everyone, or one slice? Never skip: this splits "outage" from "one bad shard".
sum by (region, version, route) (rate(http_requests_total{status=~"5.."}[$WIN]))
```

- [ ] Confirm real users are affected — edge metrics, not internal ones.
- [ ] Write down the **onset time**. You need it for MTTD and for change correlation.

## 2 · Triage — which service, and is it cause or symptom?

```text
sum by (service) (rate(http_requests_total[$WIN]))                            # Rate
sum by (service) (rate(http_requests_total{status=~"5.."}[$WIN]))
  / sum by (service) (rate(http_requests_total[$WIN]))                        # Errors
histogram_quantile(0.99,
  sum by (service, le) (rate(http_request_duration_seconds_bucket[$WIN])))    # Duration
```

- **Identical rate, errors and p99 in two services** → the upstream one is reporting, not
  causing. Follow the call graph down.
- **A service with a higher error ratio than its callers** → callers are masking with retries
  or fallbacks; that service is closer to the fault.
- **The deepest service that is still slow** is the suspect. Everything below it that is fast
  is eliminated, third parties included.

## 3 · When the cause metrics look fine

CPU normal, memory normal, disk normal, dependencies fast — and it is still slow. **This is
the common case, not the weird one.** Requests are queued on something the kernel cannot see.
Check every in-process resource *as a resource*:

```text
db_pool_connections_in_use / db_pool_max                                      # utilization
histogram_quantile(0.99, sum by (le) (rate(pool_wait_seconds_bucket[$WIN])))  # saturation
http_server_active_requests / http_server_max_concurrency                     # in-flight
queue_depth / queue_capacity                                                  # backpressure
```

- [ ] Connection pools (database, HTTP client, Redis) — **utilization near 1.0 is a queue**.
- [ ] Thread / worker / goroutine pools, fixed-size executors, locks, semaphores.
- [ ] Client rate limiters, half-open breakers, upstream *concurrency* limits (these surface
      as latency, never as errors). Event loop, GC, scheduler — busy, but not "CPU busy".

A latency distribution **pinned flat** (p50 ≈ p99 ≈ some round number) is a queue hitting a
timeout, not a slow computation. Find the timeout, then find the queue behind it.

## 4 · Localize — one trace

```text
# Grafana: click the exemplar dot on the slow histogram bucket -> opens the trace.
http_request_duration_seconds_bucket{service="$SVC",le="3"}
# Or search the trace store: { service = "$SVC" && duration > 1s && status = error }
```

- [ ] Open the **span waterfall**; find the span owning most of the wall clock. Ask of it:
      *working or waiting?* A dominant `pool.acquire`, `lock.wait`, `queue.enqueue` or
      `connect` span means contention, not slow code.
- [ ] Copy the `trace_id`; check how many traces in the window look the same.

## 5 · Explain — the fields a span cannot carry

```text
{service="$SVC"} | json | trace_id="$TID"                                # one request's story
sum(count_over_time({service="$SVC"} | json | event="<the event>" [$WIN]))    # is it systemic?
{service="$SVC"} | json | duration_ms > 1000 | line_format "{{.event}} {{.duration_ms}}"
```

- [ ] Read the request end to end, across services, in timestamp order.
- [ ] **Then aggregate that event over the window** — one request proves nothing — and run the
      identical query over a healthy window before onset. Zero then, thousands now.

## 6 · Correlate with change

- [ ] Deploys for **every** service in the path, not just the suspect. Config and flag changes,
      migrations, dependency upgrades, certificate rotations.
- [ ] Infrastructure: node scaling, failovers, DNS, security groups. Traffic: a ramp, a batch
      job, a marketing send, a retrying client.

Onset need **not** be near the deploy. A change that consumes more of a fixed resource stays
latent until traffic removes the slack. Ask *"what changed today?"*, not *"one minute ago?"*.

## 7 · Mitigate — pick by time-to-effect, not elegance

| Option | Time to effect | Use when |
|---|---|---|
| **Roll back** the correlated deploy | ~1 min | Almost always first. Reversible, no theory needed. |
| **Flip the feature flag** off | seconds | The new path is gated and the flag is trusted. |
| **Raise the saturating limit** (pool, workers, concurrency) | 1–5 min | You know the resource and its shared budget has headroom. |
| **Scale out replicas** | 2–10 min | Bottleneck is per-replica *and* the shared dependency can absorb the fan-out. |
| **Shed load / rate-limit** | seconds | Nothing else is ready; partial service beats none. |
| **Disable retries, open the breaker** | 1 min | Amplification confirmed: attempts/requests well above 1.0. |
| **Fail over** region or replica | 5–15 min | The fault is confined to one location. |

- [ ] Change **one** thing, watch the SLI for two evaluation windows, and timestamp every
      action in the channel — that is your timeline, written for free.
- [ ] Beware shared budgets: pool size spends `max_connections`, scaling out multiplies
      connections, retries multiply load.

## 8 · Postmortem template

```markdown
# Incident YYYY-MM-DD · <one-line user-visible summary>

**Impact**      <duration> · <% requests / users> · <% of error budget spent>
**Trigger**     <the change or event that armed it>
**Cause**       <the mechanism, ending in the resource that ran out>
**Detection**   <alert> at <time>,  MTTD = <onset -> page>
**Mitigation**  <action> at <time>, MTTR = <onset -> SLI healthy>

## Timeline (UTC) — time | event | source
## Observability gaps — for every "we can't see that" moment:
| gap | what it cost | signal to add |
## Action items
| # | action | gap it closes | owner | due |
```

**Blameless**: the system allowed it; a person did not cause it. Every action item gets an
owner and a date, and every "we had no metric for that" becomes a metric. An action-item list
with no observability items means nobody asked why detection took as long as it did.

> **Decision shortcut**
> Symptom at the edge, cause in the deepest slow service. Cause metrics normal → look for a
> queue, not a computation. Latency pinned flat → that is a timeout; find its queue. A deploy
> correlates → roll back first, understand second. Attempts/requests > 1.0 → retries are now
> part of the problem. And if you finish without adding a signal, the next one takes just as long.
