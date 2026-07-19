---
name: checklist-sql-or-nosql
description: A decision checklist for whether a workload should stay on a relational database or move to a specific NoSQL store — driven by the five pressures, not by hype
phase: 04
lesson: 01
---

# "Should I Leave SQL?" — A Decision Checklist

Use this before adding a new database to a system. The default answer is **stay on your
relational database.** This checklist exists to make you prove, out loud, that a *specific*
pressure justifies the permanent cost of operating another store.

## Step 0 — Start from the default

- [ ] Is the data transactional / does correctness matter (money, inventory, auth)? → **Stay
      relational.** Strong consistency and atomic transactions are the whole point; don't trade
      them away.
- [ ] Is this a new system with unknown access patterns? → **Start relational.** You can always
      extract a specialized store later; you can't easily add transactions to one that lacks them.

## Step 1 — Name the pressure (you need at least one to leave)

Which of these is *actually* acting? Vague "we need to scale" doesn't count — point at one.

- [ ] **Schema:** the data is heterogeneous or its fields change constantly, and `ALTER TABLE`
      migrations are a recurring tax. → points to **Document** (Lesson 3).
- [ ] **Joins / traversal:** the hot query is a deep relationship walk (friends-of-friends, N
      hops) that self-joins into a blow-up. → points to **Graph** (Lesson 6).
- [ ] **Write throughput:** a single primary can't absorb the write rate (feed fan-out, IoT,
      clickstream). → points to **Wide-Column** (Lesson 4) or **Time-Series** (Lesson 5).
- [ ] **Scale-out:** the working set won't fit the biggest affordable single machine, and you
      need to add cheap nodes. → points to a **distributed** store (wide-column / KV).
- [ ] **Consistency/availability:** you need to stay available during network partitions and can
      tolerate stale reads for this data. → points to a **BASE / eventually-consistent** store.

If you checked **zero** boxes: stop. You don't have a NoSQL problem. Re-check your indexes,
your N+1 queries, and your connection pool (Phase 3, Lessons 9 & 14).

## Step 2 — Check if your relational database already solves it

Before adding a system, confirm Postgres *can't* do it. It probably can:

- [ ] Schema flexibility → **`JSONB`** column (indexable JSON, inside your transactions).
- [ ] Time-series shape → declarative **partitioning** or the **TimescaleDB** extension.
- [ ] Full-text search → built-in **`tsvector`** / GIN indexes (before you reach for Elasticsearch).
- [ ] Vector/embedding search → **`pgvector`**.
- [ ] Geospatial → **PostGIS**.
- [ ] Pub/sub-ish notifications → **`LISTEN`/`NOTIFY`**.
- [ ] Read scaling → **read replicas** (scales reads without a new database).

If a built-in feature or extension covers the pressure: **use it.** One database you already
run beats two you have to operate.

## Step 3 — Count the true cost before committing

A second store is forever. Confirm you're willing to pay:

- [ ] Another system to deploy, back up, monitor, patch, and secure.
- [ ] **No cross-store transactions** — you now own consistency between the two stores by hand
      (CDC / outbox, Lesson 8; Phase 6).
- [ ] On-call knowledge: someone must learn its failure modes (hot partitions, tombstones,
      compaction, cardinality — depending on the store).
- [ ] Data duplication and the sync/staleness it implies.

## Step 4 — Match the tunable to the data

If you do go distributed and the store lets you tune consistency (quorums, per-op levels):

- [ ] Strong / quorum reads+writes for anything a user must never see stale (their own balance).
- [ ] Eventual consistency for what tolerates it (counters, feeds, recommendations, analytics).

## Red flags (you're about to make a mistake)

- Choosing a database by popularity or résumé appeal instead of by a named pressure.
- "We'll need to scale eventually" with no current pressure — premature, and it forecloses
  options. Add the store when the pressure is real and measured.
- Moving the *transactional core* (orders, payments) off relational to chase write scale you
  don't yet have.
- Adopting five databases on day one. Start with a relational core; add specialized stores one
  proven pressure at a time (polyglot persistence, Lesson 8).
