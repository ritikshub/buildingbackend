---
name: checklist-zero-downtime-schema-changes
description: Ship a schema or contract change against a live fleet without an outage — the compatibility rule, the per-operation recipes, lock and backfill settings with real numbers, deploy ordering, and the review questions that catch the changes that require downtime.
phase: 10
lesson: 13
---

# Zero-downtime schema & contract changes — review and ship checklist

Run this on every migration before it merges, and again before it is applied to production.
Every item exists because skipping it caused a real outage — or worse, silent corruption that
nobody found until the next morning's reconciliation.

The one rule everything below derives from:

> **During a rolling deploy, two versions of your code run at the same time against one
> database. Every schema state must be compatible with the version before it and the version
> after it, for as long as both can exist — which is unbounded.**

## 1 · Before you write the migration

- [ ] Name the **overlap window** for this change. Who else talks to this table or this
      contract? Include the ones not in the rollout: cron boxes, batch workers, the analytics
      reader, mobile clients, partner integrations, a replica someone reports off.
- [ ] Confirm the window is unbounded, not "90 seconds". A canary, a stuck node, a paused
      sync or a rollback all extend it indefinitely, and nothing alerts on it.
- [ ] Decide whether this change is **additive** (safe alone) or a **rename/retype/removal**
      (needs expand → backfill → migrate → soak → contract, as separate deploys).
- [ ] If it cannot be staged compatibly, **say so in the PR**: this is a change that requires
      downtime. Schedule an announced window rather than discovering it at peak.
- [ ] Check the engine version. `ADD COLUMN ... DEFAULT` is metadata-only on PostgreSQL ≥ 11
      and a full rewrite before it. Folklore in this area is a decade out of date.

## 2 · Pick the recipe

| Change | Cost | Safe staging |
|---|---|---|
| Add nullable column | metadata-only | ship it (still set `lock_timeout`) |
| Add `NOT NULL` column | metadata-only with a **non-volatile** default; rewrite with a volatile one | nullable → backfill → `CHECK ... NOT VALID` → `VALIDATE CONSTRAINT` |
| Rename column | free — and an atomic break for every deployed version | never rename; five steps |
| Change type | usually a full rewrite + index rebuilds | new column, dual-write, backfill, switch, drop |
| Drop column | metadata-only, fast, **irreversible** | stop referencing → soak → drop |
| Add index | `CREATE INDEX` blocks all writes | `CREATE INDEX CONCURRENTLY`, then check for `INVALID` |
| Add foreign key | locks both tables, scans the child | `ADD CONSTRAINT ... NOT VALID` then `VALIDATE` |
| Split a table | the multi-step change in disguise | same five steps at table granularity |

- [ ] `varchar` length **increases** and `varchar` → `text` are metadata-only. Decreases are not.
- [ ] A volatile default (`gen_random_uuid()`, `clock_timestamp()`) always rewrites. Add the
      column nullable and backfill instead.

## 3 · Locks — never send a bare DDL

- [ ] Every DDL statement sets **`lock_timeout`** (50 ms – 2 s) and is wrapped in a retry loop
      with **jittered** exponential backoff. Measured: without it, a 1 ms `ALTER` queued behind
      a 3 s analytics query stalled **42 innocent SELECTs for 51.7 query-seconds**; with it,
      **4 queries and 0.08 query-seconds**, at a cost of 1.27 s of migration latency.
- [ ] You know why: **a lock is granted only if it conflicts with nothing HELD and nothing
      already WAITING ahead of it.** A DDL that holds no lock at all still blocks the table
      while it waits.
- [ ] `statement_timeout` is set too — it bounds the run, `lock_timeout` bounds the wait.
      They are different settings for different failures.
- [ ] The migration does **not** run at peak, and does not run while a known long report runs.
- [ ] `CREATE INDEX CONCURRENTLY` is in its own migration with the framework's automatic
      transaction wrapper disabled (Alembic: no transaction; Django: `atomic = False`).
- [ ] After any concurrent index build, check for invalid indexes and drop them before retrying:
      `SELECT c.relname FROM pg_class c JOIN pg_index i ON i.indexrelid=c.oid WHERE NOT i.indisvalid;`
