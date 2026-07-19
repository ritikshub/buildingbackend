---
name: checklist-gateway-bff
description: A checklist for adding an API gateway and/or BFF layer — what to centralize at the edge, what to keep out of it, and how to fan out to services without turning the front door into a monolith or a single point of failure
phase: 02
lesson: 10
---

# API Gateway & BFF Checklist

Use this when introducing (or reviewing) an edge layer in front of multiple services.

## Does the gateway do the edge concerns — once?

- [ ] **TLS termination** at the edge; plain HTTP inside the trust boundary.
- [ ] **Authentication** verified once; a trusted identity header (`X-User-Id`) injected
      inward so services don't each re-parse tokens.
- [ ] **Rate limiting / quotas** enforced at the edge (lesson 9).
- [ ] **Routing** maps public paths to internal services; clients never see topology.
- [ ] **Observability**: a request ID stamped and propagated; latency/error metrics; a
      trace spanning downstream calls.

## What must NOT be in the gateway

- [ ] **No business/domain logic** (pricing, validation rules). That belongs in
      services — a gateway full of logic is the ESB / distributed-monolith anti-pattern.
- [ ] No per-service state that couples the gateway's deploy to a service's release.

## Availability (it's on every request path)

- [ ] The gateway is **stateless** and **horizontally scaled** behind a load balancer.
- [ ] It is **health-checked**; a bad instance is removed from rotation.
- [ ] It stays **lean** — heavy synchronous work in the request path is a latency tax on
      everything.

## Defense in depth

- [ ] Services still **authorize access to their own data** — "the gateway checked auth"
      is not a reason to trust any caller (internal attacker, misrouted call, bug).

## BFF layer (if used)

- [ ] Each BFF is **owned by one frontend team** and serves **one client**.
- [ ] BFFs are **thin**: aggregation and payload shaping, never business rules.
- [ ] Fan-out is **parallel**, with a **timeout per downstream call** and a documented
      **partial-failure policy** (fail vs. degrade) per field.
- [ ] If BFFs proliferate into many near-identical copies, consider **GraphQL** (a
      generalized, declarative BFF) instead of hand-writing one per client.
