# Why Concurrency? Latency, Throughput & Little's Law

> A typical API request takes 200 ms, and 195 ms of that is your process sitting still, blocked on a database and an HTTP call. Handled one at a time on a 16-core machine, that server measures **4.96 requests per second while using 0.157% of the CPU you are renting** — fifteen and a half cores doing nothing at all. The machine is not slow; it is idle, and it is idle because your code is standing in line. This lesson builds the four pieces of arithmetic that turn that observation into a number you can size a system with: latency versus throughput, Little's Law, the utilization knee, and the two laws that cap how far more workers can ever take you.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The CPU: Cores, Clock & Execution](../../00-foundations/05-the-cpu/), [RAM & the Memory Hierarchy](../../00-foundations/06-ram-and-memory-hierarchy/)
**Time:** ~60 minutes

## The Problem

You have written an ordinary endpoint. `GET /orders/{id}`. It parses and authorizes the request, queries Postgres for the order, calls the payments API to check whether the charge settled, shapes the result, and serializes JSON. Nothing exotic. It takes **200 ms**, and everybody agrees that is acceptable.

Then you profile where the 200 ms goes, and the shape of it is not what anyone expected:

```text
parse + authorize            2.5 ms   CPU
SELECT ... FROM orders     120.0 ms   blocked on the database
shape the rows               1.5 ms   CPU
GET /charges/{id}           75.0 ms   blocked on the payments API
serialize JSON               1.0 ms   CPU
                           -------
                           200.0 ms   of which 5.0 ms is CPU  (2.5%)
                                      and 195.0 ms is waiting (97.5%)
```

Five milliseconds. Out of two hundred. Everything else is your process suspended in a system call, holding a stack, a socket, and a slot in your web server's worker pool, while the actual work happens somewhere else on someone else's hardware.

Now run that endpoint the simplest possible way: one request at a time, start to finish, before touching the next. The Build It below measures exactly this, and here is what a real run reports:

```text
6 requests, ONE at a time : wall  1.211 s  cpu 0.030 s  ->   4.96 req/s
    CPU busy  2.51% of one core = 0.157% of a 16-core machine
```

**4.96 requests per second.** You are paying for sixteen cores. You are using **0.157% of them** — about one six-hundredth of a single core. If those cores cost you $1,200 a month, you are spending $1,198 a month on silicon that is switched on, warm, and doing nothing.

And the reflex reaction is the wrong one. Nobody's first instinct here is *"we are not overlapping the waiting."* The first instinct is "the server is slow — get a faster one." So you buy a machine with a higher clock and more cores, and your throughput goes from 4.96 req/s to 4.96 req/s, because the bottleneck was never the CPU. It was the shape of the code.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="A 200 millisecond request magnified to show 5 milliseconds of CPU split into three slivers separated by a 120 millisecond database wait and a 75 millisecond payments API wait, then two panels over the same one-second window: a serial server completing five requests per second while using 0.157 percent of a 16-core machine, and the same work with eight requests in flight completing forty per second with identical CPU cost."> <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The machine is not slow — it is standing in line</text> <rect x="16" y="44" width="848" height="124" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="2" fill-rule="evenodd"/> <text x="440" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#e0930f">ONE REQUEST — 200 ms on the wall, 5 ms of it yours</text> <text x="66" y="88" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">2.5 ms</text>
  <text x="529" y="88" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">1.5 ms</text> <text x="820" y="88" text-anchor="end" font-size="9" font-weight="700" fill="#0fa07f">1.0 ms</text> <g stroke-width="1.6"> <rect x="60" y="96" width="10" height="28" fill="#0fa07f" stroke="#0fa07f"/> <rect x="70" y="96" width="456" height="28" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/> <rect x="526" y="96" width="6" height="28" fill="#0fa07f" stroke="#0fa07f"/> <rect x="532" y="96" width="285" height="28" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
  <rect x="817" y="96" width="3" height="28" fill="#0fa07f" stroke="#0fa07f"/> </g> <text x="298" y="141" text-anchor="middle" font-size="10" fill="#d64545" font-weight="700">database query — 120 ms blocked</text> <text x="674" y="141" text-anchor="middle" font-size="10" fill="#d64545" font-weight="700">payments API — 75 ms blocked</text> <text x="440" y="160" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">5 ms of CPU (2.5%)  ·  195 ms of waiting (97.5%)</text> <rect x="16" y="182" width="416" height="286" rx="12" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="2"/>
  <rect x="448" y="182" width="416" height="286" rx="12" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/> <text x="224" y="208" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">SERIAL — one request at a time</text> <text x="656" y="208" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">8 IN FLIGHT — same work, overlapped</text> <g stroke-width="1.1"> <g fill="#d64545" fill-opacity="0.13" stroke="#d64545">
  <rect x="40" y="232" width="71" height="9"/><rect x="114" y="232" width="71" height="9"/><rect x="189" y="232" width="71" height="9"/><rect x="263" y="232" width="71" height="9"/><rect x="338" y="232" width="71" height="9"/> </g> <g fill="#0fa07f" stroke="none"> <rect x="40" y="232" width="2" height="9"/><rect x="114" y="232" width="2" height="9"/><rect x="189" y="232" width="2" height="9"/><rect x="263" y="232" width="2" height="9"/><rect x="338" y="232" width="2" height="9"/> </g> <g fill="none" stroke="currentColor" stroke-opacity="0.3" stroke-dasharray="4 4" stroke-width="1">
  <rect x="40" y="264" width="372" height="8"/><rect x="40" y="275" width="372" height="8"/><rect x="40" y="286" width="372" height="8"/><rect x="40" y="297" width="372" height="8"/><rect x="40" y="308" width="372" height="8"/><rect x="40" y="319" width="372" height="8"/><rect x="40" y="330" width="372" height="8"/> </g> </g> <text x="226" y="256" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.55">seven lanes you rent and never open</text> <g stroke-width="1.1"> <g fill="#d64545" fill-opacity="0.13" stroke="#d64545">
  <rect x="472" y="232" width="71" height="9"/><rect x="546" y="232" width="71" height="9"/><rect x="621" y="232" width="71" height="9"/><rect x="695" y="232" width="71" height="9"/><rect x="770" y="232" width="71" height="9"/> <rect x="472" y="245" width="71" height="9"/><rect x="546" y="245" width="71" height="9"/><rect x="621" y="245" width="71" height="9"/><rect x="695" y="245" width="71" height="9"/><rect x="770" y="245" width="71" height="9"/>
  <rect x="472" y="258" width="71" height="9"/><rect x="546" y="258" width="71" height="9"/><rect x="621" y="258" width="71" height="9"/><rect x="695" y="258" width="71" height="9"/><rect x="770" y="258" width="71" height="9"/> <rect x="472" y="271" width="71" height="9"/><rect x="546" y="271" width="71" height="9"/><rect x="621" y="271" width="71" height="9"/><rect x="695" y="271" width="71" height="9"/><rect x="770" y="271" width="71" height="9"/>
  <rect x="472" y="284" width="71" height="9"/><rect x="546" y="284" width="71" height="9"/><rect x="621" y="284" width="71" height="9"/><rect x="695" y="284" width="71" height="9"/><rect x="770" y="284" width="71" height="9"/> <rect x="472" y="297" width="71" height="9"/><rect x="546" y="297" width="71" height="9"/><rect x="621" y="297" width="71" height="9"/><rect x="695" y="297" width="71" height="9"/><rect x="770" y="297" width="71" height="9"/>
  <rect x="472" y="310" width="71" height="9"/><rect x="546" y="310" width="71" height="9"/><rect x="621" y="310" width="71" height="9"/><rect x="695" y="310" width="71" height="9"/><rect x="770" y="310" width="71" height="9"/> <rect x="472" y="323" width="71" height="9"/><rect x="546" y="323" width="71" height="9"/><rect x="621" y="323" width="71" height="9"/><rect x="695" y="323" width="71" height="9"/><rect x="770" y="323" width="71" height="9"/> </g> <g fill="#0fa07f" stroke="none">
  <rect x="472" y="232" width="2" height="9"/><rect x="546" y="232" width="2" height="9"/><rect x="621" y="232" width="2" height="9"/><rect x="695" y="232" width="2" height="9"/><rect x="770" y="232" width="2" height="9"/> <rect x="472" y="245" width="2" height="9"/><rect x="546" y="245" width="2" height="9"/><rect x="621" y="245" width="2" height="9"/><rect x="695" y="245" width="2" height="9"/><rect x="770" y="245" width="2" height="9"/>
  <rect x="472" y="258" width="2" height="9"/><rect x="546" y="258" width="2" height="9"/><rect x="621" y="258" width="2" height="9"/><rect x="695" y="258" width="2" height="9"/><rect x="770" y="258" width="2" height="9"/> <rect x="472" y="271" width="2" height="9"/><rect x="546" y="271" width="2" height="9"/><rect x="621" y="271" width="2" height="9"/><rect x="695" y="271" width="2" height="9"/><rect x="770" y="271" width="2" height="9"/>
  <rect x="472" y="284" width="2" height="9"/><rect x="546" y="284" width="2" height="9"/><rect x="621" y="284" width="2" height="9"/><rect x="695" y="284" width="2" height="9"/><rect x="770" y="284" width="2" height="9"/> <rect x="472" y="297" width="2" height="9"/><rect x="546" y="297" width="2" height="9"/><rect x="621" y="297" width="2" height="9"/><rect x="695" y="297" width="2" height="9"/><rect x="770" y="297" width="2" height="9"/>
  <rect x="472" y="310" width="2" height="9"/><rect x="546" y="310" width="2" height="9"/><rect x="621" y="310" width="2" height="9"/><rect x="695" y="310" width="2" height="9"/><rect x="770" y="310" width="2" height="9"/> <rect x="472" y="323" width="2" height="9"/><rect x="546" y="323" width="2" height="9"/><rect x="621" y="323" width="2" height="9"/><rect x="695" y="323" width="2" height="9"/><rect x="770" y="323" width="2" height="9"/> </g> </g> <g fill="none" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.4">
  <path d="M40 346 L 412 346"/><path d="M40 346 L 40 352"/><path d="M226 346 L 226 352"/><path d="M412 346 L 412 352"/> <path d="M472 346 L 844 346"/><path d="M472 346 L 472 352"/><path d="M658 346 L 658 352"/><path d="M844 346 L 844 352"/> </g> <g fill="currentColor" font-size="9" opacity="0.65"> <text x="40" y="364">0</text><text x="226" y="364" text-anchor="middle">500 ms</text><text x="412" y="364" text-anchor="end">1 s</text> <text x="472" y="364">0</text><text x="658" y="364" text-anchor="middle">500 ms</text><text x="844" y="364" text-anchor="end">1 s</text> </g> <g fill="currentColor">
  <text x="40" y="392" font-size="11.5" font-weight="700" fill="#3553ff">5 requests in 1 second = 5 req/s</text> <text x="40" y="412" font-size="10" opacity="0.9">measured: 4.96 req/s · CPU 2.51% of ONE core</text> <text x="40" y="432" font-size="10" opacity="0.9">= 0.157% of a 16-core machine</text> <text x="40" y="454" font-size="10.5" font-weight="700" fill="#d64545">15.97 cores doing nothing at all</text> <text x="472" y="392" font-size="11.5" font-weight="700" fill="#0fa07f">40 requests in 1 second = 40 req/s</text> <text x="472" y="412" font-size="10" opacity="0.9">8x the throughput, identical CPU work</text>
  <text x="472" y="432" font-size="10" opacity="0.9">CPU 1.2% of 16 cores — still nearly idle</text> <text x="472" y="454" font-size="10.5" font-weight="700" fill="#0fa07f">640 in flight → 3,200 req/s, CPU saturated</text> </g> <text x="440" y="486" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Concurrency does not make the CPU faster. It fills the 195 ms the CPU was already going to spend idle.</text> </g> </svg>
