# Thread Pools, Work Queues & Executors

> A thread per unit of work is the fix everyone reaches for, and it fails three ways at once in production: you pay the creation cost per item, your thread count is set by your *arrival rate* instead of your capacity, and there is nowhere to put the answer. The fix inverts all three — a fixed set of workers pulling from a bounded queue, handing results back through futures. That leaves exactly two hard questions, and this lesson measures both: sweeping a real pool from 1 to 64 workers against one capacity-limited dependency, 64 workers delivered **49% of the throughput of 8** and a p99 **16x worse**; and against identical overload, an unbounded queue grew **9.3 MiB/s** with latency climbing from 38 ms to 657 ms inside one second, while a 64-slot bound held latency flat at 90 ms.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/), [Structured Concurrency](../06-structured-concurrency-and-cancellation/), [Why Concurrency?](../01-why-concurrency/)
**Time:** ~80 minutes

## The Problem

You have a request handler that needs to do four independent things — call a pricing service, hit the database, write an audit record, push a notification. Doing them one after another takes the sum of their latencies. Doing them at the same time takes the maximum. So you reach for the obvious tool:

```python
for item in work:
    threading.Thread(target=handle, args=(item,)).start()
```

This works. It works in your tests, it works in staging, it works in production for a while. Then three separate things go wrong, and they go wrong together.

**First, you pay the creation cost per item.** A thread is not a free object. It is a kernel-scheduled entity with its own stack — on Linux the default is 8 MiB of *virtual* address space reserved per thread, committed lazily as the stack grows. Creating and destroying one costs on the order of tens of microseconds, and Lesson 2 measured it. If your unit of work takes 200 microseconds, you are spending a meaningful fraction of your budget on the paperwork of doing the work.

**Second — and this is the one that takes the site down — the number of threads is set by your arrival rate, not by your capacity.** Read that loop again. Nothing in it says how many threads may exist. The number of threads is exactly the number of items that have arrived and not finished. On a normal Tuesday that is twelve. During a traffic spike, or when the downstream database gets slow so nothing finishes, it is nine thousand. Now the machine has nine thousand runnable threads, the kernel scheduler is doing an enormous amount of work choosing between them, every context switch evicts cache lines the previous thread had warmed, and the throughput of the box *falls* precisely when you needed it to rise. The system does not degrade gracefully; it collapses. And notice the causality: the load did not exceed your capacity because there was too much of it. Your capacity fell because there was too much of it.

**Third, there is nowhere to put the answer.** `Thread(target=handle)` returns `None`. There is no return value, so you invent one — a shared list, a dictionary keyed by item id, and a lock around it. Worse, there is no error path. If `handle` raises, Python's `threading.excepthook` prints a traceback to stderr and the thread dies. The code that submitted the work never finds out. It either blocks forever waiting for a result that will never arrive, or — much more commonly and much worse — carries on believing the work succeeded.

The fix inverts the whole shape. Instead of *one thread per item*, you keep a **fixed** number of long-lived threads, and give them a **bounded** queue of items to pull from. The thread count is now a property of your machine and your dependencies, decided once, rather than a property of whatever traffic showed up. The creation cost is paid once at startup instead of per item. And every submitted item gets a **future** — a small object the submitter holds that will eventually contain the result *or* the exception.

That is a thread pool. It is not a complicated object; you will build a complete one in about 150 lines. The interesting part — the part that separates people who use pools from people who operate them — is the two questions it forces you to answer, neither of which has a default that is right:

1. **How many workers?** Too few and you leave throughput on the table. Too many and you make everything slower while gaining nothing, which is much less obvious.
2. **What happens when the queue is full?** Block? Fail? Throw work away? Each is correct somewhere.

Both answers are measurable, and this lesson measures them.

## The Concept

### Anatomy of a pool

A thread pool has exactly three parts.

**A fixed set of long-lived worker threads.** Each one runs the same infinite loop: take an item off the queue, run it, record the outcome, repeat. They are created once at startup and live until shutdown. Nothing about traffic changes how many there are.

**A shared work queue.** A first-in-first-out (FIFO) structure that submitters push into and workers pull from, with the locking already handled — Python's `queue.Queue` is exactly this. Crucially it has a `maxsize`, and the whole middle of this lesson is about that one integer.

**A Future per submitted item.** When you submit work you get back an object immediately, before the work has run. Later it will hold either the return value or the exception. The submitter can ask `result()` and block until it is ready, or check `done()` and get on with something else.

That third part is not a convenience. It is what makes the pool *correct*. Trace what happens without it: a worker calls your function, your function raises `ValueError`, the exception propagates up the worker's stack, and there is nobody there — the submitter's stack is a completely separate stack in a completely separate thread. The default behaviour is to print it and continue. The Future gives the exception a *place to go*: the worker catches it and stores it, and the submitter re-raises it from `result()`. Because the exception object itself crosses the boundary, its traceback comes with it — the Build It confirms the caller receives a `ValueError` carrying **4 stack frames** from inside the worker.

The Future is also the only reason `map()` can work. Submitting ten items gives you ten futures in order; reading them in order gives you results in order, no matter which worker finished first.

### The queue is the load-bearing part

Here is the single most consequential default in every pooling library you will use: **the queue is unbounded.** Python's `concurrent.futures.ThreadPoolExecutor` uses a `SimpleQueue` with no limit. Java's `Executors.newFixedThreadPool` uses an unbounded `LinkedBlockingQueue`. Both will accept work forever.

An unbounded queue feels safe. It is the opposite. It converts overload from a *fast, visible* failure into a *slow, invisible* one.

Consider arithmetic you can do on a napkin. Your pool serves 800 items per second. Traffic arrives at 2,400 per second. The excess, 1,600 items per second, does not disappear — it accumulates. Two things grow without limit:

- **Memory.** Every queued item holds its arguments alive. A request body, a parsed payload, a database row. At 4 KiB per item and 1,600 items per second of excess, that is 6.4 MiB per second. The Build It measures **9.3 MiB/s** for a run like this, which turns a 2 GiB container into an out-of-memory (OOM) kill in about four minutes.
- **Queue time.** An item that arrives when 1,600 items are already ahead of it waits two full seconds before a worker even *looks* at it. An item arriving a second later waits four. This grows linearly, forever, and here is the part that makes it genuinely dangerous: **your latency metric probably cannot see it.** If you time your work from "worker picked it up" to "worker finished" — which is the natural place to put a timer, inside the function — you will measure a perfectly healthy 5 ms while users are waiting eight seconds. Every dashboard is green. This is why the Build It measures latency **from submit**, and why the p50 diverges from 89 ms to 354 ms between the two runs while the *work itself* took exactly 5 ms in both.

Every item still completes. They complete long after anyone cared — after the user refreshed, after the upstream caller timed out and retried (adding *more* load), after the request context that gave the work meaning has been torn down. State the rule plainly:

> **An unbounded queue is not a buffer. It is a delay line with an out-of-memory kill at the end.**

A bounded queue does something completely different. When it fills, *something must happen right now* — and whatever that something is, it is immediate, local and actionable. You find out you are overloaded at the moment you become overloaded, at the exact place where the mismatch is, rather than four minutes later via an OOM kill with no useful stack trace. Phase 6's [Backpressure, Lag & Flow Control](../../06-messaging-and-pub-sub/09-backpressure-lag-and-flow-control/) is about propagating that signal through a whole system; Lesson 11 covers what to do with it inside one service.

A buffer that is sized to absorb a *burst* — a spike that ends — is genuinely useful. A buffer sized to absorb a sustained overload is a lie, because no finite buffer can. The bound forces you to admit which one you have.

### Rejection policies

When the queue is full you must choose. There are five reasonable answers and none of them is right everywhere.

**Block the submitter.** `put()` waits until a slot frees. The submitting thread is now stalled, which is precisely the point: the pressure propagates *upstream*, to the caller, and eventually to whoever is generating the load. Nothing is lost. In the Build It this policy completed all 360 items but took **1084 ms instead of 718 ms** — the submitter absorbed the difference. Use it when the producer is something you can afford to slow down and losing work is unacceptable. The trap: if the submitter is your HTTP accept loop, blocking it means you also stop reading sockets, which may be what you want (real backpressure to the client) or a disaster (your health check times out and the orchestrator kills you). Always set a timeout on the block.

**Reject immediately.** Raise, return an error, respond `503 Service Unavailable`. This is **load shedding**, and it is the only policy that gives an upstream a decision to make: retry with backoff, route to another instance, degrade the feature, or tell the user. The Build It shows 242 completed and **118 rejected** — and the rejection is the honest part. A rejected request that fails in 2 ms is far better for a user than one that succeeds in 30 seconds. Use it for anything user-facing.

**Discard the oldest.** Evict the item at the head of the queue and enqueue the new one. This is correct — genuinely, obviously correct — whenever a newer item *supersedes* an older one: live prices, position updates, sensor readings, metric samples, cache refreshes, a UI repaint. Nobody wants the price from four seconds ago. The measurement shows the effect precisely: the mean age of a served item drops to **14.3 ms** versus **22.4 ms** for reject, because the stale items are thrown away rather than served. You are trading completeness for freshness, deliberately.

