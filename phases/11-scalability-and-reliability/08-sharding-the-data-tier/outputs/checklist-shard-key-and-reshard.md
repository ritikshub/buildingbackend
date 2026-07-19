---
name: checklist-shard-key-and-reshard
description: Two gates and one runbook.
phase: 11
lesson: 08
---

# Checklist: Choosing a Shard Key & Resharding Live

Two gates and one runbook. **Gate A** decides whether to shard at all. **Gate B** picks the
key and the mapping — the two things you cannot change later. **The runbook** moves data
while the system serves traffic. Numbers below are measured in this lesson's `code/sharding.py`.

---

## Gate A — do not shard yet

Sharding costs a quarter and is permanent. Every box must be ticked or explicitly waived
with a name and a date.

- [ ] **The bottleneck is writes, and I have the number.** `pg_stat_statements` write share,
      WAL bytes/s, primary CPU. If reads dominate → read replicas (Lesson 7), stop here.
- [ ] **Query/index tuning is exhausted.** No seq scans in the top 20 by total time.
      ```sql
      SELECT calls, mean_exec_time, rows, query FROM pg_stat_statements
      ORDER BY total_exec_time DESC LIMIT 20;
      ```
- [ ] **Vertical scaling is exhausted.** On the largest instance that is economically sane,
      and the ceiling was measured, not assumed.
- [ ] **Caching is deployed** and the hit rate is where it should be (Phase 5).
- [ ] **Cold data is archived.** Most tables are ~5% hot. Move >90-day rows out.
- [ ] **Declarative partitioning is in place and did not solve it.** One machine, one
      transaction manager, one UNIQUE constraint — you keep every guarantee.
      ```sql
      CREATE TABLE events (...) PARTITION BY RANGE (created_at);
      ```
- [ ] **Functional partitioning is done.** `events`, `audit_log`, `sessions` already moved
      to their own databases. Split by TABLE before splitting by ROW.

**Waiver log:** _____________________ (who / date / why)

---

## Gate B — the key and the mapping

### B1. Score the candidates (one afternoon)

1. Pull the **top 20 queries by call volume** (not by count of distinct queries).
2. For each candidate key, mark every query **routed** (key is in `WHERE`) or **scatter**.
3. Weight by call volume. One query at 40k QPS outranks fifteen at 3 QPS.
4. Score writes separately — writes are what you are sharding for.

| Candidate | % of read volume routed | % of write volume routed | Can value change? | Verdict |
|---|---|---|---|---|
| `tenant_id`  |   |   |   |   |
| `user_id`    |   |   |   |   |
| `(tenant_id, bucket)` |   |   |   |   |

### B2. Hard disqualifiers — any one of these fails the candidate

- [ ] **The value can change.** Email, username, team, region, plan. A changed shard key
      means the row physically moves machines with no transaction covering both.
- [ ] **Cardinality ≤ 10× your target shard count.** `country` (~200), `plan_tier` (4).
- [ ] **It is monotonic AND you plan to range-shard it.** Measured: sequential `order_id`
      range-sharded put **100.0% of writes on the last shard**, seven idle. Splitting the
      hot range does not help — the new top range inherits 100%.

### B3. Balance expectations against measured reality

| Strategy | Measured max/min | Good at | Fails at |
|---|---|---|---|
| `range(tenant_id)` | **97.4x** | range scans, one-shard reads | ids assigned at signup ⇒ old = big ⇒ 85.5% on s0 |
| `hash(tenant_id)` | **18.1x** | write spread, tenant locality | 40% tenant ⇒ **47.7% on one shard** |
| `hash(order_id)` | **1.02x** | perfect balance | every tenant query is an 8-way scatter |
| `directory(tenant_id)` | **5.0x** (others 1.42x) | isolating the whale | lookup service on every query = new SPOF |
| `geographic(region)` | **8.2x** | latency, data residency | inherits population skew |

> **Hashing randomises placement, not volume.** No hash function fixes a skewed workload.

### B4. The mapping — non-negotiable

- [ ] **Virtual buckets, not `hash % N`.** Hash once into a fixed bucket count; keep an
      editable `bucket → shard` table.
- [ ] **Bucket count = 4096 or 8192.** Fixed forever. Measured imbalance from bucket count:

  | buckets | at 9 shards | at 17 shards | at 40 shards |
  |---|---|---|---|
  | 16   | 2.000x | idle | idle |
  | 256  | 1.036x | 1.067x | 1.167x |
  | 4096 | 1.002x | 1.004x | 1.010x |

- [ ] **Routing lives in ONE library** used by every service, so the map changes in one place.
- [ ] Cost of getting this wrong, measured — rows that must move to go **8 → 9 shards**:
      `hash % N` **88.9%** · consistent ring **9.5%** · 4096 buckets **11.3%** (456 buckets).
      (8 → 16 costs ~50% under *every* scheme; the difference is adding *one* machine.)

### B5. Decide these before the first row is written

- [ ] **Global ids:** UUIDv7 / Snowflake / per-shard ranges. `SERIAL` restarts at 1 per shard.
- [ ] **Global uniqueness:** `UNIQUE(email)` is per-shard. Name the lookup table that enforces it.
- [ ] **Cross-shard transactions that exist today** — list each, and for each write down
      "redesigned into one shard" or "becomes a saga". 2PC blocks on coordinator failure;
      do not plan around it.
