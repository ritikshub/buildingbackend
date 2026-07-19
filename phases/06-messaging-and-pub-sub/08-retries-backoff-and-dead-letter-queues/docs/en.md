# Retries, Backoff, Dead-Letter Queues & Poison Messages

> Two failures land in your consumer thirty seconds apart and look identical from the inside: an exception, a stack trace, an unacknowledged message. One of them heals if you wait two seconds. The other will never succeed, not in two seconds and not in two years — and because delivery is at-least-once, the broker will hand it back to you forever, blocking every message behind it. Telling these apart, and choosing what happens next, is the difference between a consumer that survives a bad afternoon and one that turns a brief dependency wobble into a six-hour outage of your own making.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Ordering, Partition Keys & Parallel Consumers](../07-ordering-partition-keys-and-parallel-consumers/)
**Time:** ~75 minutes

## The Problem

Your payments consumer is correct. It reads from the topic, charges the card, writes the receipt, acknowledges the message. It has been correct for eight months. Then, in the same week, it fails twice — in two ways that look the same in the logs and demand exactly opposite responses.

**Failure one: the poison message.** A producer deploys on Tuesday afternoon with a bug that leaves `amount_cents` null on roughly one event in nine thousand. One such event reaches your consumer. Your handler dereferences the null, throws, and does not acknowledge. The broker, doing exactly what at-least-once delivery promises, redelivers it. Your handler throws again. And again.

Nothing about that message will ever change. It is malformed on disk. But your consumer has no concept of "will never work", so it retries as fast as the broker will feed it — thousands of times a minute. Three things happen at once, in increasing severity. Your error-rate graph goes vertical, burying every other signal. Your consumer burns its slot re-processing one dead event instead of the live ones behind it. And — this is the one that ends the afternoon — the message is in an **ordered partition**, and the guarantee you built in [Lesson 07](../07-ordering-partition-keys-and-parallel-consumers/) means the broker *cannot* hand you offset 182,401 until you acknowledge 182,400. Every message for that key is stuck behind a corpse. One malformed event has stopped a pipeline.

**Failure two: the retry storm.** On Thursday the downstream payment API degrades — a database failover, forty-five seconds, the kind of thing that should be a blip. Every consumer gets a `503` and does the sensible-looking thing: retries. They all failed at the same instant, so they all retry at the same instant, in lockstep, indefinitely. Two hundred consumers hammering a service trying to come back up.

Then the API recovers, and the recovery is what kills you. The instant it accepts connections it is hit by the entire accumulated backlog simultaneously — every retry queued behind those forty-five seconds, in the same second. It falls over again. Your consumers see failures, retry in lockstep, and knock it over again. The forty-five-second blip is now a sustained outage, sustained **by your retry logic**. You did not build a resilience mechanism; you built a load amplifier and pointed it at an already-struggling dependency.

These two failures frame the lesson. The first says *some failures must never be retried, and you need somewhere to put them.* The second says *even failures that should be retried will destroy you if you retry them naively.*

## The Concept

### Classify the failure before you retry

Here is the single habit that separates a consumer that behaves well from one that does not, and it happens *before* any question about how long to wait:

> **Every failure is either transient or permanent, and you must decide which before you decide anything else.**

A **transient** failure is one where the same request, sent again later, may well succeed, because the cause was a property of *the moment* rather than of *the message*: a network reset, a read timeout, a `503`, a `429`, a database deadlock, a leader election in progress. The message is fine; the world was briefly hostile. Retry is exactly right.

A **permanent** failure is one where the same request will fail identically forever, because the cause is a property of *the message itself* or of a rule that will not change: a malformed payload, a schema validation failure, a `400 Bad Request`, a `403` because your credential lacks a scope, a hard decline from a card issuer. Here retry is not merely useless, it is **actively harmful** — it costs attempts, fills logs, occupies consumer capacity, and in an ordered partition blocks everything behind it, all in exchange for a guaranteed failure.

Retrying a permanent failure is the defining beginner mistake in this subject, and it is easy to make: the error path is the least-tested code in most services, and `except Exception: retry()` looks like diligence.

The HTTP status families give you most of the map for free, by design: RFC 9110 (*HTTP Semantics*) defines the `4xx` class as errors where "the client seems to have erred" and `5xx` as errors where "the server is aware that it has erred or is incapable of performing the requested method." That is the transient/permanent split, stated in the protocol.

| Signal | Class | Action | Why |
|---|---|---|---|
| Connection reset, DNS failure | transient | retry | the network is not the message |
| Read/connect timeout | transient | retry, **carefully** | may have partially succeeded — see idempotency |
| `500`, `502`, `503`, `504` | transient | retry with backoff | the server says it is broken, not that you are |
| `429 Too Many Requests` | transient | retry, and **obey `Retry-After`** | the server is telling you the delay |
| Database deadlock, serialization failure | transient | retry immediately, once | contention resolves by retrying |
| `400 Bad Request`, malformed JSON | permanent | dead-letter now | the bytes are wrong and will stay wrong |
| Schema validation failure | permanent | dead-letter now | a contract violation ([Lesson 12](../12-schema-evolution-and-event-contracts/)) |
| `401` / `403` | permanent* | dead-letter, alert loudly | a credential problem a human must fix |
| `422`, business-rule rejection | permanent | dead-letter now | the system worked; the answer is no |
| `409 Conflict` on a duplicate | **not a failure** | acknowledge as success | this is idempotency working ([Lesson 06](../06-delivery-semantics-and-idempotency/)) |

The asterisk on `401`/`403` marks the honest complication: an expired token is transient *if* your client refreshes credentials, and permanent if it does not. Classification is about your system's actual capabilities, not about the status code in the abstract.

### The ambiguous middle, and how to resolve it

Some failures genuinely do not classify themselves, and pretending otherwise produces bugs. The canonical case is **`404 Not Found` on a referenced entity**.

Your `payments` consumer receives `OrderPlaced` for order `9182` and calls `orders` to fetch details. It gets a `404`. Two completely different worlds produce that byte sequence:

- **Not yet.** The `orders` service wrote the row and published the event, but you are reading a replica that has not caught up, or the publish beat the commit. This is transient, it will resolve in milliseconds, and dead-lettering is wrong.
- **Never.** The order was rolled back, or the producer emitted a bogus id, or the row was deleted. This is permanent, and retrying it 12 times is waste.

Three resolutions, in order of preference. **Fix the contract**: have the upstream distinguish "unknown id" from "not yet visible" with different status codes — this is the real fix. **Bound the ambiguity with time**: treat `404` as transient for 60 seconds after the event's timestamp and permanent after that, which encodes "replication lag is real but bounded" as a decision rather than a hope. **Remove the lookup**: if the event carried the data you needed, you would not be asking — the argument for fatter events in [Lesson 11](../11-event-driven-architecture/).

What you must not do is pick one at random. Write the rule down, with the reasoning, next to the code.

### Backoff, derived rather than asserted

Once you have decided a failure is worth retrying, the only remaining question is *when*. Work up from the naive answer.

**Immediate retry.** Right in one situation only: contention resolved by the act of retrying — a database deadlock, an optimistic-concurrency conflict — where the loser retrying immediately is the intended recovery. For a failing network dependency it is the worst choice available, converting one failed request into a tight loop of them.

**Fixed delay.** Wait 5 seconds, always. About as sophisticated as most first drafts get, and too slow for a 50 ms blip while far too fast for a 10-minute outage: one constant cannot be right for failures whose durations span four orders of magnitude. It never adapts, either — 200 clients retrying every 5 seconds against a dead dependency deliver a steady 40 requests/second of pure waste for as long as the outage lasts.

