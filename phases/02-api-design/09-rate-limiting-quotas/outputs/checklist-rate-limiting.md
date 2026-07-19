---
name: checklist-rate-limiting
description: A checklist for adding rate limits and quotas to an API — picking the algorithm, scoping the key, surviving replicas, and communicating limits so clients back off instead of hammering
phase: 02
lesson: 09
---

# Rate-Limiting Checklist

Every API that survives production needs a way to say "no" politely. Work this before
you expose an endpoint to traffic you don't control.

## Why are you limiting? (each shapes the design)

- [ ] **Capacity** — stop one client from consuming the whole budget.
- [ ] **Fairness** — one tenant's bulk job must not starve another's checkout.
- [ ] **Abuse** — e.g. 5 login attempts/min/account to defeat brute force.
- [ ] **Cost** — cap fan-out to metered downstreams (SMS, payments).

## Algorithm

- [ ] **Sliding-window counter** as the general-purpose default (two counters, no
      boundary burst).
- [ ] **Token bucket** when you want to forgive bursts (`capacity`) but cap sustained
      rate (`rate`), or weight expensive ops with a per-request cost.
- [ ] **Sliding-window log** only for low-limit, high-stakes cases (login).
- [ ] **Fixed window** only where a ~2x boundary burst is acceptable (coarse quotas).

## Scope (what's the key?)

- [ ] Authenticated traffic → per **API key / tenant**.
- [ ] Anonymous traffic → per **IP**, aware that NAT means many users share one IP.
- [ ] Trust only the `X-Forwarded-For` entry **your own edge** appends (it's forgeable).
- [ ] Layer scopes: tight abuse limit on `/login`, per-tenant fairness everywhere, a
      global capacity limit at the edge.

## Distributed correctness

- [ ] **Shared state** (Redis), not in-process counters — in-process silently multiplies
      the limit by the replica count.
- [ ] The counter update is **atomic** (`INCR`+`EXPIRE` in one Lua script) so a crash
      can't leak a never-expiring key.
- [ ] The **fail-open vs fail-closed** behavior on a Redis outage is decided explicitly
      (fail-open for fairness, fail-closed for abuse limits).

## Communicate (so clients cooperate)

- [ ] Reject with **`429`** + **`Retry-After`**, plus `X-RateLimit-Limit/-Remaining/-Reset`.
- [ ] Duplicate the retry hint into the body (headers are awkward on some clients).
- [ ] Document the limits and quotas per plan tier.
- [ ] Clients retry with **exponential backoff + full jitter** and honor `Retry-After`;
      they never retry a `400`/`422`.
