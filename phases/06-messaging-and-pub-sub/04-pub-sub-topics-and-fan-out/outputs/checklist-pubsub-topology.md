---
name: checklist-pubsub-topology
description: A design and review checklist for a pub/sub topology - topic granularity, subscription durability, where filtering runs, fan-out cost arithmetic, slow-subscriber isolation, and how to add a subscriber without an incident
phase: 6
lesson: 04
---

# Checklist — Designing a Pub/Sub Topology

Run this when you are adding a topic, adding a subscription, or reviewing someone else's event
design. It assumes the primitives from the lesson: a **topic** fans out to **subscriptions**, each
subscription has its own queue and its own acknowledgement state, and one publish costs N writes.

The governing question, asked before anything else:

> **Is this message a command (*do this*) or a fact (*this happened*)?**

A command has exactly one correct owner and belongs on a **queue**. A fact has an unknown number of
interested parties and belongs on a **topic**. Getting this wrong is not a tuning problem — the
guarantee itself is inverted.

## Step 1 — Topic granularity and naming

- [ ] **Name the topic after the thing that happened, not the consumer or the system.**
      `orders` or `order-events`, never `email-topic`, `analytics-feed`, or `service-a-to-b`.
      A topic named after a consumer is spatial coupling that survived the refactor.
- [ ] **Pick a granularity and write the reason down.** The two coherent answers:

      | | One topic per event type | One coarse topic per domain |
      |---|---|---|
      | Subscribe to a subset | trivial — subscribe to the topic | needs subject/attribute filtering |
      | New event type | new topic + new IAM/ACL + new plumbing | free; publishers just use a new subject |
      | Subscriber sees | exactly what it asked for | everything, then filters |
      | Ordering | none across topics | possible within the topic |
      | Fails at scale by | topic sprawl (hundreds of topics, no one owns them) | fan-out waste + one hot topic |

      Default to a **coarse topic per domain with a subject hierarchy**, unless events have
      genuinely different retention, access-control, or volume profiles — those are the three
      things a topic boundary actually enforces.
- [ ] **Design the subject hierarchy left-to-right, most-filtered-on dimension first.**
      `order.eu-west-1.created` supports `order.#`, `order.eu-west-1.*`, and `order.*.created`.
      `created.order.eu-west-1` supports none of them cheaply.
- [ ] **Bound every subject segment.** No customer ids, order ids, or trace ids in a subject.
      Brokers index subjects; unbounded segments are the Phase 4 cardinality explosion.
- [ ] **Write down the wildcard dialect you are on.** `*` is one token everywhere. The
      multi-segment wildcard is not portable: AMQP `#` matches **zero or more** words (so
      `order.#` matches bare `order`); NATS `>` matches **one or more** and must be terminal;
      MQTT uses `/` + `+` + `#`. Record it, because it survives a migration undetected.

## Step 2 — Choose durability, per subscription

- [ ] Answer one question: **does this message drive state, or drive a display?**
      Drives state → **durable**. Drives a display → **ephemeral** is fine and cheaper.
- [ ] If **ephemeral**, accept in writing that a rolling restart loses everything published during
      it, at-most-once, with no error and no backlog metric. Confirm nobody downstream reconciles
      against this stream.
- [ ] If **durable**, you have accepted a backlog, and Steps 5–7 are now mandatory.
- [ ] **Never infer durability from the broker's default.** Redis pub/sub, NATS core, and
      SNS→HTTPS are ephemeral; SNS→SQS, JetStream consumers, and Google Pub/Sub subscriptions are
      durable. Same word, opposite behaviour.

## Step 3 — Decide where each filter runs

- [ ] **Compute selectivity per subscription**: `messages passing the filter / messages matching
      the subject`. This single number decides the design.

      | Selectivity | Where the filter belongs |
      |---|---|
      | > ~80% | consumer-side — broker-side adds hot-path CPU and saves little |
      | ~20–80% | broker-side usually wins; measure the bytes |
      | < ~20% | broker-side, clearly — the waste is most of the traffic |

- [ ] **Filters read the envelope, never the payload.** If a filter needs a body field, either
      promote that field to a header or accept that the broker must deserialize your payload once
      per subscription on the hot path — and that a schema change can then break routing.
- [ ] **Header values are strings on the wire.** Any numeric rule parses. Pin the producer's
      formatting (no thousands separators, no scientific notation) or the filter fails silently.
- [ ] **Flag any subscription subscribing to `#` (or the firehose) that discards most of it.**
      That is a self-inflicted denial of service, not a subscription.

## Step 4 — Do the fan-out arithmetic before you ship

Fill this in with real numbers. One publish becomes N deliveries; nothing here is optional.

```text
message size            _____ KB   (envelope + payload)
publish rate            _____ /s
subscriptions matching  _____ N

ingress    = size x rate                       = _____ MB/s
egress     = size x rate x N x selectivity     = _____ MB/s     <- the number that surprises people
storage/day= size x rate x 86400 x N           = _____ GB/day   (durable subscriptions only)
```

- [ ] **Check egress against the broker's actual NIC.** 4 KB at 10,000/s across 8 subscriptions is
      320 MB/s — a 2.5 Gbps link doing nothing but fan-out. Brokers are egress-bound far more
      often than ingress-bound.
- [ ] **Check publish latency.** The publish is not acked until the fan-out writes are durable, so
      publish latency scales with N — **adding a subscriber can slow the producer.**
