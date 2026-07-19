# Backpressure, Queueing & Load Shedding

> A dependency gets 20% slower. Nothing errors, nothing crashes, and every request your workers are executing was abandoned by its caller long ago. Measured here: the same overload through an unbounded queue and a 40-item bounded one completed the identical 9,462 requests — but the unbounded run's p99 was 61 seconds and **98% of its completed work was already past its deadline**, perfect answers nobody would ever read. Then the part that ends careers: remove the original slowdown and the system does not recover. This lesson builds the one capability that gets you out, which is the ability to say no.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Concurrency?](../01-why-concurrency/), [Thread Pools & Work Queues](../07-thread-pools-and-work-queues/)
**Time:** ~80 minutes

## The Problem

It is 14:12. The recommendations service your checkout endpoint calls got 20% slower — a routine index change on their side, well within their SLO (Service Level Objective, the latency target a team promises). Nothing on your dashboards is red. Your error rate is 0.00%. Your CPU is at 40%. Your service is *fine*.

Except that each request now occupies one of your worker threads for 60 ms instead of 50 ms. You have four workers, so your capacity just fell from 80 requests per second to 67. Traffic did not change: it is still the 75 req/s it has been all morning. Yesterday that was 94% utilization, which is uncomfortable but survivable. Today it is 112%, which is not a percentage — it is a **deficit of 8 requests per second, accumulating forever**.

Here is what those eight requests per second do, in order:

**14:12 — the queue starts to grow.** Nothing is wrong yet. The queue in front of your worker pool is doing exactly what a queue is for: absorbing the mismatch. Nobody looks at it, because queue depth is not on the dashboard, and even if it were, "37" is not an alarming number.

**14:13 — queue time becomes latency.** A request that arrives now waits behind 480 others. At 67/s that is 7.2 seconds of waiting before a worker even *starts* on it. Your served latency is the same 60 ms it always was; your **observed** latency, the only one the caller can measure, is 7.3 seconds.

**14:13:30 — the callers give up.** Their timeout is 2 seconds. Every request now in your queue will breach it before it is dequeued. Your workers are still 100% busy, still producing correct responses at 67 per second, and every single one of those responses is written to a socket whose reader disconnected five seconds ago. Your **throughput** is unchanged. Your **goodput** — answers that reach a caller still waiting for them — is zero.

**14:13:35 — the retries arrive.** The client library has a sane, standard, thoroughly reviewed policy: three attempts. So each abandoned request comes back as a new one. Your arrival rate does not stay at 75/s; it climbs toward 225/s. Your capacity went *down* by 20% and your load went *up* by 200%, and the second thing was caused by the first.

**14:14 — memory.** Each queued request holds its parsed headers, its body buffer, its trace context. At 8 KB apiece and 20,000 queued, that is 160 MB of heap you did not budget for, and the garbage collector now has 20,000 live objects to walk on every cycle, which makes each request a little slower, which grows the queue a little faster.

**14:22 — the fix lands.** The recommendations team reverts their index change. Latency returns to 50 ms. Your capacity is 80 req/s again. Real demand is still 75 req/s. **And nothing gets better.** Your arrival rate is not 75/s any more; it is 200-odd req/s of retries chasing requests that timed out because of retries. The queue does not drain, because ρ is still above 1. The trigger is gone and the failure is not, because the failure stopped depending on the trigger some time around 14:13:35.

This is not a bug you can find in a stack trace. It is a **metastable failure**: a system pushed into a bad state that it now *sustains on its own*, through a feedback loop it constructed out of ordinary, correct components. Everything in that story — the queue, the retry policy, the timeout — was best practice. Together they built a machine for staying down.

There are exactly two ways out. You drop load, or you restart the process, which is dropping all of it at once with extra steps. **If your service has no way to shed load, your only incident response is a restart.** This lesson is about building the other option.

## The Concept

### Every system is a queueing system

Three numbers describe any server. **λ** (lambda) is the **arrival rate**: requests per second showing up. **µ** (mu) is the **service rate**: requests per second one server can finish. **ρ** (rho) is **utilization**, `ρ = λ / µ` — the fraction of the time your server is busy.

For the simplest queue (one server, random arrivals, random service times), the average time a request spends **in the system** — queueing plus being served — is:

```text
W = S / (1 - rho)          S = the service time; W = what the caller measures
```

Stare at the denominator, because that is the whole lesson. As ρ approaches 1, `1 − ρ` approaches 0, and W goes to infinity. Not "gets slow". **Infinity.** Lesson 1 printed this table; it is worth reprinting because everything that follows is a consequence of it:

```text
  rho     W / S      what it means
  0.50      2.0x     half-busy, and waiting already doubles your service time
  0.70      3.3x
  0.80      5.0x     the last "comfortable" number on most dashboards
  0.90     10.0x     +12.5% more work than 0.80, +100% more latency
  0.95     20.0x
  0.99    100.0x     +10% more work than 0.90, +900% more latency
```

The measured columns in the Build It confirm this to within a few percent. The trap is not the formula; the trap is the *shape*:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="Response time as a multiple of service time plotted against utilization rho. With steady service times the curve crosses ten times service time at rho equals 0.90; with variable service times, CV squared of four, the same curve crosses ten times at rho equals 0.78, so the knee moves left. Measured simulation points sit on the steady-service curve, and both curves go vertical at rho equals one.">
  <defs>
    <marker id="l11-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The knee is a cliff you cannot see on a utilization graph</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M90 340 L 800 340"/><path d="M90 340 L 90 62"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.45">
      <path d="M228 340 L 228 345"/><path d="M366 340 L 366 345"/><path d="M504 340 L 504 345"/><path d="M642 340 L 642 345"/><path d="M780 340 L 780 345"/><path d="M85 295 L 90 295"/><path d="M85 238.75 L 90 238.75"/><path d="M85 182.5 L 90 182.5"/><path d="M85 126.25 L 90 126.25"/><path d="M85 70 L 90 70"/>
    </g>
    <path d="M780 340 L 780 62" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 5" opacity="0.8"/><path d="M90 238.75 L 776 238.75" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 5" opacity="0.45"/>

    <path d="M90 340 L 228 337.2 L 366 332.5 L 435 328.8 L 504 323.1 L 573 313.8 L 642 295 L 676 276 L 711 238.8 L 732 190 L 745 126 L 752 70" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M90 340 L 228 333 L 366 321.3 L 435 311.9 L 504 297.8 L 573 274.4 L 628 240.4 L 642 227.5 L 676 180.6 L 697 133.7 L 711 87 L 719 70" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-linejoin="round" stroke-dasharray="7 4"/>

    <g fill="#3553ff" stroke="#3553ff" stroke-width="1.6" fill-opacity="0.35">
      <circle cx="435" cy="328.8" r="4.5"/><circle cx="573" cy="313.8" r="4.5"/><circle cx="642" cy="295" r="4.5"/><circle cx="711" cy="242.1" r="4.5"/><circle cx="745" cy="95.9" r="4.5"/>
    </g>
    <g fill="none" stroke-width="2">
      <circle cx="711" cy="238.8" r="9" stroke="#0fa07f"/><circle cx="628" cy="240.4" r="9" stroke="#e0930f"/>
    </g>
    <path d="M600 208 L 622 231" fill="none" stroke="#e0930f" stroke-width="1.5" marker-end="url(#l11-a1)"/><path d="M756 268 L 719 246" fill="none" stroke="#0fa07f" stroke-width="1.5" marker-end="url(#l11-a1)"/>

    <g fill="currentColor">
      <text x="90" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">0.0</text><text x="228" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">0.2</text><text x="366" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">0.4</text><text x="504" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">0.6</text><text x="642" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">0.8</text>
      <text x="780" y="360" font-size="9.5" text-anchor="middle" opacity="0.7">1.0</text><text x="440" y="380" font-size="10.5" text-anchor="middle" opacity="0.85">utilization  rho = arrival rate / service rate</text><text x="78" y="299" font-size="9.5" text-anchor="end" opacity="0.7">5x</text><text x="78" y="242" font-size="9.5" text-anchor="end" opacity="0.7">10x</text>
      <text x="78" y="186" font-size="9.5" text-anchor="end" opacity="0.7">15x</text><text x="78" y="130" font-size="9.5" text-anchor="end" opacity="0.7">20x</text><text x="78" y="74" font-size="9.5" text-anchor="end" opacity="0.7">25x</text><text x="30" y="205" font-size="10.5" opacity="0.85" transform="rotate(-90 30 205)" text-anchor="middle">W / S</text>
      <text x="790" y="320" font-size="10" fill="#d64545" font-weight="700">rho = 1</text><text x="790" y="334" font-size="9" fill="#d64545">vertical</text>
    </g>
    <g fill="currentColor">
      <text x="150" y="110" font-size="11.5" font-weight="700" fill="#0fa07f">— steady service:  W/S = 1/(1-rho)</text><text x="150" y="130" font-size="11.5" font-weight="700" fill="#e0930f">- - variable service (CV^2 = 4)</text><text x="150" y="150" font-size="11.5" font-weight="700" fill="#3553ff">o  measured, 900k simulated requests</text><text x="150" y="176" font-size="10" opacity="0.9">rho = 0.50 -&gt; 2.0x</text>
      <text x="330" y="176" font-size="10" opacity="0.9">rho = 0.90 -&gt; 9.7x</text><text x="150" y="192" font-size="10" opacity="0.9">rho = 0.80 -&gt; 5.0x</text><text x="330" y="192" font-size="10" opacity="0.9">rho = 0.95 -&gt; 22.7x</text><text x="596" y="200" font-size="10" font-weight="700" fill="#e0930f" text-anchor="end">knee at 0.78</text>
      <text x="760" y="286" font-size="10" font-weight="700" fill="#0fa07f">knee at 0.90</text>
    </g>
    <text x="440" y="405" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Going 80% -&gt; 90% busy is +12.5% work and +100% latency. Variability moves that cliff to 78%.</text>
  </g>
