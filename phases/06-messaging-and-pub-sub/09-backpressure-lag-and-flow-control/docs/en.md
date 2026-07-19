# Backpressure, Consumer Lag & Flow Control

> Lesson 1 sold you the queue as a shock absorber. This lesson collects the bill. A queue absorbs a *burst*; it cannot absorb a *sustained* rate mismatch, and the difference between those two words is the difference between a graph that recovers on its own and an outage that ends with you choosing which four hours of data to delete. We build the lag simulator, read the shapes, size the prefetch, and watch an autoscaler make things worse.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Retries, Backoff, Dead-Letter Queues & Poison Messages](../08-retries-backoff-and-dead-letter-queues/)
**Time:** ~75 minutes

## The Problem

At 14:00 you deploy a change to the `payments-consumer`. It is a good change: each `PaymentAuthorized` message now gets enriched with the customer's loyalty tier before it goes downstream, which means one synchronous call to `loyalty-api` inside the handler. Per-message processing time goes from 4 ms to 16 ms. Nobody notices, because nothing is *broken* — every message is still processed correctly, the error rate is zero, the CPU graph is calm, and the dashboards are green.

Four consumers, each of which used to handle 250 messages/second, now handle 62.5. Your fleet's capacity has gone from 1,000/s to 250/s. The producers are still sending 800/s, exactly as they were this morning.

Do the arithmetic, because nobody does until 19:00:

```text
arrival  lambda = 800 msg/s
capacity mu     = 250 msg/s
backlog grows at  800 - 250 = 550 messages/second, forever

  +1h (15:00)    1,979,999 messages behind      41 minutes of data
  +3h (17:00)    5,939,998 messages behind    2h 03m of data
  +5h (19:00)    9,899,997 messages behind    3h 26m of data
```

Somebody finally looks at the queue depth at 19:00 and sees 9.9 million. The first instinct — *"the queue is fine, it has depth, that's what queues are for"* — is exactly the instinct that let this run for five hours. A queue's depth is not a buffer you get to spend. It is a **debt counter**.

Now three things are true at once, and all of them are bad.

**The broker's disk is a real object.** 9.9 million messages of a few kilobytes each is tens of gigabytes on the broker's volume, replicated across brokers. When that volume fills, the broker stops accepting writes — and the write it stops accepting is a *producer's*. Your checkout service, which was supposed to be protected from slow downstreams by the queue, now gets an error on publish. The outage has propagated **backwards**, into the very services the queue existed to insulate. This is the failure mode people find most surprising: backpressure travelling upstream from a consumer, through the broker, into an unrelated, perfectly healthy producer.

**Retention is a delete, not an error.** Your topic has a six-hour retention window. Messages older than six hours are removed by the broker on a schedule, whether or not anyone has read them. Time lag is growing at 0.6875 seconds per second of wall clock, so it reaches six hours at **22:43**. At 22:43 the broker begins deleting unread payment authorizations at 800 per second. There is no error. No exception is raised, no HTTP status is returned, nothing is logged on your side. The most sinister part: the lag graph goes **flat**. Depth stops growing, because the head is being deleted as fast as the tail is being written. An engineer glancing at the dashboard at 23:00 sees a flat line and thinks the incident is over. It is; the data is gone.

**And fixing the consumer is not fixing the incident.** Suppose you revert at 19:00 and capacity returns to 1,000/s. You are still receiving 800/s, so you have 200/s of headroom to work through a backlog of 9.9 million messages. That takes **13 hours 45 minutes**. Every downstream system reading that stream — fraud scoring, the ledger, the customer's order-status page — is looking at hours-old data until 08:45 tomorrow morning. You fixed the bug at 19:00 and the *business impact* runs until the next morning.

The mirror-image failure is quicker and dumber. A different team, tuning the same consumer for throughput, sets its prefetch to 10,000 — "so it doesn't waste time on network round trips". Each message is 16 KB. Four consumers × 10,000 × 16 KB is **625 MB** of messages held in memory against a 256 MB container limit. The consumers are OOM-killed, every unacknowledged message they held is redelivered, they start again, pull 10,000 each, and are killed again. The flow-control setting that was supposed to make the consumer faster turned it into a crash loop that never acknowledges anything.

Every one of these is a **flow control** problem, and flow control is the last major thing standing between the primitives you have built and a messaging system that survives a Tuesday.

## The Concept

### Lag is the metric — and there are two of them

**Consumer lag** is the gap between what has been produced and what has been processed. It is the single most important health metric of any consumer, and it comes in two forms that people routinely confuse.

**Count lag** is how many messages are behind. In a log (Lesson 5) it is the **offset lag**: the log-end offset minus the consumer group's committed offset, per partition. In a queue (Lesson 3) it is the **queue depth**: the number of messages sitting unconsumed. It is the number every broker exposes first and the number every dashboard shows.

**Time lag** is how old the oldest unprocessed message is. If the message at the head of the backlog was produced 47 seconds ago, your time lag is 47 seconds — you are 47 seconds behind reality.

Count lag alone is nearly useless, and this is not a stylistic complaint. Consider being told *"the backlog is 50,000 messages."* Is that bad? You cannot answer. If you drain 25,000/s, that is two seconds of backlog and it is fine. If you drain 50/s, that is 1,000 seconds — nearly seventeen minutes — and you are in an incident. **A count means nothing without a rate**, and the rate changes constantly, which means the meaning of the number on your dashboard changes constantly without the number changing at all.

Time lag has none of these problems, because it is already in the units of every decision you will make:

- Your SLA says orders confirm within 30 seconds. Time lag is directly comparable to 30 seconds.
- Your retention is 6 hours. Time lag is directly comparable to 6 hours, and the difference is **your deadline for irrecoverable data loss**.
- A human asking "how far behind are we?" wants an answer in minutes, not messages.

So: **alert on count lag if you like; page on time lag.**

The conversion between them is **Little's Law**, `L = λW` (Little, *A Proof for the Queuing Formula: L = λW*, Operations Research 9(3), 1961), which Lesson 1 introduced as the tool for sizing a consumer pool. Rearranged for lag it says `W = L / λ`: time lag equals count lag divided by the rate. But *which* rate? This turns out to matter enormously.

The backlog was **built by arrivals**. The set of messages currently unprocessed is exactly the set that arrived between the head's timestamp and now, so the exact identity uses the **arrival** rate:

```text
count lag  =  integral of lambda over the lag window
time lag   =  count lag / lambda          <- exact, if lambda was steady over that window
```

The conversion that actually appears on dashboards and in runbooks uses the **drain** rate — `time lag ≈ count lag / drain rate` — and it answers a genuinely different question: *"how long would this take to clear if arrivals stopped?"* Arrivals never stop. The two converge only when λ = μ, which is to say only when nothing is wrong. In the measured run below, the drain-rate estimate under-reads by 17% while a burst is draining and over-reads by 21% during sustained overload — and both errors point the wrong way for the decision being made. Under-reading tells you the situation is better than it is precisely when you are furthest behind.

The practical consequence: **compute time lag from message timestamps, do not derive it from count lag.** Every serious broker gives you a way to do this, and the `Use It` section names them.

### Reading the derivative, not the value