**Discard the newest.** Drop the arriving item. It is the cheapest to implement and it is almost always the wrong choice, because it silently biases you toward whatever arrived first — you keep the stale work and throw away the fresh work. Measured mean age **22.2 ms**, no better than rejecting, with none of the honesty.

**Caller runs.** The submitting thread executes the task itself, inline. This is backpressure with zero loss and no extra threads, and it is elegant: the pool is full, so the producer becomes a worker and therefore stops producing. In the Build It, **112 of 360** items ran on the submitter's thread. The trap is the same as blocking, sharper: whatever loop the submitter was in stops running for the duration of one task.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 520" width="100%" style="max-width:860px" role="img" aria-label="Anatomy of a thread pool: submitters hand work to a single bounded queue, a fixed set of long-lived workers pull from it, and a Future carries each result or exception back to the submitter. The queue is the pressure point, and when it is full one of five rejection policies must fire: block the submitter, reject immediately, discard the oldest item, discard the newest item, or run the task inline on the caller.">
  <defs>
    <marker id="l07-a" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l07-ared" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l07-ablue" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A pool is fixed workers + ONE bounded queue + a Future per item</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <g fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"><rect x="20" y="62" width="122" height="32" rx="7"/><rect x="20" y="106" width="122" height="32" rx="7"/><rect x="20" y="150" width="122" height="32" rx="7"/></g><rect x="196" y="58" width="252" height="130" rx="11" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <g fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"><rect x="210" y="106" width="22" height="26" rx="3"/><rect x="238" y="106" width="22" height="26" rx="3"/><rect x="266" y="106" width="22" height="26" rx="3"/><rect x="294" y="106" width="22" height="26" rx="3"/><rect x="322" y="106" width="22" height="26" rx="3"/><rect x="350" y="106" width="22" height="26" rx="3"/><rect x="378" y="106" width="22" height="26" rx="3"/><rect x="406" y="106" width="22" height="26" rx="3"/></g>
    <g fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"><rect x="504" y="60" width="126" height="28" rx="7"/><rect x="504" y="94" width="126" height="28" rx="7"/><rect x="504" y="128" width="126" height="28" rx="7"/><rect x="504" y="162" width="126" height="28" rx="7"/></g>
    <rect x="686" y="80" width="172" height="88" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7" marker-end="url(#l07-a)">
    <path d="M142 78 L 176 116"/><path d="M142 122 L 188 122"/><path d="M142 166 L 176 130"/><path d="M448 123 L 496 74"/><path d="M448 123 L 496 108"/><path d="M448 123 L 496 142"/><path d="M448 123 L 496 176"/><path d="M630 124 L 678 124"/>
  </g>
  <path d="M772 168 C 772 206, 430 220, 152 202 L 146 194" fill="none" stroke="#3553ff" stroke-width="1.8" stroke-dasharray="6 5" marker-end="url(#l07-ablue)"/><path d="M210 188 L 210 272" fill="none" stroke="#d64545" stroke-width="2.2" marker-end="url(#l07-ared)"/>
  <g fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#l07-ared)"><path d="M100 298 L 100 320"/><path d="M270 298 L 270 320"/><path d="M440 298 L 440 320"/><path d="M610 298 L 610 320"/><path d="M780 298 L 780 320"/></g><path d="M20 298 L 860 298" fill="none" stroke="#d64545" stroke-width="1.5"/>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="20" y="320" width="160" height="150" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/><rect x="190" y="320" width="160" height="150" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/><rect x="360" y="320" width="160" height="150" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    <rect x="530" y="320" width="160" height="150" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/><rect x="700" y="320" width="160" height="150" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="81" y="52" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">SUBMITTERS</text><text x="81" y="82" font-size="9" text-anchor="middle">request thread</text><text x="81" y="126" font-size="9" text-anchor="middle">request thread</text><text x="81" y="170" font-size="9" text-anchor="middle">request thread</text>
    <text x="322" y="52" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">BOUNDED QUEUE — the pressure point</text><text x="322" y="88" font-size="9" text-anchor="middle" opacity="0.9">maxsize is the ONLY thing standing between</text>
    <text x="322" y="100" font-size="9" text-anchor="middle" opacity="0.9">a traffic spike and an out-of-memory kill</text><text x="322" y="152" font-size="9.5" text-anchor="middle" font-weight="700">export depth AND queue time</text>
    <text x="322" y="170" font-size="9" text-anchor="middle" opacity="0.85">depth alone is meaningless without a service rate</text><text x="567" y="52" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">N LONG-LIVED WORKERS</text>
    <text x="567" y="78" font-size="9" text-anchor="middle">worker-0</text><text x="567" y="112" font-size="9" text-anchor="middle">worker-1</text><text x="567" y="146" font-size="9" text-anchor="middle">worker-2</text><text x="567" y="180" font-size="9" text-anchor="middle">worker-3</text>
    <text x="772" y="70" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">FUTURE</text><text x="772" y="104" font-size="9.5" text-anchor="middle">value</text><text x="772" y="120" font-size="9.5" text-anchor="middle" opacity="0.7">— OR —</text><text x="772" y="136" font-size="9.5" text-anchor="middle">exception</text>
    <text x="772" y="158" font-size="8.5" text-anchor="middle" opacity="0.85">with its traceback intact</text><text x="248" y="244" font-size="9.5" fill="#3553ff" font-weight="700">without the Future, a worker's exception goes to stderr and the caller never learns</text>
    <text x="440" y="290" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">QUEUE FULL — there is no right default. You must choose:</text><text x="100" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">BLOCK</text>
    <text x="30" y="360" font-size="8.7">slow the submitter</text><text x="30" y="373" font-size="8.7">until space frees.</text><text x="30" y="393" font-size="8.7" font-weight="700">USE: pressure should</text><text x="30" y="406" font-size="8.7" font-weight="700">reach the caller.</text>
    <text x="30" y="428" font-size="8.7" opacity="0.85">measured: 360/360</text><text x="30" y="441" font-size="8.7" opacity="0.85">done, 0 lost, but</text><text x="30" y="454" font-size="8.7" opacity="0.85">1084 ms not 718 ms</text>
    <text x="270" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">REJECT</text><text x="200" y="360" font-size="8.7">raise at once. The</text><text x="200" y="373" font-size="8.7">caller decides.</text>
    <text x="200" y="393" font-size="8.7" font-weight="700">USE: load shedding,</text><text x="200" y="406" font-size="8.7" font-weight="700">a 503 beats a hang.</text>
    <text x="200" y="428" font-size="8.7" opacity="0.85">measured: 242 done,</text><text x="200" y="441" font-size="8.7" opacity="0.85">118 rejected — and</text><text x="200" y="454" font-size="8.7" opacity="0.85">the caller KNOWS</text>
    <text x="440" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">DISCARD OLDEST</text><text x="370" y="360" font-size="8.7">evict the stalest</text><text x="370" y="373" font-size="8.7">queued item.</text>
    <text x="370" y="393" font-size="8.7" font-weight="700">USE: live prices,</text><text x="370" y="406" font-size="8.7" font-weight="700">positions, metrics.</text>
    <text x="370" y="428" font-size="8.7" opacity="0.85">measured: mean age</text><text x="370" y="441" font-size="8.7" opacity="0.85">14.3 ms vs 22.4 ms</text><text x="370" y="454" font-size="8.7" opacity="0.85">— freshest data wins</text>
    <text x="610" y="340" font-size="10.5" font-weight="700" text-anchor="middle">DISCARD NEWEST</text><text x="540" y="360" font-size="8.7">drop what just</text><text x="540" y="373" font-size="8.7">arrived. Silently.</text>
    <text x="540" y="393" font-size="8.7" font-weight="700">USE: rarely — it is</text><text x="540" y="406" font-size="8.7" font-weight="700">just the cheapest.</text>
    <text x="540" y="428" font-size="8.7" opacity="0.85">measured: 242 done,</text><text x="540" y="441" font-size="8.7" opacity="0.85">age 22.2 ms — keeps</text><text x="540" y="454" font-size="8.7" opacity="0.85">the STALE items</text>
    <text x="780" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">CALLER RUNS</text><text x="710" y="360" font-size="8.7">the submitter runs</text><text x="710" y="373" font-size="8.7">the task inline.</text>
    <text x="710" y="393" font-size="8.7" font-weight="700">USE: backpressure</text><text x="710" y="406" font-size="8.7" font-weight="700">all the way to accept.</text>
    <text x="710" y="428" font-size="8.7" opacity="0.85">measured: 360 done,</text><text x="710" y="441" font-size="8.7" opacity="0.85">112 run inline — your</text><text x="710" y="454" font-size="8.7" opacity="0.85">accept loop stalls</text>
    <text x="440" y="498" font-size="11" text-anchor="middle" opacity="0.9">An unbounded queue is not a buffer. It is a delay line with an out-of-memory kill at the end.</text>
  </g>
</svg>
```

### Sizing: the actual math

Start with the two cases that have real answers.

**For CPU-bound work in CPython, threads are the wrong tool entirely.** The **GIL** (Global Interpreter Lock) is a single lock that a thread must hold to execute Python bytecode, so exactly one thread runs Python code at a time regardless of how many cores you have. Lesson 2 measured this and the Build It reproduces it: threads on pure-Python compute came in at **0.93x–1.01x** — no gain at all, sometimes slightly worse because you added scheduling overhead to work that could not overlap. Use *processes*, and size the pool to the number of **usable** cores: the cores your container is actually allowed (`os.sched_getaffinity`, or your cgroup CPU quota — `os.cpu_count()` cheerfully reports the host's 64 cores while your quota is 2), minus whatever the main thread and the runtime need.

**For I/O-bound work, start with Little's Law.** From Lesson 1: for any stable system, `L = λW` — the average number of items *in the system* equals the arrival rate times the average time each spends there. Turn it around and it sizes your pool. If you must sustain λ = 800 requests per second and each takes W = 10 ms of mostly-waiting, then `L = 800 × 0.010 = 8` requests are in flight at any instant, so you need 8 workers. The equivalent form you will see written down is:

```text
workers = N_cores × target_utilization × (1 + wait_time / service_time)
```

which is the same statement: a task that waits 9 ms for every 1 ms of computing has a ratio of 9, so one core can usefully carry 10 such tasks.

Now the caveat that matters more than the formula. **More workers is not monotonically better, and past a point it is actively worse.**

Your pool does not do its work in a vacuum. It calls something — a database with a connection limit, an API with a rate limit, a disk with a queue depth. That thing has its own capacity, and once your workers have saturated it, adding more workers cannot make it faster. What they do instead is *queue at the dependency*. Throughput stops rising. Latency keeps rising, because latency is now dominated by waiting in a line you created. And in a real system throughput does not merely flatten, it bends back down — the Universal Scalability Law (USL) from Lesson 1 names the mechanism: contention and coherency costs that grow with concurrency, like lock convoys, cache pressure and query-plan contention in a database.

The Build It measures exactly this curve, and the numbers are stark. Against a dependency serving 8 calls at a time:

- 8 workers: **813 tasks/s**, p99 **10.3 ms**
- 64 workers: **396 tasks/s** (49% of peak), p99 **166.6 ms** (16x worse)

Fifty-six extra threads bought zero throughput, halved it in fact, and added 156 ms to the p99. Which leads to the reframing that changes how you configure everything:

> **A pool size is a concurrency limit on your dependency, not a parallelism setting.**

Setting `max_workers=200` is not "go faster". It is "allow up to 200 simultaneous connections to the database", and if that number is larger than what the database can handle you have not built a fast service, you have built a distributed denial-of-service tool aimed at your own data store.

Little's Law is worth one more sentence because it is easy to misuse. It is an *identity* — it is always true, for every system, at every worker count. The Build It shows it balancing perfectly at 64 workers too (`396/s × 166.4 ms = 65.8 in flight`), because W has inflated to include 132 ms of pure queueing. The formula tells you where to *start* the sweep. Only the curve tells you where to stop.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 450" width="100%" style="max-width:860px" role="img" aria-label="Measured throughput and p99 latency plotted against worker count for an I/O-bound pool calling one dependency that serves eight requests at a time. Throughput rises from 119 to 813 tasks per second at eight workers, then falls back to 396 at sixty-four workers, while p99 latency stays near 10 milliseconds up to the knee and then climbs to 166.6 milliseconds. The region past eight workers is marked as more workers, half the throughput, sixteen times the p99.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The sizing curve: measured, not guessed</text><rect x="450" y="80" width="350" height="260" fill="#e0930f" fill-opacity="0.08"/>
  <g fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1"><line x1="100" y1="80" x2="800" y2="80"/><line x1="100" y1="145" x2="800" y2="145"/><line x1="100" y1="210" x2="800" y2="210"/><line x1="100" y1="275" x2="800" y2="275"/></g>
  <path d="M450 80 L 450 348" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 5"/><path d="M100 340 L 810 340" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <g fill="none" stroke="currentColor" stroke-width="1.4"><path d="M100 340 L 100 347"/><path d="M217 340 L 217 347"/><path d="M333 340 L 333 347"/><path d="M450 340 L 450 347"/><path d="M567 340 L 567 347"/><path d="M683 340 L 683 347"/><path d="M800 340 L 800 347"/></g>
  <path d="M100 305 L 217 272 L 333 209 L 450 101 L 567 130 L 683 176 L 800 224" fill="none" stroke="#3553ff" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
  <path d="M100 328 L 217 327 L 333 327 L 450 325 L 567 307 L 683 257 L 800 102" fill="none" stroke="#d64545" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/>
  <g fill="#3553ff"><circle cx="100" cy="305" r="3.6"/><circle cx="217" cy="272" r="3.6"/><circle cx="333" cy="209" r="3.6"/><circle cx="450" cy="101" r="5"/><circle cx="567" cy="130" r="3.6"/><circle cx="683" cy="176" r="3.6"/><circle cx="800" cy="224" r="3.6"/></g>
  <g fill="#d64545"><circle cx="100" cy="328" r="3.6"/><circle cx="217" cy="327" r="3.6"/><circle cx="333" cy="327" r="3.6"/><circle cx="450" cy="325" r="5"/><circle cx="567" cy="307" r="3.6"/><circle cx="683" cy="257" r="3.6"/><circle cx="800" cy="102" r="3.6"/></g>
  <g fill="none" stroke-width="2.6" stroke-linecap="round"><line x1="112" y1="98" x2="140" y2="98" stroke="#3553ff"/><line x1="112" y1="118" x2="140" y2="118" stroke="#d64545"/></g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="148" y="102" font-size="10.5" font-weight="700" fill="#3553ff">throughput (tasks/s)</text><text x="148" y="122" font-size="10.5" font-weight="700" fill="#d64545">p99 latency at the dependency (ms)</text>
    <text x="450" y="68" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">KNEE · 8 workers</text><text x="466" y="97" font-size="10.5" font-weight="700" fill="#3553ff">813/s</text><text x="466" y="112" font-size="9.5" fill="#3553ff" opacity="0.85">peak</text>
    <text x="806" y="252" font-size="10.5" font-weight="700" fill="#3553ff" text-anchor="end">396/s</text><text x="806" y="266" font-size="9.5" fill="#3553ff" opacity="0.85" text-anchor="end">49% of peak</text>
    <text x="440" y="318" font-size="10" font-weight="700" fill="#d64545" text-anchor="end">p99 10.3 ms</text><text x="800" y="94" font-size="10.5" font-weight="700" fill="#d64545" text-anchor="end">p99 166.6 ms · 16x worse</text>
    <text x="478" y="194" font-size="10.5" font-weight="700" fill="#e0930f">more workers ·</text><text x="478" y="210" font-size="10.5" font-weight="700" fill="#e0930f">HALF the throughput ·</text><text x="478" y="226" font-size="10.5" font-weight="700" fill="#e0930f">16x the p99</text>
    <text x="478" y="246" font-size="9.5" fill="#e0930f" opacity="0.9">every bit of it is</text><text x="478" y="260" font-size="9.5" fill="#e0930f" opacity="0.9">queue at the dependency</text>
    <text x="100" y="362" font-size="10" text-anchor="middle">1</text><text x="217" y="362" font-size="10" text-anchor="middle">2</text><text x="333" y="362" font-size="10" text-anchor="middle">4</text>
    <text x="450" y="362" font-size="10" text-anchor="middle" font-weight="700">8</text><text x="567" y="362" font-size="10" text-anchor="middle">16</text><text x="683" y="362" font-size="10" text-anchor="middle">32</text><text x="800" y="362" font-size="10" text-anchor="middle">64</text>
    <text x="450" y="382" font-size="10.5" text-anchor="middle" opacity="0.9">worker threads in the pool  (dependency serves 8 at a time, 8 ms each)</text><text x="440" y="408" font-size="10.5" text-anchor="middle" opacity="0.95">Little's Law gave the starting point — L = 813/s x 8.3 ms = 6.8 workers. The sweep gave the answer: 8.</text>
    <text x="440" y="432" font-size="11" text-anchor="middle" opacity="0.9">The pool size is a concurrency LIMIT on your dependency, not a speed dial. Measure the curve; never trust the formula alone.</text>
  </g>
</svg>
```

### Queue depth and queue time as saturation signals

Everyone exports queue **depth** because it is trivially available: `q.qsize()`. Depth alone is nearly meaningless. A depth of 500 is catastrophic if you serve 10 items per second (50 seconds of backlog) and completely fine if you serve 50,000 (10 milliseconds of backlog). Depth is a count; what you care about is a duration.

Export **queue time** as well: how long the oldest un-started item has been waiting. It is one subtraction — stamp each item at submit, and when a worker picks it up record `now - submitted_at`. That number is directly comparable to your latency budget, it is the same unit as your service level objective, and it is the leading indicator of everything else. Latency degradation shows up in queue time before it shows up anywhere a user can see it.

This is the **saturation** golden signal from Phase 9's [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/), applied to the resource you actually control. Instrument three numbers per pool: queue depth (a gauge), queue time (a histogram, so you can take its p99 and add it up across instances), and rejections (a counter, because a counter cannot miss an event between scrapes the way a gauge can). Alert on queue *time*.

### Graceful shutdown

A pool that cannot stop cleanly will eventually corrupt something. The first decision is **drain or abandon**.

**Draining** finishes everything already in the queue and then stops. Correct when the queued items represent committed work — a write that was acknowledged, an email that was promised. **Abandoning** discards the queue and stops as soon as the in-flight items finish. Correct when the queued items are only meaningful in a context that is going away, like requests whose clients have already disconnected. Either way, *the item currently executing should be allowed to finish*, and either way you need a timeout, because "drain" without a bound is just "hang".

The mechanism for telling workers to stop is worth getting right. A shared `stop` flag checked in the loop has a race: a worker already blocked in `queue.get()` will not see it and will sit there forever. The clean solution is a **poison pill** — push a unique sentinel object onto the queue, exactly one per worker. A worker that dequeues the sentinel returns. Because the sentinels go through the same FIFO queue, they naturally arrive *after* all previously queued work, so draining falls out for free. Push N sentinels for N workers and every worker gets exactly one.

`Queue.task_done()` and `Queue.join()` are the other half: the queue keeps a count of unfinished tasks, each `get()` must be matched by a `task_done()`, and `join()` blocks until the count hits zero. It gives you "wait for the backlog to clear" without tracking futures yourself. The discipline: call `task_done()` in a `finally`, including for items you discard without running, or `join()` will hang forever on a count that never reaches zero.

Finally, **daemon threads**. A daemon thread is one the interpreter will not wait for at exit — when the main thread finishes, daemon threads are terminated wherever they happen to be. That is not a graceful stop, it is a kill. If the thread was halfway through writing a file, appending to a log, or holding a lock, it stays halfway through forever. Daemon threads are how you get truncated files and corrupt state on deploy. Use non-daemon workers and shut them down explicitly. (The Build It uses `daemon=True` in exactly one place — the deadlock demonstration — precisely so a demo of a hang can never hang the file. That is the legitimate use: threads whose work is disposable by construction.)

### Pool starvation and pool deadlock

This is the failure that turns a working service into a completely frozen one, with no error, no crash, no CPU usage and no log line.

A task running inside the pool submits another task **to the same pool** and blocks waiting for its result. With N workers and N such tasks in flight, all N workers are blocked. The inner tasks they are waiting for are sitting in the queue *behind* them. No worker will ever become free to run an inner task, because every worker is waiting for an inner task. The Build It reproduces it exactly: 4 workers, 4 nested tasks, **0 of 4 done after 0.9 seconds, queue depth 4, and the inner function never executed a single time.**

It is a deadlock in the strict sense. The pool's threads are a resource; each task *holds* one and *requests* another; the requests form a cycle. Lesson 10 generalises the conditions. Three shapes produce it:

- A pool task submitting to its own pool and waiting (the classic).
- Two pools calling into each other — A's tasks wait on B, B's tasks wait on A. Both saturate, both wait.
- A pool task blocking on a lock that is held by a task still sitting in the queue. The queued task cannot run to release the lock, because the running task will not release its thread.

The seductive non-fix is "use a bigger pool". It does not fix anything; it raises the number of concurrent nested calls needed to trigger it, so instead of failing in your load test it fails in production at 3am. The real fixes:

- **Never call `.result()` on the pool you are currently running inside.** This is the rule; the rest are ways to obey it.
- **Separate pools per tier** — a bulkhead. The tier that waits and the tier that works never compete for the same threads. Measured: 8 nested tasks complete in **5.3 ms**.
- **Make the dependency asynchronous** — return the inner future instead of blocking on it, chain a callback, or restructure so the task does not need to wait. Flattening the call entirely was fastest at **4.6 ms**, and it is usually available if you look.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:860px" role="img" aria-label="Pool deadlock and its fix. On the left, all four workers of a single pool are blocked inside outer tasks waiting on the result of inner tasks that are still sitting in that same pool's queue behind them, forming a cycle that can never break. On the right, two fixes: splitting the waiting tier and the working tier into two separate pools, and flattening the nested call so nothing blocks on the pool it runs in.">
  <defs>
    <marker id="l07-d-red" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l07-d-grn" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Pool deadlock: never block on the pool you are running inside</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="454" height="396" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/><rect x="490" y="44" width="374" height="396" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    <g fill="#d64545" fill-opacity="0.14" stroke="#d64545"><rect x="32" y="104" width="210" height="38" rx="7"/><rect x="32" y="150" width="210" height="38" rx="7"/><rect x="32" y="196" width="210" height="38" rx="7"/><rect x="32" y="242" width="210" height="38" rx="7"/></g>
    <rect x="32" y="300" width="210" height="76" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <g fill="#e0930f" fill-opacity="0.32" stroke="#e0930f" stroke-width="1.3"><rect x="44" y="330" width="42" height="24" rx="3"/><rect x="90" y="330" width="42" height="24" rx="3"/><rect x="136" y="330" width="42" height="24" rx="3"/><rect x="182" y="330" width="42" height="24" rx="3"/></g>
    <rect x="258" y="120" width="196" height="230" rx="10" fill="none" stroke="#d64545" stroke-dasharray="6 5" stroke-width="1.8"/><rect x="506" y="104" width="156" height="56" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="692" y="104" width="156" height="56" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="506" y="284" width="342" height="52" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="1.7" marker-end="url(#l07-d-red)">
    <path d="M242 200 L 254 200"/><path d="M356 168 L 356 186"/><path d="M356 214 L 356 232"/><path d="M356 260 L 356 278"/>
  </g>
  <path d="M242 336 C 250 336, 252 322, 254 314" fill="none" stroke="#d64545" stroke-width="1.7" marker-end="url(#l07-d-red)"/><path d="M282 328 C 264 318, 264 176, 280 162" fill="none" stroke="#d64545" stroke-width="1.7" stroke-dasharray="5 4" marker-end="url(#l07-d-red)"/>
  <path d="M662 132 L 686 132" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#l07-d-grn)"/><path d="M506 246 L 848 246" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.3"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="243" y="74" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">ONE pool · 4 workers · 4 nested tasks</text><text x="243" y="94" font-size="9.5" text-anchor="middle" opacity="0.85">every worker is busy — and every one of them is waiting</text>
    <text x="42" y="120" font-size="8.6">worker-0: running outer(0)</text><text x="42" y="134" font-size="8.6" font-weight="700" fill="#d64545">BLOCKED on inner(0).result()</text>
    <text x="42" y="166" font-size="8.6">worker-1: running outer(1)</text><text x="42" y="180" font-size="8.6" font-weight="700" fill="#d64545">BLOCKED on inner(1).result()</text>
    <text x="42" y="212" font-size="8.6">worker-2: running outer(2)</text><text x="42" y="226" font-size="8.6" font-weight="700" fill="#d64545">BLOCKED on inner(2).result()</text>
    <text x="42" y="258" font-size="8.6">worker-3: running outer(3)</text><text x="42" y="272" font-size="8.6" font-weight="700" fill="#d64545">BLOCKED on inner(3).result()</text><text x="137" y="320" font-size="9.5" font-weight="700" text-anchor="middle" fill="#e0930f">THE SAME POOL'S QUEUE · depth 4</text>
    <text x="65" y="346" font-size="8" text-anchor="middle">inner0</text><text x="111" y="346" font-size="8" text-anchor="middle">inner1</text><text x="157" y="346" font-size="8" text-anchor="middle">inner2</text><text x="203" y="346" font-size="8" text-anchor="middle">inner3</text>
    <text x="137" y="369" font-size="8.6" text-anchor="middle" opacity="0.9">no worker will ever pick these up</text><text x="356" y="142" font-size="10" font-weight="700" text-anchor="middle" fill="#d64545">THE CYCLE</text>
    <text x="356" y="164" font-size="9" text-anchor="middle">worker-i holds a thread</text><text x="356" y="210" font-size="9" text-anchor="middle">it waits for inner(i)</text><text x="356" y="256" font-size="9" text-anchor="middle">inner(i) needs a thread</text>
    <text x="356" y="300" font-size="9" text-anchor="middle">every thread is held</text><text x="356" y="314" font-size="9" text-anchor="middle">by a blocked worker-i</text><text x="356" y="336" font-size="9" font-weight="700" text-anchor="middle" fill="#d64545">…back to the top. Forever.</text>
    <text x="243" y="400" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">measured: 0 of 4 tasks done after 0.9 s · inner() never started</text>
    <text x="243" y="418" font-size="9.5" text-anchor="middle" opacity="0.9">N workers, N tasks that each wait on the pool = guaranteed deadlock</text><text x="677" y="74" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">TWO WAYS OUT</text>
    <text x="506" y="96" font-size="10" font-weight="700" fill="#3553ff">FIX A · separate pools per tier (a bulkhead)</text>
    <text x="584" y="126" font-size="9" text-anchor="middle" font-weight="700">tier-1 pool</text><text x="584" y="140" font-size="8.6" text-anchor="middle">runs outer()</text><text x="584" y="153" font-size="8.6" text-anchor="middle">and waits</text>
    <text x="770" y="126" font-size="9" text-anchor="middle" font-weight="700">tier-2 pool</text><text x="770" y="140" font-size="8.6" text-anchor="middle">runs inner()</text><text x="770" y="153" font-size="8.6" text-anchor="middle">and never waits</text>
    <text x="677" y="184" font-size="9" text-anchor="middle" opacity="0.9">the tier that waits and the tier that works</text><text x="677" y="198" font-size="9" text-anchor="middle" opacity="0.9">never compete for the same thread</text>
    <text x="677" y="224" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">measured: 8 nested tasks in 5.3 ms</text><text x="506" y="272" font-size="10" font-weight="700" fill="#0fa07f">FIX B · do not block at all</text>
    <text x="677" y="306" font-size="9" text-anchor="middle">fold inner() into outer() — one task, one thread,</text><text x="677" y="322" font-size="9" text-anchor="middle">no future to wait on, nothing to deadlock</text>
    <text x="677" y="352" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">measured: 8 flattened tasks in 4.6 ms</text><text x="677" y="392" font-size="10" text-anchor="middle" font-weight="700">The same cycle appears whenever a pool task</text>
    <text x="677" y="408" font-size="10" text-anchor="middle" font-weight="700">blocks on a lock held by a QUEUED task.</text><text x="677" y="426" font-size="9" text-anchor="middle" opacity="0.85">Bigger pools only move the deadlock, never remove it.</text>
    <text x="440" y="466" font-size="11" text-anchor="middle" opacity="0.9">A pool that can wait on itself is a resource that can be held and requested at once — the classic deadlock precondition.</text>
  </g>
</svg>
```

### Work stealing

One shared queue means one lock. Every worker taking an item and every submitter adding one contends for it. At a few thousand tasks per second nobody notices; at a few million — fine-grained parallel work, a task that spawns subtasks — that single lock becomes the bottleneck, and you have built a system where adding cores makes things slower.

**Work stealing** removes the shared point. Each worker gets its own double-ended queue (a *deque*). It pushes and pops its own work at one end, which needs no coordination at all in the common case because nobody else is touching that end. When a worker runs out, it *steals* from the **tail** of another worker's deque. Taking from the opposite end minimises the chance of colliding with the owner, and stealing the oldest item is a good heuristic: the oldest item is likely the largest remaining subtree of work, so one steal buys a lot of work per synchronisation.

This is what Go's scheduler does with goroutines, what Java's `ForkJoinPool` does, and what Rust's Rayon and Tokio do. It matters when tasks are tiny and numerous, and when tasks *create* tasks. For the ordinary backend case — a few thousand I/O-bound items per second — one shared queue is fine and much easier to reason about. Reach for work stealing when profiling shows contention on the queue, not before.

### Processes, and the serialization tax

`ProcessPoolExecutor` gives you real parallelism: separate interpreters, separate GILs, all your cores. The Build It measured **3.41x** on 8 processes for work where threads managed 0.95x.

It is not free, and the cost is easy to miss because it is invisible in the code. Processes do not share memory, so every argument is **pickled** (serialised to bytes), written through a pipe, and unpickled in the child; every return value makes the same trip back. You are paying for a serialise-copy-deserialise round trip on every single task.

For small tasks that tax dominates completely. The measurements:

| per-task work | serial (24 tasks) | ProcessPool(4) | verdict |
|---|---|---|---|
| 14 µs | 0.3 ms | 6.6 ms | **0.05x** — 20x slower |
| 219 µs | 5.3 ms | 6.4 ms | 0.82x — still losing |
| 1,512 µs | 36.3 ms | 12.7 ms | **2.85x** — processes win |

The crossover sits somewhere between 0.2 ms and 1.5 ms of work per task. Below it you are paying more postage than the parcel is worth.

Two mitigations. **`chunksize`** batches several tasks into one pickle-and-send: for the 14 µs task, `chunksize=10` cut the process-pool time from 6.6 ms to 1.4 ms — nearly 5x — because you send a tenth as many messages. It is not a universal win: for the 1,512 µs task the same `chunksize=10` made things *worse* (20.1 ms vs 12.7 ms), because coarse chunks destroy load balancing and one unlucky worker ends up holding the last chunk while the rest sit idle. And **shared memory** (`multiprocessing.shared_memory`, or NumPy arrays over it) skips the copy entirely for large payloads — worth it because payload cost is real and linear: the Build It clocks a 4 MB argument at **5.9 ms per round trip**, which is more expensive than several thousand iterations of actual computation.

### Bridging sync and async

If your service is built on an event loop (Lessons 4 and 5), one blocking call on the loop thread stalls *every* connection that loop is serving for the whole duration of that call. This is the single most common async performance bug there is, and the fix is a thread pool:

```python
result = await asyncio.to_thread(blocking_db_call, query)          # 3.9+
result = await loop.run_in_executor(pool, blocking_db_call, query)  # any version
```

Both move the blocking work onto a worker thread and give the loop back an awaitable. Going the other way — code on a worker thread that needs to schedule a coroutine on the loop — is `asyncio.run_coroutine_threadsafe(coro, loop)`, which returns a `concurrent.futures.Future` you can wait on from the thread. It is one of the very few asyncio calls that is safe to make from another thread; almost everything else in asyncio assumes it is called on the loop thread.

The trap is that `asyncio.to_thread` uses **the loop's default executor**, and that executor is a bounded resource almost nobody sizes. It is created lazily as a `ThreadPoolExecutor` with `max_workers = min(32, cpu_count + 4)`, and — of course — an unbounded queue. So every `to_thread` call in your entire application shares one pool of maybe 12 threads. One slow dependency saturating that pool blocks every other `to_thread` in the process, including the fast ones that had nothing to do with it. Set it explicitly, and prefer a *separate* executor per dependency.

### Choosing a model: the decision matrix

You have now seen threads, processes, event loops and pools. Here is the whole decision in one table.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 450" width="100%" style="max-width:860px" role="img" aria-label="A decision matrix mapping five workload types to the right concurrency tool and its sizing rule: CPU-bound work to a process pool sized to cores, blocking I/O to a thread pool with a bounded queue sized from Little's Law and then swept, async-capable I/O to the event loop with a semaphore per dependency, mixed async services to asyncio.to_thread with an explicitly sized default executor, and work needing isolation to a separate process or a message broker.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Choosing a model: workload → tool → how to size it</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.5">
    <rect x="20" y="48" width="165" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.5"/><rect x="190" y="48" width="185" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="380" y="48" width="260" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.5"/><rect x="645" y="48" width="215" height="30" rx="6" fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="20" y="84" width="165" height="60" rx="6" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/><rect x="20" y="148" width="165" height="60" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/><rect x="20" y="212" width="165" height="60" rx="6" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="20" y="276" width="165" height="60" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/><rect x="20" y="340" width="165" height="60" rx="6" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.6"/>
    <g stroke="currentColor" stroke-opacity="0.28" fill="none">
      <rect x="190" y="84" width="185" height="60" rx="6"/><rect x="380" y="84" width="260" height="60" rx="6"/><rect x="645" y="84" width="215" height="60" rx="6"/><rect x="190" y="148" width="185" height="60" rx="6"/><rect x="380" y="148" width="260" height="60" rx="6"/><rect x="645" y="148" width="215" height="60" rx="6"/>
      <rect x="190" y="212" width="185" height="60" rx="6"/><rect x="380" y="212" width="260" height="60" rx="6"/><rect x="645" y="212" width="215" height="60" rx="6"/><rect x="190" y="276" width="185" height="60" rx="6"/><rect x="380" y="276" width="260" height="60" rx="6"/><rect x="645" y="276" width="215" height="60" rx="6"/>
      <rect x="190" y="340" width="185" height="60" rx="6"/><rect x="380" y="340" width="260" height="60" rx="6"/><rect x="645" y="340" width="215" height="60" rx="6"/>
    </g>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="102" y="68" font-size="9.5" font-weight="700" text-anchor="middle">WORKLOAD</text><text x="282" y="68" font-size="9.5" font-weight="700" text-anchor="middle">TOOL</text><text x="510" y="68" font-size="9.5" font-weight="700" text-anchor="middle">WHY (measured where it says so)</text>
    <text x="752" y="68" font-size="9.5" font-weight="700" text-anchor="middle">SIZING RULE</text><text x="30" y="104" font-size="9" font-weight="700" fill="#7c5cff">CPU-bound</text><text x="30" y="119" font-size="8.4">pure-Python compute:</text><text x="30" y="133" font-size="8.4">parsing, hashing, math</text>
    <text x="200" y="107" font-size="9" font-weight="700">ProcessPoolExecutor</text><text x="200" y="122" font-size="8.4">(never threads)</text><text x="200" y="136" font-size="8.4" opacity="0.8">multiprocessing, not GIL</text>
    <text x="390" y="100" font-size="8.1">the GIL (Global Interpreter Lock) lets ONE</text><text x="390" y="113" font-size="8.1">thread run bytecode at a time. Measured:</text><text x="390" y="126" font-size="8.1">threads 0.93-1.01x — no gain at all;</text>
    <text x="390" y="139" font-size="8.1">8 processes 3.41x on 10 cores.</text><text x="655" y="104" font-size="8.4" font-weight="700">workers = usable cores</text><text x="655" y="118" font-size="8.4">tasks must be &gt; ~0.5 ms of work,</text>
    <text x="655" y="132" font-size="8.4">or pickling postage eats the win</text><text x="30" y="168" font-size="9" font-weight="700" fill="#0fa07f">Blocking I/O</text><text x="30" y="183" font-size="8.4">sync DB driver, files,</text><text x="30" y="197" font-size="8.4">a C extension, requests</text>
    <text x="200" y="171" font-size="9" font-weight="700">ThreadPoolExecutor</text><text x="200" y="186" font-size="8.4">+ YOUR OWN bound on the</text><text x="200" y="200" font-size="8.4">queue (its own is not)</text><text x="390" y="164" font-size="8.1">a blocking syscall RELEASES the GIL, so</text>
    <text x="390" y="177" font-size="8.1">threads genuinely overlap — and the pool</text><text x="390" y="190" font-size="8.1">then acts as a concurrency limit on</text><text x="390" y="203" font-size="8.1">whatever it calls.</text>
    <text x="655" y="168" font-size="8.4" font-weight="700">L = lambda x W, then SWEEP</text><text x="655" y="182" font-size="8.4">stop at the dependency's capacity:</text><text x="655" y="196" font-size="8.4">measured knee 8, not 64 (49% there)</text>
    <text x="30" y="232" font-size="9" font-weight="700" fill="#3553ff">Async-capable I/O</text><text x="30" y="247" font-size="8.4">an asyncio-native</text><text x="30" y="261" font-size="8.4">client for everything</text>
    <text x="200" y="235" font-size="9" font-weight="700">the event loop</text><text x="200" y="250" font-size="8.4">no pool at all</text><text x="200" y="264" font-size="8.4" opacity="0.8">asyncio.TaskGroup</text><text x="390" y="228" font-size="8.1">one thread, thousands of sockets: no</text>
    <text x="390" y="241" font-size="8.1">stack per connection, no kernel context</text><text x="390" y="254" font-size="8.1">switch per handoff. A thread pool here</text><text x="390" y="267" font-size="8.1">buys memory cost and nothing else.</text>
    <text x="655" y="232" font-size="8.4" font-weight="700">asyncio.Semaphore per dependency</text><text x="655" y="246" font-size="8.4">the "pool size" moves into the</text><text x="655" y="260" font-size="8.4">semaphore — same number, same sweep</text>
    <text x="30" y="296" font-size="9" font-weight="700" fill="#e0930f">Mixed</text><text x="30" y="311" font-size="8.4">an async service with</text><text x="30" y="325" font-size="8.4">ONE blocking call left</text>
    <text x="200" y="299" font-size="9" font-weight="700">asyncio.to_thread()</text><text x="200" y="314" font-size="8.4">loop.run_in_executor()</text><text x="200" y="328" font-size="8.4" opacity="0.8">a sized executor</text>
    <text x="390" y="292" font-size="8.1">one blocking call on the loop thread</text><text x="390" y="305" font-size="8.1">stalls EVERY other connection for its</text><text x="390" y="318" font-size="8.1">whole duration — the single most common</text>
    <text x="390" y="331" font-size="8.1">async performance bug there is.</text><text x="655" y="296" font-size="8.4" font-weight="700">set the default executor yourself</text><text x="655" y="310" font-size="8.4">it defaults to min(32, cpu+4) with</text>
    <text x="655" y="324" font-size="8.4">an UNBOUNDED queue behind it</text><text x="30" y="360" font-size="9" font-weight="700">Needs isolation</text><text x="30" y="375" font-size="8.4">untrusted code, leaks,</text><text x="30" y="389" font-size="8.4">or jobs that outlive</text>
    <text x="200" y="363" font-size="9" font-weight="700">a separate process,</text><text x="200" y="378" font-size="8.4">or a broker + workers</text><text x="200" y="392" font-size="8.4" opacity="0.8">Celery / RQ — Phase 6</text>
    <text x="390" y="356" font-size="8.1">a crash, a leak or a ten-minute job must</text><text x="390" y="369" font-size="8.1">not take the request path down with it.</text><text x="390" y="382" font-size="8.1">In-process pools also lose every queued</text>
    <text x="390" y="395" font-size="8.1">item on deploy.</text><text x="655" y="360" font-size="8.4" font-weight="700">size consumers, not threads</text><text x="655" y="374" font-size="8.4">and make the queue DURABLE —</text><text x="655" y="388" font-size="8.4">a restart must not lose work</text>
    <text x="440" y="428" font-size="11" text-anchor="middle" opacity="0.9">Every row's sizing rule ends the same way: compute a starting point, then measure the curve and stop at the knee.</text>
  </g>
</svg>
```

## Build It

You will build a complete pool and then use it as a measuring instrument. Start with the `Future`, because everything else depends on it. It is a single-slot mailbox guarded by an `Event`:

```python
class Future:
    def set_exception(self, exc: BaseException) -> None:
        # The same exception OBJECT crosses the thread boundary, so the
        # worker's traceback is still attached when the submitter re-raises it.
        self._exc, self._state = exc, "failed"
        self._ready.set()

    def result(self, timeout: float | None = None):
        if not self._ready.wait(timeout):
            raise FutureTimeout(f"future not ready after {timeout}s")
        if self._exc is not None:
            raise self._exc
        return self._value
```

The worker loop is the whole pool in fifteen lines. Note three things: the poison-pill check comes first, the `except BaseException` is deliberate rather than sloppy (a bare `Exception` would let a `KeyboardInterrupt` in a task kill the worker silently), and `task_done()` lives in a `finally` so `Queue.join()` can never hang on an item that raised.

```python
def _worker(self) -> None:
    while True:
        task = self._q.get()
        if task is _POISON:                 # poison pill: one per worker
            self._q.task_done()
            return
        started = time.perf_counter()
        self.stats.queue_waits.append(started - task.submitted_at)
        try:
            value = task.fn(*task.args, **task.kwargs)
        except BaseException as exc:
            task.future.set_exception(exc)  # the caller decides, not stderr
        else:
            task.future.set_result(value)
        finally:
            self._q.task_done()
```

`submit()` is where the rejection policy lives. `BLOCK` is just `put()` with a timeout; the interesting one is `DISCARD_OLDEST`, which has to make room before it can enqueue — and must cancel the evicted item's future, or a submitter waits forever on work that was silently thrown away:

```python
if self.policy == DISCARD_OLDEST:
    while True:
        try:                            # evict the stalest queued item
            stale = self._q.get_nowait()
        except queue.Empty:
            pass
        else:
            self._q.task_done()
            stale.future.cancel("discarded: newer work arrived")
        try:
            self._q.put_nowait(task)
            return fut
        except queue.Full:
            continue
```

`shutdown(wait, drain)` abandons the backlog first if asked (cancelling each dropped future, so no submitter waits forever on work that will never run), then pushes exactly one sentinel per worker. Because the sentinels travel through the same FIFO queue they arrive behind all existing work, so draining is the default and costs nothing extra.

The sizing sweep needs a dependency that behaves like a real one, so the simulated downstream is a fair *c*-server queue: each caller is assigned the server that frees soonest and sleeps until its own completion instant. That gives exact FIFO queueing rather than whatever order the operating system happens to wake threads in, plus a coherency penalty that grows with concurrency — the mechanism behind the USL's retrograde region:

```python
with self._lock:
    self._inflight += 1
    n = self._inflight
    i = min(range(self.capacity), key=lambda k: self._free[k])
    start = max(arrival, self._free[i])
    service = self.service_s * (1.0 + 0.025 * n)   # contention grows with n
    self._free[i] = start + service
```

The rest — `map`, the overload harness, the process-pool crossover and the deadlock watchdog — is in [`code/thread_pool.py`](code/thread_pool.py). Run it:

```bash
python3 thread_pool.py
```

```console
== 1 · A POOL IS FIXED WORKERS + A BOUNDED QUEUE + A FUTURE ==
  map over 12 tasks x 10ms on 3 workers -> [0, 2, 4, 6, 8, 10]... in   41.3 ms
  serial would have been 120.0 ms; speedup 2.91x (3 workers, ceiling 3.00x)
  worker raised -> caller caught ValueError: task 7 could not be processed
  traceback survived the thread hop (4 frames) instead of going to stderr
  future states: done=True state='failed'
  shutdown(drain=True): submitted=13 completed=12 failed=1
  worker threads still alive after shutdown: 0

== 2 · UNBOUNDED QUEUES CONVERT OVERLOAD INTO AN INVISIBLE DELAY LINE ==
  identical load: 4 workers x 5 ms of work each (= 800 items/s of capacity),
  offered at ~3000 items/s for 1.0 s. Only the queue bound differs.

  queue         offered/s  served/s  peak depth  queue MiB   done  accepted+lost
  unbounded          2473       762        1712        9.3    770           1708
  bounded(64)         828       760          64        0.4    764             64

  end-to-end latency, measured FROM SUBMIT (not from start-of-work):
  queue          p50 ms   p99 ms  first 10%  last 10%  oldest queued  drain s
  unbounded       354.1    684.9       37.9     656.5          688.8      2.2
  bounded(64)      89.0     95.5       38.4      90.0           84.7      0.1

  UNBOUNDED: latency climbed 38 ms -> 657 ms during a single second and had not stopped;
    the queue grew 9.3 MiB/s, so a 2 GiB container OOMs in ~4 min of this;
    1708 items were accepted and never run, and the survivors would need 2.2 s more to drain.
  BOUNDED  : latency flat at 38 ms -> 90 ms, backlog pinned at 64, memory 0.4 MiB.
    The queue bound converted the same overload into backpressure: the submitter was
    slowed from 2473/s to 828/s, which is a signal you can act on.

== 3 · THE SIZING CURVE: THROUGHPUT PEAKS AND FALLS, LATENCY ONLY RISES ==
  I/O-bound tasks against ONE shared dependency: 8 concurrent calls served at once,
  8 ms each, so the naive ceiling is 8 / 0.008 = 1000 calls/s -- PLUS a contention
  penalty of 2.5% per concurrent caller, which is why the real peak lands below it.
  Latency below is the DEPENDENCY call itself: worker pickup -> completion.

   workers  tasks   thru/s   p50 ms   p99 ms  wait@dep ms   throughput
         1    116      119      8.3      8.6          0.0   ###
         2    152      233      8.5      8.8          0.0   ######
         4    224      445      8.9      9.3          0.0   ############
         8    368      813      9.7     10.3          0.0   ######################  <- knee
        16    560      713     22.4     22.8         10.8   ###################
        32    560      559     57.6     58.0         41.2   ###############
        64    560      396    166.4    166.6        132.0   ###########

  Little's Law starting point : to sustain 813 tasks/s at an UNLOADED service time
    of 8.3 ms you need L = lambda x W = 6.8 workers in flight (nearest sweep point: 8).
  Measured optimum            : 8 workers -> 813 tasks/s, p50 9.7 ms, p99 10.3 ms, 0.0 ms queued at the dependency.

  Now watch the formula stop being useful. At 64 workers W has inflated to 166.4 ms,
    of which 132.0 ms is pure queueing AT THE DEPENDENCY. Little's Law still balances there
    (396/s x 166.4 ms = 65.8 in flight) -- it is an identity, always true, and it is
    NOT an optimiser. It tells you where to start the sweep; the curve tells you where to stop.

  Past the knee: 64 workers held 49% of peak throughput (396 vs 813/s) while p50 got 17.1x worse and p99 16.1x worse.
    56 extra workers bought 0 throughput and +156 ms of p99. They bought queue at the dependency.
    The pool size is a CONCURRENCY LIMIT on whatever the pool calls, not a speed dial.

== 4 · CPU-BOUND: THREADS DO NOT SCALE, PROCESSES CHARGE POSTAGE ==
  16 tasks x 150,000 iterations of pure-Python arithmetic on 10 cores
  (best of 3 runs each, because a shared machine's first run is always the slowest)
  serial (1 thread)                194 ms   1.00x
  ThreadPool(2)                    193 ms   1.01x
  ThreadPool(4)                    209 ms   0.93x
  ThreadPool(8)                    205 ms   0.95x
  ProcessPool(2)                   136 ms   1.43x
  ProcessPool(4)                    77 ms   2.51x
  ProcessPool(8)                    57 ms   3.41x

  the crossover: how big must one task be before a process pool pays for itself?
   iters/task  us/task  serial ms  ProcPool(4)  +chunk=10  speedup   verdict
          200       14        0.3          6.6        1.4     0.05   postage dominates
        2,000      219        5.3          6.4        2.9     0.82   postage dominates
       20,000     1512       36.3         12.7       20.1     2.85   processes win
      100,000     8855      212.5         87.1      116.4     2.44   processes win

  the postage itself: a no-op task, varying argument size (pickle + pipe, round trip)
      payload  per-call ms      MB/s
          64B        0.168       0.4
      64,000B        0.179     357.6
   1,000,000B        1.496     668.3
   4,000,000B        5.877     680.6

== 5 · POOL DEADLOCK: N WORKERS WAITING ON WORK QUEUED BEHIND THEM ==
  DEADLOCK: no progress after 0.9 s (0/4 outer tasks done, queue depth 4)
  all 4 workers are blocked inside outer() waiting on inner(),
  and inner() is item #1..4 in the queue BEHIND them. Nothing can move.
  inner() ever started: False

  FIX A - two pools (a bulkhead): the tier that waits is never the tier that works
  8 nested tasks across two pools -> [0, 10, 20, 30, 40, 50, 60, 70] in 5.3 ms

  FIX B - do not block at all: fold the dependency into one task
  8 flattened tasks on one pool          -> [0, 10, 20, 30, 40, 50, 60, 70] in 4.6 ms
  the rule: never call .result() on the pool you are currently running inside.

== 6 · REJECTION POLICIES: FIVE HONEST ANSWERS TO A FULL QUEUE ==
  identical overload for each policy: 2 workers x 6 ms of work
  (= 333 items/s of capacity), queue bound 8, 360 items offered at a steady 500/s.

  policy             done  rejected  dropped  inline  wall ms  mean age  oldest served
  block               360         0        0       0     1084      26.7           30.3
  reject              242       118        0       0      718      22.4           24.7
  discard_oldest      242         0      118       0      718      14.3           22.3
  discard_newest      242         0      118       0      718      22.2           24.8
  caller_runs         360         0        0     112      757      20.4           36.0
  ...

(total runtime 18.0 s; python 3.12, 10 cores)
```

**Read the numbers — four of these sections are arguments, not demos.**

**Section 2 is the case for bounding your queue, and the columns to read are `first 10%` and `last 10%`.** Both runs were offered identical work and both *served* it at the same rate — 762/s unbounded and 760/s bounded, because the workers were the bottleneck in both and the queue cannot change that. Everything else is different. The unbounded run's completed items started at a median latency of **37.9 ms** and finished at **656.5 ms**: latency did not settle at a high value, it *climbed*, linearly, for the entire second, and it was still climbing when the run stopped. That is the delay line. The bounded run went from 38.4 ms to 90.0 ms and stayed there, because with 64 slots and 760 items/s of service the wait can never exceed about 84 ms. Meanwhile the unbounded queue grew to **1,712 items and 9.3 MiB in one second** — extrapolate and a 2 GiB container is dead in four minutes — and **1,708 items were accepted and then never run**, which is the worst outcome available: you took responsibility for work, made the caller wait, and dropped it anyway. The bounded run lost 64. And note what "bounded" cost: the submitter was slowed from 2,473/s to 828/s. That slowdown *is* the signal. It is visible, it is immediate, and it is at the exact place where the mismatch is.

**Section 3 is the whole argument for measuring instead of guessing.** Throughput rises almost perfectly linearly to 8 workers — 119, 233, 445, 813 — because up to that point every added worker finds the dependency idle. Then it stops, and reverses: 713, 559, **396**. Sixty-four workers deliver **49% of what eight delivered**. The `wait@dep` column shows precisely where the loss goes: 0.0 ms of queueing at the dependency at 8 workers, **132.0 ms at 64**. Latency tells the same story more brutally — p99 goes 10.3 → 22.8 → 58.0 → **166.6 ms**, a 16x degradation, while throughput was *falling*. There is no reading of this table in which `max_workers=64` is a better configuration than `max_workers=8`; it is worse on every axis simultaneously. And Little's Law behaved exactly as a good identity should: it predicted 6.8 workers from the unloaded service time and pointed at the right sweep point, then kept balancing perfectly at 64 workers (396/s × 166.4 ms = 65.8 in flight) while describing a configuration you would never ship. The formula narrows the search. The sweep decides.

**Section 4 prices both halves of the multiprocessing trade.** Threads on CPU-bound Python delivered **1.01x, 0.93x, 0.95x** at 2, 4 and 8 workers — that is not "a modest gain", it is *no gain*, occasionally a small loss, exactly as the GIL predicts. Processes on the same work gave 1.43x, 2.51x and **3.41x**. But the crossover table is the part that changes decisions: for a 14 µs task the process pool was **20x slower than doing it serially** (0.3 ms became 6.6 ms), and even at 219 µs per task it was still losing at 0.82x. Only at 1.5 ms per task did it reach 2.85x. The postage table explains why: a 64-byte argument costs 0.168 ms per round trip, which is already 12x the cost of the 14 µs task itself. `chunksize=10` rescued the tiny case dramatically (6.6 ms → **1.4 ms**) and *hurt* the large one (12.7 ms → 20.1 ms) — batching trades message overhead for load-balancing granularity, and which one you want depends entirely on where you are on this table.

**Section 5 is the failure with no symptoms.** Four workers, four tasks, each submitting one item to its own pool and waiting: **zero of four completed, `inner()` never ran once, queue depth stuck at 4**. There is no exception, no error log, no CPU usage — just a service that has stopped, permanently, with all threads in `Event.wait()`. Both fixes complete the same nested workload in single-digit milliseconds (5.3 ms with two pools, 4.6 ms flattened), which makes the point that the deadlock was never about performance or capacity. It is structural. Adding workers moves the threshold; it does not remove the cycle.

**Section 6 shows that "queue full" has no default answer.** All five policies faced identical load — 360 items at 500/s into a pool that can serve 333/s. `block` and `caller_runs` completed all 360 and paid in wall time (1084 ms and 757 ms against 718 ms for the shedding policies). The three shedding policies each completed 242 and lost 118, and the difference between them is *which* 118: `discard_oldest` served items with a mean age of **14.3 ms** versus **22.4 ms** and **22.2 ms** for the others, because it throws away the stale work rather than the fresh work. If those items are live prices, that difference is the entire product.

## Use It

In production you use `concurrent.futures`, and everything you built maps onto it directly. Your `submit()` is its `submit()`, your `Future` is its `Future`, your `shutdown(drain=)` is its `shutdown(wait=, cancel_futures=)`.

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="db")

