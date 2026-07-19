---
name: checklist-key-value-fit
description: A checklist for deciding whether a key-value store fits a workload, choosing between an in-memory and a distributed one, and operating it without the classic footguns
phase: 04
lesson: 02
---

# Key-Value Store Fit & Operations Checklist

Use this when you're tempted to put data in Redis, Memcached, DynamoDB, or any KV store —
before you commit, and before you go to production.

## Is this actually a key-value workload?

- [ ] Every access is **by a single known key** (id, session token, user id, cache key).
- [ ] You **never** need to query, filter, or sort by anything *inside* the value.
- [ ] You don't need joins across records.
- [ ] Values are **small** (bytes to low kilobytes), not multi-megabyte blobs.

If any of these fails, reconsider: query-inside-value → **document store** (Lesson 3);
big blobs → **object storage** (S3) with the pointer in KV; need relationships → relational
or **graph** (Lesson 6).

## Pick the right kind of KV store

- [ ] Need microsecond reads, atomic counters, TTLs, typed values, one node is enough? →
      **in-memory** (Redis / Memcached).
- [ ] Need to scale writes/storage across many machines and stay available under partition? →
      **distributed** (DynamoDB / Cassandra / Riak) — routed by a **partition key** you must
      supply on every access.
- [ ] Need ordered iteration / range scans over keys? → an **ordered KV** built on a B-tree or
      LSM-tree (FoundationDB, RocksDB, etcd), not a pure hash store.

## Design the keys deliberately

- [ ] Use a **consistent, prefixed key scheme**: `user:1042`, `session:9f3a`, `cart:1042`.
      The prefix is your only namespace.
- [ ] For any "find all X" you'll need, **design a second key up front** that serves it
      (e.g. a set `tier:gold` → member ids). The store won't build indexes for you.
- [ ] Avoid unbounded growth under a single key (one key holding a million-item list becomes a
      hot, expensive object). Split it.

## Durability & consistency (choose consciously)

- [ ] Decide whether this data is a **cache** (loss is fine; rebuild from source) or a **source
      of truth** (loss is not fine). Configure persistence accordingly.
- [ ] In-memory stores can lose the last fraction of a second of writes depending on their
      fsync/AOF settings — know your setting, don't assume.
- [ ] In a distributed store, pick the **consistency level** per operation (strong/quorum for
      data a user must see fresh; eventual for counters and caches).

## Operational footguns

- [ ] **Hot keys:** one key hit far more than the rest concentrates load on one node/shard.
      Spread it (sharded counters) or cache it upstream.
- [ ] **Big values:** cap value size; large values wreck cache locality and cross-node moves.
- [ ] **TTL stampede / expiry:** many keys expiring at once can hammer the backing source
      (Phase 5, cache stampede). Jitter TTLs.
- [ ] **Unbounded memory (in-memory stores):** set a `maxmemory` and an eviction policy, or the
      store OOMs. An unbounded cache is a memory leak (Phase 5, Lesson 2).
- [ ] **Compaction / space (on-disk stores):** append-only engines accumulate dead records;
      ensure compaction is running and keeping up with write volume.

## Red flags

- Reaching for `KEYS *` / a full scan in production — it's O(n) and blocks; you're using the
  wrong model or missing an index key.
- Storing the transactional source of truth (orders, balances) in an eventually-consistent KV
  store to chase speed.
- One giant value per user that you rewrite on every small change (write amplification).
- No `maxmemory`/eviction policy on an in-memory store used as a cache.
