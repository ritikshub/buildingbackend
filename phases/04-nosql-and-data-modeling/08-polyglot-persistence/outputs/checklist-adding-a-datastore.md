---
name: checklist-adding-a-datastore
description: A decision checklist for whether to add another datastore to your architecture — naming the pressure, checking whether your existing database already relieves it, and, if you do add one, keeping it in sync with the source of truth via outbox or CDC with idempotent consumers
phase: 04
lesson: 08
---

# Should You Add Another Datastore? — A Decision Checklist

The whole of Phase 4 in one gate. Run it *before* introducing any new database, cache, index, or
queue. The default answer is **no** — every store you add is a permanent operational tax and a new
way for your data to disagree with itself. Make it earn its place.

## Step 1 — Name the pressure (or don't add it)

- [ ] State the **specific pressure** (Lesson 1) pushing on this slice of data: rigid **schema**,
      expensive **joins/traversal**, **write throughput** a single primary can't take, need to
      **scale out**, or the **consistency/availability** trade.
- [ ] If you cannot name one — if the reason is "it's trendy," "we might need it," or "the other team
      uses it" — **stop.** There is no pressure. Stay on your current store.
- [ ] Rule out the cheap relational fixes first: a missing **index**, an **N+1** query, no
      **connection pool**, no **caching** (Phase 3). Most "we need a new database" is a tuning bug.

## Step 2 — Check whether your existing database already relieves it

Postgres (and modern relational databases) have absorbed most of what used to require a second store.
Using a feature you already run costs **zero** new operational burden.

- [ ] Schema flexibility → **`JSONB`** (queryable, indexable documents inside Postgres).
- [ ] Time-series firehose → **partitioning** / **TimescaleDB** (hypertables, compression, rollups).
- [ ] Full-text / semantic search → **full-text search** / **`pgvector`**.
- [ ] Bounded graph traversal → **recursive CTE** / **Apache AGE**.
- [ ] Pub/sub → **`LISTEN`/`NOTIFY`**.
- [ ] If one of these fits, **use it** — you're done. No new system.

## Step 3 — Justify the operational cost

Only if Step 2 genuinely doesn't solve it. Confirm you can pay the permanent bill:

- [ ] **Scale** truly justifies it (the volume/latency a specialized store buys is real and needed
      now, not hypothetical).
- [ ] You can **operate** it: run, back up, monitor, patch, secure, capacity-plan, and staff on-call.
- [ ] You've accounted for the **new failure mode** (it can be down/slow/stale independently) and the
      **cognitive load** (another data model and query language for the whole team).

## Step 4 — Make it a derived, rebuildable projection

- [ ] Pick the **one source of truth** for each fact (usually the relational database). The new store
      holds a **copy shaped for a read**.
- [ ] Ensure the new store is **rebuildable from the source of truth** — if it's lost or corrupted, you
      re-derive it and lose nothing permanent.
- [ ] Never let **two stores own the same fact** with no authority to break a tie.

## Step 5 — Sync it without a dual write

- [ ] Do **not** write synchronously to both the database and the new store (the **dual-write
      problem**: no transaction spans both; a failure between them diverges permanently).
- [ ] Use the **outbox pattern** (write the data + an event in one atomic DB transaction; a relay
      publishes with retries) or **CDC** (tail the WAL and stream changes — Debezium).
- [ ] Make every consumer **idempotent** (dedupe on an event id, or set-to-a-value not increment),
      because delivery is **at-least-once**.
- [ ] Accept **eventual consistency between stores**; design the UX for the lag (read exact values from
      the source of truth where they must be exact).

## Red flags

- Adding a store because it's fashionable or "might be needed," with no named pressure.
- Two systems both treated as the source of truth for the same data.
- Synchronous dual writes ("write DB, then update the index") as the sync strategy.
- A non-idempotent consumer of an at-least-once stream.
- A pile of specialized stores where a single Postgres feature would have done.

## Decision shortcut

> No named pressure → don't add it. Postgres feature relieves it → use that, zero new ops.
> Genuinely can't + scale justifies it → add it as a rebuildable projection of one source of truth,
> synced by outbox/CDC with idempotent consumers. Every store you don't add is a problem you don't have.
