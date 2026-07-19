---
name: runbook-replication-lag-and-failover
description: For Postgres primary/standby fleets.
phase: 11
lesson: 07
---

# Runbook — Replication Lag, Stale Reads & Failover

For Postgres primary/standby fleets. Numbers assume ~250 B of WAL per commit; recompute
`bytes_per_commit` for your own workload before using the thresholds verbatim.

Companion to Phase 11 Lesson 07. Paste into your team wiki.

---

## 0. Fill this in before you need it

| Fact | Your value |
|---|---|
| Bytes of WAL per commit (`pg_current_wal_lsn()` delta / commits over 5 min) | ______ B |
| Commit rate: steady / peak / batch-window | ______ / ______ / ______ per s |
| Standbys, and which are user-facing vs analytics | ______ |
| `synchronous_standby_names` | ______ |
| Accepted RPO (rows), signed off by whom | ______ |
| Accepted RTO (seconds to promote) | ______ |
| Who may authorize a promotion at 03:00 | ______ |

**RPO in rows = flush_bytes / bytes_per_commit.** Convert to rows before any incident
conversation. "50 MB behind" means nothing at 03:00; "we would lose ~200,000 orders" ends
the discussion.

---

## 1. Alert thresholds

Alert on **byte distance**, never on time alone. Time-based lag reads **zero** on a fully
stalled replica once writes stop arriving on the primary.

| Signal | Warn | Page | Means |
|---|---|---|---|
| `flush_bytes` per standby | > 5 MB / 2 min | > 50 MB / 1 min | RPO. 50 MB ≈ 200,000 commits at risk |
| `replay_bytes` per standby | > 2 MB / 2 min | > 20 MB / 2 min | Staleness. Users are being served old rows now |
| `replay_lag` seconds | > 1 s / 5 min | > 10 s / 2 min | Human context only. Never the sole signal |
| Standby count in `pg_stat_replication` | < expected | < expected / 1 min | A gone standby often reports *no* lag, not infinite lag |
| `pg_replication_slots.active = false` | any | > 5 min | **Orphaned slot retains WAL forever → primary disk fills → all writes stop** |
| Primary disk free | < 30% | < 15% | Usually an orphaned slot or an archiver failure |
| `pg_stat_database_conflicts` rate | any sustained | — | Standby is cancelling queries to keep replay moving |

Also alert on **stale-read symptoms** at the application layer: rate of LSN-pinned reads
falling back to the primary. A jump there is replication trouble before it becomes lag.

---

## 2. The three lags — read them correctly

Run on the **primary**:

```sql
SELECT application_name,
       pg_wal_lsn_diff(pg_current_wal_lsn(), sent_lsn)   AS send_bytes,
       pg_wal_lsn_diff(pg_current_wal_lsn(), flush_lsn)  AS flush_bytes,   -- RPO
       pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn) AS replay_bytes,  -- staleness
       write_lag, flush_lag, replay_lag, state, sync_state
FROM pg_stat_replication ORDER BY flush_bytes DESC;
```

On a **standby**: `pg_wal_lsn_diff(pg_last_wal_receive_lsn(), pg_last_wal_replay_lsn())`
is the unapplied backlog; `pg_is_in_recovery()` confirms it is still a standby.

| Pattern | Diagnosis | First action |
|---|---|---|
| send high, flush/replay track it | Network or primary saturated | Check link, primary CPU/IO, WAL generation rate |
| send low, **flush high** | Standby disk cannot keep up (fsync bound) | Check standby IO; **this is your RPO growing** |
| send/flush low, **replay high** | **Replay conflict or single-threaded replay** | §3 — the WAL arrived, it is not being applied |
| All zero but standby missing from view | Standby disconnected entirely | Check slot, `state`, standby logs, network |
| Lag rises only during batch window | Expected; RPO spikes with it | Size RPO on the batch window, not the median |

---

## 3. Replay lag high, receive lag normal

The standby has everything and is not applying it. Users on that replica see old data with
**no error anywhere**.

```sql
-- On the standby: what is blocking replay?
SELECT pid, now() - query_start AS dur, state, left(query, 120)
FROM pg_stat_activity
WHERE state <> 'idle' AND backend_type = 'client backend'
ORDER BY query_start LIMIT 20;
```

