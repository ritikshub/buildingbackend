---
name: checklist-wide-column-modeling
description: A query-first checklist for designing a wide-column table (Cassandra, HBase, ScyllaDB) — listing access patterns, choosing partition and clustering keys that avoid hot and unbounded partitions, and tuning consistency per operation
phase: 04
lesson: 04
---

# Designing a Wide-Column Table — A Query-First Checklist

Run this before creating any table in a wide-column store (Cassandra, HBase, ScyllaDB). The
order is not negotiable: you list the **queries first**, then design tables to serve them. Get
the partition key wrong and the query you need becomes a full-cluster scan — or impossible.

## Step 0 — Confirm you actually want this model

- [ ] You need **enormous write throughput** a single primary can't absorb (feed fan-out, IoT,
      messaging, clickstream) — the LSM-tree's whole reason to exist.
- [ ] You need **horizontal scale** across many cheap nodes, not one big machine.
- [ ] Your reads are **lookups and ordered ranges by a known key**, not ad-hoc joins or
      analytics. If you need joins or arbitrary queries, this is the wrong store (stay relational,
      or see Lesson 8).
- [ ] You have *not* confused this with a **columnar analytics** store (Parquet/Redshift) — those
      are for OLAP scans, a different world entirely.

## Step 1 — List every access pattern FIRST

- [ ] Write down each read your app will issue, as a sentence: *"fetch X filtered by Y, ordered
      by Z."*
- [ ] For each one, name the **filter** (what you look up by) and the **order** (how you want it
      sorted). These become the partition key and clustering key.
- [ ] Accept up front: **one table per access pattern.** Two different filters → two tables →
      write the data into both. Duplicating on write is the intended design, not a hack.

## Step 2 — Choose the partition key (this decides the node)

The partition key is hashed onto the ring to pick which node owns the data. Choose it to spread
load evenly and keep partitions bounded.

- [ ] It **contains what you filter by** for this query (you can only look up by the partition
      key, efficiently).
- [ ] It is **high-cardinality and evenly distributed** — avoid a **hot partition** (e.g.
      partitioning by `country` when 60% of traffic is one country hammers a few nodes).
- [ ] It keeps each partition **bounded in size** — avoid an **unbounded partition** (e.g.
      `sensor_id` alone grows forever on one node). If a partition can grow without limit, add a
      **time bucket** (`sensor_id + day`) so each partition stays small — this is *bucketing*.
- [ ] For low-cardinality natural keys, form a **composite** partition key to spread the load.

## Step 3 — Choose the clustering key (this decides the sort order)

- [ ] It matches the **order** the query wants (`sent_at DESC` for newest-first).
- [ ] It makes the common read a **contiguous range** within one partition ("last 50 messages")
      — a single sequential read, no scatter-gather.
- [ ] It makes each row **unique** within the partition (append tie-breakers if needed) so writes
      don't silently overwrite.

## Step 4 — Tune consistency per operation

Each partition is replicated to **N** nodes. Pick read (**R**) and write (**W**) quorum sizes per
query, not once globally.

- [ ] For data a user must never see stale (balance, password), set **R + W > N** (e.g. N=3,
      W=QUORUM(2), R=QUORUM(2) → 2+2>3) for **strong consistency**.
- [ ] For data that tolerates lag (feeds, "seen" markers, counters), use **R + W ≤ N** (e.g.
      W=1, R=1) for **lower latency and higher availability**.
- [ ] Remember the same table can serve both — choose per query.

## Traps to avoid

- [ ] **Hot partition:** low-cardinality or skewed partition key concentrates load on a few nodes.
- [ ] **Unbounded / large partition:** a partition that grows forever; fix with time bucketing.
- [ ] **Tombstone build-up:** deletes and TTLs write tombstones removed only at compaction; a
      delete-heavy or heavy-TTL workload makes range reads scan *past* thousands of dead rows.
      Design to avoid delete-heavy patterns.
- [ ] **Modeling data instead of queries:** normalizing "cleanly" and hoping to join later. There
      are no joins — you will be stuck.

## Decision shortcut

> Access pattern first → partition key = what you filter by (high-cardinality, bounded) →
> clustering key = how you order it → one table per query, write to each →
> tune R/W per operation (R + W > N when it must be fresh).
