# Capstone: An Event-Driven Order Pipeline, End to End

> Twelve lessons, twelve failures, twelve fixes — each demonstrated alone, on a clean bench, with one thing broken at a time. Production does not work that way. Production hands you a rebalance *during* a retry storm, a poison message *while* a relay is dead, and a lag graph that looks identical whether the problem is upstream or downstream. This lesson builds the whole pipeline and breaks nine things at once, then proves four invariants still hold — and then removes the idempotency and runs the identical faults again, so you can see exactly what those mechanisms were holding up.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Schema Evolution & Event Contracts](../12-schema-evolution-and-event-contracts/)
**Time:** ~90 minutes

## The Problem

You have solved every problem in this phase. You have an envelope with a `message_id`, a broker that acks after processing, a partition key, an idempotent consumer, a dead-letter queue, a lag dashboard, and a transactional outbox. Each one was demonstrated in isolation, against a single injected fault, with everything else healthy.

**That is not the system you will operate.** The system you will operate presents its failures *simultaneously and interacting*, and the interactions are where things actually break — because a mechanism that is correct alone can be actively harmful in combination with another correct mechanism.

Four examples, all of which happen in the program below:

- **A rebalance manufactures duplicates exactly when the pipeline is least able to absorb them.** [Backpressure, Consumer Lag & Flow Control](../09-backpressure-lag-and-flow-control/) says: lag is growing, add consumers. [Ordering, Partition Keys & Parallel Consumers](../07-ordering-partition-keys-and-parallel-consumers/) says: adding a consumer triggers a rebalance, and a rebalance replays every partition's uncommitted window. So the correct response to lag *is* a duplicate generator, fired at the precise moment the consumer is already behind and the downstream is already slow. The two lessons are individually right and jointly a trap.
- **Parking a poison message to a retry path breaks the ordering you bought a partition key for.** [Retries, Backoff & Dead-Letter Queues](../08-retries-backoff-and-dead-letter-queues/) says: get the failing message out of the main stream so it stops blocking the partition. Lesson 07 says: everything for one key must be processed in sequence, in one partition. Move a message to a retry topic and it will be reprocessed *after* messages that came behind it. You have traded invariant 4 for invariant 3 without anyone writing that down.
- **Scaling to cut lag hits a ceiling nobody put on the dashboard.** Lag rises, the autoscaler adds consumers, lag keeps rising — because consumer parallelism is capped at the partition count, and the partition count is one of the few numbers in this phase you cannot safely change while running.
- **A dead relay and a dead consumer look identical on a lag graph and demand opposite responses.** [The Dual-Write Problem: Transactional Outbox & CDC](../10-dual-write-outbox-and-cdc/) put a relay between your database and your broker. When it dies, consumer lag goes *down* — there is nothing to consume — and outbox lag climbs. Page on the wrong one and you will scale consumers during an upstream outage, which does nothing at all.

So the capstone's job is not to recap. It is to run all of them at once and demonstrate that the pipeline still holds its promises. Which requires stating the promises precisely, because "it works" is not a thing you can test.

**The four invariants.** Everything in this lesson exists to defend these, and everything you build in production should be traceable to a list like it:

1. **No order is lost.** Every order that commits to the database eventually produces its downstream effects — payment, email, analytics — no matter what dies in between.
2. **No customer is charged twice.** Despite at-least-once delivery, relay redeliveries, lease expiries, rebalances and manual replays.
3. **No poison message halts the pipeline.** Bad data is quarantined with enough context to fix it, and the partition it landed in keeps moving.
4. **Per-customer ordering is preserved.** A customer's events apply in the order they happened, even though six other customers are being processed concurrently.

Notice what these have in common: **each one is a property of the whole chain, not of any component.** No single service can guarantee any of them. That is what makes assembly a distinct skill from construction.

## The Concept

### The pipeline, walked once, as a data flow