```

Look at the two bottom panels. They contain **exactly the same work** — the same instructions, the same syscalls, the same 5 ms of CPU per request. The only difference is whether request 2 is allowed to start while request 1 is blocked. That one structural decision is worth 8x, and it costs nothing in hardware.

That is what this whole phase is about, and this lesson gives you the vocabulary and the arithmetic to reason about it precisely — so that when someone says "the servers are only 80% busy, we have plenty of headroom", you know exactly why that sentence is wrong.

## The Concept

### Latency and throughput are not reciprocals

Two numbers describe every system's performance, and confusing them is the single most common analytical error in this field.

- **Latency** (also *response time*, written **W**) is how long **one** request takes, start to finish. Measured in seconds. It is a property of an individual request, so it has a *distribution* — a p50, a p99 — never just an average ([Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) is the lesson on why the average lies).
- **Throughput** (written **X** or **λ**, lambda) is how many requests **complete per second**. It is a property of the system as a whole over a window of time.

The trap is assuming one is `1 /` the other. It is not, and the Build It measures three implementations of the same endpoint to prove it:

```text
config                   capacity   W unloaded  W at 80% load       1/W
A  1 worker  x 10 ms      100.0/s       10.6 ms         50.5 ms    94.8/s
B 20 workers x 40 ms      500.0/s       39.7 ms         42.7 ms    25.2/s
C  4 workers x 25 ms      160.0/s       25.1 ms         43.1 ms    39.8/s
```

Config **A** has the best latency of the three (10.6 ms) and the *worst* throughput (100/s). Config **B** has the worst latency (39.7 ms) and *five times* A's throughput. And going from **C** to **B** — one refactor — improves throughput by 3.1x while making every individual request 1.6x slower. Latency and throughput are two separate dials, and it is entirely normal for a change to turn one clockwise and the other counter-clockwise.

Why `1/W` fails is worth stating exactly. For config B, `1/W = 25.2/s`, but B actually sustains **500/s** — off by a factor of **20**, which is precisely its worker count. The real relationship is:

```text
throughput = concurrency / latency          X = L / W
```

Twenty workers, each finishing one 40 ms request at a time, retire 20 requests every 40 ms. `1/W` is only the throughput of a system whose concurrency happens to be exactly 1. That formula is Little's Law rearranged, and you will meet it properly in a moment.

The supermarket analogy is the right one, provided you keep it honest. One express lane that serves a customer in 60 seconds has 60 s latency and 1 customer/minute of throughput. Twenty regular lanes taking 4 minutes each have **4x worse latency** and **5x better throughput** (20/4 = 5 customers per minute). Adding lanes does nothing for the customer standing in one; it does everything for the store. Which of those two numbers you are optimizing must be a decision, not an accident — because **latency is what a user feels and throughput is what your capacity plan is denominated in**, and there is no configuration that maximizes both.

> **The trap in production:** a p99 latency SLO and a throughput target are separate promises, and a change that meets one can break the other silently. Batching, connection pooling, Nagle's algorithm, request coalescing, and larger commit intervals all buy throughput with latency. Always graph both, on the same dashboard, from the same window.

### Concurrency is not parallelism

These two words are used interchangeably in conversation and they mean different things. Rob Pike's framing is the clearest one anybody has produced:

> **Concurrency is dealing with many things at once. Parallelism is doing many things at once.**

Sharpen it into definitions you can apply mechanically:

- **Concurrency** is a property of **how your program is structured**: it is composed of independently-progressing tasks whose execution can interleave. Concurrency is about *composition*, and it is meaningful even on a machine with exactly one core.
- **Parallelism** is a property of **how your program executes**: two or more instructions are literally retiring in the same instant, on different physical execution units. Parallelism requires hardware that can do more than one thing at once.

A single-core machine running an event loop that juggles 10,000 open sockets is **maximally concurrent and completely non-parallel**. A program that hands one enormous matrix multiply to sixteen cores is **parallel and barely concurrent** — it has one task, chopped up. The two are orthogonal.

This distinction is not pedantry; it decides what you should reach for:

- Your problem is **waiting** (195 ms of it, per request). Waiting is not work. You do not need a second core to wait on two sockets at once — you need a *structure* that lets one core register interest in both. That is concurrency, and it is what threads, event loops, and `async`/`await` provide.
- Your problem is **computation** (resizing images, parsing 400 MB of JSON, hashing passwords). Now you genuinely need more execution units running at the same instant. That is parallelism, and it is what multiple processes and multiple cores provide.

Reaching for the wrong one is the classic beginner mistake in both directions: adding threads to a CPU-bound Python workload and getting a 1.0x speedup, or spawning a process per connection to serve 10,000 idle websockets and running out of memory. Which brings us to the classification that decides everything.

### CPU-bound or I/O-bound: the classification that picks your tool

Every workload sits somewhere on one axis, and you find where by asking a single question: **during this operation, is the CPU executing my instructions, or is it available to do something else?**

- **CPU-bound**: the processor is the bottleneck. It is retiring your instructions continuously. Compression, encryption, image transforms, JSON parsing, sorting, template rendering, `bcrypt`. Making this faster means *more cores* (parallelism) or *fewer instructions* (a better algorithm).
- **I/O-bound**: the processor is idle, waiting for something outside itself to answer. Database queries, HTTP calls to other services, disk reads, cache lookups, message publishes, DNS. Making this faster means *overlapping the waits* (concurrency), because there is no CPU work to speed up.

Our endpoint is 97.5% I/O-bound. Almost every request-serving backend service is. And the reason is not a property of your code — it is a property of the hardware, and it is enormous:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 410" width="100%" style="max-width:840px" role="img" aria-label="A logarithmic ladder of latency costs from an L1 cache reference at 1 nanosecond to a cross-region network round trip at 100 milliseconds, spanning eight decades, with each cost also rescaled so that an L1 hit takes one second: main memory becomes 1.7 minutes, an NVMe read 1.2 days, a same-datacenter round trip 5.8 days, and a cross-region round trip 3.2 years."> <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Eight decades of latency, and where your 200 ms actually goes</text> <rect x="16" y="44" width="848" height="310" rx="12" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.6"/> <g fill="currentColor" font-size="9" font-weight="700" opacity="0.65"> <text x="30" y="68">operation</text> <text x="250" y="68" text-anchor="end">real cost</text> <text x="676" y="68">if an L1 hit took 1 second</text> </g> <g stroke="currentColor" stroke-opacity="0.18" stroke-width="1">
  <path d="M262 76 L 262 324"/><path d="M311.75 76 L 311.75 324"/><path d="M361.5 76 L 361.5 324"/><path d="M411.25 76 L 411.25 324"/><path d="M461 76 L 461 324"/><path d="M510.75 76 L 510.75 324"/><path d="M560.5 76 L 560.5 324"/><path d="M610.25 76 L 610.25 324"/><path d="M660 76 L 660 324"/> </g> <path d="M668 76 L 668 324" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.3"/> <g stroke-width="1.6"> <rect x="262" y="84" width="4" height="16" fill="#0fa07f" stroke="#0fa07f"/> <rect x="262" y="126" width="30" height="16" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
  <rect x="262" y="168" width="100" height="16" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/> <rect x="262" y="210" width="249" height="16" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/> <rect x="262" y="252" width="284" height="16" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/> <rect x="262" y="294" width="398" height="16" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/> </g> <g fill="currentColor" font-size="10.5"> <text x="30" y="97">L1 cache reference</text><text x="250" y="97" text-anchor="end" opacity="0.85">1 ns</text>
  <text x="30" y="139">L2 cache reference</text><text x="250" y="139" text-anchor="end" opacity="0.85">4 ns</text> <text x="30" y="181">main memory reference</text><text x="250" y="181" text-anchor="end" opacity="0.85">100 ns</text> <text x="30" y="223">NVMe SSD random read</text><text x="250" y="223" text-anchor="end" opacity="0.85">100 µs</text> <text x="30" y="265">same-datacenter round trip</text><text x="250" y="265" text-anchor="end" opacity="0.85">500 µs</text> <text x="30" y="307">cross-region round trip</text><text x="250" y="307" text-anchor="end" opacity="0.85">100 ms</text> </g>
  <g font-size="11" font-weight="700"> <text x="676" y="97" fill="#0fa07f">1 second</text> <text x="676" y="139" fill="#0fa07f">4 seconds</text> <text x="676" y="181" fill="#0fa07f">1.7 minutes</text> <text x="676" y="223" fill="#7c5cff">1.2 days</text> <text x="676" y="265" fill="#3553ff">5.8 days</text> <text x="676" y="307" font-size="12.5" fill="#d64545">3.2 years</text> </g> <g fill="currentColor" font-size="8" opacity="0.6" text-anchor="middle">
  <text x="262" y="340">1 ns</text><text x="311.75" y="340">10 ns</text><text x="361.5" y="340">100 ns</text><text x="411.25" y="340">1 µs</text><text x="461" y="340">10 µs</text><text x="510.75" y="340">100 µs</text><text x="560.5" y="340">1 ms</text><text x="610.25" y="340">10 ms</text><text x="660" y="340">100 ms</text> </g> <text x="440" y="376" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">A cross-region round trip costs 100,000,000x an L1 hit. Your 195 ms of waiting is ~390 same-datacenter round trips.</text>
  <text x="440" y="396" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">You do not optimize your way across eight decades. You overlap them with other work.</text> </g> </svg>
```

