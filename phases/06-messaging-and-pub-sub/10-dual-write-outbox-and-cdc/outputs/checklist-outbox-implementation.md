---
name: checklist-outbox-implementation
description: An implementation and review checklist for a transactional outbox and its relay or CDC connector, covering the transaction boundary, indexing, pruning, ordering, concurrency, lag monitoring and the outbox-versus-CDC-on-tables decision
phase: 6
lesson: 10
---

# Checklist — Transactional Outbox & CDC

Use this when you are **building** an outbox, **reviewing** someone else's, or **debugging** one at
3 a.m. Every unchecked box below has an incident attached to it.

The governing sentence, which the rest of this checklist only elaborates:

> **One logical operation must produce exactly one write, to exactly one system that has
> transactions. Everything else is a relay's problem.**

---

## Step 1 — The transaction boundary (get this wrong and nothing else matters)

- [ ] The outbox `INSERT` is inside **the same transaction** as the business change. Read the code
      and find the single `BEGIN` and the single `COMMIT` that bracket both. If they are in two
      different functions, two different service methods, or two different ORM sessions, prove they
      share a transaction — do not assume.
- [ ] **No broker client is imported anywhere in the request path.** This is the fastest review
      heuristic there is. If the request handler can reach `producer.send()`, the dual write is
      still there no matter what the outbox table is called.
- [ ] The ORM is not silently committing early. Check for autocommit, for a `flush()` mistaken for
      a commit, and for a framework that opens a transaction per repository call.
- [ ] The event payload is **fully materialised at insert time** — it does not contain a reference
      the relay must resolve later ("relay will look up the customer's email"). By the time the
      relay runs, that row may have changed. The event describes the world at commit time.
- [ ] The payload carries: a stable **`event_id`** (for consumer deduplication), an **`event_type`**,
      a **schema version**, a **`partition_key`**, a per-aggregate **`seq`**, `created_at`, and the
      **`trace_id`** so the flow stays traceable across the async hop.

## Step 2 — The relay: correctness

- [ ] Order is **publish, then mark**. Never mark-then-publish, which reintroduces the loss you
      just eliminated.
- [ ] **Consumers are idempotent.** The pattern is at-least-once *by construction* — the relay can
      die between the publish and the mark. If a consumer cannot process the same `event_id` twice
      safely, stop and fix that first; you have chosen a different bug, not fewer bugs.
- [ ] The claim/mark `UPDATE` is itself transactional and idempotent (marking an already-marked row
      is a no-op).
- [ ] Nothing in the system assumes a strictly monotonic per-key sequence **without deduplicating
      first** — redelivery makes the raw stream go backwards.
- [ ] The relay's failure to publish is **retried with backoff**, and a permanently failing row has
      an escape hatch (an attempt counter plus a dead-letter path — Lesson 8) so one poison event
      cannot block the entire outbox behind it. Verify this: head-of-line blocking on an ordered
      relay is a total outage, not a degraded one.

## Step 3 — The relay: concurrency and availability

- [ ] **Never run two relays without a claiming strategy.** Two naive pollers publish everything
      twice — measured at a 100% duplication rate. Pick one:

      | Strategy | Ordering | Throughput | Use when |
      |---|---|---|---|
      | Leader election (one active, others standby) | Preserved globally | Single-writer | Ordering matters across rows |
      | `SELECT ... FOR UPDATE SKIP LOCKED` | Per-key only | Scales with workers | Events are keyed, or order is irrelevant |

- [ ] Claims **expire** (a TTL column, or the lock released on connection loss), so a relay that
      dies mid-batch does not strand its rows forever.
- [ ] The relay is **not** a single point of failure with no standby. A single relay with no
      failover means every event in the system stops when one pod dies.
- [ ] Batch size is bounded, and you can state what it is: it is also the **maximum number of
      duplicates one crash can produce**.

## Step 4 — The outbox table itself

- [ ] There is a **partial index** on the unpublished rows:

      ```sql
      CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL;
      ```

      Confirm it with `EXPLAIN` on the *actual* relay query. Without it the poll degrades into a
      full table scan as the table grows — measured, 50,040 rows examined to find 40 pending.
- [ ] There is a **pruning or partitioning policy, written down and scheduled**. An unpruned outbox
      becomes the largest table in the database. At 1,000 events/sec and 500 B/event that is
      ~43 GB/day. Choose deliberately:
      - delete on publish (simplest; no replay, no audit trail)
      - mark published, nightly batched delete of rows older than *N* days
      - partition by day and drop whole partitions (cheapest at scale)
- [ ] Deletes run in **bounded batches**. One `DELETE ... WHERE published_at < ...` over ten million
      rows takes a long lock and generates enormous WAL.
- [ ] The retention window is at least as long as your worst-case replay need, and you know what
      that is.
- [ ] Sizing sanity check: `events/sec x bytes/event x retention` — compute it before launch, not
      after the disk alert.

## Step 5 — Monitoring (the relay dies silently; nothing else will tell you)

- [ ] **Outbox lag** — the age of the oldest unpublished row — is a first-class metric:

      ```sql
      SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at))) AS outbox_lag_seconds
        FROM outbox WHERE published_at IS NULL;
      ```

- [ ] The alert is on **seconds, not row count**. A pending count means nothing until you know the
      drain rate; an age means the same thing at any traffic level.
