# Why Async? Coupling and the Cost of the Direct Call

> Two services need to talk, and the obvious way is a phone call: A rings B and holds the line until B answers. It works beautifully until the day B is slow — and then A is slow, and A's callers are slow, and an outage nobody can locate is spreading up the call graph one held thread at a time. Asynchronous messaging is the difference between a phone call and voicemail. This lesson is about why voicemail exists, exactly what it costs, and how to tell which conversations need which.

**Type:** Learn
**Languages:** —
**Prerequisites:** [HTTP in Depth](../../01-networking-and-protocols/08-http-in-depth/), [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/)
**Time:** ~50 minutes

## The Problem

Everything you have built in this curriculum so far is a **synchronous request/response**. A client opens a TCP (Transmission Control Protocol) connection, sends an HTTP (HyperText Transfer Protocol) request, and *blocks* — the connection stays open, a thread or coroutine waits — until a response comes back. Phase 1 built the sockets; Phase 2 built the API on top. For "give me this user's profile *now*", it is exactly right: the caller literally cannot proceed without the answer.

Now watch it break. A user clicks **Place Order**. Your `orders` service, to finish that one request, must:

1. Charge the card — call `payments`
2. Reserve stock — call `inventory`
3. Send a confirmation email — call `email`
4. Notify the warehouse — call `shipping`
5. Update the recommendation model — call `analytics`

Five direct calls, inside the request. Three separate things now go wrong, and they compound.

**Latency stacks — and the tail stacks worse.** The user waits for the *sum*. At 200 ms each that is a full second of spinner, and the two calls they actually care about (charge, reserve) are held hostage by three they don't. But the average is the flattering number. Suppose each service is fast at p50 and has a p99 of 800 ms — utterly normal, that's a GC pause or a cold connection pool. The chance that a given request escapes *all five* slow tails is `0.99⁵ ≈ 0.951`, so **roughly 1 request in 20 hits at least one 800 ms tail.** Your p95 is now somebody else's p99. This is the central observation of Dean and Barroso's *The Tail at Scale* (Communications of the ACM, 56(2), 2013): fan out to enough dependencies and rare slowness stops being rare, because you are sampling the tail once per dependency.

**Failure propagates.** If `email` is down, the whole order fails — even though email has nothing to do with whether the order is *valid*. You have coupled the success of a critical operation to the health of a decorative one. Worse is the slow-failure case: `email` doesn't return errors, it just takes 30 seconds. Your `orders` threads pile up waiting on it, the pool exhausts, and `orders` stops serving requests that never needed email at all. A non-critical dependency has taken down a critical service without ever returning a single error.

**Load couples.** A spike on `orders` becomes an identical, simultaneous spike on all five downstreams, because every order fans out into five live calls in lockstep. There is no buffer anywhere. If `analytics` is provisioned for average load, it falls over at peak, and now it is applying backpressure into your checkout path.

Then do the availability arithmetic, which is the part that turns a design preference into a number:

```text
one service at 99.9%              ->  8.8 hours of downtime per year
5 services, all required          ->  0.999^5  = 99.50%  ->  43.8 hours/year
20 services, all required         ->  0.999^20 = 98.02%  ->  7.2 DAYS/year
```

Availability of a serial dependency chain is the **product** of its members, and products of numbers below one collapse fast. Every service you add to the critical path makes the whole path worse, permanently, and no amount of heroics in any single service fixes it — the math is doing it, not the code. You have built a system that is down for a cumulative week a year and you cannot point at whose fault it is.

This lesson is the fork in the road. Some communication *must* be synchronous. Some must not be. Telling them apart, and knowing what machinery the async branch demands, is the foundation for the other twelve lessons in this phase.

## The Concept

### What "synchronous" actually means

**Synchronous** communication is call-and-wait. The caller sends a request and does no further work until the response arrives or a timeout fires. The two parties are **coupled in time**: both must be alive, reachable, and responsive *at the same instant* for the exchange to happen at all. The caller holds a resource — a thread, a connection, a coroutine, a slot in a pool — open for the entire duration.

This is the HTTP request/response you built in Phase 1, and it is the correct model whenever the caller **cannot make progress without the answer**:

- *"Is this password correct?"* — you cannot render the next page until you know.
- *"What is the account balance?"* — the number **is** the response.
- *"Reserve seat 14C."* — the user needs a yes or no before they will pay.

