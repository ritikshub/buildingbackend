---
name: runbook-event-pipeline-operations
description: Operations runbook for an event-driven pipeline - daily and weekly health checks, the metric set with thresholds and rationale, a symptom-to-cause-to-action decision table, the safe procedures for deploying, replaying, redriving, repartitioning and rolling a schema, and a pre-production readiness checklist keyed to four invariants
phase: 6
lesson: 13
---

# Runbook — Operating an Event-Driven Pipeline

For a pipeline shaped like: **service + transactional outbox → relay/CDC → partitioned log → N consumer
groups → effects**, with a dead-letter queue and a dedup store per group.

Everything here defends four invariants. If a procedure below does not trace back to one of them,
it is ceremony and you should delete it.

| # | Invariant | The question it answers at 3 a.m. |
|---|---|---|
| **I1** | **No order is lost** — every committed order eventually produces its downstream effects | "Did anything fall through the crack?" |
| **I2** | **No customer is charged twice** — despite at-least-once delivery, redelivery and replay | "Did we do anything twice?" |
| **I3** | **No poison message halts the pipeline** — bad data is quarantined, not retried forever | "Is anything stuck?" |
| **I4** | **Per-customer ordering is preserved** — a key's events apply in the order they happened | "Did anything apply out of order?" |

---

## 0. Fill this in before you need it

Paste this block into your team's runbook page and keep the numbers current. Half the mistakes made
during an incident are made because nobody knew these.

```text
topic(s)                 __________       partition count            ____   (cannot be reduced)
retention                ____ days        earliest readable offset   ____
consumer groups          __________       partitions per group       ____   (parallelism ceiling)
offset commit interval   ____ s           max uncommitted window     ____ records
outbox prune horizon     ____ days        relay poll interval        ____ ms
dedup store              __________       dedup TTL                  ____   <- must exceed the next line
max DLQ residence        ____ hours       (i.e. your on-call response time, not your broker's timeout)
external effects         __________       provider idempotency TTL   ____
schema registry mode     __________       oldest schema in retention v____
owner / escalation       __________
```

**The single most common latent bug in this architecture is `dedup TTL < max DLQ residence`.**
Check that line first, every quarter.

---

## 1. Health checks

### Daily (5 minutes, or an automated report)

- [ ] **Outbox lag** — age of the oldest unpublished row, per service. Expect the baseline to be
      roughly the relay poll interval, **not zero**. A steady climb is a dead or throttled relay.
- [ ] **Relay heartbeat** — a counter the relay increments every loop. Alert on *absence*, because
      outbox lag stays near zero during quiet hours even when the relay is dead.
- [ ] **Consumer time lag per group**, in seconds, compared against the **retention window** rather
      than against zero. A group 4 hours behind on a 7-day log is fine; one 6 days behind is a day
      from silent, unrecoverable loss.
- [ ] **DLQ depth and, more importantly, arrivals in the last 24 h.** A first arrival after a quiet
      period almost always names a deploy.
- [ ] **Redelivery ratio** (deliveries ÷ unique messages) per group. A step change means lost acks,
      a mis-tuned lease, or a consumer that started crash-looping.
- [ ] **Reconciliation job result** — committed source rows versus applied downstream effects for
      the previous hour. **This is the only check that catches a silent, non-erroring loss (I1).**

### Weekly

- [ ] **Dedup store size and expiry** — is the TTL policy actually running? An unexpired dedup table
      becomes the largest table you own; an over-eager one silently voids I2.
- [ ] **Outbox table size** — is pruning keeping up? At 1,000 events/s and a 500-byte payload this
      grows 43 GB/day.
- [ ] **Rebalances per group per day.** More than a handful outside deploys means consumers are
      thrashing: GC pauses, aggressive liveness probes, or an autoscaler with no damping.
- [ ] **Partition skew** — max/mean records per partition. Above ~1.5 you are paying for consumers
      that cannot help; the busiest partition sets the drain time.
- [ ] **Schema versions present in retention** — confirm every upcaster still has a corresponding
      test, and that no cleanup PR deleted one.
- [ ] **Replication-slot / consumer-group retention on the CDC path.** An inactive slot retains WAL
      and can fill the primary database's disk — the single most common serious CDC incident.

### Before every release

- [ ] Compatibility check green against **every** registered schema version, not just the latest.
- [ ] Consumers deployed before producers for a backward-compatible change; producers before
      consumers for a forward-compatible one. If you cannot say which, the change is not classified.
- [ ] Autoscaler max ≤ partition count.
- [ ] The four invariants have automated checks that would fail the build.

---

## 2. The metric set

Export all of these. The right-hand column is the point: an alert that fires for four different
causes is a page, not a signal.