Here is the whole system, with the measured numbers from the run at the end of this lesson written on it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="The end-to-end order pipeline. An order service writes the order row and the outbox row in one SQLite transaction; a relay publishes 850 records into an 8-partition log keyed by customer id; three independent consumer groups - payments, email and analytics - read the same records at their own offsets, producing 600 charges, 600 emails and 600 analytics rows; a dedup store of 600 message ids absorbs 31 duplicate deliveries and each group has its own dead-letter queue holding the same 4 poison events.">
  <defs>
    <marker id="l13-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One order, all the way through — measured on 600 orders and 9 injected faults</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="76" width="176" height="128" rx="12" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-dasharray="7 5"/>
    <rect x="34" y="112" width="144" height="34" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="34" y="154" width="144" height="34" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="222" y="98" width="122" height="84" rx="11" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="372" y="70" width="150" height="140" rx="11" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="#7c5cff" stroke-width="1.4">
    <rect x="386" y="98" width="122" height="12" rx="3" fill="#7c5cff" fill-opacity="0.22"/>
    <rect x="386" y="114" width="122" height="12" rx="3" fill="#7c5cff" fill-opacity="0.22"/>
    <rect x="386" y="130" width="122" height="12" rx="3" fill="#7c5cff" fill-opacity="0.22"/>
    <rect x="386" y="146" width="122" height="12" rx="3" fill="#7c5cff" fill-opacity="0.22"/>
    <rect x="386" y="162" width="122" height="12" rx="3" fill="#7c5cff" fill-opacity="0.22"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="562" y="60" width="212" height="58" rx="10" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="562" y="128" width="212" height="58" rx="10" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="562" y="196" width="212" height="58" rx="10" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M194 150 L 216 143" marker-end="url(#l13-arrow)"/>
    <path d="M344 140 L 366 140" marker-end="url(#l13-arrow)"/>
    <path d="M522 140 L 546 90 L 556 90" marker-end="url(#l13-arrow)"/>
    <path d="M522 140 L 546 157 L 556 157" marker-end="url(#l13-arrow)"/>
    <path d="M522 140 L 546 225 L 556 225" marker-end="url(#l13-arrow)"/>
    <path d="M283 182 L 283 214 L 447 214 L 447 206" stroke-dasharray="5 4" stroke-opacity="0.7" marker-end="url(#l13-arrow)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="290" width="404" height="112" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="452" y="290" width="404" height="112" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="18" y="422" width="838" height="118" rx="12" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="106" y="100" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">ONE TRANSACTION</text>
    <text x="106" y="133" font-size="9.5" font-weight="700" text-anchor="middle">INSERT orders</text>
    <text x="106" y="175" font-size="9.5" font-weight="700" text-anchor="middle">INSERT outbox</text>
    <text x="106" y="197" font-size="8.5" text-anchor="middle" opacity="0.85">600 orders · 847 rows</text>

    <text x="283" y="120" font-size="10.5" font-weight="700" text-anchor="middle">RELAY</text>
    <text x="283" y="138" font-size="8.5" text-anchor="middle" opacity="0.9">poll 250 ms · batch 16</text>
    <text x="283" y="152" font-size="8.5" text-anchor="middle" opacity="0.9">publish, THEN mark</text>
    <text x="283" y="170" font-size="8.5" text-anchor="middle" font-weight="700" fill="#e0930f">209 polls · 1 crash</text>
    <text x="283" y="236" font-size="8.5" text-anchor="middle" opacity="0.85">crash before mark = re-publish</text>
    <text x="283" y="250" font-size="8.5" text-anchor="middle" font-weight="700" fill="#e0930f">3 duplicate publishes</text>

    <text x="447" y="60" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">PARTITIONED LOG</text>
    <text x="447" y="190" font-size="8.5" text-anchor="middle" opacity="0.9">8 partitions · key = customer_id</text>
    <text x="447" y="204" font-size="8.5" text-anchor="middle" font-weight="700">850 records, never deleted</text>

    <text x="580" y="80" font-size="10.5" font-weight="700" fill="#0fa07f">payments — the money-critical one</text>
    <text x="580" y="96" font-size="8.5" opacity="0.9">dedup record + charge in ONE txn · 2 -&gt; 8 members</text>
    <text x="580" y="110" font-size="8.5" font-weight="700">600 charges · 31 duplicates absorbed · 0.00 error</text>
    <text x="580" y="148" font-size="10.5" font-weight="700" fill="#e0930f">email — the effect you cannot undo</text>
    <text x="580" y="164" font-size="8.5" opacity="0.9">provider Idempotency-Key, 30 s TTL · retry lane</text>
    <text x="580" y="178" font-size="8.5" font-weight="700">600 sent · 116 key-suppressed · 198 retries</text>
    <text x="580" y="216" font-size="10.5" font-weight="700" fill="#3553ff">analytics — fast and tolerant</text>
    <text x="580" y="232" font-size="8.5" opacity="0.9">reads v1 and v2 through upcasters · sheds under lag</text>
    <text x="580" y="246" font-size="8.5" font-weight="700">600 counted · 400 upcast hops · 74 shed</text>

    <text x="36" y="314" font-size="11" font-weight="700" fill="#0fa07f">THE DEDUP STORE — 600 message ids</text>
    <text x="36" y="336" font-size="9" opacity="0.92">INSERT processed(message_id) + INSERT charges, one commit</text>
    <text x="36" y="353" font-size="9" opacity="0.92">a unique-constraint violation IS the duplicate check</text>
    <text x="36" y="374" font-size="9.5" font-weight="700">31 duplicate deliveries rejected: 3 from the relay,</text>
    <text x="36" y="390" font-size="9.5" font-weight="700">the rest from a consumer crash and a rebalance</text>

    <text x="470" y="314" font-size="11" font-weight="700" fill="#e0930f">THE DEAD-LETTER QUEUES — one per group</text>
    <text x="470" y="336" font-size="9" opacity="0.92">4 malformed events from a bad producer deploy,</text>
    <text x="470" y="353" font-size="9" opacity="0.92">classified PERMANENT on delivery 1 and parked</text>
    <text x="470" y="374" font-size="9.5" font-weight="700">12 entries · 0 redeliveries wasted on them</text>
    <text x="470" y="390" font-size="9.5" font-weight="700">their partition ran at 2.00 rec/s; peers at 2.02</text>

    <text x="36" y="446" font-size="11" font-weight="700" fill="#3553ff">WHAT MAKES IT ONE SYSTEM RATHER THAN THREE</text>
    <text x="36" y="468" font-size="9.5" opacity="0.95">The message_id is generated ONCE, in the outbox row, inside the business transaction. Every retry, every re-publish and</text>
    <text x="36" y="485" font-size="9.5" opacity="0.95">every replay carries the same id — so the dedup store, the DLQ, the trace and the email provider's key all agree on identity.</text>
    <text x="36" y="506" font-size="9.5" opacity="0.95">The partition key is the customer id, so every mechanism downstream inherits per-customer ordering without asking for it.</text>
    <text x="36" y="527" font-size="9.5" font-weight="700" fill="#3553ff">Two fields in the envelope carry the whole architecture. Get either wrong and no downstream mechanism can recover.</text>
  </g>
</svg>
```

Trace one order through it:

1. **The write.** The API handler opens a transaction, inserts the `orders` row and an `outbox` row holding the fully-formed envelope, and commits. One write, one system — so there is no interleaving in which the order exists and the event does not ([Lesson 10](../10-dual-write-outbox-and-cdc/)). The envelope's `message_id` is generated *here*, once, and persisted; that is what makes every later deduplication possible ([Lesson 02](../02-anatomy-of-a-message/), [Lesson 06](../06-delivery-semantics-and-idempotency/)).
2. **The relay.** A separate process polls for `published_at IS NULL`, publishes each row to the log, and *then* marks it published. That second write is itself a dual write — but an asymmetric one: it can only fail toward re-publishing, never toward losing.
3. **The log.** 8 partitions; `partition = blake2b(customer_id) % 8`. Records are appended with offsets and never deleted on acknowledgement ([Lesson 05](../05-the-log-offsets-and-replay/)), which is what makes replay, backfill and a fourth consumer group possible later.
4. **Three consumer groups**, each with its own committed offsets over the same physical records — fan-out at one copy of the data ([Lesson 04](../04-pub-sub-topics-and-fan-out/)). Within a group, each partition is owned by exactly one member, which is what preserves per-customer order ([Lesson 07](../07-ordering-partition-keys-and-parallel-consumers/)).
5. **The effects**, each with a different idempotency story, which is the honest part: payments transacts its dedup record with its charge; analytics keeps a shared set of seen ids; email pushes the key to an external provider and inherits that provider's TTL.

### Where each guarantee comes from

This table is the lesson's spine. Every row is a mechanism you built, the invariant it defends, and the measured consequence of removing it. If you take one artifact from this phase into a design review, take this.

| Invariant | The mechanism that provides it | Built in | What happens without it |
|---|---|---|---|
| 1. No order lost | Order row **and** outbox row in one DB transaction | L10 | Commit-then-publish orphaned **45 of 400** orders with zero errors |
| 1. No order lost | Relay publishes, *then* marks published | L10 | Mark-then-publish converts a duplicate into a permanent loss |
| 1. No order lost | Ack / commit offsets **after** processing | L03, L05 | Commit-first silently drops the whole uncommitted window on a crash |
| 1. No order lost | Retention decoupled from acknowledgement | L05 | A queue has nothing left to replay when you find the bug at 15:00 |
| 2. No double charge | Dedup record **and** effect in one commit | L06 | Check-then-act let two instances both pass the check: **180 vs 90** |
| 2. No double charge | `message_id` created once, in the outbox row | L02, L06, L10 | A per-attempt id is a transmission id and deduplicates nothing |
| 2. No double charge | Idempotency key at the external boundary | L06 | **151 duplicate emails** in the counterfactual below |
| 3. No halt | Classify permanent vs transient before retrying | L08 | **316 wasted attempts, 28.4% of all work**, and nothing succeeds |
| 3. No halt | Dead-letter on max delivery count | L08 | Retry-in-place collapsed throughput **50 → 0.04 msg/s, 1,250×** |
| 3. No halt | Tolerant reader + upcaster chain | L12 | A v4-only consumer processed **0 of 9,000** records on replay |
| 4. Ordering | Partition key = the aggregate id | L07 | Round-robin: **242 inversions, 178 of 300 accounts damaged** |
| 4. Ordering | One consumer per partition per group | L07 | Two consumers on one key during a repartition: rows resurrected |
| 4. Ordering | Idempotency absorbs replayed older events | L06 + L07 | **7 inversions across 5 customers** in the counterfactual below |
| All four | Lag in **seconds**, autoscale capped at partition count | L09 | Retention silently deleted **33,680** payment confirmations |

Read the last column as a list of incidents. Every one of those numbers is a measurement from an earlier lesson in this phase, produced by removing exactly one mechanism.

### The interactions — where two correct mechanisms combine badly

This is the genuinely new content, and it is the reason the capstone exists.

**1. The lag response is a duplicate generator.** Payments falls behind because its card gateway slows down. Time lag crosses the threshold, the autoscaler adds members, and adding members is a rebalance — which revokes partitions and replays every uncommitted window. In the measured run the autoscale at `t=41.00` replayed 4 records while payments was already 10.10 s behind; the member crash at `t=25.00` replayed 30. **The mitigation for lag produced work that increased lag**, and the only reason it was harmless is that a dedup store absorbed 31 duplicate deliveries. Without idempotency, the correct operational response to a slow downstream would have double-charged customers. The order matters: *make the consumer idempotent before you turn on the autoscaler*, not after.

**2. Parking a message trades invariant 4 for invariant 3.** The email consumer's failures go to a retry lane with capped exponential backoff and full jitter. That keeps the partition moving — invariant 3 — and it means a retried message is processed after messages that were behind it in the partition. For an email that is fine, because emails have no per-customer ordering requirement. For payments it would not be: a retried `order.placed` applied after a later event for the same customer is precisely an inversion. So the pipeline uses *two different failure strategies in the same system*: short in-process handling for the ordered stream, a retry lane for the unordered one. "Use a retry topic" is not a general rule; it is a rule for streams whose ordering you have explicitly declared unnecessary.

**3. The partition count is the real ceiling, and it caps two things.** The autoscaler took payments from 2 members to 8 and stopped — 8 is the partition count, and a ninth member would idle. Analytics hit the same wall and had no scaling left, so it shed: 74 `order.enriched` records dropped to protect the `order.placed` stream that the invariants depend on. This is the whole ladder from [Lesson 09](../09-backpressure-lag-and-flow-control/) in miniature — scale out, then speed up, then shed — and the first rung is shorter than people expect because it was fixed at design time by a number nobody revisits.

**4. Two outages, one lag graph, opposite responses.** At `t=50.00` the relay process dies. Consumer lag does not merely fall — it reads **exactly 0.00 on all three groups, and stays there for eight seconds**, because there is nothing left to consume. Payments had been 13.70 s behind one second earlier. Meanwhile outbox lag climbs at exactly one second per second to **8.20 s**. When the relay returns, all three groups spike to *identical* values — 16 records and 8.20 s at `t=58`, 80 records and 9.20 s at `t=59` — because they are all reading the same freshly-landed backlog.

Two diagnostics fall out, and both are worth wiring into alerts. **Independent consumer groups spiking together is an upstream signature; one group spiking alone is a consumer signature** — three groups that share no code, no downstream and no offsets can only move in lockstep through their one common input. And **a lag of zero means either "healthy" or "starved", which are opposite situations**; the discriminator is throughput. Zero lag with zero throughput is an outage upstream of you, and scaling consumers in response adds capacity to drain an empty log.

**5. The poison message's blast radius is a function of your partition key.** All four malformed events came from one bad deploy and shared a customer id, so all four landed in partition 7. Good key design concentrated the damage — and that is a double-edged result. If those messages had blocked the partition, every customer hashing to partition 7 would have stalled with them, not just the customer who triggered the bug. The measurement is the reassurance: partition 7 ran at **2.00 rec/s** during the poison window against a peer mean of **2.02 rec/s**. It was not slowed at all, because a permanent failure is classified on delivery 1 and parked rather than retried.

**6. The schema change is only safe because the upcaster is permanent.** The producer switches to `schema_version: 2` mid-run; consumers read **400 v1 records and 200 v2 records** through a single `v1 → v2` upcaster and never branch on version. But those 400 v1 records are still in the log. Any future replay — a DLQ redrive, a backfill for a fourth consumer group, a reprocess after a bug — meets them again. The upcaster is not migration scaffolding; it is production code with the same lifetime as your retention policy ([Lesson 12](../12-schema-evolution-and-event-contracts/)).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Four measured interactions between mechanisms. Scaling consumers to cut lag triggers a rebalance that replays uncommitted work, producing duplicates during the very window the pipeline is already degraded. Parking a failing message preserves throughput and destroys per-key ordering. Autoscaling stops at the partition count, after which the only lever is shedding. A relay outage makes consumer lag fall while outbox lag climbs one second per second, so the two failures require opposite responses.">
  <defs>
    <marker id="l13-arrow2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four places where the sum is not the parts</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="416" height="206" rx="13" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="448" y="44" width="416" height="206" rx="13" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    <rect x="16" y="264" width="416" height="206" rx="13" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff"/>
    <rect x="448" y="264" width="416" height="206" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="40" y="104" width="112" height="34" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="182" y="104" width="112" height="34" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="324" y="104" width="84" height="34" rx="7" fill="#e0930f" fill-opacity="0.26" stroke="#e0930f"/>
    <rect x="472" y="104" width="130" height="34" rx="7" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="632" y="104" width="208" height="34" rx="7" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M152 121 L 176 121" marker-end="url(#l13-arrow2)"/>
    <path d="M294 121 L 318 121" marker-end="url(#l13-arrow2)"/>
    <path d="M602 121 L 626 121" marker-end="url(#l13-arrow2)"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.5">
    <path d="M44 400 L 410 400"/>
    <path d="M476 400 L 842 400"/>
  </g>
  <path d="M44 396 L 110 392 L 176 382 L 240 356 L 300 330 L 340 320 L 380 350 L 410 386" fill="none" stroke="#3553ff" stroke-width="2.6"/>
  <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.6">
    <path d="M340 320 L 340 400"/>
  </g>
  <path d="M476 392 L 560 392 L 620 396 L 700 398 L 760 396 L 842 392" fill="none" stroke="#0fa07f" stroke-width="2.6"/>
  <path d="M560 396 L 620 372 L 700 344 L 760 322 L 800 336 L 842 388" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-dasharray="7 4"/>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="72" font-size="11.5" font-weight="700" fill="#e0930f">1 · THE FIX FOR LAG MAKES DUPLICATES</text>
    <text x="36" y="90" font-size="9" opacity="0.85">lesson 09 says add consumers. lesson 07 says that is a rebalance.</text>
    <text x="96" y="125" font-size="9" text-anchor="middle">time lag 10.10 s</text>
    <text x="238" y="125" font-size="9" text-anchor="middle">scale 2 -&gt; 8 members</text>
    <text x="366" y="120" font-size="9" text-anchor="middle" font-weight="700">REBALANCE</text>
    <text x="366" y="133" font-size="8" text-anchor="middle">replays</text>
    <text x="36" y="168" font-size="9.5" opacity="0.95">measured: 30 records rewound by the crash at t=25, 4 more by the</text>
    <text x="36" y="184" font-size="9.5" opacity="0.95">autoscale at t=41 — all inside the degraded window.</text>
    <text x="36" y="208" font-size="10" font-weight="700" fill="#e0930f">31 duplicate deliveries, absorbed by the dedup store.</text>
    <text x="36" y="228" font-size="9.5" opacity="0.9">Make the consumer idempotent BEFORE you enable the autoscaler.</text>

    <text x="468" y="72" font-size="11.5" font-weight="700" fill="#7c5cff">2 · PARKING TRADES ORDERING FOR THROUGHPUT</text>
    <text x="468" y="90" font-size="9" opacity="0.85">a retry lane un-blocks the partition and un-orders the key</text>
    <text x="537" y="125" font-size="9" text-anchor="middle">msg 7 fails</text>
    <text x="736" y="120" font-size="9" text-anchor="middle">parked, retried after 8, 9, 10</text>
    <text x="736" y="133" font-size="8" text-anchor="middle">198 retries, backoff + full jitter</text>
    <text x="468" y="168" font-size="9.5" opacity="0.95">Correct for email: no per-customer invariant. Fatal for payments:</text>
    <text x="468" y="184" font-size="9.5" opacity="0.95">a replayed older event applied late IS an inversion.</text>
    <text x="468" y="208" font-size="10" font-weight="700" fill="#7c5cff">Two streams, two failure strategies, in the same service.</text>
    <text x="468" y="228" font-size="9.5" opacity="0.9">"Use a retry topic" is a rule about a stream, not about a system.</text>

    <text x="36" y="292" font-size="11.5" font-weight="700" fill="#3553ff">3 · SCALING STOPS AT THE PARTITION COUNT</text>
    <text x="36" y="310" font-size="9" opacity="0.85">payments time lag, 1 s samples, peak 13.70 s at t=49</text>
    <text x="344" y="312" font-size="8.5" text-anchor="middle" font-weight="700" fill="#3553ff">8 members</text>
    <text x="344" y="325" font-size="8" text-anchor="middle" opacity="0.8">ceiling</text>
    <text x="36" y="424" font-size="9.5" opacity="0.95">2 -&gt; 8 members and no further: a 9th consumer would idle.</text>
    <text x="36" y="440" font-size="9.5" opacity="0.95">Analytics had no scaling left and shed 74 order.enriched records.</text>
    <text x="36" y="460" font-size="10" font-weight="700" fill="#3553ff">Scale out · speed up · shed. The first rung is fixed at design time.</text>

    <text x="468" y="292" font-size="11.5" font-weight="700" fill="#0fa07f">4 · SAME GRAPH, OPPOSITE RESPONSES</text>
    <text x="468" y="310" font-size="9" opacity="0.85">the relay dies at t=50 and returns at t=58</text>
    <text x="790" y="360" font-size="8.5" text-anchor="end" fill="#e0930f" font-weight="700">outbox lag: +1 s per second, to 8.20 s</text>
    <text x="700" y="414" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">consumer lag: exactly 0.00 on all 3 groups, for 8 s</text>
    <text x="468" y="428" font-size="9.5" opacity="0.95">Then all three spike to IDENTICAL values at t=59: 80 records, 9.20 s.</text>
    <text x="468" y="444" font-size="9.5" opacity="0.95">Independent groups moving in unison is an UPSTREAM signature — and a</text>
    <text x="468" y="460" font-size="9.5" opacity="0.95">lag of zero means healthy OR starved. The discriminator is throughput.</text>
  </g>
</svg>
```

### The end-to-end guarantee is the weakest link

[Lesson 06](../06-delivery-semantics-and-idempotency/) established this for delivery semantics; the capstone generalises it. **Every property in the invariant list is a property of a chain, and a chain's guarantee is its weakest hop.** One consumer that is not idempotent, one place that still does a dual write, one dedup TTL shorter than your worst redelivery delay, and the invariant is void — regardless of how carefully every other hop was built.

That makes "audit the pipeline for its weakest link" a concrete, repeatable procedure, and it is short enough to do in a design review:

1. **Enumerate every hop.** Client → API → database → outbox → relay → log → consumer → effect. Every arrow is a separate delivery problem.
2. **Name each hop's delivery semantic out loud.** At-least-once, at-most-once, or "nobody has decided". The third answer is the one that finds bugs.
3. **For every effect, name its idempotency mechanism *and its scope*.** "The dedup table" is not an answer; "a unique constraint on `processed(message_id)`, retained 30 days, in the same database as the effect" is. The scope is where the guarantee ends.
4. **Find the dual writes.** Look for two clients and two `await`s in one function with no shared transaction. There is one in this pipeline on purpose — the relay's publish-then-mark — and it is acceptable *only* because its failure direction is redelivery.
5. **Find the shortest TTL on the path.** Dedup window, provider idempotency key, log retention, DLQ residence. Compare each against the longest realistic delay: a DLQ redrive by an on-call engineer is hours to days.

Run that on the pipeline in this lesson and it has exactly one bounded hop, which the program measures rather than hides: the email provider honours its idempotency key for **30 s**, and the widest gap between a first attempt and its retry in the run was **26.00 s** — **4.00 s of margin**. Raise the backoff cap above the TTL, or redrive the DLQ an hour later, and duplicate emails start being delivered. That is not a flaw in the design; it is the design's honest edge, and the value of the audit is that you can state it in one sentence before an incident rather than after.

### What you would still add in a real system

The pipeline defends four invariants under nine faults. It is not production-complete, and the gap list is part of the lesson:

- **Exactly-once sinks.** Where the effect and the offset can live in one store — a Postgres sink, a Kafka-transactional stream job — take it. It removes the dedup TTL from your risk surface entirely.
- **Schema-registry enforcement in CI.** The upcaster chain here is a convention. In production it is a `FULL_TRANSITIVE` compatibility check as a required status on the producer's pull request, so an incompatible schema never reaches the log ([Lesson 12](../12-schema-evolution-and-event-contracts/)).
- **Tracing across every hop.** The envelope carries `traceparent`; nothing here consumes it. Real value requires a span per hop, linked across the async boundary, so "why did this customer not get their email?" is a query rather than an investigation ([Phase 9](../../09-logging-monitoring-and-observability/)).
- **Per-tenant quotas and isolation.** One customer generating 40% of traffic makes one partition hot and every consumer of that partition slow. Composite keys, salting, or a dedicated pipeline for the elephant.
- **Chaos testing as a scheduled job.** The fault schedule in this program is a test suite. Running it against staging weekly — kill the relay, expire a lease, inject a malformed event — is the only way to know the invariants still hold after six months of changes.
- **Disaster-recovery and replay drills.** Practise the replay before you need it: reset a consumer group to an old offset, confirm the upcasters still work, confirm the dedup store is sized for the burst, confirm nobody gets 40,000 emails.
- **A PII deletion strategy chosen before the first record.** An append-only log is close to the worst structure for an erasure request. Crypto-shredding is the technique that scales, and it is a design-time decision you cannot retrofit ([Lesson 05](../05-the-log-offsets-and-replay/)).

## Build It

[`code/order_pipeline.py`](code/order_pipeline.py) builds the whole thing on the standard library: a real `sqlite3` transactional outbox, a relay, an 8-partition log, three consumer groups with committed offsets and rebalances, retry lanes, dead-letter queues, lag sampling, a lag-driven control loop and an upcaster chain. Seeded, virtual clock, temp files cleaned up; two runs print byte-identical output.

The write path is the shape everything else depends on:

```python
self.conn.execute("BEGIN IMMEDIATE")
self.conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,1)", (oid, cid, seq, amount, now))
for e in evs:
    self.conn.execute(
        "INSERT INTO outbox (event_id, event_type, partition_key, envelope, "
        "created_at, published_at) VALUES (?,?,?,?,?,NULL)",
        (e["message_id"], e["type"], e["partition_key"], json.dumps(e), now))
self.conn.execute("COMMIT")     # ONE write. Both land, or neither does.
```

The relay's crash is injected at exactly the instruction that matters — after the publish loop, before the `UPDATE` — because that is the only window the pattern still has:

```python
for _id, blob in rows:
    ...
    self.log.append(env, now + 0.002)
if self.crash_armed and now >= T_RELAY_CRASH:
    self.crash_armed = False
    return                       # the UPDATE never runs: these rows re-publish
self.conn.execute("BEGIN IMMEDIATE")
self.conn.executemany("UPDATE outbox SET published_at=? WHERE id=?", ...)
```

The payments consumer is the invariant-2 machine, and the entire mechanism is that the dedup insert and the charge share one commit — there is no check, so there is no window between the check and the act:

```python
if ctx.idempotent:
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO processed VALUES (?,?)", (env["message_id"], now))
        conn.execute("INSERT INTO charges (order_id, amount, at) VALUES (?,?,?)",
                     (body["order_id"], body["total_amount"], now))
        conn.execute("COMMIT")
    except sqlite3.IntegrityError:
        conn.execute("ROLLBACK")
        g.duplicates_absorbed += 1
        return "ok"
```

A rebalance is four lines, and those four lines are where every duplicate in the run comes from — the uncommitted window is rewound and reprocessed:

```python
for p in range(N_PARTITIONS):
    lost += self.processed[p] - self.committed[p]
    self.processed[p] = self.committed[p]
    self.since_commit[p] = 0
self._reassign()
```

The email path is deliberately the honest one. It has no local dedup store, because an email is not a row it can transact with; it pushes the key to the provider and inherits the provider's window:

```python
key = env["message_id"] if ctx.idempotent else f"{env['message_id']}:{attempt}:{now:.3f}"
outcome = ctx.provider.send(key, body["order_id"], now)
if outcome == "lost_response":
    g.effects += 1              # the email WAS sent; the reply died on the way back
    return "retry"
```

And the lag-driven control loop is deliberately dull, because a dull controller is a correct one — threshold on **time** lag, a cooldown, and a hard cap at the partition count:

```python
if pt > PAY_LAG_SCALE_AT and len(gp.members) < N_PARTITIONS \
        and now - gp.last_scale > PAY_SCALE_COOLDOWN:
    gp.last_scale = now
    gp.scale_to(min(N_PARTITIONS, len(gp.members) * 4), now, timeline)
```

Run it:

```console
$ python order_pipeline.py
== 1. THE PIPELINE: every primitive of the phase, wired together ==
  order service -> sqlite (orders + outbox, ONE transaction)     lesson 10
  relay         -> claims unpublished rows, publishes, marks     lesson 10
  log           -> 8 partitions, key = customer_id, consumer-owned offsets    lessons 05, 07
  consumer groups -> payments (idempotent) · email (external effect) · analytics
                     independent offsets over one copy of the data    lesson 04
  orders placed                  600   valid business orders
  poison events injected           4   from a bad producer deploy
  outbox rows written            847   order.placed + order.enriched
  records appended to log        850   including relay re-publishes
  expected charge total        74,543.51 EUR
  simulated seconds            60.00   virtual clock, nothing sleeps
  records per partition      [74, 43, 83, 119, 132, 163, 95, 141]
    uneven because 60 customer keys over 8 partitions is low cardinality -
    hash skew, exactly as lesson 07 measured. Ordering is per key regardless.

== 2. THE FAULT SCHEDULE: all of it, in one run ==
  t= 12.00  relay crashes after publish, before mark -> duplicate publish
  t= 18.00  email provider degrades until t=30 (503s and lost responses)
  t= 20.00  producer bad deploy emits 4 malformed events
  t= 25.00  payments member 1 crashes mid-batch
  t= 27.00  lease expires, its uncommitted window is redelivered
  t= 30.00  card gateway slows 14->2 rec/s per member until t=48
  t= 30.00  warehouse loader slows 25->4 rec/s per member until t=44
  t= 32.00  a deploy adds an email member -> eager rebalance
  t= 40.00  producer starts emitting schema_version 2
  t= 50.00  relay process dies until t=58

== 3. WHAT ACTUALLY HAPPENED ==
  t= 12.00  RELAY CRASHED after publishing 3 rows, before marking them published
  t= 20.00  PRODUCER BAD DEPLOY: 4 malformed order.placed events (total_cents="N/A") -> partition 7
  t= 25.00  payments: member 1 CRASHED mid-batch, 30 uncommitted records will be redelivered
  t= 27.00  payments: member 1 back after lease expiry; partitions reassigned
  t= 32.00  email: REBALANCE (deploy adds a member) -> 2 members, 25 uncommitted records replayed
  t= 39.00  analytics: SHEDDING order.enriched (time lag 8.10 s > 8 s)
  t= 41.00  payments: REBALANCE (autoscale to 8 on lag) -> 8 members, 4 uncommitted records replayed
  t= 41.00    ^ lag-driven: time lag 10.10 s > 10 s threshold
  t= 45.00  analytics: shedding off (time lag 2.10 s)
  t= 50.00  RELAY OUTAGE begins: the process is gone, outbox lag now climbs 1 s per second
  t= 58.00  RELAY back: 114 rows pending, outbox lag 8.20 s
  t= 58.00  analytics: SHEDDING order.enriched (time lag 8.20 s > 8 s)
  t= 60.00  analytics: shedding off (time lag 0.00 s)

== 4. LAG, AND THE LAG-DRIVEN RESPONSE ==
  group        peak count lag   peak time lag   peak at  members
  payments                144         13.70 s       49s        8
  email                    80          9.20 s       59s        2
  analytics               110          9.60 s       44s        2

  payments time lag, 1 s samples, t=0 to t=60s (peak 13.70 s):
      ..:  ..:  ..:  ..:  ..:::-==  ..::-==++*##%*##%@        +* 
  analytics time lag, 1 s samples, t=0 to t=60s (peak 9.60 s):
      .:-  .:-  .:-  .:-  .:-  .:-  .:--=+*#+*#%@.:-=+        #% 
  the autoscaler took payments from 2 to 8 members (the partition ceiling is 8)
  analytics shed 74 order.enriched records to protect order.placed
  outbox lag peaked at 7.20 s during the relay outage

== 5. THE DEAD-LETTER QUEUES: quarantined, not retried forever ==
  payments   depth   4   PermanentValidationError=4
  email      depth   4   PermanentValidationError=4
  analytics  depth   4   PermanentValidationError=4

  one payments DLQ record (the replay address is the point):
    message_id       4b5a4671-568e-4711-b12e-38afa5426a6a
    type             order.placed
    partition        7
    offset           49
    deliveries       1
    reason           PermanentValidationError
    detail           total_amount is not a positive integer
    occurred_at      20.0
    dead_lettered_at 20.0

  payments throughput around the poison window (t=20 to t=26), per partition:
    partition 7 (holds all 4 poison events)     2.00 rec/s
    the other 7 partitions, mean                 2.02 rec/s
    same partition, the 6 s before the poison     3.33 rec/s
    the poisoned partition kept pace with its peers: a permanent failure is
    classified on the FIRST delivery and parked, so it never blocks the head.

== 6. THE SCHEMA CHANGE MID-STREAM ==
  producer switched to schema_version 2 at t=40
    v1 order.placed records read by analytics      400
    v2 order.placed records read by analytics      200
  upcaster hops applied (v1 -> v2)                     400
  consumer code knows exactly one shape: v2. No version branch anywhere.
  analytics revenue total   74,543.51 EUR vs expected 74,543.51 EUR   match: True

== 7. INVARIANT VERIFICATION ==
  [PASS]  1. NO ORDER IS LOST
          orders committed to the database            600
          distinct orders charged by payments         600
          distinct orders emailed                     600
          distinct orders counted by analytics        600
          outbox rows still unpublished                 0

  [PASS]  2. NO CUSTOMER IS CHARGED TWICE
          total charged                           74,543.51 EUR
          expected                                74,543.51 EUR
          error                                        0.00 EUR
          charge rows written                         600   (one per order, never more)
          duplicate deliveries absorbed                31
            source: relay re-published events            3
            source: records rewound by the crash        34   and the autoscale rebalance

  [PASS]  3. NO POISON MESSAGE HALTS THE PIPELINE
          poison events published                       4
          dead-lettered across all groups              12
          redeliveries spent on them                    0   (classified permanent on delivery 1)
          poisoned partition throughput              2.00 rec/s
          peer partitions, same window               2.02 rec/s
          every group reached the tail of every partition           yes

  [PASS]  4. PER-CUSTOMER ORDERING IS PRESERVED
          partition key                           customer_id
          customers                                    60   mean 10.0 orders each
          sequence inversions applied                   0
          customers with a damaged sequence             0

== 8. THE COUNTERFACTUAL: identical faults, idempotency disabled ==
  Same seed, same schedule, same 604 events, same crashes. The only change:
  the payments dedup record, the analytics dedup set, and the email
  idempotency key are all removed.

  measure                                    idempotent   NOT idempotent
  ----------------------------------------------------------------------
  deliveries to payments                            884              884
  charge rows written                               600              631
  distinct orders charged                           600              600
  total charged (EUR)                         74,543.51        78,161.52
  expected (EUR)                              74,543.51        74,543.51
  OVERCHARGE (EUR)                                 0.00         3,618.01
  customers double-charged                            0               31
  duplicate deliveries absorbed                      31                0
  sequence inversions applied                         0                7
  customers with damaged order                        0                5
  emails actually sent                              600              751
  provider-suppressed duplicates                    116                0
  DUPLICATE EMAILS DELIVERED                          0              151
  analytics revenue (EUR)                     74,543.51        74,820.88

  The delivery layer was byte-identical in both runs: 884 deliveries either way.
  Removing three dedup mechanisms moved 3,618.01 EUR of other people's
  money and put 5 customers' event sequences out of order.

== 9. OPERATIONAL DASHBOARD (what you would page on) ==
  group         count lag   time lag   delivered   effects    dups  retries   shed   DLQ
  payments            144     13.70s         884       600      31        0      0     4
  email                80      9.20s         875       600     116      198      0     4
  analytics           110      9.60s         850       600       3        0     74     4

  outbox: peak lag 7.20 s   relay polls 209 (0.0% empty)   crashes 1
  relay duplicate publishes 3   rebalances: email 1, payments 1
  email provider: sent 600  key-suppressed 116  duplicates delivered 0
  email idempotency margin: widest retry gap 26.00 s against a 30 s key TTL
    -> 4.00 s of margin. Raise the backoff cap (90 s) above the TTL and this stops being zero.
  dedup store size: 600 rows in payments.processed (prune above the max DLQ residence time)

  All four invariants held under nine simultaneous faults. The email row is the
  honest one: an external send is only as idempotent as the provider's key TTL.
```

### Reading the result

**Section 7 is the deliverable.** Four invariants, four `PASS`, with the supporting counts rather than an assertion. 600 orders committed, 600 charged, 600 emailed, 600 counted; **74,543.51 EUR** charged against **74,543.51 EUR** expected, error **0.00**; 12 dead-letter entries and 0 redeliveries wasted on them; 0 sequence inversions.

Note what invariant 1's evidence looks like: **three independent counts of 600**, from three consumer groups with different code, different failure modes and different downstreams, plus a fourth count of 0 unpublished outbox rows. A single count would only prove one path worked. Cross-checking independent effects against the source of truth is what an end-to-end verification is; anything less is a unit test with ambitions.

**Section 8 is the argument.** The two runs received **884 deliveries each** — byte-identical delivery layers, the same seed, the same nine faults at the same simulated timestamps. The only difference is three dedup mechanisms. Removing them:

- **31 duplicate charges**, totalling **3,618.01 EUR** of overcharge — a 4.9% error on a bill, silently, with every log line reading success.
- **7 sequence inversions across 5 customers.** Ordering was never a delivery-layer property. The partition key routed correctly in *both* runs; what broke ordering in the second was replaying an older event after a newer one had already been applied. **At-least-once means "ordered modulo redelivery", and idempotency is what converts that back into ordering.** This is the interaction most people miss: they treat the partition key as the ordering mechanism and idempotency as the duplicate mechanism, and then discover that removing the second breaks the first.
- **151 duplicate emails** delivered to real inboxes. The only thing standing between 0 and 151 was a single `Idempotency-Key` header derived from the business event rather than the transmission.
- Analytics revenue drifted to **74,820.88 EUR** — wrong by 277.37 EUR, small enough to survive a sanity check and large enough to make a report wrong.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="A side-by-side comparison of two runs with identical fault schedules and 884 identical deliveries. With idempotency the pipeline writes 600 charge rows, charges exactly 74543.51 euros, sends 600 emails and records zero sequence inversions. Without idempotency the same deliveries produce 631 charge rows, 78161.52 euros charged, an overcharge of 3618.01 euros across 31 double-charged customers, 751 emails including 151 duplicates, and 7 sequence inversions across 5 customers.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same faults. Same 884 deliveries. Three lines of code removed.</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="48" width="416" height="330" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="448" y="48" width="416" height="330" rx="13" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.6">
    <rect x="40" y="140" width="256" height="22" rx="4" fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f"/>
    <rect x="472" y="140" width="256" height="22" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    <rect x="728" y="140" width="13" height="22" rx="3" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
    <rect x="40" y="216" width="256" height="22" rx="4" fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f"/>
    <rect x="472" y="216" width="256" height="22" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    <rect x="728" y="216" width="64" height="22" rx="3" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="224" y="78" font-size="13" font-weight="700" text-anchor="middle" fill="#0fa07f">IDEMPOTENT</text>
    <text x="224" y="97" font-size="9.5" text-anchor="middle" opacity="0.85">dedup row + effect in one commit · shared seen-set · provider key</text>
    <text x="656" y="78" font-size="13" font-weight="700" text-anchor="middle" fill="#e0930f">NOT IDEMPOTENT</text>
    <text x="656" y="97" font-size="9.5" text-anchor="middle" opacity="0.85">the identical pipeline with those three mechanisms deleted</text>

    <text x="40" y="132" font-size="9.5" font-weight="700">charge rows written</text>
    <text x="308" y="157" font-size="10" font-weight="700">600</text>
    <text x="472" y="132" font-size="9.5" font-weight="700">charge rows written</text>
    <text x="752" y="157" font-size="10" font-weight="700" fill="#e0930f">631</text>
    <text x="472" y="182" font-size="9" opacity="0.9">31 customers charged twice</text>

    <text x="40" y="208" font-size="9.5" font-weight="700">emails delivered</text>
    <text x="308" y="233" font-size="10" font-weight="700">600</text>
    <text x="472" y="208" font-size="9.5" font-weight="700">emails delivered</text>
    <text x="800" y="233" font-size="10" font-weight="700" fill="#e0930f">751</text>
    <text x="472" y="258" font-size="9" opacity="0.9">151 duplicates, into real inboxes, unrecallable</text>

    <text x="40" y="292" font-size="9.5" font-weight="700">total charged</text>
    <text x="40" y="316" font-size="17" font-weight="700" fill="#0fa07f">EUR 74,543.51</text>
    <text x="40" y="336" font-size="9.5" opacity="0.95">expected EUR 74,543.51 — error 0.00</text>
    <text x="40" y="358" font-size="9.5" font-weight="700">sequence inversions 0 · damaged customers 0</text>

    <text x="472" y="292" font-size="9.5" font-weight="700">total charged</text>
    <text x="472" y="316" font-size="17" font-weight="700" fill="#e0930f">EUR 78,161.52</text>
    <text x="472" y="336" font-size="9.5" font-weight="700">overcharge EUR 3,618.01 — 4.9% of the bill</text>
    <text x="472" y="358" font-size="9.5" font-weight="700" fill="#e0930f">sequence inversions 7 · damaged customers 5</text>

    <text x="440" y="404" font-size="10.5" text-anchor="middle" opacity="0.95">The inversions are the surprise: the partition key routed correctly in BOTH runs. Ordering broke because an OLDER</text>
    <text x="440" y="422" font-size="10.5" text-anchor="middle" opacity="0.95">event was replayed after a newer one had applied. Idempotency is not only a duplicate defence — it is an ordering defence.</text>
  </g>
</svg>
```

One more detail worth stealing from section 4. The dashboard reports the outbox lag peak as **7.20 s**, while the timeline records **8.20 s** at the instant the relay returned. Both are correct: the dashboard samples once per second and the true peak fell between two samples. **A sampled metric always under-reports its own peak**, which is why the alert threshold on a lag metric should sit meaningfully below the number that actually hurts you.

## Use It

Rather than another broker tour, treat this as the production-readiness review you would run before this pipeline carries real money. Two parts: what you would actually run, and what you would page on.

### What each component becomes in production

| You built | You would run | The one thing to get right |
|---|---|---|
| `PartitionedLog` | A retained log broker — Kafka, Redpanda, Pulsar, Kinesis | The partition count. It is close to permanent; size for 3–5× projected peak on day one. |
| Partition key | Kafka's record `key`, Kinesis's partition key, SQS FIFO's `MessageGroupId`, Pub/Sub's ordering key | The aggregate id, not the tenant and not the event id. |
| `Relay` | A CDC connector (Debezium on the Postgres WAL) tailing the outbox table, or a leader-elected poller | A dead connector retains WAL and can fill the primary's disk. Alert on inactive replication slots. |
| Outbox table | A real table with a **partial index** on unpublished rows and a batched pruning job | Unpruned, it becomes your largest table within six months. |
| `processed` dedup table | Postgres with a unique constraint, or Redis/DynamoDB with a TTL | The TTL must exceed the maximum DLQ residence time, not the maximum lease. |
| Upcaster chain | A schema registry (Confluent, Apicurio, Glue) with `FULL_TRANSITIVE`, enforced in CI | The gate belongs on the producer's PR, before the schema is registered. |
| Retry lane | A retry topic per backoff tier, or the broker's native delayed delivery | Only for streams whose ordering you have declared unnecessary, in writing. |
| DLQ | A real topic or queue per consumer group, with a redrive tool | Each group needs its own; a shared DLQ makes ownership unassignable. |
| Lag sampling | The broker's consumer-group metrics into Prometheus/CloudWatch | Export **time** lag, not just offset lag. Most exporters only give you the second one. |
| The invariant checks | A scheduled reconciliation job comparing source rows to downstream effects | Run it hourly. It is the only thing that catches a silent, non-erroring loss. |

### The monitoring and alerting set

The discriminating question for every alert is *which failure does this distinguish?* An alert that fires for four different causes is a page, not a signal.

| Metric | Threshold | Why | What it distinguishes |
|---|---|---|---|
| `outbox_lag_seconds` (age of oldest unpublished row) | warn 30 s, page 120 s | Grows at 1 s/s when the relay stops. Baseline is the poll interval, not zero. | **Relay dead** — the only metric that moves when nothing else does |
| `relay_heartbeat` | page on absence > 60 s | Outbox lag stays flat during quiet hours even with a dead relay | Relay dead **at 3 a.m.** |
| `consumer_time_lag_seconds` per group | page at 25% of retention | Directly comparable to your SLA and to the retention deadline | **Consumer behind** — and the gap to retention is your deadline for silent loss |
| `consumer_time_lag_seconds` **rising on all groups at once** | correlation rule, not a threshold | Independent groups share only the upstream | **Upstream problem** — do not scale consumers |
| `dlq_depth` **rate of change**, plus first arrival after quiet | page on any arrival after 1 h of zero | Depth alone is a backlog of already-known problems | **New class of bad data**, usually a deploy |
| `redelivery_rate` (deliveries ÷ unique) | warn above 1.05 | Rises with lost acks, mis-tuned leases, and rebalance storms | **Lease too short** vs **consumers thrashing** |
| `duplicates_suppressed` | alert on a step change | Your dedup store is the only thing that sees redelivery pressure | Early warning that acks are being lost |
| `rebalances_per_hour` per group | warn above 4 | Every rebalance is a stop-the-world replay | **Consumer thrashing** — GC pauses, liveness probes, a crash loop |
| `charged_total − expected_total` (reconciliation) | page on any nonzero | The invariant itself, measured against the source of truth | **An idempotency mechanism has failed** |
| Consumer lag **flat and nonzero while throughput is zero** | page | The signature of a stalled, not slow, consumer | **Stuck consumer** vs **slow consumer** |
| Consumer lag **zero while throughput is zero** | warn | Zero lag means healthy or starved; only throughput tells you which | **Starved consumer** — the producer or relay stopped |

A sketch you can adapt — the shapes matter more than the syntax:

```yaml
groups:
  - name: order-pipeline
    rules:
      - alert: OutboxRelayStalled
        expr: max(outbox_lag_seconds) > 120
        for: 2m
        annotations:
          summary: "Outbox lag {{ $value }}s - the relay is not publishing"
          runbook: "outputs/runbook-event-pipeline-operations.md#relay-dead"

      - alert: OutboxRelayHeartbeatMissing      # catches a quiet-hours death
        expr: time() - max(relay_last_loop_timestamp_seconds) > 60
        for: 1m

      - alert: ConsumerApproachingRetention
        expr: consumer_time_lag_seconds / on(topic) topic_retention_seconds > 0.25
        for: 10m
        annotations:
          summary: "{{ $labels.group }} is 25% into the retention window - data loss deadline"

      - alert: UpstreamStall                    # all groups rise together
        expr: count(deriv(consumer_time_lag_seconds[5m]) > 0.5) >= 3
        for: 3m
        annotations:
          summary: "Every consumer group is falling behind - suspect producer or relay, NOT consumers"

      - alert: DeadLetterArrivalAfterQuiet
        expr: increase(dlq_messages_total[10m]) > 0
            and max_over_time(increase(dlq_messages_total[1h])[1h:]) == 0
        annotations:
          summary: "First dead letters in an hour on {{ $labels.group }} - check recent deploys"

      - alert: ConsumerGroupThrashing
        expr: increase(consumer_rebalances_total[1h]) > 4
        annotations:
          summary: "{{ $labels.group }} rebalanced {{ $value }} times/hour - every one replays work"

      - alert: ReconciliationMismatch           # the invariant, as an alarm
        expr: abs(orders_committed_total - order_effects_applied_total) > 0
        for: 15m
        labels: { severity: page }
```

Note what is deliberately absent: **there is no alert on CPU, and no alert on raw queue depth.** A consumer blocked on a slow downstream has near-zero CPU and enormous lag; a depth of 5,000 is a crisis at 10 msg/s and a rounding error at 10,000 msg/s. Alert on time and on the invariants.

## Think about it

1. Overnight, `payments` consumer lag rises steadily while `email` and `analytics` lag stays flat at their normal baseline. `dlq_depth` is unchanged and `redelivery_rate` is 1.0. Name the two most likely causes, say which single additional metric separates them, and say which of the four invariants is at risk first and why.

2. All three consumer groups' lag starts rising at the same minute, and outbox lag is flat at its 0.25 s baseline. What can you rule out immediately, what is the likely cause, and why would scaling consumers make the situation worse rather than better?

3. Your team wants to raise `MAX_ATTEMPTS` from 6 to 12 for the email consumer so fewer messages dead-letter. The provider's `Idempotency-Key` TTL is 30 seconds and the measured widest retry gap today is 26.00 s. Work out what breaks, name the invariant, and give two fixes — one that changes the retry policy and one that changes nothing about retries at all.

4. You must increase the partition count from 8 to 12 because one partition is hot. Walk through what happens to a customer whose key remaps from partition 5 to partition 9 while partition 5 still has 40 seconds of backlog. Which invariant breaks, which mechanism from this phase would have absorbed it, and which of the three safe procedures from Lesson 07 would you choose, given that this pipeline charges cards?

5. Six months from now, someone adds a fourth consumer group — `fraud` — that must see the last 30 days from offset 0. List everything in the pipeline that this backfill stresses, in order of what breaks first. (There are at least four: think about schema, dedup, downstream rate, and the shape of the burst.)

6. The counterfactual produced 7 sequence inversions even though the partition key was correct in both runs. Explain the exact mechanism in terms of committed offsets, then design a defence that would hold the ordering invariant *even if* the dedup store were unavailable — and say what that defence cannot do that idempotency can.

## Key takeaways

- **Assembly is a distinct skill from construction.** Every mechanism in this phase was demonstrated against one fault on a clean bench; production presents them simultaneously, and the interactions are where systems break. The capstone ran nine faults at once — relay crash, relay outage, provider degradation, poison deploy, consumer crash, rebalance, two slow downstreams and a mid-stream schema change — and all four invariants held.
- **State your invariants before you design anything.** *No order lost · no double charge · no poison halt · per-customer ordering preserved.* Each is a property of the whole chain, not of any component, which is why no single service can guarantee one and why an end-to-end reconciliation job is the only honest test. Three independent counts of 600, cross-checked against 600 committed orders, is what verification looks like.
- **The `message_id` and the partition key carry the whole architecture.** The id is generated once, inside the business transaction, in the outbox row — so every retry, re-publish and replay carries the same identity, and the dedup store, DLQ, trace and external provider key all agree. The partition key is the aggregate id, so every downstream mechanism inherits per-customer ordering for free. Get either wrong and nothing downstream can recover.
- **The fix for lag is a duplicate generator.** Scaling consumers to cut lag *is* a rebalance, and a rebalance replays every uncommitted window — measured here as 34 rewound records and 31 duplicate deliveries, all inside the already-degraded window. **Make consumers idempotent before you enable the autoscaler**, not after.
- **Parking a failing message trades ordering for throughput.** A retry lane un-blocks the partition and un-orders the key. That is correct for email and fatal for payments, which is why this pipeline runs two different failure strategies in the same system. "Use a retry topic" is a rule about a stream whose ordering you have declared unnecessary — in writing.
- **Idempotency is an ordering defence, not just a duplicate defence.** In the counterfactual the partition key routed correctly and ordering still broke: **7 inversions across 5 customers**, caused by replaying an older event after a newer one had applied. At-least-once delivery means "ordered modulo redelivery", and idempotency is what converts that back into ordering.
- **The counterfactual is the proof the mechanisms are load-bearing.** Identical seed, identical faults, **884 identical deliveries** — three dedup mechanisms removed produced **31 double charges worth 3,618.01 EUR**, **151 duplicate emails**, 7 inversions, and analytics revenue wrong by 277.37 EUR. Every log line still read success.
- **The end-to-end guarantee is the weakest link, and the audit is five steps:** enumerate the hops, name each hop's delivery semantic, name every effect's idempotency mechanism *and its scope*, find the dual writes, and find the shortest TTL on the path. This pipeline has exactly one bounded hop and the program measures its margin: a 30 s provider key TTL against a 26.00 s widest retry gap — **4.00 s** of headroom, stated out loud rather than discovered during an incident.
- **Two failures look identical on a lag graph and demand opposite responses.** A dead relay drove consumer lag to **exactly 0.00 on every group** while outbox lag climbed 1 s/s to 8.20 s; a dead consumer does the reverse. A lag of zero means healthy *or* starved — the discriminator is throughput. Independent consumer groups spiking in unison is an upstream signature. Alert on time lag against the retention window, on outbox lag, on relay heartbeat and on reconciliation — never on CPU, never on raw depth.

## Where to go next

That is the phase. You have built a message, a queue, a topic, a log, an idempotent consumer, a partitioned stream, a retry-and-dead-letter path, a lag-driven flow controller, a transactional outbox, a saga, a schema registry and an upcaster chain — and then assembled all of them into a pipeline that survives its own worst day.

Now go back and re-read [Why Async? Coupling and the Cost of the Direct Call](../01-why-async-and-the-cost-of-coupling/). It will read differently. Lesson 01 argued that async trades simplicity and immediacy for resilience and scale, and listed the costs abstractly: eventual consistency, a broker to operate, harder debugging. You have now paid every one of those costs concretely — the dedup store you must size and prune, the partition count you cannot change, the relay you must monitor separately, the upcasters you must keep forever, the invariants you must reconcile because no dashboard will tell you they broke. That list is what "async is a tool, not an upgrade" actually means, and it is worth much more now that the machinery is real.

Next: [Authentication, Authorization & the Security Mindset](../../07-auth-and-security/01-authn-authz-and-the-security-mindset/) — this pipeline moves money and personal data between services that never authenticate each other, over a broker that will hand any message to anyone who subscribes. Phase 7 is about who is allowed to do what, and how you prove it.
