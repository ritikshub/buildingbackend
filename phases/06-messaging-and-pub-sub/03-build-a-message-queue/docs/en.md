# Build a Message Queue: Work Distribution & Acknowledgement

> A queue looks like a list you push to and pop from, right up until a worker dies holding a customer's refund. Then you discover that `pop()` deleted the job before the work happened, that nothing remembers it existed, and that no error was ever logged. This lesson builds the queue that survives that: durable checksummed records, an atomic claim, a lease that expires, and an acknowledgement that arrives *after* the work. Sixty refunds, four workers, one crash — with the wrong design you silently lose one, and with the right one you lose none.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Anatomy of a Message](../02-anatomy-of-a-message/)
**Time:** ~90 minutes

## The Problem

You have a queue. It is four characters long:

```python
jobs = []
jobs.append("refund order 5004")
job = jobs.pop()
```

This is not a strawman. An enormous amount of production code has this shape — a Python list, a Redis list, a database table with a `status` column — and it works perfectly in development, where there is one process, one worker, and no crashes. Take those assumptions away one at a time. Each removal breaks something specific, and each break is a feature you are about to build.

**Failure one: the process restarts and the backlog is gone.** Your list lives in RAM (Random Access Memory) — inside the process. A deploy, an OOM (out-of-memory) kill, a reboot for a kernel patch, and the 4,000 queued refunds evaporate. Nobody gets an error, and nobody gets a refund. Fixing this is why the queue must be **durable**: written to a disk that outlives the process.

**Failure two: two workers `pop()` at the same time and the queue lies to both.** You scale to two workers because one is too slow. But "take a job off the queue" is not one operation — it is *read the tail, then remove the tail*, and a scheduler can interleave two workers between those steps. A reads job 5004. B reads job 5004 before A has removed it. A removes the tail. B removes the tail — which is now a *different job*. Order 5004 is refunded twice and order 5003 is deleted having never been delivered: one customer double-charged and another silently dropped, from three innocent-looking lines. (If that decomposition feels artificial, it is exactly why Redis added `RPOPLPUSH` — `LINDEX` then `LTRIM` is two commands and has precisely this bug.)

**Failure three — and this is the one that matters. A worker pops a job and crashes mid-processing.** The job is gone. Not "gone and retried". Not "gone and logged". Gone. The list no longer contains it because `pop()` removed it at delivery time, and the worker's memory no longer exists.

Sit with that, because it is the intellectual centre of this lesson. **Deleting a message when you deliver it is a decision about delivery semantics, and the semantics you chose are at-most-once.** Every message will be delivered zero or one times, and the difference between zero and one is invisible to you. The customer emails support in three weeks; the agent finds an order marked `refund_requested`, no refund, no error. There is nothing to debug because nothing failed — the system did exactly what it was built to do.

**Failure four: a worker hangs.** It doesn't crash, which would at least be honest. It claims a job and blocks forever on a socket read to a payment gateway that will never answer. The job is not in the queue, so nobody else can take it, and it is not being worked on either. Nothing notices, because nothing in the design has any concept of *how long a worker may hold a job*. The queue drains around it and one job sits in limbo indefinitely.

Four failures; four fixes, which are the four things a real broker gives you: **durability** (the log), **atomicity** (the claim), **acknowledgement** (the ack), and **a deadline on the claim** (the lease). You will build all four and measure what each buys.

## The Concept

### Competing consumers: the queue as a work-distribution primitive

The structure in this lesson is a **queue**, and it has one defining rule: **each message is processed by exactly one consumer.** Attach ten consumers to a queue and a message goes to one of them, not to all ten. This is the **point-to-point** shape, and the pattern name is **competing consumers** — the consumers compete for each message, and the broker arbitrates.

That rule makes a queue a *work-distribution* primitive rather than a broadcast one. It is the difference between "somebody please issue this refund" and "everybody should know a refund happened". The second is a **topic**, and it is [Lesson 4](../04-pub-sub-topics-and-fan-out/). Do not mix them up: sending work to a topic means every subscriber does the work, which for a refund means refunding it once per subscriber.

Because each message goes to exactly one consumer, a queue scales horizontally with embarrassing ease. Backlog growing? Start more consumers. No partition to rebalance, no coordination protocol, no shared state — each consumer independently asks for work and gets some. That is a rare property in distributed systems and the main reason this shape is everywhere.

One subtler property explains a measurement later on. A queue is a **pull**-based load balancer. An HTTP load balancer *pushes*: it picks a backend and sends, and if that backend is busy the request queues behind whatever it is doing. A queue lets consumers pull when ready, so a slow consumer asks less often and naturally receives less. **Load balancing happens for free, weighted by actual capacity, with no health checks and no configuration.** Hold on to that — the prefetch section shows how to break it.

### The acknowledgement is the entire design

Here is the whole lesson in one question: **when does the broker delete the message?** There are exactly two defensible answers, they produce different guarantees, and everything else here is machinery in service of the second.

**Ordering A — delete on delivery.** The broker hands the message over and removes it immediately. This is `jobs.pop()`. The guarantee is **at-most-once**: every message is delivered zero or one times. If the consumer dies between receiving and finishing, the work is lost — and, the part that makes it dangerous rather than merely lossy, lost *silently*. No error, no counter, no log line. From the outside, a lost message and a completed one are indistinguishable.

**Ordering B — delete on acknowledgement.** The broker hands the message over and *keeps it*, marked in-flight. The consumer does the work, and only on completion sends an **ack** (acknowledgement) telling the broker it may delete. If the consumer dies before acking, the broker eventually gives the message to somebody else. The guarantee is **at-least-once**: every message is delivered one or more times. Nothing is lost. Some things happen twice.

That is the trade, stated plainly:

| | At-most-once | At-least-once |
|---|---|---|
| Delete when | the message is delivered | the consumer acks |
| Failure mode | **work is lost, silently** | **work is duplicated** |
| Detectable? | No — nothing observes the loss | Yes — the delivery counter goes above 1 |
| Consumer must be | (nothing) | **idempotent** |
| Right for | metrics samples, cache warms, "nice to have" telemetry | payments, refunds, emails, anything with a customer |

Now the obvious question: why not delete *exactly* when the work completes, and get exactly-once?

Because that would require the broker's delete and the consumer's side effect to commit **atomically across two independent failure domains**. The work lands in the consumer's database; the delete lands in the broker. Two machines, two storage systems, a network between them, no shared transaction. Whichever you do first, there is a window in which the process can die: ack first and you can lose the work; ack second and you can repeat it. You can shrink the window, never close it. This is the **Two Generals problem** — two parties on a lossy channel cannot reach guaranteed common knowledge of a decision, however many messages they exchange — and it is a proof, not an engineering limitation.