| Metric | Warn / Page | Why this threshold | What it distinguishes |
|---|---|---|---|
| `outbox_lag_seconds` | 30 s / 120 s | Grows at exactly 1 s per second when the relay stops. Baseline is the poll interval. | **Relay dead** — the only metric that moves when everything else looks healthy |
| `relay_heartbeat_age_seconds` | — / 60 s | Lag stays flat in quiet hours even with a dead relay | Relay dead **overnight** |
| `consumer_time_lag_seconds{group}` | 10% / 25% of retention | Comparable to your SLA *and* to the data-loss deadline | **Consumer behind**; the gap to retention is your deadline |
| `consumer_count_lag{group}` | dashboard only | Meaningless without a rate: 5,000 is a crisis at 10/s and noise at 10,000/s | Context for the above |
| all groups' time lag rising **together** | correlation rule | Independent groups share only the input | **Upstream problem** — do not scale consumers |
| `dlq_messages_total` rate + first arrival after quiet | any arrival after 1 h of zero | Depth alone is a backlog of already-known problems | **A new class of bad data**, usually a deploy |
| `redelivery_ratio{group}` | 1.05 / 1.20 | Healthy at-least-once sits just above 1.0 | **Lease too short** vs **consumer crash-looping** |
| `duplicates_suppressed_total` | step change | Your dedup store is the only component that sees redelivery pressure directly | Early warning that acks are being lost |
| `consumer_rebalances_total{group}` | 4/h | Every rebalance is a stop-the-world replay | **Thrashing** — GC, probes, autoscaler oscillation |
| `partition_max_over_mean` | 1.5 / 2.5 | The busiest partition sets drain time; effective parallelism is `N ÷ (max/mean)` | **Hot key** |
| `oldest_unprocessed_message_age` per partition | SLA-derived | Keeps rising when a partition is stalled but not growing | **Stalled** vs **slow** |
| `reconciliation_mismatch_total` | any nonzero | This *is* I1 and I2, measured against the source of truth | **A mechanism has failed** |

**Do not alert on consumer CPU.** A consumer blocked on a slow downstream has near-zero CPU and
enormous lag. **Do not alert on raw queue depth.** Convert to seconds first.

**Remember that a sampled metric under-reports its own peak.** A once-per-second sample of a lag
that climbs 1 s per second will miss the true maximum; set thresholds meaningfully below the number
that actually hurts.

---

## 3. Symptom → cause → action

### Consumer lag growing

| Check, in this order | If | Then |
|---|---|---|
| Are *all* groups rising together? | yes | Upstream. Go to **producer surge** or **relay** below. Do **not** scale consumers. |
| Outbox lag | rising | Relay problem, not a consumer problem. See **relay dead**. |
| Input rate | up | Genuine load. Scale out, capped at the partition count. Check `λ` before `μ`. |
| Per-message processing time | up | Downstream is slow. **Scaling out makes this worse** — it loads the real bottleneck harder. Fix or shed. |
| Redelivery ratio | up | A poison message or a mis-tuned lease is re-consuming capacity. See **DLQ filling**. |
| Rebalance count | up | Thrashing. Raise the liveness/session timeout, damp the autoscaler, use sticky + cooperative assignment. |
| Consumers vs partitions | equal | You are at the ceiling. Only three levers remain: process faster, shed, or repartition (see §4.4). |
| Time lag vs retention | > 50% | **Escalate now.** You are hours from irrecoverable loss with no error anywhere. |

**Rises then abruptly flattens** is not recovery. That is retention deleting your unread data.

### DLQ filling

1. Read one entry. It carries the **replay address** (topic, partition, offset), the delivery count,
   the error class and the `message_id`. Nothing else is needed to reproduce it.
2. **Classify.** Permanent (schema violation, business rejection, malformed payload) or transient
   (timeout, `5xx`, `429`)? Transient messages in a DLQ mean your retry window was too short for the
   outage, not that the messages are bad.
3. **Correlate with deploys.** A cluster of same-error dead letters starting at a timestamp is almost
   always a producer or consumer release. Roll back before you redrive.
4. **Do not redrive until the cause is fixed.** A redrive of unfixed messages is the same failure at
   higher volume, plus a burst of duplicates.
5. Check the pipeline is still *moving* (I3): compare throughput on the affected partition with its
   peers. If the poisoned partition is slower, the message is being retried in place instead of
   parked, and that is the bug to fix first.

### Duplicates appearing

| Signal | Likely cause | Action |
|---|---|---|
| Duplicates cluster around a deploy | Rebalance replay of the uncommitted window | Expected. Confirm the dedup store absorbed them. Reduce the commit interval only if the volume hurts. |
| Duplicates cluster around a relay restart | Publish succeeded, mark did not | Expected and by design; the outbox is at-least-once. Confirm suppression. |
| Duplicates of very old messages | A DLQ redrive or a replay outside the dedup TTL | **This is the TTL bug.** Widen the window before redriving, or redrive with dedup keys pre-loaded. |
| Duplicates with *different* message ids for the same business event | The id is generated per publish attempt | Producer bug, and the only one on this list that no consumer can fix. Derive the id from the business event and persist it. |
| Duplicates rising with no other change | Lease shorter than p99.9 processing time | Raise the visibility timeout above p99.9, or heartbeat from the work loop. |