The left half of that chart is the memory hierarchy you met in Phase 0, Lesson 6. The right half is the network. The gap between them is **eight orders of magnitude** — and human brains are catastrophically bad at eight orders of magnitude, which is why the second column exists.

Rescale the whole ladder so that one L1 cache hit takes **one second**, a duration you can actually feel. Then reading from main memory takes **1.7 minutes**. Reading a random block from a fast NVMe SSD takes **1.2 days**. A round trip to a service in the same datacenter takes **5.8 days**. And a round trip to another continent takes **3.2 years**.

Sit with the last one. Your process issues that call and then *waits three years*, in CPU terms, doing nothing, while a fully capable machine sits underneath it with nothing to do. Every single technique in the rest of this phase exists to fill those three years with other people's requests.

This also tells you when concurrency will *not* help. If your endpoint spends 190 ms hashing a password with `bcrypt` and 10 ms on I/O, no amount of `async` will save you: the CPU is genuinely busy, there is no idle time to reclaim, and adding concurrency to a saturated CPU just adds queueing. Measure first. `CPU time / wall time` per request is the whole diagnostic: near 1.0 means CPU-bound, near 0 means I/O-bound. Ours is **0.025**.

### Little's Law: L = λW

In 1961, John Little proved the most useful equation in capacity planning, in *Operations Research* 9(3). It relates the three quantities you have just met:

```text
L = λ × W

  L  average number of requests IN THE SYSTEM  (concurrency, in flight)
  λ  average ARRIVAL rate, = throughput in steady state  (requests/second)
  W  average TIME a request spends in the system  (seconds)
```

Derive it in one image and you will never forget it. Draw a chart of "number of requests currently in the system" against time. That area under the curve can be sliced two ways:

- **Vertically**, by time: each slice is `L(t) dt`. Total area over a window `T` = `L̄ × T`.
- **Horizontally**, by request: each request contributes a bar as long as its own time in the system. Total area = `N × W̄`, where `N` is the number of requests.

Same area, two slicings. So `L̄ × T = N × W̄`, and since `N / T` is throughput `λ`, you get `L = λ × W`. That is the whole proof.

