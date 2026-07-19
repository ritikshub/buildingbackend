---
name: runbook-consumer-lag
description: On-call runbook for a growing consumer lag alert - the five signals to collect, a shape-plus-signal decision tree to the root cause, the remediation for each (including when NOT to scale out), how to compute your time-to-retention deadline, and how to drain a large backlog without destroying the downstream
phase: 6
lesson: 09
---

# Runbook — "Consumer lag is growing"

Use this when a lag alert fires on a consumer group, or when someone says "we're behind".

**The single most important thing on this page:** you are working against a deadline you can
compute. Find it in Step 3 before you start fixing anything, because it determines whether you
have eight hours or eight minutes, and therefore which remediations are even on the table.

---

## Step 0 — Two things to know before you touch anything

**Lag is not a buffer you get to spend.** It is a debt counter. A queue absorbs a *burst*; it
cannot absorb a *sustained* rate mismatch. "The queue is fine, it has depth" is the sentence that
turns a 20-minute incident into a 5-hour one.

**A flat lag graph is not necessarily good news.** Lag stops growing for two reasons: you reached
break-even, or the broker is now deleting unread messages at the retention limit as fast as new
ones arrive. **Assume the second until you have disproven it** (Step 1, signal 2).

---

## Step 1 — Collect these five signals, in this order

Do not skip ahead to a fix. Every wrong theory here costs you a remediation that makes things
worse. Budget three minutes.

| # | Signal | Where to get it | What you are looking for |
|---|---|---|---|
| 1 | **Input rate (lambda)** | producer metrics, or broker bytes-in / messages-in | Did the *producers* change? Cheapest check, and it reframes everything. |
| 2 | **TIME lag** — age of the oldest unprocessed message | SQS `ApproximateAgeOfOldestMessage`; Pub/Sub `oldest_unacked_message_age`; Kafka: your own gauge from record timestamps | The only number comparable to your SLA and your retention. If it equals the retention window, **you are losing data now**. |
| 3 | **Consumer count and per-partition assignment** | `kafka-consumer-groups.sh --describe`; RabbitMQ consumer count per queue | Any partition with **no** consumer, or fewer members than expected. A dead partition hides inside a healthy aggregate. |
| 4 | **Per-message processing time and consumer CPU** | app metrics; container CPU | Slow handler (high time, high CPU) vs blocked handler (high time, **low** CPU). |
| 5 | **Downstream latency + redelivery/rebalance rate** | dependency p99; broker redelivery counter; group membership events | Is lag a symptom of something else entirely? |

Also grab the **lag shape over the last 60 minutes**, not just the current value. The shape is the
diagnosis; the value is not.

---

## Step 2 — Decision tree: shape + signal → root cause

Read the shape first, then confirm with the signal.

```text
Lag graph is FLAT AND NONZERO, throughput normal
  -> HEALTHY. The standing backlog is one poll cycle of arrivals. Stand down.

Lag is FLAT AT ZERO and throughput is ZERO
  -> CONSUMERS ARE DEAD, not healthy. A depth alarm will never fire for this.
     Confirm: signal 3 (no group members) + signal 5 (no heartbeats).
     Note: client-computed lag metrics (Kafka records-lag-max) report NOTHING when
     the consumer is dead. A missing metric is not a zero metric.

Lag RISES then goes ABRUPTLY FLAT, time lag == retention window
  -> SEV-1: RETENTION IS DELETING UNREAD DATA. Silent, no errors anywhere.
     Go to Step 3 and Step 5 immediately. Do not wait for further diagnosis.

Lag is a SAWTOOTH, troughs reach ~zero
  -> A BATCH PRODUCER (cron, nightly export). Not an incident.
     Fix the ALERT (alarm on the trough, not the peak), not the system.

Lag SPIKED then is DECLINING linearly
  -> A BURST BEING ABSORBED. Working as designed.
     Compute recovery = excess / headroom. Act only if that exceeds your SLA.
     Expect TIME lag to keep RISING for a while after COUNT lag starts falling.
     That is normal during recovery of a dense burst - do not over-react.

Lag shows NARROW REPEATED SPIKES
  -> REBALANCE THRASH. Confirm: signal 5, correlate with deploys/autoscaler events.
     Cause is usually: processing time > poll timeout, a flapping autoscaler,
     or a consumer crash loop.

Lag is RISING LINEARLY  -> sustained under-capacity. Discriminate:
  |
  +- Input rate (1) stepped up?            -> PRODUCER SPIKE
  +- Consumer count (3) down / partition unassigned? -> CONSUMERS DOWN
  +- Processing time (4) up, CPU HIGH?     -> SLOW CONSUMER (usually a deploy)
  +- Processing time (4) up, CPU LOW?      -> DOWNSTREAM BOTTLENECK  ** see warning **
  +- Redelivery rate (5) high, head not advancing? -> POISON MESSAGE
```