**Exponential backoff.** `delay = base * 2^(attempt - 1)`. With `base = 2s`: 2, 4, 8, 16, 32, 64 seconds. The reason this is the right shape is information-theoretic: each failure is evidence the outage is longer than you thought, so each failure should increase your estimate of how long to wait. Doubling converges on the true duration in a logarithmic number of attempts.

**Capped exponential.** Uncapped doubling reaches absurd delays fast — attempt 15 is over nine hours. Cap it: `delay = min(cap, base * 2^(attempt - 1))`. Now the policy has three parameters that mean something operationally: `base` sets responsiveness to short blips, `cap` sets the steady-state polling rate during a long outage, and together with `max_attempts` they set the **total retry window** — the wall-clock time a message may spend failing before it is dead-lettered. In the program below, base 2 s, cap 32 s and 12 deliveries sum to exactly **254 seconds**. That is a service-level decision, not an accident: it is how long a message survives a downstream outage before a human has to get involved.

### Jitter is not optional

Capped exponential backoff still has a fatal flaw, and it is the one that caused Thursday's outage.

Every client computes the same delay from the same formula, so clients that failed together retry together, forever. Backoff spreads retries out **in time**; it does nothing to spread them **across clients**. The population stays synchronised, and a synchronised population arrives as a spike. This is the **thundering herd**: a recovering dependency's reward for coming back is to be hit by every accumulated retry at once, which knocks it over, which re-synchronises everyone for the next round.

**Jitter** — deliberate randomness in the delay — is the fix, and it is not a refinement. It is the part that makes backoff work at all once more than one client exists. Three formulations:

```text
b = min(cap, base * 2^(attempt-1))          the capped exponential ceiling

full jitter          sleep = random(0, b)                    spread [0, b],   mean b/2
equal jitter         sleep = b/2 + random(0, b/2)            spread [b/2, b], mean 3b/4
decorrelated jitter  sleep = min(cap, random(base, 3*prev))  driven by the previous delay
```

**Full jitter** gives the widest spread and lowest peak load, at the cost of sometimes retrying very soon after a failure. **Equal jitter** keeps half the delay deterministic, guaranteeing a minimum wait — useful when you want a hard floor on how fast you can hammer something. **Decorrelated jitter** derives each delay from the previous one rather than the attempt number, letting the delay walk upward quickly while staying spread.

The measured difference is the centrepiece of the program below — 200 clients, a dependency that dies at `t=0`, recovers at `t=45s`, and absorbs 60 requests/second. Peak retries in a single second *after recovery*:

```text
exponential, no jitter    112 retries/s     -> over the 60/s cliff, knocked back down
exponential + full jitter  15 retries/s     -> comfortably under it, everyone gets through
```

A 7× reduction in the peak load a recovering dependency sees, from one call to `random()`. The total attempt count barely moves — 1,440 versus 1,494 — so this is not doing less work. It is the *same* work, arriving in a shape the dependency can survive.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Two retry timelines for 200 clients against a dependency that recovers at 45 seconds. Without jitter every client computes the same delay, so retries arrive as identical spikes of 112 per second that exceed the 60 per second capacity cliff and are shed, re-synchronising the fleet. With full jitter the same retries are spread across the backoff window, peaking at 15 per second, well under the cliff, so they succeed.">
  <defs>
    <marker id="l08-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">200 clients, one dependency, two retry policies</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="184" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="240" width="848" height="184" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.55">
    <path d="M74 196 L 846 196"/>
    <path d="M74 394 L 846 394"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="1.5" stroke-dasharray="6 4" opacity="0.9">
    <path d="M74 148 L 846 148"/>
    <path d="M74 346 L 846 346"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.7">
    <path d="M470 74 L 470 208"/>
    <path d="M470 272 L 470 406"/>
  </g>

  <g fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.4">
    <rect x="92" y="106" width="15" height="90"/>
    <rect x="188" y="106" width="15" height="90"/>
    <rect x="330" y="106" width="15" height="90"/>
    <rect x="486" y="106" width="15" height="90"/>
    <rect x="656" y="106" width="15" height="90"/>
  </g>
  <g fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f" stroke-width="1.2">
    <rect x="486" y="376" width="11" height="18"/>
    <rect x="504" y="380" width="11" height="14"/>
    <rect x="522" y="374" width="11" height="20"/>
    <rect x="540" y="382" width="11" height="12"/>
    <rect x="558" y="378" width="11" height="16"/>
    <rect x="576" y="380" width="11" height="14"/>
    <rect x="594" y="376" width="11" height="18"/>
    <rect x="612" y="382" width="11" height="12"/>
    <rect x="630" y="378" width="11" height="16"/>
    <rect x="648" y="380" width="11" height="14"/>
    <rect x="666" y="376" width="11" height="18"/>
    <rect x="684" y="382" width="11" height="12"/>
    <rect x="702" y="378" width="11" height="16"/>
    <rect x="720" y="380" width="11" height="14"/>
    <rect x="738" y="382" width="11" height="12"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="68" font-size="12.5" font-weight="700" fill="#e0930f">EXPONENTIAL, NO JITTER — every client computes the same delay</text>
    <text x="34" y="88" font-size="9.5" opacity="0.85">the fleet failed together at t=0, so it retries together forever: backoff spreads retries in TIME, not across CLIENTS</text>
    <text x="850" y="144" font-size="9" text-anchor="end" fill="#3553ff" font-weight="700">capacity cliff — 60 req/s</text>
    <text x="99" y="100" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">112/s</text>
    <text x="470" y="70" font-size="9" text-anchor="middle" font-weight="700">RECOVERS t=45s</text>
    <text x="560" y="128" font-size="9.5" font-weight="700" fill="#e0930f">the whole backlog lands in one second</text>
    <text x="560" y="144" font-size="9" opacity="0.9">→ shed → re-synchronised → round again</text>
    <text x="440" y="216" font-size="10" text-anchor="middle" opacity="0.95">measured: 1,440 calls · peak 112/s after recovery · 160.0s to drain</text>

    <text x="34" y="266" font-size="12.5" font-weight="700" fill="#0fa07f">EXPONENTIAL + FULL JITTER — sleep = random(0, b)</text>
    <text x="34" y="286" font-size="9.5" opacity="0.85">the same 200 clients, the same backoff ceiling, decorrelated: each one picks a different point inside the window</text>
    <text x="850" y="342" font-size="9" text-anchor="end" fill="#3553ff" font-weight="700">capacity cliff — 60 req/s</text>
    <text x="470" y="268" font-size="9" text-anchor="middle" font-weight="700">RECOVERS t=45s</text>
    <text x="620" y="366" font-size="9.5" font-weight="700" fill="#0fa07f">15/s — arrives underneath the cliff, so it gets through</text>
    <text x="440" y="414" font-size="10" text-anchor="middle" opacity="0.95">measured: 1,494 calls · peak 15/s after recovery · 74.7s to drain</text>
    <text x="440" y="448" font-size="10.5" text-anchor="middle" font-weight="700">Same work. Same number of attempts. 7x lower peak, and half the time to drain.</text>
    <text x="440" y="466" font-size="9.5" text-anchor="middle" opacity="0.8">Jitter is not a tuning refinement — it is the part that makes backoff work once more than one client exists.</text>
  </g>
