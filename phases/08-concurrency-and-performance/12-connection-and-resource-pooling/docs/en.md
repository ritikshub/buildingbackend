# Connection & Resource Pooling

> Opening a database connection costs a TCP handshake, a TLS handshake, an authentication round trip and a whole server-side process — about 6 ms and several megabytes, to run a query that takes 1 ms. So everyone pools. Then the second, more expensive lesson arrives: a pool is not a cache, it is **the concurrency limit your database sees**, and it multiplies by every worker process and every replica you run. This lesson measures both — reuse was 6.2x faster, and widening the pool 5x past its measured knee bought **22% less throughput and 5.8x the database-side p99**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Locks & Coordination Primitives](../09-locks-and-coordination-primitives/), [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/)
**Time:** ~75 minutes

## The Problem

Your handler opens a connection, runs one query, and closes it. Here is the bill, in order.

A **TCP** (Transmission Control Protocol) connection starts with a three-way handshake — one full round trip before a single byte of your data moves. Then **TLS** (Transport Layer Security, the encryption layer from [TLS, Certificates & mTLS](../../01-networking-and-protocols/10-tls-certificates-mtls/)) adds one to two more round trips depending on version. Then the database authenticates you: another round trip, plus password hashing on both sides. Then — and this is the part people forget, because it happens on the other machine — PostgreSQL **forks a whole new backend process** for your session, with its own memory: several megabytes of private memory before you have run anything. MySQL spawns a thread, which is cheaper but not free.

On a same-datacenter link with 0.5 ms round trips that is roughly **6 ms of handshake for a query that takes 1 ms**. You are paying 86% overhead. At 1,000 requests per second you are also asking the database to fork and reap 1,000 processes per second, each allocating and freeing megabytes, which is a workload in its own right and one the database was never designed for.

So everybody pools. You open some connections once, keep them, and hand them out. In the Build It that single change takes 100 operations from 842.7 ms to 137.0 ms — a **6.15x speedup**, with 83.7% of the original wall clock revealed as pure handshake. That part is easy, and it is where most tutorials stop.

Here is where it gets expensive. A team sets `pool_size = 20`. Reasonable. They deploy behind gunicorn with **4 worker processes** per container, because a Python process has one **GIL** (Global Interpreter Lock — the mutex that lets only one thread execute Python bytecode at a time, from [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/)) and four processes use four cores. Kubernetes runs **8 replicas** at steady state and autoscales to **20** under load. The database is configured with the PostgreSQL default `max_connections = 200`.

```text
   20 (pool)  ×  4 (workers)  ×  20 (peak replicas)  =  1,600 connections
   database budget: 200 max_connections − 8 reserved  =    192
```

Nobody typed 1,600 anywhere. Nobody typed 640 either, which is what the steady-state 8 replicas already ask for. The first autoscale event at 3am takes the database down for **every** service that shares it, with `FATAL: sorry, too many clients already`, and every one of your replicas is perfectly healthy. A pool is not a local performance tweak. It is a per-process multiplier on a global, shared, hard limit.

And there is a third surprise waiting even for teams who get the arithmetic right: **making the pool bigger usually makes things worse.** Not "diminishing returns" — actually worse. The Build It sweeps pool sizes from 1 to 64 against a downstream with a real capacity limit and finds a knee at 12, where throughput is 1,785 ops/s and the database-side p99 is 8.4 ms. At 64 the same system does **1,394 ops/s (−22%) with a database-side p99 of 48.8 ms (5.8x)**. Five times the resource, less throughput, six times the latency.

## The Concept

### What a connection actually costs

Break the cost into the two halves that behave differently.

**On the wire**, a connect is a fixed number of round trips. TCP's three-way handshake is one RTT (Round-Trip Time). TLS 1.2 adds two, TLS 1.3 adds one (and zero on resumption). Authentication — SCRAM-SHA-256 in modern PostgreSQL — is another round trip or two. At an intra-datacenter RTT of 0.5 ms that is 2–3 ms; across an availability zone at 2 ms RTT it is 8–12 ms; across a region it is a disaster. This cost is **latency, not CPU**, which is exactly why it is invisible on your laptop against a local database and brutal in production.

**On the server**, a connect allocates. PostgreSQL forks a backend process per connection with its own `work_mem` allowance, catalog caches, and stack — commonly 5–10 MB of resident memory each, more once it has run some queries. That memory is why `max_connections` exists at all, and why raising it is not free: 1,000 backends at 8 MB is 8 GB of RAM that is not your buffer cache. MySQL uses a thread per connection instead, which is cheaper per unit but still real.

The Build It models this with a 6 ms setup and a 1 ms query, and the ratio it prints — **8.43 ms per operation unpooled versus 1.37 ms pooled** — is the whole justification. Reuse is not an optimization you get to weigh against complexity. It is table stakes.

### A pool is a semaphore over a bag of reusable objects

That sentence is the entire mental model, and everything else in this lesson is a consequence of it.

A **semaphore** (from [Locks & Coordination Primitives](../09-locks-and-coordination-primitives/)) is a counter with two operations: acquire, which blocks while the counter is zero and otherwise decrements it, and release, which increments it and wakes a waiter. A pool is a semaphore holding `max_size` permits, plus a bag of already-constructed objects. `acquire()` takes a permit **and** hands you an object; `release()` gives back both.

Read the consequences off that definition:

- **Sizing** is picking the semaphore's count. It bounds concurrency at the downstream resource, not at your process.
- **The checkout timeout** is the semaphore's acquire timeout. Without it, acquire blocks forever.
- **The wait queue** is the semaphore's parked-waiter list, and it needs its own bound and ordering policy.
- **A leak** is a permit acquired and never released. The semaphore is monotonic downward, so it never recovers.
- **Validation, reset and recycling** are rules about the *object* in the bag, not the permit — which is why they are all optional and all have a cost.

Keep the definition in your head and every configuration knob in every pool library becomes predictable.

### The anatomy: a free list, a wait queue, and five hooks

