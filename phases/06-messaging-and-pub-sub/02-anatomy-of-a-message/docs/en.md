# Anatomy of a Message: Envelope, Payload & Serialization

> Lesson 1 established that a message is the only thing a producer and a consumer share. That is a much sharper constraint than it sounds: two services, possibly written by different teams in different languages and deployed years apart, must agree on a sequence of bytes — and on nothing else. No shared types, no shared memory, no chance to ask a follow-up question. This lesson dissects that sequence of bytes: the envelope the broker reads, the payload it must never open, and a serialization decision that is measured here at a 4x difference in your bandwidth bill.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Async? Coupling and the Cost of the Direct Call](../01-why-async-and-the-cost-of-coupling/)
**Time:** ~65 minutes

## The Problem

You have accepted the argument from Lesson 1. `orders` will stop calling `email` directly and publish a message instead. So you sit down to write the publish call, and immediately face a question the synchronous version never asked: **what, exactly, goes on the wire?**

In a direct HTTP (HyperText Transfer Protocol) call, you and the callee shared a live connection and a request/response contract you could version behind a URL. Now there is no connection. There is a byte string, written by a process that has already moved on, read by a process that may not exist yet, possibly minutes later, possibly after a replay of last Tuesday's traffic. Every assumption you fail to write into those bytes is an assumption the consumer will get wrong.

Here is the naive path, and it fails three times in a row. The program at the end of this lesson runs all three; these are its real numbers.

**Failure one: you send your language's memory layout.** The order is a `dict`, so you send `str(order)` — 105 bytes, and it looks like JSON (JavaScript Object Notation) if you squint. It is not. It has single quotes, `True` instead of `true`, and `None` instead of `null`. A Go or TypeScript consumer trying to parse it fails at column 2. You have not chosen a format; you have shipped Python's `repr`, which is a debugging aid with no specification, no versioning story, and no other implementation.

**Failure two: you reach for the language's own serializer.** Python has `pickle`, Java has `Serializable`, .NET has `BinaryFormatter`. `pickle.dumps` produces 104 bytes — *six bytes larger* than the equivalent JSON, so you did not even get compactness. What you did get is a format only Python can read, that encodes class identity so a refactor breaks old messages, and that is a **remote code execution vector**. Pickle's wire format includes opcodes that call arbitrary importable functions; a 43-byte "message" in the run below executes attacker-chosen code the moment `pickle.loads` touches it. Not on validation failure — on *load*. In a system whose entire premise is accepting bytes from elsewhere, this is disqualifying. Language-native serializers are for a process talking to its own disk, never for a wire between services.

**Failure three, the subtle one: you fix the format and still lose.** So you switch to JSON and send `{"order_id": "...", "amount": 4299}`. Correct, portable, readable. And every one of the following now happens to you, in roughly this order, over the following eighteen months:

- **No message id.** The broker redelivers a message after a consumer crash — which Lesson 6 will show is not an edge case but the *normal* behaviour of at-least-once delivery. Your payments consumer has no way to know it has seen this exact message before, so it charges the customer twice. There is no field to deduplicate on.
- **No timestamp.** An incident forces you to replay yesterday's events. The consumers cannot distinguish a replayed order from a live one, so the warehouse picks 40,000 orders that shipped a day ago. Worse, you cannot even ask "how long did this sit in the queue?", because nothing in the message records when the fact happened versus when it was delivered.
- **No type.** One queue now carries orders, refunds, and cancellations, because someone reused it. The consumer's only way to tell them apart is to parse the body and guess from which fields are present. Routing has become schema archaeology.
- **No version.** You add a required field to the order body. Every consumer deploys at a different time. The ones running yesterday's code hit the new shape and crash — all of them, simultaneously, with no way to say "this message is v2, and I only speak v1."
- **No trace context.** Your tracing works beautifully right up to the publish call and resumes nowhere. The async hop is a black hole. "Why didn't this customer get their email?" — which Lesson 1 promised would become a distributed-tracing investigation — is now not investigable at all, because the trace ended at the broker.

Notice what these five have in common. Not one of them is about the *order*. The order data was fine the whole time. Every failure is about missing **metadata about the message itself** — and that observation is the entire lesson.

## The Concept

### Envelope and payload: two different things with two different owners

A message has exactly two parts, and confusing them is the root cause of most bad message designs.

The **payload** (or **body**) is the business fact: the order, the amount, the line items. It belongs to the domain. Its shape is agreed between the producing team and the consuming teams, it changes when the business changes, and it is the thing your application code actually cares about.

The **envelope** is metadata *about the message*, not about the order. The id, the timestamps, the type, the trace context. It belongs to the **infrastructure**. It is the same set of fields whether the message carries an order, a refund, or a password reset, and it is what lets generic machinery — brokers, routers, retry handlers, dead-letter processors, audit loggers, tracing systems — do their jobs without knowing anything about your domain.

The postal metaphor is exactly right and worth taking literally. The postal service reads the envelope: the address, the postmark, the tracking barcode. It routes, deduplicates, retries, and delivers using only that. It does not open the letter — it *cannot* open the letter, and that is a feature, not a limitation. The recipient opens the letter.

This split is not stylistic. It buys three concrete things:

**Routing without parsing.** A broker deciding where a message goes should never deserialize the body. Parsing is the expensive part of message handling, and a broker moving a million messages a second cannot afford to parse a million bodies to learn which topic they belong to. Put the routing key in the envelope and the decision is a byte comparison on a field the broker already has.

**A security boundary.** The body may be encrypted, may be a format the broker has no parser for, or may be actively hostile. Every check that runs on envelope fields is a check that happens *before* untrusted bytes reach a parser. In the program below, six malformed messages are rejected and **the body is never parsed in any of the six cases** — that is the boundary working.

