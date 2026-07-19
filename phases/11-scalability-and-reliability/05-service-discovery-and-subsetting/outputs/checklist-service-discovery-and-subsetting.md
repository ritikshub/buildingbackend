---
name: checklist-service-discovery-and-subsetting
description: Paste into the service's runbook.
phase: 11
lesson: 05
---

# Checklist — Service Discovery, Client-Side Balancing & Subsetting

Paste into the service's runbook. Every threshold below is a starting value with the
reasoning attached, not a law. Numbers marked *(measured)* come from the lesson's
simulation at N=1,000 clients × M=800 backends.

---

## 1 · Do you even need client-side balancing?

Answer these before adopting it. A proxy hop is ~1 ms and is somebody else's on-call.

- [ ] Is an L4 proxy pinning long-lived HTTP/2 or gRPC connections to one backend?
      (Single connection = balanced once. This is the #1 legitimate reason.)
- [ ] Is the hop a real percentage of the latency budget? (1 ms against a 2 ms backend = yes.
      1 ms against a 200 ms backend = no.)
- [ ] Is the balancer's own availability the limiting factor on this path?
- [ ] Can you afford one balancing implementation **per language** you ship, forever?

**If fewer than two are checked, use the proxy and stop here.**
If you proceed, prefer a **sidecar** over a library: it upgrades like infrastructure and
costs nothing per language.

| | Proxy | Client library | Sidecar |
|---|---|---|---|
| Extra hop | one | none | one, loopback |
| Balancer is a SPOF | yes | no | no |
| Upgrade path | deploy proxy fleet | rebuild every client, every language | deploy sidecar |
| Connections | pooled proxy↔backend | N × M | N × M |
| Language cost | zero | one impl per language | zero |

---

## 2 · Lease / heartbeat tuning

**Rule: `heartbeat ≤ ttl / 3`.** Tolerates two consecutive lost renewals.

```text
misses tolerated            = floor(ttl / hb) - 1
bad evictions/hour  ≈ (3600 / hb) × loss^(misses_tolerated + 1)
mean stale window           = ttl - hb/2 + poll/2
max  stale window           = ttl + poll
```

| Config | ttl | hb | poll | misses tol. | mean stale | bad evictions/inst/hr |
|---|---|---|---|---|---|---|
| aggressive | 6 s | 2 s | 1 s | 2 | 5.5 s | 0.013 |
| Consul-style TTL check | 15 s | 5 s | 2 s | 2 | 13.5 s | 0.005 |
| k8s node lease default | 40 s | 10 s | 1 s | 3 | 35.5 s | 0.000 |
| Eureka default | 90 s | 30 s | 30 s | 2 | 89.9 s | 0.000 |
| **hb too close to ttl** | 30 s | 25 s | 2 s | **0** | 18.5 s | **2.857** |
| **hb above ttl (broken)** | 30 s | 35 s | 2 s | **none** | 13.5 s | **99.955** |

*(measured, 2% renewal loss)*

- [ ] `ttl / hb >= 3` for every service in the registry.
- [ ] Assumed renewal-loss rate written down. If unknown, use 2%.
- [ ] Alert on **eviction rate for instances that never failed a health check** — a nonzero
      value here is always a config bug, never a real death.
- [ ] Do **not** shorten the TTL to speed up death detection. Use client-side outlier
      ejection instead (2–3 failed requests beats any lease expiry).

---

## 3 · Do not use DNS as the registry

If you must, know exactly what you are accepting.

| Failure | Detail |
|---|---|
| TTL ignored | JVM `networkaddress.cache.ttl` historically `-1` (cache forever) under a SecurityManager |
| Pools never re-resolve | A keep-alive socket is pinned to the address it was opened against |
| 512-byte UDP cap (RFC 1035 §2.3.4) | Only **29 A records** fit for `backend.svc.cluster.local` |
| EDNS(0) 1232 B (RFC 6891) | **74 A records** — still less than most fleets |
| No health field | An A record cannot say "failing 40% of requests" |
| No weight / drain state | SRV has them; almost nothing client-side reads them |

**Decay after removing an address** *(measured; 60% honour TTL / 30% pool-pinned / 10% cache forever)*:
at 30 s, 39.1% of clients still resolve it (4.88% of all fleet requests); at 300 s, 25.8%
(3.23%); at 3600 s, **10.4% — 1.30% of every request the fleet makes**, and it stays there.

- [ ] Removal procedure does **not** rely on "take it out of DNS and wait" — the curve has
      an asymptote above zero until those processes restart.

---

## 4 · Subsetting

**Trigger — turn it on when any one of these is true:**

- [ ] Inbound connections per backend > **50% of `RLIMIT_NOFILE`** (common soft default: **1024**)
- [ ] More than ~**100 backends**, or ~**10,000 total connections**
- [ ] Health-probe traffic > **10 probes/s per backend**
- [ ] Deploy produces a visible TLS handshake spike

**The algorithm** (Beyer et al., *Site Reliability Engineering*, O'Reilly 2016, ch. 20):

```python
def subset(backends, client_id, k):
    subset_count = len(backends) // k       # clients per round
    round_id     = client_id // subset_count
    shuffled     = list(backends)
    random.Random(round_id).shuffle(shuffled)   # SEEDED BY THE ROUND
    subset_id    = client_id % subset_count
    return shuffled[subset_id * k : subset_id * k + k]
```

Seed by **round_id**, never client_id. One round covers the backend list exactly once, so
after R rounds every backend holds exactly R clients.

**Choosing k** — `P(a client loses its whole subset) = f^k` for dead fraction `f`:

| k | conns @ N=1000 | vs full mesh | f=0.2 → whole subset dead | stranded client-draws (40 draws) *(measured)* |
|---|---|---|---|---|
| 3 | 3,000 | 0.4% | 0.8% | **338** |
| 5 | 5,000 | 0.6% | 0.032% | 14 |
| 10 | 10,000 | 1.2% | 1.02e-5% | 0 |
| 20 | 20,000 | **2.5%** | 1.05e-12% | 0 |
| 40 | 40,000 | 5.0% | ~0 | 0 |
| 800 (full mesh) | 800,000 | 100% | 0 | 0 |

- [ ] **k = 20–40.** Start at 20.
- [ ] `k >= number of failure domains you must survive` (3 AZs → k ≥ 3, realistically ≥ 20).
- [ ] `N × k / M >= 2`, or you have no smoothing left even with a perfect partition.
- [ ] Before lowering k, compute `f^k` for your worst realistic simultaneous-failure fraction.
- [ ] `client_id` comes from a **stable dense ordinal** (StatefulSet ordinal, registry slot),
      not a per-restart random value — otherwise every restart reshuffles the topology.

Both algorithms cost exactly `N × k` connections. At N=1000/M=800/k=20 random subsetting
measured min 13 / max 44 / stddev 4.94; deterministic measured min 25 / max 25 / stddev 0.00.
Deterministic is strictly better at identical cost — do not "simplify" it back to random.

---

## 5 · Control plane / data plane

> **RULE: the data plane must keep routing when the control plane is down.**

Measured over an identical 120 s registry outage with 5% real backend churn:

| Policy | Success during outage | Failed requests |
|---|---|---|
| No cache (fail closed) | **0.00%** | 144,000 of 144,000 |
| Serve stale (last-known-good) | **97.81%** | 3,153 |
| Serve stale + outlier ejection | **99.48%** | 755 |

- [ ] Endpoint cache persisted to disk, so a pod restart during a registry outage still routes.
- [ ] Cache expiry, if any, measured in **hours** — never seconds.
- [ ] Outlier ejection enabled (3 consecutive failures), with `max_ejection_percent ≤ 10%`
      so ejection can never empty a subset.
- [ ] **Game day:** kill the registry and watch request success. If it drops, you have built a
      global SPOF worse than the load balancer you removed.

---

## 6 · Drain sequence (ordering is the whole content)

1. **Mark draining** — fail readiness / tell the registry. Keep serving in-flight work.
2. **Wait for propagation.** ← the step people skip
3. **Finish in-flight requests**, bounded by a timeout.
4. **Close cleanly** — send `GOAWAY` for HTTP/2 and gRPC.
5. **Deregister, then exit.**

- [ ] `terminationGracePeriodSeconds` > **client refresh interval + longest in-flight request**.
      With client-side balancing there is no single proxy to update; the drain is not complete
      until the slowest of N cached views has noticed.
- [ ] `preStop` sleep covers step 2.
- [ ] Verify: deploy, then grep the **caller** for `ECONNREFUSED`. Any hits mean propagation
      is losing the race with shutdown.
- [ ] AWS target groups: set `deregistration_delay.timeout_seconds` deliberately
      (**default 300 s**, usually far longer than needed).

---

## 7 · Production knobs, by tool

| Tool | Knob | Default | Watch for |
|---|---|---|---|
| Kubernetes | `--max-endpoints-per-slice` | 100 (max 1000) | EndpointSlice is subsetting for the control plane's own data |
| Kubernetes | `publishNotReadyAddresses` | false | true publishes pods that are not ready |
| kube-proxy | mode `iptables` vs `ipvs` | iptables | iptables sync is O(n); use IPVS above a few thousand Services |
| gRPC | LB policy | `pick_first` | opens **one** connection — catastrophic for a fleet; `round_robin` = full mesh |
| gRPC | `LEAST_REQUEST` `choice_count` | 2 | this is P2C |
| Envoy | `lb_subset_config.fallback_policy` | — | `NO_ENDPOINT` = total outage on metadata mismatch; use `ANY_ENDPOINT` |
| Envoy | `deterministic_aperture` | off | this (not `lb_subset_config`) is the N×M fix |
| Envoy | `outlier_detection.max_ejection_percent` | 10% | never let ejection empty a subset |
| Eureka | lease 90 s / renew 30 s | — | ~90 s mean stale window is the advertised behaviour |
| Consul | DNS interface | — | returns only *passing* instances |

---

## 8 · Dashboard / alert set

- [ ] `inbound_connections_per_backend` — alert at 50% of `RLIMIT_NOFILE`
- [ ] `health_probes_per_second_per_backend` — investigate above 10
- [ ] `tls_handshakes_per_second` — alert on deploy-time spikes
- [ ] `clients_per_backend` min / max / stddev — max/ideal > 1.3 means subsetting is uneven
- [ ] `backends_with_zero_clients` — must be **0**; nonzero is paid-for, unreachable capacity
- [ ] `endpoint_cache_age_seconds` — rising means the control plane is not reaching you
- [ ] `evictions_of_instances_that_never_failed_health` — must be 0