```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The anatomy of a connection pool: requesters enter a FIFO wait queue bounded by a checkout timeout, take one of max_size permits, are handed the most recently returned resource from a LIFO free list, use it, and on release the resource is reset and pushed back while the head of the wait queue is woken. Below, a table of the five lifecycle hooks and the specific bug each one prevents.">
  <defs><marker id="l12-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs> <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700">A pool is a semaphore over a bag of reusable objects</text> <g fill="none" stroke-width="2" stroke-linejoin="round">
  <rect x="21" y="52" width="150" height="80" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/> <rect x="193" y="52" width="150" height="80" rx="10" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/> <rect x="365" y="52" width="150" height="80" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="537" y="52" width="150" height="80" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  <rect x="709" y="52" width="150" height="80" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/> </g> <g fill="none" stroke="currentColor" stroke-width="1.6"> <path d="M171 92 L 189 92" marker-end="url(#l12-ar)"/> <path d="M343 92 L 361 92" marker-end="url(#l12-ar)"/> <path d="M515 92 L 533 92" marker-end="url(#l12-ar)"/> <path d="M687 92 L 705 92" marker-end="url(#l12-ar)"/> </g> <g text-anchor="middle">
  <text x="96" y="80" font-size="11.5" font-weight="700" fill="#3553ff">REQUESTERS</text> <text x="96" y="98" font-size="9">threads or tasks</text> <text x="96" y="114" font-size="9" opacity="0.8">offered load</text> <text x="268" y="80" font-size="11.5" font-weight="700" fill="#e0930f">WAIT QUEUE</text> <text x="268" y="98" font-size="9">FIFO: bounded tail</text>
  <text x="268" y="114" font-size="9" opacity="0.8">checkout_timeout</text> <text x="440" y="80" font-size="11.5" font-weight="700" fill="#7c5cff">PERMITS</text> <text x="440" y="98" font-size="9">max_size of them</text> <text x="440" y="114" font-size="9" opacity="0.8">THE semaphore</text> <text x="612" y="80" font-size="11.5" font-weight="700" fill="#0fa07f">FREE LIST</text>
  <text x="612" y="98" font-size="9">LIFO: warmest first</text> <text x="612" y="114" font-size="9" opacity="0.8">idle ones age out</text> <text x="784" y="80" font-size="11.5" font-weight="700" fill="#3553ff">IN USE</text> <text x="784" y="98" font-size="9">one task, one conn</text> <text x="784" y="114" font-size="9" opacity="0.8">never shared</text> </g>
  <path d="M784 132 L 784 160 L 614 160 L 614 136" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l12-ar)"/> <path d="M268 132 L 268 160 L 200 160" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l12-ar)"/> <text x="672" y="178" font-size="10" text-anchor="middle" fill="#0fa07f">release(): reset() &#8594; LIFO push &#8594; wake the queue head</text>
  <text x="234" y="178" font-size="10" text-anchor="middle" fill="#d64545">timeout &#8594; PoolTimeout</text> <g fill="none" stroke-width="2" stroke-linejoin="round"> <rect x="21" y="196" width="838" height="212" rx="11" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4"/> </g>
  <text x="40" y="222" font-size="11.5" font-weight="700">THE LIFECYCLE HOOKS — each one exists because of one specific bug</text> <g font-size="9" opacity="0.65" font-weight="700"> <text x="40" y="248">HOOK</text><text x="250" y="248">WHEN IT RUNS</text><text x="470" y="248">THE BUG IT PREVENTS</text> </g> <g font-size="9.5"> <text x="40" y="274" fill="#0fa07f" font-weight="700">on-create</text>
  <text x="250" y="274" opacity="0.85">min_size / first use</text> <text x="470" y="274">the 6 ms handshake landing on the request path</text> <text x="40" y="300" fill="#e0930f" font-weight="700">validate</text> <text x="250" y="300" opacity="0.85">on checkout (SELECT 1)</text> <text x="470" y="300">handing out a corpse after failover or a NAT idle-out</text> <text x="40" y="326" fill="#3553ff" font-weight="700">reset</text>
  <text x="250" y="326" opacity="0.85">on return</text> <text x="470" y="326">an open transaction or SET leaking into the next user</text> <text x="40" y="352" fill="#7c5cff" font-weight="700">idle evict</text> <text x="250" y="352" opacity="0.85">background reaper</text> <text x="470" y="352">20 idle backends held open all night for a 3am cron</text> <text x="40" y="378" fill="#d64545" font-weight="700">max_lifetime</text>
  <text x="250" y="378" opacity="0.85">on return / reaper</text> <text x="470" y="378">no rebalance after failover — jitter it or they stampede</text> </g> <text x="440" y="440" font-size="11" text-anchor="middle" opacity="0.9">acquire() takes a permit and hands you an object. release() returns both. Everything else is a rule.</text> </g> </svg>
```

**Min/idle size versus max size.** `min_size` is how many connections the pool keeps alive even when nothing is happening; `max_size` is the semaphore count. Keeping a minimum warm means the first request after a quiet period does not pay 6 ms of handshake, but it also means holding N backends open on the database all night for a service that only runs at 9am.

**The free list** holds constructed, idle objects. The checkout path is: take a permit; if the free list has something, pop it; otherwise, if fewer than `max_size` objects exist, create one; otherwise, wait.

**The wait queue** is a separate structure with its own two policies. It needs a **bound** — an unbounded queue of waiters is just an unbounded memory leak with extra steps — and a **timeout**, which is the single most important setting in any pool. It also needs an ordering, and the standard answer is FIFO; see *Fairness* below.

**The five hooks** in the diagram each exist because of a specific production bug. *On-create* is where you pay the handshake, so you want it off the request path. *Validation on checkout* catches connections that died silently. *Reset on return* is what stops a `SET statement_timeout`, an open transaction, a temp table or a prepared statement from leaking into the next request that gets this connection — a genuine cross-user data-integrity hazard. *Idle eviction* shrinks the pool back down. *Max-lifetime recycling* forces connections to be rebuilt periodically, which is how a fleet rebalances onto a new primary after failover instead of clinging to the old one forever.

### Sizing: bigger is not better, and it is not close

This is the section that changes how you work.

The instinct is that a pool is a buffer, so more is safer. It is not a buffer. **It is a concurrency limit imposed on a shared, finite downstream.** A database has some number of cores and some number of storage devices. If you send it 64 concurrent queries and it can genuinely execute 8, the other 56 do not vanish — they queue *inside the database*, where queueing is expensive: more context switches, more contention on internal latches and buffer-pool locks, more cache-line ping-pong, more lock waits between transactions. Throughput plateaus and then declines; latency for **every** query, including the ones that would have been fast, goes up.

```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Measured throughput and database-side p99 latency against pool size, from 1 to 64. Throughput rises steeply to a knee at pool size 12 where it reaches 1785 operations per second, then plateaus and declines to 1394 at pool size 64. Database-side p99 latency stays flat near 5 milliseconds up to the knee and then climbs steadily to 48.8 milliseconds, so five times the pool bought 22 percent less throughput and nearly six times the latency.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor"> <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700">The sizing curve: 5x the pool, −22% throughput, 6x the database p99</text> <rect x="418" y="88" width="408" height="246" rx="6" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.35" stroke-width="1.4"/>
  <g stroke="currentColor" stroke-opacity="0.16" stroke-width="1"> <line x1="80" y1="90" x2="820" y2="90"/><line x1="80" y1="150" x2="820" y2="150"/> <line x1="80" y1="210" x2="820" y2="210"/><line x1="80" y1="270" x2="820" y2="270"/> </g> <line x1="80" y1="330" x2="826" y2="330" stroke="currentColor" stroke-width="1.6"/> <path d="M408 88 L 408 334" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="5 5"/>
  <path d="M511 88 L 511 200" stroke="#7c5cff" stroke-width="1.4" stroke-dasharray="4 4"/> <path d="M80 306 L 162 279 L 244 230 L 326 126 L 408 116 L 490 116 L 573 123 L 655 131 L 737 148 L 820 163" fill="none" stroke="#0fa07f" stroke-width="2.4" stroke-linejoin="round"/> <path d="M80 305 L 162 305 L 244 304 L 326 303 L 408 290 L 490 280 L 573 254 L 655 227 L 737 170 L 820 96"
  fill="none" stroke="#e0930f" stroke-width="2.4" stroke-linejoin="round"/> <g fill="#0fa07f"><circle cx="80" cy="306" r="3"/><circle cx="162" cy="279" r="3"/><circle cx="244" cy="230" r="3"/><circle cx="326" cy="126" r="3"/><circle cx="408" cy="116" r="5"/><circle cx="490" cy="116" r="3"/><circle cx="573" cy="123" r="3"/><circle cx="655" cy="131" r="3"/><circle cx="737" cy="148" r="3"/><circle cx="820" cy="163" r="3"/></g>
  <g fill="#e0930f"><circle cx="80" cy="305" r="3"/><circle cx="162" cy="305" r="3"/><circle cx="244" cy="304" r="3"/><circle cx="326" cy="303" r="3"/><circle cx="408" cy="290" r="5"/><circle cx="490" cy="280" r="3"/><circle cx="573" cy="254" r="3"/><circle cx="655" cy="227" r="3"/><circle cx="737" cy="170" r="3"/><circle cx="820" cy="96" r="3"/></g> <g font-size="9" opacity="0.65" text-anchor="end">
  <text x="72" y="94">2000</text><text x="72" y="154">1500</text><text x="72" y="214">1000</text><text x="72" y="274">500</text><text x="72" y="334">0</text> </g> <g font-size="9" opacity="0.65" text-anchor="start"> <text x="834" y="94">50</text><text x="834" y="142">40</text><text x="834" y="190">30</text><text x="834" y="238">20</text><text x="834" y="286">10</text><text x="834" y="334">0</text> </g>
  <g font-size="9.5" text-anchor="middle" opacity="0.85"> <text x="80" y="350">1</text><text x="162" y="350">2</text><text x="244" y="350">4</text><text x="326" y="350">8</text><text x="408" y="350" font-weight="700" fill="#0fa07f">12</text><text x="490" y="350">16</text><text x="573" y="350">24</text><text x="655" y="350">32</text><text x="737" y="350">48</text><text x="820" y="350">64</text> </g>
  <text x="440" y="370" font-size="10" text-anchor="middle" opacity="0.8">pool size = the concurrency limit the database actually sees</text> <g font-size="10"> <line x1="92" y1="52" x2="120" y2="52" stroke="#0fa07f" stroke-width="2.4"/> <text x="128" y="56" fill="#0fa07f" font-weight="700">throughput (ops/s, left)</text> <line x1="330" y1="52" x2="358" y2="52" stroke="#e0930f" stroke-width="2.4"/>
  <text x="366" y="56" fill="#e0930f" font-weight="700">database-side p99 (ms, right)</text> </g> <g font-size="10"> <text x="420" y="196" font-weight="700" fill="#0fa07f">knee: pool = 12</text> <text x="420" y="212">1785 ops/s · db p99 8.4 ms</text> <text x="420" y="228" opacity="0.8">everything past here is latency debt</text> <text x="516" y="158" fill="#7c5cff" font-weight="700">heuristic = 18</text>
  <text x="516" y="173" fill="#7c5cff" opacity="0.85">(cores×2)+spindles</text> <text x="816" y="200" text-anchor="end" fill="#0fa07f" font-weight="700">1394 ops/s (−22%)</text> <text x="826" y="80" text-anchor="end" fill="#e0930f" font-weight="700">48.8 ms (5.8x)</text>
  <text x="622" y="322" text-anchor="middle" fill="#d64545" font-size="10.5" font-weight="700">wider pool · no more throughput · worse latency · angrier DBA</text> </g> <text x="440" y="404" font-size="11" text-anchor="middle" opacity="0.9">Measure the curve. The formula tells you where to start looking, not where to stop.</text> </g> </svg>
```