### Ordering violations

1. Confirm the partition key is the aggregate id and is **present on every event** — a null key
   usually means round-robin, silently.
2. Confirm the partition count has not changed. Any repartition puts a key in two places at once
   while the old partition still has backlog.
3. Confirm nothing fans records out to a worker pool after `poll()`. The broker's guarantee ends at
   delivery; a thread pool destroys it in your own process.
4. Confirm the failing stream is not being parked to a retry lane. Parking preserves throughput and
   destroys per-key order — legitimate only for streams with no ordering requirement.
5. Confirm the consumer is idempotent. **A replayed older event applied after a newer one is an
   inversion**, so a duplicate defence is also an ordering defence.

### Outbox lag climbing

- **Linear ramp, 1 s per second** → the relay is stopped. Restart it; the backlog drains with no
  loss because nothing was deleted.
- **Sawtooth** → the relay is running but under-provisioned; raise batch size or add a claiming
  relay (`SELECT ... FOR UPDATE SKIP LOCKED`), never a second naive poller.
- **Flat and high** → the relay is publishing but the broker is rejecting. Check broker health and
  message size limits.
- **Zero pending but downstream sees nothing** → the relay is marking rows published without
  publishing. Check the ordering of publish and mark; it must be publish first.

### Relay dead

1. Confirm with the **heartbeat**, not with lag.
2. Restart. If it is a CDC connector, check the replication slot has not been dropped and that WAL
   retention has not filled the primary's disk. **A stopped CDC consumer can take down the database
   it only reads from.**
3. After recovery, expect a burst: all consumer groups' lag spikes together as the backlog lands.
   That spike is the recovery, not a new incident.
4. If the relay was down longer than your dedup TTL, treat the drain as a replay and read §4.3.

### Consumer thrashing

Symptoms: rebalance count high, throughput sawtoothing, duplicates elevated, no obvious error.

- Session/heartbeat timeout shorter than a worst-case GC pause → raise it.
- Kubernetes liveness probe stricter than the consumer's own work loop → loosen it, or make the
  probe reflect progress rather than process liveness.
- Autoscaler with no cooldown or deadband oscillating → damp it, add step limits, cap at partitions.
- Prefetch too large → one consumer holds work the idle ones could do, and a crash costs the whole
  batch.

---

## 4. Safe procedures

### 4.1 Deploying a consumer

1. Confirm schema compatibility against **all** registered versions.
2. Deploy consumers first for a backward-compatible change; producers first for forward-compatible.
3. Expect one rebalance and a replay of the uncommitted window. Confirm the dedup store handles it —
   check `duplicates_suppressed_total` rises and `reconciliation_mismatch_total` does not.
4. Roll one instance, watch lag and error rate for one full commit interval, then continue.
5. Prefer cooperative/incremental rebalancing with sticky assignment. Measured elsewhere in this
   phase: eager rebalancing duplicated 120 records (10.0%) against cooperative's 40 (3.3%).

### 4.2 Replaying a consumer group

**A replay is a deliberate, large-scale duplicate. Plan it as one.**

- [ ] Stop the group. Do not reset offsets on a running group.
- [ ] Confirm the target offset is **at or after** the earliest readable offset, or the reset fails.
- [ ] Confirm every schema version in the replay range still has a working upcaster, with a test.
- [ ] **Decide what must not happen twice** — emails, payments, webhooks — and disable, stub or
      idempotency-gate those effects for the duration. Your dedup TTL will not cover a replay.
- [ ] Size the downstream for the burst. A replay runs at drain speed, not at production speed.
- [ ] Reset, restart, and watch time lag fall on a monotonic curve. A flat curve means you are
      replaying into a bottleneck.
- [ ] Reconcile afterwards, against the source of truth.

### 4.3 Redriving a dead-letter queue

- [ ] Fix the cause first. Confirm with one message before moving the batch.
- [ ] Check the **dedup TTL against the age of the oldest DLQ entry.** If the entries are older than
      the window, redriving will duplicate their effects. Widen the window, or pre-populate dedup
      keys, or accept and document the duplicate rate.
- [ ] Redrive in **batches with a rate limit**. The DLQ is a backlog; releasing it at once is a
      self-inflicted burst on a system you have just repaired.
- [ ] Redrive to the *original* topic so partition keys and ordering rules still apply.
- [ ] Keep a copy. A redrive that fails again should not have consumed its own evidence.

### 4.4 Changing the partition count