Here is the skill that separates someone who can fix a lag incident from someone who can only escalate it: **the value of the lag number is nearly meaningless; its shape over the last thirty minutes tells you what is wrong.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 566" width="100%" style="max-width:840px" role="img" aria-label="Six consumer lag shapes and what each one means. Flat and nonzero is healthy. A straight linear rise is sustained under-capacity. A sharp rise followed by a slow decline is a burst being absorbed. A sawtooth is a batch producer. Repeated narrow spikes are rebalances at deploy time. A rise that flattens at a ceiling is the broker deleting your data at the retention limit.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The lag graph's SHAPE is the diagnosis — its value is not</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="268" height="240" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    <rect x="306" y="44" width="268" height="240" rx="12" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
    <rect x="596" y="44" width="268" height="240" rx="12" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff"/>
    <rect x="16" y="296" width="268" height="240" rx="12" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
    <rect x="306" y="296" width="268" height="240" rx="12" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
    <rect x="596" y="296" width="268" height="240" rx="12" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
    <path d="M30 152 L 270 152"/><path d="M320 152 L 560 152"/><path d="M610 152 L 850 152"/>
    <path d="M30 404 L 270 404"/><path d="M320 404 L 560 404"/><path d="M610 404 L 850 404"/>
  </g>

  <path d="M30 136 L 70 132 L 110 138 L 150 133 L 190 137 L 230 132 L 270 136" fill="none" stroke="#0fa07f" stroke-width="2.6"/>
  <path d="M320 148 L 560 82" fill="none" stroke="#e0930f" stroke-width="2.6"/>
  <path d="M610 148 L 640 84 L 850 146" fill="none" stroke="#3553ff" stroke-width="2.6"/>
  <path d="M30 146 L 32 90 L 74 144 L 76 90 L 118 144 L 120 90 L 162 144 L 164 90 L 206 144 L 208 90 L 250 144 L 252 108 L 270 122" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
  <path d="M320 140 L 366 140 L 376 88 L 386 140 L 436 140 L 446 88 L 456 140 L 506 140 L 516 88 L 526 140 L 560 140" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
  <path d="M610 148 L 706 96 L 726 90 L 850 90" fill="none" stroke="#e0930f" stroke-width="2.8"/>
  <path d="M610 90 L 850 90" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="6 5" opacity="0.85"/>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="150" y="70" font-size="11.5" font-weight="700" text-anchor="middle">FLAT AND NONZERO</text>
    <text x="150" y="182" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">HEALTHY</text>
    <text x="34" y="206" font-size="9">Consumers keep pace. The</text>
    <text x="34" y="222" font-size="9">standing backlog is one poll</text>
    <text x="34" y="238" font-size="9">cycle of arrivals — it should</text>
    <text x="34" y="254" font-size="9">never be zero.</text>
    <text x="150" y="274" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: none</text>

    <text x="440" y="70" font-size="11.5" font-weight="700" text-anchor="middle">STRAIGHT LINEAR RISE</text>
    <text x="440" y="182" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">SUSTAINED UNDER-CAPACITY</text>
    <text x="324" y="206" font-size="9">mu &lt; lambda and will stay that</text>
    <text x="324" y="222" font-size="9">way. Extrapolate the line to</text>
    <text x="324" y="238" font-size="9">the retention window — that</text>
    <text x="324" y="254" font-size="9">intercept is your deadline.</text>
    <text x="440" y="274" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: add capacity NOW</text>

    <text x="730" y="70" font-size="11.5" font-weight="700" text-anchor="middle">SPIKE, THEN SLOW DECLINE</text>
    <text x="730" y="182" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">A BURST, BEING ABSORBED</text>
    <text x="614" y="206" font-size="9">The system is working exactly</text>
    <text x="614" y="222" font-size="9">as designed. Recovery time is</text>
    <text x="614" y="238" font-size="9">excess / headroom — compute it</text>
    <text x="614" y="254" font-size="9">and check it beats the SLA.</text>
    <text x="730" y="274" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: watch the slope</text>

    <text x="150" y="322" font-size="11.5" font-weight="700" text-anchor="middle">SAWTOOTH</text>
    <text x="150" y="434" font-size="11" font-weight="700" text-anchor="middle" fill="#7c5cff">A BATCH PRODUCER</text>
    <text x="34" y="458" font-size="9">A cron job or nightly export</text>
    <text x="34" y="474" font-size="9">dumping in bulk. Peaks are</text>
    <text x="34" y="490" font-size="9">alarming and harmless — what</text>
    <text x="34" y="506" font-size="9">matters is that troughs reach 0.</text>
    <text x="150" y="526" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: alarm on the TROUGH</text>

    <text x="440" y="322" font-size="11.5" font-weight="700" text-anchor="middle">NARROW REPEATED SPIKES</text>
    <text x="440" y="434" font-size="11" font-weight="700" text-anchor="middle" fill="#7c5cff">REBALANCE / RESTART</text>
    <text x="324" y="458" font-size="9">Each spike is a stop-the-world</text>
    <text x="324" y="474" font-size="9">pause where the group drains</text>
    <text x="324" y="490" font-size="9">nothing. Correlate with deploys</text>
    <text x="324" y="506" font-size="9">and with autoscaler events.</text>
    <text x="440" y="526" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: scale LESS often</text>

    <text x="730" y="322" font-size="11.5" font-weight="700" text-anchor="middle">RISE, THEN HARD FLAT</text>
    <text x="836" y="84" font-size="8.5" text-anchor="end" opacity="0.9">retention ceiling</text>
    <text x="730" y="434" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">YOU ARE LOSING DATA</text>
    <text x="614" y="458" font-size="9">Lag stopped growing because the</text>
    <text x="614" y="474" font-size="9">broker is deleting the head as</text>
    <text x="614" y="490" font-size="9">fast as the tail arrives. No</text>
    <text x="614" y="506" font-size="9">error is raised. Anywhere.</text>
    <text x="730" y="526" font-size="9.5" font-weight="700" text-anchor="middle">ACTION: this is a SEV-1</text>

    <text x="440" y="556" font-size="10" text-anchor="middle" opacity="0.95">Bottom-right is the one that gets missed: a flattening lag graph looks like recovery and is the opposite.</text>
  </g>
</svg>
```

Read that bottom-right panel twice. Every other shape can be diagnosed by a tired engineer at 3 a.m. That one *rewards* the tired engineer for going back to bed.

The same table, in text, because you will want to paste it into a runbook:

| Lag shape | Diagnosis | First action |
|---|---|---|
| Flat, nonzero | Healthy — consumers keeping pace with a one-poll-cycle standing buffer | None. Zero lag is not the target. |
| Flat at **zero**, with zero throughput | Consumers are **dead**, not healthy | Check consumer liveness — a depth alarm will never fire for this |
| Rising linearly | Sustained under-capacity | Extrapolate to the retention window; add capacity before that intercept |
| Sharp rise, slow linear decline | A burst, being absorbed correctly | Compute `excess / headroom`; act only if it exceeds the SLA |
| Sawtooth | A batch producer | Alarm on the trough, not the peak |
| Narrow repeated spikes | Rebalances — deploys, restarts, autoscaler flapping | Reduce scaling frequency; lengthen cooldowns |
| Rises, then abruptly flat | **Retention is deleting unread messages** | SEV-1. Data loss is in progress and silent. |
| Time lag rising while count lag falls | A dense burst is still being retired | Normal during recovery — do not over-react |

### Six causes that all look identical on the dashboard

"Lag is up" is a symptom, not a diagnosis, and it has at least six distinct causes. The skill is knowing the **one discriminating signal** for each, because acting on the wrong theory can make things actively worse.

**Consumers are down or fewer than expected.** Discriminating signal: **consumer count and partition assignment**. Look at the group's membership, not at any one process. A partition with no assigned consumer has a drain rate of exactly zero and its lag rises with a perfectly straight line while its neighbours look fine. Check per-partition lag, not just the aggregate — one dead partition hides inside a healthy-looking total.

**Consumers are slow.** Discriminating signal: **per-message processing time**. Consumer count is right, everyone is polling, but the handler now takes 16 ms instead of 4 ms. This is the 14:00 deploy. Correlate the slope change with your deployment timeline; the answer is usually within one deploy of the inflection point.

**A downstream dependency is slow.** Discriminating signal: **the downstream's own latency**, and low CPU on the consumers. This is the most important one to identify because **the obvious remedy makes it worse**. Lag is up, so you scale from 4 consumers to 20 — and all twenty now hammer the struggling database that was the actual bottleneck. You have converted a lag incident into a database outage. Here, lag is a *symptom*; the fix is downstream, and scaling out is contraindicated. A consumer blocked on a slow dependency has near-zero CPU and enormous lag, which is also why CPU-based autoscaling is useless for consumers.

**A poison message is looping.** Discriminating signal: **redelivery rate**, and lag that is stuck rather than growing — the head does not advance. This is [Lesson 8](../08-retries-backoff-and-dead-letter-queues/)'s territory, made worse by ordering ([Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/)): a partition is processed in order, so one stuck message halts everything behind it. The dead-letter queue exists precisely so this cannot happen.

**A rebalance is thrashing.** Discriminating signal: **rebalance/group-membership events**, and lag that spikes and recovers on a period matching your control loop. Every rebalance is a stop-the-world pause; if something triggers them repeatedly — a consumer whose processing time exceeds its poll timeout, a flapping autoscaler, a crash loop — the group spends its life re-joining instead of consuming.

**Producers genuinely spiked.** Discriminating signal: **the input rate**. Sometimes nothing is wrong with your consumer and marketing sent an email. Always look at λ before μ; it is the cheapest check and it reframes the whole investigation.

Notice that four of these six are **not fixed by adding consumers**, and one is actively worsened by it. "Lag is up, scale out" is the reflex this section exists to break.

### Flow control: prefetch, and why it has two failure modes

Now the mechanism. **Flow control** is how a consumer tells a broker how much work it is willing to hold at once, and the standard implementation is **credit-based**: the consumer advertises a number of **unacknowledged messages** it will accept, and the broker will not send more than that until some are acknowledged. AMQP 0-9-1 calls this `basic.qos` with a **prefetch count**; Kafka's client-side analogue is `max.poll.records` plus the fetch buffer sizes; SQS calls it the max number of messages per receive plus your own in-flight limit.

Prefetch exists because of round trips. If a consumer asks for exactly one message at a time, it pays a full network round trip for every single message. With a 2 ms round trip and 1 ms of processing, the consumer spends **two thirds of its life waiting on the network** and achieves 333 messages/second on hardware that could do 1,000. Prefetch amortises the round trip across a batch.

So more is better — until it very much isn't. Prefetch has **two** failure modes, at opposite ends, and most tuning advice mentions only one:

**Too low → round-trip starvation.** Throughput collapses to `P / (RTT + P·s)`. This is the failure mode above, and it is why `prefetch=1` — which many people set reflexively "for fairness" — can cost you 3× throughput.

**Too high → three separate problems.**

- **Memory.** Prefetched messages live in the consumer's heap. `prefetch × message size × consumers` is a real number, and if it exceeds the container limit you get an OOM kill, which redelivers everything, which refills the prefetch, which OOMs again.
- **Unfairness.** This is the subtle one, and the reason `prefetch=1` advice exists at all. Prefetch is not a buffer — it is a **claim on work that no other consumer may do**. With a bounded backlog, the first consumer to ask grabs its whole prefetch; if the prefetch is large relative to the backlog, one consumer hoards while the others sit idle. In the measured sweep below, `prefetch=1000` gives the *highest per-consumer throughput on the table* and the *second-slowest group*, because one consumer took 2,000 of 5,000 messages and three sat idle.
- **Redelivery window.** Every unacknowledged message a consumer holds is redelivered if it dies. Prefetch 32 loses 32 messages' worth of work; prefetch 10,000 loses 10,000, which at at-least-once delivery (Lesson 6) means 10,000 duplicates for your idempotency logic to absorb.

The sizing rule falls straight out of Little's Law. Efficiency is `P·s / (RTT + P·s)`, so for a target efficiency `e`:

```text
P = e/(1-e) x RTT/s        with RTT = 2ms, s = 1ms:

  50% of peak throughput  ->  prefetch     2
  90% of peak throughput  ->  prefetch    18
  95% of peak throughput  ->  prefetch    38
  99% of peak throughput  ->  prefetch   198