</svg>
```

**The knee is not visible on a utilization graph.** A utilization graph is a straight line from 0 to 1; it looks the same at 0.85 as it does at 0.60. All the information lives in the *derivative of a different curve*. Between ρ = 0.8 and ρ = 0.9 you added 12.5% more traffic and doubled your latency. Between 0.9 and 0.99 you added 10% more traffic and multiplied latency by ten. There is no warning, because "utilization is 89%" is not a warning — until it is 91%, and then it is an outage.

And it is worse than the formula says, because the formula assumes a specific amount of randomness. The general result (Pollaczek–Khinchine) is:

```text
W / S  =  1 + rho * (1 + CV^2) / (2 * (1 - rho))
```

where **CV² is the squared coefficient of variation** of your service times — variance divided by mean squared. CV² = 1 recovers `1/(1−ρ)`. But real endpoints are not CV² = 1. A cache hit costs 2 ms and a cache miss costs 30 ms; a query over one row costs 1 ms and a query over ten thousand costs 400. The Build It measures a distribution where 95% of requests are fast and 5% are 6× the mean — CV² ≈ 4 — and the result is stark: **the point where latency reaches 10× service time moves from ρ = 0.90 to ρ = 0.78.** Bursty arrivals do the same thing. This is why real systems fall over at utilizations that "should" be safe, and why capacity planning against the mean is a planning exercise in fiction.

### You have more queues than you think

Engineers protect one queue and leave five unbounded, because the other five do not look like queues. Here is the full inventory for a single HTTP request:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 456" width="100%" style="max-width:840px" role="img" aria-label="An inventory of the seven queues a single request passes through, from the kernel accept backlog to the client retry queue, each with the knob that bounds it and the default value that knob ships with. The accept backlog and socket receive buffer are bounded by default; the web server connection queue, the worker pool work queue, the connection pool wait queue, the database queue and the client retry queue are all unbounded by default and marked in red.">
  <defs>
    <marker id="l11-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">You have more queues than you think — and five ship unbounded</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65">
      <text x="46" y="62">THE QUEUE</text><text x="330" y="62">THE KNOB THAT BOUNDS IT</text><text x="600" y="62">THE DEFAULT YOU INHERIT</text><text x="866" y="62" text-anchor="end">BOUND?</text>
    </g>
    <path d="M28 70 L 852 70" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/><path d="M34 84 L 34 424" fill="none" stroke="#3553ff" stroke-width="1.6" stroke-dasharray="4 4" opacity="0.7" marker-end="url(#l11-a2)"/>

    <g fill="none" stroke-width="1.8">
      <rect x="44" y="78" width="262" height="38" rx="7" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="44" y="126" width="262" height="38" rx="7" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="44" y="174" width="262" height="38" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/><rect x="44" y="222" width="262" height="38" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
      <rect x="44" y="270" width="262" height="38" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/><rect x="44" y="318" width="262" height="38" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/><rect x="44" y="366" width="262" height="38" rx="7" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>

    <g fill="currentColor" font-size="10.5">
      <text x="58" y="96" font-weight="700">1. kernel SYN + accept queue</text><text x="58" y="110" font-size="9" opacity="0.75">before your process ever sees it</text><text x="58" y="144" font-weight="700">2. socket receive buffer</text><text x="58" y="158" font-size="9" opacity="0.75">bytes the peer already sent you</text><text x="58" y="192" font-weight="700">3. web server connection queue</text>
      <text x="58" y="206" font-size="9" opacity="0.75">accepted, not yet dispatched</text><text x="58" y="240" font-weight="700">4. worker-pool work queue</text><text x="58" y="254" font-size="9" opacity="0.75">dispatched, waiting for a thread</text><text x="58" y="288" font-weight="700">5. connection-pool wait queue</text><text x="58" y="302" font-size="9" opacity="0.75">holding a thread, waiting for a conn</text>
      <text x="58" y="336" font-weight="700">6. the database's own queues</text><text x="58" y="350" font-size="9" opacity="0.75">lock waits, I/O, its own workers</text><text x="58" y="384" font-weight="700">7. the client-side retry queue</text><text x="58" y="398" font-size="9" opacity="0.75">the one that is not on your machine</text>
    </g>

    <g fill="currentColor" font-size="9.5" opacity="0.95">
      <text x="330" y="94">listen(fd, backlog)</text><text x="330" y="108" opacity="0.7">net.core.somaxconn</text><text x="330" y="142">SO_RCVBUF / TCP window</text><text x="330" y="156" opacity="0.7">tcp_rmem autotuning</text><text x="330" y="190">--backlog, --limit-concurrency</text><text x="330" y="204" opacity="0.7">nginx limit_conn / limit_req</text><text x="330" y="238">Queue(maxsize=N)</text>
      <text x="330" y="252" opacity="0.7">ThreadPoolExecutor has none</text><text x="330" y="286">pool_size, max_overflow</text><text x="330" y="300" opacity="0.7">pool_timeout</text><text x="330" y="334">max_connections</text><text x="330" y="348" opacity="0.7">statement_timeout, lock_timeout</text><text x="330" y="382">retry budget (% of traffic)</text><text x="330" y="396" opacity="0.7">max attempts, backoff, jitter</text>
    </g>

    <g font-size="9.5">
      <text x="600" y="94" fill="#0fa07f" font-weight="700">4096 on modern Linux</text><text x="600" y="108" fill="currentColor" opacity="0.7">but 128 on older kernels</text><text x="600" y="142" fill="#0fa07f" font-weight="700">capped, and TCP tells the peer</text><text x="600" y="156" fill="currentColor" opacity="0.7">this is backpressure done right</text>
      <text x="600" y="190" fill="#d64545" font-weight="700">unset = accept everything</text><text x="600" y="204" fill="currentColor" opacity="0.7">uvicorn --backlog 2048, no limit</text><text x="600" y="238" fill="#d64545" font-weight="700">maxsize=0 means INFINITE</text><text x="600" y="252" fill="currentColor" opacity="0.7">the default of every stdlib pool</text>
      <text x="600" y="286" fill="#d64545" font-weight="700">no cap on WAITERS</text><text x="600" y="300" fill="currentColor" opacity="0.7">30 s each, all threads parked</text><text x="600" y="334" fill="#d64545" font-weight="700">no statement_timeout</text><text x="600" y="348" fill="currentColor" opacity="0.7">a query can run forever</text><text x="600" y="382" fill="#d64545" font-weight="700">3 attempts, no budget</text>
      <text x="600" y="396" fill="currentColor" opacity="0.7">3x your load when you are down</text>
    </g>

    <g font-size="10" font-weight="700" text-anchor="end">
      <text x="866" y="101" fill="#0fa07f">YES</text><text x="866" y="149" fill="#0fa07f">YES</text><text x="866" y="197" fill="#d64545">NO</text><text x="866" y="245" fill="#d64545">NO</text><text x="866" y="293" fill="#d64545">NO</text><text x="866" y="341" fill="#d64545">NO</text><text x="866" y="389" fill="#d64545">NO</text>
    </g>
    <text x="440" y="440" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Bounding one queue just moves the backlog to the next one. Bound them all, or bound none and pretend.</text>
  </g>
</svg>
```

