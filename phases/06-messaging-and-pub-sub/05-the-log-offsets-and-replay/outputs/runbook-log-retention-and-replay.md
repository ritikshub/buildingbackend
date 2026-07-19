---
name: runbook-log-retention-and-replay
description: Operating a log-based system - sizing retention against replay needs and disk, choosing time retention vs compaction per topic, safely replaying a consumer group in production, and handling offset-out-of-range and GDPR erasure
phase: 6
lesson: 05
---

# Runbook — Log Retention & Replay

For teams operating a log-shaped broker (Kafka, Kinesis, Pulsar, Redis Streams). Four
procedures plus the sizing arithmetic. Names are generic — substitute your broker's term:

| Here | Kafka | Kinesis | Pulsar | Redis Streams |
|---|---|---|---|---|
| position | offset | sequence number | cursor position | entry ID |
| reader | consumer group | application name | subscription | consumer group |
| age retention | `log.retention.hours` | `RetentionPeriodHours` | `retentionTimeInMinutes` | (none — use `MAXLEN`) |
| size retention | `log.retention.bytes` | — | `retentionSizeInMB` | `MAXLEN ~` |
| keyed retention | `cleanup.policy=compact` | — | topic compaction | — |

---

## 1. Sizing retention

Do this per topic, in writing, before the topic exists. Retention is not a default to inherit.

**Step 1 — establish the replay requirement, in hours.** Retention must exceed your realistic
worst case, which is almost always longer than people guess:

- [ ] **Time to detect** a bad consumer deploy — not the p50, the case where it is caught by a
      customer on a Monday. Often 24–72 h.
- [ ] **Time to fix and redeploy**, including a code review and a change freeze. Often 4–24 h.
- [ ] **Time to reprocess** the backlog once you start (see step 3).
- [ ] **The longest planned consumer outage** — a migration, a dependency upgrade, a holiday.
- [ ] **Backfill window for a new subscriber**: how much history must a brand-new service read
      to build its initial state? This is frequently the binding constraint, and it is the one
      nobody asks about until the launch is blocked.

> `retention >= detect + fix + reprocess`, then add 100% margin.
> A 24-hour retention on a topic whose consumers are owned by an on-call rotation is a
> data-loss incident waiting for a long weekend.

**Step 2 — price it.**

```text
bytes/day = avg_record_bytes x records/sec x 86,400
disk      = bytes/day x retention_days x replication_factor x (1 / (1 - headroom))
```

- [ ] Use **compressed** record size if the broker compresses (usually 3–10x on JSON).
- [ ] Multiply by **replication factor** — this is the number people forget, and it is usually 3.
- [ ] Keep **30–40% headroom**. A log at 95% disk cannot compact, cannot roll a segment, and
      is one traffic spike from a broker that will not start.
- [ ] Add per-partition size retention as a **backstop** even when time is your real policy.
      It is what stops a runaway producer from filling the disk and taking every topic on that
      broker with it. Whichever limit trips first wins.

**Step 3 — check that reprocessing is even possible.** If consumers run at roughly the
production rate with no spare capacity, replaying 7 days takes 7 days. Replay is only a real
capability if you have headroom or can scale consumers out (which needs partitions — see
Lesson 7). Record the number:

```text
reprocess_hours = backlog_records / (consumer_rate x scale_out_factor) / 3600
```

**Step 4 — set the lag alert against the window, not against zero.**

- [ ] Warn at **50%** of retention consumed by lag. Page at **75%**.
- [ ] Express the threshold in **time**, not records: `lag_records / consume_rate` = seconds
      behind. A raw record count means nothing without the drain rate.
- [ ] A consumer 6 days behind on a 7-day log looks healthy on a lag chart and is 24 hours from
      permanent data loss.

---

## 2. Choosing time retention vs compaction, per topic

Decide by the question consumers ask. Getting this wrong is expensive to reverse, because
compaction requires keys and keys are a schema decision.

| Ask this | Choose | Because |
|---|---|---|
| "What happened, in order?" | **time / size retention** | you need every transition, including superseded ones |
| "What is the current state of X?" | **compaction** | you need one record per key, and size tracks key count not event count |
| "Both" | **two topics** | do not compromise a single policy; fan the events into a compacted projection |