```

The curve is brutally flat past ~40. Going from 38 to 198 buys you 4% more throughput and costs 5× the memory, 5× the redelivery window, and a large step towards unfairness. **Size prefetch from your round-trip-to-processing-time ratio, then stop.** If your processing time is long (100 ms of image resizing), the ratio is tiny and prefetch should be small; if your processing time is microseconds, you need a large prefetch to be efficient at all.

### Pull versus push, and why credits exist at all

The reason credit-based flow control had to be invented is visible in the two ways a broker can deliver.

**Pull** (Kafka, SQS): the consumer asks for messages when it is ready. This is **naturally backpressured** — a busy consumer simply does not ask, and the backlog accumulates in the broker, which is designed to hold it. Nothing arrives that was not requested, so the consumer can never be overrun. The cost is latency and wasted polls on an empty queue, which long-polling mitigates.

**Push** (AMQP's `basic.consume`, and most of the STOMP/MQTT family): the broker sends messages as they arrive. Lower latency, and without a credit mechanism **unbounded** — a fast producer overruns a slow consumer, filling its socket buffer and then its heap. Which is exactly why AMQP has `basic.qos`: push delivery is only safe with an explicit credit window, and prefetch *is* that window.

So the deep version of the rule: **every delivery mechanism must have a bound somewhere.** Pull puts it in the request; push puts it in the credit. There is no third option.

### Bounded buffers everywhere — an unbounded internal queue is a delayed OOM

The same argument applies *inside* your consumer, and this is where a surprising number of real incidents live. A consumer polls a batch, hands it to a thread pool, and returns to poll again. If that internal handoff queue is unbounded, you have built a backpressure-free path from the broker straight into your heap: the poll loop runs at broker speed, the workers run at downstream speed, and the difference accumulates in RAM until the process dies.

This is precisely the argument from [Phase 9, Lesson 4](../../09-logging-monitoring-and-observability/04-the-log-pipeline/), where an unbounded log-shipping buffer is "not a solution, it's a delayed OOM kill". **Bound every queue, and decide explicitly what happens at the bound.** Inside a consumer the right answer is almost always *stop polling* — which is backpressure done correctly, because the backlog then accumulates in the broker, which has a disk, a retention policy and a metric, rather than in your heap, which has none of those.

### When you cannot catch up: the ladder

Sooner or later λ exceeds μ and you cannot fix it in the next ten minutes. There are exactly six honest moves, and they should be tried roughly in this order.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 552" width="100%" style="max-width:840px" role="img" aria-label="Six escalating options when consumers cannot keep up, each with its cost and its limit: scale out, bounded hard by the partition count; make processing faster; shed low-value load; degrade to cheaper processing; prioritise into separate queues; and finally producer-side throttling, which ends in telling a user no. A queue does not create capacity, it defers the moment you must admit you lack it.">
  <defs>
    <marker id="l09-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">You cannot catch up. Six moves, in order, and what each one costs</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="46" width="580" height="60" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="20" y="116" width="580" height="60" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="20" y="186" width="580" height="60" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="20" y="256" width="580" height="60" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="20" y="326" width="580" height="60" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <rect x="20" y="396" width="580" height="60" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="20" y="478" width="840" height="54" rx="11" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-dasharray="7 6"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.75">
    <path d="M604 76 L 640 76" marker-end="url(#l09-arrow)"/>
    <path d="M604 146 L 640 146" marker-end="url(#l09-arrow)"/>
    <path d="M604 216 L 640 216" marker-end="url(#l09-arrow)"/>
    <path d="M604 286 L 640 286" marker-end="url(#l09-arrow)"/>
    <path d="M604 356 L 640 356" marker-end="url(#l09-arrow)"/>
    <path d="M604 426 L 640 426" marker-end="url(#l09-arrow)"/>
    <path d="M310 460 L 310 472" marker-end="url(#l09-arrow)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="11.5" font-weight="700">1 · SCALE CONSUMERS OUT</text>
    <text x="36" y="90" font-size="9.5" opacity="0.9">more consumers in the group — the first thing everyone tries</text>
    <text x="648" y="72" font-size="9.5" font-weight="700" fill="#e0930f">CEILING: partition count</text>
    <text x="648" y="88" font-size="9" opacity="0.85">extra consumers idle;</text>
    <text x="648" y="102" font-size="9" opacity="0.85">each resize costs a pause</text>

    <text x="36" y="140" font-size="11.5" font-weight="700">2 · MAKE PROCESSING FASTER</text>
    <text x="36" y="160" font-size="9.5" opacity="0.9">batch the writes; take the synchronous call OUT of the hot path</text>
    <text x="648" y="146" font-size="9.5" font-weight="700">needs a code change</text>
    <text x="648" y="162" font-size="9" opacity="0.85">but raises mu permanently</text>

    <text x="36" y="210" font-size="11.5" font-weight="700">3 · SHED LOAD</text>
    <text x="36" y="230" font-size="9.5" opacity="0.9">drop or sample the low-value stream — deliberately, and count it</text>
    <text x="648" y="216" font-size="9.5" font-weight="700">COST: data you chose</text>
    <text x="648" y="232" font-size="9" opacity="0.85">to lose, at a known rate</text>

    <text x="36" y="280" font-size="11.5" font-weight="700">4 · DEGRADE</text>
    <text x="36" y="300" font-size="9.5" opacity="0.9">process a cheaper version: skip enrichment, defer the thumbnail</text>
    <text x="648" y="286" font-size="9.5" font-weight="700">COST: quality, not data</text>
    <text x="648" y="302" font-size="9" opacity="0.85">often the best trade there is</text>

    <text x="36" y="350" font-size="11.5" font-weight="700">5 · PRIORITISE</text>
    <text x="36" y="370" font-size="9.5" opacity="0.9">separate queues by value so the important stream drains first</text>
    <text x="648" y="356" font-size="9.5" font-weight="700">structural, not reactive</text>
    <text x="648" y="372" font-size="9" opacity="0.85">do this BEFORE the incident</text>

    <text x="36" y="420" font-size="11.5" font-weight="700">6 · THROTTLE THE PRODUCER</text>
    <text x="36" y="440" font-size="9.5" opacity="0.9">push backpressure all the way upstream to whoever is sending</text>
    <text x="648" y="426" font-size="9.5" font-weight="700" fill="#e0930f">ends at a HUMAN</text>
    <text x="648" y="442" font-size="9" opacity="0.85">rate limits, 429s, queues</text>

    <text x="440" y="502" font-size="11.5" font-weight="700" text-anchor="middle">Follow rung 6 to its end and you are telling a user "no".</text>
    <text x="440" y="522" font-size="10" text-anchor="middle" opacity="0.95">A queue does not create capacity. It defers the moment you must admit you do not have enough.</text>
  </g>
</svg>
```