1. **Pull the replica out of the read pool first.** Stop serving stale data before debugging.
2. Find the long query holding the snapshot; cancel it if it is a report:
   `SELECT pg_cancel_backend(<pid>);`
3. If replay is CPU-bound rather than blocked, replay is largely single-threaded — the
   primary can generate WAL faster than one core can apply it. Reduce write volume or accept
   the lag; more replica CPU will not help.

**The configuration trade — decide per replica, you cannot have both:**

| Setting | Effect | Cost |
|---|---|---|
| `hot_standby_feedback = on` | Primary retains row versions; queries stop being cancelled | **Bloat on the primary** caused by a query on another machine |
| `max_standby_streaming_delay = 30s` (default) | Replay waits, then cancels the query | Bounded lag, cancelled analytics queries |
| `max_standby_streaming_delay = -1` | Replay waits forever | **Unbounded stale reads, silently. Never on a user-facing replica.** |

Recommended: analytics replica → `hot_standby_feedback = on`, `max_standby_streaming_delay = 30s`.
User-facing replica → `hot_standby_feedback = off`, `max_standby_streaming_delay = 5s`.

---

## 4. Read routing decision table

**Default connection = PRIMARY. Replica routing is an explicit per-query opt-in.**
Default-to-replica fails silently as a correctness bug a customer finds; default-to-primary
fails loudly as a capacity graph you can watch.

| Query class | Route to | You accept | If wrong |
|---|---|---|---|
| INSERT / UPDATE / DELETE, anything in a txn | PRIMARY | linearizable | Fails loudly — fine |
| `SELECT … FOR UPDATE` | PRIMARY | lock only exists here | `ERROR: cannot execute in a read-only transaction` |
| Read-after-write (redirect, refetch) | REPLICA, **LSN-pinned** | read-your-writes | ~62% show the old value |
| Money, permissions, stock counts | PRIMARY | no staleness at all | Double-spend, oversell, ghost access |
| A user's own history | REPLICA, **session-pinned** | monotonic reads | Their comment appears, then vanishes |
| Someone else's profile / feeds | ANY REPLICA | seconds of staleness | Acceptable — this is the win |
| Search / listings / browse | ANY REPLICA | seconds of staleness | Fix at the cache, not the router |
| Analytics / exports / BI | DEDICATED REPLICA | minutes of staleness | One report evicts the OLTP working set |

**If you cannot say which class a query is in, it belongs on the primary.**

### LSN pinning — the implementation

1. After commit, read `pg_current_wal_lsn()` and return it (cookie / `X-Read-LSN` header).
2. Client echoes it on subsequent reads.
3. Router picks any replica whose `pg_last_wal_replay_lsn()` >= the token.
4. If none: poll every 2 ms up to 10 ms, then **fall back to the primary**.

Correctness never depends on step 4's wait succeeding. Measured: 0 stale reads out of 60,000,
1.32% of reads on the primary (vs 18.52% for a 500 ms sticky window), +0.30 ms mean latency.

Monitor the fallback rate. Sustained > 5% means replicas are unhealthy or the pin wait is too short.

---

## 5. Durability configuration

```text
# primary — quorum, not a single named standby
synchronous_standby_names = 'ANY 2 (r1, r2, r3)'
synchronous_commit = on
```

| `synchronous_commit` | Ack after | You lose on |
|---|---|---|
| `off` | WAL buffer, no local flush | Primary crash — **local loss, no replica involved** |
| `local` | own fsync only | Primary loss: everything not yet on a replica |
| `remote_write` | standby `write()` to OS | Standby **machine** dying (page cache, not disk) |
| `on` | standby fsync | Nothing, if the standby survives |
| `remote_apply` | standby applied + query-visible | Nothing — the only level that kills stale reads |

- **Never `FIRST 1 (...)`** — it always prefers the first standby, so a sick-but-not-dead
  standby blocks every write. Use `ANY k (...)`.
- **`remote_apply` makes every write pay for freshness only a few reads need**, and any
  replay conflict then stalls the primary. Prefer LSN pinning.
- With `synchronous_standby_names` set and **no** standby available, Postgres **blocks
  writes indefinitely**. That is correct, and it means clearing the setting is your fastest
  path back to accepting writes — at the cost of the guarantee. Know this before 03:00.

