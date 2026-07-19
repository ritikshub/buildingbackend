# Pub/Sub: Topics, Subscriptions & Fan-Out

> The queue you just built has one rule that is about to become a problem: each message goes to exactly one consumer. That is perfect for work and catastrophic for news. When five services all need to know that an order was placed, "exactly one of you gets this" is precisely the wrong guarantee. This lesson builds the other broker shape — one message, many independent readers — and measures what it costs, because one publish quietly becomes N writes and somebody pays for all of them.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Build a Message Queue: Work Distribution & Acknowledgement](../03-build-a-message-queue/)
**Time:** ~75 minutes

## The Problem

The queue from [Lesson 3](../03-build-a-message-queue/) does one thing extremely well. Producers push work in; a pool of competing consumers pulls work out; each message is leased to exactly one consumer, acknowledged, and gone. Add a consumer and throughput rises. That is **work distribution**, and it is the right primitive whenever a message represents a *job* — resize this image, charge this card, send this one email.

Now change the message from a job to a fact. `OrderPlaced`. Who wants it?

- `shipping` needs to reserve a courier slot.
- `email` needs to send the confirmation.
- `analytics` needs to update the funnel.
- `search` needs to reindex the customer's order history.
- `fraud` needs to score the transaction.

Five services, five completely different reactions to one fact. Put that message on a queue and exactly one of those five gets it, chosen essentially at random. The other four never learn the order exists. The queue's defining guarantee — *exactly one consumer* — is now the bug.

Engineers reach for two workarounds before they reach for the right primitive, and both are worth understanding because both look reasonable on a whiteboard.

**Workaround one: the producer publishes to five queues.** `orders` writes the same message to `q.shipping`, `q.email`, `q.analytics`, `q.search`, and `q.fraud`. It works. It also throws away the single most valuable thing the broker gave you. [Lesson 1](../01-why-async-and-the-cost-of-coupling/) named three couplings a broker breaks — temporal, spatial, and load — and this design hands the **spatial** one straight back. The producer now knows every consumer by name, so adding a sixth subscriber means editing, testing, reviewing and deploying `orders` for a feature that has nothing to do with orders: the `loyalty` team cannot ship without the `orders` team's calendar. You have rebuilt the direct-call coupling on top of a broker and kept none of the benefit.

And five writes are not one write. If the producer crashes after three of them, three services think an order exists and two do not, with no record anywhere of which — a five-way dual-write problem ([Lesson 10](../10-dual-write-outbox-and-cdc/)) where you previously had none.

**Workaround two: one queue, one consumer that re-dispatches.** Keep a single `q.orders`, and have a small "dispatcher" service consume it and forward each message onward to the five real consumers. The producer stays ignorant, which is better. But look at what you built: a service that must know every consumer, that everything depends on, and that is a single point of failure for all five downstream flows. It is the spatial coupling again, relocated one hop and given a pager.

Worse is what happens on partial failure. The dispatcher takes a message, successfully forwards it to `shipping`, `email`, and `analytics`, then fails to reach `search` and `fraud`. What does it do with the acknowledgement? If it acks, two services permanently lose the event. If it nacks, the message is redelivered and `shipping`, `email`, and `analytics` get it **twice**. There is no third option, because the dispatcher holds one ack for five independent outcomes. You have taken five independent delivery states and collapsed them into a single bit, and information theory is not going to give it back. That ambiguity is the tell: **delivery state must be per-recipient, or it cannot be correct.**

Which is the whole idea. The broker already has durable storage, leases, retries, and acknowledgement machinery. What it needs is not a new service in front of it but a second *shape*: a structure where one publish produces an independent, individually-tracked delivery to every interested party. That structure is a **topic**, and the per-recipient state is a **subscription**.

## The Concept

### Topic versus queue: competing consumers, or independent delivery

This distinction is the hinge the entire lesson turns on, so here it is in one sentence each.

A **queue** is *competing consumers over one message set*. There is a single collection of pending messages. Consumers race for them. A message that goes to one consumer does not go to any other. Adding consumers divides the work.

A **topic** is *independent delivery of every message to every subscription*. Each subscription behaves as if it had its own private copy of the entire stream. A message delivered to one subscription is still delivered to all the others. Adding subscriptions multiplies the work.

They answer different questions. The queue answers *"who does this job?"*; the topic answers *"who needs to know?"* A job has one correct owner; a fact has an arbitrary number of interested parties, and the producer must not have to know how many.

| | **Queue** | **Topic** |
|---|---|---|
| Mental model | a job list | a broadcast with recorders |
| Each message goes to | exactly one consumer | every subscription |
| Adding a consumer | divides the work | (see below — it depends where you add it) |
| Message represents | a command: *do this* | an event: *this happened* |
| Producer knows | the queue name | the topic name |
| Scales | throughput | audience |
| Delivery state lives | per message | per message **per subscription** |

That last row is the implementation-level truth. In a queue there is one delivery state per message: pending, leased, acked. In a topic there is one delivery state per message *per subscription*, which is why five subscribers can be at five different places in the stream, and why one subscriber's failure to ack cannot possibly affect another's.

### The subscription is the unit — and the two shapes compose

Here is the thing that trips people up, including people who have run brokers for years. **A subscription is not a consumer.** A subscription is a named, durable, independently-tracked stream position with its own delivery state. A consumer is a process that attaches to one.

Once you separate those two ideas, the "adding a consumer" row of the table above resolves cleanly, because there are two different places to add one:

- **Add a subscription** → the audience grows. One more copy of every message. Fan-out.
- **Add a consumer to an existing subscription** → that subscription's work is divided among more workers. Load balancing.