The astonishing part is what the proof does **not** assume. It says nothing about the arrival distribution, the service-time distribution, the queueing discipline (FIFO, LIFO, priority, random), the number of servers, or whether requests overtake one another. Little's Law is not a model that might fit your system. It is an **accounting identity** that already holds, whether you know it or not, in any system that is not growing without bound. The Build It confirms it to every printed digit across four different queues.

Three ways engineers actually use it:

**1. Derive concurrency you cannot observe.** You know λ (from your metrics) and W (from your metrics), and you want to know how many requests are in flight — a number most systems do not export. At **800 req/s** with a **250 ms** p50: `L = 800 × 0.250 = 200 concurrent requests`. If your web server is configured with 50 workers, you are structurally incapable of serving 800 req/s: 50 workers × (1 / 0.250 s) = **200 req/s**, and the other 600 requests per second are queueing or being refused. Nobody had to tell you the config was wrong; the arithmetic did.

**2. Size a pool.** Same numbers, run backwards. To serve λ = 800 req/s at W = 250 ms you need `L = 200` slots, plus headroom for burst and for W getting worse. At 1.5x: **300 slots**. And note carefully what that does *not* say about CPU: the CPU you need is `λ × CPU-per-request = 800 × 5 ms = 4.0 cores`. **Threads are for waiting; cores are for working.** These are two independent sizing calculations, and conflating them is why "one worker per core" is such a persistent and expensive piece of folklore for I/O-bound services.

**3. Predict what a slow dependency will do to you.** Your pool is fixed at 200. Your ceiling is `200 / W`. At W = 250 ms that is 800 req/s. If the payments API degrades and W rises to **400 ms**, your ceiling drops to **500 req/s** — a **38% capacity loss with no code change and no traffic change**. If W hits 1 second, you are down to **200 req/s**: a **75% loss**. This is the mechanism behind most "cascading failure" postmortems. A dependency got slower, W rose, L rose past the pool size, the pool saturated, and a service that was nowhere near CPU-limited started returning 503s.

> **The trap in production:** the units must match, and "the system" must be the same system in all three terms. If λ is measured at the load balancer but W is measured inside the application (excluding queue time at the LB), the L you compute is not the L that matters. Pick a boundary, measure both sides of it consistently, and be explicit about whether W includes queue wait.

### Utilization and the knee

**Utilization** (**ρ**, rho) is the fraction of time your bottleneck resource is busy: `ρ = λ / capacity`. It looks like a budget — 50% used, 50% left — and that intuition is completely wrong.

Here is why. When a request arrives and the server is busy, it queues. The busier the server, the more likely that is, and the longer the queue it joins. For the simplest useful model — an **M/M/1 queue**, meaning random (Poisson) arrivals, random (exponential) service times, and one server — the mean time in system is:

```text
W = S / (1 − ρ)

  S  service time: how long one request takes with the server all to itself
  ρ  utilization, between 0 and 1
```

That `(1 − ρ)` in the denominator is the whole story, because it goes to zero. The Build It computes this table and then confirms the top of it against a simulated queue:

```text
   rho   W/S    W formula   W simulated
  0.10   1.1x     22.2 ms       22.2 ms
  0.50   2.0x     40.0 ms       40.2 ms
  0.80   5.0x    100.0 ms      100.8 ms
  0.90  10.0x    200.0 ms      204.7 ms
  0.95  20.0x    400.0 ms            —
  0.99 100.0x   2000.0 ms            —
```

At **50% utilization** a request already takes **twice** its service time — half of its life is spent waiting behind someone else. At **90%**, **ten times**. At **99%**, **one hundred times**. A 20 ms operation becomes a 2-second operation, and not one line of your code got slower.

Now read the deltas, because that is where the danger lives. Going from **80% to 90%** utilization is **12.5% more work** and **+100% latency**. Going from **90% to 99%** is **10% more work** and **+900% latency**. The last few percent of a resource are the most expensive thing you can buy, and they are usually bought accidentally — by a traffic spike, a slow dependency, a retry storm, or a deploy that removes half your pods for thirty seconds.

So when someone says *"the servers are only 80% busy, we have plenty of headroom"*, the correct reply is: at 80% you are **already** paying a 5x latency multiplier, and the next 10% of traffic will double it again. Utilization is not a fuel gauge. It is a latency multiplier, and it is non-linear in exactly the region where dashboards look calm.

Two caveats worth having, because this formula gets over-applied. First, M/M/1 assumes randomness; perfectly regular arrivals and constant service times queue much less, and burstier-than-Poisson arrivals queue much more. Second, more servers flatten the knee — the same total capacity split across 16 servers absorbs bursts far better than one, which is exactly what the Build It's M/M/16 row shows. The *shape* is universal; the exact multiplier depends on your variability. What never changes is that the curve has a knee and that the knee is well below 100%.

### Amdahl's Law and the Universal Scalability Law

So: overlap the waiting, add workers, done? No. There are two ceilings, and they bite in that order.

**Amdahl's Law** (Amdahl, *AFIPS Conference Proceedings* 30, 1967) says that if a fraction **s** of your work is inherently **serial** — it cannot be split, no matter how many workers you have — then your speedup with N workers is capped:

```text
speedup(N) = 1 / (s + (1 − s)/N)          and as N → ∞,  speedup → 1/s
```

The second half is the part that hurts. **A 5% serial fraction caps you at 20x, forever.** Not 20x on today's hardware — 20x on any hardware that will ever exist. The Build It prints the whole table; the row that matters:

```text
serial      N=2      N=8     N=32    N=128   N=1024    N=inf
  5.0%     1.9x     5.9x    12.5x    17.4x    19.6x    20.0x
```

One thousand and twenty-four workers deliver **19.6x** against a ceiling of 20x. You bought 1,024 workers and got **1.9% efficiency**. The serial 5% — a global lock, a single-threaded coordinator, a sequential startup phase, a shared counter — swallowed everything else.

But Amdahl is the *optimistic* law. It says adding workers has diminishing returns; it never says adding workers makes things **worse**. Real systems get worse, and every engineer has watched it happen. The **Universal Scalability Law** (Gunther, *Guerrilla Capacity Planning*, Springer 2007) explains why, by adding a second penalty term:

```text
X(N) = N / (1 + σ(N − 1) + κN(N − 1))

  σ  CONTENTION — serialized work: locks, queues, the single writer. This is Amdahl.
  κ  COHERENCY  — the cost of workers agreeing with each other: cache-line
                  invalidation, lock handoffs, consensus rounds, gossip.
                  It grows as N², because every pair of workers must agree.
```

That `κN(N−1)` term is quadratic, so it eventually beats the linear gain in the numerator, and throughput **turns over and falls**. With realistic parameters (σ = 0.05, κ = 0.0001) the Build It finds the peak by brute force and confirms it against the closed form `N* = √((1−σ)/κ)`:

```text
  workers     Amdahl        USL
       16      9.14x      9.02x
       97     16.72x     14.41x  <- USL peak
      512     19.28x      9.71x
     1024     19.64x      6.53x
```

Peak throughput at **97 workers**. At 1,024 workers you get **6.53x** — *worse than the 9.02x you had with 16*. You added 64 times more workers and ended up slower than where you started. Amdahl's curve for the same σ never dips; it flattens at 19.6x and stays there. Only the coherency term explains a system that degrades under scale-out, and it is the reason "just add more pods" sometimes makes an incident worse.

> **The trap in production:** κ is usually invisible in your code. It hides in a shared database row every worker updates, a distributed lock, a cache every worker invalidates, a leader every worker heartbeats to. The symptom is diagnostic and unmistakable: **throughput falls as you add capacity.** When you see that, stop adding capacity and go find what the workers are agreeing about.

### A map of the rest of the phase