The commonly quoted starting formula, from the PostgreSQL and HikariCP tuning literature, is:

```text
connections ≈ (core_count × 2) + effective_spindle_count
```

The reasoning is sound: `core_count` bounds how many queries can genuinely execute at once; doubling it covers the fraction of queries blocked on I/O rather than computing; and `effective_spindle_count` — how many independent storage devices can seek in parallel — adds capacity for the queries that are waiting on disk. On an 8-core box with a couple of devices, that is 18.

**Treat it as where you start looking, not as an answer.** In the Build It, the modelled downstream never blocks on disk, so the doubling term — which exists to cover queries waiting on I/O rather than computing — is pure over-provisioning. The measured knee is **12**: the right order of magnitude, and still 50% below what the formula predicts. On a real workload dominated by disk-bound sequential scans it could land above 18. Only the curve knows.

Now connect the arrival side, from [Why Concurrency?](../01-why-concurrency/). **Little's Law** states that for a stable system, `L = λW`: the average number of items in the system equals arrival rate times average time in the system. To sustain λ = 1,000 requests/second where each holds a connection for W = 5 ms, you need `L = 1000 × 0.005 = 5` connections in flight. That is the honest arithmetic for sizing, and it has a sharp corollary: if `λW` comes out larger than the number of connections your database can actually serve well, **widening the pool does not fix it.** Your options are to reduce W (make queries faster, hold connections for less time) or reduce λ (shed load). Widening the pool only moves the queue from a place where it is cheap to a place where it is catastrophic.

Which is the last and most important idea here: **the pool is where queueing should happen.** A request waiting for a permit inside your process consumes a few kilobytes of stack and nothing else. The same request waiting inside a thrashing database consumes a backend process, holds locks, dirties the buffer cache, and slows down every other query. Waiting in your process is free. Waiting in the database is contagious.

### The multiplication nobody writes down

```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="Twenty replicas each running four worker processes each holding a pool of twenty connections fan in to one database. On the left, without a pooler, 1600 connections arrive at a database whose max_connections is 200, of which 192 are usable, so 1408 are rejected with FATAL sorry too many clients already. On the right, PgBouncer in transaction mode is interposed and multiplexes 1730 client connections onto 192 server backends, at the cost of breaking prepared statements, session-level SET, advisory locks and LISTEN NOTIFY.">
  <defs><marker id="l12-m3" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs> <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700">The multiplication nobody writes down</text> <g fill="none" stroke-width="2" stroke-linejoin="round">
  <rect x="16" y="40" width="416" height="390" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.55"/> <rect x="448" y="40" width="416" height="390" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.55"/> </g> <text x="224" y="64" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">NO POOLER — the arithmetic wins</text>
  <text x="656" y="64" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">PGBOUNCER — transaction mode</text> <g fill="none" stroke-width="1.8" stroke-linejoin="round" stroke="#3553ff"> <rect x="36" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/> <rect x="130" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/>
  <rect x="224" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/> <rect x="468" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/> <rect x="562" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/> <rect x="656" y="78" width="88" height="62" rx="8" fill="#3553ff" fill-opacity="0.12"/> </g> <g text-anchor="middle">
  <g font-size="9.5" font-weight="700" fill="#3553ff"><text x="80" y="98">replica 1</text><text x="174" y="98">replica 2</text><text x="268" y="98">replica 3</text><text x="512" y="98">replica 1</text><text x="606" y="98">replica 2</text><text x="700" y="98">replica 3</text></g>
  <g font-size="8.5" opacity="0.85"><text x="80" y="114">4 workers</text><text x="174" y="114">4 workers</text><text x="268" y="114">4 workers</text><text x="512" y="114">4 workers</text><text x="606" y="114">4 workers</text><text x="700" y="114">4 workers</text></g>
  <g font-size="8.5" font-weight="700"><text x="80" y="130">4×20 = 80</text><text x="174" y="130">4×20 = 80</text><text x="268" y="130">4×20 = 80</text><text x="512" y="130">4×20 = 80</text><text x="606" y="130">4×20 = 80</text><text x="700" y="130">4×20 = 80</text></g> <g font-size="9" opacity="0.75"><text x="372" y="113">… × 20</text><text x="804" y="113">… × 20</text></g> </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.75"> <path d="M80 140 L 80 170 L 372 170"/><path d="M174 140 L 174 170"/><path d="M268 140 L 268 170"/><path d="M372 140 L 372 170" stroke-dasharray="4 4"/> <path d="M512 140 L 512 170 L 804 170"/><path d="M606 140 L 606 170"/><path d="M700 140 L 700 170"/><path d="M804 140 L 804 170" stroke-dasharray="4 4"/> </g>
  <path d="M226 170 L 226 214" fill="none" stroke="#d64545" stroke-width="3" marker-end="url(#l12-m3)"/> <path d="M658 170 L 658 192" fill="none" stroke="#7c5cff" stroke-width="3" marker-end="url(#l12-m3)"/> <text x="240" y="196" font-size="10.5" font-weight="700" fill="#d64545">1600 connection attempts</text> <g fill="none" stroke-width="2" stroke-linejoin="round">
  <rect x="76" y="220" width="300" height="86" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/> <rect x="508" y="196" width="300" height="62" rx="10" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/> <rect x="508" y="292" width="300" height="82" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/> </g> <path d="M658 258 L 658 288" fill="none" stroke="#0fa07f" stroke-width="3" marker-end="url(#l12-m3)"/>
  <g text-anchor="middle"> <text x="226" y="244" font-size="11.5" font-weight="700">PostgreSQL</text> <text x="226" y="262" font-size="9" opacity="0.9">max_connections = 200 · 192 usable</text> <text x="658" y="218" font-size="11.5" font-weight="700" fill="#7c5cff">PgBouncer</text> <text x="658" y="234" font-size="9" opacity="0.9">one server conn per TRANSACTION, not per client</text>
  <text x="658" y="250" font-size="9" font-weight="700">1730 client conns → 192 server backends</text> <text x="658" y="316" font-size="11.5" font-weight="700">PostgreSQL</text> <text x="658" y="334" font-size="9" opacity="0.9">max_connections = 200 · 192 usable</text> <text x="658" y="370" font-size="8.5" opacity="0.9">192 backends, reused by every client that needs one</text> </g> <g stroke-width="1.4">
  <rect x="96" y="274" width="260" height="13" rx="3" fill="none" stroke="currentColor" stroke-opacity="0.5"/> <rect x="96" y="274" width="31" height="13" rx="3" fill="#0fa07f" fill-opacity="0.5" stroke="#0fa07f"/> <rect x="127" y="274" width="229" height="13" fill="#d64545" fill-opacity="0.35" stroke="none"/> <rect x="528" y="344" width="260" height="13" rx="3" fill="none" stroke="currentColor" stroke-opacity="0.5"/>
  <rect x="528" y="344" width="232" height="13" rx="3" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f"/> </g> <text x="226" y="300" font-size="8.5" text-anchor="middle" font-weight="700" fill="#d64545">192 fit · 1408 rejected</text> <g fill="none" stroke-width="2" stroke-linejoin="round"> <rect x="76" y="322" width="300" height="60" rx="9" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/> </g> <g text-anchor="middle">
  <text x="226" y="346" font-size="10" font-weight="700" fill="#d64545">FATAL: sorry, too many clients already</text> <text x="226" y="366" font-size="9" opacity="0.9">every replica is healthy. The arithmetic is not.</text> <text x="226" y="408" font-size="11" font-weight="700">20 replicas × 4 workers × 20 pool = 1600</text>
  <text x="656" y="396" font-size="9.5" font-weight="700" fill="#e0930f">what transaction mode breaks:</text> <text x="656" y="412" font-size="8.5" opacity="0.9">prepared statements · session SET · advisory locks · LISTEN/NOTIFY</text> </g> <text x="440" y="462" font-size="11" text-anchor="middle" opacity="0.9">total = pool_size × worker processes × PEAK replicas. Nobody types 1600 — the autoscaler does.</text> </g> </svg>
```