- [ ] **Reference tables:** small lookups (`countries`, `currencies`) replicated to every shard.
- [ ] **Colocation:** tables joined together share a distribution column.
      ```sql
      SELECT create_distributed_table('order_items','tenant_id', colocate_with=>'orders');
      ```

---

## Runbook — resharding with traffic on

**Have before you start:** per-shard QPS/CPU/lag dashboards, a bucket-level row-count job,
a feature flag system, and a rate limiter on the copier.

### 1 · Double-write  ·  REVERSIBLE (turn the flag off)
- [ ] Every write goes to old **and** new. Old remains the source of truth.
- [ ] Deploy to 100% of writers and **confirm** before step 2 — this is the ordering that matters.
- [ ] Alert on double-write error rate. Measured: a path silently dropping 1 write in 400
      produced **no** change in error rate, latency or replication lag.

> Skipping this step and backfilling first corrupted **2,286 of 20,000 rows (11.43%)**.

### 2 · Backfill  ·  REVERSIBLE (truncate the new tables)
- [ ] Copy in batches, **rate-limited**, ordered by bucket so progress is resumable.
- [ ] The copy MUST be conditional:
      ```sql
      INSERT INTO new_shard.orders SELECT * FROM old_shard.orders
        WHERE bucket = $1 AND id > $2 ORDER BY id LIMIT 1000
        ON CONFLICT (id) DO NOTHING;          -- or: DO UPDATE ... WHERE new.version < excluded.version
      ```
- [ ] Checkpoint `(bucket, last_id)` after every batch.

> Unconditional copying with double-writes ON still corrupted **35 rows (0.17%)** — the copier
> read v5, a live write set both to v6, the copier wrote v5 over the top. At 500M rows that
> is **875,000 silently wrong rows**.

### 3 · Verify  ·  REVERSIBLE (nothing has changed yet)
- [ ] Row counts per bucket, old vs new. Must be exact.
- [ ] Checksums per bucket:
      ```sql
      SELECT bucket, count(*), md5(string_agg(id||':'||version, ',' ORDER BY id))
      FROM orders GROUP BY bucket;
      ```
- [ ] Vitess: `vtctldclient VDiff create --workflow r1 --target-keyspace commerce`
- [ ] **Gate:** zero mismatches. Not "a few". Zero.

### 4 · Shadow-read  ·  REVERSIBLE (stop shadow-reading)
- [ ] Serve reads from old; **also** run each read against new, compare, emit a metric, discard.
- [ ] Run ≥ 24 h to cover every query shape, including the month-end report.
- [ ] **Gate:** mismatch rate 0.00% over a full cycle. Measured, a 1-in-400 dropped-write bug
      surfaced here as **0.24% of shadow reads disagreeing** and nowhere else.

### 5 · Flip reads  ·  REVERSIBLE (flip the flag back, zero data loss)
- [ ] Ramp 1% → 10% → 50% → 100%, watching p99 per step.
- [ ] Double-writes stay ON. Old stays perfectly current, so rollback is free.
- [ ] **Sit here for days.** This is the cheap insurance and the step people cut short.

### 6 · Stop double-writing  ·  ⚠️ POINT OF NO RETURN
- [ ] Old begins to drift the instant you stop; rollback becomes replaying writes.
- [ ] Requires an explicit go/no-go with a named owner.
- [ ] Vitess: `Reshard SwitchTraffic --tablet-types primary`, then `Reshard Complete`.

### 7 · Drop old  ·  DESTRUCTIVE (restore from backup only)
- [ ] Wait for a **full backup cycle** to age out. Rename first, drop later.

---

## Hot-shard triage (one shard on fire, others idle)

| Symptom | Likely cause | Action |
|---|---|---|
| One shard hot, uniform key placement | Zipfian **access**, not placement. Measured 1.05x placement vs **5.83x load** | Salt the specific hot key |
| One tenant is >20% of writes | Whale | Directory-pin to a dedicated shard, or composite key |
| Newest shard hot, others idle | Monotonic shard key | Hash or composite; splitting will not help |
| All shards hot | Genuine capacity | Add shards — rebalance buckets |

**Salting cost, measured** — reading a salted key means reading all its pieces:

| salted | imbalance | shard-touch amplification |
|---|---|---|
| top 1 key (23.1% of load)  | 5.83x → **3.15x** | **4.47x** |
| top 4 keys (42.7%)         | → 2.18x | 7.41x |
| top 16 keys (60.3%)        | → 1.76x | 10.05x |

> Salt the key that is on fire, never the keyspace. Zipf has no bottom — there is always a
> next hottest key, and the returns diminish while the cost does not.
> **Adding shards does not help a hot key at all** — it still hashes to exactly one place.

---

## Metrics to have before you shard

- [ ] Per-shard: QPS (read/write split), CPU, disk, connections, p50/p99.
- [ ] `shard_imbalance_ratio` = max shard QPS / min shard QPS. Alert above 3x.
- [ ] `scatter_gather_query_ratio` = queries without the shard key / all queries. **Alert on
      any increase** — a new scatter query is a latency regression waiting for a slow shard.
- [ ] Fan-out p99 tracked separately from single-shard p99. Measured at S=8: **61 ms → 409 ms
      (6.7x)** while p50 moved only 12 ms → 23 ms. Never judge a fan-out by its median.
- [ ] Per-bucket row counts, exported hourly — this is what makes step 3 a query, not a project.