**Independent evolution.** The body's schema is versioned by the domain team on their schedule. The envelope's shape is set by your platform and changes almost never. Because the envelope declares `schema_version` and `content_type`, the body can change format entirely — JSON to Protobuf, v1 to v2 — without a single change to the broker, the router, or the retry logic.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="A message split into envelope and payload. The broker, the router and the dead-letter handler read only the 124-byte envelope and route, deduplicate and trace without ever parsing the body. Only the consumer deserializes the 81-byte payload, so parsing untrusted bytes happens exactly once, behind validation.">
  <defs>
    <marker id="l02-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One message, two parts, two audiences</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="48" width="800" height="152" rx="14" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="7 6"/>
    <rect x="62" y="80" width="756" height="60" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="62" y="148" width="756" height="40" rx="10" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M180 140 L 180 268" marker-end="url(#l02-arrow)"/>
    <path d="M440 140 L 440 268" marker-end="url(#l02-arrow)"/>
    <path d="M700 140 L 700 268" marker-end="url(#l02-arrow)"/>
    <path d="M780 188 L 780 232 L 700 232"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="6 5">
    <path d="M300 168 L 300 236"/>
    <path d="M560 168 L 560 236"/>
  </g>
  <g stroke="#e0930f" stroke-width="2.2" fill="none">
    <path d="M292 196 L 308 212"/><path d="M308 196 L 292 212"/>
    <path d="M552 196 L 568 212"/><path d="M568 196 L 552 212"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="60" y="272" width="240" height="118" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="320" y="272" width="240" height="118" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="580" y="272" width="240" height="118" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="76" y="70" font-size="10" opacity="0.8">ONE MESSAGE ON THE WIRE — 205 bytes, schema-ful binary encoding</text>
    <text x="80" y="102" font-size="11.5" font-weight="700" fill="#3553ff">ENVELOPE — 124 B — infrastructure metadata</text>
    <text x="80" y="120" font-size="9" opacity="0.9">message_id · correlation_id · causation_id · type · schema_version · source</text>
    <text x="80" y="134" font-size="9" opacity="0.9">occurred_at · published_at · recorded_at · content_type · traceparent · partition_key · crc32</text>
    <text x="80" y="166" font-size="11.5" font-weight="700" fill="#7c5cff">PAYLOAD — 81 B — the business fact</text>
    <text x="80" y="182" font-size="9" opacity="0.9">order_id · customer_id · currency · amount_minor · items[]   — opaque bytes to everything above</text>

    <text x="180" y="296" font-size="11" font-weight="700" text-anchor="middle">BROKER</text>
    <text x="180" y="316" font-size="9" text-anchor="middle" opacity="0.9">routes on `type`</text>
    <text x="180" y="331" font-size="9" text-anchor="middle" opacity="0.9">orders by partition_key</text>
    <text x="180" y="346" font-size="9" text-anchor="middle" opacity="0.9">dedups on message_id</text>
    <text x="180" y="361" font-size="9" text-anchor="middle" opacity="0.9">stamps recorded_at</text>
    <text x="180" y="380" font-size="9" text-anchor="middle" font-weight="700" fill="#3553ff">never parses the body</text>

    <text x="440" y="296" font-size="11" font-weight="700" text-anchor="middle">GENERIC MIDDLEWARE</text>
    <text x="440" y="316" font-size="9" text-anchor="middle" opacity="0.9">filters on headers</text>
    <text x="440" y="331" font-size="9" text-anchor="middle" opacity="0.9">continues the trace</text>
    <text x="440" y="346" font-size="9" text-anchor="middle" opacity="0.9">retries, dead-letters</text>
    <text x="440" y="361" font-size="9" text-anchor="middle" opacity="0.9">audits, meters, bills</text>
    <text x="440" y="380" font-size="9" text-anchor="middle" font-weight="700" fill="#3553ff">cannot parse the body</text>

    <text x="700" y="296" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">CONSUMER</text>
    <text x="700" y="316" font-size="9" text-anchor="middle" opacity="0.9">1. validate the envelope</text>
    <text x="700" y="331" font-size="9" text-anchor="middle" opacity="0.9">2. check content_type</text>
    <text x="700" y="346" font-size="9" text-anchor="middle" opacity="0.9">3. check schema_version</text>
    <text x="700" y="361" font-size="9" text-anchor="middle" opacity="0.9">4. THEN deserialize</text>
    <text x="700" y="380" font-size="9" text-anchor="middle" font-weight="700" fill="#0fa07f">the only parser on the path</text>

    <text x="300" y="256" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">no parse</text>
    <text x="560" y="256" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">no parse</text>

    <text x="440" y="428" font-size="10.5" text-anchor="middle" opacity="0.95">Every routing, retry, ordering and observability decision is answerable from the envelope alone.</text>
    <text x="440" y="448" font-size="10" text-anchor="middle" opacity="0.85">That is a performance boundary — a broker cannot afford a million parses a second — and a security</text>
    <text x="440" y="464" font-size="10" text-anchor="middle" opacity="0.85">boundary: in the measured run, six malformed messages were rejected and none of the six bodies was parsed.</text>
    <text x="440" y="486" font-size="9.5" text-anchor="middle" opacity="0.7">Corollary: if you need it to route, filter or alert, it belongs in the envelope — not buried in the body.</text>
  </g>
</svg>
```

### The envelope fields, and the failure each one prevents

Design the envelope by working backwards from failures. Every field below exists because a specific production incident happens without it.

| Field | What it is | The failure it prevents |
|---|---|---|
| `message_id` | A UUID, unique per message | A redelivery is indistinguishable from a new event, so the retry double-charges |
| `correlation_id` | One id for the whole business transaction | You cannot gather the twelve messages that belong to one checkout |
| `causation_id` | The id of the **immediate parent** message | You have a bag of related messages but no idea what caused what |
| `type` | What happened, e.g. `com.shop.order.placed` | The consumer guesses the message's meaning from the body's shape |
| `schema_version` | Version of the **body** | One schema change breaks every consumer simultaneously |
| `source` | Which service published it | Nobody knows who to page when the payload is wrong |
| `occurred_at` | When the fact happened (**event time**) | You cannot tell a replay from a live event |
| `published_at` | When the producer sent it (**processing time**) | Producer-side lag is invisible |
| `recorded_at` | When the broker durably accepted it | Broker-side lag is invisible; no trustworthy clock anywhere |
| `content_type` | How to parse the body | The consumer must sniff the format |
| `content_encoding` | `identity`, `deflate`, `gzip` | Compressed bodies are handed to a JSON parser |
| `traceparent` | W3C Trace Context | The async hop is a black hole in your traces |
| `partition_key` | The ordering scope | Related events are processed out of order (Lesson 7) |
| `crc32` / digest | Integrity check over the body | Truncation and corruption are applied instead of detected |

Four of these deserve more than a table row.

**`message_id` and why UUID version matters.** The id must be globally unique and generated by the *producer*, before the send, so that a retried send carries the **same** id — an id generated per network attempt deduplicates nothing. The canonical format is the UUID (Universally Unique Identifier) of **RFC 4122**, now obsoleted and updated by **RFC 9562** (2024). Version 4 — 122 random bits — is the default and is what the code below generates. But for a message id there is a strictly better choice worth knowing: **UUIDv7**, standardized in RFC 9562, prefixes a 48-bit Unix millisecond timestamp before the random bits, so ids sort by creation time. Your deduplication table is an index keyed on `message_id`; with v4 every insert lands at a random point in the B-tree and your working set is the whole index, which is exactly the write-amplification problem from Phase 3. With v7, inserts are append-mostly and expiring old entries is a range delete. Same uniqueness, dramatically better locality.

**`correlation_id` versus `causation_id` — the distinction everyone muddles.** These are *not* two names for the same thing, and teams that treat them as interchangeable lose the more valuable one.

- **Correlation id** answers *"which business transaction is this part of?"* It is created once at the start — the user clicking Place Order — and copied unchanged onto every message that results, however many hops deep. All twelve messages from one checkout share one correlation id.
- **Causation id** answers *"which single message caused this one?"* It is the `message_id` of the **immediate parent**, and it therefore changes at every hop.

Correlation gives you a *set*. Causation gives you *edges*, and a set plus edges is a tree. With only correlation you can gather the twelve messages of a checkout and see that one of them is missing; you cannot see *which branch* died, or that `shipment.requested` was caused by `payment.authorized` rather than directly by `order.placed`. With causation you reconstruct the causal tree exactly — and a message whose `causation_id` names no message you have is an **orphan**, a one-join consistency check that finds lost publishes. The rule when publishing is two lines long: **copy the incoming `correlation_id` unchanged; set `causation_id` to the incoming `message_id`.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Correlation identifiers alone produce a flat bag of six messages sharing one id, which shows that something is missing but not where. Adding causation identifiers, each naming the immediate parent message, reconstructs the causal tree with edges, revealing which branch stopped and which messages are orphans.">
  <defs>
    <marker id="l02-arrow2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Correlation gives you a set. Causation gives you the edges.</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="410" height="356" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="454" y="44" width="410" height="356" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="44" y="130" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="232" y="130" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="44" y="180" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="232" y="180" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="44" y="230" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="232" y="230" width="164" height="34" rx="8" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="480" y="112" width="192" height="30" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="510" y="158" width="192" height="30" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="540" y="204" width="192" height="30" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="570" y="250" width="192" height="30" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="570" y="296" width="192" height="30" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="540" y="342" width="192" height="30" rx="8" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M492 142 L 492 173 L 505 173" marker-end="url(#l02-arrow2)"/>
    <path d="M522 188 L 522 219 L 535 219" marker-end="url(#l02-arrow2)"/>
    <path d="M552 234 L 552 265 L 565 265" marker-end="url(#l02-arrow2)"/>
    <path d="M552 234 L 552 311 L 565 311" marker-end="url(#l02-arrow2)"/>
    <path d="M522 188 L 522 357 L 535 357" marker-end="url(#l02-arrow2)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="70" font-size="12" font-weight="700" fill="#e0930f">CORRELATION ONLY</text>
    <text x="34" y="90" font-size="9.5" opacity="0.85">every message carries correlation_id = 82a0a2b2</text>
    <text x="34" y="106" font-size="9.5" opacity="0.85">...and nothing else linking them</text>
    <text x="126" y="152" font-size="9" text-anchor="middle">checkout.requested</text>
    <text x="314" y="152" font-size="9" text-anchor="middle">order.placed</text>
    <text x="126" y="202" font-size="9" text-anchor="middle">payment.authorized</text>
    <text x="314" y="202" font-size="9" text-anchor="middle">inventory.reserved</text>
    <text x="126" y="252" font-size="9" text-anchor="middle">shipment.requested</text>
    <text x="314" y="252" font-size="9" text-anchor="middle">receipt.emailed</text>
    <text x="221" y="300" font-size="10" text-anchor="middle" font-weight="700">a BAG of 6 messages</text>
    <text x="221" y="322" font-size="9.5" text-anchor="middle" opacity="0.9">You can answer: "did all six arrive?"</text>
    <text x="221" y="342" font-size="9.5" text-anchor="middle" opacity="0.9">You cannot answer: "which branch died?"</text>
    <text x="221" y="362" font-size="9.5" text-anchor="middle" opacity="0.9">or "what caused the shipment request?"</text>
    <text x="221" y="384" font-size="9.5" text-anchor="middle" font-weight="700" fill="#e0930f">order is guessed from timestamps</text>

    <text x="472" y="70" font-size="12" font-weight="700" fill="#0fa07f">+ CAUSATION</text>
    <text x="472" y="90" font-size="9.5" opacity="0.85">causation_id = the parent's message_id, per hop</text>
    <text x="576" y="132" font-size="9" text-anchor="middle">checkout.requested  t+0ms</text>
    <text x="606" y="178" font-size="9" text-anchor="middle">order.placed  t+41ms</text>
    <text x="636" y="224" font-size="9" text-anchor="middle">payment.authorized  t+82ms</text>
    <text x="666" y="270" font-size="9" text-anchor="middle">shipment.requested t+164ms</text>
    <text x="666" y="316" font-size="9" text-anchor="middle">receipt.emailed  t+205ms</text>
    <text x="636" y="362" font-size="9" text-anchor="middle">inventory.reserved t+123ms</text>
    <text x="659" y="392" font-size="9.5" text-anchor="middle" font-weight="700" fill="#0fa07f">a TREE — the edges are data, not inference</text>

    <text x="440" y="424" font-size="10.5" text-anchor="middle" opacity="0.95">Publishing rule, two lines: copy the incoming correlation_id unchanged; set causation_id = the incoming message_id.</text>
    <text x="440" y="444" font-size="10" text-anchor="middle" opacity="0.85">A message whose causation_id names no message you hold is an ORPHAN — its parent was lost. One join finds every one of them.</text>
    <text x="440" y="462" font-size="9.5" text-anchor="middle" opacity="0.7">This is the message-layer twin of Phase 9's span/parent-span relationship, and it survives when the trace is sampled away.</text>
  </g>
</svg>
```

**Three timestamps, because one is a lie.** Beginners put `timestamp` in the envelope and move on. Then they discover that "when" has at least three answers, and conflating them makes whole classes of question unanswerable:

- **`occurred_at` — event time.** When the fact happened in the world. The customer clicked Place Order at 14:32:07.412. This is a property of the *event*, it never changes, and it is what business logic and analytics must use.
- **`published_at` — processing time (producer side).** When the producer actually got the message onto the wire. Usually milliseconds after `occurred_at`; occasionally hours, if the producer was down, retrying, or draining an outbox (Lesson 10).
- **`recorded_at` — broker time.** When the broker durably accepted it. Stamped by the *broker*, not the producer, which makes it the only timestamp you can trust when producers have skewed clocks — and producers always have skewed clocks.

The gap between event time and processing time is the central problem of stream processing. A mobile app that was offline for six hours uploads events with an `occurred_at` of this morning and a `published_at` of now. If your hourly revenue aggregation buckets by processing time, this morning's revenue lands in the current hour and both hours are wrong forever. Bucket by event time and the numbers are right — but now you face the question event-time processing always raises: *how long do you wait for stragglers before closing the 09:00 bucket?* That is what **watermarks** are, and they exist because these two timestamps are different. Lesson 5 returns to this. For now, the design rule is simply: **carry all three, label them unambiguously, and never name a field just `timestamp`.**

The program below encodes `published_at` and `recorded_at` as *deltas* from `occurred_at` in the binary format, which costs 3 bytes each instead of 32 — a nice demonstration that a schema lets you exploit correlations between fields that a self-describing format cannot see.

**`traceparent`, and why the async hop is where tracing dies.** Phase 9 Lesson 3 established that a trace survives a service boundary only if the trace context is *propagated* — in HTTP, as headers. The **W3C Trace Context** recommendation defines `traceparent` as four hyphen-separated fields: version, a 16-byte trace id, an 8-byte parent span id, and trace flags — `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`. Messaging needs precisely the same propagation, with one twist: the "parent" is a span that ended long before the consumer starts, so the consumer's span links back across time. Every mainstream broker now has a headers mechanism specifically so `traceparent` has somewhere to live. If you carry one field from this section into your next design review, carry this one: **an event-driven system without trace propagation through the message envelope is a system you cannot debug.**

### Headers versus body: routing must never require a parse

Sharpen the envelope/payload split into an operational rule: **any decision made by anything other than the final consumer must be answerable from the envelope alone.**

Concretely, if you find yourself wanting to route on the order's currency, filter on the customer's tier, or alert on the payment amount, you have a choice. Either the broker parses every body — unacceptable — or that field is *promoted* into the envelope as a header. Promotion is the right answer, with a cost: promoted fields are now part of your infrastructure contract, they duplicate data that also lives in the body (and can drift from it), and each one enlarges every message. Promote deliberately and sparingly. AMQP's `headers` table, Kafka's record headers, and SQS's message attributes all exist exactly for this.

The security half is stronger still. **Validate the envelope before the body is touched by a parser.** Reject unknown `content_type` values against an allowlist, reject `schema_version` values you do not speak, reject oversized bodies before allocating a buffer for them, and verify a digest before parsing. Each of these is cheap, and each stops hostile input at a boundary where nothing complicated is running yet. Compare with the pickle failure: there, "parse" and "execute" were the same operation, so no amount of post-parse validation could have helped.

### The real serialization decision: two axes, not a list of names

People ask "JSON or Protobuf?" as if picking from a menu. The useful framing is two independent axes.

**Axis 1 — text or binary?** Text (JSON, XML) is human-readable, greppable, debuggable with `curl`, and universally supported. Binary (MessagePack, CBOR, Protobuf, Avro) is smaller and faster to parse, and requires tooling to inspect. The real cost of text is not just size: it is that numbers, timestamps, and byte strings all have to be *re-encoded as characters* and parsed back, and that binary data cannot be carried at all without base64, measured below at a flat +33%.

**Axis 2 — self-describing or schema-required?** A **self-describing** format carries its field names inside every message; a consumer can parse it knowing nothing in advance. A **schema-required** format assumes both sides hold a schema that maps field *numbers* to names and types, so the wire carries only numbers and values. Self-describing costs bytes on every message forever and lets you add fields with zero coordination. Schema-required is dramatically smaller and strictly typed, but demands a **schema registry** — a place both sides fetch the schema from — and a compatibility discipline, which is all of Lesson 12.

Everything else follows from where you sit on those two axes.

- **JSON** (RFC 8259) — text, self-describing. Ubiquitous, and the correct default for public APIs, webhooks, and anything a human will debug at 3 a.m. Verbose, no native schema, no byte type. Its sharpest trap is **numbers**: JSON does not specify a numeric range, and the overwhelmingly common implementation choice is IEEE 754 binary64, so integers above 2^53−1 (9,007,199,254,740,991) silently lose precision in JavaScript and in many JSON libraries. A 64-bit database id or a Snowflake-style id **will** be corrupted in transit. The fix is to carry such ids as strings; RFC 8259 itself notes that interoperability is only assured within the range representable by a double.
- **MessagePack / CBOR** — binary, self-describing. The same data model as JSON with a compact binary framing; **CBOR** is the IETF standard version (**RFC 8949**) and supports byte strings natively, so no base64 tax. Measured below at 83.5% of JSON: a real but modest win, because the field names are still on the wire.
- **Protobuf / Avro / Thrift** — binary, schema-required. Field names collapse to varint tags, enums to small integers, and a UUID to 16 raw bytes instead of 36 characters. Measured below at 25.2% of JSON. **Avro** is worth distinguishing: it writes *no* per-field tags at all, relying on the reader having the exact writer schema, which makes it the most compact and the most registry-dependent of the three — a natural fit for Kafka, where a schema id is written once per message and the corpus is huge.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="A two by two grid of serialization formats by text versus binary and self-describing versus schema-required. Measured on the same four thousand order events, JSON averages 814 bytes per message, MessagePack 680 bytes at 83.5 percent, and a schema-ful binary encoding 205 bytes at 25.2 percent, saving 609 bytes on every message.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The two axes that actually decide the format — with measured sizes</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="126" y="60" width="352" height="176" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="490" y="60" width="352" height="176" rx="12" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="126" y="248" width="352" height="176" rx="12" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="490" y="248" width="352" height="176" rx="12" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.6">
    <rect x="146" y="186" width="312" height="26" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
    <rect x="146" y="374" width="261" height="26" rx="4" fill="#3553ff" fill-opacity="0.28" stroke="#3553ff"/>
    <rect x="510" y="374" width="79" height="26" rx="4" fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="62" y="150" font-size="11" font-weight="700" text-anchor="middle" transform="rotate(-90 62 150)">TEXT</text>
    <text x="62" y="338" font-size="11" font-weight="700" text-anchor="middle" transform="rotate(-90 62 338)">BINARY</text>
    <text x="302" y="48" font-size="11" font-weight="700" text-anchor="middle">SELF-DESCRIBING — names on the wire</text>
    <text x="666" y="48" font-size="11" font-weight="700" text-anchor="middle">SCHEMA-REQUIRED — numbers on the wire</text>

    <text x="146" y="90" font-size="12.5" font-weight="700" fill="#e0930f">JSON · XML · YAML</text>
    <text x="146" y="112" font-size="9.5" opacity="0.9">greppable, curl-able, no tooling needed</text>
    <text x="146" y="128" font-size="9.5" opacity="0.9">no byte type: binary must be base64'd (+33%)</text>
    <text x="146" y="144" font-size="9.5" opacity="0.9">number trap: ints &gt; 2^53-1 lose precision</text>
    <text x="146" y="160" font-size="9.5" opacity="0.9">add a field, coordinate with nobody</text>
    <text x="146" y="180" font-size="10.5" font-weight="700">814 B/message  ·  baseline 100%</text>
    <text x="466" y="204" font-size="9" text-anchor="end" font-weight="700">328 GB/day at 5k msg/s</text>

    <text x="510" y="90" font-size="12.5" font-weight="700" opacity="0.75">JSON + JSON Schema</text>
    <text x="510" y="112" font-size="9.5" opacity="0.85">the schema validates but does not shrink:</text>
    <text x="510" y="128" font-size="9.5" opacity="0.85">names are still on every message</text>
    <text x="510" y="150" font-size="9.5" opacity="0.85">you pay the coordination cost of a registry</text>
    <text x="510" y="166" font-size="9.5" opacity="0.85">and keep the byte cost of text</text>
    <text x="510" y="192" font-size="10.5" font-weight="700" opacity="0.8">worth it for correctness, not for size</text>

    <text x="146" y="278" font-size="12.5" font-weight="700" fill="#3553ff">MessagePack · CBOR (RFC 8949) · BSON</text>
    <text x="146" y="300" font-size="9.5" opacity="0.9">JSON's data model, compact binary framing</text>
    <text x="146" y="316" font-size="9.5" opacity="0.9">native byte strings — no base64 tax</text>
    <text x="146" y="332" font-size="9.5" opacity="0.9">still self-describing: field names remain</text>
    <text x="146" y="348" font-size="9.5" opacity="0.9">drop-in for JSON, no registry to run</text>
    <text x="146" y="368" font-size="10.5" font-weight="700">680 B/message  ·  83.5%  ·  saves 134 B</text>
    <text x="415" y="392" font-size="9" font-weight="700">273 GB/day</text>

    <text x="510" y="278" font-size="12.5" font-weight="700" fill="#0fa07f">Protobuf · Avro · Thrift</text>
    <text x="510" y="300" font-size="9.5" opacity="0.9">field NUMBERS + varints; UUID = 16 B not 36</text>
    <text x="510" y="316" font-size="9.5" opacity="0.9">enums = 1 byte; timestamps delta-encoded</text>
    <text x="510" y="332" font-size="9.5" opacity="0.9">needs a schema registry (lesson 12)</text>
    <text x="510" y="348" font-size="9.5" opacity="0.9">Avro drops tags too — smallest, most coupled</text>
    <text x="510" y="368" font-size="10.5" font-weight="700" fill="#0fa07f">205 B/message · 25.2% · saves 609 B</text>
    <text x="598" y="392" font-size="9" font-weight="700">83 GB/day</text>

    <text x="440" y="450" font-size="10.5" text-anchor="middle" opacity="0.95">Bars are the measured average of the same 4,000 order events, drawn to scale. The 4x gap is entirely the envelope and the field names.</text>
    <text x="440" y="470" font-size="10" text-anchor="middle" opacity="0.85">Choose text when humans debug it and volume is low. Choose schema-required when volume is high and you can run a registry.</text>
    <text x="440" y="490" font-size="10" text-anchor="middle" opacity="0.85">Choose self-describing binary when you want most of the size win with none of the coordination cost.</text>
    <text x="440" y="510" font-size="9.5" text-anchor="middle" opacity="0.7">And measure with YOUR messages: the ratio is dominated by how much of your bytes are field names and identifiers.</text>
  </g>
</svg>
```

### Compression: when it pays, and when it is a loss

Compression looks like free money and frequently is not. Three rules, all measured below.

**Small messages do not compress.** A compressor needs redundancy to exploit, and a 205-byte message does not contain any — while a zlib stream carries a header and trailer of its own. In the run below, compressing a single 205-byte binary message produces **209 bytes**: strictly worse, plus the CPU. Across the whole corpus, per-message compression of the binary format achieves 0.98x, i.e. it *inflates*.

**Batches compress far better than messages.** The redundancy in a message stream lives *across* messages — the same field names, the same type string, the same SKU codes, the same URL prefixes, over and over. A compressor can only exploit that if it sees them together. Measured on JSON: per-message compression gives 1.67x, batching 100 messages first gives **4.13x**, and compressing the whole corpus gives 4.26x. Batching before compressing is worth **2.48x** on its own. This is precisely why Kafka compresses at the *batch* level rather than per record, and why raising `linger.ms` — waiting a few milliseconds to fill a batch — often cuts bandwidth by more than half.

**Already-compact formats have less to gain.** JSON compresses 4.13x because it is full of repeated field names; the binary format compresses only 1.40x because those names were removed at encode time. Note where the two end up: compressed JSON batches (787,613 B) versus *uncompressed* binary (820,402 B) are nearly identical. Compression and a compact schema are substitutes for each other on the size axis — but the binary version also decodes without a decompression step, and its *compressed* form is 586,606 B, still 25% smaller.

The practical decision: compress **batches**, above a size threshold (a few kilobytes), and skip it entirely for small messages on a fast internal network. If you are cross-region or paying per gigabyte, compress more aggressively; if you are latency-sensitive on a 10 GbE link, the CPU may cost more than the bytes.

### Message size, broker limits, and the claim-check pattern

Brokers impose hard limits, and they are smaller than people expect:

| Broker | Limit | Note |
|---|---|---|
| Amazon SQS | 256 KiB | Both standard and FIFO queues |
| Apache Kafka | ~1 MiB default | `message.max.bytes`, raisable — usually a mistake to raise far |
| RabbitMQ (AMQP 0-9-1) | 128 MiB default max message size | Technically large; practically ruinous. `frame_max` is negotiated separately and much smaller |
| Google Pub/Sub | 10 MiB | Per message |

The limits are not arbitrary. Large messages wreck throughput for reasons that survive raising the limit: they occupy broker memory per in-flight message, they blow up consumer heap when a prefetch of 100 messages is suddenly 100 MB, they make head-of-line blocking dramatically worse, and they turn a redelivery into a re-transfer of megabytes. A broker is a *coordination* system, not a file transfer system.

The standard answer is the **claim-check pattern**, named after a coat check: put the bulky thing in storage, carry the ticket. Write the payload to object storage (S3, GCS), and publish a message containing a **pointer** — the URI, plus a content digest, plus the size, plus the content type. The consumer fetches the blob and verifies the digest. Measured below: a 408,890-byte message the broker refuses becomes a **795-byte** message, a 514x reduction, and the payload sits in object storage compressed 8.0x.

The digest is not optional decoration. Without it the pointer is an unvalidated download: you cannot tell a corrupted blob, a truncated upload, or a substituted object from the real thing, and you have handed a consumer a URL fetched from a message. With it, the message remains self-certifying about what it points at.

The cost of claim-check is a genuine architectural liability, and you should say it out loud when you propose it: **two systems now own one fact, with no transaction between them.** Three failure modes follow. If the blob is deleted before the message is consumed — a lifecycle rule, a cleanup job, a retention policy shorter than your dead-letter queue's age — the message is a dangling pointer that can never be processed. If the message is lost but the blob was written, the blob leaks and nobody ever collects it. And if a message is replayed a year later from a log (Lesson 5), the blob must still exist. The mitigations are to write the blob **before** publishing the message, to carry an explicit `expires_at` in the ticket so a consumer can distinguish "expired" from "corrupt", and to set the storage lifecycle rule to at least *max retention + max dead-letter age*, with margin.

### Immutability: a published message is a fact that happened

A message is not a row. You never update it, and no broker offers you the option.

The reason is that a message asserts something about the past: `order.placed` says an order *was* placed, at a time, by a customer. That either happened or it did not; it cannot become untrue later. If the amount was wrong, the truth is not "the order was always €35" — the truth is that an order was placed for €50 and later corrected to €35, and both of those are facts your system should carry.

So the mechanism for changing your mind is to **publish a new message**: `order.amount.corrected`, or a compensating `order.cancelled` followed by a fresh `order.placed`. This is not pedantry — it is the property that makes the whole phase work. Immutable messages can be safely replayed (Lesson 5), safely cached, safely deduplicated by id (Lesson 6), and safely audited, because the bytes for a given `message_id` are the same bytes forever. Mutable messages break every one of those. It is also why financial systems never delete a ledger entry and post a reversing entry instead: the correction *is* the history.

### Poison payloads: never deserialize untrusted data into arbitrary objects

The pickle demonstration is the extreme case of a general rule. Any deserializer that can instantiate arbitrary types from the wire is a remote code execution primitive: Python's `pickle`, Java's native serialization, .NET's `BinaryFormatter`, and — historically — YAML loaders that construct arbitrary classes and JSON libraries with polymorphic type handling enabled. The vulnerability is not a bug in those libraries; it is what they are *for*. They were designed to restore objects within a trusted process, and a message queue is the definition of an untrusted boundary.

The defensive posture is four rules:

1. **Deserialize into data, then validate, then construct.** Parse to a plain map, check it against the declared schema, and only then build a domain object. Never let the wire pick the type.
2. **Check the envelope before the body.** Allowlist `content_type`, bound `schema_version`, verify the digest, and enforce a size limit *before* handing anything to a parser.
3. **Bound everything.** Maximum body size, maximum nesting depth, maximum array length, maximum decompressed size. A 1 KB message that decompresses to 10 GB is a decompression bomb, and `content_encoding: deflate` is an invitation to try one.
4. **Treat a validation failure as a routing decision, not an exception.** A message that fails validation is not retryable — it will fail identically forever. Send it straight to the dead-letter queue with the reason attached (Lesson 8) rather than retrying it into an infinite loop.

## Build It

[`code/message_envelope.py`](code/message_envelope.py) builds the envelope, writes three encoders and three decoders by hand, and measures every claim above. Standard library only, seeded, deterministic — two runs print identical output.

The envelope is a frozen dataclass, and `validate()` is deliberately everything checkable *without* parsing the body:

```python
def validate(self) -> None:
    """Everything checkable without parsing the body. Cheap, and a security boundary."""
    for f in ("message_id", "correlation_id", "type", "source",
              "content_type", "content_encoding", "partition_key"):
        if not getattr(self, f):
            raise EnvelopeError(f"missing required envelope field: {f}")
    for f in ("message_id", "correlation_id", "causation_id"):
        ...                                   # must parse as an RFC 4122 UUID, right variant
    if self.content_type not in ALLOWED_CONTENT_TYPES:
        raise EnvelopeError(f"content_type not on the allowlist: {self.content_type!r}")
    if self.schema_version not in SUPPORTED_VERSIONS:
        raise EnvelopeError(
            f"schema_version {self.schema_version} outside supported {SUPPORTED_VERSIONS}")
    if self.published_at < self.occurred_at:
        raise EnvelopeError("published_at precedes occurred_at: clock skew or a forged event")
    if len(self.body) > BROKER_MAX_BYTES:
        raise EnvelopeError(
            f"body {len(self.body):,} B exceeds broker limit {BROKER_MAX_BYTES:,} B")
```

The schema-ful encoder is Protobuf's wire format: a varint **tag** carrying `field_number << 3 | wire_type`, then the value. Wire type 0 is a varint, 2 is length-delimited, 5 is a fixed 32-bit value:

```python
def uvarint(n: int) -> bytes:
    out = bytearray()
    while True:
        b, n = n & 0x7F, n >> 7
        out.append(b | 0x80 if n else b)      # high bit = "another byte follows"
        if not n:
            return bytes(out)


def bvar(f: int, n: int) -> bytes:            # wire type 0
    return uvarint(f << 3) + uvarint(n)


def bbytes(f: int, b: bytes) -> bytes:        # wire type 2
    return uvarint(f << 3 | 2) + uvarint(len(b)) + b
```

The envelope encoder is where the schema earns its keep. Three tricks, each visible in the measured table below — a UUID becomes 16 raw bytes instead of 36 characters, the two later timestamps become *deltas*, and the 55-character `traceparent` becomes its 26 constituent bytes:

```python
"message_id":   bbytes(1, uuid.UUID(e.message_id).bytes),        # 36 chars -> 16 bytes
"type":         bvar(4, TYPE_IDS[e.type]),                       # reverse-DNS -> 1 byte
"occurred_at":  bvar(7, e.occurred_at),
"published_at": bvar(8, e.published_at - e.occurred_at),         # delta: micros, not an epoch
"recorded_at":  bvar(9, (e.recorded_at or e.published_at) - e.published_at),
# 55 ASCII chars -> 26 raw bytes: version, trace-id, parent-id, flags
"traceparent":  bbytes(12, bytes([int(tp[0], 16)]) + bytes.fromhex(tp[1])
                       + bytes.fromhex(tp[2]) + bytes([int(tp[3], 16)])),
```

The MessagePack-style encoder sits between the two: binary framing, but the field names still travel, because nothing on the wire tells the reader what field 4 means without a schema. The rest — the decoders, the corpus generator, the causal-tree walker, and the claim-check store — is in the file. Run it:

```console
$ python message_envelope.py
== 1. THE NAIVE PATH: three ways to fail before you start ==
  str(dict)         105 B   {'order_id': '8f9a533a-d681-4d28-a890-f320d03af60b', 'amou...
  -> another language parses it as JSON: FAILS (Expecting property name enclosed in double quotes at col 2)
     single quotes, True/None instead of true/null. It is Python's repr, not a format.
  pickle            104 B   opcodes 80 04 95 5d 00 00 00 00 00 00 00 7d ...
  -> +6 B vs JSON, and unreadable outside Python
  pickle RCE         43 B   a 43-byte 'message' whose __reduce__ ran on load: executed=1
     pickle.loads() on attacker-influenced bytes is remote code execution, always.
  and none of the three carry: message_id, timestamp, type, schema_version, traceparent
     -> a retry double-charges, a replay looks live, the consumer guesses, the first
        schema change breaks every consumer, and the async hop leaves no trace.

== 2. THE ENVELOPE: 15 fields, each one a failure that cannot happen ==
  message_id        d7c162ef-7847-4721-97c2-c08782dec009     dedup key: a redelivery is recognised, not re-charged
  correlation_id    1ab449ec-cd11-419a-b803-acb3718a5ad6     one id for the whole business transaction
  causation_id      7035fd70-a283-4a1e-9a29-6ca1ea5f5867     the IMMEDIATE parent - gives a causal tree, not just a bag
  type              com.shop.order.placed                    the consumer routes on this without opening the body
  schema_version    1                                        of the BODY; lets old and new consumers coexist
  source            urn:svc:orders                           who to page when the payload is wrong
  occurred_at       1750000000000471                         EVENT time: when the fact happened in the world
  published_at      1750000000001274                         PROCESSING time: when the producer sent it. Skew lives here.
  recorded_at       1750000000008335                         when the broker durably accepted it. Broker-stamped.
  content_type      application/vnd.shop.order.v1+binary     how to parse the body - checked BEFORE parsing it
  content_encoding  identity                                 identity | deflate
  traceparent       00-4b7ff3b515a2bc60f5c4f67382a850ce-876a W3C Trace Context, so the async hop is not a black hole
  partition_key     c_061476                                 ordering scope (lesson 07)
  crc32             3957547317                               corruption and truncation are detected, not applied
  body              <81 B>                                   the business fact. Opaque to the broker.

== 3. THE SAME BYTES, THREE WAYS ==
  one line item: sku='AX-1042' qty=4 unit_minor=8851
  a) JSON   43 B  self-describing text, no schema needed
    0000  7b 22 71 74 79 22 3a 34  {"qty":4  the name "qty" costs 6 B to carry 1 digit
    0008  2c                       ,
    0009  22 73 6b 75 22 3a 22 41  "sku":"A  the name "sku" costs 6 B; the value needs quotes too
    0011  58 2d 31 30 34 32 22 2c  X-1042",
    0019  22 75 6e 69 74 5f 6d 69  "unit_mi  the name "unit_minor" costs 13 B to carry 5 digits
    0021  6e 6f 72 22 3a 38 38 35  nor":885
    0029  31 7d                    1}
  b) MessagePack-style  32 B  self-describing binary (CBOR family, RFC 8949)
    0000  83                       .         0x83 = fixmap, 3 pairs follow
    0001  a3 71 74 79              .qty      0xa3 = fixstr(3), then 'qty'
    0005  04                       .         positive fixint = 4 (1 byte, not 1 char)
    0006  a3 73 6b 75              .sku      0xa3 'sku'
    000a  a7 41 58 2d 31 30 34 32  .AX-1042  0xa7 fixstr(7) 'AX-1042'
    0012  aa 75 6e 69 74 5f 6d 69  .unit_mi  0xaa fixstr(10) 'unit_minor'
    001a  6e 6f 72                 nor
    001d  cd 22 93                 .".       0xcd = uint16, then 8851 big-endian
  c) schema-ful binary  14 B  field NUMBERS, not names (Protobuf wire format)
    0000  0a                       .         tag 0x0a = field 1 (sku) << 3 | wire 2
    0001  07                       .         length 7
    0002  41 58 2d 31 30 34 32     AX-1042   'AX-1042' - no field name on the wire at all
    0009  10                       .         tag 0x10 = field 2 (qty) << 3 | wire 0
    000a  04                       .         varint 4
    000b  18                       .         tag 0x18 = field 3 (unit_minor)
    000c  93 45                    .E        varint 8851 in 2 bytes, 7 bits each
  field names cost 29 of JSON's 43 bytes here (67%). Multiply by every message, forever.