- [ ] **Confirm buffering is per subscription, not shared.** The claim "a slow subscriber does not
      affect the others" is only true with independent buffering. Shared buffers, shared delivery
      threads, or a shared disk quota make one stuck subscriber everyone's problem.

## Step 5 — Push or pull

- [ ] **Pull by default** — backpressure is free, the backlog stays visible and bounded in the
      broker, and a busy consumer simply does not ask.
- [ ] **Push only when latency dominates and consumers are reliably fast.** If you push, name the
      flow-control mechanism (prefetch window, credit limit, max outstanding) and the behaviour
      when a consumer stops responding. "The broker buffers" is not an answer; it is an unbounded
      buffer with a different name.

## Step 6 — Slow-subscriber isolation and retention

The failure shape: one stuck subscriber fills the broker's shared disk, and every producer and
every other subscription goes down with it.

- [ ] **Do the backlog arithmetic** for a realistic outage — *a consumer down over a weekend*, not
      ten minutes. `rate x seconds x message size x`. 5,000/s of 1 KB for 48 h is ~864 GB.
- [ ] **Set a retention or expiry bound on every durable subscription** — max age or max depth,
      after which the broker discards deliberately and counts it, rather than dying.
- [ ] **Every subscription has a named owning team**, recorded somewhere a stranger can find it.
- [ ] **Sweep for abandoned subscriptions on a schedule.** The prototype whose service was deleted
      is the classic disk-filler. Alarm on any subscription with zero acks over 24 h.

## Step 7 — Per-subscription alerting and DLQ

Aggregate topic metrics hide exactly the failure you care about: total backlog looks fine when
four subscriptions are at zero and the fifth is at 800 GB.

- [ ] **Alarm per subscription, never in aggregate**, on:
      - **age of oldest unacknowledged message** — the best single indicator; seconds behind, not
        raw depth (Little's Law: `depth / drain rate`)
      - backlog depth, against the retention bound
      - ack rate dropping to zero while publish rate is non-zero
      - redelivery rate — a spike means crashes or a lease that is too short
- [ ] **Ephemeral subscriptions need a different alarm.** Their backlog is flat at zero whether
      healthy or dropping everything. Alarm on delivery-side evidence instead — subscriber count,
      or the broker's "delivered to N clients" counter reaching zero.
- [ ] **Every subscription gets its own dead-letter queue and its own maxReceiveCount.** A poison
      message is poison to one subscriber's *code*, not to the topic; a shared DLQ makes it
      everyone's incident.
- [ ] **Every DLQ has an alarm and a documented drain procedure.** A DLQ nobody watches is a
      slower way to lose messages.

## Step 8 — Adding a subscriber safely

Adding a subscription is a production change to *every* publisher's latency and the broker's disk,
even though the producer's code does not change.

- [ ] Compute the new N and re-run Step 4. Egress and storage both go up by one subscription's
      worth **before** the subscriber processes anything.
- [ ] **Create the subscription with a filter and a retention bound from the first commit**, not
      "we will narrow it later". A subscription created wide and left wide is permanent.
- [ ] **Create it before the consumer is deployed only if you have a retention bound** — otherwise
      you have built a backlog generator with no drain.
- [ ] Deploy the consumer, confirm the ack rate is non-zero and the backlog is draining, *then*
      widen the filter to full scope if you staged it.
- [ ] Add the per-subscription alarms from Step 7 **in the same change**, not as follow-up work.
- [ ] Confirm the consumer is **independently idempotent** — delivery is at-least-once, and its
      redeliveries are unrelated to any other subscription's.

## Step 9 — Sanity checks against the classic mistakes

- [ ] **No producer fan-out.** If the producer publishes the same message to N destinations, you
      have handed back the spatial decoupling and created an N-way dual-write.
- [ ] **No dispatcher service.** A consumer that re-forwards to N others holds one ack for N
      independent outcomes: it must either lose messages or duplicate them. That ambiguity is
      unfixable, which is the whole reason subscriptions exist.
- [ ] **No cross-subscription ordering assumptions.** "Analytics has seen it by the time shipping
      acts" is a race. There is no global order across subscriptions, only a partial one.
- [ ] **No code asking "was this event processed?"** With N subscriptions the honest answer is
      "processed by two, retrying in one, unseen by one" — the question is malformed. User-visible
      state must live in a service that owns it, not be inferred from event delivery.
- [ ] **No identifiers in subjects.** See Step 1.
- [ ] **Not actually a fan-out-to-browsers problem.** Tens of durable service subscriptions is this
      checklist. A hundred thousand WebSocket clients is a different discipline — an edge relay
      tier with per-connection drop policy and conflation, subscribing to your broker once.

## The one-line record

Put this in the design doc for each subscription, so the decision outlives the people who made it:

```text
<topic>/<subscription>  ->  DURABLE | EPHEMERAL
  pattern:     <subject pattern>            filter: <policy>   selectivity: __%
  filter runs: BROKER | CONSUMER            because: <selectivity + broker CPU headroom>
  delivery:    PUSH | PULL                  ack deadline: __s
  costs:       +__ MB/s egress, +__ GB/day storage, +__ ms publish latency
  bounds:      retention __d / __GB         DLQ: <name>, maxReceive __
  owner:       <team>                       alarms: oldest-unacked > __s, ack-rate == 0
```