Which means the two shapes **compose**. A topic fans out across subscriptions; *within* a single subscription, the classic competing-consumers queue reappears exactly as Lesson 3 built it, leases and all. `email` can be one subscription served by twelve workers while `fraud` is one subscription served by one, and neither arrangement is visible to the other or to the producer.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="A queue delivers each message to exactly one of its competing consumers, so three consumers share the work. A topic delivers every message to every subscription independently, so three subscriptions each receive all twenty-four messages. Inside the email subscription, three competing consumers split its twenty-four messages nine, five and ten, showing that fan-out across subscriptions and load balancing within one subscription compose.">
  <defs>
    <marker id="l04-fan-a" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Two shapes, one broker — and they nest</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="170" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="226" width="848" height="314" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="108" width="96" height="48" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="184" y="102" width="152" height="60" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="404" y="84" width="112" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="404" y="120" width="112" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="404" y="156" width="112" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M136 132 L 178 132" marker-end="url(#l04-fan-a)"/>
    <path d="M336 132 L 370 132"/>
    <path d="M370 132 L 370 99 L 398 99" marker-end="url(#l04-fan-a)"/>
    <path d="M370 132 L 398 132" marker-end="url(#l04-fan-a)"/>
    <path d="M370 132 L 370 171 L 398 171" marker-end="url(#l04-fan-a)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="358" width="96" height="48" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="184" y="352" width="130" height="60" rx="9" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="360" y="278" width="196" height="56" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="360" y="356" width="196" height="56" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="360" y="450" width="196" height="60" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="616" y="286" width="112" height="40" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="616" y="364" width="112" height="40" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="616" y="432" width="112" height="26" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="616" y="464" width="112" height="26" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="616" y="496" width="112" height="26" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M136 382 L 178 382" marker-end="url(#l04-fan-a)"/>
    <path d="M314 382 L 338 382"/>
    <path d="M338 382 L 338 306 L 354 306" marker-end="url(#l04-fan-a)"/>
    <path d="M338 382 L 354 382" marker-end="url(#l04-fan-a)"/>
    <path d="M338 382 L 338 480 L 354 480" marker-end="url(#l04-fan-a)"/>
    <path d="M556 306 L 610 306" marker-end="url(#l04-fan-a)"/>
    <path d="M556 384 L 610 384" marker-end="url(#l04-fan-a)"/>
    <path d="M556 480 L 582 480"/>
    <path d="M582 480 L 582 445 L 610 445" marker-end="url(#l04-fan-a)"/>
    <path d="M582 480 L 582 477 L 610 477" marker-end="url(#l04-fan-a)"/>
    <path d="M582 480 L 582 509 L 610 509" marker-end="url(#l04-fan-a)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="68" font-size="12.5" font-weight="700" fill="#e0930f">QUEUE — competing consumers over ONE message set</text>
    <text x="36" y="88" font-size="9.5" opacity="0.85">answers "who does this job?" · a job has exactly one correct owner</text>
    <text x="88" y="130" font-size="10" font-weight="700" text-anchor="middle">producer</text>
    <text x="88" y="145" font-size="8.5" text-anchor="middle" opacity="0.8">24 msgs</text>
    <text x="260" y="127" font-size="10.5" font-weight="700" text-anchor="middle">q.orders</text>
    <text x="260" y="144" font-size="8.5" text-anchor="middle" opacity="0.85">one pending set</text>
    <text x="460" y="103" font-size="9.5" font-weight="700" text-anchor="middle">worker-1  ·  8</text>
    <text x="460" y="139" font-size="9.5" font-weight="700" text-anchor="middle">worker-2  ·  8</text>
    <text x="460" y="175" font-size="9.5" font-weight="700" text-anchor="middle">worker-3  ·  8</text>
    <text x="546" y="112" font-size="9.5" opacity="0.95">each message goes to EXACTLY ONE</text>
    <text x="546" y="130" font-size="9.5" opacity="0.95">8 + 8 + 8 = 24 · add a worker and</text>
    <text x="546" y="148" font-size="9.5" opacity="0.95">each one does LESS work</text>
    <text x="546" y="172" font-size="9.5" font-weight="700" fill="#e0930f">scales THROUGHPUT</text>

    <text x="36" y="252" font-size="12.5" font-weight="700" fill="#0fa07f">TOPIC — independent delivery of EVERY message to EVERY subscription</text>
    <text x="36" y="270" font-size="9.5" opacity="0.85">answers "who needs to know?" · a fact has any number of interested parties</text>
    <text x="88" y="380" font-size="10" font-weight="700" text-anchor="middle">producer</text>
    <text x="88" y="395" font-size="8.5" text-anchor="middle" opacity="0.8">24 msgs</text>
    <text x="249" y="377" font-size="10.5" font-weight="700" text-anchor="middle">topic</text>
    <text x="249" y="394" font-size="8.5" text-anchor="middle" opacity="0.85">"orders"</text>
    <text x="376" y="300" font-size="10" font-weight="700">SUBSCRIPTION  search-index</text>
    <text x="376" y="318" font-size="8.5" opacity="0.85">own queue · own cursor · own acks</text>
    <text x="376" y="378" font-size="10" font-weight="700">SUBSCRIPTION  analytics</text>
    <text x="376" y="396" font-size="8.5" opacity="0.85">own queue · own cursor · own acks</text>
    <text x="376" y="472" font-size="10" font-weight="700">SUBSCRIPTION  email</text>
    <text x="376" y="490" font-size="8.5" opacity="0.85">own queue — and a QUEUE inside it</text>
    <text x="672" y="311" font-size="9.5" font-weight="700" text-anchor="middle">consumer · 24</text>
    <text x="672" y="389" font-size="9.5" font-weight="700" text-anchor="middle">consumer · 24</text>
    <text x="672" y="449" font-size="9" font-weight="700" text-anchor="middle">email-1 · 9</text>
    <text x="672" y="481" font-size="9" font-weight="700" text-anchor="middle">email-2 · 5</text>
    <text x="672" y="513" font-size="9" font-weight="700" text-anchor="middle">email-3 · 10</text>
    <text x="750" y="306" font-size="9.5" opacity="0.95">24 publishes</text>
    <text x="750" y="324" font-size="9.5" opacity="0.95">72 deliveries</text>
    <text x="750" y="342" font-size="9.5" font-weight="700" fill="#0fa07f">3.0x fan-out</text>
    <text x="750" y="384" font-size="9.5" opacity="0.95">scales the</text>
    <text x="750" y="402" font-size="9.5" font-weight="700" fill="#0fa07f">AUDIENCE</text>
    <text x="748" y="440" font-size="9" opacity="0.95">9+5+10 = 24:</text>
    <text x="748" y="456" font-size="9" opacity="0.95">the subscription</text>
    <text x="748" y="472" font-size="9" opacity="0.95">still got every</text>
    <text x="748" y="488" font-size="9" opacity="0.95">message exactly</text>
    <text x="748" y="504" font-size="9" opacity="0.95">once — split three</text>
    <text x="748" y="520" font-size="9" opacity="0.95">ways internally</text>
    <text x="440" y="534" font-size="10" text-anchor="middle" font-weight="700">Fan out ACROSS subscriptions; load-balance WITHIN one. The shapes nest, and the producer sees neither.</text>
  </g>
</svg>
```

Every number in that diagram is measured by the program at the end of this lesson, including the uneven 9/5/10 split — which is not a bug, and which we will come back to.

### Durable or ephemeral: does the broker remember you were here?

The next question decides more about your operational life than any other in this lesson: **when a subscriber is not connected, does the broker keep its messages?**

An **ephemeral** subscription has no retained state. The broker pushes to whoever is currently attached, and if nobody is attached the message is discarded. There is no queue, no cursor, no acknowledgement, and nothing to clean up. This is the "pub/sub" that people who have only used Redis mean when they say pub/sub. Its delivery guarantee is **at-most-once**: you get the message or you do not, and nobody finds out which.

A **durable** subscription is a persistent, named object that exists whether or not anyone is attached. Messages accumulate in its queue while the subscriber is away. It has acknowledgement state, redelivery on lease expiry, and it survives broker restarts. Its guarantee is **at-least-once** ([Lesson 6](../06-delivery-semantics-and-idempotency/) makes that precise, and explains why the duplicates are your problem).

Ephemeral is not a lesser thing — it is a genuinely different tool with a real cost profile. It is O(1) state, it cannot build a backlog, it cannot fill a disk, and it cannot page you at 3 a.m. because a subscription nobody remembers creating has been retaining messages for six weeks. For live telemetry, presence updates, cache-invalidation hints and dashboard ticks — data whose value expires in seconds — dropping is correct behaviour and durability is pure overhead.

The trouble is that ephemeral pub/sub does not *look* lossy, because in development your subscriber is always connected. Then a subscriber redeploys — a rolling restart of six pods, twenty seconds — and everything published in that window is simply gone, with no error, no metric and no log line anywhere. Redis's `PUBLISH` returns the number of clients that received the message, and that return value is the only evidence you will ever get; if it says `0`, the message went nowhere and Redis considers the job done.

**The rule: if the message drives state, it must be durable. If it drives a display, ephemeral is fine.** An `OrderPlaced` that `shipping` must act on is state. A "342 users online" tick is a display.

### Routing, part one: subject hierarchies and wildcards

A topic with no routing is a firehose: every subscription gets everything and throws away what it does not want. That works until the volume matters, and then you want the broker to do the discarding — before the bytes hit the network.

The first and cheapest routing mechanism is **hierarchical subjects**. Instead of naming a topic `orders`, you give every message a structured, dot-separated **subject** (also called a *routing key* or *topic name*, depending on the broker):

```text
order.eu-west-1.created
order.eu-west-1.cancelled
order.us-east-1.created
payment.eu-west-1.captured
```

Subscriptions then declare a **pattern** rather than an exact name, and the broker matches subject against pattern per message. Two wildcards are near-universal, and their exact semantics are where the bodies are buried:

- **`*` matches exactly one token.** It never matches zero tokens and never crosses a separator. `order.*.created` matches `order.eu-west-1.created` but not `order.created` and not `order.eu.west.created`.
- **The multi-segment wildcard matches a run of tokens** — and here the specifications disagree with each other, which is a real interoperability trap.

The AMQP 0-9-1 specification (AMQP = Advanced Message Queuing Protocol), which defines RabbitMQ's topic exchange, uses `#` and defines it as **zero or more** words. So `order.#` matches `order.eu-west-1.created` *and* it matches the bare subject `order`. NATS uses `>` and defines it as **one or more** tokens, which must be the final token in the pattern. So `order.>` matches `order.eu-west-1.created` but does **not** match `order`. MQTT (Message Queuing Telemetry Transport, standardized by OASIS) uses `/` as its separator, `+` as its single-level wildcard and `#` as its multi-level wildcard, which must be the last character of the filter and — like AMQP — matches the parent level, so `sport/#` matches `sport` itself.

Same idea, three spellings, and two different answers to "does the multi-segment wildcard match zero tokens?" The separator character is cosmetic; the zero-or-one minimum is not, and it survives a migration undetected until the one subject that happens to have no suffix stops being routed.

The design guidance is boring and important: **put the most stable, most-filtered-on dimension leftmost**, since subjects are matched left to right. `order.eu-west-1.created` lets a subscriber cheaply say "all orders" (`order.#`), "all EU-West traffic" (`order.eu-west-1.*`) or "all creations anywhere" (`order.*.created`); `created.order.eu-west-1` would make the region filter wildcard-heavy and buy you nothing. And keep the hierarchy **bounded** — a subject segment containing a customer ID gives you a distinct subject per customer, which is the Phase 4 cardinality explosion wearing new clothes, because brokers index subjects and an index with ten million entries is not free.

### Routing, part two: attribute filters on the envelope

Subjects are a *hierarchy*, so they can only express things you thought to put in the hierarchy. The moment you want "orders over €500" or "orders from customers on the gold tier", the hierarchy fails you — those are orthogonal dimensions, and encoding both into a subject gives you the cross product.

That is what **attribute-based filtering** is for: a per-subscription predicate evaluated against the message's **headers** — the envelope from [Lesson 2](../02-anatomy-of-a-message/), not the body.

This envelope/body split is the entire point, and it is not a stylistic preference. The broker must evaluate a filter for every subscription on every message. If the filter reads the payload, the broker must **deserialize the payload** — parse JSON, or worse, load an Avro or Protobuf schema — on the hot path, once per subscription. That burns broker CPU proportional to payload size times subscription count, forces the broker to understand your serialization format (so a schema change can break routing), and destroys the useful property that a broker is an opaque pipe. Keeping filters on the envelope means the broker parses a small, flat, string-keyed map it already had to read, and the payload stays a sealed blob it copies without ever opening. The program below makes 600 filter decisions and reports **0 bytes of payload deserialized** — the invariant, made visible.

The practical shape of a filter policy, which you will recognize from more than one cloud provider:

```json
{
  "region":       [{"prefix": "eu-"}],
  "tier":         ["gold", "platinum"],
  "amount_cents": [{"numeric": [">=", 50000]}]
}
```

The conventional semantics: **AND across keys, OR within a key.** A message matches only if every named key is satisfied, and a key is satisfied if *any* of its rules match. A key absent from the envelope fails — which is why "assert this header is absent" needs its own explicit `exists: false` rule rather than falling out of the algebra.

One production detail that catches everyone: **envelope headers are strings on the wire.** A numeric rule must parse `"145000"` into a number before comparing, and if the producer ever emits `"1.45e5"` or `"145,000"` the comparison silently fails and the subscriber silently stops receiving. This is why brokers that offer numeric matching also make you *declare* the attribute's type, and why a schema for your envelope ([Lesson 12](../12-schema-evolution-and-event-contracts/)) is not bureaucracy.

### Where the filter runs — and why selectivity is a real number

You can filter in exactly two places, and it is a genuine engineering trade rather than an obvious win.

**Broker-side** filtering evaluates the predicate before delivery, so non-matching messages never enter the subscription's queue, cross the network, or wake the consumer. You save network bytes, consumer CPU and — often the biggest one — per-subscription *storage*, because a message never enqueued is never persisted. You pay in broker CPU: one predicate evaluation per subscription per message, on the hot path of the one component you cannot easily scale horizontally.

**Consumer-side** filtering delivers everything matching the subject and lets the consumer discard the rest. Broker CPU stays flat and the filter logic can be arbitrarily complex — real code, with access to the payload and a database. You pay in bandwidth, consumer CPU and per-subscription storage for messages that were always going to be thrown away.

The number that decides it is **selectivity**: the fraction of subject-matched messages that actually pass the filter. At 90% selectivity broker-side filtering gains almost nothing — you moved a cheap discard onto your least-scalable component. At 5% selectivity, 95% of everything that subscription receives is waste, multiplied by message size and message rate, every second, forever.

**A subscription that matches everything and discards 99% is not a subscription, it is a denial-of-service attack you are running against yourself.** The measured run below makes this concrete: a `vip-concierge` subscription that keeps 7.5% of what it subscribes to would be spending 92.5% of its bandwidth and CPU on messages destined for `del`.

### Fan-out amplification: one publish, N writes

Here is the cost model nobody sketches before the first incident. When a producer publishes one message to a topic with N subscriptions, the broker does **N writes**, not one. That single fact drives three separate amplifications:

- **Storage amplification.** Each durable subscription needs its own record that this message is pending for it. Whether the broker stores N full copies or one copy plus N reference-counted cursors is an implementation choice with a large constant factor attached, but the per-subscription *state* is unavoidable — that is what makes subscriptions independent.
- **Network amplification.** N deliveries leave the broker for every one that arrived. A 4 KB message at 10,000/s is 40 MB/s inbound; with eight subscriptions it is **320 MB/s outbound**, a 2.5 Gbps link doing nothing but fan-out. This is why brokers are far more often egress-bound than ingress-bound.
- **Write amplification on the hot path.** The publish is not acknowledged until the fan-out writes are durable, so publish latency scales with subscription count — meaning **adding a subscriber can slow down the producer**, a coupling most people assume they removed by going async.

Then the crucial qualifier: **the slowest subscriber does not slow the others — but only if each has independent buffering.** If subscriptions share a fixed-size buffer, a delivery thread, or a disk quota, one stuck subscriber's backlog is everyone's problem. Independence is not automatic; it is a property the broker has to be designed for, and worth confirming rather than assuming.

### Push or pull

One more design axis, because it interacts with everything above. Once the broker has a message for a subscription, who initiates the transfer?

**Push**: the broker sends to a registered endpoint or open connection as soon as the message arrives. Latency is minimal, but the broker must now track consumer liveness, handle a consumer that stops responding, and decide what to do about one slower than the publish rate. Push systems therefore need their own flow control — a credit or prefetch window, an outstanding-message limit — or the broker buffers unboundedly on behalf of a slow subscriber, which is Phase 9's unbounded-buffer failure in a new location.

**Pull**: the consumer asks for the next batch when it is ready. This is naturally backpressured — a busy consumer simply does not ask, and the backlog stays in the broker where it is visible, bounded and has a metric ([Lesson 9](../09-backpressure-lag-and-flow-control/) is entirely about that backlog). The cost is a little latency, since a message arriving just after a poll returns waits for the next one — which is what long-polling exists to reduce.

The rough rule: **push when latency dominates and consumers are reliably fast; pull when consumers are variable, bursty, or expensive to scale.** Pull is the safer default precisely because backpressure is the behaviour you get for free rather than the behaviour you have to remember to configure.

### Slow-consumer isolation, and the incident it causes

Now combine durability with fan-out and you get the production failure shape this lesson exists to warn you about.

A durable subscription whose consumer has stopped — crashed, deployed badly, stuck on a poison message, throttled by a downstream API — accumulates a backlog. That is exactly what durability is *for*, and for a ten-minute outage it is a feature. But the backlog is stored on the broker's disk, and the broker's disk is shared with every other subscription on that broker.

Do the arithmetic once and you will never skip the alarm again. A subscription 6 hours behind on a 5,000 msg/s topic with 1 KB messages is holding `5,000 × 3,600 × 6 = 108,000,000` messages, or **108 GB** of retained backlog. Nothing about that is unusual — a consumer that fails over a weekend is a two-day backlog. When that disk fills, the broker cannot accept publishes, and now *every producer and every subscription on the broker is down* because one team's consumer had a bad deploy. The blast radius of a single stuck subscriber is the entire broker.

This is why the operational checklist for a topic differs from a queue's. Per-subscription backlog and per-subscription **age of oldest unacknowledged message** must be monitored separately, with alerts owned by the team that owns the subscriber; aggregate topic-level metrics actively hide this failure, since total backlog looks fine when four subscriptions are at zero and the fifth is at 108 GB. And every durable subscription needs a **retention or expiry policy** — a maximum age or depth after which the broker discards deliberately, with a metric, rather than dying. The classic version is the abandoned subscription: someone prototypes a service, creates a durable subscription, deletes the service, and the subscription quietly retains every message until the disk fills months later.

### Ordering across a fan-out, and partial failure

Two consequences to name now and resolve later, because they are the seams where fan-out leaks.

**There is no global ordering across subscriptions.** Each progresses independently, so at any instant `shipping` may have processed message 500 while `analytics` is on 340. Within one subscription you can usually get per-key ordering; *across* subscriptions there is no meaningful "when" at all, so any logic of the form "analytics must have seen it by the time shipping acts" is a race no broker will save you from. This is Lamport's point in "Time, Clocks, and the Ordering of Events in a Distributed System" (CACM, 1978): absent communication between two parties there is no ordering relation between their events, only a partial order. [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/) covers what ordering you *can* buy and what it costs.

**Partial failure is now the normal case, not an edge case.** Subscriber A acks; subscriber B fails and is redelivered; subscriber C has been down for an hour. The publish succeeded, and the event is simultaneously fully processed, being retried, and not yet seen. There is no state in which "the OrderPlaced event was handled" is true or false — the question is malformed. That is the direct consequence of splitting one delivery state into N, and it is a *good* trade (it is what killed the dispatcher workaround), but every consumer must therefore be independently idempotent and independently retryable. [Lesson 6](../06-delivery-semantics-and-idempotency/) and [Lesson 8](../08-retries-backoff-and-dead-letter-queues/) are the two halves of that bill, and the second is why **each subscription needs its own dead-letter queue** — a poison message is poison to one subscriber's code, not to the topic.

### Two more things worth knowing exist

**Retained / last-value messages.** Some brokers keep the most recent message per subject and deliver it immediately to any *new* subscriber, so a subscriber connecting at 09:00 learns the current state rather than waiting for the next update. MQTT calls this the `RETAIN` flag; elsewhere it is a last-value cache or a compacted topic. It fixes "the state changes rarely and I just connected" — a device reporting its temperature hourly would otherwise leave a dashboard blank for 59 minutes. Note what it really is: a tiny key-value store bolted onto the topic, keyed by subject. Treat it as such, including for cleanup.

**Fan-out to a handful of services is a different problem from fan-out to a million browsers.** Everything above assumes tens of durable, service-shaped subscriptions. Fan-out to 100,000 WebSocket clients is a different discipline: hierarchical relay tiers, per-connection buffers with an explicit drop policy, conflation (send the newest value, not every value), and almost always ephemeral delivery, because durable per-connection state times a million connections is not a thing you want to own. If your fan-out target is measured in browsers rather than services, you want an edge fan-out tier subscribing to your broker — not a million broker subscriptions.

## Build It

`code/pubsub_broker.py` implements the topic, the subscription, the matcher, the filter, and the consumer, on a virtual clock with every RNG seeded. Standard library only. It reuses Lesson 3's lease/ack machinery rather than re-explaining it — the interesting part here is that each subscription owns a *separate instance* of that machinery.

The subject matcher is small enough to read completely, and it handles both dialects by giving each wildcard token its own minimum:

```python
MULTI = {"#": 0, ">": 1}          # multi-segment wildcard -> tokens it must consume


def _match(p: list[str], i: int, s: list[str], j: int) -> bool:
    while i < len(p):
        tok = p[i]
        if tok in MULTI:
            lo = MULTI[tok]
            if i == len(p) - 1:                       # terminal wildcard: swallow the rest
                return len(s) - j >= lo
            for k in range(lo, len(s) - j + 1):       # interior '#': try every split
                if _match(p, i + 1, s, j + k):
                    return True
            return False
        if j >= len(s) or (tok != "*" and tok != s[j]):
            return False
        i += 1
        j += 1
    return j == len(s)
```

The `lo` value is the entire AMQP-versus-NATS difference: `#` may consume zero tokens, `>` must consume at least one. The interior-`#` branch backtracks over every possible split, because `order.#.created` has to try consuming zero, one, or many tokens before it can decide.

`publish` is where fan-out amplification becomes visible — it is a loop, and the loop body is a write:

```python
def publish(self, msg: Message) -> None:
    """One publish; up to len(subscriptions) writes. This is the amplification."""
    self.published += 1
    self.published_bytes += msg.size
    for sub in self.subscriptions:
        if not subject_matches(sub.pattern, msg.subject):
            sub.stats.subject_miss += 1
            continue
        if sub.filt is not None:
            self.header_bytes_read += msg.header_bytes
            if not sub.filt.matches(msg.headers):
                sub.stats.filtered += 1
                continue
        if sub.offer(msg):
            self.fanout_writes += 1
            self.fanout_bytes += msg.size
```

Note what is counted and what is not. `header_bytes_read` accumulates on every filter evaluation; there is no code path anywhere that reads `msg.payload`, which is why the report can honestly print `0 B of payload`.

The durability difference lives in two short methods. `offer` is the broker deciding whether a copy exists at all, and `disconnect` is what a subscriber losing its connection actually costs:

```python
def offer(self, msg: Message) -> bool:
    """The fan-out write. Returns True if a copy was stored for this subscription."""
    if not self.durable and not self.attached:
        self.stats.lost += 1                       # Redis PUBLISH with nobody subscribed
        return False
    self.queue.append(msg)
    ...

def disconnect(self) -> None:
    if not self.durable:
        # No retained state: the queue evaporates, and an at-most-once consumer
        # loses whatever it was still holding. Nothing is redelivered.
        self.stats.lost += len(self.queue) + sum(len(c.holding) for c in self.consumers)
        self.queue.clear()
    for c in self.consumers:
        c.online = False
        c.holding = []                             # a crashed consumer acks nothing
        c.busy_until = 0.0
```

A durable subscription in the same situation keeps its queue untouched; its in-flight messages simply fail to be acked, their leases expire, and Lesson 3's redelivery path puts them back. The whole durable/ephemeral distinction is those four lines.

Run it:

```console
$ python pubsub_broker.py
== 1. SUBJECT MATCHING: '*' is one token, '#' is zero or more, '>' is one or more ==
  pattern            subject                        expect  got     why
  order.*.created    order.eu-west-1.created        True    True    '*' fills exactly one token
  order.*.created    order.created                  False   False   '*' cannot match zero tokens
  order.*.created    order.eu.west.created          False   False   '*' never crosses a dot
  order.*            order.eu.created               False   False   pattern is shorter than the subject
  *.eu-west-1.*      order.eu-west-1.created        True    True    wildcards anywhere, not just the tail
  order.#            order.eu-west-1.created        True    True    '#' swallows the remaining tokens
  order.#            order                          True    True    AMQP '#' matches ZERO tokens -- the classic surprise
  order.>            order                          False   False   NATS '>' needs at least one token. Same shape, different rule
  order.>            order.eu-west-1.created        True    True    '>' behaves like '#' once there is something to eat
  order.#.created    order.eu.west.created          True    True    an interior '#' is legal in AMQP
  order.#.created    order.created                  True    True    ...and matches zero tokens there too
  #                  payment.eu-west-1.captured     True    True    the firehose subscription
  order.#            payment.eu-west-1.captured     False   False   a different root never matches
  Order.#            order.eu-west-1.created        False   False   subjects are case-SENSITIVE
  order.*.created    order.eu-west-1.cancelled      False   False   literal tokens must match exactly
  15/15 cases agree with the specification
  rejected at subscribe time: '>' must be the final token: 'order.>.created'

== 2. ATTRIBUTE FILTERS: AND across keys, OR within a key, envelope only ==
  three envelopes under test (headers only -- no payload is ever read):
    A  high-value EU order   region=eu-west-1  tier=gold    amount_cents=145000  source=checkout-api
    B  small US order        region=us-east-1  tier=free    amount_cents=1299    source=batch-importer
    C  region/tier headers absent                                                source=checkout-api
  policy                                               A      B      C      rule
  {"region":["eu-west-1","eu-central-1"]}              MATCH  --     --     an OR list of exact values
  {"amount_cents":[{"numeric":[">=",50000]}]}          MATCH  --     --     numeric rule; header string is parsed
  {"amount_cents":[{"numeric":[">=",1000,"<",50000]}]} --     MATCH  --     a numeric range, both bounds
  {"tier":[{"anything-but":["free"]}]}                 MATCH  --     --     negation
  {"source":[{"prefix":"checkout-"}]}                  MATCH  --     MATCH  prefix match
  {"region":[{"exists":false}]}                        --     --     MATCH  assert a header is absent
  {"region":[{"prefix":"eu-"}],"tier":["gold"]}        MATCH  --     --     two keys -> both must pass
  every decision above read only the envelope; 0 bytes of payload were deserialized

== 3. FAN-OUT + COMPOSITION: 3 subscriptions, one of them load-balanced 3 ways ==
  published 24 messages to topic 'orders'  (10,430 bytes on the wire, once)
  subscription   pattern    cons  stored  deliv  redeliv  acked  dup  unique
  warehouse      order.#       1      24     24        0     24    0      24
  analytics      order.#       1      24     24        0     24    0      24
  email          order.#       3      24     24        0     24    0      24
  the 'email' subscription's three competing consumers split its 24 messages: email-1=9  email-2=5  email-3=10
  fan-out: 24 publishes -> 72 queue writes  (3.0x)   every subscription holds all 24, no subscription holds any twice

== 4. ISOLATION: one subscriber disconnects (durable vs ephemeral) ==
  published 60 messages over 0.60s; 'analytics' (durable) and 'live-dashboard' (ephemeral) were away from t=0.15s to t=0.45s
  30 messages were published during that window
    t (s)   warehouse   analytics   live-dashboard   backlog depth
    0.100           1           1                0
    0.200           1           7                0  <- away
    0.300           1          17                0  <- away
    0.400           1          27                0  <- away
    0.450           1          32                0
    0.500           1          29                0
    0.560           1          27                0
  subscription      durable  stored  redeliv  acked  LOST  peak backlog
  warehouse            True      60        0     60     0             2
  analytics            True      60        1     60     0            34
  live-dashboard      False      30        0     29    31             1
  drained at t=0.745s. Durable accounting: 60 acked + 0 lost = 60. Ephemeral accounting: 29 acked + 31 lost = 60.
  'warehouse' never noticed: peak backlog 2, acked 60/60 throughout.

== 5. AMPLIFICATION: what one publish costs, and what a filter saves ==
  published 200 messages, 85,146 bytes  (avg 426 B = 133 B envelope + ~293 B payload)
  subscription    pattern          subj-match  passed  select   stored B
  audit-archive   #                       200     200  100.0%     85,146
  search-index    order.*.created         112     112  100.0%     47,869
  gdpr-export     order.#                 200     103   51.5%     43,762
  fraud-review    order.#                 200      69   34.5%     29,687
  vip-concierge   order.#                 200      15    7.5%      6,530
  broker-side filtering :   499 deliveries     212,994 B   amplification 2.50x
  consumer-side filtering:   912 deliveries     388,453 B   amplification 4.56x
  moving the filter to the broker saved 175,459 B (45.2% of delivered bytes) and 413 deliveries
  it cost the broker 600 filter evaluations over 79,959 B of envelope -- and 0 B of payload, because filters never touch the body
  selectivity matters: 'vip-concierge' keeps 7.5% of what it subscribes to. Filtered at the consumer that is 92.5% wasted network and CPU.
```

**The matcher agrees with the specs on all fifteen cases, including the two that disagree with each other.** `order.#` matches the bare subject `order`; `order.>` does not. If you have ever migrated between brokers and found that one subject stopped routing, that row is why. The rejected pattern on the last line matters too: a broker that validates "`>` must be terminal" **at subscribe time** turns a silent routing hole into an immediate, loud error.

**Fan-out worked, and so did the composition.** Twenty-four publishes produced seventy-two queue writes, a clean 3.0×. Every subscription shows `acked 24` and `unique 24` with `dup 0`. Meanwhile the `email` subscription's three competing consumers split *its* twenty-four messages 9/5/10 — uneven because the consumers take 20 ms, 30 ms and 15 ms per message, so the fastest did roughly twice the work of the slowest. That is Lesson 3's competing consumers running unchanged *inside* one branch of a fan-out, and both invariants hold at once: **every subscription got everything, and within one subscription nobody did the same work twice.**

**Isolation is the section to read twice.** `analytics` and `live-dashboard` both went away for 300 ms, during which 30 messages were published. `analytics` climbs 1 → 7 → 17 → 27 → 32, peaks at **34**, then drains to zero by t=0.745s having acked **60 of 60 with zero loss**. It even shows `redeliv 1` — the message its consumer held when the connection dropped was never acked, so the lease expired and Lesson 3's redelivery path returned it to the queue.

`live-dashboard` ran through the identical outage and **lost 31 messages permanently**: the 30 published while it was away, plus the one its consumer was holding when it disconnected. Its backlog column reads `0` at every sample — not because it kept up, but because *there was never anything there to count*. **An ephemeral subscription's backlog metric is flat at zero whether it is perfectly healthy or losing every message.** The graph you would naturally build to detect this problem cannot detect this problem.

And `warehouse`, on the same topic over the same window, never noticed: peak backlog **2**, acked 60/60. That is subscription independence, measured.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Backlog depth over time for three subscriptions during a 300 millisecond subscriber outage. The healthy warehouse subscription stays at a backlog of one or two throughout. The durable analytics subscription climbs to a peak backlog of 34 while away, then drains to zero having acked all 60 messages with zero loss. The ephemeral live-dashboard subscription shows a backlog of zero at every sample yet permanently lost 31 messages, proving that a flat backlog metric cannot distinguish health from total loss.">
  <defs>
    <marker id="l04-iso-a" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One subscriber goes away for 300 ms — measured backlog, per subscription</text>

  <rect x="236" y="110" width="292" height="270" rx="6" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="6 5"/>
  <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
    <path d="M90 380 L 836 380"/>
    <path d="M90 380 L 90 120"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.28">
    <path d="M90 134 L 836 134"/>
    <path d="M90 199 L 836 199"/>
    <path d="M90 264 L 836 264"/>
    <path d="M90 329 L 836 329"/>
  </g>

  <path d="M187 373 L 236 373 L 285 329 L 382 257 L 479 185 L 528 149 L 545 134 L 577 170 L 635 185 L 720 285 L 815 380" fill="none" stroke="#3553ff" stroke-width="2.8"/>
  <path d="M187 373 L 285 373 L 382 366 L 479 373 L 577 373 L 635 373 L 736 373 L 815 380" fill="none" stroke="#0fa07f" stroke-width="2.8"/>
  <path d="M90 380 L 836 380" fill="none" stroke="#7c5cff" stroke-width="2.8" stroke-dasharray="7 5"/>
  <circle cx="545" cy="134" r="4" fill="#3553ff"/>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="72" y="138" font-size="9" text-anchor="end" opacity="0.8">34</text>
    <text x="72" y="203" font-size="9" text-anchor="end" opacity="0.8">26</text>
    <text x="72" y="268" font-size="9" text-anchor="end" opacity="0.8">17</text>
    <text x="72" y="333" font-size="9" text-anchor="end" opacity="0.8">9</text>
    <text x="72" y="384" font-size="9" text-anchor="end" opacity="0.8">0</text>
    <text x="40" y="256" font-size="9.5" text-anchor="middle" transform="rotate(-90 40 256)" opacity="0.9">backlog depth</text>
    <text x="236" y="398" font-size="9" text-anchor="middle" opacity="0.8">0.15s</text>
    <text x="528" y="398" font-size="9" text-anchor="middle" opacity="0.8">0.45s</text>
    <text x="815" y="398" font-size="9" text-anchor="middle" opacity="0.8">0.745s</text>
    <text x="382" y="398" font-size="9.5" text-anchor="middle" font-weight="700" fill="#e0930f">SUBSCRIBER AWAY — 30 messages published</text>
    <text x="440" y="416" font-size="9" text-anchor="middle" opacity="0.8">virtual time  ->  60 messages published over 0.60s, drained by 0.745s</text>

    <text x="560" y="128" font-size="9.5" font-weight="700" fill="#3553ff">peak 34</text>
    <text x="106" y="356" font-size="9" fill="#0fa07f" font-weight="700">warehouse — peak backlog 2, never noticed</text>
    <text x="600" y="200" font-size="9.5" fill="#3553ff" font-weight="700">analytics (DURABLE)</text>
    <text x="600" y="216" font-size="9" fill="#3553ff">catches up · acked 60/60 · LOST 0</text>
    <text x="600" y="232" font-size="9" fill="#3553ff">1 redelivery: the lease it held expired</text>
    <text x="240" y="360" font-size="9.5" fill="#7c5cff" font-weight="700">live-dashboard (EPHEMERAL) — backlog flat at 0 the entire run</text>

    <text x="440" y="440" font-size="10.5" text-anchor="middle" font-weight="700" fill="#7c5cff">...and it lost 31 of 60 messages. A flat backlog graph looks identical whether an ephemeral</text>
    <text x="440" y="458" font-size="10.5" text-anchor="middle" font-weight="700" fill="#7c5cff">subscription is perfectly healthy or dropping everything. Alarm on delivery, not on depth.</text>
  </g>
</svg>
```

**And the amplification is the number to take to a capacity review.** Two hundred messages, 85,146 bytes, went in. With filters evaluated at the broker, 499 deliveries and 212,994 bytes came out — **2.50× amplification**. With the identical subscriptions filtering at the consumer instead, 912 deliveries and 388,453 bytes — **4.56×**. Moving the predicate to the broker saved 175,459 bytes, **45.2% of all delivered bytes**, and 413 deliveries that would have been received and immediately discarded. It cost 600 filter evaluations over 79,959 bytes of envelope, and not a single byte of payload — the Lesson 2 envelope/body split paying for itself, with the broker never once having to know what an order looks like.

The per-subscription selectivity column is where the decisions live. `audit-archive` at 100% is legitimate: it subscribes to `#` and genuinely wants everything, so a broker-side filter buys it nothing. `vip-concierge` at **7.5%** is the opposite extreme — filtered at the consumer, 92.5% of everything it received would be waste. Same topic, same run, opposite correct answers, and selectivity is the number that tells you which is which.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="Fan-out amplification measured over 200 published messages totalling 85 kilobytes. Consumer-side filtering delivers 912 messages and 388 kilobytes, a 4.56 times amplification. Broker-side filtering delivers 499 messages and 213 kilobytes, a 2.50 times amplification, saving 45 percent of delivered bytes. Per-subscription selectivity ranges from 100 percent for the audit archive down to 7.5 percent for the VIP concierge subscription, which would waste 92.5 percent of its bandwidth if it filtered at the consumer.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One publish, N deliveries — 200 messages in, and what came out</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="200" y="66" width="123" height="34" rx="5" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <rect x="200" y="126" width="560" height="34" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="200" y="186" width="307" height="34" rx="5" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="507" y="186" width="253" height="34" rx="5" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 4"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="192" y="82" font-size="10" font-weight="700" text-anchor="end">PUBLISHED</text>
    <text x="192" y="96" font-size="8.5" text-anchor="end" opacity="0.8">200 msgs</text>
    <text x="333" y="88" font-size="10" font-weight="700" fill="#3553ff">85,146 B  ·  1.00x  ·  the bytes you actually sent</text>
    <text x="192" y="142" font-size="10" font-weight="700" text-anchor="end">CONSUMER-SIDE</text>
    <text x="192" y="156" font-size="8.5" text-anchor="end" opacity="0.8">filtering</text>
    <text x="440" y="148" font-size="11" font-weight="700" text-anchor="middle">912 deliveries  ·  388,453 B  ·  4.56x</text>
    <text x="192" y="202" font-size="10" font-weight="700" text-anchor="end">BROKER-SIDE</text>
    <text x="192" y="216" font-size="8.5" text-anchor="end" opacity="0.8">filtering</text>
    <text x="353" y="208" font-size="11" font-weight="700" text-anchor="middle">499  ·  212,994 B  ·  2.50x</text>
    <text x="633" y="203" font-size="9.5" text-anchor="middle" opacity="0.9">saved 175,459 B — 45.2%</text>
    <text x="633" y="217" font-size="9" text-anchor="middle" opacity="0.75">413 deliveries never sent</text>
    <text x="200" y="246" font-size="9.5" opacity="0.9">cost of moving the filter to the broker: 600 evaluations over 79,959 B of ENVELOPE — and 0 B of payload.</text>

    <text x="200" y="288" font-size="11.5" font-weight="700">Selectivity per subscription — the number that decides where the filter belongs</text>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.6">
    <rect x="330" y="302" width="300" height="20" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="330" y="330" width="300" height="20" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="330" y="358" width="155" height="20" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <rect x="330" y="386" width="104" height="20" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <rect x="330" y="414" width="23" height="20" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    <rect x="330" y="302" width="300" height="132" rx="0" fill="none" stroke="currentColor" stroke-opacity="0.25" stroke-dasharray="4 4"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="322" y="316" font-size="9.5" text-anchor="end">audit-archive</text>
    <text x="322" y="344" font-size="9.5" text-anchor="end">search-index</text>
    <text x="322" y="372" font-size="9.5" text-anchor="end">gdpr-export</text>
    <text x="322" y="400" font-size="9.5" text-anchor="end">fraud-review</text>
    <text x="322" y="428" font-size="9.5" text-anchor="end">vip-concierge</text>
    <text x="640" y="316" font-size="9.5" opacity="0.9">100%  — wants everything; broker filter buys nothing</text>
    <text x="640" y="344" font-size="9.5" opacity="0.9">100%  — narrowed by SUBJECT, not by filter</text>
    <text x="640" y="372" font-size="9.5" opacity="0.9">51.5% — worth filtering at the broker</text>
    <text x="640" y="400" font-size="9.5" opacity="0.9">34.5% — clearly worth it</text>
    <text x="640" y="428" font-size="9.5" font-weight="700" fill="#0fa07f">7.5%  — 92.5% waste if filtered at the consumer</text>
    <text x="440" y="464" font-size="10.5" text-anchor="middle" font-weight="700">A subscription that receives everything and discards 99% is a self-inflicted denial of service.</text>
  </g>
</svg>
```

## Use It

Every broker below implements the same three primitives — a topic, a subscription with its own delivery state, and a routing predicate. Learn to spot them and the vocabulary stops mattering.

**RabbitMQ** splits the topic into two objects, which is unusual and clarifying. Messages go to an **exchange**; queues **bind** to the exchange with a binding key; the exchange type is the routing algorithm. Crucially, **the subscription is the queue** — each bound queue is one independent subscription with its own durable storage and its own acks, and multiple consumers on that queue are the competing-consumers shape:

```bash
rabbitmqadmin declare exchange name=orders type=topic durable=true
rabbitmqadmin declare queue name=q.search  durable=true
rabbitmqadmin declare queue name=q.fraud   durable=true
# each binding is a subscription; each queue gets its own independent copy
rabbitmqadmin declare binding source=orders destination=q.search routing_key='order.#'
rabbitmqadmin declare binding source=orders destination=q.fraud  routing_key='order.*.created'
```

The four exchange types are the routing options in ascending order of cost: `fanout` ignores the key and copies to every bound queue; `direct` requires an exact key match; `topic` does the `*` / `#` matching you just implemented, with `#` as **zero or more** words exactly as the AMQP 0-9-1 spec defines it; and `headers` ignores the routing key and matches on message headers with `x-match=all|any` — AMQP's attribute filter, mapping directly onto the AND-across-keys / OR-within-a-key semantics above.

**AWS SNS → SQS** is the canonical durable fan-out topology, and it is worth understanding *why* it is two services. SNS (Simple Notification Service) is the topic and does the fan-out; SQS (Simple Queue Service) queues are the subscriptions and hold the durable per-subscriber state. The subscriber's own consumers then compete over its queue — the composition, in two managed services:

```bash
aws sns subscribe --topic-arn arn:aws:sns:eu-west-1:123:orders \
    --protocol sqs --notification-endpoint arn:aws:sqs:eu-west-1:123:q-fraud \
    --attributes '{"FilterPolicy": "{\"amount_cents\":[{\"numeric\":[\">=\",50000]}],\"region\":[{\"prefix\":\"eu-\"}]}"}'
```

That `FilterPolicy` is the attribute filter from Section 2, near-identically. Its default scope is `MessageAttributes` — the envelope — which is precisely the design argument made above; a `MessageBody` scope exists for when you need it and costs the broker exactly what you would expect. Subscribing SNS directly to Lambda or HTTPS instead gives you push delivery with no durable queue in between, and with it every slow-consumer problem described here.

**Google Cloud Pub/Sub** models it most explicitly: a **subscription is a first-class named resource** you create and manage separately, with its own filter, retention and dead-letter policy — and a delivery mode, which is the push/pull decision as a config field:

```bash
gcloud pubsub topics create orders
gcloud pubsub subscriptions create fraud-sub --topic=orders \
    --filter='attributes.region="eu-west-1" AND attributes.tier="gold"' \
    --ack-deadline=30 --message-retention-duration=7d       # pull: the consumer sets the pace
gcloud pubsub subscriptions create search-sub --topic=orders \
    --push-endpoint=https://search.internal/events           # push: low latency, broker tracks liveness
```

`--ack-deadline` is Lesson 3's lease, per subscription. `--message-retention-duration` is the bound on how far behind a stuck subscriber may fall before the broker starts discarding — the answer to the 108 GB problem.

**NATS** is the cleanest illustration of the durable/ephemeral split, because it ships both in one system. Core NATS is pure ephemeral pub/sub: subjects with `*` and `>` wildcards, at-most-once, no storage, and if no subscriber is listening the message is gone. **JetStream** adds a persistence layer on top with durable consumers, acks, and replay:

```bash
nats sub 'order.*.created'      # core: ephemeral. Disconnect and you miss what happened.
nats sub 'order.>'              # '>' is one-or-more and must be the final token
nats stream add ORDERS --subjects 'order.>' --storage file --retention limits
nats consumer add ORDERS fraud --filter 'order.*.created' --ack explicit   # durable subscription
```

Same subjects, same wildcards, same broker — and the single decision of whether you `sub` or add a durable consumer is the entire difference between losing 31 messages and losing 0.

**MQTT** uses `/`-separated topic filters with `+` for one level and `#` for the remainder (which must be last, and matches the parent level). Its `RETAIN` flag is the retained-message feature, and its "clean session" / "persistent session" flag is the durable-versus-ephemeral choice made per client connection — a device that reconnects with a persistent session receives what it missed at its configured QoS level.

**Redis pub/sub** is the pure-ephemeral case, and the one to know the caveat for:

```bash
SUBSCRIBE order.created          # exact channel
PSUBSCRIBE 'order.*'             # glob patterns, not the hierarchy above
PUBLISH order.created '{"id":"ord_1"}'      # -> (integer) 2 : delivered to 2 clients. Or 0.
```

There is no queue, no acknowledgement and no retention: `PUBLISH` delivers to currently-connected subscribers and returns the count. If that count is `0`, the message is gone and nothing records that it existed — fine for cache invalidation and live counters, completely wrong for anything that drives state, and a leading cause of "we lost events and we don't know why". Redis's own answer when you need durability is **Streams** (`XADD` / `XREADGROUP`), which is the log shape — the next lesson.

**Kafka** reaches the same fan-out from a different direction and deserves one paragraph, not more. It has no per-subscription queues at all: it retains one shared, ordered log and lets each **consumer group** track its own offset into it. Every group independently reads every message — the fan-out — and consumers *within* a group split the partitions between them — the load balancing. Same composition, achieved by making subscriptions cursors over shared storage rather than independent copies, and that single change alters the cost model completely: fan-out becomes nearly free (N readers, one copy on disk, no storage amplification), and replay becomes possible because the messages are still there after they have been read. That is [Lesson 5](../05-the-log-offsets-and-replay/), the third and last broker shape.

## Think about it

1. A topic has eight subscriptions. One team asks to add a ninth for a new service, and the change is "just one API call". Name three distinct costs that ninth subscription imposes on the *existing* eight and on the producer — and say which of the three the producer will notice first, and how.

2. Your `live-dashboard` subscription is ephemeral, its backlog graph has read a perfectly flat zero for six months, and the team is proud of it. Using the measured run, explain why that graph is worthless as a health signal, and design the metric you would alarm on instead. (Hint: the broker knows something at publish time that the subscriber never learns.)

3. A subscription filters `amount_cents >= 50000` and matches 7.5% of the topic. A second subscription filters `region != "antarctica"` and matches 99.9%. Both are currently filtering at the consumer. You have budget to move exactly one to broker-side filtering. Which, and roughly what do you save — and what would change your answer if the broker were already CPU-saturated?

4. `shipping` acks an `OrderPlaced`, `fraud` is retrying it, and `analytics` has been down for an hour. A support engineer asks: "has order 4471 been processed?" Explain why the question has no answer, what you would put on a status page instead, and what this implies about where the *user-visible* order state must actually live.

5. Your broker's disk is at 94% and climbing. You discover one subscription named `test-sub-2` created eleven months ago by an engineer who has since left, retaining every message on the busiest topic in the company. Beyond deleting it: name the two policies that would have made this impossible, and the one metric that would have caught it in week one.

6. A colleague proposes replacing your five-subscription fan-out with one subscription consumed by a dispatcher service that forwards to the five, "to cut broker costs by 80%". The storage argument is arithmetically correct. Give the two-part reason this is still wrong, using the acknowledgement ambiguity from The Problem — and name the one situation in which they would actually be right.

## Key takeaways

- A **queue** is *competing consumers over one message set* — each message to exactly one consumer, adding consumers divides the work, and it answers "who does this job?". A **topic** is *independent delivery of every message to every subscription* — adding subscriptions multiplies the work, and it answers "who needs to know?". Commands go on queues; events go on topics.
- **The subscription is the unit of fan-out, not the consumer.** Each subscription owns a queue, a cursor, and its own acknowledgement state, which is why five subscribers can sit at five different positions and why one's failure cannot affect another's. Delivery state must be per-recipient or it cannot be correct — that is exactly what kills the "one dispatcher forwards to five" design, which holds a single ack for five independent outcomes and must therefore either lose messages or duplicate them.
- **The two shapes compose**: fan out *across* subscriptions, load-balance *within* one. The measured run shows three subscriptions each receiving all 24 messages (72 queue writes, 3.0× fan-out, zero duplicates) while one of them split its own 24 across three competing consumers 9/5/10 — uneven because the consumers were 20 ms, 30 ms and 15 ms per message, which is competing consumers working correctly.
- **Durable versus ephemeral is the choice that decides your on-call life.** Durable retains messages for an absent subscriber (at-least-once, plus a backlog you must bound); ephemeral drops them (at-most-once, no state, no backlog). Over the same 300 ms outage the durable subscription caught up with **0 lost** and the ephemeral one lost **31 of 60** — and the ephemeral subscription's backlog metric read **zero at every sample**, identical to perfect health. If the message drives state, it must be durable.
- **Routing is subjects plus attributes.** Hierarchical subjects with `*` (exactly one token) and a multi-segment wildcard handle structural narrowing; put the most-filtered-on dimension leftmost and keep segment cardinality bounded. The specs genuinely disagree on the multi-segment wildcard: AMQP 0-9-1's `#` matches **zero or more** words (so `order.#` matches bare `order`), NATS's `>` matches **one or more** and must be terminal (so `order.>` does not). That difference survives a broker migration undetected.
- **Attribute filters belong on the envelope, not the payload.** A broker that filters on headers parses a small flat map it already read; one that filters on bodies must deserialize your payload once per subscription on the hot path, learn your serialization format, and let a schema change break routing. The measured run made 600 filter decisions reading 79,959 bytes of envelope and **0 bytes of payload**. Remember that header values are strings on the wire — numeric rules parse, and an unexpected format fails silently.
- **Fan-out amplification is real arithmetic: one publish, N writes.** It hits storage, network (a 4 KB message at 10,000/s with eight subscriptions is 320 MB/s of egress), and publish latency — so adding a subscriber can slow the producer. Filter selectivity is the lever: broker-side filtering measured **2.50×** amplification against **4.56×** for the same subscriptions filtering at the consumer, saving 45.2% of delivered bytes. A subscription keeping 7.5% of what it receives wastes 92.5% of its bandwidth; one keeping 100% gains nothing from a broker-side filter.
- **Subscribers are isolated only if their buffering is.** A stuck durable subscription is a growing backlog on the broker's shared disk — 6 hours behind on 5,000 msg/s of 1 KB messages is 108 GB — and when that disk fills, every producer and every subscription on the broker goes down. Monitor backlog **and age of oldest unacked message per subscription**, never in aggregate; give every subscription a retention bound, its own dead-letter queue, and an owner.
- **Fan-out breaks two things you may still be assuming.** There is no ordering across subscriptions — only a partial order, per Lamport (CACM, 1978) — so "analytics has seen it by the time shipping acts" is a race. And partial failure is the normal state: one subscriber acked, one retrying, one down, all simultaneously, which makes "was this event processed?" a malformed question and makes independent idempotency the entry fee for every consumer.

Next: [The Log: Offsets, Replay & Retention](../05-the-log-offsets-and-replay/) — the third broker shape, where the subscriptions stop being copies and become cursors over one retained, ordered log, fan-out gets almost free, and for the first time you can read a message that was already delivered.
