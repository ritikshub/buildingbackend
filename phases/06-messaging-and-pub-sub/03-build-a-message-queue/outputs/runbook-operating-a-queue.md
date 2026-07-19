---
name: runbook-operating-a-queue
description: Operating a work queue in production - the five metrics, how their combinations diagnose the failure, visibility-timeout tuning, safe consumer deploys, and the emergency levers
phase: 6
lesson: 03
---

# Runbook — Operating a Work Queue

For a point-to-point queue with competing consumers (SQS, RabbitMQ, Redis Streams
consumer groups, or any broker with claim/ack/lease semantics). Use during an incident,
or read it once before you are paged at 3 a.m.

---

## 1. The five metrics, and what each one alone cannot tell you

Instrument all five. Every diagnosis below is a *combination* — no single metric identifies
a failure on its own, which is why dashboards with only queue depth are so misleading.

| # | Metric | What it is | Alert on |
|---|---|---|---|
| 1 | **Queue depth** | messages ready for delivery | never alone — convert to time (see below) |
| 2 | **Oldest-message age** | wall-clock age of the oldest ready message | **this is your primary alert** |
| 3 | **In-flight count** | claimed, unacked, lease not yet expired | sustained rise, or a value near your consumer count x prefetch |
| 4 | **Ack rate** | successful acks per second (= real throughput) | drop against baseline |
| 5 | **Redelivery rate** | deliveries where delivery_count > 1, per second | > ~1% of delivery rate |

**Depth is meaningless without a rate.** 5,000 messages is a catastrophe at 10 msg/s and a
rounding error at 10,000 msg/s. Convert with Little's Law:

```text
seconds of backlog = queue depth / ack rate
```

**Prefer oldest-message age over depth-derived time.** It needs no drain rate, it is directly
the answer to "how far behind are we?", and — critically — **it rises when the queue is stalled
even though depth is flat**. A stalled queue with steady depth looks perfectly healthy on a
depth chart and is screaming on an age chart.

Also record, per message: **delivery count** (SQS: `ApproximateReceiveCount`; Redis Streams:
the delivery counter in `XPENDING`). You cannot find a poison message without it.

### Suggested alerts

```text
P1  oldest_message_age > 5 * normal_p99_end_to_end_latency     for 5 min
P2  oldest_message_age > 15 min                                for 5 min
P2  ack_rate < 20% of the trailing-7-day same-hour baseline    for 10 min
P2  redelivery_rate / delivery_rate > 0.05                     for 10 min
P3  depth / ack_rate > 300 s (5 min of backlog)                for 15 min
P3  in_flight_count flat and non-zero while ack_rate == 0      for 10 min
P3  dead_letter_queue_depth > 0                                for 15 min
```

Alert on **time**, not counts. A count threshold has to be retuned every time traffic changes;
a time threshold means the same thing forever.

---

## 2. Diagnosis — reading the five together

Find the row that matches. The combination is the diagnosis.

| Depth | Oldest age | In-flight | Ack rate | Redeliveries | Diagnosis |
|---|---|---|---|---|---|
| rising | rising | **~0** | **~0** | ~0 | **Consumers are down or disconnected.** Nobody is claiming. |
| rising | rising | normal | **low but steady** | ~0 | **Consumers are slow / under-scaled.** They are working, just not fast enough. |
| rising | rising | normal | normal | ~0 | **Producers spiked.** Consumers are fine; arrival rate exceeded capacity. |
| **flat** | rising | normal | **normal** | **high** | **Poison message(s) looping.** Throughput is being spent on retries, not progress. |
| flat/falling | rising | **high and flat** | ~0 | ~0 | **Consumers hung.** Work claimed, nothing finishing; leases not yet expired. |
| rising | rising | normal | normal | **high** | **Visibility timeout too short.** Live work is being redelivered mid-flight. |
| falling | falling | normal | high | ~0 | Recovery in progress. Do nothing. |

### The three you will actually be paged for

**"Consumers are down" vs "consumers are slow"** — the discriminator is **ack rate**, not depth.
Both make depth and age rise identically. Down means ack rate ~0 and in-flight ~0; slow means
ack rate is positive but below arrival rate, and in-flight sits at its normal level. Check ack
rate *before* you scale anything: scaling a consumer fleet that cannot connect to the broker
achieves nothing except a bigger bill and more connection errors.

