---
name: checklist-index-review
description: A review checklist for deciding which indexes a table needs — and which existing ones to drop — based on real query patterns rather than guesswork
phase: 03
lesson: 09
---

# Index Review Checklist

Use this when a query is slow, before a schema review, or when a table has grown a
suspicious pile of indexes. The goal: index what you actually query, and nothing else.

## Which columns deserve an index?

Index a column (or column group) when it appears in:

- [ ] A `WHERE` filter that runs often on this table.
- [ ] A `JOIN` condition (foreign-key columns are prime candidates — they're joined
      constantly and often un-indexed by default).
- [ ] An `ORDER BY` / `GROUP BY` that would otherwise sort a large result.
- [ ] A `UNIQUE` business rule (the unique constraint creates the index for you).

## Is the column worth it? (selectivity)

- [ ] Does the column have **many distinct values** (email, user_id) → good index.
- [ ] Is it **low-selectivity** (a boolean, a status with 3 values, mostly-NULL) → an index
      probably won't be used; a scan is cheaper. Skip it, or consider a partial index.
- [ ] Rule of thumb: if a filter returns more than ~5-10% of the table, the planner will
      likely scan anyway.

## Composite (multi-column) indexes

- [ ] Order columns by the **leftmost-prefix** rule: an index on `(a, b, c)` serves queries
      on `a`, `a+b`, and `a+b+c` — but not `b` or `c` alone.
- [ ] Put the column used for **equality** first, the one used for **range/sort** later.
- [ ] Don't create `(a)` if you already have `(a, b)` — the composite already covers `a`.

## Confirm it's actually used

- [ ] Run `EXPLAIN` (Lesson 10) on the target query — did it switch to an Index Scan?
- [ ] Check index usage stats (`pg_stat_user_indexes` in Postgres): an index with ~zero
      scans after real traffic is dead weight — drop it.

## Count the cost before adding

- [ ] Every new index slows every `INSERT`/`UPDATE`/`DELETE` on the table. Is this table
      write-heavy? Weigh accordingly.
- [ ] Each index consumes disk and buffer-pool space. More indexes = less room for data.
- [ ] Redundant/overlapping indexes are pure cost. Audit and consolidate.

## Red flags

- A foreign-key column with no index → joins and cascade deletes scan the child table.
- Ten+ indexes on a write-heavy table → writes are paying a heavy tax; prune to what's used.
- An index on a low-selectivity boolean → almost certainly unused; drop it.
- Adding an index without running `EXPLAIN` before and after → you're guessing, not measuring.