- [ ] The incident query is in the runbook, not invented at 03:00:
      `SELECT pid, pg_blocking_pids(pid), left(query,60) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid)) > 0;`
      Cancel the **blocker** if it is a re-runnable report; cancel your migration if it is user work.

## 4 · Backfills

- [ ] **Never one transaction.** Bounded batches with a commit and a short pause each.
      Measured on 1,000,000 rows: one transaction 2.43 s, 50 batches 4.28 s (+76% wall time),
      but the longest lock hold fell **2,427 ms → 114 ms (21×)** and a concurrent reader
      completed **1 query vs 165** on identical traffic.
- [ ] **Keyset pagination, not `OFFSET`.** `OFFSET n` re-scans the rows it skips and turns a
      linear backfill into a quadratic one.
- [ ] The backfill is a **separate migration** from the DDL, and separately re-runnable —
      idempotent, resumable, and safe to kill at 90%.
- [ ] Batch size is tuned against replication lag, not just wall time. Watch replica lag while
      it runs; a backfill that outruns your replicas is an availability problem elsewhere.
- [ ] You know a single long `UPDATE` pins an MVCC snapshot, so **vacuum stops reclaiming dead
      rows database-wide** for its duration, and the bloat outlives the migration.

## 5 · The dual-write window

- [ ] Code writes **both** shapes for the entire window, and still reads the old one.
- [ ] The reader switch is a **separate deploy**, gated on a verification query — not on
      "the backfill script exited 0".
- [ ] The verification counts **rows where the two shapes disagree**, and requires zero.
      If you cannot write that query, you do not know the backfill finished. Reading the new
      shape before the backfill completes returns `NULL` with no exception: silent corruption
      on a schedule you chose.
- [ ] Rows created *during* the backfill are covered by the dual write, not by the backfill.
      Confirm both paths, not one.

## 6 · Deploy ordering

| Step | Migration | Code | Gap |
|---|---|---|---|
| Add column / index | **before** the deploy | uses it after | minutes |
| Backfill | between deploys, after dual-write ships | — | as long as it takes |
| Switch readers | — | after backfill **verified** | verify, don't assume |
| Stop writing old shape | — | its own deploy | soak ≥ one deploy cycle |
| Drop column / table / constraint | **after** the code soaked | already shipped | days, not minutes |

- [ ] Expand and contract are in **different releases**. Not the same PR "for tidiness".
- [ ] Your process can actually express "these two migrations ship a week apart". If it cannot,
      fix that before the next rename.
- [ ] The rollout is verified **complete**, not started — including the instances not in the
      rollout. A stuck node means you are still in the window.

## 7 · Before the DROP

The only irreversible step. Measured: **4 of 4 code versions work after the backfill; 1 of 4
after the contract**, and the other three raise on every request rather than degrading.

- [ ] Nothing reads the old shape. Verified by grep **and** by evidence — a counter on the
      old-shape read path that has been at zero for the whole soak.
- [ ] Nothing writes it. Same standard of proof.
- [ ] The soak covered at least one full deploy cycle, one nightly batch run, and one weekly
      job if you have one.
- [ ] A backup exists and has been **restore-tested**, not merely taken. Re-adding a column
      does not bring the data back.
- [ ] You have accepted that from this moment you cannot roll back the application either.

## 8 · Contracts that are not databases

- [ ] **API responses:** adding a field is safe if consumers ignore unknowns; removing or
      renaming one is a rename. Making an optional request field required is breaking.
- [ ] **Events and messages:** durable, so a replay feeds consumers every version you ever
      emitted. Enforce compatibility in a registry, not in review comments.
- [ ] **Cached blobs and serialized columns:** a pickle, a protobuf in Redis, a JSON column —
      each is a schema with two versions of your code reading it.
- [ ] For every contract change, answer one question in review: **which consumer do I deploy
      atomically with this producer?** The answer is always "none".

## 9 · The three review questions

Ask these on every migration PR. They catch nearly everything above.

1. **What happens if this runs and the deploy never completes?** If the answer is anything
   other than "nothing", it is not a compatible step.
2. **What happens if we roll the code back one version, right now, after this has applied?**
   If any version raises or silently returns the wrong value, the step is not reversible.
3. **What is the longest-running query on this table today?** That is how long your DDL will
   wait — and how long everything behind it will be blocked, unless `lock_timeout` is set.