**"Slow" vs "hung"** — a slow consumer still acks. A hung one claims work and never finishes,
so **in-flight is high and flat while ack rate is zero**. In-flight that does not move is the
signature. Without leases these messages are stuck forever; with leases they will return after
the timeout, so expect a redelivery spike shortly after — that is the system healing, not a new
problem.

**Poison message** — the giveaway is **high ack/delivery rate with a flat depth**. The system is
busy and making no progress. Confirm in one query:

```text
SQS            -> ApproximateReceiveCount on received messages; look for a cluster >> 1
Redis Streams  -> XPENDING <key> <group> - + 20        (delivery counts + idle time, sorted)
RabbitMQ       -> x-death header count, or the dead-letter queue's depth
```

A handful of messages at 20+ deliveries while everything else is at 1 names the culprit
immediately. Get the message id, get the payload, reproduce locally.

---

## 3. Tuning the visibility timeout (lease)

Both directions cost you. Get this from data, not intuition.

- **Too short** → live work is redelivered while the first consumer is still processing. You
  get duplicates with **no failure of any kind** — the most confusing bug shape in messaging,
  because every component is healthy.
- **Too long** → a genuinely dead consumer's messages wait that long before anyone retries.

**Procedure:**

1. Measure end-to-end processing time per message. Take the **p99.9**, not p50 or p99.
2. Set `visibility_timeout >= 2 x p99.9`, with a floor of 30 s.
3. If p99.9 is large or unbounded (external API calls, video transcodes, LLM calls), do **not**
   set a huge timeout. Set a short one (30–60 s) and **heartbeat** instead.
4. Verify: redelivery rate should be well under 1% of delivery rate in steady state.

**Heartbeating** (`ChangeMessageVisibility` / `XCLAIM` / a lease-extend call) lets a live
consumer extend its own claim. This is the correct answer for long or variable jobs: a short
lease gives fast crash detection, and heartbeats stop legitimate long-runners being duplicated.

> **Heartbeat correctly.** Beat from the work loop between units of work, or gate the beat on a
> progress counter the work updates. A heartbeat on an independent timer thread keeps beating
> while the worker thread is deadlocked, which turns a detectable failure (lease expiry) into an
> undetectable one (a message pinned forever by a zombie). A heartbeat that cannot fail is not a
> health check.

**Remember what the lease does not promise.** Redelivery latency is the lease duration **plus
the time to drain the backlog ahead of the message**, because an expired message returns to the
*back* of the queue. With a deep queue this is minutes. Never write a retry-latency SLA against
the visibility timeout alone.

---

## 4. Safe consumer deploys and draining

A consumer killed mid-message is not a data-loss event in an at-least-once queue — the lease
expires and the message is redelivered. But every ungraceful kill costs one lease duration of
latency per in-flight message, and re-runs work that may be expensive or externally visible.

**Graceful shutdown, in order:**

1. Trap `SIGTERM`. **Stop claiming new messages immediately.**
2. Finish messages already in flight, then ack them.
3. For anything that will not finish inside the shutdown window, **nack it explicitly**
   (`basic_nack(requeue=True)`, or set visibility timeout to 0) so it is redelivered instantly
   instead of waiting out the lease.
4. Close the broker connection, then exit 0.

**Set the platform's grace period above your p99 processing time**, or the orchestrator's
`SIGKILL` lands mid-message and step 2 never completes. In Kubernetes that is
`terminationGracePeriodSeconds`; the default of 30 s is too short for many consumers.

**Keep prefetch small during deploys.** A consumer holding a prefetch of 100 strands 100
messages on every rolling-restart pod kill.

**Rolling deploy checklist:**

- [ ] Consumers are idempotent — redelivery during the deploy is expected, not exceptional.
- [ ] Grace period > p99 processing time.
- [ ] Roll one pod (or a small percentage) first; watch ack rate and redelivery rate for one
      full minute before continuing.
- [ ] Depth and oldest age are at baseline **before** starting. Never deploy into a backlog.
- [ ] The new consumer version can process messages produced by the *old* producer, and vice
      versa — both versions run simultaneously during the roll (see Lesson 12).

---

## 5. Emergency levers

In escalating order of blast radius. Prefer the earliest one that works.

### Lever 1 — Scale consumers out (safe, first resort)