**Scale consumers out** is first because it is fastest and usually right — but it is bounded by the **partition count** from [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/), and this is the constraint people hit hardest. A partition is consumed by exactly one member of a group. Twelve partitions means twelve useful consumers; the thirteenth is assigned nothing and idles while the lag it was hired to fix continues to grow. Worse, adding it still triggered a rebalance, so it cost throughput and bought none. This ceiling is why partition count is a capacity decision made months before the incident.

**Make processing faster** raises μ permanently rather than renting more of it. The highest-yield version is almost always *removing a synchronous call from the hot path* — the very thing the 14:00 deploy added. Batching downstream writes is second: one 100-row insert instead of 100 single-row inserts is routinely a 10× improvement in μ, for free.

**Shed load** means dropping messages on purpose. This is the same argument as Phase 9 Lesson 4's severity-based dropping, and the same insight applies: under sustained overload you do not get to choose *whether* to lose data, only *whether you choose which*. If you do nothing, the retention window will choose for you — uniformly at random, silently, and disproportionately from your most valuable stream because that stream is interleaved with everything else.

**Degrade** is shedding's gentler cousin: process every message, but cheaply. Skip the enrichment, write the record without the derived fields, queue the thumbnail for later. You keep the data and lose some quality, which is very often the best trade available.

**Prioritise** means separating streams by value *before* the incident, so that shedding and degradation have something to act on. If payments and recommendation updates share one queue, you cannot protect one without inspecting every message. If they are separate topics with separate consumer groups, the important one simply drains first.

**Throttle the producer** is last, and it is the one that reveals what a queue actually is. Push backpressure far enough upstream and it stops being a technical control: your API starts returning `429 Too Many Requests`, your batch job gets a smaller rate limit, your internal team is told their export can't run at that speed — and eventually somebody has to tell a *user* "not right now". That is not a failure of engineering. **A queue does not create capacity; it defers the moment you must admit you lack it.** Every rung above simply buys time before that conversation.

### Autoscaling on lag, and why the control loop is the hazard

If lag is the metric, scale on lag. Specifically:

**Scale on lag, not CPU.** A consumer blocked on a slow database has near-zero CPU and enormous lag. A CPU-based autoscaler will scale it *down*. This is not a hypothetical — it is the single most common autoscaling misconfiguration for queue workers, and it produces the exact opposite of the desired behaviour at the worst possible moment.

**Scale on time lag, or on lag derivative.** Time lag is directly comparable to your target ("keep us under 30 seconds behind"). The derivative catches problems before the value crosses a threshold, which matters when the deadline is a retention window hours away.

Then the hazards, which are all properties of the *control loop* rather than the metric:

**Every scaling event costs a rebalance.** Adding or removing a consumer revokes and reassigns partitions, and during that window the group's drain rate is **zero**. A five-second rebalance at 2,600 messages/second is 13,000 messages of extra backlog created *by the act of fixing the backlog*. Scale too eagerly and lag gets monotonically worse while your autoscaler works harder and harder: the aggressive scaler below spends **28% of the run rebalancing**, makes 17 scaling decisions, and never converges.

**Oscillation and flapping.** Lag high → scale up → lag drops → scale down → lag rises → scale up. A control loop with no damping around a system with a delayed response is a textbook oscillator. The fixes are standard control theory: a **cooldown** after each change, made **asymmetric** (up fast, down slowly — being over-provisioned costs money, being under-provisioned costs data), a **deadband** so small deviations produce no action, and a **step limit**. A damped scaler with those four properties converges below in **2 scaling events and 10 seconds of rebalance downtime**.

**The partition ceiling caps the whole thing.** An autoscaler that does not know the partition count will happily scale to 32 consumers on a 12-partition topic, pay 20 rebalances for it, and add exactly zero throughput. Set the autoscaler's maximum to the partition count.

### Alerting: what to page on, and the alarm that never fires

Four rules, and the fourth is the one most teams are missing.

1. **Page on time lag against your SLA.** "Oldest unprocessed message is older than 5 minutes" is an alert a human can act on immediately.
2. **Page on time lag against your *retention*.** This is a different, more urgent alarm with a different threshold — say, 50% of the retention window — because crossing it means irrecoverable loss. It is the only lag alarm whose severity is "wake someone up regardless of business hours".
3. **Alert on the lag *derivative*.** "Lag has been rising steadily for 15 minutes" fires long before any absolute threshold and gives you the whole retention window to respond rather than the last few minutes of it.
4. **Monitor consumer liveness separately.** This is the crucial one. If your consumers all die, lag stops being reported — in Kafka, `records-lag-max` is computed *by the client*, so a dead client reports nothing at all, and a metric that stops arriving is not the same as a metric that is zero. Meanwhile a naive queue-depth alarm may also stay quiet if producers happen to be idle. **Zero lag plus zero throughput means your consumers are dead, not healthy.** Alert on consumer group membership, on heartbeats, and on processed-messages-per-second being unexpectedly zero.

## Build It

[`code/backpressure_and_lag.py`](code/backpressure_and_lag.py) simulates a broker on a virtual clock and runs eight experiments against it. Standard library only, deterministic, self-terminating.

The broker is a **fluid queue** — a FIFO of per-tick buckets whose message counts are real numbers, which is how capacity-planning arithmetic works anyway and makes every figure reproducible to the digit. The core is a backlog that knows both kinds of lag, and a retention window that deletes from the head:

```python
class Broker:
    """A partition's backlog. Tracks count lag, time lag, and retention loss."""

    @property
    def count_lag(self) -> float:
        return self._nh + self._nl

    def time_lag(self, now: float) -> float:
        return (now - self.q[0][0]) if self.q else 0.0

    def expire(self, now: float) -> None:
        """Retention deletes the head of the log. Nobody gets an error."""
        if self.retention is None:
            return
        cut = now - self.retention
        while self.q and self.q[0][0] < cut:
            _, h, l = self.q.popleft()
            self.expired["high"] += h
            self.expired["low"] += l
```

Consumers **poll** rather than sipping continuously, which is why a healthy system still shows a standing backlog of one poll cycle of arrivals:

```python
def poll_due(now: float) -> bool:
    """Consumers do not sip continuously; they poll. This is why a healthy
    system still has a standing backlog of one poll cycle of arrivals."""
    return abs((now / POLL) - round(now / POLL)) < 1e-9
```

The consumer group models the thing that makes autoscaling dangerous — resizing is not free:

```python
@dataclass
class Group:
    """A consumer group. Resizing costs a stop-the-world rebalance pause."""

    @property
    def assigned(self) -> int:
        return self.n if self.partitions is None else min(self.n, self.partitions)

    def capacity(self, now: float) -> float:
        if now < self.pause_until:
            self.paused += TICK
            return 0.0
        return self.assigned * self.per

    def resize(self, n: int, now: float) -> None:
        if n == self.n:
            return
        self.n = n
        self.events += 1
        self.pause_until = now + self.rebalance_s
```

`assigned` is the partition ceiling in one line: consumers beyond the partition count contribute nothing to `capacity`, but resizing to add them still sets `pause_until`. That is the entire failure mode, mechanically.

The two autoscalers differ only in damping. The naive one reacts to every evaluation:

```python
    def decide(self, now, n, per, clag, tlag, rate):
        if now - self.last < self.interval:
            return n
        self.last = now
        if tlag > 10.0:
            return min(self.nmax, n * 2)
        if tlag < 1.0:
            return max(1, n // 2)
        return n
```