**This is the most dangerous routine operation in the architecture.** `hash(key) % N` is a function
of N: going from 16 to 17 partitions relocates about 94.6% of keys, and any key that moves while its
old partition still has backlog is being processed by two consumers at once.

In order of preference:

1. **Do not.** Over-provision at design time for 3–5× projected peak. Idle partitions are nearly free.
2. **Drain first.** Stop producers, consume every partition to zero lag, change N, restart. The only
   procedure with no correctness window at all — because empty partitions cannot strand a key.
3. **Double, never increment.** 8→16 keeps half the keys put; 16→17 moves nearly all of them.
4. **Consistent hashing**, where supported, shrinks the blast radius (6.0% instead of 94.6% for
   16→17). It does not remove the hazard: every key that *does* move still splits.

Partition counts go up and never down. Treat the number as permanent.

### 4.5 Rolling a schema

1. Classify the change: additive-with-default (free), removal, rename (a delete plus an add —
   there is no rename on the wire), type change, enum addition, units change.
2. Run the compatibility check against **every** registered version in CI, as a required status.
   Non-transitive checks certify against the latest version only, which was never the question.
3. **Never redefine an existing field's units or meaning.** No checker on earth detects it. Add a new
   field and leave the old one alone forever.
4. Deploy in the order the compatibility direction permits; if the change is compatible in neither
   direction, use expand-contract with dual-writing.
5. **Write the upcaster and keep it forever.** Expand-contract never completes on a retained log:
   the old records are still there and every replay meets them.
6. Add a record of the new shape to the historical-corpus fixture.

---

## 5. Pre-production readiness checklist

Sign off per invariant. An unchecked box is a known defect, not an omission.

### I1 — No order is lost

- [ ] The business change and the event are written in **one transaction** (outbox or event sourcing).
      No handler contains two clients and two writes with no shared transaction.
- [ ] The relay **publishes, then marks**. Never the reverse.
- [ ] Offsets/acks are committed **after** processing, never before.
- [ ] The log retains data independently of acknowledgement, with the window written down.
- [ ] `outbox_lag_seconds` and a relay heartbeat are both alerted.
- [ ] A **reconciliation job** compares source rows to downstream effects on a schedule. This is the
      only control that catches a silent loss.

### I2 — No customer is charged twice

- [ ] The `message_id` is derived from the business event, generated **once**, and persisted — not
      regenerated per publish attempt.
- [ ] Every consumer with a non-idempotent effect writes its **dedup record and its effect in one
      commit**. No check-then-act anywhere.
- [ ] The dedup store is **shared across instances**, and its behaviour when unreachable is a
      decided policy ("stop and build backlog" or "process and risk duplicates"), written down.
- [ ] **Dedup TTL > maximum DLQ residence time**, where that maximum is set by your on-call rota.
- [ ] Every external effect uses an idempotency key derived from the business event, and its
      **provider TTL is recorded** and compared against your worst realised backoff.
- [ ] Idempotency shipped **before** the autoscaler was enabled.

### I3 — No poison message halts the pipeline

- [ ] Failures are **classified** permanent vs transient before any retry decision.
- [ ] Permanent failures go **straight** to the DLQ. No retries are spent on them.
- [ ] Retries use capped exponential backoff **with jitter**, and a maximum delivery count.
- [ ] Every consumer group has **its own** DLQ with a named owner.
- [ ] DLQ records carry the replay address, delivery count, error class and idempotency key.
- [ ] Long retries happen out of the main stream, and the ordering cost of that has been accepted
      **in writing** for each stream that does it.
- [ ] There is a test that proves a poisoned partition keeps pace with its peers.

### I4 — Per-customer ordering is preserved

- [ ] The partition key is the **aggregate id** — not the tenant, not a per-event UUID — and it is
      never null.
- [ ] Which of the key's three jobs (ordering, load distribution, parallelism ceiling) you optimised,
      and what you conceded on the other two, is written in the design doc.
- [ ] Consumers process a partition **serially**, or route to workers by key hash. No naive
      `gather()` over a poll batch.
- [ ] The partition count is sized for peak and treated as permanent.
- [ ] Consumers are idempotent, or reject stale versions — because a redelivered older event applied
      late is an inversion.
- [ ] There is a test that counts inversions and asserts zero.

### Cross-cutting

- [ ] Trace context propagates through the envelope and a span is emitted per hop.
- [ ] Schema compatibility is enforced in CI on the producer's repository, as a required status.
- [ ] Retention, dedup TTL, outbox prune horizon and DLQ residence are documented **as numbers**.
- [ ] Autoscaler maximum ≤ partition count.
- [ ] The PII erasure strategy was chosen before the first record was written.
- [ ] The fault schedule — kill the relay, expire a lease, force a rebalance, inject a malformed
      event, slow a downstream, roll a schema — runs against staging on a schedule, and the four
      invariant checks run after it.
