---
name: checklist-partition-key-design
description: A design-review checklist for choosing a partition key and partition count before a topic goes to production, including the skew arithmetic, the repartitioning hazard, and the two ways to remove the ordering requirement entirely
phase: 6
lesson: 07
---

# Checklist — Choosing a Partition Key and a Partition Count

Run this **before** the topic exists. Both decisions are close to permanent: the key is baked into
every producer, and partition counts go up and never down. Getting them wrong is not a
performance bug — it is a data-corruption bug that surfaces in a support queue weeks later,
after every dashboard has said the system is healthy.

The governing question, asked first:

> **Which specific pairs of messages will corrupt data if they are processed in the wrong order?**

If you cannot answer that with entity names, stop. You do not yet know what you are buying.

## Step 1 — Write down the ordering requirement, per entity

Do not write "the events must be ordered." Write the constraint as pairs.

- [ ] For each event type, list the events that **must not** be reordered relative to it, and name
      the field that identifies the thing they share.

      ```text
      AccountCreated -> AccountUpdated -> AccountDeleted   ordered per: account_id
      WalletDebit / WalletCredit                           ordered per: NOTHING (addition commutes)
      OrderPlaced -> OrderShipped                          ordered per: order_id
      InvoiceLine -> InvoiceFinalised                      ordered per: invoice_id
      ```

- [ ] For each row, state **what breaks** if the pair swaps: orphan row, resurrected row, lost
      update, negative intermediate balance, double charge. If the answer is "nothing", you have
      just deleted a requirement — record that, it is the cheapest win available.
- [ ] Confirm no requirement crosses entities ("all events for a tenant, in order"). A cross-entity
      requirement forces a coarser key and costs you parallelism — make it explicit and challenge it.
- [ ] Check the **consumers you do not own**. A second team's aggregation job may need ordering by
      a different field than yours. The key serves every consumer of the topic, not just the first.

## Step 2 — Verify the candidate key actually satisfies it

- [ ] Every event that must be ordered together **carries the key field, always, non-null**. A null
      key means no ordering at all — the producer batches into whichever partition is convenient.
      This is the single most common cause of the bug.
- [ ] The key is **immutable for the entity's lifetime**. A key derived from mutable state (account
      status, tenant tier, shard name) relocates the entity mid-stream and splits its history.
- [ ] The key is **not unique per message.** If it is, you have a message id, not a partition key,
      and you have reinvented round-robin.