Size it with Little's Law rather than guessing:

```text
consumers needed = target throughput (msg/s) x processing time (s)
# 500 msg/s at 200 ms each  ->  100 concurrent consumers
```

To burn down a backlog in a target time, add the drain requirement:

```text
required drain rate = arrival rate + (current depth / target seconds to clear)
```

**Check the downstream first.** Consumers usually bottleneck on a database, an API, or a rate
limit — not CPU. Tripling consumers against a saturated database converts a queue backlog into
a database outage, which is strictly worse because it takes your synchronous traffic with it.

### Lever 2 — Isolate the poison message (surgical)

Do not purge the queue to remove one bad message.

1. Identify by delivery count (section 2).
2. If a dead-letter queue is configured with `maxReceiveCount`, it will move there on its own.
   Confirm it does, then move on.
3. If not, consume it specifically and ack it into a side store (a table, an S3 object) so the
   payload is preserved for analysis.
4. File the bug. Add the DLQ (dead-letter queue) if it was missing — this failure will recur.

### Lever 3 — Pause producers (buys time without losing data)

If the backlog is growing faster than you can drain it and the work is deferrable, stop the
producers rather than dropping messages. Feature-flag the publish path. Messages that are never
produced can be produced later; messages that are purged are gone.

### Lever 4 — Redrive from the dead-letter queue (recovery, after a fix)

After deploying a fix, move dead-lettered messages back to the main queue.

- [ ] The fix is deployed **and verified** on live traffic first.
- [ ] Redrive at a **throttled rate** — a DLQ dumped back at once is a self-inflicted thundering
      herd on a service that just recovered.
- [ ] Confirm the messages are still meaningful. A 3-day-old "send password reset email" should
      be discarded, not sent. **Check message age before redriving anything user-visible.**
- [ ] Watch the redelivery rate during the redrive; if messages fail again, stop immediately.

### Lever 5 — Purge (last resort, irreversible)

`PurgeQueue` / `XTRIM` / `queue_purge` deletes everything. It is occasionally correct — a queue
of stale position updates where only the latest matters, or a backlog of work that is now
provably irrelevant. It is never correct for anything with a customer attached.

- [ ] Written approval from an incident commander, recorded in the incident channel.
- [ ] The messages are **provably** worthless (write down why).
- [ ] Snapshot first if the broker supports it, or drain to a file rather than purging.
- [ ] Announce it. A purge is invisible to every downstream team until they notice work missing.

---

## 6. Pre-production checklist

Run this before a queue carries anything that matters.

- [ ] **Consumers ack after the work, never before.** Confirm the setting explicitly:
      `auto_ack=False` (RabbitMQ), `DeleteMessage` after processing (SQS), `XACK` after
      processing (Redis Streams). Ack-on-delivery loses work silently.
- [ ] **Consumers are idempotent.** At-least-once means duplicates *will* arrive; they are
      normal operation, not an incident. (Lesson 6.)
- [ ] **Durability is fully configured.** RabbitMQ needs all three: `durable=True` on the
      queue, `delivery_mode=2` on the message, and publisher confirms. Any one missing loses
      messages on broker restart, and a non-durable queue is *deleted* on restart, not drained.
- [ ] **Visibility timeout is set from measured p99.9**, with heartbeats for long jobs.
- [ ] **A dead-letter queue exists**, with a `maxReceiveCount` (5–10 is typical) and an alert on
      its depth > 0. A DLQ nobody watches is a silent data-loss mechanism.
- [ ] **Prefetch is deliberate**, not defaulted. Small for slow/variable work, large for fast
      uniform work.
- [ ] **All five metrics are on one dashboard**, on the same time axis, so the combinations in
      section 2 are readable at a glance.
- [ ] **Alerts are on time, not counts** (oldest-message age is the primary).
- [ ] **Graceful shutdown is implemented and tested** by actually killing a pod under load.
- [ ] **A trace/correlation id rides in the message envelope**, or you cannot answer "what
      happened to this order?" across the hop. (Phase 9.)
- [ ] **Ordering assumptions are written down and justified.** With competing consumers you have
      none; if you need it, you need partition keys (Lesson 7).
- [ ] **Log compaction / retention is configured** on the broker's own storage, so restart time
      grows with queue *contents*, not queue *lifetime*.