</svg>
```

### Retry budgets: bounding amplification at fleet scale

`max_attempts = 3` feels like a bound on retry load. It is not, and the reason is arithmetic.

A per-request limit bounds what *one request* does. What a struggling dependency experiences is the *sum* across every client. Three hundred consumer instances, each retrying up to 3 times, means a dependency handling `N` requests/second can suddenly see `3N` — exactly when it is least able to. The amplification is highest precisely when the failure rate is highest, so the mechanism supplies maximum extra load at the moment of maximum weakness, and no individual client is misbehaving.

A **retry budget** bounds the thing that matters: the *fraction* of traffic that may be retries. "Retries may not exceed 10% of this consumer group's request volume." Implemented as a token bucket — successful requests earn tokens at the budget ratio, each retry spends one, retries are denied when the bucket is empty — it has a property no per-request limit can have: **the bound holds regardless of how many clients there are and how badly they are failing.** If everything is failing there is almost no successful traffic, so almost no budget, so retries stop almost entirely. The mechanism gets *more* conservative exactly as the situation gets worse. This is the Google SRE formulation; 10% is the usual starting point.

What happens to a denied message matters: discarding it is data loss. **Park** it instead — to a delay tier or the dead-letter path — so the budget costs *latency*, not *messages*. Measured: all 200 messages still succeed, outage load drops from 1,294 calls to 504, and the price is 493 park events and a drain time of 195.2 s instead of 74.7 s.

### The circuit breaker: closed, open, half-open

A retry budget rations retries. A **circuit breaker** goes further and stops sending requests at all when the evidence says they cannot succeed. It is a three-state machine wrapped around a dependency:

- **Closed** — normal. Requests pass through; consecutive failures are counted.
- **Open** — after N consecutive failures (or a failure rate over a window), the breaker trips and every request is **rejected locally, without a network call at all**. You fail in microseconds instead of waiting for a timeout, stop consuming your own threads and connections on a doomed call, and stop adding load to a service that is down.
- **Half-open** — after a cooldown, exactly **one** probe passes. Success closes the breaker; failure re-opens it. This is how it discovers recovery without a herd: one request, not two hundred.

Fail-fast is the underrated half. A breaker is not only a favour to the dependency; it protects *you*, because the alternative is your consumers blocked on timeouts, threads exhausted, and your own service failing for want of capacity parked on something that will not answer.

Measured over the 45-second outage: the unprotected fleet delivered **1,294 calls** to the dying dependency; with a breaker, **13** — a 100× reduction. It rejected 1,800 attempts locally and spent 9 half-open probes discovering when to close. And because a locally-rejected attempt never burned a delivery, nothing was dead-lettered and the queue drained *faster* than the unprotected run: 50.2 s versus 74.7 s. Protecting the dependency was also the fastest way to get the work done.

### Max delivery count and the dead-letter queue

Retries must terminate. The mechanism is a **delivery count** — a counter, maintained by the broker or by you, of how many times a message has been handed to a consumer. When it exceeds `max_delivery_count`, the message stops being retried and moves out of the main flow into a **dead-letter queue** (DLQ): a separate queue or topic holding messages that could not be processed.

The framing most teams get backwards:

> **The DLQ exists to unblock the pipeline. Dead-lettering is the design working, not the design failing.**

A message in the DLQ is no longer costing throughput, no longer filling logs, no longer blocking a partition, and is *preserved* for a human. The alternative — retrying forever — is not "not giving up"; it is trading an entire pipeline for one message.

What you write into the DLQ decides whether triage takes two minutes or two hours. The payload alone is nearly useless; you need enough to answer *what, from where, how many times, since when, why,* and *is it safe to replay*:

```json
{
  "dlq_reason": "max_delivery_count_exceeded",
  "message_id": "aa52e02aaa36211436a5ded5aea3ca9d",
  "idempotency_key": "4d322c7933c3a2b479432612620ed4c5",
  "partition_key": "order-05908",
  "original_topic": "orders.payments.v2",
  "original_partition": 3,
  "original_offset": 182400,
  "consumer_group": "payments-worker",
  "consumer_version": "2.14.3",
  "delivery_count": 12,
  "max_delivery_count": 12,
  "first_seen_at": "2023-11-14T22:13:20Z",
  "dead_lettered_at": "2023-11-14T22:17:34Z",
  "seconds_in_flight": 254.0,
  "failure_class": "transient",
  "last_error_code": "http_502",
  "error_codes_seen": ["http_502", "http_503", "read_timeout"],
  "stack_digest": "sha256:9f2c41ab",
  "payload": {"order_id": "order-05908", "amount_cents": 19938, "currency": "EUR"}
}
```

Four fields are load-bearing and routinely omitted. **`original_topic`/`partition`/`offset`** is the address you replay to; without it a redrive is guesswork. **`consumer_version`** tells you whether a deploy is the cause — if every record says `2.14.3` and none says `2.14.2`, you have found your incident. **`error_codes_seen`** distinguishes "one downstream was down the whole time" from "this message fails differently every time", which are different bugs. And **`idempotency_key`** is what makes replay safe at all.

### Where the retry lives — the architectural decision

This is the subtle part, and the part that separates a working design from a working-until-Tuesday one. "Retry with backoff" says nothing about *where the message waits during the backoff*, and that choice has completely different consequences.

**In-process retry.** The handler catches the error, sleeps, and tries again without releasing the message. Lowest latency, simplest code, no broker involvement. But for the entire backoff the message is still checked out: it holds the consumer slot, it holds the partition, and it still counts against the **visibility timeout** or lease. Sleep 32 seconds inside a handler with a 30-second lease and the broker concludes you died and redelivers to *another* consumer, which now processes it concurrently with you. Correct only for short retries — a few hundred milliseconds, two or three attempts, well inside the lease.

**Broker-level redelivery.** Do not acknowledge; the lease expires, the broker redelivers. Simple and durable — no timer of yours is lost to a restart. Two limits: the delay *is* the visibility timeout, one fixed value you probably tuned for something else, and every redelivery still arrives at the head of the same ordered partition, so it blocks exactly as in-process retry does.

**Retry topics / delay queues.** The message is **republished** to a separate topic on failure and acknowledged on the original. It leaves the main stream *immediately*, so the pipeline keeps flowing, and comes back later from a delayed consumer. Tiers give exponential backoff at the infrastructure level: `retry-5s` → `retry-1m` → `retry-10m` → DLQ.

When the broker has no native delayed delivery — Kafka has none — you implement it yourself. **Timestamp-and-requeue**: the tier consumer compares `now` to a `not_before` header and, if early, pauses the partition rather than requeuing (requeuing is a hot loop). Because a tier's messages are in arrival order and share one delay, checking the head is enough — everything behind it is younger. Or **per-tier topics** with a consumer that polls slowly. RabbitMQ has a third trick, below, using message TTL plus a dead-letter exchange.

The cost must be stated plainly: **a message parked to a retry topic loses its position, so ordering for its key is broken.** Whether that is acceptable is exactly the question [Lesson 07](../07-ordering-partition-keys-and-parallel-consumers/) taught you to ask.

| | In-process retry | Broker redelivery | Retry topic / delay queue |
|---|---|---|---|
| Delay control | exact, in your code | fixed = visibility timeout | per tier, arbitrary |
| Blocks the partition | **yes**, for the whole backoff | **yes**, every redelivery | **no** — it leaves immediately |
| Holds a consumer slot | yes | no | no |
| Survives consumer restart | no (timer lost) | yes | yes |
| Preserves ordering | yes | yes | **no** |
| Extra infrastructure | none | none | topics + consumers |
| Use when | retries are short, < lease | delay ≈ visibility timeout is fine | backoff is long, throughput matters |

The guidance in one line: **short retries in process, long retries in a retry topic, and broker redelivery when the visibility timeout happens to be the delay you wanted anyway.** If a retry will take longer than a fraction of your lease, it does not belong in the handler.

### Head-of-line blocking, measured

Now put the poison message back into an ordered partition and watch the three options play out. This is the most vivid measurement in the lesson.

A partition holds 40 messages for key `order-9182`, each taking 20 ms. Clean, it drains in 0.80 s at 50 messages/second. Message #12 is poison.

- **Halt** — retry in place and never give up (a broker redelivering forever, or no max delivery count). After 300 seconds: **12 processed, 27 blocked, 0.04 msg/s** — a **1,250× throughput collapse** from one malformed event, and it does not end. This is Tuesday afternoon.
- **Retry in place with a max delivery count** — the same blocking, bounded. The poison message exhausts 12 deliveries over 212 s of backoff, dead-letters, and the rest flow: **0.18 msg/s**, a 272× collapse, better only in that it terminates.
- **Park to a retry topic on the first failure** — republished and acknowledged immediately, so the partition never stalls: **0.80 s, 49.68 msg/s**, 1.01× the clean baseline.

The parked run pays its bill in a different currency, and the program prints it: **27 messages for key `order-9182` overtook the parked one.** Ordering for that key is gone.

So the three options are not "good, better, best". They are **skip** (break ordering, keep flowing), **park** (break ordering for that key, keep flowing, keep the message), and **halt** (preserve correctness absolutely, stop throughput). If ordering was a genuine correctness requirement — applying #13 before #12 corrupts state — halting may be *right*, and the correct response is to page a human rather than skip. If ordering was a habit, parking is obviously right. You cannot make this choice from inside the consumer; it comes from the domain.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Three ways to handle a poison message at offset twelve of an ordered partition. Retrying in place forever blocks 27 messages behind it and collapses throughput from 50 messages per second to 0.04. Retrying in place until max delivery count still blocks for 212 seconds at 0.18 messages per second. Parking the message to a retry topic on first failure keeps the partition at 49.68 messages per second, at the cost of 27 messages overtaking it and losing ordering for that key.">
  <defs>
    <marker id="l08-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One poison message at offset 12 — three responses, measured</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="132" rx="12" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="16" y="186" width="848" height="132" rx="12" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    <rect x="16" y="330" width="848" height="146" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-width="1.8" stroke-linejoin="round">
    <rect x="196" y="104" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="228" y="104" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="260" y="104" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="296" y="98" width="34" height="42" rx="5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="2.4"/>
    <rect x="344" y="104" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="376" y="104" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="408" y="104" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="440" y="104" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>

    <rect x="196" y="248" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="228" y="248" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="260" y="248" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="296" y="242" width="34" height="42" rx="5" fill="#7c5cff" fill-opacity="0.5" stroke="#7c5cff" stroke-width="2.4"/>
    <rect x="344" y="248" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="376" y="248" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="408" y="248" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="440" y="248" width="26" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4"/>

    <rect x="196" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="228" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="260" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="296" y="386" width="34" height="42" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="4 3"/>
    <rect x="344" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="376" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="408" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="440" y="392" width="26" height="30" rx="4" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f"/>
    <rect x="556" y="386" width="120" height="42" rx="7" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="700" y="386" width="76" height="42" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M313 148 A 22 16 0 1 1 336 122" marker-end="url(#l08-a2)" opacity="0.85"/>
    <path d="M313 292 A 22 16 0 1 1 336 266" marker-end="url(#l08-a2)" opacity="0.85"/>
    <path d="M320 386 L 320 362 L 616 362 L 616 382" marker-end="url(#l08-a2)" stroke="#7c5cff"/>
    <path d="M676 407 L 696 407" marker-end="url(#l08-a2)" stroke="#e0930f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="68" font-size="12" font-weight="700" fill="#e0930f">HALT — retry in place, never give up</text>
    <text x="34" y="86" font-size="9.5" opacity="0.85">the broker cannot hand you offset 13 until offset 12 is acknowledged</text>
    <text x="120" y="123" font-size="9.5" text-anchor="middle" opacity="0.9">processed</text>
    <text x="313" y="160" font-size="8.5" text-anchor="middle" font-weight="700" fill="#e0930f">15 attempts</text>
    <text x="405" y="153" font-size="9" text-anchor="middle" opacity="0.75">27 messages blocked, indefinitely</text>
    <text x="850" y="98" font-size="11" text-anchor="end" font-weight="700" fill="#e0930f">0.04 msg/s</text>
    <text x="850" y="116" font-size="9.5" text-anchor="end" opacity="0.9">1,250x collapse</text>
    <text x="850" y="134" font-size="9.5" text-anchor="end" opacity="0.9">12 done in 300s</text>
    <text x="850" y="156" font-size="9" text-anchor="end" opacity="0.75">ordering: intact</text>

    <text x="34" y="212" font-size="12" font-weight="700" fill="#7c5cff">IN PLACE, MAX DELIVERY 12 — bounded, still blocking</text>
    <text x="34" y="230" font-size="9.5" opacity="0.85">the same head-of-line block, but it terminates: 212s of backoff, then the DLQ</text>
    <text x="313" y="304" font-size="8.5" text-anchor="middle" font-weight="700" fill="#7c5cff">12 attempts</text>
    <text x="410" y="297" font-size="9" text-anchor="middle" opacity="0.75">27 messages blocked for 212s</text>
    <text x="850" y="242" font-size="11" text-anchor="end" font-weight="700" fill="#7c5cff">0.18 msg/s</text>
    <text x="850" y="260" font-size="9.5" text-anchor="end" opacity="0.9">272x collapse</text>
    <text x="850" y="278" font-size="9.5" text-anchor="end" opacity="0.9">39 done in 212s</text>
    <text x="850" y="300" font-size="9" text-anchor="end" opacity="0.75">ordering: intact</text>

    <text x="34" y="356" font-size="12" font-weight="700" fill="#0fa07f">PARK — republish to a retry topic on the FIRST failure, ack the original</text>
    <text x="120" y="411" font-size="9.5" text-anchor="middle" opacity="0.9">processed</text>
    <text x="313" y="443" font-size="8.5" text-anchor="middle" opacity="0.8">gone</text>
    <text x="405" y="443" font-size="9" text-anchor="middle" opacity="0.9">everything behind it flows</text>
    <text x="616" y="411" font-size="9.5" text-anchor="middle" font-weight="700">retry-5s / 1m / 10m</text>
    <text x="616" y="446" font-size="8.5" text-anchor="middle" opacity="0.8">665s of tiers, off the main path</text>
    <text x="738" y="411" font-size="9.5" text-anchor="middle" font-weight="700">DLQ</text>
    <text x="850" y="356" font-size="11" text-anchor="end" font-weight="700" fill="#0fa07f">49.68 msg/s</text>
    <text x="850" y="374" font-size="9.5" text-anchor="end" opacity="0.9">1.01x of clean</text>
    <text x="440" y="470" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">the bill: 27 messages for this key overtook the parked one — ordering for order-9182 is gone</text>
  </g>
</svg>
```