# ThreadPoolExecutor's internal queue is UNBOUNDED. Bounding it is your job.
admission = threading.Semaphore(8 + 64)          # workers + the queue depth you chose

def submit_bounded(fn, *args, timeout=0.25):
    if not admission.acquire(timeout=timeout):   # <- the bound, and the backpressure
        raise RuntimeError("pool saturated")     # <- shed load; return 503 upstream
    fut = pool.submit(fn, *args)
    fut.add_done_callback(lambda _f: admission.release())
    return fut

futures = {submit_bounded(fetch, url): url for url in urls}
for fut in as_completed(futures):                # results in COMPLETION order
    try:
        handle(fut.result())
    except TimeoutError:                         # the exception the worker raised,
        log.warning("slow: %s", futures[fut])    # re-raised here, with its traceback

pool.shutdown(wait=True, cancel_futures=True)    # 3.9+: drop the queue, finish in-flight
```

Four details in that snippet are the ones people get wrong:

- **`max_workers` defaults to `min(32, cpu_count + 4)`**, which is a number chosen with no knowledge of your dependency. Set it from your sweep.
- **The internal queue is unbounded.** `ThreadPoolExecutor` uses a `SimpleQueue` with no limit, so `submit()` never blocks and never fails, and Section 2 is what happens next. The semaphore above is the standard fix; an explicit `queue.Queue(maxsize=…)` with your own consumer loop is the other.
- **`as_completed()` yields in completion order; `map()` yields in submission order.** Use `as_completed` when you want to start handling the fast results immediately, `map` when order matters. A subtle one: `map()` re-raises the first exception when you *reach* that element, so a failure in item 0 hides item 1's result until you handle it.
- **`shutdown(cancel_futures=True)`** (Python 3.9+) is `drain=False` — it drops everything still queued and lets in-flight tasks finish. Without it, `shutdown(wait=True)` drains, which during a deploy can mean waiting out an entire backlog.

For the async side, size the executor rather than inheriting the default:

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def main():
    loop = asyncio.get_running_loop()
    loop.set_default_executor(ThreadPoolExecutor(max_workers=8, thread_name_prefix="blocking"))
    rows = await asyncio.to_thread(legacy_driver.query, sql)      # off the loop thread
    # a separate pool per dependency: one slow backend cannot starve the others
    report = await loop.run_in_executor(reports_pool, render_pdf, rows)
```