The defining property: the request carries an implicit demand for a **fresh, immediate reply**, and the caller's next line of code depends on its content.

Note carefully what synchronous does *not* mean. It does not mean slow, and it does not mean blocking a thread. A call made with `await` in Python or a goroutine in Go is still **synchronous communication** if the logical flow waits for the reply before continuing. We will come back to this landmine at the end, because it confuses almost everyone.

### What "asynchronous" actually means

**Asynchronous** communication is send-and-continue. The sender hands its message to an intermediary and **immediately moves on**. It does not wait for the receiver to process the message, or even for the receiver to be awake. The receiver handles it later, on its own schedule, at its own pace.

The intermediary is the entire point. It is called a **broker** — and depending on its shape it is a *queue*, a *topic*, or a *log*, which are the next three lessons. It sits between sender and receiver and breaks the coupling between them.

Here is the same order flow, both ways:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="Comparison of synchronous fan-out and asynchronous fan-out for an order flow. Synchronously, the orders service calls five services in series inside the request, so latency is the sum and any one failure fails the order. Asynchronously, only payments and inventory are called directly and the remaining three receive a published event, so the user-facing request finishes in 202 milliseconds and survives downstream outages.">
  <defs>
    <marker id="l01-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The same order, two topologies</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="184" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="240" width="848" height="196" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="36" y="112" width="104" height="54" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="188" y="112" width="112" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="330" y="112" width="112" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="472" y="112" width="112" height="54" rx="9" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="614" y="112" width="112" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="756" y="112" width="86" height="54" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M140 139 L 182 139" marker-end="url(#l01-arrow)"/>
    <path d="M300 139 L 324 139" marker-end="url(#l01-arrow)"/>
    <path d="M442 139 L 466 139" marker-end="url(#l01-arrow)"/>
    <path d="M584 139 L 608 139" marker-end="url(#l01-arrow)"/>
    <path d="M726 139 L 750 139" marker-end="url(#l01-arrow)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="36" y="322" width="104" height="54" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="188" y="292" width="112" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="188" y="352" width="112" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="352" y="322" width="118" height="54" rx="9" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="546" y="272" width="112" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="546" y="326" width="112" height="42" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="546" y="380" width="112" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M140 337 L 182 315" marker-end="url(#l01-arrow)"/>
    <path d="M140 361 L 182 375" marker-end="url(#l01-arrow)"/>
    <path d="M300 349 L 346 349" marker-end="url(#l01-arrow)"/>
    <path d="M470 349 L 500 349"/>
    <path d="M500 349 L 500 293 L 540 293" marker-end="url(#l01-arrow)"/>
    <path d="M500 349 L 540 349" marker-end="url(#l01-arrow)"/>
    <path d="M500 349 L 500 401 L 540 401" marker-end="url(#l01-arrow)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="68" font-size="12.5" font-weight="700" fill="#e0930f">SYNCHRONOUS FAN-OUT — five calls on the critical path</text>
    <text x="34" y="88" font-size="9.5" opacity="0.85">latency = the sum · availability = the product · one dependency down = order lost</text>
    <text x="88" y="136" font-size="10" font-weight="700" text-anchor="middle">orders</text>
    <text x="88" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">waits ×5</text>
    <text x="244" y="136" font-size="10" font-weight="700" text-anchor="middle">payments</text>
    <text x="244" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">200 ms</text>
    <text x="386" y="136" font-size="10" font-weight="700" text-anchor="middle">inventory</text>
    <text x="386" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">200 ms</text>
    <text x="528" y="134" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">email</text>
    <text x="528" y="150" font-size="8.5" text-anchor="middle" font-weight="700" fill="#e0930f">DOWN</text>
    <text x="528" y="163" font-size="8" text-anchor="middle" opacity="0.75">order dies here</text>
    <text x="670" y="136" font-size="10" font-weight="700" text-anchor="middle" opacity="0.45">shipping</text>
    <text x="670" y="152" font-size="8.5" text-anchor="middle" opacity="0.4">never reached</text>
    <text x="799" y="136" font-size="10" font-weight="700" text-anchor="middle" opacity="0.45">analytics</text>
    <text x="799" y="152" font-size="8.5" text-anchor="middle" opacity="0.4">never reached</text>
    <text x="440" y="196" font-size="10.5" text-anchor="middle" opacity="0.95">user waits 1,000 ms for a result that needed 400 ms of work — and then gets a 500</text>
    <text x="440" y="214" font-size="9.5" text-anchor="middle" opacity="0.8">0.999^5 = 99.50% available · 43.8 hours of downtime per year</text>

    <text x="34" y="266" font-size="12.5" font-weight="700" fill="#0fa07f">ASYNCHRONOUS FAN-OUT — two calls on the critical path, three via the broker</text>
    <text x="88" y="346" font-size="10" font-weight="700" text-anchor="middle">orders</text>
    <text x="88" y="362" font-size="8.5" text-anchor="middle" opacity="0.8">returns fast</text>
    <text x="244" y="312" font-size="10" font-weight="700" text-anchor="middle">payments</text>
    <text x="244" y="326" font-size="8" text-anchor="middle" opacity="0.8">200 ms · SYNC</text>
    <text x="244" y="372" font-size="10" font-weight="700" text-anchor="middle">inventory</text>
    <text x="244" y="386" font-size="8" text-anchor="middle" opacity="0.8">200 ms · SYNC</text>
    <text x="411" y="342" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">BROKER</text>
    <text x="411" y="357" font-size="8.5" text-anchor="middle" opacity="0.85">publish · 2 ms</text>
    <text x="411" y="370" font-size="8" text-anchor="middle" opacity="0.75">OrderPlaced</text>
    <text x="602" y="290" font-size="9.5" font-weight="700" text-anchor="middle">shipping</text>
    <text x="602" y="303" font-size="8" text-anchor="middle" opacity="0.75">consumes later</text>
    <text x="602" y="344" font-size="9.5" font-weight="700" text-anchor="middle" fill="#7c5cff">email · DOWN</text>
    <text x="602" y="357" font-size="8" text-anchor="middle" opacity="0.85">message waits safely</text>
    <text x="602" y="398" font-size="9.5" font-weight="700" text-anchor="middle">analytics</text>
    <text x="602" y="411" font-size="8" text-anchor="middle" opacity="0.75">consumes later</text>
    <text x="762" y="330" font-size="10" font-weight="700" text-anchor="middle">USER SEES</text>
    <text x="762" y="348" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">202 ms · OK</text>
    <text x="762" y="366" font-size="8.5" text-anchor="middle" opacity="0.8">email sends when</text>
    <text x="762" y="379" font-size="8.5" text-anchor="middle" opacity="0.8">email recovers</text>
    <text x="440" y="456" font-size="10" text-anchor="middle" opacity="0.95">The order succeeded while a dependency was down. That is the entire value proposition of this phase.</text>
    <text x="440" y="474" font-size="9.5" text-anchor="middle" opacity="0.75">Critical path availability is now 0.999^3 (payments, inventory, broker) = 99.70% — and the broker is the new thing you must keep alive.</text>
  </g>