- [ ] The threshold is **above the poll interval**. Healthy baseline lag is `L = lambda x W` —
      about one poll interval's worth of rows — not zero.
- [ ] There is a **relay heartbeat** alerted on *absence*, separately from lag. Lag stays flat when
      traffic is quiet, so a relay that dies at 3 a.m. is invisible to the lag alert until morning.
- [ ] Also emit: publish failures, claim contention, batch size distribution, and rows pruned per
      run. Dashboard them next to consumer lag (Lesson 9) so producer-side and consumer-side
      backlog are visible on one screen.

## Step 6 — Choosing polling vs CDC

Decide with numbers, not taste. Measured trade-off from this lesson's program:

| Poll interval | DB queries/event | Empty polls | Mean latency | p95 |
|---|---|---|---|---|
| 5 ms | 4.99 | 79.9% | 6.0 ms | 7.0 ms |
| 25 ms | 1.00 | 0.5% | 12.1 ms | 27.0 ms |
| 100 ms | 0.25 | 0.0% | 60.5 ms | 102.0 ms |
| 500 ms | 0.15 | 0.0% | 307.3 ms | 540.0 ms |
| 2,000 ms | 0.14 | 9.1% | 1,488.5 ms | 3,540.0 ms |
| **CDC (log tail)** | **0.00** | — | **3.3 ms** | **4.0 ms** |

- [ ] Start with **polling** if you have no CDC infrastructure. It is simple, has no new operational
      surface, and 100–500 ms is fine for most event-driven work.
- [ ] Move to **CDC** when you need sub-100 ms propagation, when poll load on the primary is
      material, or when you already run a connector for something else. It wins on latency *and*
      database load simultaneously — the amortised cost is operational, not runtime.
- [ ] Never use **query-based capture** (`WHERE updated_at > watermark`) as a substitute for
      log-based CDC on anything that must be correct. It cannot see deletes, and it collapses
      intermediate states — measured, 3 of 7 changes captured.

## Step 7 — If you are using CDC

- [ ] **Replication slot retention is monitored and alerted.** This is the single most common
      serious CDC incident: a stopped consumer makes the database retain WAL until the disk fills,
      and a full WAL volume stops all writes. **A read-only consumer can take down your primary.**

      ```sql
      SELECT slot_name, active, pg_size_pretty(
               pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained
        FROM pg_replication_slots;
      ```

- [ ] `max_slot_wal_keep_size` (Postgres) or `expire_logs_days` / binlog retention (MySQL) is set as
      a **backstop**, so the database chooses a broken connector over a dead database. Decide this
      before the incident, not during it.
- [ ] Alert on **inactive slots**, not just on retention size — an inactive slot is a countdown.
- [ ] MySQL: `binlog_format = ROW` and `binlog_row_image = FULL`. Statement-based binlog is unusable
      for CDC.
- [ ] The **initial snapshot** plan is understood and scheduled: a large table's snapshot is a long,
      heavy read, and the handover to streaming must be gapless.
- [ ] Schema-change behaviour is known: what happens to the stream on `ALTER TABLE`, and who is
      notified.

## Step 8 — Outbox events or CDC on business tables?

Answer this explicitly in the design doc. Getting it wrong is expensive and slow to undo.

- [ ] **Domain events consumed by other teams → outbox table.** You own a deliberate, versioned,
      self-contained contract, and your schema stays refactorable.
- [ ] **Replication, analytics, search-index sync, cache invalidation → CDC on tables.** You want
      raw row changes, you control the consumer, there is no external contract to break.
- [ ] **Best of both: CDC tailing the outbox table.** Transactional correctness, a deliberate event
      contract, no polling load, near-zero latency, exact commit order.
- [ ] If someone proposes CDC on business tables for a public feed, confirm they have accepted, in
      writing, that: **every column rename is a breaking change for every consumer**, consumers get
      row diffs rather than business facts (`status: paid -> cancelled` versus
      `OrderCancelled(reason=...)`), and multi-table operations arrive shredded across streams.

## Step 9 — The consumer side (the inbox)

- [ ] The processed `event_id` is recorded **in the same transaction as the effect**:

      ```sql
      BEGIN;
        INSERT INTO inbox (event_id, processed_at) VALUES (:event_id, now());  -- PK conflict = seen
        -- the effect
      COMMIT;
      ```

- [ ] Deduplication is **durable**, not an in-memory set — it must survive a restart and work across
      replicas.
- [ ] The inbox is pruned, with retention longer than the maximum possible redelivery delay (broker
      retention plus your worst replay window).

## The one-line record for the design doc

```text
<event name>  ->  OUTBOX | CDC-ON-TABLE | OUTBOX+CDC
  transaction: <the single BEGIN..COMMIT containing the business write and the outbox insert>
  relay:       <poll Nms | CDC connector>   concurrency: <leader election | SKIP LOCKED>
  ordering:    <partition key>  ·  guarantee: AT-LEAST-ONCE  ·  consumer dedupe: <inbox table>
  retention:   <outbox prune policy>  ·  <inbox prune policy>  ·  <slot/binlog retention>
  alerts:      outbox_lag_seconds > <T>   ·   relay heartbeat absent   ·   slot retained > <GB>
```