So a queue offers exactly two choices, and one of them loses money. **Pick at-least-once, and make the consumer safe to run twice.** That last clause is the whole of [Lesson 6](../06-delivery-semantics-and-idempotency/), where at-least-once delivery plus an idempotent consumer produces *effectively-once* behaviour — the thing people mean when they say exactly-once. This lesson builds the delivery half properly so Lesson 6 has something to stand on.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Three acknowledgement orderings compared against the same measured workload of 60 refunds with one crashed worker and one hung worker. Deleting on delivery gives at-most-once and loses one refund silently. Acknowledging after processing gives at-least-once, loses nothing, and duplicates one refund. Adding a lease heartbeat keeps the zero losses and removes the duplicate.">
  <defs>
    <marker id="l03-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">When does the broker delete the message?</text>
  <text x="440" y="43" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">Same 60 refunds, same seed, same two failures: one worker crashes, one worker hangs for 13s under a 5s lease</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="58" width="276" height="330" rx="13" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="302" y="58" width="276" height="330" rx="13" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff"/>
    <rect x="588" y="58" width="276" height="330" rx="13" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="38" y="130" width="232" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="38" y="176" width="232" height="30" rx="7" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="38" y="222" width="232" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="324" y="130" width="232" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="324" y="176" width="232" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="324" y="222" width="232" height="30" rx="7" fill="#3553ff" fill-opacity="0.22" stroke="#3553ff"/>
    <rect x="610" y="130" width="232" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="610" y="176" width="232" height="30" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="610" y="222" width="232" height="30" rx="7" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.7">
    <path d="M154 160 L 154 172" marker-end="url(#l03-a1)"/>
    <path d="M154 206 L 154 218" marker-end="url(#l03-a1)"/>
    <path d="M440 160 L 440 172" marker-end="url(#l03-a1)"/>
    <path d="M440 206 L 440 218" marker-end="url(#l03-a1)"/>
    <path d="M726 160 L 726 172" marker-end="url(#l03-a1)"/>
    <path d="M726 206 L 726 218" marker-end="url(#l03-a1)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="154" y="82" font-size="12" font-weight="700" fill="#e0930f">ACK ON DELIVERY</text>
    <text x="154" y="100" font-size="9.5" opacity="0.85">jobs.pop()</text>
    <text x="154" y="118" font-size="10.5" font-weight="700">AT-MOST-ONCE</text>
    <text x="154" y="150" font-size="9.5">1. broker sends the message</text>
    <text x="154" y="196" font-size="9.5" font-weight="700">2. broker DELETES it</text>
    <text x="154" y="242" font-size="9.5">3. consumer does the work</text>
    <text x="154" y="282" font-size="10" font-weight="700" fill="#e0930f">crash between 2 and 3</text>
    <text x="154" y="299" font-size="9.5" opacity="0.9">= the work is gone, and</text>
    <text x="154" y="315" font-size="9.5" opacity="0.9">nothing anywhere knows</text>
    <text x="154" y="349" font-size="12" font-weight="700" fill="#e0930f">LOST 1 of 60</text>
    <text x="154" y="368" font-size="10" opacity="0.9">duplicates 0 · no ack step</text>

    <text x="440" y="82" font-size="12" font-weight="700" fill="#3553ff">ACK AFTER PROCESSING</text>
    <text x="440" y="100" font-size="9.5" opacity="0.85">claim · work · ack</text>
    <text x="440" y="118" font-size="10.5" font-weight="700">AT-LEAST-ONCE</text>
    <text x="440" y="150" font-size="9.5">1. broker HIDES it (lease)</text>
    <text x="440" y="196" font-size="9.5">2. consumer does the work</text>
    <text x="440" y="242" font-size="9.5" font-weight="700">3. ack -> broker deletes</text>
    <text x="440" y="282" font-size="10" font-weight="700" fill="#3553ff">crash before the ack</text>
    <text x="440" y="299" font-size="9.5" opacity="0.9">= the lease expires and</text>
    <text x="440" y="315" font-size="9.5" opacity="0.9">someone else picks it up</text>
    <text x="440" y="349" font-size="12" font-weight="700" fill="#3553ff">LOST 0 of 60</text>
    <text x="440" y="368" font-size="10" opacity="0.9">duplicates 1 · redelivered 2</text>

    <text x="726" y="82" font-size="12" font-weight="700" fill="#0fa07f">ACK AFTER + HEARTBEAT</text>
    <text x="726" y="100" font-size="9.5" opacity="0.85">claim · extend · work · ack</text>
    <text x="726" y="118" font-size="10.5" font-weight="700">AT-LEAST-ONCE</text>
    <text x="726" y="150" font-size="9.5">1. broker HIDES it (lease)</text>
    <text x="726" y="196" font-size="9.5" font-weight="700">2. work + EXTEND the lease</text>
    <text x="726" y="242" font-size="9.5" font-weight="700">3. ack -> broker deletes</text>
    <text x="726" y="282" font-size="10" font-weight="700" fill="#0fa07f">a live worker keeps its claim</text>
    <text x="726" y="299" font-size="9.5" opacity="0.9">a dead one stops beating,</text>
    <text x="726" y="315" font-size="9.5" opacity="0.9">so its message still returns</text>
    <text x="726" y="349" font-size="12" font-weight="700" fill="#0fa07f">LOST 0 of 60</text>
    <text x="726" y="368" font-size="10" opacity="0.9">duplicates 0 · redelivered 1</text>

    <text x="440" y="418" font-size="10.5" opacity="0.95">There is no fourth column. Exactly-once needs the broker's delete and the consumer's side effect</text>
    <text x="440" y="436" font-size="10.5" opacity="0.95">to commit atomically across two failure domains — that is the Two Generals problem, and it is a proof.</text>
    <text x="440" y="458" font-size="10" opacity="0.78">Choose at-least-once and make the consumer idempotent (Lesson 6). That is what "exactly-once" means in practice.</text>
  </g>