== 3b. THE ENVELOPE, FIELD BY FIELD (bytes on the wire) ==
  field                json   msgpk  binary   what the schema buys
  message_id             52      49      18   36-char UUID text -> 16 raw bytes
  correlation_id         56      53      18   same
  causation_id           54      51      18   same
  type                   31      27       2   reverse-DNS string -> 1-byte registry id
  schema_version         19      16       2   small int
  source                 26      22       2   URN string -> 1-byte registry id
  occurred_at            31      21       9   varint micros beats 16 ASCII digits
  published_at           32      22       3   DELTA from occurred_at: micros, not an epoch
  recorded_at            31      21       3   delta from published_at
  content_type           34      33       2   MIME string -> registry id
  content_encoding       30      26       2   enum
  traceparent            72      69      28   55 ASCII chars -> 26 raw bytes
  partition_key          27      23      10   short string, nothing to win
  crc32                  19      11       5   fixed32
  body                  302     238      83   the order itself, natively encoded
  TOTAL ON WIRE         817     683     205
  of which body         294     231      81
  ENVELOPE ONLY         523     452     124   metadata is 4.2x cheaper with a schema
  (each column carries its own native body and content_type, hence the body rows differ)

== 4. THE CORPUS: 4,000 order events, measured ==
  format          total    avg   vs json   bytes saved/msg    at 5k msg/s
  json      3,256,217 B    814    100.0%               0 B         328 GB/d
  msgpack   2,718,339 B    680     83.5%             134 B         273 GB/d
  binary      820,402 B    205     25.2%             609 B          83 GB/d
  CPU: every encode and decode landed within 1.5x of the json baseline (best of 5 over 4,000
  messages), so a 4x size win cost essentially no CPU. Note the handicap, though:
  `json` is C inside CPython and our binary codec is interpreted Python. Format and
  implementation are different variables; a compiled Protobuf moves binary well ahead.
  round-trip: binary msg 7 -> same order_id True, same amount True, same items True