The formula is one line and you must run it before every deploy that changes any of its terms:

```text
total_connections = pool_size × worker_processes × PEAK_replicas   (+ sidecars, + crons, + migrations)
```

Three things make this go wrong quietly.

**A pool cannot be shared across processes.** A pool is an in-memory data structure guarded by an in-process lock. When gunicorn or uvicorn forks four workers, you get four independent pools, each with its own `max_size`. Worse, if you build the pool *before* the fork, each child inherits the parent's already-open sockets and multiple processes start writing into the same TCP connection — a corruption bug that looks like random protocol errors. Always create pools **after** fork, in a worker-init hook.

**Autoscaling multiplies dynamically.** The number that must fit inside `max_connections` is your **peak** replica count, not your steady-state one, and peak is exactly when the database is already busiest.

**Everything else connects too.** Cron jobs, migration runners, admin consoles, the analytics sidecar, your monitoring exporter, the person with psql open. Reserve headroom: PostgreSQL's `superuser_reserved_connections` exists so you can still get in to fix it, and it defaults to 3 — set it higher.

### Health, staleness and recycling

A pooled connection is a socket that has been sitting idle, and idle sockets die silently:

- A **NAT** (Network Address Translation) gateway or stateful firewall drops its mapping after an idle timeout — often 350 seconds on cloud NAT, sometimes 60 on a load balancer. Neither end is told. Your next write lands in a black hole and you learn about it on TCP retransmit timeout, tens of seconds later.
- The database **restarts, fails over, or is redeployed**. If it closed cleanly you get a RST and find out fast; if the node vanished you do not.
- A **proxy** (PgBouncer, an AWS RDS Proxy, an Envoy sidecar) closes idle server connections on its own schedule.

The pool does not know. It hands you the corpse, your query fails, and a user sees a 500. In the Build It, killing all six pooled connections server-side and then issuing 60 requests produced **6 failed requests** — one per dead connection — before the pool organically rebuilt itself.

The fixes, and their costs:

- **Validate on checkout** (`SELECT 1`, or the driver's `pool_pre_ping`). Correct, and expensive: it is one extra round trip on **every** request. Measured cost in the Build It: **+0.83 ms per request, +74%** on a workload whose real query took 1 ms. Failures went from 6 to **0**. Use it when you sit behind a NAT, a proxy or a failover-capable endpoint; skip it on a direct, stable link where the driver's error handling plus a retry is cheaper.
- **Background reaping** of idle connections. Closes connections that have sat unused past `idle_timeout`, shrinking the pool overnight. Costs nothing on the request path.
- **`max_lifetime` recycling.** Every connection is retired after a fixed age regardless of health. This is what makes a fleet converge after a failover or a rolling upgrade — otherwise a connection opened to the old primary lives until something breaks it.
- **TCP keepalives** (`keepalives_idle`, `keepalives_interval`). Cheap, and they stop the NAT from garbage-collecting your mapping in the first place. Set them *below* the NAT's idle timeout.

**Jitter your `max_lifetime`.** If every connection is created at startup with a 30-minute lifetime, every connection expires at the same instant 30 minutes later, and your whole fleet reconnects simultaneously — a thundering herd of handshakes exactly like the cache stampede in [Cache Stampede](../../05-caching/06-cache-stampede/) and the retry storms in [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/). The Build It's pool multiplies each lifetime by a random factor in `1 ± jitter`; with a 1.0 s lifetime and 0.25 jitter, eight connections expired across **0.78 s to 1.08 s** instead of all at 1.00 s.

### Checkout timeout and pool exhaustion

An unbounded wait for a permit is the single worst default in pooling, because it silently converts a *slow dependency* into a *fully hung service*. Every request that needs the database parks forever; your worker threads are all blocked; your health check (which probably does not touch the database) still returns 200; and the load balancer keeps sending traffic to a process that will never answer.

A bounded wait converts the same failure into fast, visible, countable errors. The Build It sends 240 requests at 400 req/s (an **open loop** — arrivals do not wait for replies) into a pool of 4 whose capacity is 160 req/s, a 2.5x overload:

| | served | shed | p99 | goodput ≤250 ms |
|---|---|---|---|---|
| unbounded wait | 240 | 0 | **962 ms** | 60 / 240 |
| 100 ms checkout timeout | 111 | 129 | **126 ms** | **111 / 240** |

The unbounded run "succeeded" at everything and was useless: p99 of 962 ms for 25 ms of work, and the queue kept draining for 962 ms *after the last request arrived*. That number grows linearly with how long the overload lasts — there is no bound. Meanwhile only 60 of the 240 responses arrived before the client's 250 ms deadline; the other 180 were work the system performed for nobody. The bounded run shed 129 requests in ~103 ms each and delivered **111 useful responses, 1.9x the goodput** — which is precisely the goodput-over-throughput argument from [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/).

**And now the crucial diagnostic point: pool exhaustion is almost always a symptom, not a cause.** `PoolTimeout` means demand for connection-seconds exceeded supply, and there are five different diseases with that one symptom:

1. **Slow queries** — W went up, so `λW` exceeded the pool. Fix the query or the index.
2. **A leak** — permits taken and never returned. Monotonic; never recovers.
3. **A held-open transaction** — a `BEGIN` with a slow HTTP call or a human inside it. Shows as `idle in transaction`.
4. **Unrelated I/O inside the checkout** — see below.
5. **Genuine capacity shortfall** — λ actually grew. The only one where a bigger pool is the right answer, and it is the rarest.

Raising `pool_size` "fixes" all five for about ten minutes and makes four of them worse. The runbook in `outputs/` is how you tell them apart.

### Leaks: the checkout that never came back

A leak is a connection acquired and never released, and it happens for three boring reasons: an early `return` between acquire and release, an exception on a path with no `finally`, or a forgotten `close()`.

```python
def get_user(uid):
    conn = pool.acquire()
    row = conn.query("SELECT ... WHERE id = %s", uid)
    if row is None:
        return None            # <- the connection is gone forever
    conn.query("UPDATE last_seen ...")
    pool.release(conn)
```

What makes leaks nasty is that they are **monotonic and indistinguishable from undersizing**. In the Build It, four of ten requests raised on the path between `acquire()` and `release()`; after the fourth, the pool sat at **4/4 in use, 0 idle, 100% utilization**, and the next three requests failed with `PoolTimeout` — exactly what a too-small pool looks like. The difference is that a too-small pool recovers when load drops and a leak never does. If you cannot tell which one you have, wait for the traffic trough: utilization that stays at 100% at 4am is a leak.

The fix is one rule with no exceptions: **acquire only inside a `with`.** The diagnostic is checkout tracking — record for every outstanding checkout the holder, the acquisition time, and a truncated stack of the code that acquired it, then report anything older than a threshold. The Build It's detector prints exactly that:

```console
  leak detector (checkouts held longer than 50 ms):
    conn#537  held   522.7 ms  by MainThread   acquired at leaky_request():809 <- demo_leaks():818
```

Real pools have this: SQLAlchemy's `pool_use_lifo`/`echo_pool` debugging and HikariCP's `leakDetectionThreshold` do the same job. Turn it on in staging permanently.

### The async traps

Everything above applies to threads and to `asyncio` alike. Four things are specific to async, and the first one is the most expensive bug in this lesson.

**(a) Holding a connection across an unrelated `await`.** In async code it costs nothing syntactically to `await` something in the middle of a block, so this reads as perfectly natural:

```python
async with pool.acquire() as conn:                 # permit taken here
    user = await conn.fetchrow("SELECT ...")       # 5 ms of database
    profile = await http.get(f"/profile/{user.id}")  # 50 ms of SOMETHING ELSE
    await conn.execute("UPDATE ...")               # 2 ms of database
```

The permit is held for 57 ms to do 7 ms of database work. Your pool's capacity, in requests per second, is `pool_size / hold_time` — so an unrelated 50 ms call multiplies your required pool size by 8, and it will exhaust at a fraction of the load you sized for. The Build It measures it directly:

```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 360" width="100%" style="max-width:840px" role="img" aria-label="Two timelines of how long one pooled connection is held. In the trap version the 50 millisecond HTTP call happens inside the checkout, so the permit is held 58.9 milliseconds and the pool achieves 135 operations per second on 8 permits, needing 59 permits to reach 1000 per second. In the fixed version the HTTP call happens before the checkout, the permit is held only 6.3 milliseconds, the pool achieves 866 operations per second, and 6 permits would reach 1000 per second.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor"> <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700">The async trap: one unrelated await, 9.4x the hold time</text> <text x="16" y="58" font-size="10.5" font-weight="700" fill="#d64545">TRAP — the HTTP call happens INSIDE the checkout</text>
  <rect x="116" y="66" width="650" height="44" rx="6" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4"/> <g stroke-width="1.8" stroke-linejoin="round"> <rect x="120" y="72" width="583" height="32" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/> <rect x="703" y="72" width="59" height="32" rx="4" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/> </g>
  <text x="16" y="93" font-size="9" opacity="0.75">permit</text> <text x="411" y="93" font-size="9.5" text-anchor="middle">await http_client.get(...) — 50 ms, and the database sees nothing</text> <text x="772" y="93" font-size="9" fill="#3553ff" font-weight="700">← 5 ms query</text> <text x="120" y="130" font-size="10.5" font-weight="700" fill="#d64545">permit held 58.9 ms — 89% of it spent not talking to the database</text>
  <text x="120" y="148" font-size="10">135 ops/s on 8 permits  ·  you would need 59 permits to reach 1000 ops/s</text> <text x="16" y="182" font-size="10.5" font-weight="700" fill="#0fa07f">FIX — the HTTP call happens BEFORE the checkout</text> <g stroke-width="1.8" stroke-linejoin="round"> <rect x="120" y="196" width="583" height="32" rx="4" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
  <rect x="703" y="196" width="61" height="32" rx="4" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/> </g> <rect x="699" y="190" width="69" height="44" rx="6" fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="5 4"/> <text x="16" y="217" font-size="9" opacity="0.75">permit</text>
  <text x="411" y="217" font-size="9.5" text-anchor="middle" opacity="0.85">await http_client.get(...) — 50 ms, holding nothing at all</text> <text x="776" y="217" font-size="9" fill="#0fa07f" font-weight="700">← 6.3 ms held</text> <text x="120" y="252" font-size="10.5" font-weight="700" fill="#0fa07f">permit held 6.3 ms — the checkout covers the query and nothing else</text>
  <text x="120" y="270" font-size="10">866 ops/s on 8 permits  ·  6 permits would reach 1000 ops/s</text> <line x1="120" y1="296" x2="830" y2="296" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.6"/> <g stroke="currentColor" stroke-width="1.2" stroke-opacity="0.6">
  <path d="M120 296 L 120 302"/><path d="M237 296 L 237 302"/><path d="M353 296 L 353 302"/><path d="M470 296 L 470 302"/><path d="M587 296 L 587 302"/><path d="M703 296 L 703 302"/><path d="M820 296 L 820 302"/> </g> <g font-size="9" opacity="0.65" text-anchor="middle">
  <text x="120" y="314">0</text><text x="237" y="314">10</text><text x="353" y="314">20</text><text x="470" y="314">30</text><text x="587" y="314">40</text><text x="703" y="314">50</text><text x="824" y="314">60 ms</text> </g> <text x="440" y="344" font-size="11" text-anchor="middle" opacity="0.9">Same work, same pool. The await never slowed the query — it multiplied how long you owned the permit.</text> </g> </svg>
```

The same work, the same pool, the same 8 permits: **135 ops/s versus 866 ops/s, a 6.4x throughput difference**, from moving one line above the `async with`. And it is worse than it looks — the trap version would need **59 permits** to sustain 1,000 ops/s where the fixed version needs **6**. That is your `max_connections` budget, spent on waiting.

**(b) Pools are per-event-loop and per-process.** An `asyncio` pool builds futures and locks bound to the loop that created it. Creating one at import time and using it from a different loop (or after `asyncio.run()` has closed the first) produces `got Future attached to a different loop`. Create the pool in your application's startup hook, on the loop that will use it.

**(c) One connection, one task at a time.** A database connection is a stateful protocol stream: request frames go out, response frames come back, in order. Two tasks issuing queries on the same connection interleave their frames and corrupt both. The pool is what enforces exclusivity — which is exactly why sharing a checked-out connection between `asyncio.gather()` branches, however convenient, is a data-corruption bug rather than a style issue.

**(d) Cancellation must still return the connection.** From [Structured Concurrency & Cancellation](../06-structured-concurrency-and-cancellation/): when a task is cancelled mid-query, `CancelledError` is raised at the `await` point. If your release is in a `finally` (or an `async with`), the connection goes back — good. But if the *server* is still executing that query, the connection is not actually idle; the next user of it will read the previous query's result rows and get silently wrong data. The correct behaviour is to either issue a protocol-level cancel and wait for it, or **discard the connection** rather than return it. `asyncpg` does this for you; a hand-rolled pool must be told.

### Fairness: LIFO objects, FIFO waiters

These look contradictory and are not, because they order two different things.

The **free list is LIFO** (Last In, First Out — a stack). The connection you just returned is the warmest: its TCP window is open, its TLS session is live, the server's plan cache and catalog cache for it are hot. Handing it back out maximises the chance of hitting warm state. LIFO also has a structural benefit — under light load the *same few* connections get reused and the rest sit untouched, ageing past `idle_timeout` so the reaper can close them. A FIFO free list would touch every connection in rotation and none would ever look idle, so the pool could never shrink.

The **wait queue is FIFO** (First In, First Out — a queue). Here the goal is the opposite: bounded waiting time. LIFO service for waiters would let a newly arrived request jump ahead of one that has been parked for 400 ms, and under sustained load some unlucky requests would wait effectively forever. That is unbounded p99 by construction. FIFO gives every waiter a bound: at most `queue_length × mean_hold_time`.

So: **LIFO for objects because state is warm; FIFO for people because starvation is unacceptable.** Most good pools do exactly this. The Build It's pool implements FIFO by handing a resource *directly* to the head waiter on release, rather than pushing it back and letting the woken threads race — a race would be neither FIFO nor bounded.

### External poolers: PgBouncer and transaction mode

When the multiplication cannot be made to fit — you genuinely need 400 processes and the database genuinely cannot host 400 backends — you interpose a **connection pooler** between your fleet and the database. PgBouncer is the canonical one for PostgreSQL. It accepts thousands of cheap client connections and multiplexes them onto a small number of real server connections. Its three modes differ in *when* a server connection is released back to its internal pool:

- **Session pooling.** A server connection is assigned for the entire life of the client connection. Nothing breaks, and nothing is gained beyond faster reconnects — you still need one server backend per concurrently connected client.
- **Transaction pooling.** A server connection is assigned only for the duration of a transaction and returned at `COMMIT`/`ROLLBACK`. **This is the mode that makes the arithmetic work**: 1,730 client connections can share 192 backends, because at any instant only a few hundred clients are actually inside a transaction.
- **Statement pooling.** Released after every single statement. Multi-statement transactions are impossible. Rarely what you want.

Transaction pooling works by breaking the assumption that a "connection" is a stable session. Anything with **session-scoped state** therefore breaks:

- **Server-side prepared statements** — your next execute may land on a different backend that never saw the `PREPARE`. (Mitigate: `prepare_threshold=0` in psycopg, `statement_cache_size=0` in asyncpg, or PgBouncer 1.21+ which tracks them.)
- **Session-level `SET`** (`SET statement_timeout`, `SET search_path`, `SET TIME ZONE`) — use `SET LOCAL` inside a transaction instead.
- **Advisory locks** taken with `pg_advisory_lock()` — session-scoped, so they may be taken on one backend and released on another. Use the `_xact_` variants.
- **`LISTEN`/`NOTIFY`** — inherently session-scoped; needs a dedicated session-mode connection.
- **`WITH HOLD` cursors** and temporary tables that outlive a transaction.
- **`SET` from your ORM's connection init hooks**, which is the way this usually bites people who did not know they had any of the above.

The other consequence is that your application's own pool should get *smaller*, not disappear. In transaction mode, the standard advice is a small per-process pool (or SQLAlchemy's `NullPool`, which does no pooling at all and relies entirely on PgBouncer being cheap to connect to).

