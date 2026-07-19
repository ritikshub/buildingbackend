---
name: checklist-idempotent-consumer
description: A review checklist for making a consumer safe under at-least-once delivery, from identifying the effect through sizing the dedup TTL and deliberately replaying to prove it
phase: 6
lesson: 06
---

# Checklist — Is This Consumer Safe Under At-Least-Once Delivery?

Run this per **consumer handler**, before it ships and again whenever its effect changes.

The governing assumption, which is not negotiable and does not depend on your broker:

> **This handler will be called more than once with the same message.**
> Not "might be" under exotic failure. Will be, routinely, in normal operation.

Duplicates arrive from at least five independent sources, and fixing one does not address the
others: a client retry, a producer retry after a lost publish confirm, a broker redelivery after
a lost ack or an expired lease, a dead-letter queue redrive, and a deliberate replay from an
offset. Only idempotency **at the point where the effect happens** covers all five.

## Step 1 — Name the effect, in one sentence

- [ ] Write down what this handler *changes about the world*, starting with a verb: *"charges a
      card"*, *"decrements warehouse stock"*, *"sends a shipping email"*. If you cannot write one
      sentence, the handler is doing too much and each effect needs its own answer below.
- [ ] List **every** effect, including the ones that don't feel like effects: rows written,
      messages published to another topic, files uploaded, metrics incremented, third-party calls.
      A handler is only as idempotent as its *least* idempotent effect.
- [ ] Classify each: **internal** (a store you can transact over) or **external** (someone else's
      system). The two get completely different treatments — Steps 3 and 6.

## Step 2 — Try to make it naturally idempotent first

The best dedup store is the one you didn't need. Ask before building machinery.

- [ ] Is the write **absolute** or **relative**?

      | Shape | Idempotent? | Example |
      |---|---|---|
      | `SET status = 'shipped'` | yes | absolute, overwrites |
      | `SET qty = 40` | yes | absolute |
      | `DELETE WHERE id = 7` | yes | already-gone is the same as gone |
      | `balance = balance + 10` | **no** | relative, composes with itself |
      | `INSERT` with no unique key | **no** | creates again |
      | `list.append(x)` | **no** | relative |

- [ ] Can a relative operation be **restructured** into an absolute one? "Add 90 to the balance"
      becomes "record ledger entry `charge:order-1042` for 90, derive the balance by summing" —
      and the entry's primary key gives you idempotency for free.
- [ ] Does a **natural business key** already exist that could carry a unique constraint
      (`order_id`, `(tenant_id, invoice_no)`)? If so, jump to Step 4 and skip the dedup store
      entirely. This is the simplest correct pattern and it beats every alternative here.

## Step 3 — Choose the idempotency key, and prove it is stable

This is where most implementations quietly break. The key must be identical across every
retry, restart and redeploy that refers to the same business event.

- [ ] The key is a **deterministic function of the business event** — `charge:order-1042`, or a
      hash of `(tenant, entity_id, operation)`. Not a timestamp. Not a random value.
- [ ] **The producer does not generate a fresh id per publish attempt.** Search the producer's
      retry loop for `uuid4()`, `random`, `now()`. A key generated inside a retry loop is a
      *transmission* id, and it defeats every dedup mechanism downstream — including a perfectly
      correct transactional consumer.
- [ ] If a UUID (RFC 4122) is the key, it is generated **once** when the business event occurs and
      **persisted with the event**, so retries read it back rather than minting a new one. A
      transactional outbox does this for you.
- [ ] The key survives a **producer process restart**. Broker-side `(producer_id, sequence)` dedup
      (Kafka `enable.idempotence`) does not: the producer id is per session, so a retry straddling
      a restart is indistinguishable from new work. Enable it anyway — just don't rely on it.
- [ ] The key is **scoped** correctly: per tenant if ids are only unique per tenant, and versioned
      if the same business event can legitimately recur (a monthly subscription charge needs the
      period in the key).
- [ ] The key is **carried in the message envelope**, not derived from the payload's serialization
      — a re-serialized body with reordered JSON keys must still produce the same key.

## Step 4 — Make the dedup record and the effect atomic

- [ ] **There is no `if seen: return` followed by the effect as separate statements.** Check-then-act
      is a race, not a safeguard: two instances both pass the check before either records, and both
      apply the effect. A distributed lock does not fix it — the lock has its own lease and its own
      expiry, so you now have two leases that can disagree.
- [ ] The dedup record and the effect are in **one transaction**, or the unique constraint *is* the
      dedup check:

      ```sql
      -- best: no dedup table at all
      INSERT INTO payments (order_id, amount) VALUES (1042, 9000)
      ON CONFLICT (order_id) DO NOTHING;        -- 0 rows => already done, just ack

      -- when there is no natural key
      BEGIN;
        INSERT INTO processed_messages (message_id) VALUES ('charge:order-1042');
        UPDATE accounts SET balance = balance - 9000 WHERE id = 42;
      COMMIT;                                    -- unique violation => rollback, no money moves
      ```