== 5. COMPRESSION: per message vs per batch ==
  format            raw         per-message      per-batch-of-100        whole corpus
  json      3,256,217 B   1,953,566 B  1.67x       787,613 B  4.13x     763,820 B  4.26x
  msgpack   2,718,339 B   2,004,545 B  1.36x       788,237 B  3.45x     765,025 B  3.55x
  binary      820,402 B     839,719 B  0.98x       586,606 B  1.40x     573,997 B  1.43x
  batching 100 JSON messages beats compressing them one by one by 2.48x - repetition ACROSS messages is where the entropy savings live
  a single 205 B binary message zlibs to 209 B: the header and empty dictionary cost more than they save
  base64 tax: the 81 B binary body becomes 108 B inside a JSON string (+33%) - JSON cannot carry bytes

== 6. CORRELATION vs CAUSATION: reconstructing the causal tree ==
  correlation_id 82a0a2b2-566a-43c8-aee3-e34211176a9f  <- identical on all 6 messages
  com.shop.checkout.requested            urn:svc:web-bff        072eb622  t+0ms
    +- com.shop.order.placed             urn:svc:orders         c9cac276  t+41ms
      +- com.shop.payment.authorized     urn:svc:payments       fc53cd2a  t+82ms
        +- com.shop.shipment.requested   urn:svc:shipping       c0ff668e  t+164ms
        +- com.shop.receipt.emailed      urn:svc:notifications  f62d8338  t+205ms
      +- com.shop.inventory.reserved     urn:svc:inventory      fea0944f  t+123ms
  correlation alone gives you a BAG of 6 messages sharing an id.
  causation gives you the edges: who caused whom, and where a branch stopped.
  a message whose causation_id 99aaa4bd names no known message is an ORPHAN - the
  parent was never published, or was lost. One join is the whole consistency check.