The damped one targets a *capacity* rather than reacting to a threshold, scales up promptly and down reluctantly, and refuses to act inside a cooldown:

```python
    def decide(self, now, n, per, clag, tlag, rate):
        ...
        # keep up with the input, plus enough headroom to drain the backlog in 60s
        want_cap = rate * self.headroom + clag / self.drain_target
        want = max(1, min(self.nmax, math.ceil(want_cap / per)))
        if want > n:                                        # scale up promptly
            self.down_votes = 0
            new, self.cooldown = min(want, n + self.step), self.up_cd
        elif want <= n - self.deadband:                     # scale down reluctantly
            self.down_votes += 1
            if self.down_votes < 2:                         # and only on a second vote
                return n
            self.down_votes = 0
            new, self.cooldown = max(want, n - self.step), self.down_cd
```

Run it:

```console
$ python backpressure_and_lag.py
== 1. THE RUN: one consumer group, six lag shapes, 400 virtual seconds ==
  4 consumers x 250 msg/s = 1,000/s capacity (1,600/s after the operator scales out at t=270)
  each plot cell is ~5.3s; the ramp is ' .:-=+*#%@' from zero to the peak on that row
  arrival/s  |..........+............................................             |  peak 8,000 msg/s
  drain/s    |++++++++++******************+*****************@@@@@@@@# -::= =.-- - |  peak 1,600 msg/s
  COUNT lag  |          +%%%##**++==--::.. ...::--==++**##%%%#*+=-:..             |  peak 21,800 msgs
  TIME lag   |          .-+#@%%#**+==--:..  ..:::--===++**###*+=-::.              |  peak 21.5 s
   phase:    steady          BURST + absorb            +20% OVERLOAD     recov  sawtooth
   t=            0s         60s                      170s              270s   320s   400s

== 2. READING THE DERIVATIVE: the shape is the diagnosis ==
  Values are the phase mean; d/dt is the least-squares gradient across the phase.
  phase                  window        lam     mu  count lag     d/dt  time lag    d/dt  shape -> diagnosis
  steady rho=0.80        10-59s        800  1,000        500       +0      0.4s  +0.000  flat + nonzero -> HEALTHY
  10x burst, 3s          60-63s      8,000  1,000     11,850   +6,979      1.4s  +0.790  vertical -> a burst arriving
  absorbing the burst    63-169s       800  1,000     10,851     -200     10.9s  -0.132  rise then fall -> absorbed
  +20% sustained         170-269s    1,200  1,000     10,500     +200      8.6s  +0.167  linear rise -> UNDER-CAPACITY
  scaled out to 1,600/s  270-319s    1,200  1,600     10,650     -400      8.7s  -0.334  falling -> recovering
  batch producer         320-399s      400  1,600        452       -5      0.3s  +0.000  sawtooth -> batchy input

  The two lags do NOT peak together. While the burst backlog drains:
    count lag peaks at t= 63.0s  (   21,800 msgs) and falls monotonically from there
    TIME lag peaks at t= 85.0s  (     21.5s) -- 22.0s LATER, while count lag was already down to 17,400
    the head is still crawling through densely-packed burst messages: 8,000/s of
    arrivals are being retired at 1,000/s, so the oldest message ages 0.875s per second.

  The sawtooth is invisible above because the burst sets the scale. Zoomed to t=320-400s:
  COUNT lag  |#=      :-.      +:      :-.      +:      :-.      +:      :-.      |  peak 4,900 msgs
    A batch producer dumping 4,000 messages every 10s. Mean lag is low, the shape is
    alarming, and nothing is wrong -- alarm on the trough, not the peak.

  Converting count lag to time lag. The backlog was BUILT by arrivals, so the
  identity is time_lag = count_lag / lambda (accurate to one sample interval, 0.25s).
  The conversion on every dashboard is count_lag / mu, which answers a different
  question -- 'how long to drain if arrivals stopped' -- and arrivals never stop:
                                measured   / lambda     err       / mu      err
    t=  50s steady, rho=0.80        0.75s      1.00s    +33%      0.80s      +7%
    t=  84s draining a burst       21.25s     22.00s     +4%     17.60s     -17%
    t= 269s sustained overload     17.25s     17.33s     +0%     20.80s     +21%
    t= 300s after scaling out       7.25s      7.50s     +3%      5.62s     -22%
    The dashboard estimate is only right when mu = lambda -- that is, only when
    nothing is wrong. It under-reads while a burst drains and over-reads during
    overload, and both errors point the wrong way for the decision you are making.

== 3. BURST vs SUSTAINED: the small one is the dangerous one ==
  Both runs: capacity mu = 1,000 msg/s, horizon 1,200s.
  A: a 10x BURST -- 8,000/s for 30s, then back to 800/s (baseline rho=0.80)
  B: a mere +20% SUSTAINED overload -- 1,200/s, forever
  A count lag|  =@@@@%%%%%%#######*******++++++=======------:::::::.......        |  peak 210,800 msgs
  A time lag |  ..:--==+**#%%@@@%%%%%######*****+++++=====------:::::.....        |  peak 210.5 s
  B count lag|    .......::::::::-------========++++++++*******########%%%%%%%@@@@|  peak 240,800 msgs
  B time lag |    .......::::::::-------========++++++++*******########%%%%%%%@@@@|  peak 200.5 s

  A: excess delivered = (8,000-1,000) x 30s = 210,000 messages
     Little's Law recovery = excess / headroom = 210,000 / 200 = 1,050s
     measured recovery after the burst ends      = 1,045s   (0.5% off)
     peak count lag   210,800   peak time lag  210.5s   state at 1,200s: RECOVERED (lag 600, 0.50s)
  B: excess delivered = 200/s, with no end. At 1,200s the 'small' mismatch has
     already put 240,700 messages behind -- more than the 10x burst's peak of 210,800.
     peak count lag   240,800   peak time lag  200.5s   state at 1,200s: STILL GROWING
     B overtakes A's peak backlog after 1,054s (18 min) and never stops.

  The 14:00 deploy: a synchronous enrichment call, 4ms -> 16ms per message.
     lambda = 800/s   mu = 4 x 62.5/s = 250/s
     measured slopes: +550 msg/s of count lag, +0.6875s of time lag per second
       +1h (15:00): count lag    1,979,999   time lag   0h41m
       +3h (17:00): count lag    5,939,998   time lag   2h03m
       +5h (19:00): count lag    9,899,997   time lag   3h26m
     retention is 6h. Time lag reaches it at +8h43m -- 22:43. That is the
     deadline for IRRECOVERABLE loss; past it the broker deletes 800 msg/s
     forever and the lag graph goes FLAT because you are losing, not catching up.

     Three options at 19:00 -- backlog 9,899,997, time lag 3h26m:
       revert the deploy          mu=1,000/s  headroom   200/s  -> drained in  13h45m
       revert + double the group  mu=2,000/s  headroom 1,200/s  -> drained in   2h17m
       revert + 4x the group      mu=4,000/s  headroom 3,200/s  -> drained in   0h51m
     All three beat the deadline: time lag falls the moment mu > lambda. But the
     first leaves every downstream consumer reading stale data until 08:45 tomorrow.
     Doing nothing loses data from +8h43m and never stops.

== 4. PREFETCH: credit-based flow control, and both of its failure modes ==
  4 consumers drain a 5,000-message backlog. Fetch round trip 2ms, processing 1ms/msg,
  message 16 KB, container heap 256 MB.
  prefetch  tput/consumer  group tput    drain     held per-consumer split          imbal   at risk
         1         333/s     1,333/s   3,750ms     0.1MB 1,250/1,250/1,250/1,250       0%      1 msg
         2         500/s     2,000/s   2,500ms     0.1MB 1,250/1,250/1,250/1,250       0%      2 msg
         4         667/s     2,662/s   1,878ms     0.2MB 1,252/1,252/1,248/1,248       0%      5 msg
         8         800/s     3,185/s   1,570ms     0.5MB 1,256/1,248/1,248/1,248       1%     13 msg
        16         889/s     3,536/s   1,414ms     1.0MB 1,256/1,248/1,248/1,248       1%     28 msg
        32         941/s     3,743/s   1,336ms     2.0MB 1,256/1,248/1,248/1,248       1%     60 msg
        64         970/s     3,788/s   1,320ms     4.0MB 1,280/1,280/1,224/1,216       5%    121 msg
       128         985/s     3,846/s   1,300ms     8.0MB 1,280/1,280/1,280/1,160      10%    246 msg
       256         992/s     3,876/s   1,290ms    16.0MB 1,280/1,280/1,280/1,160      10%    490 msg
       512         996/s     3,243/s   1,542ms    32.0MB 1,536/1,416/1,024/1,024      41%    815 msg
     1,000         998/s     2,495/s   2,004ms    62.5MB 2,000/1,000/1,000/1,000      80%  1,248 msg

  Best group throughput at prefetch 256: 3,876 msg/s, 1,290ms to drain.
  prefetch 1     is 2.91x slower -- the consumer spends 67% of its life waiting on the network.
  prefetch 1,000 is 1.55x slower -- per-consumer throughput is the HIGHEST on the table
                 (998/s), and the group is the second slowest. One consumer claimed
                 2,000 of the 5,000 messages while three sat idle for 3,006ms combined.
                 Prefetch is not a buffer. It is a CLAIM on work nobody else may do.

  Sizing from Little's Law: a consumer must hold enough in flight to cover the fetch
  round trip. efficiency = P*s / (RTT + P*s), so P = e/(1-e) * RTT/s  with RTT/s = 2:
      50% of peak throughput needs prefetch      2
      90% of peak throughput needs prefetch     18
      95% of peak throughput needs prefetch     38
      99% of peak throughput needs prefetch    198
  Past ~40 you are buying <5% more throughput with linear growth in memory,
  unfairness and redelivery risk. That is the whole sizing argument.

  The crash cost. A consumer that dies loses every unacked message it holds, and the
  broker redelivers all of them (at-least-once, Lesson 06 - the duplicates are yours):
    prefetch  worst case  repeat work  group memory
          32      32 msg       0.03s       2.00 MB
       1,000   1,000 msg       1.00s      62.50 MB
      10,000  10,000 msg      10.00s     625.00 MB   > the heap. Not a crash - an OOM kill.
    At prefetch 10,000 the group needs 625 MB against a 256 MB heap, so every consumer is
    killed, redelivers its 10,000, refills, and is killed again. The prefetch that
    looked like throughput tuning was a crash loop with a duplicate-message chaser.

== 5. AUTOSCALING ON LAG: the control loop is the hazard ==
  Input steps 800/s -> 2,600/s at t=30 and stays. Each consumer drains 250/s, so the
  group must reach 11 consumers to keep up and more to drain. Every resize costs a
  5s stop-the-world rebalance in which the group's drain rate is ZERO.

  naive: x2 when lag>10s, /2 when lag<1s, no cooldown
  consumers  |.......::==#@@@@====-::::::==*@@@@+====::::::==*@@@@*====::::::-=+@@|  peak 32
  TIME lag   |.:-=+##%#*#*#=  ::. .:--==+*##%+. .:.  :--==+*##%+. .:.  :--==+*##%*|  peak 19.5 s
    resizes 17   rebalance downtime  85.0s (28% of the run)   final size 32   peak time lag   19.5s
    last 60s: time lag min 0.00s / max 19.00s   -> STILL OSCILLATING

  damped: capacity target + 15% headroom, cooldown, asymmetric deadband
  consumers  |:::::::::+***#@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@|  peak 15
  TIME lag   |       .:=****%%#*+=-:.                                             |  peak 17.0 s
    resizes  2   rebalance downtime  10.0s (3% of the run)   final size 15   peak time lag   17.0s
    last 60s: time lag min 0.00s / max 0.75s   -> CONVERGED

  The naive loop is not slow because it scales wrong; it is slow because it scales
  OFTEN. Doubling and halving on every evaluation keeps the group inside a rebalance,
  and a group inside a rebalance drains nothing. Scaling was the outage.

== 6. THE PARTITION CEILING: adding consumers stops helping ==
  Same damped scaler, but the topic has 12 partitions and the input steps to 5,000/s.
  12 x 250/s = 3,000/s is the maximum drain rate this topic can ever have (Lesson 07).
  consumers  |...........:----++++*****%%%%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@|  peak 32
  COUNT lag  |         ....::::::------======++++++++********#########%%%%%%%%@@@@|  peak 660,600 msgs
  TIME lag   |         ....::::::------======++++++++********#########%%%%%%%%@@@@|  peak 132.0 s
    scaled to 32 consumers, 12 assigned a partition, 20 idle with no work to do
    drain rate is pinned at 3,000/s against 5,000/s of arrivals
    count lag still growing at +1,988 msg/s at the end of the run   peak time lag 132.0s
    every one of the last resizes bought 0 throughput and cost a 5s rebalance.
    The fix is not in this lesson: it is repartitioning, or making each message cheaper.

== 7. LOAD SHEDDING: choose your loss, or retention chooses it for you ==
  640/s of payment confirmations (HIGH) + 960/s of recommendation updates (LOW)
  = 1,600/s against 1,000/s of capacity. Broker retention: 60s. Horizon 300s.

  no shedding
  HIGH tlag  |  ....::::----====++++****####%%%%@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@|  peak 60.0 s
    processed    299,400  (high   119,760   low   179,640)
    shed               0  (high         0   low         0)   deliberate, counted, low value
    EXPIRED       84,200  (high    33,680   low    50,520)   silent, uncounted, chosen at random
    peak HIGH time lag   60.0s   final HIGH time lag  60.00s   shedding active   0% of the run
    HIGH stream:  62.4% processed,  17.5% deleted by retention

  shed LOW above 20s HIGH lag
  HIGH tlag  | ..::--===++**##%%@@%##*++=--:....::--===++**##%%@@%##*+==-::....::-|  peak 32.2 s
    processed    299,400  (high   184,848   low   114,552)
    shed         162,720  (high         0   low   162,720)   deliberate, counted, low value
    EXPIRED            0  (high         0   low         0)   silent, uncounted, chosen at random
    peak HIGH time lag   32.2s   final HIGH time lag  11.00s   shedding active  56% of the run
    HIGH stream:  96.3% processed,   0.0% deleted by retention

  Read the EXPIRED row twice. Without shedding, retention deleted 33,680 payment
  confirmations -- 17.5% of the high-value stream -- with no error, no log line, no metric
  except a lag number that had mysteriously STOPPED GROWING. With shedding, 0.

  Now the part that surprises people: TOTAL messages processed is 299,400 vs 299,400
  -- identical, because the consumers were saturated either way. Shedding did not
  cost throughput. It re-aimed it: high-priority processed went from 119,760 to
  184,848 (+54%), paid for with 162,720 recommendation updates dropped on purpose.
  You never choose whether to lose messages under sustained overload. You only
  choose whether YOU pick which ones, or the retention window picks for you.

== 8. SUMMARY: every scenario, same columns ==
  scenario                      peak count peak time  to drain      shed     lost  final state
  10x burst, 30s                   210,800    210.5s    1,045s         0        0  recovered
  +20% sustained                   240,800    200.5s     never         0        0  unbounded growth
  14:00 deploy (mu/4), 5h in     9,899,997     3h26m    13h45m         0        0  deletes from +8h43m
  autoscale, naive                  49,600     19.5s         -         0        0  32 consumers, oscillating
  autoscale, damped                 44,750     17.0s         -         0        0  15 consumers, converged
  partition ceiling (12)           660,600    132.0s     never         0        0  20 consumers idle, lag growing
  no shedding                            -     60.0s         -         0   84,200  HIGH tlag 60.00s
  shed LOW above 20s HIGH lag            -     32.2s         -   162,720        0  HIGH tlag 11.00s
```