- [ ] **Never compact a topic feeding an aggregation that sums or counts events.** Compaction
      deletes superseded records, so a revenue report that sums every transition silently loses
      most of its input. This is the classic incident.
- [ ] **Compaction needs a key that means identity** (`customer_id`, `order_id`). You can only
      erase and deduplicate along the key you compact by — choose it for the access pattern
      *and* the erasure pattern.
- [ ] **Deletes need tombstones** (a record with the key and a null value). Set the tombstone
      grace period longer than your worst consumer lag, or a lagging consumer never sees the
      delete and keeps the record forever.
- [ ] **Compaction is not a size guarantee.** It converges toward one record per key; a topic
      with unbounded key cardinality (a `trace_id` key, say) does not shrink at all. Check key
      cardinality before choosing compaction — same cardinality trap as Phase 4 and Phase 9.
- [ ] Compaction **preserves offsets and leaves gaps**. Any tool that assumes contiguous
      offsets, or that computes lag as `end - start`, will be wrong on a compacted topic.

---

## 3. Replaying a consumer group in production

**This is a destructive, high-blast-radius operation.** Resetting an offset re-runs every side
effect the consumer has. Work top to bottom; do not skip to the command.

### Pre-flight — answer all six in writing

1. [ ] **Is the consumer idempotent?** If reprocessing record 42 twice produces a different
       result than once, replay will corrupt data. Check for: `INSERT` without an upsert or a
       unique key, counters incremented in place, `balance = balance + x`, appends to a list.
2. [ ] **What side effects fire on each record?** Enumerate them: emails, SMS, push
       notifications, payment captures, webhooks to customers, downstream publishes. **Every
       one of these is externally visible and cannot be undone.** If any exist, do not replay
       into the live consumer — see the shadow-group pattern below.
3. [ ] **What does this consumer publish?** If it emits to another topic, its consumers will
       double-process too. Walk the graph to its leaves; the blast radius is rarely one service.
4. [ ] **Can you use a new group instead of resetting the existing one?** Almost always yes,
       and it is almost always the right answer. A new group starts at your chosen offset, reads
       the same records, and leaves the production group untouched and running.
5. [ ] **Will the replay volume hurt anyone?** Reprocessing 6 hours in 10 minutes is a traffic
       spike into every downstream — database write load, third-party rate limits, cache
       churn. Plan to throttle.
6. [ ] **Do you have the exact offsets?** Prefer replaying by **timestamp** (`--to-datetime`) —
       it is what the incident is described in, and it does not require you to translate
       "since 09:00" into an offset by hand.

### The safe pattern: a shadow group

Preferred whenever the consumer has any external side effect.

1. [ ] Deploy the fixed consumer under a **new group name** (`payments-reconciler-repair-2026-07-18`).
2. [ ] Configure it with side effects **disabled** by flag (no email, no webhook), writing only
       to the store that needs repair — ideally to a shadow table first.
3. [ ] Start it at the chosen offset or timestamp; let it run to the tail.
4. [ ] Diff the shadow output against production, reconcile, then swap.
5. [ ] Delete the group. The production group never stopped and never lost its place.

### The direct reset — only when there are no external side effects

1. [ ] **Announce it.** Post the topic, group, offset range, expected duration and expected
       downstream load where the owning teams will see it.
2. [ ] **Record the current committed offsets for every partition.** This is your rollback.
       Save it somewhere outside the terminal you are typing in.

       ```bash
       kafka-consumer-groups --bootstrap-server $B --group $G --describe > /tmp/$G.before.txt
       ```

3. [ ] **Stop every member of the group.** Most brokers refuse to reset a group with live
       members; if yours does not, a running member will overwrite your reset on its next commit.
       Confirm zero members before continuing.
4. [ ] **Dry run first.** Every mature tool has one. Read the output — check the partition count
       and the offset deltas match what you intended.

       ```bash
       kafka-consumer-groups --bootstrap-server $B --group $G --topic $T \
         --reset-offsets --to-datetime 2026-07-18T09:00:00.000 --dry-run
       ```

5. [ ] **Execute**, then verify the new committed offsets before starting anything.

       ```bash
       kafka-consumer-groups --bootstrap-server $B --group $G --topic $T \
         --reset-offsets --to-datetime 2026-07-18T09:00:00.000 --execute
       ```