### DLQ operations — the part nobody teaches

A DLQ nobody looks at is a data-loss bucket with extra steps. Building one is 10% of the work; the other 90% is operational, and it is skipped almost universally.

**Alert on the rate of change, not the depth.** A DLQ holding 400 messages that arrived over six months is a backlog; one holding 40 that arrived in the last four minutes is an incident. The absolute number tells you almost nothing; the derivative tells you everything. Alert on **first arrival after a quiet period** — a DLQ empty for a week that now has one message is the highest-signal alert in this lesson, because it usually means a deploy just broke something and you are ninety seconds into it. Then rate, and only then depth.

**Triage means classifying the *population*, not reading messages.** Three shapes account for nearly everything, and the DLQ record tells them apart:

- **One bad producer deploy** — arrivals start abruptly, producer version uniform, `last_error_code` uniform and permanent, payloads sharing a defect. Roll back, then redrive after repair.
- **A downstream outage** — arrivals track a dependency's error rate, `failure_class` is `transient`, `error_codes_seen` full of `503`s and timeouts, `delivery_count` at maximum for all. Wait for recovery, then redrive unchanged: nothing is wrong with these messages.
- **A schema change** — arrivals begin at a producer deploy, errors are validation failures on one field, and *older* messages still process fine. [Lesson 12](../12-schema-evolution-and-event-contracts/) territory — make the consumer tolerant, then redrive.