The equivalents you will meet elsewhere are worth recognising, because they make the same decisions explicit that Python hides:

- **Java's `ThreadPoolExecutor`** takes the `BlockingQueue` and the `RejectedExecutionHandler` as *constructor arguments* — you cannot build one without choosing a bound and a policy. Its four built-in handlers are `AbortPolicy` (reject), `CallerRunsPolicy`, `DiscardPolicy` (discard newest) and `DiscardOldestPolicy` — the same four you built. Note the trap: with an unbounded queue the `maximumPoolSize` and the rejection handler are both dead code, since the queue never fills.
- **Go** has no pool type; the idiom is N goroutines ranging over one buffered channel — `make(chan Job, 64)` *is* the bounded queue, and a send on a full channel blocks, which is the BLOCK policy. `select` with a `default` case gives you REJECT.
- **Celery / RQ** move the queue out of the process entirely, into Redis or a broker — see [Build a Message Queue](../../06-messaging-and-pub-sub/03-build-a-message-queue/). That buys durability across restarts and independent scaling of consumers, at the cost of serialisation and a network hop.

Production rules, in the order they will save you:

- **Always bound the queue, and always set a submit timeout.** An unbounded queue plus a blocking submit is a hang; an unbounded queue plus a non-blocking submit is an OOM. The bound is the only thing that makes overload visible while you can still act on it.
- **Never block on the pool you are running inside.** If you cannot guarantee that, use a second pool. A single `.result()` call in a task is enough to freeze the service, and it will not fail in testing.
- **One pool per dependency — bulkheads.** A pool shared between the payments API and the reporting database means a slow report starves every payment. Separate pools convert a dependency outage into a degraded feature instead of a total outage. Lesson 11 develops this.
- **Export queue depth *and* queue time, and alert on the time.** Depth is a count with no units of meaning; time is directly comparable to your latency budget and it moves first. Add a rejection counter — a gauge can miss a spike between scrapes, a counter cannot.
- **Size from measurement, not intuition, and re-measure when the dependency changes.** Your pool size is a concurrency limit on something else. When that something else gets a bigger connection pool, or a new index, or moves regions, your correct pool size changed and nothing told you.