### The warning, in full

> **When the downstream is the bottleneck, DO NOT SCALE OUT.**
>
> A consumer blocked on a slow database has near-zero CPU and enormous lag. Going from 6 replicas
> to 24 applies **four times the load** to the dependency that is already failing. You will
> convert a lag incident into a database outage, and then you will have both.
>
> The tell is unambiguous: **low consumer CPU + elevated downstream p99**. If you see it, cap or
> freeze the autoscaler *first*, then fix the downstream.
>
> This is also why consumers must never autoscale on CPU: a blocked consumer looks idle, so a
> CPU-driven scaler scales it **down** at exactly the wrong moment.

---

## Step 3 — Compute the deadline before you fix anything

```text
1. slope       = d(time lag)/dt          [seconds of lag per second of wall clock]
                 (or: 1 - mu/lambda)
2. retention   = your topic/queue retention window, in seconds
3. deadline    = (retention - current time lag) / slope

   Worked example from the lesson:
     lambda = 800/s, mu = 250/s  ->  slope = 1 - 250/800 = 0.6875 s/s
     retention 6h = 21,600s      ->  deadline = 21,600 / 0.6875 = 8h43m from onset
```

Write the wall-clock time on the incident channel. **That timestamp is when irrecoverable loss
begins**, and everything below is chosen relative to it.

Then compute the **drain time** for each candidate fix, because fixing the consumer is not the
same as fixing the incident:

```text
drain time = backlog / (new mu - lambda)          <- headroom, not capacity

   Backlog 9.9M, lambda 800/s:
     revert only        mu=1,000/s   headroom   200/s  ->  13h45m to drain
     revert + 2x group  mu=2,000/s   headroom 1,200/s  ->   2h17m
     revert + 4x group  mu=4,000/s   headroom 3,200/s  ->    51m
```

Restoring baseline capacity stops the bleeding but can leave every downstream consumer reading
hours-old data. **Decide explicitly whether "not losing data" is enough, or whether you also need
"caught up by 09:00".**

### If you cannot make the deadline

You are choosing what to sacrifice. In preference order:

1. **Shed low-value traffic** (Step 4) — you pick the loss, deliberately, and you count it.
2. **Degrade** — process everything, but cheaply: skip enrichment, defer derived fields.
3. **Copy the backlog out** — dump the unprocessed range to object storage for later replay, so
   the retention deadline stops being a data-loss deadline. Often the single best move.
4. **Extend retention** — many brokers allow this live. Do this *early*; it is nearly free and it
   buys back the whole deadline. Check disk headroom first.
5. **Accept the loss and document precisely which stream, which time range, and how much.**

Never let the retention window make this choice for you. It deletes from the head at random and
takes your highest-value messages in proportion to their share of the stream.

---

## Step 4 — Remediation by root cause