Everything after this lesson is one of these arithmetic terms, attacked directly. **Threads and processes** (Lesson 2) let one program have many independently-blocking flows, which is how you turn L = 1 into L = 200 — and processes are also how you get real parallelism for the CPU-bound half. **Non-blocking I/O and event loops** get you the same L without one OS thread per in-flight request, because 10,000 threads is a memory problem long before it is a throughput one. **`async`/`await`** makes that structure readable instead of a callback graph. **Locks and atomics** are what you need once concurrent flows touch the same data — and they are also where σ and κ come from, so every lock you add pulls the USL peak leftward. **Backpressure and bounded queues** are how you refuse to let L grow past what your pool can serve, which is the only real defense against the knee. And **measurement and load testing** are how you find your actual ρ, your actual W, and your actual peak instead of guessing.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 408" width="100%" style="max-width:840px" role="img" aria-label="On the left, response time divided by service time plotted against utilization, flat until about 70 percent and then rising steeply through 5x at 80 percent, 10x at 90 percent and 100x at 99 percent, with three simulated points sitting on the curve. On the right, a map of the rest of Phase 8 pairing each symptom — waiting, idle cores, thread exhaustion, callback complexity, data races, unbounded queues, and negative scaling — with the technique that addresses it."> <defs>
  <marker id="l01-up" markerWidth="9" markerHeight="9" refX="4.5" refY="7" orient="auto"><path d="M4.5,0 L9,8 L0,8 Z" fill="#d64545"/></marker> <marker id="l01-lead" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker> </defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The knee, and the map of everything that comes next</text>
  <rect x="16" y="44" width="440" height="320" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="2"/> <rect x="472" y="44" width="392" height="320" rx="12" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="2"/> <text x="222" y="68" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">RESPONSE TIME vs UTILIZATION:  W = S/(1−ρ)</text> <text x="668" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">the rest of Phase 8: which pain, which tool</text> <g stroke="currentColor" stroke-opacity="0.18" stroke-width="1" fill="none">
  <path d="M62 322.3 L 430 322.3"/><path d="M62 281.3 L 430 281.3"/><path d="M62 212.8 L 430 212.8"/><path d="M62 76 L 430 76"/> </g> <g fill="none" stroke="currentColor" stroke-opacity="0.55" stroke-width="1.5"> <path d="M62 76 L 62 336 L 434 336"/> <path d="M243 336 L 243 342"/><path d="M351.6 336 L 351.6 342"/><path d="M387.8 336 L 387.8 342"/><path d="M420.4 336 L 420.4 342"/> </g> <g fill="currentColor" font-size="8.5" opacity="0.7" text-anchor="end"> <text x="56" y="325.5">2x</text><text x="56" y="284.5">5x</text><text x="56" y="216">10x</text><text x="56" y="79">20x</text> </g>
  <g fill="currentColor" font-size="8.5" opacity="0.7" text-anchor="middle"> <text x="62" y="354">0</text><text x="243" y="354">50%</text><text x="351.6" y="354">80%</text><text x="387.8" y="354">90%</text><text x="420.4" y="354">99%</text> </g> <path d="M62 336 L 98.2 334.5 L 134.4 332.6 L 170.6 330.1 L 206.8 326.9 L 243 322.3 L 279.2 315.5 L 315.4 304.1 L 333.5 295 L 351.6 281.3 L 369.7 258.5 L 380.6 235.7 L 387.8 212.8 L 395 178.7 L 402.3 121.7 L 405.9 76 L 408 60" fill="none" stroke="#d64545" stroke-width="2.4" stroke-linejoin="round" marker-end="url(#l01-up)"/>
  <g fill="#e0930f" stroke="#e0930f" stroke-width="1.2"> <circle cx="243" cy="322.2" r="3.6"/><circle cx="351.6" cy="280.7" r="3.6"/><circle cx="387.8" cy="209.6" r="3.6"/> </g> <path d="M300 268 L 344 278" fill="none" stroke="currentColor" stroke-width="1.2" stroke-opacity="0.7" marker-end="url(#l01-lead)"/> <text x="296" y="265" text-anchor="end" font-size="9.5" font-weight="700" fill="#e0930f">the knee</text> <g fill="currentColor"> <text x="80" y="112" font-size="10.5" font-weight="700">a queue is a latency multiplier</text> <text x="80" y="134" font-size="10" opacity="0.9">ρ = 0.50  →  W =   2.0 × S</text>
  <text x="80" y="152" font-size="10" opacity="0.9">ρ = 0.80  →  W =   5.0 × S</text> <text x="80" y="170" font-size="10" opacity="0.9">ρ = 0.90  →  W =  10.0 × S</text> <text x="80" y="188" font-size="10" font-weight="700" fill="#d64545">ρ = 0.99  →  W = 100.0 × S</text> <text x="80" y="212" font-size="10" font-weight="700" fill="#d64545">80% → 90% busy = +12.5% work,</text> <text x="80" y="228" font-size="10" font-weight="700" fill="#d64545">+100% latency</text> <text x="80" y="252" font-size="9" opacity="0.75">line = S/(1−ρ)   ● = M/M/1 simulation</text> </g> <g stroke-width="0">
  <rect x="484" y="90" width="8" height="8" fill="#0fa07f"/><rect x="484" y="127" width="8" height="8" fill="#0fa07f"/> <rect x="484" y="164" width="8" height="8" fill="#3553ff"/><rect x="484" y="201" width="8" height="8" fill="#3553ff"/> <rect x="484" y="238" width="8" height="8" fill="#e0930f"/><rect x="484" y="275" width="8" height="8" fill="#e0930f"/> <rect x="484" y="312" width="8" height="8" fill="#d64545"/> </g> <g fill="currentColor" font-size="9.5"> <text x="500" y="97" opacity="0.8">195 ms of every request is spent waiting</text>
  <text x="500" y="112" font-size="10" font-weight="700" fill="#0fa07f">threads &amp; processes — overlap the wait</text> <text x="500" y="134" opacity="0.8">one core busy, fifteen sitting idle</text> <text x="500" y="149" font-size="10" font-weight="700" fill="#0fa07f">processes &amp; the GIL — real parallelism</text> <text x="500" y="171" opacity="0.8">10k connections would need 10k threads</text> <text x="500" y="186" font-size="10" font-weight="700" fill="#3553ff">non-blocking I/O &amp; event loops</text> <text x="500" y="208" opacity="0.8">callbacks everywhere, nothing readable</text>
  <text x="500" y="223" font-size="10" font-weight="700" fill="#3553ff">async/await — concurrency you can read</text> <text x="500" y="245" opacity="0.8">two workers updated the same row</text> <text x="500" y="260" font-size="10" font-weight="700" fill="#e0930f">locks, atomics &amp; race conditions</text> <text x="500" y="282" opacity="0.8">the queue grew until the pod was killed</text> <text x="500" y="297" font-size="10" font-weight="700" fill="#e0930f">backpressure &amp; bounded queues</text> <text x="500" y="319" opacity="0.8">we added workers and it got slower</text>
  <text x="500" y="334" font-size="10" font-weight="700" fill="#d64545">Amdahl, the USL &amp; measuring for real</text> </g> <text x="440" y="390" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Utilization is a latency multiplier, not a budget. Every lesson after this one buys back part of the multiplier.</text> </g> </svg>
```

## Build It

Five sections, and four of them are arguments rather than demonstrations — each one takes a claim from above and either measures it or confirms it against a simulation. Standard library only, every random number generator seeded, whole thing under five seconds.

Start with the workload, because everything hangs off it. The point is to burn **real CPU** and do **real waiting**, so the split is measured rather than declared. `time.thread_time()` is per-thread CPU time, so the burn consumes the same CPU whether or not another thread is competing for the interpreter:

```python
CPU_WORK = (0.0025, 0.0015, 0.0010)   # parse+authorize, shape rows, serialize
IO_WAIT = (0.120, 0.075)              # database query 120 ms, payments API 75 ms