### The metrics that matter

Instrument these and pool problems stop being mysterious. In the golden-signals framing from [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/), the pool is your clearest **saturation** signal — the leading indicator that fires before latency and errors do.

- **Checkout wait time, p50 and p99** (histogram). The single best pool metric. In a healthy pool p99 is near zero. Anything above a few milliseconds means you are queueing for permits.
- **Pool utilization** — `in_use / max_size` (gauge). Sustained 100%, especially through a traffic trough, is a leak or a genuine shortfall.
- **Checkout timeouts per second** (counter). Count the *events*, not a gauge sampled every 15 s — a gauge misses spikes between scrapes.
- **Connections created per second** (counter). A pool that is working creates almost nothing in steady state. A high sustained rate means you are churning, not pooling: something is killing connections (an aggressive `max_lifetime`, a NAT, a proxy) and you are paying the 6 ms handshake over and over.
- **In use vs idle vs waiting** (gauges). `waiting > 0` is the queue forming.

Alert on **checkout wait p99**, not on utilization. Utilization at 100% with zero wait time is a perfectly-sized pool.

## Build It

[`code/resource_pool.py`](code/resource_pool.py) builds a generic `ResourcePool` and then uses it to run seven measurements. Standard library only; it runs in about 18 seconds.

The core is `_take_locked`, which is the entire checkout policy in nine lines — free list first (LIFO, and recycle anything that has outlived `max_lifetime` on the way past), then spare capacity, then `None` meaning "you must wait":

```python
def _take_locked(self):
    """Free list first (LIFO, warm), then spare capacity. None => wait."""
    now = time.perf_counter()
    while self._free:
        entry = self._free.pop()               # LIFO: newest, warmest
        if entry.expires_at <= now:            # max-lifetime recycling
            self.recycled_total += 1
            self._total -= 1
            self._pending_close.append(entry)
            continue
        return entry
    if self._total < self._max_size:
        self._total += 1
        return _NEW                            # a slot, not an object
    return None
```

FIFO fairness is not achieved by waking everyone and letting them race — that would be neither FIFO nor bounded. It is achieved by **direct hand-off**: on release, the pool pops the *oldest* waiter and gives it the resource before anyone else can see it:

```python
def _grant_locked(self) -> None:
    """Hand resources straight to the head of the wait queue: strict FIFO."""
    while self._waiters:
        slot = self._take_locked()
        if slot is None:
            return
        waiter = self._waiters.popleft()       # oldest first
        self._in_use += 1
        waiter.granted = True
        if slot is _NEW:
            waiter.fresh = True                # you own a slot: go build it
        else:
            waiter.entry = slot
        waiter.event.set()
```

Lifetimes are jittered at creation, which is a one-line defence against a fleet-wide reconnect stampede:

```python
expires = now + self._max_lifetime * (1.0 + random.uniform(-self._jitter, self._jitter))
```

The context manager is the whole leak story. Note that it discards on exception rather than returning the resource — an exception may have left the connection mid-protocol, and returning it poisons the next user:

```python
@contextlib.contextmanager
def connection(self, timeout=None):
    """The only safe way to use a pool: release lives in a `finally`."""
    resource = self.acquire(timeout)
    try:
        yield resource
    except BaseException:
        self.release(resource, discard=True)
        raise
    else:
        self.release(resource)
```

And the async pool, in twenty lines, exists to make the point that it is the *same object*: a semaphore over a bag.

```python
class AsyncResourcePool:
    def __init__(self, factory, max_size: int):
        self._sem = asyncio.Semaphore(max_size)
        self._free: list[Any] = []

    @contextlib.asynccontextmanager
    async def connection(self):
        await self._sem.acquire()                                       # the permit
        resource = self._free.pop() if self._free else self._factory()  # LIFO
        try:
            yield resource
        finally:
            self._free.append(resource)
            self._sem.release()
```

The sizing curve needs a downstream that degrades the way a real database does, so `SimulatedDownstream` models contention rather than adding a constant delay: up to `cores` concurrent queries run at full speed, and past that each one slows *proportionally* (they share cores) **and** *superlinearly* (latch contention, context switching, cache thrash).

```python
over = max(1.0, n / self.cores)
elapsed = self.service_ms * over * (1.0 + self.thrash * (over - 1.0))
```

Run it:

```bash
docker compose exec -T app python phases/08-concurrency-and-performance/12-connection-and-resource-pooling/code/resource_pool.py
```