</svg>
```

The `orders` service is done in the time of two fast calls plus one broker write. It does **not** wait for the email. If `email` is down for ten minutes, the message sits safely in the broker and is delivered when `email` recovers. The order succeeded regardless.

The vocabulary, defined once and used for the rest of the phase:

- **Producer** (or **publisher**) — the service that *sends* a message.
- **Consumer** (or **subscriber**) — the service that *receives and processes* it.
- **Message** — a self-contained unit of data: a payload plus metadata (an id, a timestamp, a type). It is the **only** thing the two sides share. Lesson 2 dissects it.
- **Broker** — the intermediary that stores messages and routes them from producers to consumers.
- **Queue** — a broker structure where each message goes to exactly **one** consumer. Work distribution. Lesson 3.
- **Topic** — a broker structure where each message goes to **every** interested consumer. Broadcast, a.k.a. **pub/sub**. Lesson 4.
- **Log** — an append-only, replayable sequence of messages that consumers read at their own position. Lesson 5.

### The three couplings a broker actually breaks

"Decoupling" is the word everyone uses and almost nobody defines. It is really three separate independences, and naming them tells you precisely what async is protecting you from — and what it is *not*.

| Coupling | Synchronous (direct call) | Asynchronous (via broker) |
|---|---|---|
| **Temporal** — must both be up *right now*? | Yes. Callee down ⇒ call fails. | **No.** The message waits in the broker. |
| **Spatial / referential** — must the sender know the receiver? | Yes. The caller holds the callee's address and knows it exists. | **No.** The producer writes to a topic and never names a consumer. |
| **Load / rate** — must the receiver match the sender's speed? | Yes. A fast caller overruns a slow callee. | **No.** The queue *is* the buffer; the consumer drains at its own rate. |

The **spatial** row is the one that quietly changes how organisations build software. In the synchronous world, adding a sixth thing that must happen on every order means editing, testing, and redeploying `orders`. In the pub/sub world, the new service subscribes to `OrderPlaced` and `orders` never learns it exists. The producer's code stops growing a limb every time the business grows a requirement. That is why "event-driven" is an *organisational* strategy as much as a technical one — it is Conway's Law working for you instead of against you.

The **load** row is the most underrated, and it deserves real arithmetic.

### The queue as shock absorber — and the queueing theory behind it

A queue is a **buffer against variance**. When producers briefly outrun consumers, messages pool up (the **queue depth** rises) instead of crashing the consumer. The consumer works through the backlog at its sustainable rate.

Two results make this precise, and they are worth knowing by name because they govern every system in this phase.

**Little's Law** — `L = λW`. The average number of items in a stable system (`L`) equals the average arrival rate (`λ`) times the average time each item spends in it (`W`). It holds for *any* stable queue regardless of distribution, which is what makes it so useful. Read it three ways: a queue of 5,000 messages draining at 500/s is **10 seconds** of backlog; if you need backlog under 2 seconds at 500/s, your depth alarm belongs at 1,000; and if each message takes 200 ms to process and you want 500/s of throughput, you need `L = 500 × 0.2 = 100` messages in flight, so **100 concurrent consumers**. That last reading is how you size a consumer pool, and it is the same formula every time.

**The utilisation knee.** For a simple M/M/1 queue (Poisson arrivals, exponential service, one server), the average time in system is `W = 1/(μ − λ)`, where `μ` is the service rate. Take a consumer that handles `μ = 100` messages/second and push load at it:

```text
utilisation ρ = λ/μ      arrival λ        wait W = 1/(μ-λ)
     0.50                  50/s              20 ms
     0.80                  80/s              50 ms
     0.90                  90/s             100 ms
     0.95                  95/s             200 ms
     0.99                  99/s           1,000 ms      <- 50x the wait at half the load