def burn(seconds: float) -> None:
    """Occupy a CPU for `seconds` of *thread* CPU time — real work, not a sleep."""
    end = time.thread_time() + seconds
    while time.thread_time() < end:
        pass

def handle_request() -> None:
    """One request: three bursts of CPU separated by two blocking waits."""
    burn(CPU_WORK[0]); time.sleep(IO_WAIT[0])     # blocked on the database
    burn(CPU_WORK[1]); time.sleep(IO_WAIT[1])     # blocked on the payments API
    burn(CPU_WORK[2])
```

Section 1 runs six of those serially and six through a `ThreadPoolExecutor`, timing both with `perf_counter()` (wall clock) and `process_time()` (CPU across all threads). Two clocks is the whole trick: the ratio between them *is* the utilization.

Sections 2 and 3 need a queue, so build one — a first-come-first-served **M/M/c** simulator with a virtual clock. The min-heap holds each server's next-free time, so `heappop` gives you the server that frees up soonest, which is exactly FCFS across `c` identical servers:

```python
def simulate_mmc(lam, mu, c, n, seed):
    """FCFS M/M/c queue. Returns (throughput, W_mean, L_time_average, utilization)."""
    rng = random.Random(seed)
    free = [0.0] * c                  # min-heap of per-server next-free times
    heapq.heapify(free)
    clock = 0.0
    for _ in range(n):
        clock += rng.expovariate(lam)             # next Poisson arrival
        earliest = heapq.heappop(free)
        start = clock if clock > earliest else earliest
        done = start + rng.expovariate(mu)
        heapq.heappush(free, done)
        arrivals.append(clock); departures.append(done)
```

`L` is then measured **independently** of `W` by integrating the number in system over the whole run — the vertical slicing from the derivation, made literal:

```python
    events = [(t, 1) for t in arrivals] + [(t, -1) for t in departures]
    events.sort()
    area, level, prev = 0.0, 0, span_start
    for t, delta in events:
        area += level * (t - prev)        # rectangle: how many were here, for how long
        prev = t
        level += delta
    #   L = area / horizon      W = mean(departure - arrival)      lambda = n / horizon
```

Because Little's Law is an identity, `λ × W` and `L` will agree to every digit — which proves the arithmetic but not the *queue*. So the code also computes the analytic answer from the **Erlang C** formula and compares, which is a genuine independent check that the simulator is modelling a real M/M/c system:

```python
def erlang_c_L(lam, mu, c):
    """Steady-state mean number in an M/M/c system, from the Erlang C formula."""
    a = lam / mu                       # offered load in erlangs
    rho = a / c
    head = sum(a ** k / math.factorial(k) for k in range(c))
    tail = a ** c / (math.factorial(c) * (1 - rho))
    return (tail / (head + tail)) * rho / (1 - rho) + a
```

Section 4 needs millions of customers to converge, so it drops the event list for **Lindley's recursion** — the waiting time of customer *k+1* is the waiting time of customer *k*, plus their service, minus the gap until the next arrival, floored at zero. One line, no data structures, and it is exact for FCFS single-server queues:

```python
    for k in range(n):
        s = expo(mu)
        if k >= warm:                  # discard the first 20% while the queue warms up
            total += wq + s            # sojourn = queue wait + own service
            counted += 1
        wq = wq + s - expo(lam)
        if wq < 0.0:
            wq = 0.0
```

And section 5 is two closed forms plus a brute-force search for the USL peak, so the `N* = √((1−σ)/κ)` prediction is checked rather than trusted:

```python
def usl(workers, sigma, kappa):
    """Universal Scalability Law: contention (sigma) plus coherency (kappa)."""
    n = float(workers)
    return n / (1.0 + sigma * (n - 1.0) + kappa * n * (n - 1.0))