## Think about it

1. Your pool has 16 workers and a 1,000-item bounded queue. Queue depth sits at 950 all day and nothing has ever been rejected. Your p99, measured inside the task function, is 4 ms. What is the actual latency your users experience, and what is the smallest change that would have made this visible?
2. You are told to raise `max_workers` from 8 to 64 because "the service is slow". Given Section 3's curve, what single measurement would you take first, and what would you expect to see if the diagnosis were right — as opposed to what you would expect to see if the dependency were already saturated?
3. A pool handles image thumbnailing, 40 ms of CPU-bound work per image in a C library that releases the GIL. Threads or processes? Now the library is replaced with a pure-Python implementation at the same 40 ms. Does your answer change, and what number from Section 4 decides it?
4. You choose DISCARD_OLDEST for a queue of outbound webhooks because the queue keeps filling. Six months later a customer asks why some webhooks never arrived. What went wrong at the design stage, and which policy should it have been?
5. Your service runs an event loop and calls `asyncio.to_thread` in three places: a slow S3 upload, a fast local file read, and a database query. All three share the default executor. Describe the failure mode when S3 has a bad afternoon, and give two different fixes with their trade-offs.

## Key takeaways

- **A pool replaces "one thread per item" with a fixed worker count, a bounded queue and a Future per item**, and each of the three fixes a distinct failure: creation cost paid once instead of per item, thread count set by your capacity instead of your arrival rate, and exceptions delivered to the caller instead of printed to stderr — the Build It confirms a worker's `ValueError` reaching the submitter with **4 stack frames** of traceback intact.
- **An unbounded queue is not a buffer, it is a delay line with an OOM at the end.** Under identical overload the unbounded run grew to **1,712 queued items and 9.3 MiB in one second** (a 2 GiB container dies in ~4 minutes) with latency climbing **38 ms → 657 ms** and still rising, and **1,708 items accepted and never run**; a 64-slot bound held latency flat at **38 → 90 ms** and converted the overload into a visible slowdown of the submitter from 2,473/s to 828/s.
- **More workers is not monotonically better.** Sweeping 1→64 workers against a dependency that serves 8 at a time, throughput peaked at **813/s with 8 workers** and fell to **396/s (49%) at 64**, while p99 rose **10.3 → 166.6 ms (16x)** — all of it queueing at the dependency (0.0 ms → 132.0 ms). **A pool size is a concurrency limit on whatever the pool calls, not a speed dial.** Little's Law (`L = λW`) gives the starting point and keeps balancing even at 64 workers; only the measured curve tells you where to stop.
- **In CPython, threads never help CPU-bound work** — measured **0.93x–1.01x** at 2, 4 and 8 workers, against **3.41x** for 8 processes. But processes charge postage: a 14 µs task ran **20x slower** through a process pool (0.3 → 6.6 ms), and the crossover sits between roughly 0.2 ms and 1.5 ms of work per task. `chunksize` cut the tiny case to 1.4 ms and made the large case *worse*.
- **Blocking on the pool you are running inside is a guaranteed deadlock, not a race.** Four workers, four nested tasks: **0 of 4 done, `inner()` never started, no error of any kind.** Bigger pools only raise the trigger threshold. Fix it structurally — separate pools per tier (5.3 ms) or no blocking at all (4.6 ms).
- **Export queue *time*, not just queue depth, and choose a rejection policy deliberately.** Depth is a count with no meaning absent a service rate; queue time is comparable to your latency budget and moves first. Under identical overload `block` completed all 360 items in 1084 ms while the shedding policies completed 242 in 718 ms — and `discard_oldest` served data with a mean age of **14.3 ms** against **22.4 ms**, which is the whole difference between fresh and stale for live data.

Next: [Race Conditions, Atomicity & Critical Sections](../08-race-conditions-and-atomicity/) — what happens when the workers in that pool stop being independent and start touching the same memory, and why `counter += 1` is three operations pretending to be one.
