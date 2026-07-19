---
name: checklist-service-discovery-and-routing
description: Measure and bound the real window between an instance dying and its callers stopping — the six additive delays, the connection lifetime nobody sets, the ejection cap, and the shutdown ordering that drops zero requests.
phase: 10
lesson: 08
---

# Service discovery & health-aware routing — the blackhole window checklist

The gap between "an instance died" and "nothing is sending it traffic" is a **sum**, not a
setting. Almost every team quotes one term of it — usually the lease TTL — and is wrong by
1.5× to 2×. This checklist makes you enumerate the terms, bound the one nobody bounds, and
fix the ordering that drops requests on every deploy.

Run it once per service, and again whenever you change a client library, a proxy, or a
registry knob. Every item exists because skipping it caused a real outage.

## 1 · Enumerate your six delays — in writing, with numbers

Fill this in for one real service. If you cannot fill a row, that row is your largest risk,
because an unmeasured delay is not a small one.

```text
layer                          your value   where it is configured
1  heartbeat / probe interval  ______ s     the instance, or the readiness probe period
2  lease grace (TTL)           ______ s     the registry: TTL, or probe failureThreshold
3  expiry sweep granularity    ______ s     the registry's scan interval (often undocumented)
4  propagation to the caller   ______ s     control plane push, endpoint watch, config reload
5  caller list / DNS cache TTL ______ s     client library, resolver, OS, runtime — all four
6  max connection lifetime     ______ s     the HTTP/gRPC client or proxy. Usually UNSET.
                               ---------
   TOTAL blackhole window      ______ s     <- this is the number, not row 2
```

- [ ] Every row has a number from a config file or a measurement, not from memory.
- [ ] The **total** is written down where the on-call can find it in under a minute.
- [ ] Row 3 was verified, not assumed. "Expired" and "the registry noticed" are two moments.
- [ ] The total is compared against what the team *believed* it was. Note the ratio.
      (Reference measurement: assumed 30 s, actual 47.25 s representative / 48.96 s mean /
      62.24 s p95 — 1.57× to 2.07×.)

## 2 · Measure it for real, once

- [ ] In staging, with traffic on, **hard-kill one instance** (`SIGKILL`, or block its
      network — not a graceful stop, which measures a different thing) and time from kill to
      last failed request.
- [ ] Also test the **wedge**: a process that holds its socket open and answers nothing.
      This is the case a TCP-level check never catches.
- [ ] Record the measured window next to the arithmetic from section 1. If they disagree,
      you have a layer you did not know about — find it.
- [ ] Repeat after any client-library or proxy upgrade. Defaults change silently.

## 3 · Bound the connection — the layer nobody sets

Discovery updates **lists**. It does not close **sockets**. A keep-alive connection is pinned
to an IP address and never re-resolves.

- [ ] A **maximum connection lifetime** is set on every outbound client and every proxy.
      Envoy: `common_http_protocol_options.max_connection_duration`. nginx: `keepalive_time`.
      Go: no such setting exists — you must implement it or periodically close idle
      connections. Database pools: HikariCP `maxLifetime` and equivalents.
- [ ] The value is **jittered** or randomised per connection. Five hundred instances that all
      started together will all recycle together otherwise.
- [ ] Idle timeouts are set too, but are not confused with a lifetime cap: a busy connection
      is never idle and will never expire.
- [ ] Runtime DNS caches are set explicitly, not inherited:
      JVM `networkaddress.cache.ttl` (**-1 with a security manager means cache for the whole
      process lifetime**), plus whatever `nscd`/`systemd-resolved` is doing underneath.
- [ ] Written down somewhere the team reads: **a DNS change is not a completed rollout.**
      TTLs cannot be revoked, and lowering one only helps after the old one expires everywhere.

## 4 · Registered ≠ healthy ≠ ready

- [ ] Registration is gated on the **readiness signal**, not on process start or port bind.
- [ ] Deregistration happens on **drain start**, not at process exit.
- [ ] The registry is not treated as a health signal on its own. A lease says a process once
      claimed it could serve, aged by up to a full TTL.
- [ ] Someone can state, without looking, which of registered / healthy / ready each of your
      routing layers is actually keying on.
- [ ] Kubernetes: `publishNotReadyAddresses` is false (the default) for anything serving
      request traffic.

## 5 · Detection: run both mechanisms, and cap the ejector

- [ ] **Active health checks** are configured, so instances receiving *no* traffic are still
      evaluated — the freshly scaled pod, the new zone, the idle canary.
- [ ] The probe cost is calculated, not assumed: `instances × routers ÷ interval` = probes/s.
      (Reference: 7 probes/s across 6 instances was **18% of production request rate.**)
- [ ] Probe endpoints are excluded from RED metrics and access logs, or they dominate both.
- [ ] **Passive outlier detection** is configured, and the team knows its floor: it must lose
      N requests (5 by default in most proxies) before it acts, every time.
- [ ] `max_ejection_percent` is set to **50 or less**. Check it — Envoy's default is 10, but
      several proxies and cloud load balancers default to no cap at all.
- [ ] There is an alert on "ejected instance count" that fires when a *large fraction* of the
      pool is ejected — that is a shared fault, and ejection is making it worse.
- [ ] Health checks do not exercise a shared dependency, or a single slow database will eject
      the entire fleet at once.

## 6 · The shutdown ordering — deregister, wait, drain, stop

In this order. Step 2 is the one that gets skipped, and it costs 228 requests per rollout.

- [ ] **1. Deregister** (or fail readiness, which deregisters you). Keep serving.
- [ ] **2. Wait** — strictly longer than the **measured** propagation delay from row 4 above.
      Kubernetes: `preStop: sleep N`, which runs *before* `SIGTERM` is delivered.
      This is the only step that distinguishes 228 dropped requests from 0.
- [ ] **3. Drain** — stop accepting new work; finish in-flight requests with a deadline. Send
      `Connection: close` so pooled clients reconnect elsewhere.
- [ ] **4. Stop** — close pools, flush telemetry, exit 0.
- [ ] The hard kill deadline (`terminationGracePeriodSeconds` or equivalent) exceeds
      **wait + drain + longest request**, with headroom. Do the addition; do not accept 30.
- [ ] The ordering is verified by measurement — count dropped requests during a rolling
      replacement in staging. The correct ordering measures **zero**, not "a few".

## 7 · During an incident

- [ ] Ask "when did the *caller* stop sending?", never "when did the registry expire it?".
      The gap between those two questions is most of the incident.
- [ ] Check whether traffic is arriving over an **established connection**. If so, no registry
      or DNS action will stop it. You must close the connection — restart the client, or trip
      the ejector.
- [ ] If the whole pool looks unhealthy, suspect a **shared** dependency and check whether
      your ejector has already emptied the pool. Raise the ejection cap or disable ejection
      before adding capacity.
- [ ] After the incident, add the measured window to the timeline. Post-incident reviews that
      say "it took 40 seconds" are reporting one draw from a distribution — record which
      layers contributed, so the next review can compare.