- [ ] Where a full transaction isn't available, a **conditional write** does the same job atomically:
      `UPDATE ... WHERE version = 7` (compare-and-set), DynamoDB `ConditionExpression`, HTTP
      `If-Match` with an `ETag`. Branch on the affected-row count.
- [ ] For work that can arrive **stale** as well as duplicated, use a **fencing token**:
      `WHERE last_seq < :seq`. This rejects a delayed redelivery of an *older* message that would
      otherwise overwrite newer state — a distinct and nastier bug than a plain duplicate.
- [ ] The dedup table is **written before or with** the effect, never after it.

## Step 5 — Size the dedup TTL against the worst case, not the typical one

A TTL converts your guarantee into a conditional one. Write the condition down.

- [ ] Enumerate your redelivery sources and take the **maximum**, not the median:

      | Source | Realistic delay |
      |---|---|
      | Lost ack / lease expiry | seconds |
      | Consumer crash and restart | seconds to a minute |
      | Rebalance during a deploy | seconds to minutes |
      | Retry with exponential backoff | minutes to hours |
      | **Manual DLQ redrive by on-call** | **hours to days** |
      | Deliberate replay from an offset | unbounded |

- [ ] `TTL > max redelivery delay`, with margin. A 15-minute window against a 6-hour redrive
      expires every record and reprocesses everything.
- [ ] Write the guarantee in the design doc as a **complete sentence**: *"Idempotent for
      redeliveries within 24 hours, which exceeds our DLQ redrive SLA of 8 hours."* Not
      *"the consumer is idempotent."*
- [ ] The dedup store is **shared by every consumer instance**. A per-process in-memory set
      deduplicates nothing, because redelivery is precisely the case where a *different* instance
      picks it up.
- [ ] You have decided what happens when the **dedup store is unreachable**: process anyway and
      risk duplicates, or stop and build backlog? Both are defensible. Not having decided is not.
- [ ] Capacity, expiry lag and backups are budgeted — this is a stateful dependency on the hot path
      of every message.
- [ ] A **duplicates-suppressed** counter is exported. A sudden rise is the earliest signal you get
      that acks are being lost or a consumer is timing out.

## Step 6 — Handle the effects you cannot deduplicate

Emails, SMS, third-party calls, printed letters, publishes to another broker.

- [ ] **Push idempotency to the boundary wherever the API allows it.** Send a stable,
      business-derived key: Stripe-style `Idempotency-Key`, SQS FIFO `MessageDeduplicationId`.
      This is the highest-value line of code in any integration.
- [ ] If the API offers no key, **ask** — for payment providers this is a procurement question, not
      an engineering constraint.
- [ ] Where it genuinely cannot be deduplicated: record the fact of having done it in the same
      transaction as everything else, order the steps so the *cheaper* failure is the one you get,
      and **write down the expected duplicate rate** ("~1 duplicate welcome email per 100k
      signups"). A measured, bounded rate is an engineering result; an unknown one is an incident
      waiting for a trigger.
- [ ] Choose the failure mode **by the cost of the effect**. It is entirely reasonable to run
      at-most-once for a notification and full transactional idempotency for a charge, in the same
      service, in the same handler.

## Step 7 — Confirm the chain, not just this hop

- [ ] Trace the message from its true origin — mobile client, browser, upstream service — and mark
      the semantics of **every** hop. The end-to-end guarantee is the weakest link: at-least-once
      anywhere makes the chain at-least-once; at-most-once anywhere makes the chain lossy.
- [ ] Confirm no upstream hop retries with a **regenerated** id. A client retry two hops up
      produces a duplicate your broker's producer dedup never sees.
- [ ] If this handler publishes downstream, its output messages carry **stable ids** too — otherwise
      you have solved your problem and created one for the next consumer.

## Step 8 — Prove it by deliberately replaying

An idempotent consumer that has never been replayed is a hypothesis.

- [ ] **Integration test:** feed the same message twice, back to back. Assert the final state is
      identical to feeding it once — not merely that no exception was raised.
- [ ] **Concurrency test:** feed the same message to two instances *simultaneously*. This is the
      test that catches check-then-act, and the sequential test does not.
- [ ] **Window test:** feed it twice with the dedup TTL expired in between. Assert you get the
      behaviour you documented in Step 5 — this test's job is to make the boundary visible, not
      necessarily to pass.
- [ ] **Staging replay:** rewind an offset or redrive a real DLQ batch in staging and diff the
      resulting state. Do this before production does it for you.
- [ ] **Game day:** kill a consumer mid-work so a lease expires with the effect already applied.
      This is the exact interleaving from The Problem, and it is easy to reproduce on purpose.

## The one-line record

For each handler, put this in the design doc so the decision survives its authors:

```text
<handler>  effect: <what changes in the world>  |  external effects: <list, or none>
  idempotency:  natural | key+dedup | conditional write | fencing token
  key:          <expression>            stable across producer retries: yes/no + why
  atomicity:    <the single transaction, or the unique constraint that enforces it>
  window:       idempotent for redeliveries within <T>, vs max redelivery delay <D>
  undedupable:  <effect> -> <boundary key used, or accepted duplicate rate>
  proven by:    <the replay test that would fail if this regressed>
```
