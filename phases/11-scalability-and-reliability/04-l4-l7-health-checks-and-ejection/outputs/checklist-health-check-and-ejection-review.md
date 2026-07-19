---
name: checklist-health-check-and-ejection-review
description: Run this against one service before it takes production traffic, and again after any incident where instances left rotation.
phase: 11
lesson: 04
---

# Checklist — Load-Balancer Health Check & Ejection Review

Run this against one service before it takes production traffic, and again after any
incident where instances left rotation. Every threshold below has a measured
justification in Phase 11 Lesson 04; the numbers are from a seeded simulation, so treat
them as the shape of the answer and re-measure the two marked **MEASURE THIS**.

Time: ~40 minutes for a service you know. Output: a filled table and at most three tickets.

---

## 0 · Facts to collect first

You cannot tune any of this from defaults. Fill this in before touching config.

| Fact | Where to get it | Yours |
|---|---|---|
| p50 / p99 / **p99.9 of the health endpoint** | load test or APM, on the probe path specifically | |
| p99 of a normal request | RED dashboard | |
| Does the probe share a thread pool with request handlers? | read the code | |
| Number of balancers / proxies probing this service (M) | mesh topology, sidecar count | |
| Number of backends (N) | replica count at peak | |
| Fleet capacity vs peak demand (headroom %) | capacity plan | |
| Does the balancer see responses? (no ⇒ direct server return) | LB mode | |
| What the balancer does when 100% of backends are unhealthy | **test it** | |

> **MEASURE THIS #1 — the probe path's p99.9.** It is the only number here you cannot
> copy from anyone else, and it is the one that causes outages when guessed. If the probe
> shares a thread pool with request handlers, its p99.9 *includes your queueing delay*,
> which is the coupling that turns overload into a death spiral. Give the health endpoint
> its own thread or listener and re-measure.

---

## 1 · Layer: are you balancing what you think you are balancing?

- [ ] Identify the layer of every hop: client → edge → mesh → service. Write down which
      hop makes a **per-request** decision. If none do, you have no request balancing.
- [ ] List the long-lived-connection protocols in use: gRPC, HTTP/2, WebSocket, database
      connection pools, message-broker consumers, aggressive HTTP/1.1 keep-alive.
- [ ] For each: **how long does a connection live?** If the answer is "until the next
      deploy", an L4 hop in front of it is making one decision per client per deploy.
- [ ] Graph **requests per second per instance**, not CPU and not connections. A flat
      connection graph over a spiky request graph is this lesson's entire failure mode.
- [ ] Deploy a new instance during business hours and confirm it receives traffic within
      60 s. Zero traffic for hours is the symptom; measured at exactly 0 requests in 600 s.

**If you are stuck on L4 in front of long-lived connections, pick one:**

| Fix | Cost | Notes |
|---|---|---|
| L7 proxy / mesh sidecar | proxy CPU; the proxy's bandwidth becomes the ceiling | measured 1.00x spread, new instance at full share immediately |
| Client-side balancing | client library fleet-version problem; N×M connections | see Lesson 05 for subsetting, which is the required companion |
| `max_connection_age` **+ jitter** | periodic reconnect cost | see below — jitter is not optional |
| Shorter keep-alive | handshake cost per reconnect | the accidental pre-migration configuration that hid the problem |

- [ ] If using `max_connection_age`: **jitter is configured.** Without it, connections
      opened together expire together — measured 24 simultaneous reconnects vs 2/s with
      ±10% jitter, a 12× burst, forever, on a fixed metronome.
- [ ] Confirm the reconnect is *graceful* (GOAWAY, drain, then close), not a reset.

---

## 2 · Active health check config

Set these deliberately. The defaults are not a recommendation, they are a starting point
someone else picked for a different service.

| Knob (Envoy / k8s / AWS) | Start at | Why |
|---|---|---|
| `interval` / `periodSeconds` / `HealthCheckIntervalSeconds` | **2 s** | detection is linear in it; the only cost is probe traffic |
| `timeout` / `timeoutSeconds` / `HealthCheckTimeoutSeconds` | **≥ p99.9 of probe path** | below the p99 you manufacture false ejections forever |
| `unhealthy_threshold` / `failureThreshold` / `UnhealthyThresholdCount` | **5** | false ejections go as `p^k` — exponential protection |
| `healthy_threshold` / `successThreshold` / `HealthyThresholdCount` | **5** | fail fast, recover slow; re-admit in 11 s, not 1 s |
| `interval_jitter` | **~25% of interval** | decorrelates M balancers probing in lockstep |
| `no_traffic_interval` | **60 s** | idle clusters cost less to watch |

- [ ] `timeout` is **≥ p99.9**, not ≥ p99. At the p99 (1,396 ms measured) a 1 s timeout
      fails 2.22% of healthy probes ⇒ ~94 false ejections/day across 200 backends.
- [ ] AWS only: `interval ≥ timeout + 1` is enforced. A 3 s timeout needs a ≥ 4 s interval.
- [ ] Detection arithmetic written down and accepted by the on-call team:
      `worst case = interval × (unhealthy_threshold + 1) + timeout`.
      Defaults for reference: k8s 10s/3 ⇒ **25.9 s mean, 41 s worst**;
      AWS 30s/2 ⇒ **49.8 s mean, 95 s worst**.