Six things in that output are worth more than the rest of this lesson.

**The two lags do not peak together, and the gap is 22 seconds.** Count lag peaks at t=63 with 21,800 messages and falls monotonically from there. Time lag keeps climbing for another 22 seconds, peaking at **21.5 s at t=85**, by which point count lag was already down to 17,400. The mechanism is worth internalising: while the head of the backlog is inside the burst region, arrivals were deposited at 8,000/s and are being retired at 1,000/s, so the oldest message's timestamp advances at only 1/8 of real time — it ages **0.875 seconds per second**. Anyone watching count lag alone concludes the recovery started at t=63; the customer waiting for their confirmation email experiences the worst moment at t=85.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Measured divergence between count lag and time lag while a burst backlog drains. Count lag peaks at 21,800 messages at t=63 seconds and falls linearly. Time lag keeps rising for another 22 seconds, peaking at 21.5 seconds at t=85, at which point count lag had already fallen to 17,400. Watching count lag alone reports a recovery that has not started.">
  <defs>
    <marker id="l09-tip" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Count lag falls for 22 seconds while time lag is still climbing</text>

  <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
    <path d="M90 340 L 800 340"/>
    <path d="M90 340 L 90 88"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="5 5" opacity="0.5">
    <path d="M108 100 L 108 340"/>
    <path d="M242 100 L 242 340"/>
  </g>

  <path d="M90 340 L 108 100 L 242 148 L 759 340 L 800 340" fill="none" stroke="#3553ff" stroke-width="2.8"/>
  <path d="M90 340 L 108 311 L 160 240 L 242 100 L 400 178 L 600 268 L 759 340 L 800 340" fill="none" stroke="#e0930f" stroke-width="2.8"/>
  <circle cx="108" cy="100" r="4.5" fill="#3553ff"/>
  <circle cx="242" cy="100" r="4.5" fill="#e0930f"/>
  <circle cx="242" cy="148" r="4" fill="none" stroke="#3553ff" stroke-width="2"/>

  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.8">
    <path d="M270 118 L 300 118" marker-end="url(#l09-tip)" transform="rotate(180 285 118)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="76" y="214" font-size="9.5" text-anchor="middle" transform="rotate(-90 76 214)" opacity="0.9">lag (each series to its own scale)</text>
    <text x="445" y="368" font-size="9.5" text-anchor="middle" opacity="0.9">virtual seconds — the 10x burst ends at t=63, backlog clears at t=170</text>
    <text x="108" y="358" font-size="9" text-anchor="middle" opacity="0.8">t=63</text>
    <text x="242" y="358" font-size="9" text-anchor="middle" opacity="0.8">t=85</text>

    <text x="128" y="86" font-size="10.5" font-weight="700" fill="#3553ff">COUNT lag peaks 21,800</text>
    <text x="306" y="112" font-size="10.5" font-weight="700" fill="#e0930f">TIME lag peaks 21.5s — 22s later</text>
    <text x="306" y="132" font-size="9.5" opacity="0.9">count lag is already down to 17,400 here</text>
    <text x="470" y="212" font-size="9.5" fill="#3553ff" opacity="0.95">count lag: falling steadily at 200/s</text>
    <text x="470" y="300" font-size="9.5" fill="#e0930f" opacity="0.95">time lag: the head ages 0.875s per second</text>
    <text x="470" y="316" font-size="9.5" opacity="0.8">while it is still inside the burst region</text>

    <text x="440" y="398" font-size="10.5" text-anchor="middle" font-weight="700">Alarm on count lag and you declare recovery at t=63. The oldest message disagrees for 22 more seconds.</text>
    <text x="440" y="418" font-size="10" text-anchor="middle" opacity="0.9">This is why time lag is the number you page on — and why it must come from timestamps, not division.</text>
  </g>