```console
== 1 · THE POOL: A SEMAPHORE OVER A BAG OF REUSABLE OBJECTS ==
  two checked out : in_use=2/3  idle=0  utilization=67%
  both returned   : in_use=0/3  idle=2  utilization=0%
  stats(): checkouts=2 created=2 timeouts=0 recycled=0 wait_p50=0.00ms wait_p99=0.01ms

== 2 · WHY POOL AT ALL: THE HANDSHAKE COSTS MORE THAN THE QUERY ==
  handshake budget : TCP 1.5 + TLS 3.0 + auth 1.5 = 6.0 ms per connect
  the query itself : 1.0 ms
  100 ops, reconnect each time :    842.7 ms ( 8.43 ms/op)
  100 ops, pooled (1 connect)  :    137.0 ms ( 1.37 ms/op)
  speedup                          :     6.15x   83.7% of the wall clock was handshake

== 3 · THE SIZING CURVE: BIGGER IS NOT BETTER, AND IT IS NOT CLOSE ==
  downstream   : 8 cores, 4.0 ms of work per query, superlinear contention past 8 concurrent
  offered load : 64 client threads, always trying (closed loop)

  pool  throughput   e2e p50   e2e p99    db p50    db p99   mean db   pool wait
  size      ops/s        ms        ms        ms        ms  inflight     p99 ms
     1        204     306.4     325.4      4.78      5.25       1.0       320.4
     2        422     152.6     160.0      4.55      5.31       1.9       155.1
     4        833      78.3      82.1      4.67      5.44       3.9        77.5
     8       1699      36.8      42.6      4.48      5.68       7.5        37.6
    12       1785      34.8      41.1      6.45      8.40      11.5        34.1
    16       1784      35.7      38.5      8.76     10.50      15.6        29.2
    24       1728      37.8      42.8     13.70     15.85      23.1        29.1
    32       1658      38.6      41.6     19.18     21.55      31.1        21.1
    48       1517      42.2      47.9     31.52     33.41      46.4        15.2
    64       1394      45.8      48.8     45.75     48.82      61.2         0.0

  peak throughput        : pool=12  1785 ops/s
  measured knee (>=97%)  : pool=12  1785 ops/s, db p99 8.4 ms <- the answer
  heuristic (cores*2+sp) : pool=18  = (8 x 2) + 2  <- a starting point, not an answer
  widest pool tested     : pool=64  1394 ops/s, db p99 48.8 ms
  5x the knee bought -22% throughput and 5.8x the database-side p99

== 4 · EXHAUSTION: UNBOUNDED WAIT HANGS, BOUNDED WAIT SHEDS ==
  240 requests arriving at 400 req/s (open loop) into a pool of 4 doing 25 ms of work each
  pool capacity = 4/25ms = 160 req/s. Offered load is 2.5x capacity.
  client gives up at 250 ms; anything slower is wasted work (Lesson 11's goodput)

                     served  shed   p50 ms   p99 ms   shed p99   wall ms   goodput
  unbounded wait       240     0    484.9    962.1         —    1562.4        60
  100 ms timeout       111   129    124.0    126.2      102.6     723.7       111

  unbounded: all 240 'succeeded', but p99 = 962 ms for 25 ms of work, and the queue drained 962 ms
             after the last arrival. The longer the overload lasts, the worse that gets — without bound.
  bounded  : 129 requests shed in 103 ms — fast, visible, alertable, retryable
  GOODPUT inside the 250 ms deadline: 60/240 unbounded vs 111/240 bounded  (1.9x)

== 5 · THE ASYNC TRAP: AN UNRELATED await INSIDE THE CHECKOUT ==
  identical work: a 50 ms HTTP call + a 5 ms query, 160 ops, 80 concurrent, pool_size=8

                                  hold ms    ops/s   wall ms   permits for 1000 ops/s
  HTTP call INSIDE the checkout      58.9      135      1181             59
  HTTP call BEFORE the checkout       6.3      866       185              6

  hold-time multiple 9.4x   throughput multiple 6.4x

== 6 · LEAKS: THE CHECKOUT THAT NEVER CAME BACK ==
  request 7: PoolTimeout — leaky: no resource after 151 ms (size=4/4, in_use=4, waiting=0)
  4 of 10 requests raised between acquire() and release(); the next 3 could not get a connection at all
  pool now: in_use=4/4  idle=0  checkout timeouts=3  utilization=100%
  this looks exactly like a pool that is too small — except it never recovers

  leak detector (checkouts held longer than 50 ms):
    conn#537  held   522.7 ms  by MainThread   acquired at leaky_request():809 <- demo_leaks():818
    conn#536  held   519.2 ms  by MainThread   acquired at leaky_request():809 <- demo_leaks():818
    ...
  same workload with `with`: 5 exceptions raised, in_use=0, idle=1, timeouts=0

== 7 · STALENESS: THE POOL WILL HAND YOU A CORPSE ==
  6 pooled connections, all killed server-side, then 60 requests

  validate_on_checkout=False :  6/60 failed with ConnectionError, mean 1.13 ms/req
  validate_on_checkout=True  :  0/60 failed, mean 1.96 ms/req, 6 corpses detected and replaced
  cost of SELECT 1           : +0.83 ms per request (+74%) — one extra round trip, every checkout

  max_lifetime=1.0s jitter=0.25 -> 8 connections expire across 0.78..1.08 s
  idle_timeout=0.2s: the background reaper evicted 8 idle connections; pool shrank to 0

== 8 · THE MULTIPLICATION NOBODY WRITES DOWN ==
  postgres max_connections = 200, 8 reserved for superuser/monitoring -> app budget 192

  service                  pool  workers  replicas    total   verdict
  api (steady state)         20        4         8      640   OVER by 448
  api (autoscaled peak)      20        4        20     1600   OVER by 1408
  async worker fleet         10        2         6      120   fits
  cron + migrations           5        1         2       10   fits

  peak fleet = (20x4x20) + (10x2x6) + (5x1x2) = 1730 vs budget 192  ->  9.0x OVER

  fix A: pool_size <= 2 per process (budget 192 / (4 workers x 20 peak replicas))
  fix B: PgBouncer in transaction mode — 1730 client connections multiplexed onto ~192 server backends
```

**Read the numbers — five of these are arguments, not demos.**

**Section 2** prices the thing everyone assumes. 100 operations of 1 ms each took **842.7 ms** when each opened its own connection and **137.0 ms** through a pool of one: a **6.15x speedup**, and 83.7% of the original wall clock was handshake that produced nothing. On the database side the unpooled version also forked and killed 100 backend processes. That is the case for pooling, and it is the last time in this lesson that "more pool" is unambiguously better.

**Section 3 is the point of the lesson.** Watch four columns together. Throughput climbs cleanly to **1,785 ops/s at pool=12** — the knee, where the downstream's 8 cores are saturated and a little queueing keeps them fed — and then *falls*: 1,728 at 24, 1,658 at 32, **1,394 at 64**. Meanwhile the database-side p99 (the time from getting a connection to the query returning, which is what your DBA sees) sits between **5.2 and 5.7 ms all the way to pool=8**, is 8.4 ms at the knee, and then climbs monotonically to **48.8 ms**. Now the last column, `pool wait p99`: at the knee, requests waited **34 ms** for a permit; at pool=64 they waited **0 ms**. That is the trade laid bare. The wide pool eliminated all waiting inside your process by relocating every last bit of it into the database, where the identical queue costs 5.8x the latency and a fifth of your throughput. And the customer got nothing for it — the end-to-end p99 column reads **41.1 ms at pool=12 versus 48.8 ms at pool=64**: the wide pool is worse end to end as well. Finally, the `(cores × 2) + spindles` heuristic predicted **18** against a measured **12**. It found the right order of magnitude and was 50% high, because the doubling term exists to cover I/O wait that this workload never incurs. Measure.

**Section 4** is what a bounded checkout timeout is for. Under a 2.5x open-loop overload, the unbounded pool served every one of the 240 requests — and its p99 was **962 ms for 25 ms of work**, with the queue still draining **962 ms after the last request arrived**. That last number is the important one: it grows linearly with the duration of the overload, so on a real incident lasting minutes the tail is unbounded. Only **60 of 240** responses beat the client's 250 ms deadline; the rest was work performed for nobody, and every one of those wasted requests occupied a connection that a useful request needed. The bounded pool shed 129 requests in about 103 ms each — a real error, fast, that a caller can retry or degrade on — and delivered **111 useful responses, 1.9x the goodput**, with a p99 of **126.2 ms** that stays put no matter how long the overload lasts. Bounding the wait did not reduce capacity; it stopped capacity being spent on answers nobody would read.

**Section 5** is the async trap, and the multiple is not subtle. Identical work, identical pool, identical 8 permits: with the 50 ms HTTP call inside the checkout the permit is held **58.9 ms** and the system does **135 ops/s**; moved outside, the hold is **6.3 ms** and it does **866 ops/s** — **6.4x**. The right-hand column is the one to take to a design review: to sustain 1,000 ops/s the trap version needs **59 connections** and the fixed version needs **6**. That is the difference between fitting in `max_connections` and not. Nothing about the query changed; only how long you owned the permit.

**Sections 6 and 7** are the two failure modes you will actually page on. The leak drove utilization to **4/4, 100%**, with three subsequent `PoolTimeout`s and no idle connections — visually identical to a too-small pool, which is why the tracker matters: it names four checkouts held for over 500 ms and the exact function that acquired them. The same workload with `with` finished at **in_use=0** with zero timeouts. Section 7 prices the health check: killing all six connections server-side cost **6 failed user requests** without validation and **0** with it, for **+0.83 ms (+74%)** on every single request forever. That is a real trade, not an obvious win — the right answer depends on whether you sit behind a NAT or a failover endpoint, and the number to compare it against is your own p99 budget.

## Use It

**SQLAlchemy** (synchronous or async) is the pool most Python services actually run. Every parameter maps to something you just built:

```python
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql+psycopg://app@db/app",
    pool_size=8,            # your max_size — the STEADY concurrency limit
    max_overflow=4,         # extra connections allowed in a burst, closed after use
    pool_timeout=1.0,       # your checkout_timeout. NEVER leave this unbounded
    pool_recycle=1800,      # your max_lifetime, seconds (SQLAlchemy jitters nothing — see below)
    pool_pre_ping=True,     # your validate_on_checkout (SELECT 1): +1 round trip/request
    pool_use_lifo=True,     # your LIFO free list; lets idle connections age out
    connect_args={"keepalives_idle": 30, "keepalives_interval": 10},
)

with engine.connect() as conn:            # your `with pool.connection()`
    conn.execute(text("SELECT 1"))
```