peak_n = max(range(1, 4001), key=lambda k: usl(k, sigma, kappa))
```

The whole file is [`code/concurrency_math.py`](code/concurrency_math.py). Run it:

```bash
python3 concurrency_math.py
```

```console
== 1 · WHERE THE TIME ACTUALLY GOES ==
  one request = 5.0 ms CPU + 195.0 ms waiting = 200.0 ms  (2.5% CPU, 97.5% idle)
  6 requests, ONE at a time : wall  1.211 s  cpu 0.030 s  ->   4.96 req/s
      CPU busy  2.51% of one core = 0.157% of a 16-core machine
  6 requests, 6 IN FLIGHT   : wall  0.215 s  cpu 0.033 s  ->  27.89 req/s   (5.6x)
      same work, same CPU, 1.00 s of waiting overlapped away

  projection: N requests in flight, each 200 ms with 5 ms of CPU
   in flight N    throughput    latency   cores busy     % of 16
             1         5.0/s     200 ms        0.025        0.2%
             8        40.0/s     200 ms        0.200        1.2%
            64       320.0/s     200 ms        1.600       10.0%
           256      1280.0/s     200 ms        6.400       40.0%
           640      3200.0/s     200 ms       16.000      100.0%  <- CPU saturated
          1280      3200.0/s     400 ms       16.000      100.0%  <- CPU saturated: past here N only adds queueing
  the CPU ceiling is 16 cores / 5 ms = 3200 req/s,
  and reaching it needs L = 3200/s x 0.200 s = 640 requests in flight (Little's Law, section 3)

  why waiting dominates — the same clock, scaled so L1 = 1 second
  operation                           real      if L1 took 1 second
  L1 cache reference                  1 ns                 1 second
  L2 cache reference                  4 ns                4 seconds
  main memory reference             100 ns              1.7 minutes
  NVMe SSD random read              100 us                 1.2 days
  same-datacenter round trip        500 us                 5.8 days
  cross-region round trip           100 ms                3.2 years
  a cross-region round trip costs 100,000,000x an L1 hit. You do not
  optimize your way past that. You overlap it with other work.

== 2 · LATENCY AND THROUGHPUT ARE INDEPENDENT DIALS ==
  three implementations of the same endpoint, simulated as M/M/c queues
  config                   capacity   W unloaded  W at 80% load       1/W
  A  1 worker  x 10 ms      100.0/s       10.6 ms         50.5 ms    94.8/s
  B 20 workers x 40 ms      500.0/s       39.7 ms         42.7 ms    25.2/s
  C  4 workers x 25 ms      160.0/s       25.1 ms         43.1 ms    39.8/s

  A has 2.4x better latency than C and 5.0x LESS throughput than B.
  C -> B improves throughput 3.1x while making latency 1.6x WORSE.
  B: 1/W = 25.2/s but capacity = 500.0/s — off by 20x, which is exactly its worker count.
  throughput = concurrency / latency. Not 1 / latency. That is Little's Law.

== 3 · LITTLE'S LAW: L = lambda x W, VERIFIED THEN USED ==
  queue             lambda(meas)    W(meas)  lambda x W   L(meas)  L(theory)     err
  M/M/1 rho=.50          50.01/s   19.85 ms       0.993     0.993      1.000   -0.7%
  M/M/1 rho=.85          84.95/s   66.50 ms       5.649     5.649      5.667   -0.3%
  M/M/4 rho=.70          27.98/s  134.76 ms       3.771     3.771      3.800   -0.8%
  M/M/16 rho=.90        143.77/s  135.37 ms      19.463    19.463     19.722   -1.3%
  lambda x W and L(meas) agree to every printed digit — that is not luck.
  L is the area under the in-system curve sliced by TIME; sum(W) is the same
  area sliced by REQUEST. Little's Law is an accounting identity, and the
  Erlang-C column is the independent check that the queue itself is right.

  using it forward — three questions you get asked at work
  (a) how many requests are in flight at 800 req/s and 250 ms?
      L = 800 x 0.250 = 200 concurrent requests. A 50-thread pool serves 200/s, not 800.
  (b) how big should the pool be? L x headroom = 200 x 1.5 = 300 slots.
      CPU needed is separate: 800/s x 5 ms = 4.0 cores. Threads are for waiting, cores are for working.
  (c) the pool is 200 and W has risen to 250 ms. Ceiling = 800 req/s.
      if a dependency slows W to 400 ms the same pool caps you at 500 req/s — a 38% capacity loss with no code change.
      if a dependency slows W to 1000 ms the same pool caps you at 200 req/s — a 75% capacity loss with no code change.

== 4 · THE UTILIZATION KNEE: W = S / (1 - rho) ==
  service time S = 20 ms; W is the time a request spends in the system
      rho   W/S formula   W formula   W simulated  sim/formula
    0.100          1.1x      22.2 ms        22.2 ms        1.00
    0.300          1.4x      28.6 ms        28.6 ms        1.00
    0.500          2.0x      40.0 ms        40.2 ms        1.00
    0.700          3.3x      66.7 ms        67.0 ms        1.00
    0.800          5.0x     100.0 ms       100.8 ms        1.01
    0.900         10.0x     200.0 ms       204.7 ms        1.02
  the simulation confirms the formula wherever it converges; past rho=0.9
  a queue takes longer to reach steady state than it does to hurt you:
    0.950         20.0x     400.0 ms           —  (formula only)
    0.990        100.0x    2000.0 ms           —  (formula only)
    0.995        200.0x    4000.0 ms           —  (formula only)
  going 80% -> 90% busy costs +100% latency for +12.5% work.
  going 90% -> 99% busy costs +900% latency for +10% work.

== 5 · AMDAHL'S CEILING AND THE USL'S CLIFF ==
  Amdahl — speedup vs workers, by serial fraction
    serial      N=2      N=8     N=32    N=128   N=1024    N=inf
     0.1%     2.0x     7.9x    31.0x   113.6x   506.2x  1000.0x
     1.0%     2.0x     7.5x    24.4x    56.4x    91.2x   100.0x
     5.0%     1.9x     5.9x    12.5x    17.4x    19.6x    20.0x
    25.0%     1.6x     2.9x     3.7x     3.9x     4.0x     4.0x
  5% serial caps you at 20x. 1024 workers buys 19.6x — 1.9% efficiency.

  USL — sigma=0.05 (contention), kappa=0.0001 (coherency)
    workers     Amdahl        USL
          1      1.00x      1.00x
          4      3.48x      3.47x
         16      9.14x      9.02x
         64     15.42x     14.06x
         97     16.72x     14.41x  <- USL peak
        256     18.62x     12.62x
        512     19.28x      9.71x
       1024     19.64x      6.53x
       2048     19.82x      3.92x
  peak measured at N=97; sqrt((1-sigma)/kappa) predicts 97.5. Throughput at
  N=1024 is 6.53x — worse than N=16's 9.02x. Amdahl says 19.64x and never
  goes down; only the coherency term explains a system that gets slower.

  (total runtime 4.6 s)
```

**Read the numbers.** Section 1 is the lesson's thesis, measured rather than asserted. Six requests serially take **1.211 seconds of wall clock and 0.030 seconds of CPU**. Six requests concurrently take **0.215 seconds of wall clock and 0.033 seconds of CPU** — the CPU number barely moved, because the work never changed. What changed is that **1.00 second of pure waiting got overlapped away**, and throughput went from 4.96 req/s to 27.89 req/s: a **5.6x improvement from a structural change with no additional hardware**. The utilization line is the one to internalize: **2.51% of one core**, which on the 16-core machine you are actually billed for is **0.157%**. Nearly sixteen cores, warm and idle, for the entire 1.2 seconds.

The projection table then walks the same workload up the concurrency axis and finds the other end of it. Every extra request in flight buys 5 req/s until the CPU actually runs out, and the CPU runs out at `16 cores ÷ 5 ms = 3,200 req/s` — which needs `L = 3,200 × 0.200 = 640 requests in flight`. That is a 640x span between what the serial server does and what the same hardware can do, and it is why "just buy a bigger box" is such an expensive answer. Note the last row: at 1,280 in flight, throughput is still 3,200/s but latency has **doubled to 400 ms**. Past saturation, added concurrency does not add throughput; it only adds queue. That is the knee arriving from a different direction, and it is exactly what backpressure exists to prevent.

**Section 2 kills the reciprocal intuition.** Three implementations, all simulated as real queues. Config A is the fastest per request (10.6 ms) and the slowest overall (100/s). Config B is the slowest per request (39.7 ms) and the fastest overall (500/s). And B's `1/W` is **25.2/s** against a real capacity of **500/s** — wrong by exactly **20x, its worker count**, because the missing factor is L. Look also at the "W at 80% load" column, which is the knee sneaking in: under load A's latency degrades from 10.6 ms to **50.5 ms** (a 4.8x multiplier, since one server has nowhere to absorb a burst) while B's barely moves, from 39.7 to **42.7 ms**. The configuration with the *worst* unloaded latency has the *best* loaded latency. This is why benchmarks run on an idle box tell you almost nothing.

**Section 3 is the one worth slowing down for.** Four different queues, from one server at 50% load to sixteen servers at 90%, and in every case `λ × W` equals the independently-measured `L` to every printed digit — 0.993, 5.649, 3.771, 19.463. Not approximately. *Identically.* That is not a coincidence and not a fitted model; it is the two ways of slicing the same area, and it is why Little's Law holds for your system too, whatever your system is. The `L(theory)` column, computed from Erlang C, lands within **1.3%** across all four, confirming the simulator is a real M/M/c queue rather than something that merely satisfies an identity. Then the three worked applications: 800 req/s at 250 ms **is** 200 concurrent requests, so a 50-thread pool physically cannot exceed **200 req/s**; sizing that pool means 200 × 1.5 = **300 slots** while the CPU sizing is a completely separate **4.0 cores**; and if a dependency drags W from 250 ms to 1 second, that same pool's ceiling collapses from 800 req/s to **200 req/s — a 75% capacity loss with nothing deployed and no traffic change.**

**Section 4 confirms the knee instead of asserting it.** The simulated column tracks `S/(1−ρ)` to within 2% everywhere it converges: 40.2 ms against a predicted 40.0 at ρ = 0.5, **100.8 against 100.0 at ρ = 0.8**, 204.7 against 200.0 at ρ = 0.9. The formula is real. The rows past 0.9 are formula-only for an honest reason worth naming: a queue at ρ = 0.99 takes far longer to reach steady state than a simulation of that length can reach, and printing a badly-converged number would be worse than printing none. The economics are in the last two lines. **+12.5% work costs +100% latency at the 80→90 step; +10% work costs +900% at the 90→99 step.** There is no version of capacity planning where you run a queue at 99% on purpose.

**Section 5 sets up the last third of the phase.** The Amdahl table shows a 5% serial fraction letting 1,024 workers reach **19.6x of a 20x ceiling — 1.9% efficiency**, and a 25% serial fraction capping you at 4.0x no matter what you spend. Then the USL columns diverge from Amdahl exactly where real systems do. Throughput peaks at **97 workers (14.41x)**, against a closed-form prediction of **97.5** — the brute-force search and the formula agree. And past the peak it *falls*: **9.71x at 512 workers, 6.53x at 1,024** — worse than the **9.02x you had at 16**. Amdahl's curve over the same σ climbs monotonically to 19.64x and never turns down, so it can never explain that shape. Only the quadratic coherency term can. When your throughput graph goes down as your pod count goes up, you are looking at κ, and no amount of additional capacity will fix it.

## Use It

There is no library for this lesson, because the arithmetic *is* the tool. What you need instead is a way to get λ, W, and ρ for **your** service, and every one of them is already in your metrics if you instrumented the four golden signals — the RED method's Rate, Errors and Duration are exactly the inputs Little's Law wants. That instrumentation is [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/), and the dashboards are [Dashboards: RED, USE & Grafana](../../09-logging-monitoring-and-observability/11-dashboards-red-and-use/).

Assuming a request counter and a duration histogram on every handler, here is the whole toolkit as queries:

```text
λ  (throughput, req/s)      rate(http_requests_total[5m])
W  (latency, seconds)       histogram_quantile(0.5,  rate(http_request_duration_seconds_bucket[5m]))
                            — and take p95/p99 too; W in Little's Law is the MEAN,
                              which is rate(..._sum[5m]) / rate(..._count[5m])
L  (concurrency, requests)  λ × W          ← the number nobody exports, derived
ρ  (utilization)            λ / capacity   where capacity = pool_size / W_service
```

Note the subtlety in W. Little's Law takes the **mean** time in system, which is `_sum / _count` on your histogram — *not* the p50 and definitely not the p99. Use the mean for the sizing arithmetic, then look at p99 separately to decide your headroom factor, because a fat tail means your L spikes far above its average.

Then the four calculations to run on Monday morning:

```python
# 1. Your real concurrency — the number your dashboards do not show you.
L = lam * W_mean                       # e.g. 800 req/s * 0.250 s = 200 in flight

# 2. Pool size. Headroom covers burst and dependency degradation; 1.5-2x is typical.
pool_size = math.ceil(L * headroom)    # 200 * 1.5 = 300 workers/connections/slots

# 3. Cores. A SEPARATE calculation — do not conflate it with the pool.
cores = lam * cpu_seconds_per_request  # 800 * 0.005 = 4.0 cores

# 4. Your ceiling at the current pool, and what a slow dependency does to it.
ceiling = pool_size / W_mean           # 300 / 0.250  = 1200 req/s
degraded = pool_size / (W_mean * 4)    # 300 / 1.000  =  300 req/s   -75%
```

Spotting the knee in a real latency graph takes about ten seconds once you know the shape. Put `rate(...)` (traffic) and your p99 on the same time axis, and look at whether they move **proportionally**. If traffic rises 10% and p99 rises 10%, you are on the flat part of the curve and you have real headroom. If traffic rises 10% and p99 rises 80%, you are past the knee and your "20% headroom" does not exist — the next 10% will roughly double you again. That divergence between a linear traffic line and a super-linear latency line is the knee, and it is visible on a dashboard long before it is visible in an alert.

Five rules that survive contact with production:

- **Classify the workload before choosing a tool.** Measure `CPU time / wall time` per request — `time.process_time()` over `time.perf_counter()`, or your APM's on-CPU breakdown. Near 1.0 is CPU-bound and wants processes and cores; near 0 is I/O-bound and wants concurrency. Ours was **0.025**. Adding threads to CPU-bound work buys nothing; adding processes to I/O-bound work costs memory and buys nothing.
- **Size the pool from Little's Law, not from core count.** "Workers = 2 × cores" is folklore inherited from CPU-bound batch jobs. For an I/O-bound service the correct answer is `λ × W × headroom`, which for our numbers is **300 slots on a machine that only needs 4 cores**. Then size the connection pool the same way for every downstream dependency, or the pool you did not size becomes your real ceiling.
- **Target 60-70% utilization on anything latency-sensitive, and treat 80% as your alerting threshold.** At 80% you are already at a 5x latency multiplier and one traffic spike from 10x. The capacity you are "wasting" between 70% and 100% is not waste; it is the entire reason your p99 is stable.
- **Never let a queue be unbounded.** An unbounded queue converts a throughput problem into a latency problem and then into an out-of-memory kill. Bound every queue, every pool, and every in-flight-request count, and shed load when the bound is hit — a fast 503 preserves the requests you can still serve. This is what backpressure means, and it is the direct application of "past saturation, more L only adds W."
- **When throughput falls as you add workers, stop adding workers.** That is the USL's κ term, and it means your workers are spending their time agreeing with each other. Go find the shared thing — a hot row, a distributed lock, a leader, a cache everybody invalidates — because more capacity will make it worse, not better.

## Think about it

1. Your service runs at 40% CPU utilization and p99 latency is climbing week over week while traffic is flat. Which term in `W = S/(1−ρ)` is moving, what resource's ρ are you actually failing to look at, and how would you find it?
2. Little's Law holds for any stable system. What does "stable" exclude, precisely — and what does the law tell you about a service whose queue is growing? Given that, is there any useful thing you can compute during the incident?
3. You are asked to cut p99 latency by 30%. List three changes that would do it, and for each one say what happens to throughput and why. Is there a version that improves both, and what would have to be true for that to exist?
4. A colleague proposes replacing your 200-thread pool with an async runtime, arguing it will "handle way more load." Under what measured conditions is that true, under what conditions does it change nothing at all, and what would you measure first to decide?
5. Amdahl's Law and the USL both take a parameter you cannot read off your code. How would you *estimate* σ and κ for a service you own, using only load-test data at several worker counts — and what would the resulting curve tell you to do differently?

## Key takeaways

- A typical request is **97.5% waiting**: 5 ms of CPU against 195 ms blocked on a database and an HTTP call. Served one at a time, that measured **4.96 req/s at 2.51% of one core = 0.157% of a 16-core machine**. Overlapping six requests moved the same work to **27.89 req/s (5.6x)** with the CPU number essentially unchanged — concurrency does not make the CPU faster, it fills the idle time the CPU was going to spend anyway.
- **Latency and throughput are independent dials, not reciprocals.** Three configurations of one endpoint measured 10.6 ms / 100 req/s, 39.7 ms / 500 req/s, and 25.1 ms / 160 req/s; one refactor improved throughput 3.1x while making latency 1.6x worse. `1/W` under-reported one config's capacity by **20x — exactly its worker count** — because the real relation is `X = L / W`. **Concurrency** is a structuring property (many things in progress, possible on one core); **parallelism** is an execution property (many things at once, needs many cores). Waiting needs the first; computation needs the second.
- **Little's Law `L = λW` is an accounting identity, not a model** — the area under "requests in system" sliced by time versus sliced by request. Four simulated queues matched `λ × W` to `L` to every printed digit and matched Erlang C within **1.3%**. Use it three ways: derive your invisible concurrency (800 req/s × 250 ms = **200 in flight**, so a 50-thread pool caps at **200 req/s**), size a pool (`L × headroom` = **300 slots**, a separate calculation from the **4.0 cores** the CPU needs), and predict degradation (W rising 250 ms → 1 s costs **75% of capacity** with no deploy).
- **Utilization is a latency multiplier, not a budget.** `W = S/(1−ρ)` was confirmed by simulation to within 2%: **2x service time at 50% busy, 5x at 80%, 10x at 90%, 100x at 99%**. The marginal cost is what kills you — **80%→90% is +12.5% work for +100% latency; 90%→99% is +10% work for +900%**. "Only 80% busy" already means a 5x multiplier and one spike from 10x.
- **Amdahl caps you and the USL turns you around.** A 5% serial fraction limits you to **20x forever** — 1,024 workers delivered **19.6x at 1.9% efficiency**. The USL's quadratic coherency term makes it worse than diminishing: throughput peaked at **97 workers (14.41x, closed form predicts 97.5)** and fell to **6.53x at 1,024 — below the 9.02x at 16 workers.** Throughput falling as capacity rises is the unmistakable signature of workers coordinating with each other, and no additional capacity fixes it.
- Get your own numbers from the RED metrics you already have: `λ = rate(requests_total)`, `W = rate(duration_sum)/rate(duration_count)` (the **mean**, not the p50), `L = λW`, `ρ = λ/capacity`. Then find the knee by plotting traffic and p99 together — when a 10% traffic rise produces an 80% p99 rise, your headroom is already gone.

Next: [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/) — the first mechanism for getting L above 1, what an OS thread actually costs, and why CPython's Global Interpreter Lock means threads buy you overlap on the 195 ms of waiting but no parallelism at all on the 5 ms of CPU.