</svg>
```

**Little's Law predicted the burst recovery to within 0.5%.** A 10× burst delivered `(8,000 − 1,000) × 30 = 210,000` excess messages. With 200/s of headroom, the predicted recovery is `210,000 / 200 = 1,050 s`; the simulator measured **1,045 s**. This is the arithmetic to do on a whiteboard during an incident, before you touch anything: *how much excess arrived, and how much headroom do I have?*

**A 20% sustained overload is far worse than a 10× burst.** Scenario A peaked at 210,800 messages and had fully recovered by t=1,200 (lag 600, time lag 0.50 s). Scenario B — a mismatch that would barely register on an input-rate graph — was at **240,700 messages and still growing** at the same moment, having overtaken the 10× burst's *peak* after **1,054 seconds, about 18 minutes**. Look back at the arrival-rate sparkline in section 1: the 10× burst is unmissable and harmless; the +20% step at t=170 is invisible there and is the one that never stops. **The size of an anomaly on the input graph is uncorrelated with its danger.** What matters is whether λ > μ, not by how much.

**Prefetch has a genuine optimum with losses on both sides.** Group throughput at `prefetch=1` is 1,333/s; it peaks at 3,876/s around 256; and falls back to 2,495/s at 1,000. The prefetch-1 case is 2.91× slower than optimal because the consumer spends 67% of its life waiting on round trips. The prefetch-1,000 case is 1.55× slower *despite having the highest per-consumer throughput on the table*, because one consumer claimed 2,000 of the 5,000 messages while three sat idle for 3,006 ms combined. Both extremes lose, for completely different reasons, and only one of them is usually taught.

Note also that the Little's Law sizing rule and the measured curve agree: the rule says 38 buys you 95% of peak, and the table shows `prefetch=32` already delivering 3,743/s against the 3,876/s peak — **96.6%, at 2 MB of memory instead of 16 MB and a 60-message redelivery exposure instead of 490.** The plateau is where you should live.

**The aggressive autoscaler was the outage.** The naive scaler made 17 resizes and spent **85 seconds — 28% of the run — inside a rebalance, drain rate zero**, and never converged: its time lag in the final minute still swung between 0.00 s and 19.00 s. The damped scaler made **2 resizes, spent 10 seconds (3%) rebalancing, and converged** to a final-minute maximum of 0.75 s. Both scalers were reacting to the same metric with the same information. The difference is entirely damping. And note the honest part: the damped scaler's *peak* lag (17.0 s) is barely better than the naive one's (19.5 s), because reacting more slowly does cost you something on the way up. It wins on everything after that.

**Shedding did not cost a single message of throughput.** Total processed was **299,400 in both arms** — identical, because the consumers were saturated either way. What changed was *what* got processed: high-priority throughput rose from 119,760 to 184,848, a **54% increase**, paid for entirely with 162,720 recommendation updates dropped on purpose. And the control arm's `EXPIRED` row is the whole argument: without shedding, retention silently deleted **33,680 payment confirmations, 17.5% of the high-value stream**, while its lag graph sat reassuringly flat at exactly 60.0 s — and it deletes from the head, at random, disproportionately taking the stream you care most about.

## Use It

You will configure these controls, not write them. Every setting below maps to a primitive above.

**Kafka — lag is offsets, and the client computes it.** Consumer lag is the partition's log-end offset minus the group's committed offset. Two very different ways to read it:

```bash
# Server-side: authoritative, works even when every consumer is dead.
kafka-consumer-groups.sh --bootstrap-server broker:9092 \
    --describe --group payments-consumer
# TOPIC     PARTITION  CURRENT-OFFSET  LOG-END-OFFSET  LAG   CONSUMER-ID
# payments  0          8823041         8823102         61    consumer-1-a3f...
# payments  7          8402118         9611844      1209726   -            <- no consumer!
```

That last row is the discriminating signal for "consumers are down": one partition with no assignment, lag rising linearly, hidden inside a healthy-looking aggregate. Contrast with the client-side metric `records-lag-max`, which is **computed by the consumer itself** — so a dead consumer reports nothing at all, and your dashboard shows a gap rather than a spike. This is exactly why liveness must be monitored separately.

Kafka gives count lag natively; **time lag you must compute yourself**, by subtracting the timestamp of the record you are processing from the current time and exporting it as your own gauge. It is three lines of code and it is the most valuable metric your consumer will emit.

Two settings interact to produce the classic Kafka bug:

```text
max.poll.records=500          # the prefetch: records handed to your loop per poll
max.poll.interval.ms=300000   # you must call poll() again within this, or you are DEAD
```

If processing 500 records takes longer than `max.poll.interval.ms`, the broker concludes the consumer has failed, kicks it out of the group, and rebalances. The consumer finishes its batch, tries to commit, discovers it no longer owns the partition, rejoins — and the whole group pauses again. The symptom is "my consumers keep getting kicked out of the group" plus the narrow-repeated-spikes lag shape, and the fix is arithmetic: **`max.poll.records × per-record time` must be comfortably under `max.poll.interval.ms`.** Slow processing means *lower* the prefetch, which is exactly backwards from the throughput intuition.

**RabbitMQ — `basic.qos` is credit-based flow control, verbatim.** The AMQP 0-9-1 method takes a prefetch count, and it is the mechanism this lesson's section 4 measures:

```python
channel.basic_qos(prefetch_count=32)      # <= 32 unacked messages on this channel
channel.basic_consume(queue="payments", on_message_callback=handle)  # PUSH delivery
```

Push delivery is why the credit is mandatory: without `basic.qos`, RabbitMQ will push the entire queue at your consumer as fast as the socket allows. The historical default of "unlimited" is responsible for a great many OOM kills.

Separately, RabbitMQ has broker-level **flow control**: when memory or disk free space crosses a configured watermark, the broker **blocks publishing connections** — producers stop, and their `basic.publish` calls hang.

```text
vm_memory_high_watermark.relative = 0.4     # block publishers above 40% of RAM
disk_free_limit.absolute = 5GB              # block publishers below 5GB free
```

That is backpressure travelling upstream, by design, as the alternative to the broker dying. It is also The Problem's first failure mode with a name and a config key: your producers hang because a consumer was slow.

**SQS — the time-lag metric, named.** Two CloudWatch metrics matter, and they are exactly this lesson's two lags:

```text
ApproximateNumberOfMessagesVisible   -> COUNT lag (queue depth)
ApproximateAgeOfOldestMessage        -> TIME lag  (seconds; page on THIS one)
```

`ApproximateAgeOfOldestMessage` is the time-lag metric, provided directly by the broker, and it is the correct alarm target. The flow-control equivalents are `MaxNumberOfMessages` (up to 10 per receive — a small prefetch) and the **visibility timeout**, which is the in-flight window: a message being processed is invisible to other consumers until the timeout expires, at which point it is redelivered. Visibility timeout is therefore your redelivery window, and it must exceed your processing time or you will reprocess everything forever.

**Google Cloud Pub/Sub** names the same pair: `oldest_unacked_message_age` (time lag — again, the one to alert on) and `num_undelivered_messages` (count lag). Its client libraries expose credit-based flow control explicitly:

```python
flow_control = pubsub_v1.types.FlowControl(
    max_messages=100,           # prefetch: outstanding messages
    max_bytes=100 * 1024 * 1024,  # ...and a byte bound, which is the one that saves you
)
```

Note `max_bytes`. Bounding by **count** alone is insufficient when message sizes vary — 100 messages might be 100 KB or 100 MB. Bounding both is the correct pattern, and it is worth copying even where the broker does not offer it.

**Autoscaling: KEDA and friends.** KEDA (Kubernetes Event-Driven Autoscaling) scales a Deployment on a queue metric rather than CPU:

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
spec:
  scaleTargetRef: {name: payments-consumer}
  minReplicaCount: 2
  maxReplicaCount: 12            # == the partition count. Never higher.
  cooldownPeriod: 300            # damping: no scale-down for 5 minutes
  triggers:
    - type: kafka
      metadata:
        consumerGroup: payments-consumer
        lagThreshold: "1000"     # target lag per replica
```