The real ceiling is `pool_size + max_overflow` — that is the number that goes into the multiplication, not `pool_size`. `QueuePool` is the default and is what you built. `NullPool` opens and closes a connection per checkout and is the **right** choice behind a transaction-mode PgBouncer, where connecting is cheap and a local pool would just add a second layer of idle sockets holding PgBouncer client slots. `pool_recycle` is not jittered, so with many replicas restarted together, add your own spread (e.g. `pool_recycle=1800 + random.randint(0, 300)` at engine creation).

**asyncpg** for async PostgreSQL:

```python
pool = await asyncpg.create_pool(
    dsn, min_size=2, max_size=8,
    max_inactive_connection_lifetime=300,   # your idle_timeout
    command_timeout=2.0,                    # a query timeout — NOT the checkout timeout
    max_queries=50_000,                     # recycle a connection after N queries
)

async with pool.acquire() as conn:          # wrap in asyncio.wait_for() for a checkout timeout
    await conn.fetchrow("SELECT ...")
```

Note the gap: `asyncpg.Pool.acquire()` takes an optional `timeout`, and if you omit it you have the unbounded wait from Section 4. Always pass it. `command_timeout` bounds the *query*, which is a different (and also necessary) bound.

**HTTP connections pool too**, and the same reasoning applies — the keep-alive mechanics are in [Keep-Alive, Pooling & Timeouts](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/):

```python
limits = httpx.Limits(max_connections=100, max_keepalive_connections=20,
                      keepalive_expiry=30.0)
client = httpx.AsyncClient(limits=limits, timeout=httpx.Timeout(2.0, connect=1.0))

# requests/urllib3 equivalent
session = requests.Session()
session.mount("https://", HTTPAdapter(pool_connections=10, pool_maxsize=20,
                                      max_retries=Retry(total=2, backoff_factor=0.2)))
```

`urllib3`'s default `pool_maxsize` is **10** per host, and by default it silently discards connections beyond that instead of blocking (`block=False`) — so a burst quietly reverts to connect-per-request. Set `pool_maxsize` to your real concurrency.

**Redis**: `redis.ConnectionPool(max_connections=N)` with `redis.Redis(connection_pool=pool)`. Redis commands are microseconds, so the pool is small — but a `BLPOP` or a `WATCH`/`MULTI` block holds a connection for its entire duration, which is exactly the async trap in a different costume.

**PgBouncer** when the arithmetic will not fit:

```yaml
# pgbouncer.ini
pool_mode = transaction        # session | transaction | statement
max_client_conn = 5000         # cheap client sockets
default_pool_size = 40         # server backends per (database, user) pair
reserve_pool_size = 5
server_idle_timeout = 600
```

Before you switch to transaction mode, audit for: server-side prepared statements, session `SET`, `pg_advisory_lock`, `LISTEN`/`NOTIFY`, `WITH HOLD` cursors, and temp tables. Each has a workaround; each will break silently and intermittently if you skip the audit.

Production rules, hard-won:

- **Measure the curve; never guess the size.** Sweep pool sizes against real traffic and pick the knee — the smallest pool that reaches ~97% of peak throughput. In the Build It the knee was **12** where the popular formula said 18, and pool=64 gave 22% *less* throughput at 5.8x the database p99.
- **Compute `pool_size × workers × PEAK replicas` against `max_connections` before every deploy** that changes any term, and put the result in the PR description. Add crons, migrations, sidecars, and your own `psql`.
- **Always set a checkout timeout, and make it short** — a second, not thirty. An unbounded wait turns a slow dependency into a hung service; a bounded one turns it into an error you can shed on and alert on.
- **Always `with`. No exceptions, ever.** And enable leak detection in staging permanently — 100% utilization that survives the traffic trough is a leak, not a capacity problem.
- **Never hold a connection across unrelated I/O.** Fetch from the cache, call the third-party API, render the template — all of it *outside* the checkout. Measured cost of getting this wrong: 6.4x throughput and 9.4x the connections needed.
- **Jitter `pool_recycle`, and set TCP keepalives below your NAT's idle timeout.** Enable `pool_pre_ping` if you sit behind a NAT, a proxy, or a failover-capable endpoint; skip it on a direct link where +0.83 ms per request is not worth it.
- **Export checkout wait p99 and alert on it**, not on utilization. Then treat every `PoolTimeout` as a symptom to diagnose — slow query, leak, held transaction, or unrelated await — and never as a number to raise.

## Think about it

1. Your pool's checkout wait p99 is 400 ms, utilization is pinned at 100%, and the database reports a CPU load of 12%. Which of the five causes of exhaustion does that combination rule *out*, and what would you query next to discriminate between the ones it leaves?
2. You move to PgBouncer in transaction mode and set your application pools to `NullPool`. What have you gained, what have you moved rather than solved, and where does the queue form now when the database saturates?
3. Your service holds a connection for 5 ms per request and serves 2,000 requests/second across 10 replicas of 4 workers. Compute the per-process pool size Little's Law justifies, then compute the fleet total. Now the p99 query time triples during a nightly backup — what happens, and which of your three options (widen, shed, or fix W) is correct?
4. `pool_pre_ping` costs one round trip on every request and eliminates a class of failure entirely. Under what measurable conditions is that trade clearly wrong, and what would you instrument to know which side of the line you are on?
5. LIFO free list, FIFO wait queue. Construct a workload where a LIFO *wait* queue would actually produce better aggregate throughput than FIFO, and explain why virtually no production pool offers it anyway.

## Key takeaways

- A connection costs a TCP handshake, one or two TLS round trips, an authentication exchange and a forked server-side backend of several megabytes — about **6 ms and megabytes for a 1 ms query**. Pooling took 100 operations from **842.7 ms to 137.0 ms (6.15x)**, with **83.7%** of the original wall clock revealed as handshake.
- **A pool is a semaphore over a bag of reusable objects.** Sizing is the permit count, the checkout timeout is the acquire timeout, a leak is a permit never returned, and validation/reset/recycling are rules about the object rather than the permit. Every knob in every pool library falls out of that one sentence.
- **The pool is a concurrency limit on the downstream, and bigger is worse.** Measured knee at **pool=12: 1,785 ops/s, database p99 8.4 ms**. At **pool=64: 1,394 ops/s (−22%) and database p99 48.8 ms (5.8x)** — and the end-to-end p99 was worse too (41.1 ms vs 48.8 ms). Widening a pool does not remove the queue; it moves it from your process, where waiting is free, into the database, where it is contagious. `(cores × 2) + spindles` predicted 18 against a measured 12: a starting point, not an answer.
- **Total connections = pool_size × worker processes × PEAK replicas**, plus crons and sidecars. A pool cannot be shared across processes, so `20 × 4 × 20 = 1,600` against a `max_connections` budget of 192 — **8.3x over**, and 9.0x once the worker fleet and crons are added — with nobody ever having typed 1,600. Run the multiplication before the deploy, or interpose a transaction-mode pooler.
- **Never hold a connection across unrelated I/O, and never wait for one forever.** A 50 ms HTTP call inside the checkout took hold time from 6.3 ms to 58.9 ms, throughput from 866 to 135 ops/s (**6.4x**), and the connections needed for 1,000 ops/s from 6 to **59**. An unbounded checkout wait under a 2.5x overload gave p99 **962 ms** and 60/240 goodput; a 100 ms timeout gave p99 **126 ms** and **111/240 — 1.9x the goodput**.
- **Pool exhaustion is a symptom with five different diseases** — slow queries, a leak, a held-open transaction, unrelated I/O inside the checkout, or genuine capacity. Alert on **checkout wait p99** (saturation), watch **connections created/sec** for churn, always use `with`, jitter `pool_recycle`, and diagnose before you ever touch `pool_size`.

Next: [Profiling: Finding the Real Bottleneck](../13-profiling/) — you have now measured pools, queues and hold times from the outside; profiling opens the process and tells you which line of code the time is actually going to.