Measured latency cost per commit: same-AZ +0.66 ms (2.6x), cross-AZ +1.8 ms,
**cross-region +88.5 ms (211x)**. Cross-region synchronous is a different product.

---

## 6. Failover

**Before promoting — 60 seconds of checks that decide how much data you lose.**

```sql
-- Pick the standby with the highest FLUSH position, not the highest receive position.
SELECT application_name, flush_lsn, replay_lsn FROM pg_stat_replication
ORDER BY flush_lsn DESC;
```

1. **Is the primary dead, or unreachable?** If you cannot prove dead, assume partitioned and
   fence before promoting. Getting this wrong is split brain.
2. **Promote by highest `flush_lsn`.** Measured: the right choice lost 387 rows, the wrong
   one 3,203 — **8.3x more**. This is not a nicety.
3. **Fence the old primary first** — STONITH, revoke its lease, or block it at the network /
   security group. Hold promotion until strictly after the old lease could have expired.
4. Record `pg_current_wal_lsn()` of the promoted node and the wall-clock instant.
5. Promote: `pg_ctl promote` / `SELECT pg_promote();`
6. Repoint the application. Verify `pg_is_in_recovery() = false`.
7. Re-establish replication from the new primary; **the old primary cannot simply rejoin** —
   `pg_rewind` it or rebuild from a base backup. Until that finishes you are running with
   one fewer copy than you designed for.

**After every failover, compute and publish the actual loss:**

```text
rows_lost ≈ (primary_lsn_at_death − promoted_flush_lsn) / bytes_per_commit
```

Then reconcile from outside the database — idempotency ledger, event log, payment processor
records. **No caller was told anything.** Acknowledged-and-lost commits return zero errors.

### Split brain — signs and response

Signs: two nodes report `pg_is_in_recovery() = false`; writes appearing on one node and not
the other; timeline divergence in the logs; sequence values colliding.

1. **Stop writes to the old primary immediately** — network isolation is faster than a clean
   shutdown, and a clean shutdown may not be possible.
2. Do **not** attempt to merge. Choose the surviving timeline (normally the promoted node).
3. Extract the orphaned writes from the old node's WAL for **manual** reconciliation.
4. Rebuild the old node from a base backup.

Measured: unfenced, 25 s of split brain produced 1,080 rows on two timelines carrying 5,489
mutually unmergeable writes. A 2 s lease with promotion held to 5 s produced **0 divergent
rows** — 800 writes still lost, but bounded and explainable.

---

## 7. Capacity — when to stop buying replicas

Read capacity per replica = `C − W` (C = one node's ops/s, W = write ops/s);
replicas needed = `ceil(R / (C − W))`. Fraction of a new replica that serves users:
**97% at a 1% write ratio, 70% at 10%, 50% at 16.7%, 10% at 30%, impossible at 35%.**

**Past `W = C/2`, each replica adds more write work than the read work it relieves.**
Compute your write ratio quarterly; crossing C/2 is the trigger to plan sharding, not an
emergency, but it takes two quarters to execute.

---

## 8. Pre-incident checklist

- [ ] `bytes_per_commit` measured and RPO published **in rows**, not bytes
- [ ] Alerts on `flush_bytes` and `replay_bytes` (byte distance), not time alone
- [ ] Alert on `pg_replication_slots.active = false` — orphaned slots fill the primary's disk
- [ ] `synchronous_standby_names` uses `ANY k (...)`, never `FIRST 1 (...)`
- [ ] `max_standby_streaming_delay` is **not** `-1` on any user-facing replica
- [ ] Default DB connection is the **primary**; replica routing is opt-in per query
- [ ] Read-after-write paths use LSN pinning; fallback-to-primary rate is monitored
- [ ] Session-scoped reads are pinned to one replica or carry a last-seen LSN
- [ ] Analytics runs on a dedicated replica, never one serving users
- [ ] Fencing exists and has been tested — lease, epoch, or STONITH
- [ ] Failover tested **under batch-window load**, not on a calm system (RPO measured 128x
      worse during the batch than at rest)
- [ ] Post-failover reconciliation source identified (idempotency ledger / event log)
- [ ] Base-backup rebuild time known — it is how long you run without a spare