== 7. CLAIM CHECK: a payload the broker will not carry ==
  direct publish    408,890 B  REJECTED: body 408,367 B exceeds broker limit 262,144 B
  claim check           795 B  a pointer + sha256 + size + expiry
  payload parked in object storage: 50,795 B deflated (8.0x)
  the message shrank 514x (408,890 B -> 795 B) and now fits every broker
  consumer fetches, then verifies sha256: True  (without this the pointer is an unvalidated download)
  the cost: two systems now own one fact. Delete the blob before the message is
  consumed and it is a dangling pointer; drop the message and the blob leaks.
  hence expires_at in the ticket, and a lifecycle rule >= retention + DLQ age.

== 8. VALIDATION: six messages that must never reach business logic ==
  unknown content type             rejected: content_type not on the allowlist: 'application/x-python-pickle'
  missing required field           rejected: missing required envelope field: message_id
  schema_version from the future   rejected: schema_version 9 outside supported (1, 2)
  message_id is not a UUID         rejected: message_id is not an RFC 4122 UUID: 'order-2291'
  published before it occurred     rejected: published_at precedes occurred_at: clock skew or a forged event
  body altered in flight           rejected: crc32 mismatch: declared 3704443669, computed 3704443882
  the unmodified message           accepted: type=com.shop.order.placed v1, crc ok, 294 B body
  every reject happened on ENVELOPE fields alone. The body was never parsed.