- [ ] Probe cost priced: `M × N / interval` probes/s. At M=6, N=200, interval=2 s that is
      **600/s**. Confirm the backends can absorb it and that it is excluded from SLI math.
- [ ] Probe traffic is excluded from your latency and error-rate dashboards.

---

## 3 · The endpoint itself (the balancer's side of the contract)

- [ ] `/healthz` is **shallow**: no database, no cache, no downstream service, no peer check.
- [ ] It answers "can **this instance** serve traffic?" — its own threads, memory, warm-up
      state, local config. Nothing shared with its peers.
- [ ] Any dependency-aware check lives on a **separate** endpoint that **pages a human**
      and does **not** feed the balancer or the readiness probe.
- [ ] Liveness and readiness use **different** endpoints. Failing readiness removes traffic;
      failing liveness **restarts the container**. Never point liveness at a deep check.
- [ ] The probe path exercises the same listener/port users take. A probe on a separate
      admin port can pass while the traffic path is dead.

> **The correlated-failure test.** Ask of every check inside the endpoint: *if this fails,
> does it fail on all N replicas in the same second?* If yes, it must not be wired to
> anything that removes capacity. One database blip otherwise ejects the whole Deployment.

---

## 4 · Passive / outlier detection

- [ ] Outlier detection is **on**. Active checks cannot see a failure off the probe path;
      passive detection ejects a fully broken backend in ~10 ms after 5 bad responses.
- [ ] `consecutive_5xx` is understood as a **total**-failure detector: at a 20% error rate
      it needs 3,705 requests and burns 741 users first, 148× the damage.
- [ ] A **success-rate** rule is configured for partial failure, with a minimum volume.
- [ ] `success_rate_request_volume` ≥ **100**. At 5 requests/window, a backend with a
      healthy 1% error rate is ejected **17.6×/hour** — 7.8 million times more often than
      the identical backend measured over 100. The quietest backend is usually the newest.
- [ ] `base_ejection_time` (30 s) × times-ejected, capped by `max_ejection_time` (300 s).
      12 ejections ⇒ 38 minutes out, not 6. Repeat offenders earn quarantine.
- [ ] If the balancer does **direct server return**, passive detection is impossible by
      construction. Document how you detect a backend returning 500s, and how long it takes.

---

## 5 · The guards (do not ship without these)

These add no capacity. They stop the balancer from discarding capacity it already has.
Measured: on-time delivery **21.3% without, 99.7% with**.

- [ ] `max_ejection_percent` = **10%** (Envoy default). Strongest single guard measured.
- [ ] `healthy_panic_threshold` = **50%** (Envoy default). Below it, route to everything —
      because if most of the fleet looks dead, the check is likelier wrong than the fleet.
- [ ] **Kubernetes has neither.** If you deploy on plain k8s Services:
      - `successThreshold` is **forced to 1** for readiness — you cannot express "recover slow"
      - nothing prevents an EndpointSlice from **emptying completely**
      - compensate with: a mesh sidecar that has these knobs, a `PodDisruptionBudget`,
        hysteresis inside the endpoint (latch unhealthy for N seconds once tripped),
        and a shallow probe that cannot fail fleet-wide
- [ ] `deregistration_delay.timeout_seconds` (AWS, default 300) reviewed: long enough to
      drain your longest request, short enough not to stall every rolling deploy.

---

## 6 · Verify, do not assume

- [ ] **Mark every backend unhealthy in staging.** Does the balancer route to all of them
      or to none? One line of config; the difference between degraded and down.
- [ ] **Run the fleet at 92% of capacity for 5 minutes.** Watch healthy-instance count.
      If it falls at all, your probe timeout is inside your loaded latency distribution.
      Measured: 20 → 0 healthy in 44 s, 23 s with nothing in rotation, from a 12-point
      step in demand on a fleet that had the capacity to serve it.
- [ ] **Kill one instance hard** (SIGKILL, not a graceful stop) and time how long traffic
      keeps being routed to it. Compare against your computed worst case.
- [ ] **Deploy during traffic** and confirm the new instance takes its share within 60 s.

> **MEASURE THIS #2 — the healthy-instance count under peak load.** A fleet that sheds
> healthy instances at 92% utilization is one demand spike away from the death spiral, and
> this is the only test that surfaces it before a customer does.

---

## 7 · Dashboard & alerts

- [ ] **Requests/s per instance** (not connections, not CPU) — the graph that would have
      ended the incident in an hour instead of a day.
- [ ] **Healthy-instance count** as a first-class graph, with the panic threshold drawn on it.
- [ ] **Ejections per hour, by instance.** A backend ejected repeatedly is a different
      problem from many backends ejected once — the second is a health-check failure.
- [ ] Alert: healthy fraction < 80% for 60 s (before panic mode would fire, not after).
- [ ] Alert: any instance with **zero** requests for 10 minutes while marked healthy.
- [ ] Alert: panic mode **engaged** — this should be loud and rare. If it fires routinely,
      your health checking is wrong and panic mode is the only thing hiding it.

---

## Sign-off

| Item | Owner | Date | Note |
|---|---|---|---|
| Probe path p99.9 measured | | | |
| Timeout ≥ p99.9 confirmed | | | |
| Guards present (or compensated on k8s) | | | |
| All-unhealthy behaviour tested | | | |
| 92%-load healthy-count test passed | | | |