6. [ ] **Restart one member.** Watch it process for several minutes: error rate, downstream
       latency, output correctness on known records. Then scale up.
7. [ ] **Watch lag return to normal** and confirm the group reaches the tail. Post the result.

### Rollback

If the replay is producing wrong output: stop all members, reset offsets to the values saved in
step 2, restart. The records were never destroyed — that is the entire point of the log — so a
bad replay is recoverable as long as you saved the offsets before you started.

---

## 4. Incident: offset out of range

**Symptom:** a consumer logs `OffsetOutOfRange` / `InvalidSequenceNumber` / "offset N is below
the earliest available offset M", or silently jumps to the tail depending on its
`auto.offset.reset` setting.

**Cause:** the group's committed offset was deleted by retention. Either the consumer was down
or lagging longer than the retention window, or retention was shortened, or a size limit
tripped earlier than expected.

**There is no option that avoids loss. Choose deliberately, and record the choice.**

1. [ ] **Quantify the gap first.** `earliest_available - committed_offset` = records lost. Get
       this number before touching anything; it is what you will be asked for.
2. [ ] **Decide:**
       - **Reset to earliest** — reprocess everything still available. Costs duplicates and a
         load spike; run the pre-flight in section 3 first. Choose this when correctness of the
         derived store matters more than duplicate side effects.
       - **Reset to latest** — resume at the tail, accept a permanent hole. Choose this for
         metrics, caches, or anything that self-heals on the next update. **Log exactly which
         offset range was skipped** — that range is now an unrecorded data-loss event.
3. [ ] **Check whether another source can fill the gap** — a database table, an object-storage
       archive of the same stream, an upstream that can re-emit.
4. [ ] **Set `auto.offset.reset` deliberately on every consumer.** `latest` fails silently and
       loses data; `earliest` fails loudly and duplicates; `none` throws and makes a human
       decide. For anything financial, prefer `none`.

**Prevent the recurrence — do all four:**

- [ ] Lag alerting expressed as a fraction of the retention window (section 1, step 4).
- [ ] Retention long enough to survive a long weekend plus a holiday.
- [ ] An alert on **any** consumer group with no commits for > 1 hour, which catches the
      silently-dead consumer that a lag chart on a paused group will not.
- [ ] Size retention set as a backstop, and an alert when a topic is being trimmed by **size**
      rather than by age — that means it is expiring faster than you designed for.

---

## 5. GDPR erasure against an immutable log

An Article 17 erasure request against an append-only log has exactly three answers. "Delete the
record" is not one of them. **Pick one per topic, at design time.**

| Approach | When it works | Limits |
|---|---|---|
| **Wait for retention** | short-retention topics where the window is within your legal response time | useless for long-retention or compacted topics |
| **Tombstone + compaction** | topic is compacted and keyed by the subject (`user_id`) | only erases along the compaction key; needs a compaction cycle to complete; a lagging consumer must see the tombstone |
| **Crypto-shredding** | everything else, especially long-retention history | must be designed in before the first record is written |

**Crypto-shredding, concretely:** encrypt each subject's personal fields with a per-subject data
key held in a separate, mutable key store; write only ciphertext to the log. On erasure, delete
the key. The ciphertext remains and is permanently undecryptable, which regulators generally
accept as erasure.

- [ ] Decide this **before** the first record is written. It cannot be retrofitted to a log you
      have already filled.
- [ ] Erasure must reach **every derived store too** — the log is not the only copy. Enumerate
      consumers and their sinks now, while you can.
- [ ] Note that replaying a log after an erasure produces *different* downstream state than the
      original run. That is correct and intended, and it will surprise someone comparing a
      rebuild against a backup.
- [ ] Keep an **erasure audit log** — itself a log — recording which subject was erased when.
      Do not put the personal data in it.

---

## Quick reference

```text
retention        >= detect + fix + reprocess, x2 margin
disk             =  bytes/day x days x replication / (1 - 0.35 headroom)
lag alert        =  warn at 50% of retention window, page at 75%, measured in TIME
replay           =  new group + side effects off  >  resetting the production group
before reset     =  save current offsets; stop all members; dry-run; one member first
compaction       =  keyed topics only; never for aggregations that sum events
tombstone grace  >  worst-case consumer lag
erasure          =  crypto-shred, decided before the first record is written
```