```

Latency does not degrade linearly with load; it degrades **hyperbolically**, and the knee is brutally sharp above about 80%. Running a service at 99% utilisation is not "efficient", it is standing on the vertical part of a curve where a 1% traffic increase doubles your latency.

Here is the thing to internalise, because it is the whole reason this phase exists: **that wait happens either way.** Queueing is not something a broker introduces — it is a property of any system where arrivals sometimes exceed service capacity. The only question is *where the queue lives and who waits in it*.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Two charts showing where queueing happens. In the synchronous system the queue is implicit, formed of held threads and TCP backlog, and the user waits in it. In the asynchronous system the queue is explicit and durable in the broker, the user has already left, and queue depth rises and drains over the burst.">
  <defs>
    <marker id="l01-arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The queue exists either way — the design choice is where it lives</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="418" height="382" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="446" y="42" width="418" height="382" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
  </g>

  <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
    <path d="M64 350 L 396 350"/>
    <path d="M64 350 L 64 130"/>
    <path d="M494 350 L 826 350"/>
    <path d="M494 350 L 494 130"/>
  </g>

  <path d="M64 340 L 130 336 L 190 328 L 240 314 L 280 292 L 312 258 L 336 214 L 352 168 L 362 140" fill="none" stroke="#e0930f" stroke-width="2.6"/>
  <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 5" opacity="0.55">
    <path d="M280 292 L 280 350"/>
    <path d="M336 214 L 336 350"/>
  </g>

  <path d="M494 344 L 546 344 L 570 300 L 596 246 L 620 206 L 646 186 L 672 200 L 700 244 L 730 292 L 760 328 L 790 342 L 826 344" fill="none" stroke="#0fa07f" stroke-width="2.6"/>
  <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 5" opacity="0.55">
    <path d="M546 344 L 546 350"/>
    <path d="M790 342 L 790 350"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="1.6" stroke-dasharray="6 4" opacity="0.8">
    <path d="M494 168 L 826 168"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="34" y="68" font-size="12" font-weight="700" fill="#e0930f">SYNCHRONOUS — the implicit queue</text>
    <text x="34" y="87" font-size="9.5" opacity="0.85">held threads, connection pools, TCP accept backlog</text>
    <text x="34" y="103" font-size="9.5" opacity="0.85">the queue is invisible, unbounded, and in RAM</text>
    <text x="46" y="240" font-size="9" text-anchor="middle" transform="rotate(-90 46 240)" opacity="0.9">latency</text>
    <text x="230" y="372" font-size="9" text-anchor="middle" opacity="0.9">utilisation  ρ = λ/μ</text>
    <text x="280" y="366" font-size="8" text-anchor="middle" opacity="0.75">0.80</text>
    <text x="336" y="366" font-size="8" text-anchor="middle" opacity="0.75">0.95</text>
    <text x="376" y="152" font-size="9" font-weight="700" fill="#e0930f">W = 1/(μ-λ)</text>
    <text x="230" y="180" font-size="9" text-anchor="middle" opacity="0.9">the knee: past ~80%,</text>
    <text x="230" y="196" font-size="9" text-anchor="middle" opacity="0.9">1% more load doubles the wait</text>
    <text x="225" y="398" font-size="9.5" text-anchor="middle" font-weight="700">THE USER WAITS IN THIS QUEUE</text>
    <text x="225" y="414" font-size="8.5" text-anchor="middle" opacity="0.8">and when RAM runs out, the service dies</text>

    <text x="464" y="68" font-size="12" font-weight="700" fill="#0fa07f">ASYNCHRONOUS — the explicit queue</text>
    <text x="464" y="87" font-size="9.5" opacity="0.85">a durable, bounded, observable buffer</text>
    <text x="464" y="103" font-size="9.5" opacity="0.85">depth is a metric you can alarm on</text>
    <text x="476" y="240" font-size="9" text-anchor="middle" transform="rotate(-90 476 240)" opacity="0.9">queue depth</text>
    <text x="660" y="372" font-size="9" text-anchor="middle" opacity="0.9">time  →  a 10x burst arrives and drains</text>
    <text x="546" y="366" font-size="8" text-anchor="middle" opacity="0.75">burst</text>
    <text x="790" y="366" font-size="8" text-anchor="middle" opacity="0.75">drained</text>
    <text x="820" y="160" font-size="8.5" text-anchor="end" fill="#3553ff" font-weight="700">alarm threshold — Little's Law: depth ÷ drain rate = seconds of backlog</text>
    <text x="660" y="398" font-size="9.5" text-anchor="middle" font-weight="700">THE USER ALREADY LEFT</text>
    <text x="660" y="414" font-size="8.5" text-anchor="middle" opacity="0.8">consumers drain at their sustainable rate</text>

    <text x="440" y="448" font-size="10" text-anchor="middle" opacity="0.95">Async does not remove the wait. It moves the wait off the user's request and into a place you can see, bound, and alarm on.</text>
  </g>
</svg>
```

