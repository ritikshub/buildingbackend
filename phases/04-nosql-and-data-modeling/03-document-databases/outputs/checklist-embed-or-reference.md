---
name: checklist-embed-or-reference
description: A data-modeling checklist for document databases — deciding per relationship whether to embed or reference, drawing aggregate boundaries, and avoiding the classic document-model traps
phase: 04
lesson: 03
---

# Embed or Reference? — A Document Modeling Checklist

Run this per relationship when modeling for a document database (MongoDB, DynamoDB documents,
Postgres `JSONB`). The decision is not global — you make it once per relationship, and getting
it right is the whole craft.

## Draw the document (aggregate) boundary first

- [ ] Group data that is **read together** in the same request.
- [ ] Group data that must **change together atomically** — the single-document write is your
      atomicity boundary; anything that must stay consistent belongs in one document.
- [ ] The result is your **aggregate**: the unit you load and save as a whole (an order + its
      items; a user + their profile).

## Embed when ALL of these hold

- [ ] The child is **read together** with the parent (you'd otherwise always join them).
- [ ] The child is **owned by** the parent (it has no independent life).
- [ ] The child collection is **bounded** — it won't grow without limit.
- [ ] You want the parent+child write to be **atomic**.

Examples: line items in an order, an address on a user, a few pinned comments on a post.

## Reference when ANY of these hold

- [ ] The child is **shared** across many parents (a product used by thousands of orders) —
      embedding would duplicate it everywhere.
- [ ] The child is **unbounded** (a user's followers, an activity log) — it can't fit in one
      document.
- [ ] The child is **queried independently** of the parent.
- [ ] The child **changes often** and you can't tolerate stale copies.

## Handling denormalization honestly

- [ ] If you embed mutable data, decide who owns keeping copies in sync (app logic, background
      job, or accept eventual consistency).
- [ ] Prefer embedding **immutable** data or an intentional **point-in-time snapshot** (e.g. the
      product name and price *at order time* — often exactly what you want to preserve anyway).
- [ ] For mutable shared data, **reference** and fetch on read, or maintain a derived copy
      deliberately.

## Indexing & querying

- [ ] Create a **secondary index** on every field you filter/sort by often (including nested
      paths) — same rules and write-cost as relational indexes (Phase 3, Lesson 9).
- [ ] Index the fields inside embedded arrays you query on.
- [ ] Don't over-index a write-heavy collection; each index taxes every write.

## Traps to avoid

- [ ] **Unbounded array growth:** an embedded array that grows forever makes one document slow
      and ever-larger. If it can grow without limit, reference it out.
- [ ] **Treating it like a relational DB:** deeply referencing everything and doing app-side
      joins everywhere means you get the costs of both models and the benefits of neither.
- [ ] **No validation:** schema-on-read will store typos and missing required fields silently.
      Turn on schema validation for anything important.
- [ ] **Reaching for a new database unnecessarily:** check whether **Postgres `JSONB`** solves it
      inside the database you already run, keeping ACID and avoiding a second system.

## Decision shortcut

> One-to-few, read-together, bounded → **embed.**
> One-to-many-shared, unbounded, or independently-queried → **reference.**
> Mutable-and-embedded → **snapshot immutable fields** or reference.