**The redrive** replays DLQ messages back into the main queue once the cause is fixed. It is the most dangerous button in your infrastructure: a deliberate, concentrated burst of duplicates aimed at a system that just recovered. Everything in [Lesson 06](../06-delivery-semantics-and-idempotency/) is load-bearing here — and one detail in particular, which people do not see coming.

**Your dedup TTL must exceed the maximum time a message can sit in the DLQ.** Idempotency in practice means a store of processed keys with an expiry, because you cannot keep them forever. If a message was *partially applied* before failing — the card charged, then the acknowledgement timed out — replaying it is safe only while its idempotency key is still in that store. A message sitting in a DLQ for 6.2 hours with a 1-hour dedup TTL is no longer protected by anything:

```text
120 messages redriven, 35 of them already applied before the ack failed

dedup TTL 24 h  ->  35 suppressed,  0 double-charged,  EUR     0.00
dedup TTL  1 h  ->   0 suppressed, 35 double-charged,  EUR 4,622.09
```

Same code, same messages, same button. The only difference is a TTL. **Dedup TTL > DLQ retention** is not a tuning detail; it is a correctness invariant, and it is the reason the pre-redrive checklist in this lesson's runbook asks about it before anything else.

Three more operational rules. **Rate-limit the redrive** — replaying 50,000 messages at full speed into a service that just came back is how you cause the second outage. **Set DLQ retention longer than your triage SLA** — a 4-day retention with a team that triages weekly is silent data loss on a timer. And **quarantine repeat offenders**: a message that dead-letters, is redriven, and dead-letters again must not be redriven a third time automatically, or you have rebuilt the infinite retry loop with extra steps.

### Retries and idempotency are the same subject

Worth stating plainly, because it is the assumption underneath everything above: **every retry is a deliberate duplicate.**

You are re-sending a request that may have already succeeded. The timeout case makes this unavoidable — a read timeout tells you the *response* did not arrive and says nothing about whether the *request* was processed. The card may well be charged. Retrying without an idempotency key charges it again.

The chain is: at-least-once delivery means duplicates; retries mean *more* duplicates, concentrated; redrives mean a *burst* of them. If the consumer is not idempotent, every mechanism in this lesson makes your data worse rather than better. Retry logic on a non-idempotent consumer is not resilience — it is an amplifier for corruption.

### Two things that quietly make retries worse

**Amplification down a chain.** Retries multiply through hops. A retries 3× into B, which retries 3× into C, which retries 3× into D: one user request becomes `3 × 3 × 3 = 27` calls at the bottom, and the deepest service — usually the database — sees the largest multiple. Mitigations: retry at **one** layer, propagate a deadline so inner layers stop when the caller has already given up, and use retry budgets so the multiplication is bounded by a ratio rather than a product.

**Missing timeouts.** A retry policy without a timeout is not a retry policy. If a call can hang indefinitely your retry never fires, the consumer slot is held forever, and you have the worst outcome available: neither success, nor failure, nor retry. **An unbounded wait is worse than a failure**, because a failure is actionable and a hang is not. Every remote call needs an explicit timeout; it must be shorter than the visibility timeout of the message you are holding, and the total retry window shorter than any deadline you promised upstream.

## Build It

[`code/retries_and_dlq.py`](code/retries_and_dlq.py) runs six experiments on a virtual clock — nothing sleeps, every RNG is seeded, two runs print identical output. The core of the fleet simulation is a discrete-event loop with a rolling one-second window modelling the dependency's capacity cliff:

```python
calls += 1
window.append(t)
while window and window[0] <= t - 1.0:
    window.popleft()
success = t >= RECOVER_AT and len(window) <= CAP_RPS
```

That is the whole overload model, and it is deliberately harsh: a second carrying more than `CAP_RPS` requests is shed *entirely*, the way a service behaves once its connection or thread pool is exhausted — the utilisation cliff from [Lesson 01](../01-why-async-and-the-cost-of-coupling/), not a gentle degradation. It is what makes a synchronised retry wave self-defeating rather than merely wasteful.

The backoff strategies are the standard formulations, one line each:

```python
def s_exponential(rnd, attempt, prev):
    return min(CAP, BASE * 2 ** (attempt - 1))

def s_full_jitter(rnd, attempt, prev):
    return rnd.uniform(0.0, min(CAP, BASE * 2 ** (attempt - 1)))

def s_equal_jitter(rnd, attempt, prev):
    b = min(CAP, BASE * 2 ** (attempt - 1))
    return b / 2 + rnd.uniform(0.0, b / 2)

def s_decorrelated(rnd, attempt, prev):
    return min(CAP, rnd.uniform(BASE, max(BASE, prev * 3.0)))
```

Every strategy sees an *identical* arrival pattern, because arrival times come from their own generator seeded the same way for all five runs — otherwise the comparison would measure the arrivals rather than the strategy:

```python
arrivals = random.Random(SEED + 900)   # identical arrivals for every strategy
rnd = random.Random(SEED + seed_off)   # only the jitter differs
```

The histogram counts **retries only** (`attempt > 0`): the first delivery is identical under every policy, so including it would hide the thing being measured. The breaker is the textbook three-state machine, with the one detail that matters — a locally-rejected attempt never touches the network and never burns a delivery count.

```python
def allow(self, now):
    if self.state == "open":
        if now < self.open_until:
            return False                 # fail fast: no network call at all
        self.state = "half-open"         # cooldown expired: one probe may pass
    if self.state == "half-open":
        self.probes += 1
    return True
```

Run it:

```console
$ python retries_and_dlq.py
== 1. CLASSIFY BEFORE YOU RETRY ==
  error code        class      action    why
  http_503          transient  retry     the world may be different in 2 seconds
  http_429          transient  retry     the world may be different in 2 seconds
  read_timeout      transient  retry     the world may be different in 2 seconds
  db_deadlock       transient  retry     the world may be different in 2 seconds
  http_400          permanent  DLQ now   no amount of waiting changes the answer
  schema_invalid    permanent  DLQ now   no amount of waiting changes the answer
  http_403          permanent  DLQ now   no amount of waiting changes the answer
  hard_decline      permanent  DLQ now   no amount of waiting changes the answer

  workload: 600 messages  ->  425 clean,  96 transient (heal in 1-3 attempts),  79 permanently broken
  policy               attempts  wasted  succeeded  dead-lettered  recoverable lost
  retry everything        1,112     316        521             79                 0
  classify first            796       0        521             79                 0
  never retry               600       0        425            175                96
  classifying first saves 316 attempts (28.4% of all work) and costs nothing: 521 messages succeed either way
  never retrying is the mirror-image mistake: 96 messages dead-lettered that one retry saves

== 2. BACKOFF AND JITTER: 200 clients, a dependency that dies at t=0 ==
  down until t=45s, then serves 60 req/s; a second carrying more than that is shed entirely
  base 2s  cap 32s  floor 0.5s  max delivery 12  horizon 400s
  strategy          calls  in outage  peak/s  peak/s @45s+    ok   DLQ    drain
  fixed 5s          2,220      1,800     112           112   180    20    57.0s
  exponential       1,440      1,000     112           112   200     0   160.0s
  + full jitter     1,494      1,294     109            15   200     0    74.7s
  + equal jitter    1,271      1,071      99            15   200     0    76.3s
  + decorrelated    1,459      1,261     112            14   198     2    77.0s

  retries per 2s bucket, t=0 to t=160s   scale '.:-=+*#%@'   blank = 0, @ = 200
                  0s        20        40        60        80        100       120       140
  fixed 5s          += @ += @ += @ += @ += *  =                                                   |
  exponential      @ @   @       @               @               *               =               .|
  + full jitter   +%#=--::.::...........................                                          |
  + equal jitter  -#*::=-...:::..  ......................                                         |
  + decorrelated   @:+-::::-::..:........................                                         |
  the dependency recovers 22 characters in, and that is the column that matters:
  peak retries in one second after recovery - exponential 112/s vs full jitter 15/s, 7x lower.
  Un-jittered strategies hit the 60 req/s cliff on every wave, so a recovered dependency is knocked
  straight back over; the jittered ones arrive under it and get through.

== 3. RETRY BUDGETS AND CIRCUIT BREAKERS (all on full jitter) ==
  budget: retries capped at 10/s (10% of a 100 req/s group); denied retries park to 5s/30s/120s
  breaker: 5 consecutive failures -> open 5s -> half-open probe -> closed
  protection            calls  in outage  peak/s  peak/s @45s+    ok  parks    drain
  none                  1,494      1,294     109            15   200      0    74.7s
  retry budget            704        504      15            11   200    493   195.2s
  circuit breaker         213         13       3             3   200      0    50.2s
  budget + breaker        213         13       3             3   200      0    50.3s
  load delivered to the dying dependency: 1,294 calls unprotected  ->  13 with a breaker (100x less)
  the breaker rejected 1,800 attempts locally and spent 9 half-open probes finding out when to close again

== 4. DELIVERY COUNT -> DLQ: what a dead-letter record must carry ==
  120 messages exhausted delivery count 12 during a payment-API outage.
  12 deliveries at base 2s / cap 32s = 254s of retry window. One record, in full:
    {
      "dlq_reason": "max_delivery_count_exceeded",
      "message_id": "aa52e02aaa36211436a5ded5aea3ca9d",
      "idempotency_key": "4d322c7933c3a2b479432612620ed4c5",
      "partition_key": "order-05908",
      "original_topic": "orders.payments.v2",
      "original_partition": 3,
      "original_offset": 182400,
      "consumer_group": "payments-worker",
      "consumer_version": "2.14.3",
      "delivery_count": 12,
      "max_delivery_count": 12,
      "first_seen_at": "2023-11-14T22:13:20Z",
      "dead_lettered_at": "2023-11-14T22:17:34Z",
      "seconds_in_flight": 254.0,
      "failure_class": "transient",
      "last_error_code": "http_502",
      "last_error": "502 Bad Gateway",
      "error_codes_seen": [
        "http_502",
        "http_503",
        "read_timeout"
      ],
      "stack_digest": "sha256:9f2c41ab",
      "payload": {
        "order_id": "order-05908",
        "amount_cents": 19938,
        "currency": "EUR"
      }
    }
  every field answers a triage question: what, from where, how many times, since when,
  why, and - via idempotency_key - whether it is safe to replay

== 5. POISON MESSAGE AND HEAD-OF-LINE BLOCKING ==
  one ordered partition, 40 messages for key order-9182, #12 is poison, 20 ms each
  strategy                          elapsed  done  blocked   msg/s  attempts  out of order
  halt: retry in place forever       300.0s    12       27    0.04        15             0
  in place, max delivery -> DLQ      212.0s    39        0    0.18        12             0
  park to retry topic on 1st fail      0.8s    39        0   49.68         1            27
  poison message ends: halt = still retrying,  inplace = dead-lettered,  parked = parked to retry-5s
  a clean partition drains in 0.80s at 50 msg/s. One malformed message costs 1,250x throughput if you never
  give up, and 272x if you give up after 12 deliveries. Parking costs 1.01x throughput - it is
  effectively free - and the bill is paid in ordering instead: 27 messages for key order-9182 overtook
  the parked one. The parked copy walks 5s/60s/600s = 665s of tiers and then DLQs, none of it on the main partition.

== 6. REDRIVE: safe only if the dedup window outlived the DLQ ==
  the payment API is healthy again. Redriving 120 messages that sat 6.2 h in the DLQ.
  35 of them had already moved money before the ack failed - they are duplicates by construction.
  dedup TTL     replayed  processed  suppressed  DOUBLE CHARGED           value
      24 h            120         85          35               0        EUR 0.00
       1 h            120         85           0              35    EUR 4,622.09
  same code, same messages, same redrive button. The only difference is whether the idempotency
  keys were still in the dedup store after 6.2 h. Dedup TTL > max time in DLQ is not a tuning
  detail; it is the difference between a clean replay and charging customers twice.

== 7. SUMMARY: same 200 messages, seven ways to attempt them ==
  strategy                        calls  outage load  peak/s @45s+   DLQ  parks    ok    drain
  fixed 5s                        2,220        1,800           112    20      0   180    57.0s
  exponential                     1,440        1,000           112     0      0   200   160.0s
  + full jitter                   1,494        1,294            15     0      0   200    74.7s
  + equal jitter                  1,271        1,071            15     0      0   200    76.3s
  + decorrelated                  1,459        1,261            14     2      0   198    77.0s
  full jitter + retry budget        704          504            11     0    493   200   195.2s
  full jitter + circuit breaker     213           13             3     0      0   200    50.2s
  full jitter + budget + breaker    213           13             3     0      0   200    50.3s
  every row delivered the same work. What changed is how much damage the attempt did
  to the dependency, how many messages survived, and how long the queue took to drain.
```

Read the histogram first, because it is the picture the rest of the lesson argues for.

**The shape of a herd is visible in ASCII.** `fixed 5s` renders as a metronome — `+= @ += @ += @` — identical spikes every five seconds, because a constant delay preserves synchronisation exactly. `exponential` renders as spikes that get *further apart* but never *shorter*: `@ @   @       @               @`. That is the failure of un-jittered backoff in one line — it reduces the *frequency* of the waves and does nothing about their *amplitude*, because every client still computes the same number. The jittered rows are a different object entirely: a dense smear that decays, `+%#=--::.::......`, with no spike after the first few seconds.

**The peak is the number that matters, and it is 7×.** After recovery, exponential delivers 112 retries in one second into a dependency that can take 60; full jitter delivers 15. Watch what that does to drain time — exponential **160.0 s**, full jitter **74.7 s**. The polite strategy finished in less than half the time, because every wave that trips the capacity cliff is a wave that has to happen again.

**`fixed 5s` dead-letters 20 messages, and nothing else does.** It burns all 12 deliveries inside 57 seconds — 2,220 calls, the most load of any strategy — and 20 messages run out of attempts before the dependency is healthy enough to serve them. That is the cost of a retry window shorter than the outage, and a constant delay spends that window fast and evenly, which is the worst way to spend it.

**Classification is nearly a third of the work.** 79 permanently-broken messages retried 5 times each cost 316 attempts that could not possibly succeed — 28.4% of all work — and eliminating them changes the success count not at all: 521 either way. Never retrying is the mirror error, dead-lettering **96 messages that a single retry would have saved.** Both are one-line fixes in the same place.

**The circuit breaker is worth two orders of magnitude** — 1,294 calls into the dying dependency unprotected, **13** with a breaker, plus 1,800 attempts rejected locally that never became packets. It also drained *fastest* of everything at 50.2 s: restraint was the optimal strategy for throughput too. The retry budget makes the other trade, cutting outage load to 504 calls with all 200 messages surviving, paid for in a 195.2 s drain.