In a synchronous system the queue still forms — it is just made of held threads, exhausted connection pools, and the kernel's TCP accept backlog. It is **invisible** (no metric reports it), **unbounded** (until memory runs out), and **the user is standing in it**. In an asynchronous system the queue is an explicit, durable, bounded, measurable object with a name and a depth metric. Async does not abolish queueing. It **relocates** it somewhere you can observe and control. That reframing is most of the value.

### The trade you are actually making

Async is not a free upgrade, and treating it as one is how systems get *worse*. You are trading a set of easy problems for a set of harder ones, and you should be able to state all four:

**You lose the immediate result.** The producer receives an acknowledgement that the message was *stored*, not that it was *processed*. If the work fails later — bad card, out of stock — you have already told the user "OK". You now need a way to report failure asynchronously: a status field the client polls, a websocket push, an email, or a **compensating action** that undoes the earlier step. Lesson 11 covers compensation properly under sagas. The work does not disappear; it changes shape from *"handle the error"* to *"design the failure notification."*

**You gain eventual consistency.** The system is deliberately, briefly wrong: the order exists before the email is sent, before the warehouse knows, before analytics updates. Different parts of the system disagree for seconds or minutes. It converges — *eventually* — but any code that assumes "if the order row exists, the confirmation was sent" is now a bug. This is the same ACID-versus-BASE trade from Phase 4, resurfacing at the messaging layer. The hard part is rarely technical; it is that a product manager must accept a UI that says "processing" instead of "done".