```

Six things in that output are worth reading twice.

**Pickle is not even a size win.** 104 bytes against JSON's 98 — larger, Python-only, and carrying a 43-byte proof that loading it executes code. There is no axis on which it is the right choice for a wire format, and the reason to know this is that "just pickle it, it's faster" is a real thing people say in code review.

**Field names are most of a small message.** On one line item, JSON spends 29 of 43 bytes — 67% — on the strings `qty`, `sku`, `unit_minor` and their punctuation. The MessagePack version still spends them; it just frames them more efficiently, which is exactly why it lands at 83.5% rather than 25%. Dropping the names is where the real win lives, and dropping them is precisely what requires a schema.

**The envelope is not free, and a schema makes it nearly so.** The envelope alone costs **523 bytes in JSON and 124 in binary** — 4.2x. Look at the individual rows: `message_id` 52 → 18, `traceparent` 72 → 28, `content_type` 34 → 2, and `published_at` 32 → 3 because a delta from `occurred_at` is a four-digit number rather than a sixteen-digit epoch. None of those are clever compression; they are what happens when both sides already know what field 8 means and what type it is.

**Across the corpus the ratio holds: 814 → 680 → 205 bytes per message, or 100% → 83.5% → 25.2%.** At a modest 5,000 messages/second that is **328 GB/day versus 83 GB/day** — a difference that shows up in cross-AZ transfer charges, broker disk, and replication bandwidth simultaneously. And the CPU cost of the win was nil: everything landed within 1.5x of the JSON baseline. Read the handicap in the output honestly, though — `json` is C inside CPython and our encoder is interpreted Python, so this comparison *understates* binary's speed. Format and implementation are different variables, and confusing them is how benchmark arguments start.

**Compressing one small message is a loss.** 205 bytes in, **209 bytes out**. Batch 100 of them first and JSON hits 4.13x where per-message managed 1.67x — a 2.48x improvement from batching alone. If you remember one operational fact from this lesson, make it this one: **compression is a property of batches, not of messages.**

**Every rejection happened on envelope fields.** Six malformed messages — a pickle content type, a missing id, a version from the future, a non-UUID id, an impossible timestamp ordering, and a flipped CRC — and the body was never handed to a parser in any of them. That is the security boundary from the first diagram, working.

## Use It

You will not hand-roll an envelope in production. You will map these fields onto whatever your broker already provides — and every broker provides them, because every broker's designers hit the same failures.

**AMQP 0-9-1** (Advanced Message Queuing Protocol) is the most explicit: the `basic.properties` structure has named slots for most of the envelope, plus a free-form `headers` table for the rest.

```python
properties = pika.BasicProperties(
    message_id="d7c162ef-7847-4721-97c2-c08782dec009",     # our message_id
    correlation_id="1ab449ec-cd11-419a-b803-acb3718a5ad6", # our correlation_id
    content_type="application/vnd.shop.order.v1+binary",   # our content_type
    content_encoding="identity",                           # our content_encoding
    type="com.shop.order.placed",                          # our type
    app_id="urn:svc:orders",                               # our source
    timestamp=1750000000,                                  # ONE timestamp -- see below
    delivery_mode=2,                                       # persistent
    headers={"schema_version": 1,                          # no native slot -> headers
             "causation_id": "7035fd70-...",
             "traceparent": "00-4b7ff3b5...-01",
             "occurred_at": 1750000000000471})