**One poison message costs 1,250× throughput.** 50 msg/s clean; 0.04 msg/s when a single malformed event is retried in place forever, 27 messages stuck behind it, no end. A max delivery count improves that only to 0.18 msg/s. Parking on the first failure costs 1.01×, and the real bill is beside it: 27 messages overtook the parked one and ordering for that key is gone.

**And the redrive.** 120 messages, 35 already applied. A 24-hour dedup TTL against a 6.2-hour stay in the DLQ: 35 suppressed, zero double charges. A 1-hour TTL: **35 double charges, EUR 4,622.09.** Nothing else differed. The idempotency work from Lesson 06 is not finished until its TTL has been checked against the DLQ retention of every queue that can redrive into it.

The whole path a failing message walks — and the two constraints that make it safe — fits in one picture:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="The lifecycle of a failing message. A delivery is classified: permanent failures go straight to the dead-letter queue, transient ones pass a retry budget and circuit breaker, then wait a jittered capped-exponential backoff and are redelivered until the delivery count is exhausted, at which point they are dead-lettered. From the dead-letter queue an operator triages and redrives, which is safe only if the consumer is idempotent and the dedup TTL is longer than the time spent in the queue.">
  <defs>
    <marker id="l08-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One failing message, end to end</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="86" width="118" height="56" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="176" y="86" width="128" height="56" rx="10" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
    <rect x="344" y="86" width="150" height="56" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="534" y="86" width="150" height="56" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="724" y="86" width="138" height="56" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="344" y="228" width="340" height="60" rx="11" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="2.4"/>
    <rect x="724" y="228" width="138" height="60" rx="11" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="18" y="228" width="290" height="60" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="18" y="322" width="844" height="84" rx="12" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-dasharray="7 6"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M136 114 L 170 114" marker-end="url(#l08-a3)"/>
    <path d="M304 114 L 338 114" marker-end="url(#l08-a3)"/>
    <path d="M494 114 L 528 114" marker-end="url(#l08-a3)"/>
    <path d="M684 114 L 718 114" marker-end="url(#l08-a3)"/>
    <path d="M793 142 L 793 222" marker-end="url(#l08-a3)"/>
    <path d="M724 258 L 690 258" marker-end="url(#l08-a3)"/>
    <path d="M344 258 L 314 258" marker-end="url(#l08-a3)"/>
    <path d="M77 228 L 77 148" marker-end="url(#l08-a3)"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 4">
    <path d="M240 142 L 240 190 L 514 190 L 514 222" marker-end="url(#l08-a3)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="77" y="110" font-size="10.5" font-weight="700" text-anchor="middle">DELIVER</text>
    <text x="77" y="127" font-size="8.5" text-anchor="middle" opacity="0.85">count += 1</text>
    <text x="240" y="105" font-size="10.5" font-weight="700" text-anchor="middle">CLASSIFY</text>
    <text x="240" y="121" font-size="8.5" text-anchor="middle" opacity="0.85">transient?</text>
    <text x="240" y="135" font-size="8.5" text-anchor="middle" opacity="0.85">permanent?</text>
    <text x="258" y="180" font-size="9" font-weight="700" fill="#e0930f">permanent → straight to DLQ, attempt 1</text>
    <text x="419" y="105" font-size="10.5" font-weight="700" text-anchor="middle">BUDGET + BREAKER</text>
    <text x="419" y="121" font-size="8.5" text-anchor="middle" opacity="0.85">may I even try?</text>
    <text x="419" y="135" font-size="8.5" text-anchor="middle" opacity="0.85">1,294 calls → 13</text>
    <text x="609" y="105" font-size="10.5" font-weight="700" text-anchor="middle">BACKOFF + JITTER</text>
    <text x="609" y="121" font-size="8.5" text-anchor="middle" opacity="0.85">min(cap, base·2ⁿ)</text>
    <text x="609" y="135" font-size="8.5" text-anchor="middle" opacity="0.85">peak 112/s → 15/s</text>
    <text x="793" y="105" font-size="10.5" font-weight="700" text-anchor="middle">WAIT WHERE?</text>
    <text x="793" y="121" font-size="8.5" text-anchor="middle" opacity="0.85">in-process · broker</text>
    <text x="793" y="135" font-size="8.5" text-anchor="middle" opacity="0.85">· retry topic</text>

    <text x="793" y="252" font-size="10" font-weight="700" text-anchor="middle">count &gt; max?</text>
    <text x="793" y="270" font-size="8.5" text-anchor="middle" opacity="0.85">254s retry window</text>
    <text x="514" y="252" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">DEAD-LETTER QUEUE</text>
    <text x="514" y="272" font-size="9" text-anchor="middle" opacity="0.95">payload + offset + delivery count + errors + idempotency key</text>
    <text x="163" y="252" font-size="10.5" font-weight="700" text-anchor="middle">TRIAGE → FIX → REDRIVE</text>
    <text x="163" y="272" font-size="8.5" text-anchor="middle" opacity="0.85">rate-limited replay to the source</text>

    <text x="440" y="346" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">the two invariants that make the loop safe</text>
    <text x="234" y="370" font-size="10" text-anchor="middle" font-weight="700">1 · the consumer is idempotent</text>
    <text x="234" y="388" font-size="9" text-anchor="middle" opacity="0.9">every retry is a deliberate duplicate (Lesson 06)</text>
    <text x="646" y="370" font-size="10" text-anchor="middle" font-weight="700">2 · dedup TTL &gt; time in DLQ</text>
    <text x="646" y="388" font-size="9" text-anchor="middle" opacity="0.9">24h TTL: 0 double charges · 1h TTL: EUR 4,622.09</text>
  </g>
</svg>
```

## Use It

Every broker implements these primitives; only the vocabulary changes.

**Amazon SQS (Simple Queue Service)** — closest to the lesson's model. The delivery count is `ApproximateReceiveCount`; the DLQ is a **redrive policy** on the source queue:

```json
{
  "maxReceiveCount": 5,
  "deadLetterTargetArn": "arn:aws:sqs:eu-west-1:123456789012:payments-dlq"
}
```

`maxReceiveCount` is the max delivery count; SQS increments `ApproximateReceiveCount` on every receive and moves the message when it exceeds the limit. Read that counter in your handler — it is how you know you are on the last attempt. For tiered retries, SQS has **delay queues** and per-message `DelaySeconds` (up to 15 minutes), a native delayed-delivery primitive: publish with `DelaySeconds: 300` and you have a `retry-5m` tier with no consumer of your own. And the **redrive-to-source** API (`StartMessageMoveTask`) replays a DLQ back to its origin with an optional `MaxNumberOfMessagesPerSecond` — the rate-limited redrive this lesson insists on, available as a parameter. Set it.

**RabbitMQ** — dead-lettering is a routing rule. A queue declared with `x-dead-letter-exchange` republishes messages there when they are rejected (AMQP 0-9-1's `basic.reject` carries a `requeue` bit; reject with `requeue=false` and the message dead-letters), when they expire, or when the queue overflows:

```python
channel.queue_declare("payments", arguments={
    "x-dead-letter-exchange": "payments.dlx",
    "x-delivery-limit": 5,            # quorum queues: the max delivery count
})
# the classic delayed-retry trick: a queue whose ONLY job is to expire messages
channel.queue_declare("payments.retry-30s", arguments={
    "x-message-ttl": 30000,           # every message expires after 30s...
    "x-dead-letter-exchange": "payments.main",   # ...and is dead-lettered back to the main queue
})
```

That second declaration is worth understanding rather than copying: RabbitMQ has no native delayed delivery, so you build one from a queue with a TTL and a dead-letter exchange pointing home. Nothing consumes `payments.retry-30s`; messages simply age out and get routed back. Note the trap — TTL expiry is evaluated at the *head* of the queue, so a queue mixing TTLs will hold a short-TTL message behind a long-TTL one. One TTL per tier queue, always. (The `rabbitmq_delayed_message_exchange` plugin does per-message delays properly, if you can install plugins.)

**Apache Kafka** — has *neither* per-message redelivery *nor* a native DLQ, and understanding why is the best teaching moment in this section. A Kafka partition is an append-only **log** ([Lesson 05](../05-the-log-offsets-and-replay/)), and a consumer's position in it is a single integer offset. There is no per-message acknowledgement to withhold and no per-message state to increment, because the only state is "how far have I read". You cannot leave message 12 un-acknowledged and take message 13; the offset would have to be in two places at once. That model buys cheap replay and enormous throughput, and the price is that **redelivery and dead-lettering are not primitives you can be given — they are patterns you must build.** The retry-topic pattern is the direct consequence:

```text
orders.payments.v2   --fail-->  orders.payments.retry-5s   (consumer waits, republishes)
                     --fail-->  orders.payments.retry-1m
                     --fail-->  orders.payments.retry-10m
                     --fail-->  orders.payments.DLQ        (nothing consumes; humans triage)
```

The delivery count lives in a header you increment yourself; the delay is a consumer that checks `not_before` and pauses the partition rather than requeuing. Kafka Connect formalises the DLQ end with `errors.tolerance=all`, and will add the original topic, partition and offset as headers if you ask — precisely the triple from the record above:

```text
errors.tolerance=all
errors.deadletterqueue.topic.name=orders.payments.DLQ
errors.deadletterqueue.context.headers.enable=true
```

**Google Cloud Pub/Sub** — a subscription carries a dead-letter policy directly, and the delivery count arrives on the message as `delivery_attempt`:

```yaml
deadLetterPolicy:
  deadLetterTopic: projects/acme/topics/payments-dlq
  maxDeliveryAttempts: 5     # minimum 5, maximum 100
```

Pub/Sub dead-letters to a **topic**, not a queue — so you attach a subscription to it and your triage tooling is just another subscriber. It also exposes `minimumBackoff` / `maximumBackoff` on the subscription's `retryPolicy`: broker-side capped exponential backoff you configure rather than write.

**The default nobody checks.** Most client libraries ship a retry configuration with **no jitter** — a fixed delay, or plain exponential, exactly the two strategies the histogram shows failing. Some ship with retries *on* and a max attempt count you did not choose, which quietly multiplies through every hop in your chain. Read the actual defaults for every client in your critical path and set jitter explicitly. It is one parameter, it is almost never the default, and this lesson measured it at 7× peak load and half the drain time.

## Think about it

1. Your consumer gets a read timeout calling the payment API. Classify it. Then explain why this specific error is more dangerous than a `503`, and what must be true of your handler before retrying it is safe at all.

2. A colleague sets `max_attempts = 3` on every consumer in a 300-instance fleet and calls the retry-amplification problem solved. Using the fleet numbers above, explain what a struggling dependency actually experiences, and what a retry budget bounds that a per-request limit cannot.

3. `fixed 5s` was the only strategy to dead-letter messages during the outage — 20 of them — despite making the most attempts of any strategy (2,220). Explain the mechanism, and compute the `base`, `cap` and `max_delivery_count` you would need for a consumer to survive a 20-minute downstream outage without dead-lettering anything.

4. Your `OrderShipped` consumer processes a partition keyed by `order_id` and ordering is a correctness requirement: `ShipmentCreated` must be applied before `ShipmentDelivered`. A `ShipmentCreated` message is poison. Which of skip, park, or halt is correct here, and what should the consumer do *in addition* to the mechanical choice?

5. Your DLQ alert fires on depth > 100. It has never fired. Give two distinct scenarios in which real, serious data loss happens without that alert ever firing, and state the alert you would add for each.

6. You are about to redrive 50,000 messages that have been in the DLQ for three days. Your dedup store has a 48-hour TTL. Walk through what happens to a message that was partially applied before it dead-lettered, and describe the two independent changes that would each have prevented the damage.

## Key takeaways

- **Classify before you retry.** Transient failures (timeouts, `5xx`, `429`, deadlocks) may succeed later; permanent ones (`400`, schema violations, business rejections) never will and must go straight to the dead-letter path. Not classifying cost **316 wasted attempts, 28.4% of all work**, with zero change in messages succeeding. The mirror-image mistake — never retrying — dead-lettered **96 recoverable messages**. RFC 9110's `4xx`/`5xx` split gives most of the map; ambiguous cases like `404` need an explicit written rule.
- **Backoff should be capped exponential, and its three parameters are a service-level decision.** `base` sets responsiveness to blips, `cap` the steady-state rate during a long outage, and with `max_delivery_count` they define the **total retry window** — 254 seconds here — which is how long a message survives an outage before a human is involved. Get it wrong and you dead-letter healthy messages: `fixed 5s` lost 20 by spending its whole window in 57 seconds.
- **Jitter is not optional.** Backoff spreads retries in *time*; only jitter spreads them across *clients*. Without it, clients that failed together retry together forever, and the reward for recovering is the whole backlog in one second. Measured: **112 retries/s peak for plain exponential versus 15/s with full jitter — 7× lower — and drain time halved, 160.0 s to 74.7 s**, on the same number of attempts. Most client libraries default to no jitter.
- **A per-request retry limit does not bound fleet load.** Three hundred clients at 3 attempts each is 3× amplification aimed at a dependency precisely when it is weakest. A **retry budget** caps retries as a *fraction* of traffic (10% to start) and so holds regardless of client count — 504 outage calls instead of 1,294, no messages lost, paid for in drain time.
- **A circuit breaker fails fast and protects both sides.** Closed → N consecutive failures → open (reject locally, no network call) → cooldown → half-open (one probe) → closed. It cut load on the dying dependency **from 1,294 calls to 13, a 100× reduction**, and drained *fastest of every strategy* at 50.2 s: holding the fleet back beat hammering.
- **The DLQ exists to unblock the pipeline; dead-lettering is the design working.** Write the full record — original topic/partition/offset (the replay address), delivery count, timestamps, error class and history, consumer version, and the **idempotency key**. Alert on **rate of change and first arrival after quiet**, never depth alone.
- **Where the retry waits matters more than how long it waits.** In-process retry blocks the partition and holds the consumer slot for the whole backoff, and must stay well inside the visibility timeout. Broker redelivery is durable but its delay is fixed and it still blocks. **Retry topics** get the message out of the main stream immediately — at the explicit cost of ordering for that key. Short retries in process, long retries in a retry topic.
- **A poison message in an ordered partition is a throughput cliff with only three moves.** Retrying in place forever collapsed throughput from 50 msg/s to **0.04 msg/s — 1,250× — with 27 messages blocked indefinitely**; a max delivery count bounded it only to 0.18 msg/s; parking cost **1.01×, effectively nothing**, and the bill was 27 messages overtaking it. Skip, park, or halt — only the domain knows whether ordering was correctness or habit.
- **Every retry is a deliberate duplicate; a redrive is a burst of them.** The invariant nobody writes down: **dedup TTL must exceed the maximum time a message can sit in the DLQ.** Replaying the same 120 messages after 6.2 hours produced 0 double charges with a 24-hour dedup window and **35 double charges worth EUR 4,622.09 with a 1-hour one.** Same code, same button, one TTL.

Next: [Backpressure, Consumer Lag & Flow Control](../09-backpressure-lag-and-flow-control/) — retries and parking both push work into the future, which means the queue grows. The next lesson is about what to do when it grows faster than you can drain it, how to measure that in seconds rather than message counts, and how to slow a producer down without breaking it.