**You add critical infrastructure.** The broker must be run, monitored, scaled, upgraded, and kept from losing messages. Look again at the diagram: the critical path went from five dependencies to three, and one of the three is *the broker*. You did not eliminate a dependency, you **swapped five specialised ones for a single shared one that everything now relies on**. That is usually an excellent trade — a broker is a simpler, more reliable, more heavily engineered thing than your `email` service — but it is a trade, and the broker is now the most consequential machine you own. New failure modes come with it: a full disk, a stuck consumer, a silently growing backlog, a partition leader election gone wrong.

**Debugging gets harder.** A synchronous call has one stack trace. An async flow is a chain of hops across services *and across time*. "Why didn't this email send?" is no longer a log line; it is a distributed-tracing investigation. This is precisely why Phase 9 (correlation IDs, trace context propagation) is not optional in an event-driven system — you must propagate a `trace_id` through the message envelope, which is exactly what Lesson 2 builds.

The honest one-sentence summary: **synchronous trades resilience for simplicity and a fresh answer; asynchronous trades simplicity and immediacy for resilience and scale.**

### The decision rule

Do not choose by fashion. Choose by asking one question about the caller: **does the caller's very next step depend on the result?**

```text
Does the caller need the result to continue?

  YES — a query, or a human is waiting on the answer
     -> SYNCHRONOUS.  HTTP / gRPC request-response.
        "read the balance", "check the password", "reserve the seat"

  NO  — a side effect, a notification, or work for later
     -> ASYNCHRONOUS. Publish a message to a broker.
        "send the email", "update analytics", "notify the warehouse", "resize the image"
```

Apply it to the order and the mess resolves itself. **Charge the card, reserve the stock** — the user is standing there waiting to learn whether the order went through, and the answer gates their next action. Synchronous. **Send the email, notify the warehouse, update analytics** — none of these needs to have *happened* before the user sees "Order placed!". They are side effects the system owes the world, but not *now*, and not on the critical path. Asynchronous: publish one `OrderPlaced` event and let each service react on its own time.

Two refinements that separate a junior answer from a senior one.

**Most real requests are a mix**, and the split is per-call, not per-service. The question is never "should `orders` be async?" — it is "should *this particular call* be async?" The same pair of services can have both kinds of conversation.

**"A human is waiting" is not the same as "the caller needs the result."** A user waiting on a slow report does not need the *bytes* before the request returns; they need an acknowledgement and a way to collect the result later. That is the standard async job pattern: `202 Accepted`, a job id, and a `Location` header to poll — which is Phase 2's asynchronous-request-reply, now with a real broker behind it.

### Two things that look like async and are not

**Request-reply over a broker.** A producer publishes a request to a queue, then blocks reading a correlated reply queue. Every message is asynchronous; the *system* is entirely synchronous. You still have temporal coupling (the consumer must be up *now* or you time out), you still have latency on the critical path, and you have added a broker's worth of hops and operational burden to get it. The pattern is legitimate — it is how some RPC-over-AMQP systems work, and it buys you location transparency and load balancing — but do not confuse it with decoupling. **If the producer waits for a result, it is synchronous communication no matter what transport carries it.**

**`async`/`await`, goroutines, promises.** Python's `async`/`await`, JavaScript's promises, Go's goroutines are **asynchronous *programming***: a single-process technique for not blocking a thread while waiting on I/O (Phase 8 covers it properly). That is a different thing from the **asynchronous *communication*** in this phase, which decouples two *separate services in time* via a broker. You can call a remote service with `await` and still be doing fundamentally synchronous communication — your code did not block a thread, but the logical flow still waits for the reply, the callee still has to be up, and the availability still multiplies. The shared keyword is a genuine trap: this phase is about **architecture**, not about a concurrency primitive.

A useful test: *if the receiving service is switched off for ten minutes, does the sender's work survive?* If yes, it is asynchronous communication. If no, it is a synchronous call wearing a costume.

### When async is the wrong answer

Symmetry demands this section, because the failure mode of this phase is applying it everywhere.

- **Reads.** A query wants a fresh answer. Putting a broker in front of a read is almost always wrong.
- **Strong, immediate consistency requirements.** "Do not let two people book the same seat" wants a transaction, not an event. Some invariants must be enforced synchronously, at a single point, or they are not invariants.
- **Simple systems with two services and one deploy.** The broker's operational cost is real and roughly fixed. Below a certain scale it exceeds the coupling it removes. A direct call with a sane timeout, a retry with jitter, and a circuit breaker is a *perfectly good* architecture and much easier to debug at 3 a.m.
- **When you have not solved idempotency.** Async delivery is almost always at-least-once (Lesson 6), which means duplicates. If your consumer cannot safely process the same message twice, async will corrupt your data faster than sync ever failed. Idempotency is the entry fee, not an optimisation.