Three lines carry this lesson. `maxReplicaCount` is the **partition ceiling** — set it to the partition count and the section-6 failure mode cannot happen. `cooldownPeriod` is the **damping** that separates the converging scaler from the oscillating one. And the trigger is **lag**, not CPU, because a consumer blocked on a slow downstream has neither.

## Think about it

1. Your lag graph rose steadily for two hours and has now been perfectly flat for twenty minutes. Your teammate says the incident is resolving. Give the two possible explanations for a flat lag graph, name the single metric that distinguishes them, and say which one you should assume until proven otherwise.

2. A consumer's time lag is 40 minutes and rising. The downstream database it writes to is at p99 = 4 seconds, up from 40 ms. Your autoscaler is configured to scale on lag and is about to go from 6 replicas to 24. Explain precisely what will happen and what you should do to the autoscaler in the next sixty seconds — then say what the *correct* long-term fix is, and why it is not "more consumers".

3. Using the measured prefetch table: your messages take 200 ms each to process (not 1 ms) and your fetch round trip is still 2 ms. Recompute the sizing rule for 95% of peak throughput. What prefetch does it give you, and what does that tell you about copying another team's prefetch setting?

4. The load-shedding run processed exactly the same total number of messages with and without shedding — 299,400 both times. If shedding did not increase throughput, what did it actually buy, and what would have to be true about the workload for shedding to increase total throughput as well?

5. You have a 12-partition topic and your consumers are at the ceiling with lag still growing at 2,000/s. You cannot repartition today. Walk down the ladder from the diagram and name, for your own system, what rungs 2 through 5 would concretely be — and identify which one you should have built *before* the incident.

6. Your consumer's time lag is 3 hours and your retention is 6 hours. You have a fix ready that restores μ to 1.25× λ. Compute whether you make the deadline, and then explain why "we made the deadline" is a much weaker statement than "we recovered" — what is still broken for the next several hours, and who notices?

## Key takeaways

- **A queue absorbs a burst; it cannot absorb a sustained rate mismatch.** A 10× burst lasting 30 seconds peaked at 210,800 messages and fully recovered in a measured 1,045 s — within 0.5% of Little's Law's `excess / headroom` prediction of 1,050 s. A mere +20% sustained overload passed that same peak after 18 minutes and never stopped. **The size of an anomaly is uncorrelated with its danger; only the sign of `λ − μ` matters.**
- **There are two lags and you should page on the second.** **Count lag** (offset lag, queue depth) is meaningless without a rate. **Time lag** (age of the oldest unprocessed message) is directly comparable to your SLA and to your **retention window** — and the gap to retention is your deadline for irrecoverable, silent data loss. Compute time lag from message timestamps; do not derive it by dividing count lag by the drain rate, which under-read by 17% while a burst drained and over-read by 21% during overload.
- **The two lags do not move together.** While a dense burst drains, count lag falls monotonically while time lag climbs for another 22 seconds — measured peaks of 21,800 messages at t=63 and 21.5 s at t=85, by which point count lag was already 17,400. The oldest message ages 0.875 s per second while the head is still inside the burst region.
- **Read the derivative, not the value.** Flat and nonzero is healthy; linear rise is sustained under-capacity (extrapolate it to the retention window for your deadline); spike-then-decline is a burst absorbing correctly; sawtooth is a batch producer (alarm on the trough); narrow repeated spikes are rebalances. **Rises-then-abruptly-flat means retention is deleting your unread data**, and it looks exactly like recovery.
- **"Lag is up" has six causes and only two are fixed by adding consumers.** Discriminate with: consumer count and partition assignment; per-message processing time; the *downstream's* latency (here scaling out makes it worse by loading the real bottleneck); redelivery rate (a poison message, Lesson 8); rebalance events; and the input rate. Check λ before μ.
- **Prefetch is credit-based flow control with two failure modes.** Too low starves on round trips — `prefetch=1` measured 2.91× slower than optimal, with the consumer idle 67% of the time. Too high costs memory (10,000 × 16 KB × 4 = 625 MB against a 256 MB heap is an OOM crash loop), a proportional redelivery window, and **unfairness** — `prefetch=1000` had the highest per-consumer throughput on the table and the second-slowest group, because one consumer claimed 2,000 of 5,000 messages while three idled. Size it from Little's Law: `P = e/(1−e) × RTT/s`, which put 95% of peak at 38 and matched the measured plateau.
- **Bound every buffer, including the ones inside your consumer.** Pull delivery is naturally backpressured; push delivery requires explicit credit or the broker overruns you. An unbounded internal handoff queue inside a consumer is a delayed OOM — the same argument as [Phase 9 Lesson 4](../../09-logging-monitoring-and-observability/04-the-log-pipeline/). The right response to a full internal buffer is to **stop polling**, so the backlog accumulates in the broker, which has a disk and a metric, rather than your heap, which has neither.
- **Autoscale on lag, never CPU — and the control loop is the hazard, not the metric.** A consumer blocked on a slow downstream has near-zero CPU and enormous lag. Every resize costs a stop-the-world rebalance during which the group drains **nothing**: the aggressive scaler spent 28% of its run rebalancing across 17 resizes and never converged, while a damped one with cooldown, deadband and step limits converged in 2 resizes and 3%. Cap the autoscaler at the **partition count** — the measured run scaled to 32 consumers on 12 partitions, left 20 idle, and watched lag keep growing at 1,988/s.
- **Under sustained overload you do not choose whether to lose messages, only whether you choose which.** Shedding low-value traffic cost *zero* total throughput (299,400 processed either way) and raised high-priority throughput 54%, from 119,760 to 184,848. Without it, retention silently deleted 33,680 payment confirmations — 17.5% of the high-value stream — with no error anywhere. And the whole ladder ends in the same place: scale out (capped by partitions), speed up processing, shed, degrade, prioritise, throttle the producer — and then tell a user "no". **A queue does not create capacity; it defers the moment you must admit you lack it.**

Next: [The Dual-Write Problem: Transactional Outbox & CDC](../10-dual-write-outbox-and-cdc/) — you have kept the consumer alive and the backlog bounded, but there is still a crack between your database commit and your broker publish, and every message that falls through it is lost without ever appearing in a lag metric at all.
