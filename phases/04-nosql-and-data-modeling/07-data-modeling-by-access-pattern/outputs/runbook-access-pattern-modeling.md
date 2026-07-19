---
name: runbook-access-pattern-modeling
description: A step-by-step runbook for modeling any NoSQL store query-first — capturing access patterns, designing partition and sort keys, building single-table item collections and secondary indexes, and validating that every read is a targeted lookup rather than a scan
phase: 04
lesson: 07
---

# Query-First Data Modeling — A Runbook

A repeatable process for designing storage in any join-free NoSQL store (DynamoDB, Cassandra,
MongoDB, and friends). The order is the whole point: **access patterns first, keys second, data
last.** Work through it top to bottom; do not design a key until the pattern that needs it exists on
the list.

## Step 1 — Capture every access pattern (before any schema)

Write a numbered list. Each row is one read your application will issue, as a sentence naming **what
you filter by** and **how you sort/limit**:

| # | Access pattern | Filter by | Sort / range | Frequency |
|---|----------------|-----------|--------------|-----------|
| 1 | Get a customer's profile | customer id | — | very high |
| 2 | List a customer's orders, newest first | customer id | date desc | high |
| 3 | Get an order with its line items | order id | item order | high |
| 4 | List orders in a given status | status | date | medium |

- [ ] Include **writes** too (what you create/update, and what must change together).
- [ ] Mark each pattern's **frequency** — the hot ones drive the key design; rare ones can tolerate a
      secondary index or a slower path.
- [ ] Stop and sanity-check: if the list is still churning weekly, the product is too young for
      query-first modeling — **stay relational** until it stabilizes (Lesson 1).

## Step 2 — Design the partition key (what groups + locates data)

For each hot access pattern, the thing you filter by is a candidate partition key.

- [ ] The partition key **contains what you filter by** (you can only look up efficiently by it).
- [ ] It is **high-cardinality and evenly distributed** — avoid a hot partition (Lesson 4).
- [ ] It keeps each partition **bounded** — add a time/bucket component if a partition would grow
      forever (Lesson 4's bucketing).
- [ ] **Encode meaning + a type prefix**: `CUSTOMER#c-1`, `ORDER#o-620` — the prefix namespaces the
      entity so one table can hold many.

## Step 3 — Design the sort key (order + range within a partition)

- [ ] It matches the **order** the pattern wants (`ORDER#<date>#<id>` gives newest-first via
      descending order).
- [ ] It enables the **range slice** you need: `begins_with` a prefix, `between` two values.
- [ ] It makes each item **unique** within the partition (append an id tie-breaker).
- [ ] Reserve prefixes so a parent's metadata sorts predictably among its children (e.g. `#PROFILE`,
      `#META` sort before `ORDER#`, `ITEM#`).

## Step 4 — Co-locate with single-table design (the joins you can't do)

- [ ] Group a **parent and its children** under one partition key so a single query returns the whole
      **item collection** (customer + orders; order + items).
- [ ] **Duplicate on write** where two patterns need the same entity keyed differently (an order under
      both the customer partition and its own). This is the intended design, not a hack — storage is
      cheap, cross-partition scans are not.
- [ ] Keep keys **generic/overloaded** (`PK`/`SK`, `gsi1pk`/`gsi1sk`) so new entity types slot into the
      same table without re-keying.

## Step 5 — Cover the rest with secondary indexes

- [ ] Any pattern whose filter is **not** the base partition/sort key → a **secondary index (GSI)**: a
      store-maintained copy keyed by that attribute.
- [ ] Control index **membership** by which items carry the index's key attributes (only the canonical
      item, so nothing is double-listed).
- [ ] Budget the cost: each index adds **write amplification** and storage (Phase 3, Lesson 9).

## Step 6 — Validate against the list

- [ ] Walk the numbered list from Step 1 and confirm **each pattern is a point lookup or a
      single-partition/index query** — no `Scan`.
- [ ] For each, state the exact key or index it uses. If any pattern has no answer but a scan, go back
      to Step 2/5 — you're missing a key or an index.
- [ ] Re-check the hot-partition and unbounded-partition traps (Lesson 4).

## Red flags

- A **`Scan` in production** — an access pattern you never modeled a key for.
- **Normalizing "cleanly" and hoping to join later** — there are no joins; you'll be stuck.
- **A new required query mid-project** with no index to serve it — this is a data migration, so it
  belongs on the roadmap, not a hotfix.
- **Access patterns still changing weekly** — you probably want a relational database's flexibility,
  not query-first rigidity (Lesson 1).

## Decision shortcut

> Access patterns first (filter + sort + frequency) → partition key = what you filter by
> (high-cardinality, bounded, type-prefixed) → sort key = how you order/range it →
> co-locate parents+children as item collections, duplicate on write → secondary index for every
> non-key filter → validate every pattern is a lookup, never a Scan.