</svg>
```

### The lease: invisible, not deleted

An ack-after-processing design needs an answer to one question: *what if the ack never comes?* A crashed consumer never acks; nor does a hung one. If "in-flight" means "held until somebody says otherwise", failure four is back and the message is stuck.

The answer is a **lease** — SQS calls it the **visibility timeout**, Redis Streams calls it **idle time**, and *lease* is the general term because that is exactly what it is: a time-bounded, revocable grant of exclusive access.

When a consumer claims a message, the broker neither deletes it nor locks it forever. It makes the message **invisible for N seconds**. During that window no other consumer can see it. Three things can happen:

- **The consumer acks.** The message is deleted. Normal path.
- **The consumer nacks** (negative acknowledgement) — "I cannot process this". The message becomes visible again immediately, without waiting out the lease. Use this for a transient failure you already know about.
- **N seconds pass with neither.** The lease expires and the message becomes visible automatically. The broker neither knows nor cares *why* — crashed, hung, partitioned, descheduled. It knows only that nobody claimed responsibility in time.

That last bullet is a beautiful piece of design. The broker never has to detect consumer death — famously impossible to do correctly in an asynchronous network, where "dead" and "slow" are indistinguishable. It replaces that impossible question with a trivial one: *did an ack arrive before the deadline?* **The lease converts failure detection into timekeeping.**

### Choosing the timeout — and why it is a genuinely hard number

The lease duration is one of the few numbers in messaging you must actually tune, and both directions hurt.

**Too short, and you get duplicate work while the first consumer is still going.** The lease expires, the broker concludes the consumer is dead, and hands the message to a second one — while the first is still processing it. Two workers now issue the same refund, and the first eventually finds its ack *rejected*, because it no longer holds the lease. This is the most common way a well-meaning at-least-once system produces duplicates, and it involves no crash at all.

**Too long, and recovery from a real death is slow.** A worker dies holding a message and it stays invisible until the lease expires. A five-minute visibility timeout means five minutes before anyone retries — annoying for a refund, a breach for an order-fulfilment step with a downstream SLA (Service Level Agreement).

The rule of thumb: **set the visibility timeout comfortably above your p99.9 processing time, not your p50.** People instinctively size against the average, which guarantees the tail of legitimately-long jobs is duplicated constantly. If p50 is 200 ms and p99.9 is 40 seconds, a 30-second timeout duplicates roughly one message in a thousand forever, and you will spend a week blaming the network.

One more effect surprises people, and the measurement below makes it concrete: **recovery time is not the lease duration — it is the lease plus the time to drain the backlog ahead of the message.** An expired lease returns the message to the *back* of the queue, behind everything enqueued since. Below, a worker crashed at t=3.50s holding a message whose lease ran out at t=8.50s; it became visible at t=9.25s and was not redelivered until **t=24.50s**, because it landed behind 40 other messages. For worst-case latency, the lease is a floor, not the answer.

### The heartbeat: how to have a short lease and long jobs

The dilemma above assumes the lease is set once at claim time. It doesn't have to be. A consumer that is still alive and still working can **extend the lease** — send "still working on it" before the deadline and the broker pushes the deadline out. This is a **heartbeat** (SQS: `ChangeMessageVisibility`).

It dissolves the trade-off. Set a *short* lease — say 30 seconds — so a dead consumer is detected quickly, and have long-running consumers extend it every 10 seconds. A dead consumer stops beating and its message returns in 30 seconds; a live consumer on a 20-minute transcode keeps its claim for all 20 minutes. Fast failure detection *and* correct handling of long jobs, which is exactly what the third column of the measured run shows: same crash, same 13-second job, zero duplicates.

One warning separates a working heartbeat from a dangerous one. **The heartbeat must signal progress, not merely process liveness.** Run it on a background timer thread, let the worker thread deadlock, and the timer beats happily forever while the message is never reclaimed — converting a detectable failure (lease expiry) into an undetectable one (a job pinned by a zombie). Beat from the work loop, or gate the beat on a progress counter the work updates. A heartbeat that cannot fail is not a health check; it is a lie with a schedule.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="A measured timeline of two lease failures over 27 seconds. Worker w3 claims a message at 1.5 seconds that needs 13 seconds under a 5 second lease, so the lease expires at 6.5 seconds and the refund is processed twice. Worker w1 crashes at 3.5 seconds holding a message whose lease expires at 8.5 seconds, but redelivery does not happen until 24.5 seconds because the message went to the back of the queue behind the remaining backlog.">
  <defs>
    <marker id="l03-a2" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The measured lease timeline — 60 refunds, 4 workers, a 5.0s lease</text>

  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.55">
    <path d="M60 372 L 830 372"/>
    <path d="M60 366 L 60 378"/>
    <path d="M201 366 L 201 378"/>
    <path d="M342 366 L 342 378"/>
    <path d="M483 366 L 483 378"/>
    <path d="M624 366 L 624 378"/>
    <path d="M765 366 L 765 378"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="102" y="76" width="141" height="26" rx="6" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff"/>
    <rect x="243" y="76" width="225" height="26" rx="6" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-dasharray="5 4"/>
    <rect x="243" y="112" width="507" height="26" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="5 4"/>
    <rect x="159" y="200" width="141" height="26" rx="6" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff"/>
    <rect x="320" y="236" width="430" height="26" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="5 4"/>
    <rect x="750" y="200" width="56" height="26" rx="6" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    <rect x="750" y="76" width="56" height="26" rx="6" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M243 68 L 243 60" opacity="0.6"/>
    <path d="M159 192 L 159 184" opacity="0.6"/>
    <path d="M468 102 L 468 118" marker-end="url(#l03-a2)" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="4 3">
    <path d="M243 40 L 243 76"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="70" font-size="11" font-weight="700" fill="#e0930f">A · THE LEASE WAS TOO SHORT</text>
    <text x="34" y="90" font-size="9.5" text-anchor="start">w3</text>
    <text x="172" y="93" font-size="9" text-anchor="middle" font-weight="700">lease 1.50 - 6.50</text>
    <text x="355" y="93" font-size="9" text-anchor="middle">w3 STILL WORKING, no lease</text>
    <text x="497" y="129" font-size="9" text-anchor="middle">m-0008 sits at the back of the queue</text>
    <text x="778" y="93" font-size="9" text-anchor="middle" font-weight="700" fill="#0fa07f">redeliver</text>
    <text x="243" y="34" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">t=6.50 lease expires</text>
    <text x="468" y="156" font-size="9.5" text-anchor="middle" font-weight="700" fill="#e0930f">t=14.50 · w3 finishes and its ack is REJECTED</text>
    <text x="468" y="172" font-size="9" text-anchor="middle" opacity="0.9">the refund was processed twice — nobody crashed, the timeout was just wrong</text>

    <text x="34" y="194" font-size="11" font-weight="700" fill="#3553ff">B · THE WORKER REALLY DIED</text>
    <text x="34" y="214" font-size="9.5" text-anchor="start">w1</text>
    <text x="229" y="217" font-size="9" text-anchor="middle" font-weight="700">lease 3.50 - 8.50</text>
    <text x="535" y="253" font-size="9" text-anchor="middle">m-0013 waits behind the 40 messages already in the queue</text>
    <text x="778" y="217" font-size="9" text-anchor="middle" font-weight="700" fill="#0fa07f">redeliver</text>
    <text x="159" y="178" font-size="9" text-anchor="middle" fill="#3553ff" font-weight="700">t=3.50 w1 CRASHES holding m-0013</text>
    <text x="320" y="288" font-size="9.5" text-anchor="start" font-weight="700">t=9.25 · visible again  →  t=24.50 · actually redelivered (delivery #2)</text>
    <text x="320" y="304" font-size="9" text-anchor="start" opacity="0.9">recovery took 21 seconds, not the 5 seconds the lease implied</text>

    <text x="440" y="336" font-size="10.5" text-anchor="middle" font-weight="700">Redelivery latency = lease duration + time to drain the backlog ahead of it.</text>
    <text x="440" y="352" font-size="10" text-anchor="middle" opacity="0.9">An expired message goes to the BACK of the queue, not the front — so a deep queue slows every retry.</text>
    <text x="60" y="392" font-size="9" text-anchor="middle" opacity="0.8">0s</text>
    <text x="201" y="392" font-size="9" text-anchor="middle" opacity="0.8">5s</text>
    <text x="342" y="392" font-size="9" text-anchor="middle" opacity="0.8">10s</text>
    <text x="483" y="392" font-size="9" text-anchor="middle" opacity="0.8">15s</text>
    <text x="624" y="392" font-size="9" text-anchor="middle" opacity="0.8">20s</text>
    <text x="765" y="392" font-size="9" text-anchor="middle" opacity="0.8">25s</text>
    <text x="440" y="416" font-size="9.5" text-anchor="middle" opacity="0.8">Both rows are real events from the run in Build It — nothing here is illustrative.</text>
  </g>
</svg>
```

### Durability: the queue's storage layer is a write-ahead log

Failure one demanded that the queue survive a restart, which means writing to disk. The naive approach — keep a file holding the current state and rewrite it on every change — is wrong for a reason worth understanding: **a crash mid-rewrite leaves you with neither the old state nor the new one.**

The correct structure is **append-only**. Never modify what is on disk; only add to the end. Each operation — enqueue, claim, ack, nack — becomes one **record** appended to a log file, and the queue is reconstructed by replaying that log.

If that sounds familiar, it should: **this is exactly Write-Ahead Logging, from [Phase 3, Lesson 13](../../03-relational-databases/13-write-ahead-logging/).** A database writes the intent of a change to a sequential log and flushes it *before* touching its real data structures, so a crash is recovered by replay. A queue does the identical thing for the identical reason. WAL is not a database technique — it is *the* technique for making an in-memory data structure survive a crash, and you will find it in filesystem journals, LSM commit logs, Kafka (where the partition log *is* the storage), and Raft. A queue is one more instance.

The record format we use is three fields and nothing else:

```text
[ u32 length ][ u32 crc32 ][ payload bytes ]
   4 bytes       4 bytes      `length` bytes
```

Both header fields earn their place:

- **The length prefix** tells the reader where this record ends and the next begins, *before* it parses anything. Without it you cannot know whether the bytes at the tail are a complete record or half of one.
- **The CRC** (Cyclic Redundancy Check — a checksum over the payload) tells the reader whether these are the bytes that were written. A length alone catches a truncated write but not a *corrupted* one: if a disk flips a bit inside a record whose length is intact, the length check passes happily and you replay garbage into your queue state. The measurement below flips exactly one byte and shows the CRC catching it.

The **crash-consistency argument** falls out of the format. Because writes only append, and every record is self-delimiting and self-verifying, **the only damage a crash can do is leave a partial record at the tail.** Earlier records cannot be affected, because nothing ever goes back and touches them. So recovery has a provably-safe rule: *read records until one fails to verify, then stop and truncate there.* You keep the longest valid prefix — precisely the set of operations durably recorded before the machine died. No ambiguity, no repair step.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="The append-only log format and its recovery. Each record is a 4-byte length, a 4-byte CRC32 and a payload. A crash leaves a torn record at the tail, which recovery detects and truncates, keeping the longest valid prefix of 32 records and 1837 bytes. A flipped byte inside an intact record is caught only by the checksum. Compaction rewrites the log from 320,595 bytes to 6,885 bytes, a 47 times reduction.">
  <defs>
    <marker id="l03-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The append-only log — and the only damage a crash can do</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="48" width="70" height="40" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/>
    <rect x="100" y="48" width="70" height="40" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="170" y="48" width="240" height="40" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="65" y="66" font-size="9.5" text-anchor="middle" font-weight="700">u32 len</text>
    <text x="65" y="80" font-size="8.5" text-anchor="middle" opacity="0.85">4 bytes</text>
    <text x="135" y="66" font-size="9.5" text-anchor="middle" font-weight="700">u32 crc32</text>
    <text x="135" y="80" font-size="8.5" text-anchor="middle" opacity="0.85">4 bytes</text>
    <text x="290" y="66" font-size="9.5" text-anchor="middle" font-weight="700">payload — put / clm / ack / nak / ext</text>
    <text x="290" y="80" font-size="8.5" text-anchor="middle" opacity="0.85">`len` bytes of compact JSON</text>
    <text x="430" y="60" font-size="9.5" opacity="0.95">length = where the record ENDS</text>
    <text x="430" y="76" font-size="9.5" opacity="0.95">crc32  = whether these are the bytes that were WRITTEN</text>
    <text x="430" y="92" font-size="9" opacity="0.75">a length check alone cannot catch a flipped bit</text>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="30" y="140" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="142" y="140" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="254" y="140" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="366" y="140" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="478" y="140" width="70" height="34" rx="5" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f" stroke-dasharray="5 4"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.6">
    <path d="M513 178 L 513 208" marker-end="url(#l03-a3)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="30" y="128" font-size="11" font-weight="700">1 · A CRASH MID-APPEND</text>
    <text x="83" y="161" font-size="9" text-anchor="middle">record 29</text>
    <text x="195" y="161" font-size="9" text-anchor="middle">record 30</text>
    <text x="307" y="161" font-size="9" text-anchor="middle">record 31</text>
    <text x="419" y="161" font-size="9" text-anchor="middle">record 32</text>
    <text x="513" y="156" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">TORN</text>
    <text x="513" y="168" font-size="8" text-anchor="middle" fill="#e0930f">24 of 96 B</text>
    <text x="566" y="150" font-size="9.5" opacity="0.95">power cut halfway through the append —</text>
    <text x="566" y="166" font-size="9.5" opacity="0.95">records 1–32 are untouched, because nothing rewrites them</text>
    <text x="540" y="200" font-size="9.5" font-weight="700" fill="#0fa07f">recovery: keep the longest valid prefix, truncate the rest</text>
    <text x="540" y="216" font-size="9" opacity="0.9">32 records · 1,837 bytes kept · writes resume immediately</text>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="30" y="258" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="142" y="258" width="106" height="34" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="254" y="258" width="106" height="34" rx="5" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="366" y="258" width="106" height="34" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="30" y="246" font-size="11" font-weight="700">2 · BIT ROT INSIDE AN INTACT RECORD</text>
    <text x="83" y="279" font-size="9" text-anchor="middle">record 29</text>
    <text x="195" y="279" font-size="9" text-anchor="middle">record 30</text>
    <text x="307" y="274" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">record 31</text>
    <text x="307" y="286" font-size="8" text-anchor="middle" fill="#e0930f">1 byte flipped</text>
    <text x="419" y="279" font-size="9" text-anchor="middle" opacity="0.6">record 32</text>
    <text x="492" y="268" font-size="9.5" opacity="0.95">the length field is still perfectly valid — only the CRC catches this</text>
    <text x="492" y="284" font-size="9.5" opacity="0.95">scan stops at record 31; 31 of 32 records survive</text>
    <text x="492" y="300" font-size="9" opacity="0.75">without a checksum you replay garbage into broker state</text>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="356" width="500" height="34" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="30" y="410" width="11" height="34" rx="4" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M280 392 L 280 406" marker-end="url(#l03-a3)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="30" y="344" font-size="11" font-weight="700">3 · COMPACTION — the checkpoint that stops the file growing forever</text>
    <text x="280" y="377" font-size="9.5" text-anchor="middle">5,805 records · 320,595 bytes — to represent 100 live messages</text>
    <text x="300" y="402" font-size="9" text-anchor="start" opacity="0.9">rewrite live state only, fsync, then os.replace() — an atomic rename</text>
    <text x="56" y="432" font-size="9.5" text-anchor="start" font-weight="700" fill="#0fa07f">105 records · 6,885 bytes · 47x smaller</text>
    <text x="440" y="466" font-size="10" text-anchor="middle" opacity="0.95">Append-only is what makes all three safe: earlier records are never rewritten, so a crash can only ever damage the tail.</text>
  </g>
</svg>
```

### fsync, and what it costs

There is a trap between `write()` and durability. When your program writes to a file the bytes land in the operating system's **page cache** — RAM owned by the kernel. The call returns success immediately, and the data may not reach the device for seconds; lose power in that window and the write is gone, having been reported as successful. **`fsync()` closes the gap**: it blocks until the kernel has pushed that file's dirty pages to the storage device. A broker that promises "your message is safely queued" must fsync before sending that promise, or the promise is a guess.

It is not free. Appending 3,000 messages with an `fsync` after each ran at **17,856 messages/second** (56.0 µs each) against **78,495/second** (12.7 µs) with none — a **4.4× throughput cost** on a laptop SSD. On a spinning disk or network-attached volume the ratio is far worse, often 100×, because you pay a device round trip per message instead of a memory copy. (These three numbers are the only ones in this lesson that will differ on your machine; everything else is identical on every run.)

Which is why real brokers do not fsync per message. They use **group commit**: accumulate writes for a few milliseconds or a few hundred records, issue *one* fsync, then acknowledge every producer it covered. Throughput recovers almost entirely, because the expensive part is the round trip rather than the bytes. The cost is a small latency floor on every publish, and that is a better trade than it sounds.

One caveat, since it bites people benchmarking on a Mac: **on macOS `fsync()` does not flush the drive's own internal write cache.** Only `fcntl(F_FULLFSYNC)` forces the drive to commit to persistent media, and it is slower still. If a durability number looks too good, check which was called.

### Recovery, and the checkpoint that stops the log growing forever

On startup the broker replays the log and rebuilds its in-memory state: which messages exist, which are ready, which are in-flight and until when, and how many times each was delivered.

A design rule shows up here that generalises well: **log the decisions, derive everything else.** Lease *expiry* is never written down — it is a function of a recorded deadline and the current clock, so replay recomputes it for free. Writing derived state into a log costs I/O and, worse, lets the log disagree with itself. If you can recompute it, don't record it.

The remaining problem is growth. Every operation appends, so the file only grows — including operations on messages deleted weeks ago. Below, pushing 2,000 messages through and acking 1,900 produced **5,805 records and 320,595 bytes** for a queue whose live contents are 100 messages.

The fix is a **checkpoint** (or **compaction**): write a fresh log containing only what still matters — one `put` per live message, plus a `claim` for anything in flight — and atomically swap it in. Measured: **320,595 bytes down to 6,885, a 47× reduction**, with startup replaying 105 records instead of 5,805.

The swap must be atomic or compaction becomes a new way to lose the queue. Write to a temporary file, fsync it, then `os.replace()` — on POSIX an atomic `rename(2)`. A crash at any instant leaves the directory entry pointing at the complete old log or the complete new one, never a half-built file.

### Delivery counting: the number that finds your poison messages

Every time the broker hands out a message it increments a counter on that message and persists it. A few bytes, and the single most useful diagnostic a queue has.

Delivery count 1 is normal. 2 or 3 says a consumer crashed or a lease lapsed. Delivery **47** is a **poison message**: something about it makes every consumer fail, and it has been burning capacity in a loop for hours. Without the counter it is indistinguishable from ordinary traffic; with it, it is a `WHERE deliveries > 5` away. This is the hook [Lesson 8](../08-retries-backoff-and-dead-letter-queues/) uses for **dead-letter queues**: after N deliveries, stop retrying and move the message somewhere a human can look at it.

SQS exposes it as `ApproximateReceiveCount`, and *Approximate* is not modesty but a design statement. Delivery is the broker's hottest path, and durably persisting an increment before every delivery would put an fsync in front of every read. SQS declines to pay that, so the count can be slightly low after a broker-side failure — the right call, since the counter's job is to find the message stuck at 47, and it does that fine if it occasionally says 46.

### Ordering: you do not have any, and you should stop pretending

Queues are drawn as FIFO (First In, First Out), so it is tempting to believe messages are *processed* in order. With competing consumers they are not, for two structural reasons.

**Concurrency destroys it.** Even with the broker handing out messages in perfect FIFO order, consumer A gets message 1 and consumer B gets message 2 at the same instant; if A's takes 900 ms and B's takes 50 ms, message 2 completes first. The ordering guarantee ends at delivery, and what follows is a race between independent processes.

**The failure path destroys it far more violently.** An expired lease puts the message back — at the *back*. In the measured run, `m-0008` was the eighth message enqueued, yet when its lease lapsed it landed behind **43** messages and was not redelivered until t=24.50 in a run that finished at t=26.50 — dead last. Any consumer assuming `order.updated` arrives after `order.created` is a latent bug waiting for its first redelivery.

So: **a queue with more than one consumer gives no useful ordering guarantee at all.** You may have ordering of *delivery attempts*, which is worth nothing to application logic.

Getting ordering means giving something up. The mechanism is a **partition key** — group related messages (all events for one `order_id`) so everything in a group goes to the same consumer, in order, one at a time. You keep parallelism *across* groups and lose it *within* one. That is [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/), and where SQS FIFO's `MessageGroupId` and Kafka's partition key come from. Until then, assume none.

### Prefetch: how much a consumer takes at once

A consumer can claim one message per request, or ten, or a thousand. This is **prefetch** (RabbitMQ: `prefetch_count`, part of its QoS — Quality of Service — settings; SQS: `MaxNumberOfMessages`, capped at 10).

Prefetch exists because one round trip per message is wasteful. At 1 ms of network latency, a consumer taking messages one at a time cannot exceed 1,000/second however fast it processes them — it is latency-bound, not CPU-bound. Claiming 100 at a time amortises that round trip and moves the ceiling by two orders of magnitude.

The cost is that **a prefetched message is claimed but not being worked on.** It sits in the consumer's local buffer, invisible to everyone else, waiting behind the other 99. Three consequences:

- **Fairness collapses.** A slow consumer holding a big batch is sitting on work that idle fast consumers could have finished. The pull-based self-balancing above is gone — a large prefetch turns the queue back into a *push* system, assigning work at claim time, before anyone knows how long anything takes. Measured: four consumers, one 6× slower, 120 jobs. At prefetch 1 everything finishes at **t=21.25s**; at prefetch 16, **t=48.25s** — 2.3× longer — because the slow consumer grabbed 16 jobs up front while three fast ones idled at the end.
- **Crashes cost more.** A consumer dying with a prefetch of 100 makes 100 messages wait out the lease, not one.
- **Leases get harder.** The lease starts when the message is *claimed*, not when work *begins*. Message 100 of a batch may sit buffered for minutes before the consumer reaches it, its lease ticking the whole time.

The rule: **small prefetch for slow or variable tasks, large for fast uniform ones.** A 5-second video transcode wants `prefetch=1`; a 200-microsecond metric aggregation wants `prefetch=500`. The default of 1 is a sensible start precisely because too-high fails invisibly (idle consumers, slow drain) while too-low fails obviously (low throughput). Prefetch is also one lever in the flow-control story of [Lesson 9](../09-backpressure-lag-and-flow-control/).

### Three more features you will be asked for

**Priority.** The naive implementation — a priority field and a sorted structure — fails by **starvation**: a steady stream of high-priority messages means low-priority ones are never delivered, and "never" can be measured in weeks. Real systems use *aging* (effective priority rises with wait time) or, far more commonly, **separate queues per priority with dedicated consumer capacity** — uglier on the whiteboard, vastly easier to monitor. Many brokers, SQS among them, offer no priority at all, and separate queues is the recommended answer.

**Delay and scheduled delivery.** A message invisible until a future time: "retry in 30 seconds", "remind me tomorrow". The mechanism is a `visible_at` timestamp — the same machinery as a lease with the deadline in the future, since a delayed message is just one born in-flight. This is what makes exponential backoff possible without the consumer sleeping, and it is the backbone of Lesson 8's retry story. Note the limits: SQS's `DelaySeconds` caps at 15 minutes, and RabbitMQ needs a plugin or a TTL-plus-dead-letter-exchange trick. For a reminder next Tuesday, use a scheduler and a database.

**Queue depth is the primary health metric — with a caveat.** Chart it first, since it is arrivals minus completions over time. But raw depth alone is meaningless: 5,000 messages is a crisis at 10/second and a rounding error at 10,000/second. Convert with Little's Law from [Lesson 1](../01-why-async-and-the-cost-of-coupling/) — `depth ÷ drain rate = seconds of backlog` — and alert on *seconds*. Better still, alert on **oldest-message age**, which needs no drain rate and keeps rising even when depth is flat because the queue is stalled rather than growing. The runbook in `outputs/` treats these properly.

## Build It

`code/message_queue.py` builds the queue in the order the failures demanded: a durable log, an atomic claim, leases and acks, then recovery. Standard library only, seeded, on a virtual clock — nothing sleeps, so a 26-second simulated run takes microseconds and prints the same numbers every time.

The on-disk format is nine lines:

```python
HEADER = struct.Struct("<II")          # u32 payload length, u32 CRC32 of payload

def frame(payload: bytes) -> bytes:
    """[u32 length][u32 crc32][payload] — the whole on-disk format."""
    return HEADER.pack(len(payload), zlib.crc32(payload)) + payload


def _append(self, rec: dict) -> None:
    self._f.write(frame(json.dumps(rec, separators=(",", ":"), sort_keys=True).encode()))
    if self.fsync:
        os.fsync(self._f.fileno())     # the write is not durable until this returns
```

Recovery reads records until one fails to verify, returning the length of the good prefix so the caller can truncate to it:

```python
        if len(data) - body < n:
            return recs, off, f"torn payload: {len(data) - body} of {n} bytes at offset {off}"
        payload = data[body:body + n]
        if zlib.crc32(payload) != crc:
            return recs, off, f"CRC mismatch at offset {off} (record {len(recs)})"
```

The claim is where atomicity lives. One lock is held across *read the ready queue, decide, mutate, append* — so failure two's read-then-write race cannot occur, because no window exists between the read and the write for another consumer to enter:

```python
    def claim(self, consumer: str, lease_secs: float, prefetch: int = 1) -> list[Message]:
        with self._lock:
            self._expire_locked()
            out: list[Message] = []
            while self.ready and len(out) < prefetch:
                mid = self.ready.popleft()
                m = self.msgs[mid]
                m.deliveries += 1
                m.owner, m.epoch = consumer, m.epoch + 1
                m.lease_until = round(self.clock.now + lease_secs, 6)
                if self.mode == "at_most_once":
                    m.state = DONE                          # delete on read
                    self._append({"o": "ack", "id": mid, "c": consumer})
                else:
                    m.state = IN_FLIGHT
                    heapq.heappush(self.leases, (m.lease_until, mid, m.epoch))
                    self._append({"o": "clm", "id": mid, "c": consumer,
                                  "u": m.lease_until, "n": m.deliveries})
```

Lease expiry uses a min-heap keyed on the deadline, so finding expired leases costs O(1) per expiry rather than scanning every in-flight message. Because a deadline can change (a heartbeat) or become irrelevant (an ack), heap entries carry an `epoch` and stale ones are discarded lazily on pop:

```python
    def _expire_locked(self) -> list[str]:
        while self.leases and self.leases[0][0] <= self.clock.now:
            _, mid, epoch = heapq.heappop(self.leases)
            m = self.msgs[mid]
            if m.state != IN_FLIGHT or m.epoch != epoch:
                continue                       # stale heap entry; the message moved on
            m.state, m.owner, m.epoch = READY, None, m.epoch + 1
            self.ready.append(mid)             # back of the queue, not the front
```

And `ack` refuses an acknowledgement from a consumer that no longer holds the lease — the one `if` that turns a mis-tuned timeout from silent corruption into a countable event:

```python
    def ack(self, mid: str, consumer: str) -> bool:
        with self._lock:
            m = self.msgs.get(mid)
            if m is None or m.state != IN_FLIGHT or m.owner != consumer:
                self.stats["ack_rejected"] += 1
                return False
```

Run it:

```console
$ python message_queue.py
== 1. THE NAIVE QUEUE: three ways `jobs.pop()` loses your work ==
  jobs = [] with 5 refunds queued, in a Python list
  (a) process restarts        -> backlog after restart: 0 of 5   the whole queue was in RAM
  (b) two workers pop() at once -> A got 'refund order 5004'
                                   B got 'refund order 5004'   <- the same job, refunded twice
                                   'refund order 5003' was deleted undelivered; 3 of 5 left
  (c) worker claims 'refund order 5002', then crashes mid-refund
      not in the list, not in memory: gone silently, and no error was ever logged
  (d) worker hangs holding a job -> nothing reclaims it; the job is stuck forever

== 2. THE DURABLE LOG: length + CRC32 + payload, replayed on open ==
  one enqueue produced 65 bytes on disk
    header  39 00 00 00 d8 17 36 69   length=57  crc32=0x693617d8
    payload {"b":"refund order 5000","id":"m-0001","o":"put","t":0.0}
  8 bytes of header per record; the CRC is what makes a torn write detectable

== 3. ATOMIC CLAIM: 4 threads racing for 400 messages ==
  4 threads claimed 400 messages, 400 distinct, 0 delivered twice
  the claim path holds one lock across read-decide-write, so the read-then-write
  race from 1(b) cannot happen -- this is the primitive a broker must provide

== 4. THE CRASH TEST: same seed, same failures, three delivery designs ==
  60 refunds, 4 workers, 5s lease, prefetch 1
  w1 dies the instant it claims its 4th job; w3's 3rd job takes 13s

  design               enqueued delivered  acked  redelivered  processed  duplicates   LOST
  -----------------------------------------------------------------------------------------
  ack on delivery            60        60      0            0         59           0      1
  ack after work             60        62     60            2         61           1      0
  ack after + heartbeat       60        61     60            1         60           0      0
  (ack-on-delivery shows 0 acks because there is no ack step: claim deletes)

  -- ack on delivery (at-most-once) --
     t=  1.50  w3 claimed m-0008, which needs 13.0s under a 5.0s lease
     t=  3.50  w1 CRASHED holding m-0013 (its lease runs out at t=8.50)
     finished at t=26.00s   per worker: w0=21  w1=3  w2=23  w3=12

  -- ack after work (at-least-once) --
     t=  1.50  w3 claimed m-0008, which needs 13.0s under a 5.0s lease
     t=  3.50  w1 CRASHED holding m-0013 (its lease runs out at t=8.50)
     t=  6.50  m-0008 lease expired, no ack -> visible again at the BACK of the queue, behind 43 messages
     t=  9.25  m-0013 lease expired, no ack -> visible again at the BACK of the queue, behind 40 messages
     t= 14.50  w3 finished m-0008 after 13s -- ack REJECTED, lease long gone: this refund ran twice
     t= 24.50  m-0008 redelivered to w0 (delivery #2) once the backlog drained to it
     t= 24.50  m-0013 redelivered to w3 (delivery #2) once the backlog drained to it
     finished at t=26.50s   per worker: w0=22  w1=3  w2=23  w3=13

  -- ack after + heartbeat (at-least-once+hb) --
     t=  1.50  w3 claimed m-0008, which needs 13.0s under a 5.0s lease
     t=  3.50  w1 CRASHED holding m-0013 (its lease runs out at t=8.50)
     t=  9.25  m-0013 lease expired, no ack -> visible again at the BACK of the queue, behind 39 messages
     t= 24.50  m-0013 redelivered to w0 (delivery #2) once the backlog drained to it
     finished at t=26.50s   per worker: w0=22  w1=3  w2=23  w3=12

== 5. RECOVERY: reopen the file, replay the log, rebuild the state ==
  before crash: {'ready': 0, 'in_flight': 7, 'done': 5}   log 1837 bytes, 32 records, clock t=7.0
  3 were delivered, left unacked, expired, redelivered: {'m-0006': 2, 'm-0007': 2, 'm-0008': 2}
  after replay: {'ready': 0, 'in_flight': 7, 'done': 5}   replayed 32 records, damage=None
  state matches: True   delivery counts survived: True   (this is SQS's ApproximateReceiveCount)
  t=13.0, restored leases lapse: {'ready': 7, 'in_flight': 0, 'done': 5}  -> 7 visible again
  nothing was lost across the restart: 12 of 12 messages accounted for

== 6. TORN AND CORRUPT RECORDS: what the CRC is for ==
  intact log: 32 records, 1837 bytes
  torn write appended 32 bytes of a 104-byte record
    scan stopped: torn payload: 24 of 96 bytes at offset 1837
    kept 32 records (1837 bytes), discarded the tail
    reopened: {'ready': 0, 'in_flight': 7, 'done': 5}   file truncated to 1837 bytes
    and it still accepts writes: {'ready': 1, 'in_flight': 7, 'done': 5}
  bit rot: one byte flipped inside the last record's payload
    scan stopped: CRC mismatch at offset 1780 (record 31)
    kept 31 of 32 records -- length alone would not have caught this

== 7. COMPACTION: stopping the log growing forever ==
  2,000 enqueued, 1,900 claimed and acked -> {'ready': 95, 'in_flight': 5, 'done': 1900}
  log before compaction   320,595 bytes  (5,805 records)
  log after  compaction     6,885 bytes  (2.1% -- 47x smaller)
  reopened from the checkpoint: {'ready': 95, 'in_flight': 5, 'done': 0}   replayed 105 records, not 5,805

== 8. PREFETCH: the fairness cost of claiming in bulk ==
  120 jobs, 4 consumers; w0-w2 take 0.5s per job, w3 takes 3.0s (6x slower)
  prefetch  1: all work done at t= 21.25s   w0= 38  w1= 38  w2= 37  w3=  7
  prefetch 16: all work done at t= 48.25s   w0= 40  w1= 32  w2= 32  w3= 16
  a big prefetch lets the slowest consumer hoard work the fast ones could have done

== 9. THE COST OF fsync (the only machine-dependent numbers here) ==
  fsync per enqueue  (durable)           17,856 msg/s       56.0 us/msg
  OS page cache only (fast, lossy)       78,495 msg/s       12.7 us/msg
  durability costs 4.4x throughput -- which is why real brokers batch the fsync across many messages
  caveat: on macOS os.fsync() does not flush the drive's own write
  cache -- only F_FULLFSYNC does, and it is slower still
```

Sections 1–8 print identically on every run; only the three throughput lines in section 9 depend on your hardware. Now read what was measured.

**The crash test is the lesson.** Same seed, same sixty refunds, same two failures. Under **ack-on-delivery**, 60 messages were delivered, 59 processed, and **one refund was lost** — not delayed, not errored, lost without a trace. Under **ack-after-processing**, 62 deliveries produced 60 acks, **zero lost**, one duplicate; the two extra deliveries are the two redeliveries.

**Those two redeliveries are not the same event, and the distinction matters.** `m-0013` came back because its owner genuinely died — the lease doing its job, and no other design recovers it. `m-0008` came back because the lease was too short while `w3` was still perfectly alive and processing; at t=14.50 `w3` finished and its ack was **rejected**, so that refund was issued twice. That duplicate was caused entirely by a configuration number, with nothing failing at all.

**The heartbeat removes the second and keeps the first.** Third row: 61 deliveries, 60 acks, one redelivery, zero duplicates, zero lost. The crashed worker's message still came back, because a dead process cannot extend a lease; the slow worker's did not, because a live one can. That is why a short lease plus heartbeats beats a long lease — it distinguishes *slow* from *dead*, which a fixed timeout cannot.

**Recovery is slower than the lease implies.** `m-0013`'s lease expired at t=8.50 and it was visible at t=9.25, but it was not redelivered until **t=24.50** — a 21-second recovery from a 5-second lease, because it went to the back of the queue behind 40 other messages. If you are writing an SLA around retry latency, this number ruins it, and it worsens as the backlog grows.

**Durability survived a kill and two kinds of corruption.** The queue was closed mid-life with 7 in flight and 5 done; replaying 32 records reconstructed that exactly, including delivery counts of 2 on the three already-redelivered messages. Appending 32 bytes of a 104-byte record then simulated a power cut mid-write: the scanner reported `torn payload: 24 of 96 bytes`, kept all 32 good records, truncated, and accepted writes immediately. Finally one byte was flipped *inside* a well-formed record — length field still valid — and only the CRC caught it, at record 31.

**Compaction is not optional at real volume.** 2,000 messages produced 5,805 records and 320,595 bytes to represent 100 live ones; the checkpoint took that to 6,885 bytes (2.1%, a 47× reduction) and cut startup replay to 105 records. Uncompacted, restart time grows with the queue's *lifetime* rather than its *contents* — which is how a broker up for six months takes twenty minutes to come back.

**Prefetch turned a 21-second job into a 48-second one.** At `prefetch=1` the slow consumer took 7 jobs and the fast ones 38, 38 and 37 — the pull model balanced load automatically, finishing at t=21.25. At `prefetch=16` the slow consumer grabbed 16 up front and everything finished at t=48.25, **2.3× slower**, with three fast consumers idle at the end. Nothing failed; the queue was configured to be unfair.

## Use It

Every production queue is the thing you just built, with better storage and a network protocol. The vocabulary changes; the primitives do not.

**Amazon SQS (Simple Queue Service)** maps almost one-to-one:

```bash
# claim: receive up to 10 messages, invisible for 300s, wait up to 20s for one to arrive
aws sqs receive-message --queue-url "$Q" \
  --max-number-of-messages 10 \        # prefetch
  --visibility-timeout 300 \           # the lease
  --wait-time-seconds 20 \             # long polling
  --attribute-names ApproximateReceiveCount

# ack: the delete IS the acknowledgement
aws sqs delete-message --queue-url "$Q" --receipt-handle "$H"

# heartbeat: this job is taking longer than expected
aws sqs change-message-visibility --queue-url "$Q" --receipt-handle "$H" --visibility-timeout 600
```

`ReceiveMessage` is `claim`, `DeleteMessage` is `ack`, `VisibilityTimeout` is the lease, `ChangeMessageVisibility` is the heartbeat, `ApproximateReceiveCount` is the delivery counter. Two details worth knowing: **`--wait-time-seconds` enables long polling**, where the server holds the connection open until a message arrives instead of returning empty immediately — it cuts both cost and latency versus busy-polling, so turn it on always. And a `receipt-handle` is not the message id but a token for *this delivery*, so a redelivered message has a new handle and the old one is void — the same "your lease is gone" rejection our `ack` implements.

**RabbitMQ** is an AMQP (Advanced Message Queuing Protocol, version 0-9-1) broker, and it has the same pieces with different names:

```python
channel.basic_qos(prefetch_count=1)                 # prefetch — the fairness knob
channel.queue_declare(queue="refunds", durable=True)  # survives a BROKER restart

def on_message(ch, method, props, body):
    try:
        process(body)
        ch.basic_ack(delivery_tag=method.delivery_tag)              # ack after work
    except TransientError:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)   # give it back
    except PoisonError:
        ch.basic_nack(delivery_tag=method.delivery_tag, requeue=False)  # -> dead-letter

channel.basic_consume(queue="refunds", on_message_callback=on_message, auto_ack=False)
```

`auto_ack=False` is the whole lesson in one keyword — `auto_ack=True` is ack-on-delivery and at-most-once. RabbitMQ has no lease timer; a message is redelivered when the **channel or connection closes**, a faster failure detector with a different blind spot: it catches a dead process instantly but never a hung one holding its TCP connection open. Hence the per-queue **consumer timeout**.

The detail that costs people their data: **durability in RabbitMQ needs three separate things, and any one missing loses everything.** The queue must be declared `durable=True`, each message published with `delivery_mode=2` (persistent), and the publisher must use **publisher confirms** to learn the broker actually stored it. A non-durable queue is *deleted* on broker restart — not drained — with every message in it, and a persistent message published to a non-durable queue is still lost. Note also that `basic_nack(requeue=True)` requeues at the **front**, so a deterministically-failing message spins in a tight CPU-burning loop; use `requeue=False` plus a dead-letter exchange for those.

**Redis lists** are the poor-man's queue, and they show why the lease exists by lacking one:

```text
LPUSH refunds "{...}"                          # enqueue
BRPOP refunds 0                                # claim -- and DELETE. at-most-once.
BLMOVE refunds refunds:processing RIGHT LEFT 0 # claim atomically into an in-flight list
LREM refunds:processing 1 "{...}"              # ack -- remove from the in-flight list
```

`BRPOP` is `jobs.pop()` with a network in front of it: the message leaves Redis at delivery, so a consumer crash loses it. The **reliable queue pattern** uses `BLMOVE` (which superseded `BRPOPLPUSH`) to move the message from the pending list into a *processing* list in one atomic step, so a claimed message is still recorded somewhere; acking is removing it from that list. What Redis lists do not give you is lease expiry — nothing returns items from the processing list automatically, so you must run your own reaper scanning for entries older than a threshold. You are hand-building the lease, which is exactly why Redis Streams exists.

**Redis Streams consumer groups** are the closest commodity match to what you built:

```text
XADD refunds '*' body "{...}"                      # enqueue
XGROUP CREATE refunds workers 0                    # a group of competing consumers
XREADGROUP GROUP workers w1 COUNT 10 BLOCK 5000 STREAMS refunds '>'   # claim (prefetch 10)
XACK refunds workers 1712-0                        # ack
XPENDING refunds workers - + 10                    # what is in flight, and for how long
XAUTOCLAIM refunds workers w2 60000 0 COUNT 10     # reclaim anything idle > 60s
```

The mapping is near-exact. `XREADGROUP` with `>` is `claim`, moving entries into the group's **PEL** (Pending Entries List) — the in-flight set. `XACK` is `ack`. `XPENDING` exposes the in-flight set *with per-message idle time and delivery count*, the diagnostic surface our `counts()` and `deliveries` provide. `XAUTOCLAIM` with a minimum idle time is lease expiry made explicit: instead of the broker reclaiming on a timer, a consumer asks for anything idle longer than N milliseconds — same semantics, inverted control. And because the underlying structure is a log rather than a queue, entries survive being acked and can be replayed, which is [Lesson 5](../05-the-log-offsets-and-replay/).

## Think about it

1. Your consumer processes a message in 200 ms at p50 and 45 seconds at p99.9, and the visibility timeout is 60 seconds. A colleague proposes cutting it to 10 seconds "so crashes recover faster". Estimate what fraction of messages get processed twice, and describe the change that gets fast crash recovery *without* that cost.

2. In the measured run, `m-0013`'s lease expired at t=9.25 but redelivery happened at t=24.50. Your team wants to promise "a failed message is retried within 10 seconds". Explain why the lease duration alone cannot deliver that promise, and name two changes to the *queue* — not the consumers — that would get closer.

3. A colleague argues that fsync is unnecessary because the queue runs on three replicas: "if one machine loses power the other two still have the message." Under what failure does this reasoning hold, and under what failure does it lose data anyway? What would you need to know about the replication protocol to decide?

4. Ack-on-delivery lost one message in sixty and reported no error at all. Design the smallest change to that system that would at least make the loss *visible* — without changing the delivery semantics. Then argue whether shipping that is better or worse than shipping nothing.

5. Your queue is at 5,000 messages and flat. Consumers report healthy, CPU is low, the ack rate is steady at 400/s, and the redelivery rate is 380/s. What is happening, and which single additional metric would confirm it in one glance?

6. With `prefetch=16` the run finished 2.3× slower than with `prefetch=1`, purely from unfairness. But `prefetch=1` costs a network round trip per message. Sketch the arithmetic that tells you which effect dominates for a given workload — what do you need to know about processing time, round-trip time, and consumer-speed variance?

## Key takeaways

- A **queue** delivers each message to exactly **one** consumer — the **competing consumers** pattern. It scales horizontally by adding consumers with no coordination between them, and load-balances by **pull** rather than push, so a slow consumer automatically receives less. A topic (Lesson 4) is the opposite shape: everyone gets a copy.
- **The acknowledgement is the design.** Delete on delivery is **at-most-once** and loses work *silently* — the measured run lost 1 refund of 60 with no error, log line or counter. Delete on ack is **at-least-once**: 62 deliveries, 60 acks, **zero lost**, one duplicate. There is no third ordering, because exactly-once needs the broker's delete and the consumer's side effect to commit atomically across two failure domains — the **Two Generals** problem. Choose at-least-once and make the consumer idempotent (Lesson 6).
- A **lease** (SQS: `VisibilityTimeout`) makes a claimed message *invisible* rather than deleted, and returns it automatically if no ack arrives — replacing the impossible problem of detecting consumer death with the trivial one of watching a clock. Too short and you duplicate live work: the measured 13-second job under a 5-second lease ran twice with nothing crashing. Too long and a real death takes that long to recover. Size it against **p99.9, not p50** — or better, keep the lease short and **heartbeat**, since a live consumer can extend its own claim and a dead one cannot. That took the measured run to zero duplicates *and* zero losses. Beat from the work loop, not a background timer: a heartbeat that keeps ticking while the worker is deadlocked converts a detectable failure into an invisible one.
- **The queue's storage layer is a write-ahead log** — the same technique as **Phase 3 Lesson 13**. Records are `[u32 length][u32 crc32][payload]`, appended and never modified. The length makes each record self-delimiting; the CRC catches corruption a length check cannot, as a single flipped byte inside a well-formed record demonstrated. Because writes only append, **the only damage a crash can do is a torn tail**, so recovery keeps the longest valid prefix and truncates.
- **`fsync` is where durability actually happens**, and it cost **4.4×** throughput (17,856 vs 78,495 msg/s); real brokers pay it once per *batch* (group commit). Log decisions and derive everything else — lease expiry is recomputed, never written down. And **compact**: 2,000 messages produced 5,805 records and 320,595 bytes, which a checkpoint cut 47× to 6,885 bytes and 105 records to replay.
- **A delivery counter** (SQS: `ApproximateReceiveCount`) turns retries into data. A message on delivery 47 is a poison message burning capacity in a loop, invisible without the counter. It is the hook Lesson 8 uses for dead-lettering, and it must survive a broker restart — it did, across a simulated kill.
- **A queue with competing consumers gives you no useful ordering.** Concurrency breaks it, and redelivery breaks it violently: when its lease lapsed the 8th message enqueued went to the back behind 43 others and finished dead last. If ordering matters you need **partition keys** (Lesson 7), trading parallelism within a key to get it.
- **Prefetch trades round trips for fairness.** One message per request is latency-bound; large batches amortise the network but let a slow consumer hoard work while fast ones idle. Measured: the same 120 jobs finished at t=21.25 with `prefetch=1` and t=48.25 with `prefetch=16` — **2.3× slower with nothing broken**, purely from configuration. Small for slow or variable tasks, large for fast uniform ones (Lesson 9).
- **Operate on seconds, not counts.** Raw depth means nothing without a drain rate: use Little's Law (`depth ÷ drain rate`), or better, alert on **oldest-message age**, which stays honest when the queue is stalled rather than growing. Watch depth, oldest age, in-flight count, redelivery rate and ack rate *together* — the runbook in `outputs/` shows how their combinations separate "consumers are down" from "consumers are slow" from "a poison message is looping".

Next: [Pub/Sub: Topics, Subscriptions & Fan-Out](../04-pub-sub-topics-and-fan-out/) — the other shape. Instead of one consumer taking each message, every interested subscriber gets its own copy, and the producer stops needing to know who they are.