Two of these deserve a note. The **accept queue** is really two queues: the kernel's **SYN queue** holds half-open connections (SYN received, handshake not finished — see [Transport Layer: TCP vs UDP](../../01-networking-and-protocols/05-transport-layer-tcp-vs-udp/)), and the **accept queue** holds completed connections waiting for your process to call `accept()`. The `backlog` argument to `listen()` sizes the second one, capped by `net.core.somaxconn`. When it overflows, Linux silently drops the SYN-ACK by default, and the client sees a timeout rather than a refusal — an outage that produces no log line on your side at all.

The **connection-pool wait queue** (Lesson 12) is the one that surprises people most, because it inverts the usual reasoning. A thread waiting for a database connection is *not idle* — it is a fully allocated worker, holding its request's memory, doing nothing. Bounding your worker pool at 200 and your connection pool at 20 does not give you a 20-deep bottleneck; it gives you 180 threads parked in a wait queue with a 30-second timeout, all of them consuming memory and none of them consuming CPU.

### An unbounded queue is a latency bomb

Lesson 7 stated the rule; here it is as the central law of this lesson:

> **An unbounded queue does not absorb overload. It converts a fast, honest failure into a slow, dishonest success — and then it kills you anyway.**

With a bound, an overloaded system rejects some requests instantly and serves the rest correctly. Without one, it accepts everything, serves nothing usefully, and grows until the process dies. The Build It runs both under identical 2× overload for two simulated minutes. **Both completed exactly 9,462 requests.** Identical throughput. The difference is everything else: the unbounded run had a p50 of 31.5 seconds and a p99 of 61 seconds against a 1-second deadline, peaked at 9,957 queued requests (~82 MB of live objects at 8 KB each), and **98% of everything it completed was already past its deadline.** The bounded run had a p99 of 794 ms, peaked at 40 queued items (0.3 MB), and wasted 0%. Note the *order* in which things die. Memory is the second victim and gets all the attention because it produces a crash with a stack trace. The **deadline is the first victim**, and it dies silently, long before the heap does.

### Backpressure vs load shedding — different answers, both needed

These get used as synonyms. They are opposites.

**Backpressure** propagates "slow down" *upstream* to the producer. It works when the producer is something you control and something that can wait. Blocking on a bounded channel is backpressure. So is refusing to read from a socket, and so is an HTTP/2 stream window ([HTTP/2 and HTTP/3](../../01-networking-and-protocols/11-http2-and-http3-quic/)). The canonical example is already in your head from Phase 1: **TCP flow control**. Every TCP segment carries a **receive window** — the number of bytes the receiver still has room for. When your application stops calling `read()`, the kernel's receive buffer fills, the advertised window shrinks, and when it reaches zero the *sender stops sending*. No data is lost. No error is raised. The producer is simply throttled to the consumer's actual rate, by a mechanism that runs beneath both of them. That is what backpressure looks like when it is done right, and it is the standard everything else is measured against.

**Load shedding** *drops* work you cannot do, and returns a fast, explicit failure — `429 Too Many Requests` or `503 Service Unavailable`, ideally with `Retry-After`. It is what you do when the producer is the public internet and cannot be told anything, or when it is a client that will simply retry harder if you slow it down. The choice is not stylistic:

- **Producer is yours, can wait, work is durable?** Backpressure. A batch job, a worker consuming from a broker, an internal pipeline. [Backpressure, Consumer Lag & Flow Control](../../06-messaging-and-pub-sub/09-backpressure-lag-and-flow-control/) covers this case in depth for message consumers — how lag is measured, how a broker's prefetch and flow control work, and why an autoscaler can make it worse. **This lesson is the other half: the in-process, request-serving case**, where the producer is a user with a timeout and there is no broker to hold anything.
- **Producer is a human with a 2-second attention span?** Shed. Slowing them down does not reduce demand; it *increases* it, because a slow response and a failed response both produce a retry, and the slow one costs you a worker on the way.

### Timeouts are load shedding

This is the deepest idea here, and it is one line: **a request whose deadline has passed is worthless, and executing it consumes capacity a live request needed.**

Once you accept that, the implementation follows. It is not enough to check the deadline when you *start* a request — by then you have already paid the queueing cost. **Check the deadline when you dequeue**, and discard expired work immediately, before it touches a worker. Dropping an expired item is free; executing one costs you a full service time you will never get back. Now the counterintuitive part, and it is real: **under overload, LIFO beats FIFO.**

FIFO (first in, first out) is fair, and fairness is exactly what kills you. Under sustained overload the head of a FIFO queue is always the *oldest* item — the one that has already spent its entire latency budget waiting. Serve it and it completes late. Serve the next one and it completes late too. Everyone waits the maximum; everyone times out; your success rate is zero and it is *uniformly* zero. LIFO (last in, first out) serves the **newest** request — the one that just arrived and still has its whole budget. That one finishes in time. The old ones at the tail age out and get dropped. You have converted "everybody fails" into "some people succeed and the rest fail fast," which is strictly better for every user and every business metric. Meta has described running LIFO queues in production for exactly this reason.

The fairness objection is honest and should be stated plainly: under LIFO, the requests that get dropped are the ones that waited longest, which feels unjust. Two answers. First, under overload *someone* is being dropped no matter what; the only question is whether you also waste capacity on them first. Second, LIFO's unfairness only appears when the queue is deep — that is, only during overload. When you are healthy the queue is nearly empty and LIFO and FIFO are indistinguishable. It is a discipline that changes behaviour exactly when you need it to. The Build It measures all three: naive FIFO produces **1.2 successful responses per second**; FIFO with a dequeue-time deadline check produces **16.5/s**; LIFO with the same check produces **80.1/s — the full capacity of the pool.**

### Queue time is the health signal, not queue depth

"Queue depth is 400" tells you nothing. Four hundred items drained at 10,000/s is 40 milliseconds of work; drained at 20/s it is twenty seconds. **A count is meaningless without a rate**, and the rate moves. Measure **the age of the oldest item in the queue** instead. It requires no division, it needs no other metric to interpret, and it is directly comparable to the number you actually care about — the caller's deadline. It gives you a rule you can put in code without a meeting:

> **If the oldest queued item has waited longer than the deadline budget, shed.** If it has waited longer than *(deadline − expected service time)*, shed it too: you cannot finish it in time, so starting it is pure waste.

Emit it as a gauge (`queue_oldest_item_age_seconds`) and put it on the dashboard next to goodput. See [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) for why a *gauge* sampled every 15 seconds can miss a 4-second saturation spike entirely, and count the shed events with a counter so nothing hides between scrapes.

### Admission control and adaptive concurrency limits

**Admission control** means deciding, at the front door, how many requests may be in flight at once, and rejecting the rest immediately. The simplest correct version is a semaphore. Sizing it from Little's Law (`L = λ × W`) is a good start: if you want to serve 400 req/s at 20 ms, you need `400 × 0.020 = 8` concurrent requests. Set the limit slightly above that and you have a bound. And it is wrong the moment your dependency's latency changes, which it will. A limit sized for a healthy 20 ms dependency is a limit that permits 8 concurrent requests. When that dependency degrades to 50 ms, the correct limit is different, and your fixed one is now either strangling you or letting through work that will time out.

The fix is to stop configuring a number and start **measuring congestion**, exactly the way TCP does. TCP has no idea what the network's capacity is; it discovers it continuously by treating a signal (loss, or in TCP Vegas, *rising round-trip time*) as evidence of congestion and adjusting its window. Two families:

- **AIMD** (Additive Increase, Multiplicative Decrease): add 1 to the limit on success, multiply by 0.9 on a timeout. Simple, robust, slow to find the right value.
- **Latency gradient** (TCP Vegas, and Netflix's `concurrency-limits` library): track the **minimum** round-trip time you have ever observed — that is the uncontended service time, with no queueing in it. Compare the current RTT to it. The ratio `rtt_min / rtt_current` is a **gradient**: 1.0 means no queue anywhere, 0.5 means half your latency is queueing. Then `new_limit = limit × gradient + √limit`, where the `√limit` term is a deliberate allowance for a small standing queue so the limiter keeps probing instead of collapsing to zero.

The Build It implements the gradient version against a dependency whose capacity drops to 40% mid-run. The fixed limiter keeps its 64 in-flight slots full, RTT climbs to 320 ms against a 100 ms deadline, and **goodput falls to 4 req/s while throughput stays at 200 req/s — 98% of the work is wasted.** The adaptive limiter shrinks to ~6.6 in flight within a second, holds RTT at 33 ms, and delivers **181 req/s of goodput, 9% wasted**, shedding the surplus in zero milliseconds. Same capacity. Same load. The difference is whether the limit is a constant or a measurement.

### Retries amplify — the retry storm

A three-attempt retry policy triples your load precisely when your system is least able to take it. This is not a tuning subtlety; it is the single most common cause of a small degradation becoming an outage. Four rules:

**Retry budgets.** Cap retries as a *fraction of traffic*, not as a per-request count. "At most 10% of requests may be retries" is a global invariant that holds no matter how many requests are failing. A per-request cap of 3 is a multiplier that gets applied to 100% of traffic when 100% of traffic fails. In the Build It, the naive policy pushes offered load from 80 req/s to **187 req/s (2.3×)**; the budgeted one holds it at 84 req/s with retries at **4% of traffic**.

**Exponential backoff with jitter.** Backoff alone is not enough, and this is the part people skip. If a thousand clients all fail at the same instant and all wait exactly 1 s, then 2 s, then 4 s, you have not spread the load — you have **synchronised** it into a series of thundering herds, each one landing on a system that is still trying to recover from the last. Randomising the wait (`sleep(random.uniform(0, backoff))` — "full jitter") destroys the correlation. See [Retries, Backoff & DLQs](../../06-messaging-and-pub-sub/08-retries-backoff-and-dead-letter-queues/) for the message-consumer treatment.

**Retry only idempotent operations.** A timeout tells you nothing about whether the work happened — the request may have completed and the *response* may have been lost. Retrying a non-idempotent `POST /charge` on a timeout is how a customer gets billed twice. [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/) covers the idempotency key mechanism that makes retrying safe.

**Never retry at more than one layer.** If your SDK retries 3×, your service mesh retries 3×, and your gateway retries 3×, a single user request can become **27** requests at the bottom of the stack. The multiplication is exponential in the number of layers, and every layer was configured by someone who believed they were the only one. Pick one layer — usually the one closest to the caller, which knows the deadline — and turn retries off everywhere else.

### Circuit breakers and bulkheads

A **circuit breaker** is a state machine that stops you from sending requests to something you already know is broken.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="The circuit breaker state machine. In the closed state every call goes through and failures are counted; crossing the failure threshold moves it to open, where every call fails instantly without touching the dependency. After a cool-down the breaker moves to half-open and lets a small number of probes through; a probe success closes it and a probe failure reopens it. Each transition is annotated with its tuning trap: a threshold that is too sensitive flaps, a cool-down that is too short stampedes, and a breaker without a timeout never trips at all.">
  <defs>
    <marker id="l11-a4" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The circuit breaker: three states, and the trap on every edge</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2.2" stroke-linejoin="round">
      <rect x="40" y="112" width="204" height="90" rx="12" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/><rect x="338" y="112" width="204" height="90" rx="12" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/><rect x="636" y="112" width="204" height="90" rx="12" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="142" y="142" font-size="13.5" font-weight="700" fill="#0fa07f">CLOSED</text><text x="142" y="160" font-size="9.5" opacity="0.9">calls pass through</text><text x="142" y="176" font-size="9.5" opacity="0.9">failures counted</text><text x="142" y="192" font-size="9.5" opacity="0.9">a success resets the count</text><text x="440" y="142" font-size="13.5" font-weight="700" fill="#d64545">OPEN</text>
      <text x="440" y="160" font-size="9.5" opacity="0.9">fail instantly, 0 ms</text><text x="440" y="176" font-size="9.5" opacity="0.9">dependency untouched</text><text x="440" y="192" font-size="9.5" opacity="0.9">workers stay free</text><text x="738" y="142" font-size="13.5" font-weight="700" fill="#e0930f">HALF-OPEN</text><text x="738" y="160" font-size="9.5" opacity="0.9">let N probes through</text>
      <text x="738" y="176" font-size="9.5" opacity="0.9">everything else fails</text><text x="738" y="192" font-size="9.5" opacity="0.9">one probe, not a flood</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.8">
      <path d="M244 138 L 332 138" marker-end="url(#l11-a4)"/><path d="M542 138 L 630 138" marker-end="url(#l11-a4)"/><path d="M632 172 L 550 172" marker-end="url(#l11-a4)"/><path d="M700 106 C 700 62, 200 62, 160 104" marker-end="url(#l11-a4)"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="288" y="128" font-size="9.5" font-weight="700" fill="#d64545">5 fails</text><text x="288" y="152" font-size="8.5" opacity="0.8">or &gt;50% of</text><text x="288" y="164" font-size="8.5" opacity="0.8">a 20-call window</text><text x="586" y="128" font-size="9.5" font-weight="700" fill="#e0930f">after 0.5 s</text><text x="589" y="192" font-size="8.5" opacity="0.8">probe fails</text>
      <text x="589" y="204" font-size="8.5" opacity="0.8">-&gt; open again</text><text x="430" y="54" font-size="9.5" font-weight="700" fill="#0fa07f">probe succeeds -&gt; closed, counter reset</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="40" y="238" width="252" height="112" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/><rect x="314" y="238" width="252" height="112" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/><rect x="588" y="238" width="252" height="112" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
    </g>
    <g fill="currentColor">
      <text x="56" y="260" font-size="10" font-weight="700" fill="#d64545">TRAP: too sensitive</text><text x="56" y="278" font-size="9.5" opacity="0.9">A threshold of 3 on a service</text><text x="56" y="294" font-size="9.5" opacity="0.9">with a 0.5% baseline error rate</text><text x="56" y="310" font-size="9.5" opacity="0.9">will open on noise. Use a RATE</text>
      <text x="56" y="326" font-size="9.5" opacity="0.9">over a window plus a minimum</text><text x="56" y="342" font-size="9.5" opacity="0.9">call count, not a raw count.</text><text x="330" y="260" font-size="10" font-weight="700" fill="#d64545">TRAP: probe stampede</text><text x="330" y="278" font-size="9.5" opacity="0.9">Every instance's cool-down ends</text>
      <text x="330" y="294" font-size="9.5" opacity="0.9">at the same instant, so the whole</text><text x="330" y="310" font-size="9.5" opacity="0.9">fleet probes together and re-kills</text><text x="330" y="326" font-size="9.5" opacity="0.9">the recovering dependency. Jitter</text><text x="330" y="342" font-size="9.5" opacity="0.9">the cool-down; cap probes to 1.</text>
      <text x="604" y="260" font-size="10" font-weight="700" fill="#d64545">TRAP: it is not a timeout</text><text x="604" y="278" font-size="9.5" opacity="0.9">A breaker only helps if the call</text><text x="604" y="294" font-size="9.5" opacity="0.9">it replaces was BOUNDED. Without</text><text x="604" y="310" font-size="9.5" opacity="0.9">a timeout, threads park forever</text>
      <text x="604" y="326" font-size="9.5" opacity="0.9">and the failure counter never</text><text x="604" y="342" font-size="9.5" opacity="0.9">reaches the threshold.</text>
    </g>
    <text x="440" y="386" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Measured: 361 calls short-circuited, 2 probes paid for, and an unrelated endpoint's p99 fell from 905 ms to 54 ms.</text>
  </g>
</svg>
```

The breaker's real job is not to protect the dependency — it is to protect **your workers**. Every call to a dead dependency parks a thread for the full timeout. Enough of them and every thread you own is asleep on a socket, which means endpoints that never touch that dependency stop responding too.

A **bulkhead** attacks the same failure from the other side. The name is from shipbuilding: a hull is divided into watertight compartments so a breach floods one and the ship stays up. In software it means **a separate resource pool per dependency**. Give `/checkout`'s calls their own 4 threads and `/profile`'s their own 4, and no amount of `/checkout` misery can consume `/profile`'s capacity. The breaker is a dynamic fix that needs tuning; the bulkhead is a static fix that needs none. Use both — they fail differently.

The Build It runs all three against 8 real threads and a dependency that is 100% dead. Without protection, `/profile` — which calls nothing — had a **p99 of 905 ms** and served 60 requests. With a breaker, **54 ms** and 150 requests. With a bulkhead, **5 ms** and 150 requests.

### Graceful degradation and priority

Shedding is only palatable because **not all traffic is equal.** Before you need it, sort your traffic into criticality tiers:

- **Tier 1 — revenue and safety.** Checkout, payment, authentication, anything a human is waiting on.
- **Tier 2 — normal reads.** Product pages, search, profile. Degradable: serve a stale cache ([Invalidation & TTLs](../../05-caching/05-invalidation-and-ttls/)), drop the personalised block, return fewer results.
- **Tier 3 — background.** Analytics, prefetch, recommendation refresh, that hourly report. Sheddable to zero with no user impact whatsoever.

Then shed from the bottom. Dropping 100% of Tier 3 and 50% of Tier 2 can restore Tier 1 entirely — the difference between "checkout was slower for ten minutes" and "the site was down." Without tiers, your only shedding tool is a coin flip, which drops checkouts and prefetches at the same rate. Degradation is the other half. A reduced response beats no response: stale data, a cached fallback, a default recommendation list, an empty personalisation block. Decide *now* what the degraded version of each endpoint is, because you will not design it during an incident.

### Metastable failure

Formally (Bronson et al., *Metastable Failures in Distributed Systems*, HotOS 2021): a metastable failure is a state in which a system remains in a degraded, low-goodput mode **after the trigger that caused it has been removed**, because it has entered a *sustaining feedback loop*. The system has two stable states — healthy and collapsed — and a trigger large enough to push it across the boundary does not need to persist for it to stay there.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:840px" role="img" aria-label="Two measured queue-depth time series side by side. On the left, a naive service with three retry attempts: a fifteen second capacity dip starting at twenty seconds sends the queue past eight thousand items and it keeps climbing long after the dip ends, with goodput at zero. On the right, the same run with a retry budget, jittered backoff and deadline shedding stays near zero depth throughout and recovers two seconds after the dip ends. Below, the sustaining feedback loop is drawn as a cycle: the queue grows, waits exceed the timeout, clients retry, arrivals rise, and the queue grows again. The trigger box is detached because the loop no longer needs it.">
  <defs>
    <marker id="l11-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l11-a3r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Metastable failure: remove the trigger, the system stays down</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="44" width="414" height="226" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/><rect x="450" y="44" width="414" height="226" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <rect x="122" y="88" width="62" height="147" fill="#e0930f" fill-opacity="0.18" stroke="none"/><rect x="556" y="88" width="62" height="147" fill="#e0930f" fill-opacity="0.18" stroke="none"/>

    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M40 235 L 412 235"/><path d="M474 235 L 846 235"/>
    </g>
    <path d="M40 235 L 114 235 L 151 233 L 188 214 L 225 188 L 262 163 L 299 135 L 336 111 L 373 87 L 410 65" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/><path d="M474 235 L 548 235 L 585 233 L 622 232 L 659 235 L 696 234 L 733 235 L 770 235 L 807 235 L 844 235" fill="none" stroke="#0fa07f" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M184 235 L 184 218" fill="none" stroke="#e0930f" stroke-width="1.6"/><path d="M184 118 L 184 88" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="5 4"/><path d="M618 235 L 618 218" fill="none" stroke="#e0930f" stroke-width="1.6"/><path d="M618 118 L 618 88" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="5 4"/>

    <g fill="currentColor">
      <text x="223" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">NAIVE: 3 attempts, no budget</text><text x="657" y="66" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">GUARDED: budget + jitter + shed</text><text x="153" y="82" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">dip</text>
      <text x="587" y="82" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">dip</text><text x="196" y="104" font-size="9" fill="#e0930f" font-weight="700">trigger gone</text><text x="630" y="104" font-size="9" fill="#e0930f" font-weight="700">trigger gone</text><text x="34" y="239" font-size="9" text-anchor="end" opacity="0.7">0</text><text x="34" y="70" font-size="9" text-anchor="end" opacity="0.7">8k</text>
      <text x="40" y="253" font-size="9" opacity="0.7">0 s</text><text x="410" y="253" font-size="9" text-anchor="end" opacity="0.7">90 s</text><text x="474" y="253" font-size="9" opacity="0.7">0 s</text><text x="844" y="253" font-size="9" text-anchor="end" opacity="0.7">90 s</text><text x="60" y="140" font-size="10" font-weight="700" fill="#d64545">queue depth</text>
      <text x="60" y="156" font-size="9.5" opacity="0.9">8,399 items, oldest 35 s</text><text x="60" y="172" font-size="9.5" opacity="0.9">offered 187/s (2.3x demand)</text><text x="60" y="188" font-size="9.5" opacity="0.9">goodput 0/s</text><text x="60" y="206" font-size="10" font-weight="700" fill="#d64545">recovery: NEVER</text><text x="494" y="140" font-size="10" font-weight="700" fill="#0fa07f">queue depth</text>
      <text x="494" y="156" font-size="9.5" opacity="0.9">peak 76, oldest 1.0 s</text><text x="494" y="172" font-size="9.5" opacity="0.9">offered 84/s (retries 4%)</text><text x="494" y="188" font-size="9.5" opacity="0.9">goodput 82/s, 425 shed</text><text x="494" y="206" font-size="10" font-weight="700" fill="#0fa07f">recovery: 2.0 s</text>
    </g>

    <text x="440" y="300" font-size="12.5" font-weight="700" text-anchor="middle" fill="currentColor">the loop that keeps it there — the trigger is only needed once</text>
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="24" y="326" width="146" height="52" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/><rect x="222" y="326" width="146" height="52" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="404" y="326" width="164" height="52" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
      <rect x="604" y="326" width="176" height="52" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.8">
      <path d="M368 352 L 398 352" marker-end="url(#l11-a3r)"/><path d="M568 352 L 598 352" marker-end="url(#l11-a3r)"/><path d="M780 352 C 820 352, 828 400, 780 408 L 300 408 C 268 408, 262 388, 264 380" marker-end="url(#l11-a3r)"/>
    </g>
    <path d="M170 352 L 216 352" fill="none" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="5 4" marker-end="url(#l11-a3)"/>
    <g fill="currentColor">
      <text x="97" y="348" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">TRIGGER</text><text x="97" y="364" font-size="9" text-anchor="middle" opacity="0.9">capacity -30% for 15 s</text><text x="295" y="348" font-size="10.5" font-weight="700" text-anchor="middle">queue grows</text><text x="295" y="364" font-size="9" text-anchor="middle" opacity="0.85">rho crosses 1.0</text>
      <text x="486" y="348" font-size="10.5" font-weight="700" text-anchor="middle">wait &gt; 1.0 s timeout</text><text x="486" y="364" font-size="9" text-anchor="middle" opacity="0.85">the caller walks away</text><text x="692" y="348" font-size="10.5" font-weight="700" text-anchor="middle">every caller retries</text><text x="692" y="364" font-size="9" text-anchor="middle" opacity="0.85">arrivals x2.3, capacity x1</text>
      <text x="97" y="396" font-size="9" text-anchor="middle" fill="#e0930f" font-weight="700">removed at t=35 s</text><text x="540" y="428" font-size="9.5" text-anchor="middle" fill="#d64545" font-weight="700">retries are new arrivals — the loop feeds itself</text>
    </g>
    <text x="440" y="466" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Removing the trigger does not exit the loop. Only dropping load does — or a restart, which is dropping all of it.</text>
  </g>
</svg>
```

Two loops account for most real incidents. **Retries** are the one measured above. **Cache-miss amplification** is the other: a cache flush or an eviction storm sends every request to the database, the database slows down, requests time out before they can *populate* the cache, so the miss rate stays at 100% and the database never gets the break it needs to catch up. Restart the cache tier and it happens again. ([Cache Stampede](../../05-caching/06-cache-stampede/) is the same feedback loop at a single key.) The engineering conclusion has two parts, and the second is the one that gets skipped.

1. **You must be able to shed load.** Not "you should have a plan" — there must be a switch, and it must work when your service is at 100% CPU with a 9,000-deep queue.
2. **You must have tested that switch under load**, because a shed path that has never been exercised is a shed path that allocates, logs at INFO, calls the database to check a feature flag, or waits on the same exhausted connection pool it is meant to protect. It will fail in exactly the moment it exists for, and nobody in the incident channel will know why.

## Build It

[`code/backpressure.py`](code/backpressure.py) is six numbered arguments. Standard library only, seeded, ~7 seconds. The interesting parts:

**The queue itself.** One discrete-event simulator handles all of sections 2 and 3; the flags are the lesson. Note where the deadline is checked — at *dequeue*, not at start — and note the reaper loop that drops the expired prefix without paying for it:

```python
else:                                            # departure
    busy -= 1
    completed += 1
    lat.append(now - req.arrival)
    if now > req.deadline:
        late += 1                                # wasted work: nobody is reading
    else:
        ok_lat.append(now - req.arrival)
    if shed_expired:
        # Reap abandoned work off the HEAD. The oldest item's age is the
        # health signal; anything past its deadline is free to delete.
        while q and now > q[0].deadline:
            q.popleft()
            shed += 1
    while q:                                     # pull the next unit of work
        nxt = q.popleft() if discipline == "fifo" else q.pop()
        if shed_expired and now > nxt.deadline:
            shed += 1
            continue
        start(nxt, now)
        break
```

The entire FIFO-vs-LIFO result is `q.popleft()` versus `q.pop()`. That is the whole change. Everything else — arrival process, service times, worker count, deadline, seed — is identical across the three runs. **The gradient limiter.** This is TCP Vegas' congestion signal, applied to a thread pool instead of a network path. `S_MIN` is the best RTT ever observed; the ratio to the current RTT says how much of the current latency is queueing:

```python
if adaptive and observed >= limit / 2:
    # Vegas gradient: how far is the current RTT above the best we've seen?
    gradient = max(0.5, min(1.0, S_MIN / rtt))
    probe = limit * gradient + math.sqrt(limit)
    limit = max(1.0, min(200.0, limit * (1 - ALPHA) + probe * ALPHA))
```

Three details matter. The `observed >= limit / 2` guard stops the limiter from reacting to latency when it is not actually saturated (otherwise it would grow without bound during quiet periods). The `max(0.5, ...)` floor caps how fast the limit can shrink, so one slow request cannot collapse it. And `+ math.sqrt(limit)` is the standing-queue allowance that keeps the limiter probing upward — without it the fixed point is zero and the limiter strangles the service it is protecting.

**The retry storm.** The mechanic that makes it metastable is one line of honesty: when a client times out, the server *does not find out*. The request stays in the queue and will still be executed, at full cost, for nobody:

```python
# 3. clients time out and retry. The server never learns; the original
#    request stays in the queue and will still be executed.
while scan - origin < len(q):
    item = q[scan - origin]
    if t - item[0] <= timeout:
        break
    scan += 1
    if item[2]:
        continue
    item[2] = True
    schedule_retry(item[1], t)
```

And the budget, which is the entire difference between the two runs — a cap on retries as a *fraction of real traffic*, evaluated globally rather than per request:

```python
def schedule_retry(attempt: int, now: float) -> None:
    """A client that got a timeout or a 503 tries again — if the budget allows."""
    nonlocal retries
    if attempt >= cfg.attempts:
        return
    if cfg.budget is not None and retries >= cfg.budget * base:
        return                                      # retry budget exhausted
    retries += 1
    back = cfg.backoff * (2 ** (attempt - 1))
    heapq.heappush(due, (now + (rng.uniform(0.0, back) if cfg.jitter else back),
                         attempt + 1))
```

**The breaker** is 30 lines of state machine over real threads. `allow()` is called before every dependency call and is the thing that costs zero milliseconds when open:

```python
def allow(self) -> bool:
    with self.lock:
        if self.state == "closed":
            return True
        if time.perf_counter() - self.opened_at >= self.open_secs:
            self.state = "half-open"      # let exactly one probe through
            self.opened_at = time.perf_counter()
            self.probes += 1
            return True
        self.short_circuited += 1
        return False
```

Run it:

```bash
docker compose exec -T app python \
  phases/08-concurrency-and-performance/11-backpressure-and-load-shedding/code/backpressure.py
```

```console
== 1 · THE UTILIZATION KNEE IS NOT VISIBLE ON A UTILIZATION GRAPH ==
  one worker, service time S = 40 ms, Poisson arrivals
      rho   S/(1-rho)   measured     mean W      p99 W    p99/S
     0.50        2.0x       2.0x      81 ms     373 ms       9x
     0.70        3.3x       3.3x     131 ms     599 ms      15x
     0.80        5.0x       5.0x     200 ms     878 ms      22x
     0.90       10.0x       9.7x     387 ms    1641 ms      41x
     0.95       20.0x      22.7x     908 ms    4076 ms     102x
     0.99      100.0x      68.5x    2741 ms   11792 ms     295x
  utilization went from 0.50 to 0.99 — a 2x change in a number you graph.
  mean latency went up 34x and p99 went up 32x. Nothing 'broke'.
  (past rho=0.95 the simulation UNDER-reads the formula: a queue takes
   longer to reach steady state than it takes to hurt you.)

  same queue, variable service times (95% fast / 5% slow, CV^2 = 3.96):
      rho   CV^2=1 W/S   CV^2=4 W/S   P-K theory   penalty
     0.50         2.0x         3.4x         3.5x      1.7x
     0.70         3.3x         7.0x         6.8x      2.1x
     0.80         4.8x        11.2x        10.9x      2.3x
     0.90         9.8x        21.1x        23.3x      2.2x
  W/S crosses 10x at rho = 0.90 with steady service times,
  but at rho = 0.78 once service times vary — the knee moved LEFT.

== 2 · AN UNBOUNDED QUEUE DOES NOT ABSORB OVERLOAD — IT HIDES IT ==
  4 workers x 50 ms service = 80 req/s capacity;  arrivals = 160 req/s (2.0x)
  client deadline = 1.0 s; run = 120 simulated seconds
  config                     p50       p99   peak Q      mem    done    503s   wasted
  unbounded queue        31540ms   61284ms     9957   81.6MB    9462       0     98%
  bounded queue (40)       539ms     794ms       40    0.3MB    9462    9917      0%
  19423 requests arrived in both runs. Both completed 9462 — identical throughput.
  the unbounded queue completed 9462 requests and 98% of them
  were already past the caller's deadline: 9307 responses nobody read.
  goodput — answers that arrived in time — was 1.3/s unbounded vs 78.8/s bounded (61x).

== 3 · TIMEOUTS ARE LOAD SHEDDING, AND UNDER OVERLOAD LIFO BEATS FIFO ==
  identical 2.0x overload; the only difference is what happens at dequeue
  discipline                  goodput   success   wasted   p99(ok)   peak Q  dropped
  FIFO, no deadline check       1.2/s        1%      99%     986ms     9603        0
  FIFO + drop expired          16.5/s       10%      79%    1000ms      213     9450
  LIFO + drop expired          80.1/s       50%       0%     258ms      149     9533
  dropping expired work at dequeue capped the queue at 213 items instead of 9603
  (1.7 MB instead of 78.7 MB) — but FIFO goodput stayed at 16.5/s,
  because the oldest LIVE request has already spent its whole budget waiting.
  LIFO serves the newest instead: goodput 80.1/s, 50% of callers answered in time,
  p99 of those answers 258 ms. Same capacity, same arrivals, one line of code.

== 4 · ADAPTIVE CONCURRENCY LIMITS: LATENCY AS A CONGESTION SIGNAL ==
  dependency: 20 ms uncontended, 500 req/s healthy; it drops to 200 req/s
  at t=4s and recovers at t=8s. Offered load 400 req/s constant, deadline 100 ms,
  both limiters start at 64 in flight.
      t    cap|   lim  flight      rtt     good|    lim  flight      rtt     good
              |     ---- fixed limit ----      |    -- adaptive (gradient) --
    0.0    500|    64     8.0     20ms    400/s|   64.0     8.0     20ms    400/s
     ...
    4.0    200|    64     8.0     40ms    200/s|   64.0     8.0     40ms    200/s
    5.0    200|    64    64.0    320ms      0/s|    7.0     7.1     35ms    200/s
    7.0    200|    64    64.0    320ms      0/s|    6.6     6.6     33ms    200/s
    8.0    500|    64    64.0    128ms      0/s|    7.1     6.6     20ms    328/s
   11.0    500|    64     8.0     20ms    400/s|   16.3     8.0     20ms    400/s
  during the 4 s outage window:
    fixed limit   throughput    200/s   goodput      4/s   -> 98% wasted
    adaptive      throughput    200/s   goodput    181/s   -> 9% wasted
  whole run goodput: fixed 267/s, adaptive 327/s (1.22x)
  the fixed limiter kept ACCEPTING work it could not finish in time;
  the adaptive one shrank to fit the dependency and shed the rest in ~0 ms.

== 5 · THE RETRY STORM AND METASTABLE FAILURE ==
  80 req/s against 100 req/s of capacity (rho = 0.80). At t=20s capacity
  drops 30% to 70 req/s for 15 s, then returns. Client timeout 1.0 s.
       t|   depth   oldest   good/s|   depth   oldest   good/s
        |  ------- naive -------   |  ---- with shedding ---
     0.0|       0     0.0s        0|       0     0.0s        0
    18.0|       6     0.0s       85|       6     0.0s       85
    27.0|      78     0.8s       70|      76     1.0s       70 <-- dip
    36.0|    1039     4.2s        0|      10     0.8s       80
    54.0|    3570    14.6s        0|       2     0.0s       85
     ...
    81.0|    7325    30.6s        0|       0     0.0s       78
  naive  : real demand never changed (80 req/s) but offered load averaged 187 req/s
           = 2.3x amplification from 9582 retries on 7225 real requests
           (the ceiling is 3.0x: three attempts each)
           55 s after the trigger cleared: queue 8399 deep, oldest 35 s, goodput 0/s
           recovery: NEVER  <-- the trigger is gone and the system is still down
  guarded: offered 84 req/s — 295 retries on 7227 requests = 4%, the budget ceiling
           shed 425 expired at dequeue + 0 at the door; goodput 82/s at the end
           recovery: 2.0 s after the trigger cleared

== 6 · CIRCUIT BREAKERS AND BULKHEADS: ONE DEAD DEPENDENCY, TWO ENDPOINTS ==
  8 real threads. /checkout calls a dependency that always fails after 80 ms.
  /profile takes 4 ms and calls nothing.  Offered: 250/s + 100/s for 1.5 s.
  config                    /profile p50  /profile p99   served  dropped  /checkout thread-time
  shared pool, no breaker          460ms         905ms       60       41                   95%
  shared pool + breaker              4ms          54ms      150        0                    9%
  bulkhead (4+4 pools)               4ms           5ms      150        0                   50%
  /profile never calls the broken dependency, yet without a breaker its p99
  was 905 ms — 17x the breaker run's 54 ms — because /checkout owned 95% of every thread.
  the breaker short-circuited 361 calls and paid for 2 half-open probes;
  the bulkhead fixed it differently: /checkout simply cannot borrow /profile's threads.

  (total wall time 6.7 s)
```

Read the numbers — five of these sections are arguments, not demos. **Section 1** grounds everything else. The measured column tracks `1/(1−ρ)` to within 3% up to ρ = 0.90, so the formula is not a metaphor. Two things to take from it. First, the p99 column: at ρ = 0.90 the *mean* is 387 ms — mildly annoying — but p99 is 1,641 ms, **41× the 40 ms service time**. The mean stays polite long after the tail has stopped being polite, which is why an SLO written on a mean will pass all the way into an outage. Second, the variability table: with the same mean service time but a 95/5 fast/slow split, ρ = 0.80 costs **11.2× service time instead of 4.8×**, and the practical knee (W/S = 10) moves from **ρ = 0.90 to ρ = 0.78**. If your endpoint has a cache, a slow path, or a variable result-set size — and it does — your safe operating point is well below the one the textbook formula gives you.

**Section 2 is the law of the lesson, measured.** Both configurations completed **exactly 9,462 requests** out of 19,423 arrivals. Identical throughput; the capacity is the capacity and no queueing policy changes it. Now look at everything else: the unbounded queue delivered a p50 of **31.5 seconds** and a p99 of **61 seconds**, peaked at **9,957 queued requests (~82 MB)**, and **98% of its completed work was already dead on arrival — 9,307 responses written for nobody.** Goodput was **1.3 req/s**. The bounded queue rejected 9,917 requests instantly with a 503 and delivered **78.8 req/s of goodput, a 61× difference**, with a p99 of 794 ms and 0.3 MB of queue. The bound did not create capacity. It stopped you from spending the capacity you had on work that no longer mattered.

**Section 3 is where the reader's intuition gets corrected.** Adding a dequeue-time deadline check to FIFO does something real: the queue stops growing (**213 items instead of 9,603, 1.7 MB instead of 78.7 MB**) and you stop running out of memory. But goodput only moves from 1.2/s to **16.5/s, with 79% of completions still wasted** — because the oldest live item is by definition the one that has already spent its entire budget waiting, so serving it produces a late answer. Switch one method call to LIFO and goodput jumps to **80.1/s — the pool's full capacity — with 0% waste and a p99 of 258 ms on successful responses.** Fifty percent of callers get a correct, timely answer instead of one percent. Nothing about the system changed except which end of the deque you pop from.

**Section 4** is the same argument moved to a dependency you do not control. Both limiters see identical conditions. When capacity drops to 40%, the fixed limit of 64 stays full: in-flight sits at 64, RTT sits at **320 ms against a 100 ms deadline**, throughput is a healthy-looking **200 req/s and goodput is 4 req/s — 98% waste.** The gradient limiter reads its own latency as a congestion signal, shrinks from 64 to **6.6 in flight in about one second**, and holds RTT at **33 ms**, delivering **181 req/s of goodput with 9% waste** — and shedding the other 200 req/s in zero milliseconds so those callers can fail fast and go elsewhere. It also *recovers*: within a second of capacity returning it is back to 400 req/s, and the guard clause parks the limit at 16 rather than growing forever.

**Section 5 is the one to remember during an incident.** Both runs get the identical trigger: a 15-second, 30% capacity dip on a service running at a comfortable ρ = 0.80. The naive run enters the loop about seven seconds in, and then the trigger becomes irrelevant. **55 seconds after capacity returned to normal**, the naive service has a queue **8,399 items deep**, an oldest item **35 seconds old**, an offered load of **187 req/s against real demand of 80** (2.3× amplification, heading for the 3.0× ceiling), and a goodput of **exactly zero**. It is not recovering; the graph is a straight line up. The guarded run — retry budget, full jitter, LIFO, dequeue-time shedding — rides the same dip at reduced goodput and is **back to baseline 2.0 seconds** after it ends. The difference is not capacity, hardware or code quality. It is whether the system was permitted to say no.

**Section 6** makes the blast-radius argument with real threads and real socket-shaped waits. `/profile` takes 4 ms and calls nothing at all. With a shared pool and no breaker its **p99 is 905 ms** and it serves 60 of 150 requests, because `/checkout` — calling a dependency that always fails after an 80 ms timeout — occupies **95% of all thread-time**. A breaker cuts that to **9% of thread-time and a 54 ms p99 (17× better)** after short-circuiting 361 calls and paying for 2 half-open probes. A bulkhead reaches **5 ms** by a different route: `/checkout` is confined to its own 4 threads and structurally cannot take `/profile`'s. The 54 ms residue in the breaker run is the cost of the probes and the pre-trip failures — a breaker is a *reaction*, so it always lets some damage through. The bulkhead is a *guarantee*, so it does not. Ship both.

## Use It

Nothing above needs a framework, but every layer of your stack has a knob for it. **Bound the front door.** The kernel accept queue is `listen(fd, backlog)`, capped by `net.core.somaxconn` (4096 on modern Linux, 128 on older kernels — check, do not assume). Above it, your ASGI server:

```bash
uvicorn app:api --backlog 512 --limit-concurrency 200 --timeout-keep-alive 5
gunicorn app:api -k uvicorn.workers.UvicornWorker --workers 4 --backlog 512 \
                 --timeout 30 --graceful-timeout 10
```

`--limit-concurrency` is admission control: uvicorn returns `503` immediately once that many requests are in flight. Without it, the only bound is memory. **Shed at the edge** with nginx, before a request costs you a worker at all:

```text
limit_req_zone $binary_remote_addr zone=perip:10m rate=20r/s;
limit_conn_zone $server_name zone=perserver:10m;

location /api/ {
    limit_req  zone=perip burst=40 nodelay;   # burst, then 503 immediately
    limit_conn perserver 500;
    limit_req_status  429;
    proxy_read_timeout 2s;                    # a bounded wait, always
}
```

[Rate Limiting & Quotas](../../02-api-design/09-rate-limiting-quotas/) builds the token bucket behind `limit_req` and covers the `429` / `Retry-After` contract. Rate limiting and load shedding are not the same thing — a rate limit enforces a *quota you sold*; shedding protects capacity you *have* — but they share a mechanism and a status code. **Admission control in the app** is a semaphore. This is your `run_queue` bound and your fixed limiter, in eight lines:

```python
import anyio, time
from fastapi import FastAPI, Request, Response

api = FastAPI()
GATE = anyio.Semaphore(200)          # the in-flight limit — Little's Law, then measure
DEADLINE_HEADER = "x-request-deadline"

@api.middleware("http")
async def admission_control(request: Request, call_next):
    # Deadline propagation (Lesson 6): the caller's budget, or our own default.
    header = request.headers.get(DEADLINE_HEADER)
    deadline = float(header) if header else time.time() + 2.0
    request.state.deadline = deadline

    if GATE.statistics().tokens_available == 0:          # full: fail fast, no queue
        return Response(status_code=503, headers={"Retry-After": "1"})
    async with GATE:
        # Check AGAIN after acquiring: we may have queued for the whole budget.
        if time.time() >= deadline:
            SHED_EXPIRED.inc()                           # a counter, not a log line
            return Response(status_code=503, headers={"Retry-After": "1"})
        with anyio.fail_after(deadline - time.time()):   # never outlive the caller
            return await call_next(request)
```

Every line maps to something you built. `GATE` is `run_queue`'s `maxq`. The `tokens_available == 0` check is the 503-at-the-door path from section 2. The **second** deadline check after acquiring is section 3's dequeue-time check — the one that took FIFO goodput from 1.2/s to 16.5/s — and it is the line people leave out. `fail_after` stops a slow handler from outliving the caller who is waiting for it.

**Adaptive limits and breakers** exist as libraries. Netflix's `concurrency-limits` (JVM) implements exactly the Vegas gradient from section 4; `resilience4j` (JVM) and `Polly` (.NET) provide breakers, bulkheads, retries and rate limiters as composable policies; Hystrix is its influential, now-archived ancestor — its thread-pool-per-dependency model is the bulkhead in section 6, and its retirement notice is itself an argument for adaptive limits over hand-tuned pool sizes. In a service mesh, Envoy gives you both without code:

```yaml
circuit_breakers:
  thresholds:
    - priority: DEFAULT
      max_connections: 200
      max_pending_requests: 50      # THE bound — the default is 1024
      max_requests: 200
      max_retries: 3                # a retry budget, fleet-wide
outlier_detection:                  # eject hosts that are actually broken
  consecutive_5xx: 5
  base_ejection_time: 30s
  max_ejection_percent: 50          # never eject everything and cause the outage
```

`max_pending_requests` is the one to change today. Its default of 1024 is an unbounded queue with extra steps.

Production rules that survive contact with an incident:

- **Bound every queue in the diagram, not the one you remember.** Bounding the worker pool while the connection-pool wait queue is unbounded just relocates the backlog into a place with no metrics on it. Write down the bound for all seven; for the ones you cannot bound, write down why.
- **Give every request a deadline and check it at dequeue, not just at start.** Propagate it as a header so downstream services inherit the *remaining* budget, and never let a downstream timeout exceed the time your caller is still waiting.
- **Measure queue *time*, not queue depth.** Alert on the age of the oldest queued item. Graph **goodput** (responses delivered before their deadline) next to throughput; when the two diverge, everything between them is work you are paying for and nobody is receiving.
- **Shed before you saturate, and shed by criticality tier.** By the time ρ = 0.99 the latency damage is done. Tag traffic Tier 1/2/3 at ingress and drop from the bottom; a shed that cannot distinguish a prefetch from a checkout is a coin flip.
- **Retry budgets and jitter, always. Retries at exactly one layer.** Cap retries at ~10% of traffic globally, jitter every backoff, retry only idempotent operations, and disable retries in the other three layers that also have them.
- **One pool per dependency.** A shared pool means one slow downstream can consume every worker you own, including the workers serving endpoints that never call it — measured at 95% of thread-time in section 6.
- **Load-test the shedding path.** Not the happy path *with* shedding enabled — the path where the semaphore is full and the deadline has passed. Confirm it does not allocate, does not log per request, does not query a feature-flag service, and does not need a connection from the pool it is protecting. An untested shed path fails in exactly the moment it exists for.

## Think about it

1. Your service runs at ρ = 0.55 and everyone agrees there is plenty of headroom. A deploy makes 5% of requests take 20× longer than the rest, with no change to the mean. Using the Pollaczek–Khinchine relation, what happens to p99, and what has effectively happened to your headroom? What single metric would have told you before the deploy?
2. LIFO gave 50% of callers a good answer where FIFO gave 1%. Design the queue you would actually ship: which requests, if any, must never be reordered, and how would you keep LIFO's overload behaviour without breaking them? What does your answer imply about where the queue must live?
3. Your service returns `503` with `Retry-After: 1` when shedding. Ten thousand clients receive it at the same instant. Trace what happens one second later, and again ten seconds later. What must be true of the *client* for shedding to help at all — and what does that say about shedding as a defence against traffic you do not control?
4. You have a retry budget of 10% and three layers that each want retries. Where do you put the budget so it is enforced globally rather than 10% per layer, and what breaks if two services in the same request path each enforce their own?
5. Section 5's naive run never recovers. Assume you are on call, the trigger is already gone, and you cannot restart (the process holds warm state that takes 20 minutes to rebuild). List the actions that could break the loop, in the order you would try them, and say for each which side of `ρ = λ/µ` it moves and by how much.

## Key takeaways

- **Every server is a queue, and `W = S/(1−ρ)` is not a metaphor.** Measured over 900k simulated requests, latency tracked the formula to within 3% up to ρ = 0.90: 2.0× service time at ρ = 0.50, 5.0× at 0.80, **9.7× at 0.90**. The knee is invisible on a utilization graph, and **variability moves it left** — a 95%-fast/5%-slow service distribution (CV² ≈ 4) put the 10× point at **ρ = 0.78 instead of 0.90**.
- **An unbounded queue does not absorb overload; it hides it.** Under identical 2× overload the bounded and unbounded runs completed **exactly the same 9,462 requests**. The unbounded one had a p99 of **61 s**, peaked at **9,957 queued (~82 MB)**, and **98% of everything it completed was already past its deadline** — goodput 1.3/s against the bounded run's 78.8/s, a **61× difference** created by one integer.
- **Timeouts are load shedding, and the check belongs at dequeue.** Dropping expired work at dequeue capped the queue at 213 items instead of 9,603, but FIFO goodput only reached **16.5/s** because the oldest live request has already spent its budget. **LIFO reached 80.1/s — full capacity, 0% wasted, p99 258 ms** — from `q.pop()` instead of `q.popleft()`. Alert on the **age of the oldest queued item**, never on depth: a count is meaningless without a rate.
- **A fixed concurrency limit is right for exactly one dependency latency.** When capacity dropped 60%, a fixed limit of 64 kept accepting work and delivered **4 req/s of goodput with 98% waste at a 320 ms RTT**; a Vegas-style latency-gradient limiter shrank to 6.6 in flight, held RTT at **33 ms**, delivered **181 req/s of goodput**, shed the rest in ~0 ms, and recovered within a second.
- **Retries turn a dip into a metastable failure.** A 15-second, 30% capacity dip on a service at ρ = 0.80 pushed offered load from 80 to **187 req/s (2.3×)**; **55 seconds after the trigger was gone** the queue was **8,399 deep, the oldest item 35 s old, and goodput exactly zero — it never recovers.** With a 10% retry budget, full jitter and deadline shedding, the same dip cost nothing and the system was back to baseline in **2.0 seconds**.
- **Breakers protect your workers; bulkheads make it structural.** One dead dependency consumed **95% of all thread-time** and pushed an endpoint that never calls it to a **905 ms p99**. A breaker cut that to 9% and **54 ms**; a bulkhead (4+4 pools) reached **5 ms** and cannot fail the way the breaker can. Ship both — and **load-test the shed path**, because a shed path that has never run under load fails in the one minute it exists for.

Next: [Connection & Resource Pooling](../12-connection-and-resource-pooling/) — the connection-pool wait queue from this lesson's inventory, built properly: sizing, acquisition timeouts, health checks, and why a pool that is too *large* is as dangerous as one that is too small.