| Root cause | Do this | Do NOT do this |
|---|---|---|
| **Producer spike** | Confirm it is legitimate. Scale consumers if partitions allow; otherwise shed or throttle at the producer. | Assume the consumer is broken. |
| **Consumers down / partition unassigned** | Restart or reschedule. Check for a crash loop, an OOM kill, or a failed deploy. Verify assignment covers every partition. | Add *more* replicas before finding out why the existing ones died. |
| **Slow consumer (high CPU)** | Correlate the slope's inflection point with the deploy timeline; revert. Then remove the synchronous call from the hot path or batch the downstream writes. | Scale out as the permanent answer — you are renting mu instead of raising it. |
| **Downstream bottleneck (low CPU)** | Freeze the autoscaler. Fix or scale the dependency. Add batching so N messages become 1 downstream call. Consider a concurrency limit toward that dependency. | **Scale consumers out.** See the warning above. |
| **Poison message** | Check redelivery counts and the head message. Route to the DLQ so the partition can advance. | Restart consumers repeatedly — the message will still be there. |
| **Rebalance thrash** | Lengthen cooldowns, raise `max.poll.interval.ms` **or** lower `max.poll.records` so a batch finishes inside the timeout, freeze the autoscaler during the incident. | Add replicas — each one costs another stop-the-world pause. |
| **At the partition ceiling** | Nothing in the consumer helps. Repartition (plan for ordering/key changes), split the topic, or make each message cheaper. | Keep scaling. Consumers beyond the partition count are assigned no work and still cost a rebalance each. |

### Prefetch, if you are touching it

- **Too low** starves on round trips: `prefetch=1` measured 2.91x slower than optimal.
- **Too high** costs memory, fairness and redelivery exposure. Prefetch is a *claim on work no
  other consumer may take*, so a large one lets one consumer hoard a bounded backlog while others
  idle.
- Size it: `P = e/(1-e) x RTT / processing_time`. For 95% of peak that is `19 x RTT/s`.
- Sanity-check memory: `prefetch x message_size x consumers` must be well under the container
  limit, or a burst becomes an OOM crash loop that redelivers everything it held.
- **Slow processing means LOWER the prefetch**, not raise it — otherwise the batch outlives the
  poll timeout and the group is evicted mid-batch.

---

## Step 5 — Draining a large backlog without causing a second outage

Once you are catching up, the backlog itself becomes the hazard: it is a stored burst, and
releasing it at full speed can flatten every downstream system at once.

1. **Snapshot first, if the deadline is close.** Copy the unprocessed range to object storage
   before you do anything else. Now the retention window cannot hurt you.
2. **Turn off the autoscaler's scale-*down* leg.** You do not want it removing capacity mid-drain
   and paying a rebalance for it.
3. **Ramp capacity, do not step it.** Add consumers in stages and watch the *downstream's* p99
   after each stage, not just your own lag. Stop increasing as soon as the dependency's latency
   starts moving.
4. **Rate-limit the drain deliberately.** A consumer group at 4x normal throughput is a 4x load
   test on every downstream, unannounced. Cap the drain at a rate the downstream is known to
   survive, and accept a longer recovery.
5. **Batch downstream writes.** During a drain this is often worth more than extra replicas —
   one 500-row insert instead of 500 single-row inserts raises mu without adding load.
6. **Watch for duplicate amplification.** A drain at high concurrency with a large prefetch means
   more in-flight messages, so any consumer crash redelivers more. Confirm your idempotency keys
   are doing their job before you increase concurrency.
7. **Announce it.** Downstream owners should hear "we are replaying 9M messages over the next two
   hours" *before* their dashboards do.
8. **Declare recovery on TIME lag, not count lag.** Time lag keeps climbing after count lag
   starts falling. Recovery is when the oldest unprocessed message is fresh again.

---

## Step 6 — After the incident

- [ ] Is there a **time lag** metric, or only queue depth? If only depth, add time lag today.
- [ ] Is there an alert on time lag vs the **retention window**, separate from the SLA alert?
- [ ] Is there an alert on the lag **derivative** ("rising for 15 minutes")?
- [ ] Is **consumer liveness** monitored independently? Zero lag + zero throughput = dead
      consumers, and client-computed lag metrics go *silent* rather than high.
- [ ] Is the autoscaler capped at the **partition count**, scaling on **lag not CPU**, with a
      cooldown and an asymmetric scale-down?
- [ ] Are high-value and low-value messages on **separate** topics/queues, so shedding and
      degradation are possible next time without inspecting every message?
- [ ] Is the retention window long enough to survive your worst realistic recovery time?
- [ ] Is prefetch sized from RTT and processing time, and is
      `prefetch x message_size x consumers` inside the container limit?