The counter-pressure to all of this: async wins overwhelmingly for side effects, fan-out, load levelling, spiky workloads, cross-team integration, and anything where a slow dependency must not become your outage. That is a *lot* of a mature backend — which is why the remaining twelve lessons exist.

## Think about it

1. A signup flow does five things: create the user row, hash the password, send a welcome email, add the user to the marketing CRM, and provision a default workspace. Sort each into synchronous or asynchronous using the decision rule — and note that one of them is a trick, because it is not a service call at all.

2. Your teammate proposes making the payment charge asynchronous too, "so checkout is even faster". Using the *"you lose the immediate result"* trade-off, describe the specific bad user experience this creates, and what you would have to build to make it acceptable. (Real businesses do exactly this — what do they build?)

3. Twenty synchronous services, each 99.9% available, chained so one request touches all twenty. Compute the combined availability and the annual downtime. Now make nineteen of those calls asynchronous. Recompute for the user-facing request — and name the component whose availability you just made critical instead.

4. A producer emits 10× its normal rate for thirty seconds. Using Little's Law, compute the peak queue depth if the consumer drains at 500 messages/second and normal load is 400/second. How long after the burst ends does the backlog clear — and what would have happened in the fully synchronous version?

5. Your team adds a broker, and the producer publishes a message and then blocks waiting on a reply queue with a 5-second timeout. List which of the three couplings (temporal, spatial, load) this design actually breaks, and which it leaves fully intact.

6. You are running a consumer at 95% utilisation because "the CPU graph looks efficient". Using the utilisation table, explain to a manager why you want to add capacity, in terms of what happens to latency when traffic grows 5%.

## Key takeaways

- **Synchronous** communication is call-and-wait: the caller blocks until the reply arrives, and both parties must be healthy *at the same instant* (**temporal coupling**). It is the right model when the caller's next step depends on the result — reads, checks, reservations.
- **Availability multiplies down a synchronous chain.** Five services at 99.9% give 99.5% (43.8 hours down per year); twenty give 98.02% (7.2 days). Latency stacks the same way, and *tail* latency stacks worse — fan out to five dependencies with an 800 ms p99 and roughly 1 request in 20 hits a slow tail.
- **Asynchronous** communication is send-and-continue through a **broker**: the producer hands off a message and moves on; the consumer processes it later on its own schedule. It is the right model for side effects and work-for-later — emails, notifications, analytics, fan-out.
- A broker breaks **three couplings**: **temporal** (the receiver may be down), **spatial** (the sender need not know the receiver exists — this is what lets new services subscribe without editing the producer), and **load** (the queue absorbs bursts as a shock absorber).
- **Async does not remove queueing; it relocates it.** In a synchronous system the queue is made of held threads and TCP backlog — invisible, unbounded, and the user is standing in it. In an async system it is explicit, durable, bounded, and has a depth metric. **Little's Law (`L = λW`)** sizes it: depth ÷ drain rate = seconds of backlog, and `arrival rate × processing time` = the consumer concurrency you need.
- **Latency degrades hyperbolically with utilisation**, not linearly (`W = 1/(μ − λ)`). The knee is near 80%; at 99% utilisation the wait is 50× what it was at 50%. "High utilisation" is not efficiency, it is fragility.
- The trade is real: you give up the immediate result and strict consistency, and take on **eventual consistency**, a broker to operate, and much harder debugging — in exchange for **resilience and scale**. You also swap five specialised dependencies for one shared critical one. Async is a tool, not an upgrade.
- The decision rule is one question: **does the caller's next step depend on the result?** Yes → synchronous. No → asynchronous. Most real requests are a mix, and the choice is made *per call*, not per service.
- Do not confuse async **communication** (this phase — decoupling services in time via a broker) with async **programming** (`await`, goroutines — not blocking a thread inside one process). The test: **if the receiver is switched off for ten minutes, does the sender's work survive?**

Next: [Anatomy of a Message](../02-anatomy-of-a-message/) — before building a broker, we build the thing it carries: the envelope, the payload, the id that makes retries safe, and the serialization decision you will live with for years.