```

Note what the mapping teaches: AMQP gives you exactly one `timestamp`, at second granularity, with no statement about *which* of the three it is. Real deployments therefore push `occurred_at` into `headers` and treat the native field as publish time. That is the general shape of every broker mapping — a few native slots, and a headers table for everything the protocol's designers did not anticipate.

**Kafka** gives a record four parts: **key**, **value**, **headers** (arbitrary byte-string pairs, added in 0.11), and a **timestamp**. The key is our `partition_key` — it decides the partition and therefore the ordering scope (Lesson 7). Everything envelope-ish goes in headers. Kafka's timestamp is the sharpest illustration of the event-time/processing-time split anywhere in this phase, because the broker lets you choose which one it stores:

```text
# per topic:
message.timestamp.type = CreateTime    # the PRODUCER's timestamp -- closest to event time
# message.timestamp.type = LogAppendTime  # the BROKER's -- our recorded_at, monotonic per partition
```

`CreateTime` trusts a producer clock you do not control; `LogAppendTime` is trustworthy but tells you nothing about when the fact happened. Neither is "correct" — which is the entire argument for carrying `occurred_at` yourself in a header and letting the broker's field mean whatever it means.

**Amazon SQS** (Simple Queue Service) carries `MessageAttributes` (up to 10 typed key/value pairs) alongside the body, and FIFO queues add two envelope fields as first-class parameters: `MessageDeduplicationId` — literally our `message_id`, used by SQS to suppress duplicates within a 5-minute window — and `MessageGroupId`, which is our `partition_key` under a different name.

```python
sqs.send_message(
    QueueUrl=q, MessageBody=body,
    MessageDeduplicationId="d7c162ef-7847-4721-97c2-c08782dec009",  # message_id
    MessageGroupId="c_061476",                                      # partition_key
    MessageAttributes={
        "type": {"DataType": "String", "StringValue": "com.shop.order.placed"},
        "schema_version": {"DataType": "Number", "StringValue": "1"},
        "traceparent": {"DataType": "String", "StringValue": "00-4b7ff3b5...-01"}})