- [ ] The hash is **explicit and stable across processes and languages**. Do not use a language's
      built-in string hash (Python's is randomised per interpreter under PEP 456). Verify that every
      producing client library uses the same partitioner — Kafka's Java client defaults to murmur2
      while librdkafka-based clients default to CRC32, so the same key from two languages can land
      in two different partitions and silently break ordering across the pair.

## Step 3 — Estimate cardinality and skew against REAL data

Never estimate this from intuition. Run the query.

- [ ] `SELECT key, COUNT(*) FROM events WHERE ts > now() - 7 days GROUP BY key ORDER BY 2 DESC`
      against production, at **peak hour**, not daily average.
- [ ] **Cardinality** — distinct keys. This is the hard ceiling on useful partitions. Fewer distinct
      keys than partitions means guaranteed empty partitions.
- [ ] **Skew** — compute both ratios and the number that matters:

      | metric | formula | read it as |
      |---|---|---|
      | max/min | busiest ÷ quietest partition | how lopsided |
      | **max/mean** | busiest ÷ average | **the one that matters** |
      | **effective parallelism** | `N / (max/mean)` | consumers actually doing work |

      Reference point from the lesson's measured run: 500 tenants, Zipf s=1.0, 16 partitions gave
      `max/mean = 2.64` and an effective parallelism of **6.07 of 16**. Ten consumers paid for and
      unable to help, with nothing broken and lag fine.
- [ ] Assume the distribution is **Zipfian**, because it is. Identify the top 3 keys and their share
      of total traffic. Ask: what happens when the top key doubles? Sales will sign a bigger customer.
- [ ] Check whether the top key alone exceeds one consumer's throughput. If so, no partition count
      saves you and you must go to Step 5 now.

## Step 4 — Size the partition count for a number you cannot easily change

- [ ] Required consumer parallelism = `peak arrival rate x processing time` (Little's Law, Lesson 01).
- [ ] Multiply by the skew factor from Step 3: `partitions = concurrency x (max/mean)`.
- [ ] Add headroom for **3-5x growth**. An idle partition costs a file handle and a little metadata;
      a partition migration costs a maintenance window and a correctness window.
- [ ] Sanity-check the upper bound: partitions cost broker file descriptors, replication traffic, and
      rebalance time. Thousands per broker is where it starts to hurt.
- [ ] **Confirm you understand the cost of being wrong**, from the lesson's measured run:

      | change | keys that move (modulo) | keys that move (consistent hash) |
      |---|---|---|
      | 8 -> 12 | 65.8% | 34.0% |
      | 16 -> 32 (doubling) | 52.4% | 50.0% |
      | **16 -> 17** | **94.6%** | 6.0% |

      Adding one partition to sixteen relocates almost every key. Every moved key with unconsumed
      backlog exists in two partitions at once and is processed by two consumers concurrently.
- [ ] Write the repartitioning procedure into the runbook **now**, while nobody is under pressure:
      1. Over-provision up front (preferred — you are doing this at Step 4).
      2. Drain to zero lag on every partition, then change N. The only procedure with no
         correctness window.
      3. If you must grow live, **double** rather than increment, and accept the window.
- [ ] Record that partition counts **cannot be decreased**. Kafka refuses the operation.

## Step 5 — Plan the hot-key mitigation before you need it

Pick one and write down the cost. Do not leave this until the incident.

- [ ] **Composite key** (`tenant_id:account_id`). Best option when it applies: raises cardinality,
      flattens distribution, and keeps the ordering you actually needed. Verify first that nothing
      depends on cross-account ordering within a tenant.
- [ ] **Salt the hot key** (`tenant-0000#0` .. `#7` for the top N keys only). Measured effect:
      `max/mean` 2.64 -> 1.53, effective parallelism 6.07 -> 10.45 of 16. **The cost is total loss
      of ordering for those keys** — 26.7% of traffic in the measured run. Only choose this if you
      can state why those keys do not need order, or pair it with Step 6.
- [ ] **Isolate the elephant** — its own topic, partitions, and consumer deployment. Preserves
      ordering completely and stops one customer affecting everyone's lag. Costs a second pipeline,
      producer-side routing, and a policy for who gets promoted.
- [ ] Decide the **trigger**: at what `max/mean` or per-partition lag does the mitigation get applied,
      and who is allowed to apply it?

## Step 6 — Try to delete the requirement instead of paying for it

The cheapest ordering guarantee is the one you did not need. Check both techniques before shipping.

- [ ] **Version-based rejection.** Add a monotonic version per entity and have handlers skip stale
      events: `if incoming.version <= stored.version: return`. Measured, this turned 242 inversions
      into **0 corrupted rows**. Limits, both real:
      - It converges on the **final** state and silently drops intermediates. Wrong if an audit
        trail, change feed, or notification needed to observe the skipped version.
      - It is wrong for handlers that **accumulate** (`balance += amount`) rather than overwrite.
- [ ] **Commutativity.** For accumulating handlers, make order stop mattering by algebra: counters,
      sums, sets, max/min. If a fraud or alerting rule reads an intermediate value, fix the rule —
      an intermediate value in an unsettled stream is not a fact.
- [ ] For every handler, answer: *"what specifically breaks if these two events swap?"* before
      answering *"how do I order them?"*

## Step 7 — Confirm the consumer survives a rebalance

Rebalances are routine — every deploy, autoscale, pod eviction, and long GC pause. They generate
duplicates by construction, because offsets commit in batches and reassignment replays the
uncommitted window.

- [ ] **Consumers are idempotent** (Lesson 06). This is mandatory, not advisable. Measured: an eager
      rebalance produced 120 duplicates on 1,200 records (10%); the idempotent consumer performed
      exactly 1,200 side effects with zero wrong.
- [ ] **Cooperative + sticky assignment** is configured
      (`partition.assignment.strategy=CooperativeStickyAssignor` or equivalent). Measured: revoking
      only the dead consumer's partitions cut duplicates from 120 to 40, a 3x reduction, with no
      stop-the-world pause. Cooperative makes the window smaller; idempotency makes it harmless.
- [ ] **Offsets are committed after processing, not on a timer** (`enable.auto.commit=false`).
      Auto-commit acknowledges work that may not have happened.
- [ ] **The consumer does not fan a poll batch across a thread pool.** Measured: 8 naive worker
      threads gave 7.5x throughput and 49 inversions across 47 of 300 accounts. If you need
      intra-partition concurrency, route by `hash(key) % n_workers` — measured 2.9x the serial
      throughput with zero violations.
- [ ] Per-partition state that would be expensive to rebuild is either **small or reconstructible**,
      since sticky assignment is a preference, not a guarantee.

## Step 8 — Instrument it so skew is visible before a customer finds it

- [ ] Alarm on **`max(lag)` across partitions, never aggregate lag.** Fifteen partitions at zero and
      one at four million averages out to something that looks survivable.
- [ ] Chart **messages/second per partition**. A hot key is a shape on this graph long before it is
      a complaint.
- [ ] Track `max/mean` as a metric and alert when it crosses the threshold from Step 5.
- [ ] Count **ordering inversions in the consumer** — if events carry a version, the handler already
      knows when it sees a stale one. Emit a counter. Silent reordering is the failure mode of this
      entire lesson; a counter converts it into a graph.
- [ ] Alert on **idle group members** (consumers assigned zero partitions). It is a live billing
      error and a sign someone scaled the wrong dimension.

## The one-line record

Put this in the design doc so the decision survives the people who made it:

```text
topic:        <name>
key:          <field>            because ordering is required per <entity>
NOT ordered:  <what you gave up — be specific>
cardinality:  <distinct keys>    top-3 share: <%>   max/mean: <ratio>
partitions:   <N>                sized for <concurrency> x <skew> x <growth>; increasing is HAZARDOUS
hot-key plan: <composite | salt (ordering cost: ...) | isolated topic>   trigger: <metric threshold>
requirement removed by: <version rejection | commutativity | neither — we pay for order>
rebalance:    idempotent via <dedup key>; cooperative-sticky; manual commit
```
