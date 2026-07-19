---
name: checklist-graphql-production
description: A pre-production checklist for a GraphQL API — the operational tax REST doesn't charge you: N+1 batching, query-cost limits, persisted queries, and errors-aware monitoring
phase: 02
lesson: 08
---

# GraphQL Production Checklist

GraphQL trades a server-shaped contract for a client-shaped one. That trade comes with
a tax REST doesn't charge. Pay it before you go live.

## Performance (N+1 is the default failure)

- [ ] Every resolver that fetches children uses a **DataLoader** — batches same-tick
      loads into one query and caches per request.
- [ ] Loaders are instantiated **per request** (a shared loader leaks one user's cache
      into another's).
- [ ] The batch function returns results in the **same order and length** as its keys.
- [ ] You've load-tested a **deeply nested** query, not just a flat one.

## Security (you handed clients a query planner)

- [ ] **Depth limit** (10–15) rejects pathological recursive documents at validation.
- [ ] **Cost/complexity budget** weights fields and multiplies through list args,
      rejecting expensive queries before execution.
- [ ] **Introspection is off** in production for private APIs.
- [ ] **Alias/batch caps** guard against amplification (thousands of aliased fields in
      one request).
- [ ] **Authorization is enforced in resolvers** per object, using the principal from
      context — never by hoping a type is unreachable.

## Caching

- [ ] **Persisted queries** (hash known operations) give you an allow-list *and*
      CDN-cacheable GETs — the strongest single hardening.
- [ ] Mutations **return the mutated object with its `id`** so normalized client caches
      stay consistent.

## Correctness & monitoring

- [ ] **Nullability is deliberate**: top-level fetch-by-id fields are nullable so a
      missing row doesn't null-propagate and destroy the response.
- [ ] Monitoring watches the **`errors` array**, not just HTTP status — GraphQL returns
      `200` with partial failures.
- [ ] The schema is the contract: additive changes are safe; removing/renaming a field
      or tightening nullability is breaking.

## Should this even be GraphQL?

- [ ] Many client types render different shapes of one rich, nested domain? → good fit.
- [ ] Public, cache-heavy, or simple CRUD? → REST is probably the better tool.