```

SQS's 256 KiB limit is the tightest in common use, and AWS ships an Extended Client Library whose entire purpose is the claim-check pattern: bodies above a threshold go to S3 automatically and the message carries a pointer.

**NATS** added headers in 2.2 for the same reason everyone else did, and JetStream uses `Nats-Msg-Id` for deduplication — again, our `message_id` under a local name.

**CloudEvents** is the one to know by name. It is a **CNCF** (Cloud Native Computing Foundation) specification that standardizes the envelope itself, so an event crossing vendors, clouds, and languages keeps its metadata. Version 1.0 defines four **required** attributes — `id`, `source`, `specversion`, `type` — plus optional ones, with transport bindings for HTTP, AMQP, Kafka, MQTT and more:

```json
{
  "specversion": "1.0",
  "id": "d7c162ef-7847-4721-97c2-c08782dec009",
  "source": "urn:svc:orders",
  "type": "com.shop.order.placed",
  "time": "2025-06-15T14:32:07.412Z",
  "datacontenttype": "application/json",
  "dataschema": "https://schemas.shop.example/order/v1.json",
  "subject": "order/9f4c2b18",
  "partitionkey": "c_061476",
  "traceparent": "00-4b7ff3b3577b34da6a3ce929d0e0e473-00f067aa0ba902b7-01",
  "correlationid": "1ab449ec-cd11-419a-b803-acb3718a5ad6",
  "causationid": "7035fd70-a283-4a1e-9a29-6ca1ea5f5867",
  "data": { "order_id": "9f4c2b18-...", "customer_id": 61476, "amount_minor": 42999 }
}
```

The mapping to what you just built is nearly one-to-one: `id` is `message_id`, `source` is `source`, `type` is `type`, `time` is `occurred_at`, `datacontenttype` is `content_type`, `dataschema` replaces `schema_version` with a URI that resolves to the schema itself, and `data` is the payload. `partitionkey` and `traceparent`/`tracestate` come from official **extension** specifications — the Partitioning and Distributed Tracing extensions — and `correlationid`/`causationid` are the conventional custom extensions you add yourself, since CloudEvents does not standardize them.

Two properties make CloudEvents worth adopting even in a single-broker shop. It has **two content modes**: *structured*, where the whole envelope is one JSON document as above, and *binary*, where each attribute becomes a transport header (`ce-id`, `ce-type`, `ce-source`) and the body stays raw — which is exactly the headers-versus-body boundary from the first diagram, made official. And it means the retry handler, the dead-letter processor, and the audit logger you write once will work for every event your organization ever produces, because they read a standard envelope rather than yours.

**The `traceparent` propagation convention**, finally, is worth stating as a rule because it is the piece teams most often skip: the producer writes the *current* span's context into the message as `traceparent`; the consumer reads it and starts its span as a child (or, for batches, as a **link**, since one consumer span may cover many parent messages). Do this and a trace spans the async hop. Skip it and Phase 9's tooling stops at the publish call, which is where you needed it to start.

## Think about it

1. Your team has been carrying a single `timestamp` field for two years. An analytics engineer reports that revenue for 09:00–10:00 keeps changing hours after the hour closed. Explain the mechanism in terms of event time versus processing time, say which of the three timestamps would fix it, and describe what new question you are forced to answer once you bucket by event time.

2. A colleague proposes dropping `causation_id` because "`correlation_id` already links everything, and one id is simpler." Construct a concrete incident — an order that half-completed — where correlation alone leaves you unable to answer the operational question, and state exactly what the causation edges tell you that the shared id does not.

3. The measured run shows compressing a single 205-byte binary message *inflates* it to 209 bytes, while batching 100 JSON messages first yields 4.13x. Your broker client has a `linger_ms` setting currently at 0. Explain what raising it to 20 ms would do to bandwidth and to latency, and describe one workload where that trade is clearly wrong.

4. You adopt the claim-check pattern with a 30-day object-storage lifecycle rule. Your main queue retains messages for 4 days, your dead-letter queue for 14, and an engineer replays a month of events from an archived log to rebuild a projection. Walk through what breaks, and specify the lifecycle rule you should have set.

5. A vendor's SDK offers "transparent object serialization" that turns your domain objects into messages and back with no schema. List the failures from The Problem this reintroduces, and identify which single one makes it unacceptable regardless of the others.

6. Your envelope has `crc32` over the body. A teammate argues this makes the message tamper-proof and you can therefore trust bodies from partner systems. Explain precisely what a CRC does and does not give you here, and say what you would use instead if the threat is a malicious partner rather than a corrupted network.

## Key takeaways

- A message has two parts with two owners. The **payload** is the business fact, owned by the domain; the **envelope** is metadata *about the message*, owned by the platform and identical whether the body is an order or a password reset. Confusing them is the root cause of most bad message designs.
- **Every routing, retry, ordering, dedup and observability decision must be answerable from the envelope alone.** This is a performance boundary — a broker cannot parse a million bodies a second — and a security boundary: in the measured run, six malformed messages were rejected and not one body was ever handed to a parser.
- **Never use a language-native serializer on a wire.** Python's `pickle` measured *larger* than JSON (104 B vs 98 B), is unreadable outside Python, and a 43-byte crafted "message" executed arbitrary code inside `pickle.loads`. Deserializing into arbitrary object types is remote code execution by design, not by bug.
- **`correlation_id` and `causation_id` are not the same field.** Correlation is the whole business transaction, copied unchanged onto every descendant; causation is the *immediate parent's* `message_id`, and it changes every hop. Correlation gives you a set; causation gives you the edges, and set + edges = the causal tree, plus a one-join orphan check that finds lost publishes.
- **"Timestamp" is at least three fields.** `occurred_at` (event time — when the fact happened), `published_at` (producer processing time), and `recorded_at` (broker-stamped, the only clock you did not have to trust). The gap between the first two is why watermarks exist, and why Kafka makes you choose between `CreateTime` and `LogAppendTime`.
- **Serialization is two axes, not a menu**: text vs binary, and self-describing vs schema-required. Measured on 4,000 identical order events: JSON 814 B/msg (100%), MessagePack-style 680 B (83.5%), schema-ful binary 205 B (25.2%) — **328 vs 83 GB/day at 5,000 msg/s** — with the whole 4x gap coming from dropping field names, packing a UUID as 16 bytes instead of 36 characters, and delta-encoding timestamps. The envelope alone went from 523 B to 124 B, a 4.2x saving.
- **Compression is a property of batches, not messages.** Compressing one 205-byte message *grew* it to 209 B; batching 100 JSON messages before compressing beat per-message compression by 2.48x (4.13x vs 1.67x), because the redundancy lives across messages, in the repeated field names and type strings. Already-compact binary has far less to gain (1.40x).
- **Big payloads do not belong in messages.** Broker limits are tight (SQS 256 KiB, Kafka ~1 MiB by default), and large messages wreck memory and head-of-line latency even where allowed. The **claim-check pattern** — blob in object storage, pointer plus digest plus size plus expiry in the message — took a rejected 408,890-byte message to 795 bytes, a 514x reduction. Its cost is real: two systems now own one fact, so write the blob first and set the storage lifetime to at least retention + dead-letter age.
- **A published message is an immutable fact.** You never edit it; you publish a correction. That immutability is what makes replay, caching, deduplication by id, and audit possible at all — and it is why validation failures go straight to a dead-letter queue rather than into a retry loop, since a message that fails validation will fail identically forever.

Next: [Build a Message Queue: Work Distribution & Acknowledgement](../03-build-a-message-queue/) — now that a message is a well-formed, self-describing, verifiable thing, we build the broker that carries it: a queue that hands each message to exactly one consumer, holds it until the work is acknowledged, and returns it to the front when the consumer dies mid-task.
