---
name: checklist-health-checks-and-shutdown
description: Ship a service whose health signals help your automation instead of weaponising it — probe separation, dependency classification, probe tuning numbers, and the graceful-shutdown sequence step by step.
phase: 09
lesson: 08
---

# Health checks & graceful shutdown — pre-ship checklist

Run this before a service takes production traffic, and again any time you add a dependency.
Every item exists because skipping it has caused a real outage.

## 1 · Probe separation

- [ ] Three **separate** endpoints exist: `/startupz`, `/healthz` (liveness), `/readyz` (readiness).
- [ ] They are **not** aliases of each other. One endpoint wired to all three probes means a
      dependency failure becomes a restart.
- [ ] **Liveness checks nothing external.** No database, no cache, no downstream HTTP call, no
      DNS lookup. Not even "just a fast ping". Search the handler for a client object; if you
      find one, it's wrong.
- [ ] Liveness reflects real in-process progress (worker-loop heartbeat, event-loop tick), not
      a bare `return 200` — or accept that a deadlock will go undetected.
- [ ] Readiness returns 503 while the process is **draining** (see section 5).
- [ ] Startup probe covers the *whole* boot: config load, pool warm, cache prime, model load.
- [ ] Neither probe is behind authentication. The node agent has no credentials.
- [ ] Probe routes are excluded from RED metrics and access logs, or they will dominate both.
- [ ] Responses carry `Cache-Control: no-store`.

## 2 · Dependency classification

- [ ] Every dependency is written down as **hard** or **soft**, in the repo, before an incident.
- [ ] **Hard** = cannot serve a meaningful response without it → appears in readiness.
- [ ] **Soft** = can degrade (skip the feature, serve stale, return partial) → returns 200 with
      `status: degraded`, plus a log line and a metric. Never affects the status code.
- [ ] Nothing you merely *write to asynchronously* (analytics sink, metrics backend, audit
      queue) is classified hard.
- [ ] A dependency that is itself checking *its* dependencies is not in your readiness path —
      transitive health checks chain failures across the whole architecture.

## 3 · Check hygiene

- [ ] Every dependency check has an explicit **timeout**, smaller than the probe's
      `timeoutSeconds`, which is itself smaller than `periodSeconds`.
- [ ] Check results are **cached with a TTL** (5–10 s is typical).
      Do the arithmetic for your fleet: `replicas × (1 / periodSeconds)` = QPS of pure health
      traffic. 40 replicas at 1/s = 40 QPS before a single user request.
- [ ] Concurrent probes share one in-flight check (single-flight), not one query each.
- [ ] The cache TTL is counted as part of your detection budget — it is added latency.
- [ ] A failed check is cached too, and the TTL is short enough that recovery isn't delayed.
- [ ] The check does real but *cheap* work (`SELECT 1`, a pool-acquire) — never a business query.

## 4 · Probe tuning numbers

```text
detection      ≈ periodSeconds × failureThreshold + timeoutSeconds
worst case      = periodSeconds × (failureThreshold + 1) + timeoutSeconds
blip tolerated  = periodSeconds × (failureThreshold − 1)
```

- [ ] **Liveness slow and forgiving** — e.g. `period 10 / timeout 2 / threshold 3` → acts in
      ~32 s, shrugs off a 20 s pause. It should almost never fire.
- [ ] **Readiness fast and twitchy** — e.g. `period 3 / timeout 1 / threshold 2` → out of
      rotation in ~7 s, back in on the first success.
- [ ] **Startup generous** — `failureThreshold × periodSeconds` exceeds your worst cold boot,
      with margin. Exceeding it produces a crash loop that looks like a broken image.
- [ ] With a startup probe configured, `initialDelaySeconds` is 0 everywhere.
- [ ] Coming back is harder than leaving (higher healthy threshold than unhealthy) so an
      instance can't flap.

## 5 · The shutdown sequence

In this order. Step 2 is the one that gets skipped.

- [ ] **0.** A `SIGTERM` handler is installed. Without one, the default action kills the
      process instantly and everything below is moot.
- [ ] **1.** On `SIGTERM`, flip a flag so readiness returns 503 **immediately** — and keep
      serving.
- [ ] **2.** **Wait** while still serving, long enough for every load balancer and kube-proxy
      to notice (`preStop: sleep 5`). Requests already routed to you must still succeed.
- [ ] **3.** Stop accepting: close the listening socket; refuse new work.
- [ ] **4.** Send `Connection: close` on responses during the drain, so keep-alive clients
      holding a pooled socket reconnect to a healthy instance.
- [ ] **5.** Finish in-flight requests with a deadline. Track an in-flight counter; don't guess.
- [ ] **6.** Close connection pools, stop background workers and consumers.
- [ ] **7.** **Flush telemetry** — log buffers, span exporter, metrics push. Batched telemetry
      dies in memory otherwise, and it is exactly the data describing this shutdown.
- [ ] **8.** `exit 0`.
- [ ] `terminationGracePeriodSeconds` > preStop sleep + longest request + flush, with headroom.
- [ ] The load balancer's **deregistration delay** (AWS) is no larger than the grace period.
- [ ] Verified by watching a real rollout: zero connection resets, zero 5xx attributable to it.

## 6 · Anti-patterns to grep for

- [ ] Liveness that opens a database connection. **The** classic fleet-killer.
- [ ] A single `/health` endpoint used for every probe and for the load balancer.
- [ ] A `tcpSocket` probe on an HTTP service — it passes on a deadlocked process forever.
- [ ] Readiness with no timeout on its checks: the dependency hangs, so the probe hangs.
- [ ] Readiness returning 503 for a soft dependency, shedding capacity for a partial problem.
- [ ] `exit()` in a signal handler — nothing drains, nothing flushes.
- [ ] Alerting a human on a single instance failing readiness. That is the system working.
- [ ] A health endpoint that returns internal versions, config, or connection strings.

> ## Decision shortcut
>
> **"Would I want a human to `kill -9` this process right now?"**
> Yes → it belongs in **liveness**. Almost nothing does.
> "No, but stop sending it traffic for a while" → **readiness**. Almost everything does.
> "It's still booting" → **startup**.
> If the answer depends on a machine you don't own, it is *never* liveness.
