# Capstone: Make a Slow Service Fast

> You inherit a service that is correct, reviewed, in production, and serves **11.5 requests per second** on a machine with ten idle cores. Nobody has ever profiled it. Over nine stages you will take it to **794 requests per second** and a p99 of **27 ms** — but the number that matters is not the speedup, it is that every single step was decided by a measurement. One stage makes it faster and silently wrong. One stage does nothing at all and gets reverted. That is what a real performance investigation looks like.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Concurrency](../01-why-concurrency/) · [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/) · [Blocking vs Non-Blocking I/O](../03-blocking-vs-non-blocking-io/) · [The Event Loop](../04-the-event-loop/) · [Coroutines & async/await](../05-coroutines-and-async-await/) · [Structured Concurrency & Cancellation](../06-structured-concurrency-and-cancellation/) · [Thread Pools & Work Queues](../07-thread-pools-and-work-queues/) · [Race Conditions & Atomicity](../08-race-conditions-and-atomicity/) · [Locks & Coordination Primitives](../09-locks-and-coordination-primitives/) · [Deadlock, Livelock & Starvation](../10-deadlock-livelock-and-starvation/) · [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/) · [Connection & Resource Pooling](../12-connection-and-resource-pooling/) · [Profiling](../13-profiling/) · [Benchmarking & Load Testing](../14-benchmarking-and-load-testing/)
**Time:** ~100 minutes

## The Problem

The ticket says: *"checkout is slow, please make it faster."* It is assigned to you because the person who wrote the service left.

Here is everything you know on day one. The service handles one endpoint. It works — the outputs are right, the tests pass, there are no errors in the logs, and the error rate on the dashboard is a flat **0.00%**. Traffic is about **40 requests per second** and product would like to double it next quarter. The box it runs on has ten cores and its CPU graph sits around 5%. And the service's own latency dashboard says **p99 = 93 ms**, which everybody agrees is fine, while support keeps forwarding emails from users who waited five seconds and gave up.

Two of those facts cannot both be true, and finding out which one is lying is the first job. There is a second problem, and it is the one that actually sinks people. Everyone on the team already knows what is wrong. The senior engineer is certain it is `score_items()`, the scoring function, because it is the only loop in the file and it "looks expensive". Somebody else wants to raise the thread count. Somebody else has been asking for a bigger connection pool for a year. Three theories, three deploys, three weeks, and no way to tell afterwards which of them helped — because nobody wrote down a number before they started.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 580" width="100%" style="max-width:940px" role="img" aria-label="The inherited request path drawn end to end: an unbounded queue feeds twenty-four worker threads, each of which takes one global lock and holds it across eleven sequential upstream calls on eleven fresh connections, including an N plus one loop of eight item fetches, a CPU-bound scoring step and an unguarded counter increment. Seven numbered flaws are marked on the path and listed on the right with the lesson that diagnoses each.">
  <defs> <marker id="l15-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker> </defs>
  <text x="490" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The service you inherited — 11.5 req/s, and every flaw is one a real team has shipped</text> <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M155 84 L155 100" marker-end="url(#l15-a1)"/> <path d="M155 148 L155 164" marker-end="url(#l15-a1)"/> <path d="M155 200 L155 222" marker-end="url(#l15-a1)"/> <path d="M155 490 L155 508" marker-end="url(#l15-a1)"/> </g> <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="50" width="250" height="34" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/> <rect x="30" y="104" width="250" height="44" rx="9" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/> <rect x="30" y="164" width="250" height="36" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <rect x="22" y="228" width="598" height="262" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-dasharray="7 5"/> <rect x="40" y="262" width="440" height="28" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="40" y="296" width="440" height="28" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/> <rect x="40" y="330" width="440" height="28" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="40" y="368" width="500" height="32" rx="7" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/> <rect x="40" y="410" width="440" height="28" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/> <rect x="40" y="448" width="440" height="28" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="30" y="508" width="250" height="34" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/> <rect x="648" y="46" width="312" height="498" rx="12" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.45"/> </g>
  <path d="M494 262 L504 262 L504 358 L494 358" fill="none" stroke="#e0930f" stroke-width="1.8"/> <g stroke-width="1.7"> <circle cx="300" cy="126" r="10" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/> <circle cx="58" cy="276" r="10" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
    <circle cx="530" cy="310" r="10" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff"/> <circle cx="562" cy="384" r="10" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/> <circle cx="58" cy="424" r="10" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
    <circle cx="58" cy="462" r="10" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/> <circle cx="46" cy="246" r="10" fill="#e0930f" fill-opacity="0.24" stroke="#e0930f"/> </g> <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor"> <g font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="300" y="130">5</text><text x="58" y="280">3</text><text x="530" y="314">1</text> <text x="562" y="388">4</text><text x="58" y="428">6</text><text x="58" y="466">7</text><text x="46" y="250">2</text> </g> <text x="46" y="72" font-size="11">arrivals — 40 req/s, open loop</text>
    <text x="46" y="124" font-size="11" font-weight="700">queue.Queue(maxsize=0)</text> <text x="46" y="140" font-size="9" opacity="0.8">unbounded — no maxsize, no deadline</text> <text x="46" y="187" font-size="11">24 worker threads</text>
    <text x="66" y="250" font-size="11" font-weight="700" fill="#e0930f">one global lock — taken here, released 89 ms later</text> <text x="78" y="281" font-size="10.5">connect → GET /profile</text><text x="452" y="281" font-size="10" text-anchor="end" opacity="0.85">8 ms</text>
    <text x="78" y="315" font-size="10.5">connect → GET /settings</text><text x="452" y="315" font-size="10" text-anchor="end" opacity="0.85">7 ms</text> <text x="78" y="349" font-size="10.5">connect → GET /items  →  8 ids</text><text x="452" y="349" font-size="10" text-anchor="end" opacity="0.85">9 ms</text>
    <text x="546" y="298" font-size="9" fill="#3553ff" font-weight="700">nothing</text> <text x="546" y="311" font-size="9" fill="#3553ff" font-weight="700">here needs</text> <text x="546" y="324" font-size="9" fill="#3553ff" font-weight="700">to be serial</text>
    <text x="78" y="388" font-size="10.5" font-weight="700">for id in ids:  connect → GET /item/{id}   × 8</text> <text x="512" y="388" font-size="10" text-anchor="end" opacity="0.85">42 ms</text> <text x="78" y="429" font-size="10.5">score_items() — 1.6 ms of pure Python, holds the GIL</text>
    <text x="78" y="467" font-size="10.5">stats.record():  n = n + 1   ← safe only by accident</text> <text x="46" y="530" font-size="11">upstream dependency — knee at 32</text> <text x="804" y="72" font-size="12" font-weight="700" text-anchor="middle">SEVEN FLAWS, AND WHO DIAGNOSES THEM</text> <g font-size="10">
      <text x="666" y="104" font-weight="700">1 · sequential blocking I/O</text> <text x="678" y="119" opacity="0.82">three independent calls, run one at a time</text> <text x="678" y="133" opacity="0.6">Lessons 3 &amp; 5 — blocking I/O, async/await</text>
      <text x="666" y="166" font-weight="700">2 · one global lock, held across I/O</text> <text x="678" y="181" opacity="0.82">86.6% of all thread time waits on it</text> <text x="678" y="195" opacity="0.6">Lesson 9 — locks and critical sections</text> <text x="666" y="228" font-weight="700">3 · no connection pooling</text>
      <text x="678" y="243" opacity="0.82">11 handshakes per request; 45% of wall time</text> <text x="678" y="257" opacity="0.6">Lesson 12 — connection and resource pools</text> <text x="666" y="290" font-weight="700">4 · N+1: one call, then one per item</text>
      <text x="678" y="305" opacity="0.82">8 extra round trips; a call COUNT finds it</text> <text x="678" y="319" opacity="0.6">Lessons 7 &amp; 13 — work queues, profiling</text> <text x="666" y="352" font-weight="700">5 · unbounded queue, no timeouts</text>
      <text x="678" y="367" opacity="0.82">accepts 3x capacity, answers far too late</text> <text x="678" y="381" opacity="0.6">Lessons 6 &amp; 11 — deadlines, backpressure</text> <text x="666" y="414" font-weight="700">6 · CPU-bound step on the request path</text>
      <text x="678" y="429" opacity="0.82">holds the GIL: 96 threads = the same as 24</text> <text x="678" y="443" opacity="0.6">Lesson 2 — processes, threads and the GIL</text> <text x="666" y="476" font-weight="700">7 · a latent race in the counter</text>
      <text x="678" y="491" opacity="0.82">invisible now; loses 47% of updates later</text> <text x="678" y="505" opacity="0.6">Lesson 8 — race conditions and atomicity</text> </g>
    <text x="490" y="570" font-size="11" text-anchor="middle" opacity="0.9">Correct, shipped, reviewed, and 11.5 req/s on a machine with ten idle cores. Nobody had ever profiled it.</text> </g> </svg>
```

That is the service, drawn honestly. Seven flaws, each one shipped by a real team on a real Tuesday: a handler that makes eleven sequential blocking calls that could have been three concurrent ones; one global lock held across every one of them; a fresh connection and handshake per call; an N+1 loop that fetches a list and then each item in it; an unbounded work queue with no deadline anywhere; a CPU-bound step on the request path; and a counter increment that is not atomic and does not currently matter.

None of these is exotic. Each one is what you get when a reasonable change is made to a reasonable codebase without anyone measuring afterwards. And note the last one especially: **it is not a bug today.** The global lock serialises every request, so the unguarded counter is only ever touched by one thread at a time — it is a bug waiting for you to make the service fast. This lesson is the investigation. Not the fixes — you already know the fixes, they are the previous fourteen lessons. The investigation: how to decide **what to change first**, how to know whether a change **worked**, how to notice when a change made things faster and **wrong**, and how to recognise the moment when the next improvement is smaller than your measurement error and the honest move is to stop.

## The Concept

### "Fast" is meaningless. An SLO is the only definition that survives a meeting

You cannot optimise toward "faster" because there is no state of the world in which you are done. You can optimise toward a **service level objective** — an SLO, a specific promise about a specific number over a specific window:

```text
99% of requests complete in under 250 ms, at the 40 requests/second we
actually receive, with an error rate below 1%.
```

Every word is load-bearing. **99%** names the percentile, so a beautiful median cannot hide a horrible tail. **250 ms** is a number a product person agreed to. **At 40 req/s** ties it to a load, because latency without a load is not a claim about anything. And the **error budget** stops you from meeting the latency target by failing fast — which is a real optimisation, and a real cheat, unless you count it.

An SLO also tells you when to stop, which is the part nobody teaches: once you are inside it with headroom, further optimisation is not free work you are doing for the users, it is engineering time you are spending on a number nobody is measuring.

### The three numbers: throughput, goodput, and the tail

**Throughput** is responses per second — the number engineers quote, and the least interesting of the three, because a service can produce a magnificent throughput of answers that arrived too late to be useful. **Goodput** is responses per second that were *actually useful*: delivered inside the deadline the caller cared about. Under overload later in this lesson, throughput sits at **802 responses/second** while goodput sits at **115**. The machine is flat out and achieving almost nothing, and only one of those two numbers noticed.

**The tail** is p99: the value 99% of requests come in under — not the mean, which describes nobody, and not the p50, which describes the lucky. When your service is called by a service that is called by a service, the tail is what compounds.

### Coordinated omission: the measurement mistake that hides the whole problem

Here is how the service's dashboard came to say 93 ms while users waited five seconds.

A **closed-loop** load test uses a fixed number of virtual clients, each of which sends a request, waits for the response, then sends the next one. It is the easy way to write a load generator and it is what most people write. It also has a fatal property: **when the service slows down, the load generator slows down with it.** The requests that would have arrived during the stall are never sent, their latency is never recorded, and the tool politely omits exactly the measurements that would have shown the problem — hence Gil Tene's name for it, *coordinated omission*. An **open-loop** test fixes the arrival schedule in advance — request *k* is due at `t0 + k/rate`, whatever the service is doing — and measures each request's latency **from its intended arrival time**, not from when a worker finally picked it up. Real users are open loop; they click when they click.

In the Build It, the same service under the same code measures **p99 = 92 ms** closed loop and **p99 = 5,515 ms** open loop — a factor of **60**. Neither is a bug in the service; one is a bug in the measurement. The service's own instrumentation makes the identical mistake for the identical reason: its timer starts *after* the handler acquires the global lock, so it measures work and never the queue in front of the work, reporting **92.8 ms** for a request that is **5,515 ms** old. If your latency histogram starts after `lock.acquire()` — or after `pool.get_connection()`, or after the framework's queue — it is structurally incapable of seeing your worst outage.

### Amdahl's law is the arithmetic that ends arguments

Amdahl's law, in the only form you need at work: if a component is fraction **p** of the total time, making it *infinitely fast* — free, zero, gone — speeds the whole thing up by at most

```text
speedup ≤ 1 / (1 − p)
```

That is a ceiling, not an estimate — what you get for perfect success. So when the senior engineer says the scoring function is the problem, you do not argue: you profile, find that `score_items()` is **6.2% of the wall clock**, and observe that deleting it entirely buys **1.07×** against a ticket that asked for 3×. The argument is over, and nobody had to be persuaded of anything. Amdahl also explains why the order of your fixes matters: every fix you land changes the denominator, so the ceiling on every *other* candidate moves. Recompute after each stage — the thing worth 1.1× at the start can be worth 3× once the thing in front of it is gone.

### Wall-clock time and CPU time are different questions

A profiler answers one of two questions and you must know which. **On-CPU profiling** asks "which code is burning the processor?" **Wall-clock profiling** asks "where is the request's *time* going?" For a service that spends its life waiting on other computers, those answers can be near-disjoint: in the Build It, `score_items()` is **100% of the on-CPU samples and 6.2% of the wall clock.** A CPU profiler ranks it first, a wall-clock profiler ranks it fifth, and the first tool would have sent the team to rewrite it in C for a 1.07× win.

And there is a third question neither profiler answers, which is the one that finds the biggest bug in this service: **how many times was it called?** A flat profile says `connect` is 45.6% of the wall clock, which sounds like an argument for pooling. The **call count** — 11 connections per request — says that eight of those eleven exist only because the handler is looping over items one at a time. Same measurement, completely different fix. Percentages tell you where the time is; counts tell you *why*.

### Little's Law: the equation behind every queue you will ever tune

For any stable system, **L = λ × W** — the average number of items in the system equals the arrival rate times the average time each spends inside. It is almost embarrassingly simple and it silently governs every thread pool, connection pool and queue depth you will ever pick.

Read forwards it sizes a pool: a service handling 40 requests/second that holds a connection for 32 ms needs `40 × 0.032 = 1.3` connections busy on average. Read backwards it explains a latency regression: at saturation throughput is pinned at capacity, so `W = L / λ` says **latency is directly proportional to how many requests you allow in flight** — doubling your worker count at saturation does not double throughput, it doubles latency. In stage 7 that prediction lands within a factor of two of the measurement: 24 in flight over 794 req/s predicts 30 ms, 128 in flight over 791 predicts 162 ms, and the measured service-time p99 goes 46 ms → 265 ms.

### The fix-one-thing loop

The whole method, and it is short:
1. **Measure a baseline** you would defend in a review. Open loop, at a stated rate, reporting throughput, goodput, p50, p99 and errors.
2. **Localise** with a profile and a call count. Not a guess, not a hunch, not the file that looks expensive.
3. **Predict** — write down the expected magnitude *before* you change anything, from the Amdahl ceiling. This is the step everyone skips, and it is the only thing that makes the next step meaningful.
4. **Change exactly one thing.**
5. **Re-measure the same way.** Compare to the prediction. A result far under the prediction means you fixed something else. A result far over it means your baseline was wrong.
6. **Verify correctness**, every time, because speed uncovers bugs.
7. **Keep or revert**, then go back to 2 — with a fresh profile, because the profile has changed.

Steps 3 and 6 are what separate this from guessing: without 3 you cannot tell a real win from noise, and without 6 you will eventually ship a service that is fast and wrong, which is worse than the one you started with.

## Build It

Three files. [`code/slow_service.py`](code/slow_service.py) is the service — every pathology behind a flag on one `Stage` dataclass, so the same handler code serves every version and nothing drifts between runs. [`code/harness.py`](code/harness.py) is the measuring apparatus: the open-loop generator and a sampling profiler. [`code/run_capstone.py`](code/run_capstone.py) drives the nine stages and prints the final table.

```bash
python3 run_capstone.py
```

The handler is one function whose shape is decided by flags. This is the whole service:

```python
def handle(self, req: Request) -> int:
    st = self.stage
    if not st.narrow_lock:
        _acquire_global(self.glock, self.lock_waits, self._lw)   # held to the end
    req.work_start = perf()          # a naive in-service timer starts HERE
    try:
        if st.concurrent:
            futs = (self.fan.submit(self.fetch_profile),
                    self.fan.submit(self.fetch_settings),
                    self.fan.submit(self.fetch_list))
            for f in futs:
                f.result()
        else:
            self.fetch_profile(); self.fetch_settings(); self.fetch_list()
        if st.batch:
            self.fetch_items_batch(req.ids)
        else:
            for item_id in req.ids:              # <- N+1: one call per item
                self.fetch_item(item_id)
```

Note `req.work_start`: that is not instrumentation for us but the service's own latency timer, started where a real service would start it, and it is how we reproduce the 93 ms dashboard. The load generator below is the lesson-14 correction in ten lines — every request's `intended` time is fixed **before the run begins**, so a slow service cannot bend the schedule:

```python
    for i, r in enumerate(reqs):
        r.intended = t0 + i / rate          # the schedule, fixed before we start
    # One dispatcher thread cannot reliably emit more than a few hundred
    # arrivals a second; past that the generator becomes the bottleneck and
    # silently understates the load. Split the schedule across several.
    nd = max(1, min(8, int(rate // 250)))
```

and latency is `done − req.intended`, never `done − dequeued`. The comment matters too: at the overload rates in stage 8 a single-threaded generator becomes the bottleneck and quietly reports a load it never produced — a load generator is a distributed system and it lies in exactly the ways one does. The race itself lives in the statistics counter, and both versions are in the file so the fix can be measured rather than asserted:

```python
    def record(self, nbytes: int) -> None:
        with self._truth:
            self.true_calls += 1          # ground truth, always guarded
        if self.safe:
            with self._lock:              # the fix: make the RMW atomic
                tmp = self.calls
                _widen()
                self.calls = tmp + 1
        else:
            tmp = self.calls              # read  --+
            _widen()                      #         +- another thread lands here
            self.calls = tmp + 1          # write --+  and its increment is lost
```

`_widen()` calls `time.sleep(0)`, which forces CPython to hand the GIL to another thread in the middle of the read-modify-write. **We widened the window deliberately**, and you should know that: a real window here is a few nanoseconds and a real system loses an update every few days. Widening does not create the bug, it makes the bug punctual. That is a legitimate testing technique, and it is the only way to write a lesson whose stage 3 fails on every reader's machine.

The profiler is a background thread reading `sys._current_frames()` every 3 ms, walking each stack to the first frame it recognises (`_classify`), and marking the sample **off-CPU** if the innermost frame is one of the known blocking helpers — that one distinction is the whole difference between a wall-clock profile and a CPU profile. It comes with one wrinkle worth its own paragraph, because it is a trap you will hit the first time you write a profiler in Python. **The profiler is itself a thread competing for the GIL.** While a CPU-bound function runs, the sampler cannot be scheduled until the interpreter's switch interval expires — 5 ms by default — so it systematically under-samples exactly the code that is burning CPU. Measured while building this lesson, on the same profiled run: `score_items()` reported **0.3%** of wall time with the default 5 ms switch interval and **2.8%** after dropping it to 0.5 ms, against a directly-timed truth of about 2.9%. The number is recorded in `harness.py`'s docstring so nobody has to rediscover it. `SamplingProfiler.start()` shortens the interval and `stop()` puts it back. Your profiler is part of the system it measures.

Now the investigation.

### Stage 0 — a baseline you would defend in a review

```console
== 0 . BASELINE, MEASURED HONESTLY ==
  SLO      p99 <= 250 ms and errors < 1% at 40 req/s offered
  method   open loop: arrivals on a clock, latency measured from the
           INTENDED arrival time, not from when a worker got round to it
  caveat   72 requests per stage, so the reported p99 IS the worst request
           observed. Read it as 'the tail', not as a stable percentile.
  handler  11 sequential upstream calls on 11 fresh connections,
           one global lock held across all of it, one CPU scoring step
  score_items(4000 rounds) = 1.60 ms of CPU per request
  0 baseline                 thr   11.5/s  good    0.8/s  p50  2186.0ms  p99   5514.8ms  err   0.0%  ok
    72 requests offered at 40/s; 72 completed in 6.3s -> 11.5 req/s is the real capacity
    p99 wait for the global lock        5427.9 ms
    p99 as the SERVICE times it           92.8 ms  <- its own dashboard
    p99 as the USER experiences it      5514.8 ms  <- 59x worse
  ...
    latency histogram, 72 responses, buckets in ms:
         10    15    25    40    60   100   160   250   400   630  1000  1600  2500  4000  6300 10000   +inf
          0     0     0     0     0     1     2     2     5     7     4     7    13    20    11     0     0
  the same service measured the WRONG way (closed loop, 1 client, 14 reqs):
    p50 89.1 ms   p99 92.4 ms   throughput 11.5/s -- 'p99 is 92 ms, we are fine'
    coordinated omission: the client never sent request k+1 until k came
  ...
```

Read the first line as an accusation. We offered 40 requests/second and got **11.5** back: the service is not "slow", it is **overloaded at a third of its traffic**, and everything after that follows — the queue never drains, latency is dominated by queueing, p50 is 2.2 seconds and the tail reaches 5.5.

Now the three views of the same request, which is the most important block in this lesson. The **closed-loop** test says p99 = 92 ms. The service's **own timer** says 92.8 ms — and of course it does, it is measuring the same thing, the work after the wait. The **user** experiences 5,515 ms. Two independent instruments, both careful, both wrong in the same direction, because both of them start the clock after the queue. The whole error is 60×, and it is invisible from inside the service.

One honesty note the harness prints itself: with 72 requests per stage, the reported p99 **is** the slowest request observed. That is a weak percentile and you should read it as "the tail", not a stable estimate. Saying so is not a disclaimer, it is the job — a benchmark that does not tell you its sample size is asking to be believed rather than checked.

### Stage 1 — profile before touching anything

```console
== 1 . PROFILE BEFORE TOUCHING ANYTHING ==
  (a) UNDER LOAD -- 10436 stack samples across every request thread
      WAIT  global lock                     86.6% of wall clock
      connect  (TCP+TLS handshake)           4.7% of wall clock
      other Python                           2.9% of wall clock
      one lock owns almost all of the wall clock. That is a CONTENTION
  ...

  (b) ONE REQUEST AT A TIME -- 8024 samples, 14 requests, budget 89 ms
      WHERE THE TIME IS                    wall%    cpu%  calls/req
      connect  (TCP+TLS handshake)          45.6     0.0       11.0
      GET /item/{id}                        25.6     0.0        8.0
      GET /items                             8.4     0.0        1.0
      GET /profile                           6.2     0.0        1.0
      score_items()  [CPU]                   6.2   100.0          -
      GET /settings                          5.0     0.0        1.0
      stats.record()  [race window]          2.8     0.0          -

  AMDAHL CEILINGS -- the most a change could possibly buy, from (b)
      if you made this free                      wall%   max speedup
      the N+1: item calls + their connects        58.8         2.43x
      every connection handshake                  45.6         1.84x
      the two overlappable calls                  11.2         1.13x
      score_items() -- the standing theory         6.2         1.07x
      the red herring: score_items() is 6.2% of the WALL clock and 100% of
  ...
      the tell no flat profile prints: 112 item fetches across 14 requests
      = 8.0 calls per request. That is an N+1, and it is the biggest number here.
```

Two profiles, because they answer different questions, and confusing them is how investigations go sideways. Profile **(a)** is taken under real load and says one thing: **86.6% of all thread time is spent waiting for a single lock.** That is a genuine and important finding, and it is *not* a cost signal. It tells you where requests wait; it says nothing about what they are waiting for. If you optimise from profile (a) alone your only possible conclusion is "remove the lock", and you would never find the N+1 — which is the thing making the lock so expensive to hold in the first place.

Profile **(b)** removes the queueing by running one request at a time, and shows the request's actual time budget. Now `connect` is 45.6%, the item fetches are 25.6%, and — the line that matters — **11 connections and 8 item fetches per request.** No percentage in that table announces "N+1"; the call count does.

Then the arithmetic. Killing the N+1 removes eight item calls and their eight handshakes: **58.8% of the budget, ceiling 2.43×**. Pooling every connection is 45.6%, ceiling 1.84×. Overlapping the two independent calls is 11.2%, ceiling 1.13×. And `score_items()`, the theory everyone came in with, is 6.2% of the wall clock and **100% of the on-CPU samples** — a rewrite in C, executed perfectly, buys **1.07×**. Nobody has to lose an argument; the table just ends it. That is what "argue with measured numbers" buys you politically, not just technically.

### Stage 2 — kill the N+1

```console
== 2 . KILL THE N+1 ==
  hypothesis: 8 item calls -> 1 batch call deletes 8 handshakes and 8 round
  trips. Amdahl ceiling from (b): 2.43x. The batch call is not free (it is still a
  connect plus a round trip), so predict a little under that.
  2 batch the N+1            thr   23.3/s  good    7.1/s  p50   433.8ms  p99   1890.6ms  err   0.0%  ok    (2.03x throughput)
    predicted <= 2.43x, measured 2.03x. throughput 11.5 -> 23.3 req/s, p99 5515 -> 1891 ms. KEEP.
    still 8x over the 250 ms SLO. One fix is never the fix.
```

Predicted at most 2.43×, measured **2.03×** — close under the ceiling, which is what a correctly-diagnosed fix looks like. The gap is the batch call itself: it still costs a handshake and a round trip, so we did not get the full 58.8% back. Had we measured 4×, the honest response would be alarm, not celebration, because a result above the ceiling means the baseline was wrong. And note the second line: throughput doubled, the tail dropped by two thirds, and we are still **8× outside the SLO**. This is the most common way performance work goes wrong emotionally — the first fix feels like a triumph and people stop. One fix is never the fix.

### Stage 3 — concurrency, and the bug it uncovers

```console
== 3 . SEQUENTIAL -> CONCURRENT I/O, AND THE BUG IT UNCOVERS ==
  the three remaining calls do not depend on each other. Fan them out.
  3 concurrent I/O           thr   39.9/s  good   39.9/s  p50    42.9ms  p99     53.7ms  err   0.0%  WRONG (1.71x)
    faster -- and WRONG. upstream_calls_total reads 153; the true count is 288.
    135 increments vanished (47% of them). The metric now under-reports every
    dashboard, alert and capacity model that reads it.
    diagnosis: CallStats.record() is a read-modify-write. The global lock
    serialised REQUESTS, so it was atomic BY ACCIDENT. Nothing serialises
  ...
  3b + lock the counter      thr   39.7/s  good   39.7/s  p50    39.9ms  p99     83.5ms  err   0.0%  ok    (1.70x)
    counter reads 288 against 288 true. Throughput 39.9 -> 39.7 req/s:
  ...
    saturating probe: capacity 23 -> 40 req/s, and at saturation the p99
    wait for the global lock is 1714 ms. That is the next thing to attack.
```

**This is the most important stage in the lesson, and the win is not the 1.71×.** Look at the correctness column: `WRONG`. The service is faster, the latency is inside the SLO for the first time, the error rate is 0.00%, every response body is correct — and `upstream_calls_total` reports **153 calls when 288 actually happened**. 47% of the increments evaporated. Every dashboard, every alert threshold, every capacity model built on that metric is now wrong by half, and *nothing* in the system will tell you.

The diagnosis is the phase's punchline. `CallStats.record()` does `n = n + 1` — a read, a modify and a write, three operations another thread can land between (Lesson 8). It was never atomic; it was **safe by accident**, because the global lock serialised entire requests so only one thread was ever inside it. The moment we fanned three calls out to a thread pool, three threads inside *one* request began racing each other, and the lock that had been accidentally protecting the counter was protecting nothing at all. Sit with that, because it generalises past this counter. **A lock protects only what it is actually held across, and if you cannot say out loud which invariant a lock defends, you do not know what it protects — you know what it currently happens to prevent.** Every concurrency change you ship re-tests every one of those accidents at once.

The fix is a dedicated lock around the counter (Lesson 9), and the measurement makes the trade explicit: **39.9 → 39.7 req/s**, indistinguishable from noise. Correctness was free because the critical section is one increment and not a network call — the same lesson as stage 4 in miniature. It is not "locks are slow", it is *scope*. And the number that sets up the next stage: at saturation the p99 wait for the global lock is **1,714 ms**.

### Stage 4 — get the I/O out from under the lock

```console
== 4 . GET THE I/O OUT FROM UNDER THE GLOBAL LOCK ==
  measured: p99 wait for the global lock is 5428 ms at baseline and 1714 ms
  at saturation even after stages 2 and 3, because it is still held across
  every network call. Shrink it to the index write itself; shard 16 ways.
  4 shrink+shard the lock    thr   40.0/s  good   40.0/s  p50    30.3ms  p99     39.0ms  err   0.0%  ok    (capacity 484/s)
    p99 lock wait at saturation 1714 ms -> 0.00 ms: it is gone.
    p99 end to end at 40 req/s 83.5 ms -> 39.0 ms -- but the offered load is the
    ceiling on that number now, so latency has stopped being the interesting measurement.
  ...
    informative. Saturating probe instead: capacity 40 -> 484 req/s (12.2x),
    which is 42x the 11.5 req/s we started with. Biggest single win of the run.
```

**12.2× — the single biggest win in the investigation, and it deletes no work whatsoever.** Every call the service made before, it still makes; all that changed is *when the lock is held*. Instead of wrapping the entire request it now wraps only the index write, and the index is sharded into 16 stripes so writes to different keys do not contend at all. The p99 lock wait goes from **1,714 ms to 0.00 ms**. This is why "the lock is slow, replace it with a faster lock" is almost always the wrong instinct. `threading.Lock` was never the problem; holding it across eleven network round trips was. A critical section should contain the smallest number of instructions that preserve the invariant, and **network calls are never among them** — that is Lesson 9's rule and this is what it is worth in requests per second.

Note the methodological shift in the last lines, because it recurs on every real investigation. At 40 req/s the service is now so far inside its capacity that the queue is always empty, so measured throughput just equals the offered rate no matter what we do next: the instrument has stopped responding. From here we measure **capacity** with a saturating probe, and latency at the SLO rate becomes a pass/fail check rather than a dial.

### Stage 5 — pool the connections, sized from the curve

```console
== 5 . POOL THE CONNECTIONS, SIZED FROM THE CURVE ==
  every call still pays a handshake. Reuse connections instead -- but
  size the pool from a measurement, not from a round number.
       pool size   capacity req/s   p99 service ms  peak upstream
               2               75            578.9              2
               4              154            248.5              4
               8              309            121.6              8
              16              495             70.1             16
              32              490            135.3             32
      the curve: 75 -> 154 -> 309 -> 495 -> 490 req/s across pool sizes 2, 4, 8, 16, 32.
  ...
      Little's Law sizes it: at pool 16 the service sustains 495 req/s, so a request holds
      32 ms of connection time; serving the 40 req/s we actually get needs 1.3 connections.
  5 pool (size 16)           thr   40.1/s  good   40.1/s  p50    18.8ms  p99     25.7ms  err   0.0%  ok    (capacity 499/s)
    capacity 484 -> 499 req/s: unchanged within the noise. The ceiling was never the handshakes.
    p50 30.3 -> 18.8 ms, p99 39.0 -> 25.7 ms, p99 pool wait 0.02 ms.
    pooling bought LATENCY, not capacity. Both are worth buying; confusing
  ...
```

The curve is the deliverable here, not the pool. Capacity climbs steeply while the pool is the binding constraint — 75, 154, 309 — and then flattens as something else becomes one, in this case the interpreter, which was already serving 484 req/s with no pool at all. **The knee is where you stop buying.** Then size it from the measurement rather than a round number. Little's Law backwards: at pool 16 the service sustains 495 req/s, so each request occupies `16 / 495 = 32 ms` of connection time, and the 40 req/s we actually receive therefore needs `40 × 0.032 = 1.3` connections on average. We take **16** — an order of magnitude more than the measured need, which is burst headroom, and still at or below the dependency's own knee of 32 concurrent, the ceiling you must not cross because past it you are queueing inside someone else's database. And read the verdict carefully, because it is the sort of thing people misreport in standups: **capacity did not move** (484 → 499 is inside the noise) but **p50 fell 38% and p99 fell 34%**. Pooling bought latency, not throughput, because the ceiling was never the handshakes. Both are worth buying. Claiming the wrong one is how a team ends up with a folk belief that pooling "fixes capacity" and then a year later cannot explain why raising the pool did nothing.

### Stage 6 — the CPU-bound step

```console
== 6 . THE CPU-BOUND STEP ==
  score_items() is 1.6 ms of pure Python. It holds the GIL (Global
  Interpreter Lock), so more threads cannot make it parallel. Prove that
  before spending anything on it:
       24 worker threads -> capacity    515 req/s   p99 service   68.0 ms
       96 worker threads -> capacity    519 req/s   p99 service  301.7 ms
  6 CPU -> process pool      thr   40.1/s  good   40.1/s  p50    18.8ms  p99     27.2ms  err   0.0%  ok    (capacity 794/s)
    4 processes dodge the GIL: capacity 499 -> 794 req/s (1.59x)
    three probes of the SAME build: 792, 794, 799 req/s -- a 1% spread.
  ...
    p99 at 40/s: 25.7 -> 27.2 ms -- barely moved. This bought HEADROOM,
  ...
    latency histogram, 72 responses, same buckets as stage 0:
         10    15    25    40    60   100   160   250   400   630  1000  1600  2500  4000  6300 10000   +inf
          0     8    61     3     0     0     0     0     0     0     0     0     0     0     0     0     0
```

First, the control experiment, which is the part people skip: **quadrupling the threads from 24 to 96 changes capacity by nothing** (515 → 519, inside the noise) **and quadruples the service-time tail** (68 ms → 302 ms). That is the GIL — the Global Interpreter Lock, the mutex that lets only one thread run Python bytecode at a time (Lesson 2). Threads are for waiting, not for computing, and proving it costs one probe and saves the argument forever. Moving the scoring to four *processes* sidesteps the GIL — separate interpreters, separate locks — and capacity goes **499 → 794 req/s, 1.59×**. But read the next two lines, the most professionally useful in the whole run: three probes of *the identical build* measured **792, 794 and 799 req/s**, and the harness still refuses to claim better than **3%** resolution, because that is the floor for any wall-clock benchmark on a machine you share with an operating system. Any change smaller than that floor is not measurable by this instrument, and reporting one as a win would be fiction. Finally, the honest scoping of what this bought. At the 40 req/s the service actually receives, p99 went **25.7 → 27.2 ms** — it did not improve, and within the tail's own variance it did not change. The offload doubled the *ceiling*, not the experience. That is a legitimate thing to ship (it is next year's headroom) and a dishonest thing to put in a release note as "1.6× faster". The serialisation tax is also real: every call pickles its payload and crosses a pipe, and at 1.6 ms of work that tax pays for itself while at 0.2 ms it would not.

### Stage 7 — a fix that fails

```console
== 7 . A FIX THAT FAILS ==
  'more parallelism is more throughput.' The pool is already sized from
  the curve, so the only knob left is the worker count: 24 -> 128.
  Ship it, and measure it like everything else.
  7 workers 24 -> 128        thr   40.1/s  good   40.1/s  p50    19.6ms  p99     25.3ms  err   0.0%  ok    (capacity 791/s)
    capacity 794 -> 791 req/s (1.00x, medians of three).
    the runs: 792, 794, 799 against 782, 791, 793: a -0.4% change against a
    3.0% combined spread, so the honest verdict on throughput is FLAT.
    p99 service under saturation 45.6 -> 265.1 ms (5.8x worse) -- and that regression never overlaps.
    p99 at the 40 req/s we actually serve: 27.2 -> 25.3 ms -- unchanged.
    peak requests in flight 24 -> 128, but peak concurrent upstream calls 16 -> 16:
    the pool of 16 was already the constraint, so the extra 104 threads bought no
    concurrency at all. p99 wait for a connection 17.2 ms -> 137.7 ms -- the queue
    did not shrink, it moved from our accept queue into the pool.
    Little's Law, applied backwards: latency = in-flight / throughput.
       24 in flight / 794 req/s =   30.2 ms
      128 in flight / 791 req/s =  161.9 ms
  ...
    VERDICT: at today's load this changes nothing, and at saturation it
    multiplies the tail by 5.8x. We run at 5% of capacity: we are not
  ...
```

Every investigation has one of these, and a write-up without one is a demo. The change is the most intuitive thing in the entire lesson — **more workers, more parallelism** — and it is what the second theory in *The Problem* wanted a year ago. Throughput: **−0.4%, against a 3% noise floor.** Flat. Not better, not worse, not worth a deploy. Notice how much easier the decision is because the noise floor was established before the experiment ran; without it, someone is arguing that 791 versus 794 means something.

The tail: **46 ms → 265 ms, 5.8×**, and *that* does not overlap anything. Little's Law explains it. At saturation throughput is pinned, so `W = L / λ`: 24 in flight over 794 req/s predicts 30 ms, 128 in flight over 791 predicts 162 ms. **When you are already at the ceiling, every additional in-flight request converts one-for-one into latency.**

The mechanism line is the one to remember: peak concurrent upstream calls went **16 → 16**. The pool of 16 was already the constraint, so the extra 104 threads bought no concurrency at all — they bought a longer line, and the p99 wait for a connection went **17.2 ms → 137.7 ms**. The queue did not shrink; it moved out of our accept queue and into the pool, where it is harder to see. Revert — and notice how cheap that decision was: because a baseline existed, because one thing changed, because the noise floor was known, the whole question took one probe and produced no argument.

### Stage 8 — survive overload

```console
== 8 . SURVIVE OVERLOAD ==
  measured capacity is 794 req/s. Offer 3x that (2381 req/s) for 0.8 s
  with the queue unbounded and no deadlines -- the configuration we ship.
  8a overload, unbounded     thr  801.6/s  good  115.4/s  p50   806.9ms  p99   1565.2ms  err   0.0%  ok
    accepted all 1904 requests and eventually completed 1904 of them -- a 0% error rate --
    but only 274 landed inside the 250 ms SLO. Goodput 115/s against a capacity of 794/s.
  ...
  8b bounded + deadlines     thr  801.0/s  good  801.0/s  p50   147.0ms  p99    159.8ms  err  60.4%  ok
    same 1904 requests. Shed at the door (queue full): 1150. Dropped on a blown deadline: 0.
    goodput 115/s -> 801/s (6.9x), p99 1565 -> 160 ms, p50 807 -> 147 ms.
    the error rate went UP, 0% -> 60%, and that is the point. A bounded queue
  ...
    goodput and throughput per 200 ms window, req/s:
      8a  throughput  720  800  780  840  805  800  805  820  805  795  815  735
      8a  GOODPUT     720  650    0    0    0    0    0    0    0    0    0    0
      8b  throughput  735  815  825  805  590
      8b  GOODPUT     735  815  825  805  590
    read the 8a rows together: the machine stays busy at full throughput
    for two seconds while goodput sits at zero. It is not idle, it is
  ...
```

The service is fast now. Push 3× its measured capacity at it for eight hundred milliseconds and watch what a fast service does when it runs out of road. **Version 8a has a 0.00% error rate.** It accepted all 1,904 requests and completed all 1,904 of them; by the dashboard it is perfect. **115 of those responses per second arrived in time**, and the other 86% went to users who had already given up. This is a **metastable failure** (Lesson 11): the queue fills with work whose caller has left, and serving that dead work is precisely what prevents the service from serving anyone new. The system does not recover when the burst ends — it stays stuck, because the backlog is now the load.

The two-row time series is the clearest thing in this lesson: throughput holds at 720–840 responses/second for the whole 2.4 seconds while goodput is **zero from 0.4 seconds onward.** A CPU graph, a throughput graph and an error-rate graph all look healthy while the service delivers nothing of value for two full seconds.

Version 8b adds three things from Lessons 6 and 11: a **bounded queue** (96 deep), **shedding at the door** when it is full, and a **deadline check at dequeue** so a request whose SLO has already expired is dropped instead of served. Goodput goes **115 → 801 req/s, 6.9×**, p99 goes 1,565 → 160 ms, and the run finishes in 1.0 s instead of 2.4 s because it never accepted work it could not finish. And the error rate goes **0% → 60.4%**, which is the sentence to take to your next design review. The bounded version *fails more requests and serves more users*. An error rate is not a quality measure; **goodput** is. A fast 503 tells the caller to retry elsewhere, now, while a 1.6-second 200 that nobody is waiting for costs you the capacity that would have served someone real.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 500" width="100%" style="max-width:940px" role="img" aria-label="Two time-series panels of the same overload: 2381 requests per second offered to a service whose measured capacity is 794. In the top panel the unbounded build keeps throughput near 800 responses per second for two and a half seconds while goodput falls to zero after 400 milliseconds. In the bottom panel the bounded build with deadline-aware shedding holds goodput equal to throughput at about 800 per second and finishes in one second.">
  <text x="490" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">3× capacity for 0.8 s — the busy service that serves nobody, and the one that sheds</text>
  <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.28"><path d="M70 160 L920 160"/><path d="M70 110 L920 110"/><path d="M70 360 L920 360"/><path d="M70 310 L920 310"/></g>
  <g fill="none" stroke="currentColor" stroke-width="1.6"><path d="M70 210 L920 210"/><path d="M70 410 L920 410"/></g>
  <path d="M70 210 L70 66 M70 410 L70 266" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5"/>
  <path d="M70 90.0 L139.2 90.0 L139.2 76.7 L208.4 76.7 L208.4 80.0 L277.6 80.0 L277.6 70.0 L346.8 70.0 L346.8 75.8 L416.0 75.8 L416.0 76.7 L485.2 76.7 L485.2 75.8 L554.4 75.8 L554.4 73.3 L623.6 73.3 L623.6 75.8 L692.8 75.8 L692.8 77.5 L762.0 77.5 L762.0 74.2 L831.2 74.2 L831.2 87.5 L900.4 87.5" fill="none" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round" opacity="0.85"/>
  <path d="M70 210 L70 90.0 L139.2 90.0 L139.2 101.7 L208.4 101.7 L208.4 210 L900.4 210 Z" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round"/>
  <path d="M70 410 L70 287.5 L139.2 287.5 L139.2 274.2 L208.4 274.2 L208.4 272.5 L277.6 272.5 L277.6 275.8 L346.8 275.8 L346.8 311.7 L416.0 311.7 L416.0 410 Z" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2.2" stroke-linejoin="round"/>
  <rect x="416" y="266" width="484" height="144" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2" stroke-dasharray="5 5"/>
  <path d="M560 150 L560 82" fill="none" stroke="#7f7f7f" stroke-width="1.2" stroke-dasharray="3 3" opacity="0.8"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="70" y="52" font-size="11.5" font-weight="700" fill="#d64545">8a · UNBOUNDED QUEUE, NO DEADLINES — 0 errors, 115 goodput/s</text>
    <text x="70" y="252" font-size="11.5" font-weight="700" fill="#0fa07f">8b · BOUNDED QUEUE (96) + DEADLINE-AWARE SHEDDING — 60% errors, 801 goodput/s</text>
    <g font-size="8.5" opacity="0.6" text-anchor="end"><text x="64" y="213">0</text><text x="64" y="163">300</text><text x="64" y="113">600</text><text x="64" y="413">0</text><text x="64" y="363">300</text><text x="64" y="313">600</text></g>
    <g font-size="8.5" opacity="0.6" text-anchor="middle"><text x="70" y="428">0</text><text x="416" y="428">1.0 s</text><text x="762" y="428">2.0 s</text></g>
    <text x="470" y="158" font-size="9.5" font-weight="700" fill="#7f7f7f">throughput — the machine is flat out the whole time</text>
    <text x="240" y="176" font-size="9.5" font-weight="700" fill="#0fa07f">GOODPUT — answers inside 250 ms</text>
    <text x="240" y="192" font-size="9" fill="#d64545" font-weight="700">zero from 0.4 s onward</text>
    <text x="446" y="292" font-size="9.5" opacity="0.75">the shedding build is DONE here.</text>
    <text x="446" y="307" font-size="9.5" opacity="0.75">Same offered load, same capacity,</text>
    <text x="446" y="322" font-size="9.5" opacity="0.75">1.0 s instead of 2.4 s, because it</text>
    <text x="446" y="337" font-size="9.5" opacity="0.75">never accepted work it could not</text>
    <text x="446" y="352" font-size="9.5" opacity="0.75">finish in time.</text>
    <text x="110" y="392" font-size="9.5" font-weight="700" fill="#0fa07f">goodput == throughput: nothing served is wasted</text>
    <text x="490" y="462" font-size="10.5" text-anchor="middle" opacity="0.9">The 0%-error build served 1904 of 1904 requests and only 274 of them in time. The 60%-error build served fewer, all useful.</text>
    <text x="490" y="480" font-size="10.5" text-anchor="middle" opacity="0.9">An error rate is not a quality measure. Goodput is. A fast 503 beats a 1.6-second 200 nobody is waiting for.</text>
  </g>
</svg>
```

### Stage 9 — the whole investigation in one table

```console
== 9 . THE WHOLE INVESTIGATION IN ONE TABLE ==
  stage                      offered   thr/s  good/s   p50 ms    p99 ms   err%  correct  verdict
  0 baseline                      40    11.5     0.8   2186.0    5514.8    0.0       ok  the service as inherited
  2 batch the N+1                 40    23.3     7.1    433.8    1890.6    0.0       ok  2.03x -- kept
  3 concurrent I/O                40    39.9    39.9     42.9      53.7    0.0    WRONG  1.71x -- but WRONG
  3b + lock the counter           40    39.7    39.7     39.9      83.5    0.0       ok  1.70x -- kept
  4 shrink+shard the lock         40    40.0    40.0     30.3      39.0    0.0       ok  capacity 40 -> 484/s, lock wait to zero -- kept
  5 pool (size 16)                40    40.1    40.1     18.8      25.7    0.0       ok  p50 30 -> 19 ms -- kept
  6 CPU -> process pool           40    40.1    40.1     18.8      27.2    0.0       ok  capacity 499 -> 794/s -- kept
  7 workers 24 -> 128             40    40.1    40.1     19.6      25.3    0.0       ok  p99 at saturation 5.8x worse -- REVERTED
  8a overload, unbounded        2381   801.6   115.4    806.9    1565.2    0.0       ok  goodput 115/s of 794 capacity -- collapse
  8b bounded + deadlines        2381   801.0   801.0    147.0     159.8   60.4       ok  goodput 6.9x -- kept
  (stages 0-7 are offered 40 req/s, the real traffic; stage 8
   is offered 3x the measured capacity, which is a different question)

  end to end, at the 40 req/s the product actually sends:
    throughput    11.5 ->   40.1 req/s (3.5x)
    p50         2186.0 ->   18.8 ms     (116x faster)
    p99         5514.8 ->   27.2 ms     (203x faster)
  ...
    capacity      11.5 ->    794 req/s (69x headroom)
    SLO (p99 <= 250 ms, err < 1%): baseline FAIL, final PASS

  what mattered, in order of measured effect:
    the global lock scope  40 -> 484 req/s of capacity
    the N+1                11 -> 23 req/s (2.03x)
    concurrent I/O         23 -> 40 req/s (1.70x)
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 566" width="100%" style="max-width:940px" role="img" aria-label="Two stacked bar charts on logarithmic scales across the eight stages of the investigation. The top chart shows measured capacity climbing from 11.5 requests per second at the baseline to 794 after the CPU offload, with the reverted stage flat. The bottom chart shows the 99th percentile latency at forty requests per second falling from 5515 milliseconds to about 27, crossing under the 250 millisecond objective at the concurrency stage.">
  <text x="490" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Eight changes, every one measured — and the eighth was thrown away</text>
  <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.30"><path d="M80 217.8 L950 217.8"/><path d="M80 143.9 L950 143.9"/><path d="M80 70 L950 70"/><path d="M80 413.3 L950 413.3"/><path d="M80 356.7 L950 356.7"/><path d="M80 300 L950 300"/></g>
  <path d="M80 390.8 L950 390.8" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="7 4" opacity="0.85"/>
  <g fill="none" stroke="currentColor" stroke-width="1.6"><path d="M80 240 L950 240"/><path d="M80 470 L950 470"/></g>
  <g stroke="#0fa07f" stroke-width="1.8" fill="#0fa07f" fill-opacity="0.20">
    <rect x="101" y="213.3" width="66" height="26.7"/> <rect x="208" y="190.6" width="66" height="49.4"/>
    <rect x="316" y="173.3" width="66" height="66.7" stroke="#d64545" fill="#d64545" fill-opacity="0.18"/> <rect x="423" y="173.3" width="66" height="66.7"/>
    <rect x="531" y="93.3" width="66" height="146.7"/> <rect x="638" y="92.3" width="66" height="147.7"/> <rect x="746" y="77.4" width="66" height="162.6"/>
    <rect x="853" y="77.5" width="66" height="162.5" stroke="#e0930f" fill="#e0930f" fill-opacity="0.14" stroke-dasharray="6 4"/>
  </g>
  <g stroke="#e0930f" stroke-width="1.8" fill="#e0930f" fill-opacity="0.20">
    <rect x="101" y="314.6" width="66" height="155.4"/> <rect x="208" y="341.0" width="66" height="129.0"/>
    <rect x="316" y="428.6" width="66" height="41.4" stroke="#d64545" fill="#d64545" fill-opacity="0.18"/> <rect x="423" y="417.8" width="66" height="52.2"/>
    <rect x="531" y="436.5" width="66" height="33.5"/> <rect x="638" y="446.8" width="66" height="23.2"/> <rect x="746" y="445.4" width="66" height="24.6"/>
    <rect x="853" y="447.2" width="66" height="22.8" stroke-dasharray="6 4" fill-opacity="0.12"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="80" y="48" font-size="11.5" font-weight="700" fill="#0fa07f">MEASURED CAPACITY — requests/second at saturation (log scale)</text>
    <text x="80" y="278" font-size="11.5" font-weight="700" fill="#e0930f">p99 LATENCY at the 40 req/s we actually get — milliseconds (log scale)</text>
    <g font-size="8.5" opacity="0.6" text-anchor="end"><text x="74" y="221">10</text><text x="74" y="147">100</text><text x="74" y="73">1000</text><text x="74" y="473">10</text><text x="74" y="417">100</text><text x="74" y="360">1k</text><text x="74" y="303">10k</text></g>
    <g font-size="9.5" font-weight="700" text-anchor="middle"><text x="134" y="207">11.5</text><text x="241" y="184">23</text><text x="349" y="167" fill="#d64545">40</text><text x="456" y="167">40</text><text x="564" y="87">484</text><text x="671" y="86">499</text><text x="779" y="71">794</text><text x="886" y="92" fill="#e0930f">791</text></g>
    <g font-size="9.5" font-weight="700" text-anchor="middle"><text x="134" y="331">5515</text><text x="241" y="335">1891</text><text x="349" y="422" fill="#d64545">54</text><text x="456" y="412">84</text><text x="564" y="430">39</text><text x="671" y="441">26</text><text x="779" y="439">27</text><text x="886" y="441" fill="#e0930f">25</text></g>
    <g font-size="9.5" text-anchor="middle">
      <text x="134" y="490" font-weight="700">0</text><text x="134" y="503" font-size="8.5" opacity="0.8">baseline</text>
      <text x="241" y="490" font-weight="700">2</text><text x="241" y="503" font-size="8.5" opacity="0.8">batch N+1</text>
      <text x="349" y="490" font-weight="700" fill="#d64545">3</text><text x="349" y="503" font-size="8.5" fill="#d64545">concurrent</text>
      <text x="456" y="490" font-weight="700">3b</text><text x="456" y="503" font-size="8.5" opacity="0.8">race fixed</text>
      <text x="564" y="490" font-weight="700">4</text><text x="564" y="503" font-size="8.5" opacity="0.8">lock scope</text>
      <text x="671" y="490" font-weight="700">5</text><text x="671" y="503" font-size="8.5" opacity="0.8">pool = 16</text>
      <text x="779" y="490" font-weight="700">6</text><text x="779" y="503" font-size="8.5" opacity="0.8">CPU → procs</text>
      <text x="886" y="490" font-weight="700" fill="#e0930f">7</text><text x="886" y="503" font-size="8.5" fill="#e0930f">128 workers</text>
    </g>
    <text x="349" y="153" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">counter WRONG</text>
    <text x="886" y="59" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">REVERTED</text>
    <text x="944" y="387" font-size="9" text-anchor="end" font-weight="700" fill="#d64545">SLO: p99 ≤ 250 ms</text>
    <text x="490" y="530" font-size="10.5" text-anchor="middle" opacity="0.9">Two changes did almost all of it: killing the N+1 (2.03×) and getting the I/O out from under the lock (12.2×).</text>
    <text x="490" y="548" font-size="10.5" text-anchor="middle" opacity="0.9">Stage 7 moved throughput by −0.4% against a 3% noise floor, and the tail under saturation by 5.8×. That is why it is not in the final build.</text>
  </g>
</svg>
```

Now the honest accounting, which is the deliverable of a performance investigation — not the speedup, the *attribution*. **Three changes did essentially all of it.** Shrinking the lock's scope was worth 12.2× in capacity, killing the N+1 was worth 2.03×, and overlapping the independent calls was worth 1.70×; multiply them and you have the entire result. Every one of them removes *waiting* — waiting for a lock, waiting for round trips that need not exist, waiting for calls that could have overlapped. Not one of them makes any code compute faster.

**One change bought latency and was reported as such:** pooling moved p50 by 38% and capacity by nothing. **One change bought only headroom:** the CPU offload raised the ceiling 1.59× and left the p99 at the SLO rate where it was — real, useful, and not what the ticket asked for.

**One change was reverted**, on the strength of a −0.4% throughput move against a 3% noise floor and a 5.8× tail regression, in one probe and with no argument.

**One change was a bug in disguise** and would have shipped, because it was faster, the tests passed and the error rate was zero — only an explicit invariant check caught it. And the theory everyone walked in with, the expensive-looking scoring function, was **6.2% of the wall clock** and never got touched.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 980 470" width="100%" style="max-width:940px" role="img" aria-label="Two latency histograms of seventy-two responses each on a shared logarithmic time axis. The baseline spreads from sixty milliseconds to over six seconds with its mass piled up between one and a half and six seconds, its median at 2186 milliseconds and its 99th percentile at 5515. The optimised build is a single spike between fifteen and twenty-five milliseconds, median 18.8 and 99th percentile 27.2, entirely to the left of the 250 millisecond objective.">
  <text x="490" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The same 72 requests, before and after — a smear across five seconds, and a spike</text>
  <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.25"><path d="M70 340.8 L900 340.8"/><path d="M70 291.5 L900 291.5"/><path d="M70 242.3 L900 242.3"/></g>
  <g fill="#d64545" fill-opacity="0.18" stroke="#d64545" stroke-width="1.4">
    <rect x="282.7" y="387.5" width="60.6" height="2.5"/> <rect x="343.3" y="385.1" width="55.8" height="4.9"/> <rect x="399.1" y="385.1" width="53.0" height="4.9"/>
    <rect x="452.1" y="377.7" width="55.9" height="12.3"/> <rect x="508.0" y="372.8" width="53.9" height="17.2"/> <rect x="561.9" y="380.2" width="54.8" height="9.8"/>
    <rect x="616.7" y="372.8" width="55.7" height="17.2"/> <rect x="672.4" y="358.0" width="53.0" height="32.0"/> <rect x="725.4" y="340.8" width="55.9" height="49.2"/>
    <rect x="781.3" y="362.9" width="53.8" height="27.1"/>
  </g>
  <g fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="1.6">
    <rect x="70" y="370.3" width="48.1" height="19.7"/> <rect x="118.1" y="239.8" width="60.6" height="150.2"/> <rect x="178.7" y="382.6" width="55.8" height="7.4"/>
  </g>
  <path d="M70 390 L900 390" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <g fill="none" stroke-width="1.6" stroke-dasharray="5 4">
    <path d="M144.9 224 L144.9 390" stroke="#0fa07f"/><path d="M188.8 252 L188.8 390" stroke="#0fa07f"/>
    <path d="M709.5 300 L709.5 390" stroke="#d64545"/><path d="M819.3 330 L819.3 390" stroke="#d64545"/>
    <path d="M452.1 190 L452.1 390" stroke="#e0930f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <g font-size="8.5" opacity="0.6" text-anchor="middle"><text x="70" y="406">10 ms</text><text x="343" y="406">100 ms</text><text x="617" y="406">1 s</text><text x="890" y="406">10 s</text></g>
    <g font-size="8.5" opacity="0.55" text-anchor="end"><text x="64" y="344">20</text><text x="64" y="295">40</text><text x="64" y="246">60</text></g>
    <text x="46" y="216" font-size="9" opacity="0.7">responses</text>
    <text x="150" y="216" font-size="11" font-weight="700" fill="#0fa07f">FINAL BUILD</text>
    <text x="150" y="230" font-size="9" fill="#0fa07f" opacity="0.95">61 of 72 requests land in one 10 ms bucket</text>
    <text x="112" y="274" font-size="9" text-anchor="end" font-weight="700" fill="#0fa07f">p50</text>
    <text x="112" y="287" font-size="9" text-anchor="end" fill="#0fa07f">18.8 ms</text>
    <text x="194" y="266" font-size="9" font-weight="700" fill="#0fa07f">p99</text>
    <text x="194" y="279" font-size="9" fill="#0fa07f">27.2 ms</text>
    <text x="676" y="300" font-size="11" font-weight="700" fill="#d64545" text-anchor="end">BASELINE</text>
    <text x="704" y="316" font-size="9" text-anchor="end" font-weight="700" fill="#d64545">p50</text>
    <text x="704" y="329" font-size="9" text-anchor="end" fill="#d64545">2186 ms</text>
    <text x="825" y="346" font-size="9" font-weight="700" fill="#d64545">p99</text>
    <text x="825" y="359" font-size="9" fill="#d64545">5515 ms</text>
    <text x="458" y="186" font-size="9.5" font-weight="700" fill="#e0930f">SLO: 250 ms</text>
    <text x="458" y="199" font-size="8.5" fill="#e0930f" opacity="0.9">baseline: 5 requests of 72 inside it</text>
    <text x="490" y="434" font-size="10.5" text-anchor="middle" opacity="0.9">A log axis flatters the baseline. Those two distributions are 100× apart, and only one of them has a tail at all.</text>
    <text x="490" y="452" font-size="10.5" text-anchor="middle" opacity="0.9">Goodput — responses inside the SLO, per second — went from 0.8/s to 40.1/s. That is the number the user feels.</text>
  </g>
</svg>
```

## Use It

You will not have this harness in production. You will have a service you cannot restart casually, a load you do not control, and a deploy pipeline where "change one thing" costs a day. The method survives all of that; only the instruments change.

### Where each measurement comes from when it is not your laptop

| In the Build It | In production |
|---|---|
| open-loop harness, latency from intended start | client-side **RED** metrics at the edge (Phase 9, Lesson 11) — measured at the load balancer, never inside the service |
| `capacity_probe()` | a load test against a canary or staging replica, plus the observed daily peak |
| sampling profiler | a **continuous profiler** (`py-spy`, `async-profiler`, Pyroscope) sampling production at ~1%, always on |
| call counts per request | **distributed tracing** (Phase 9, Lesson 7) — span counts per trace are how you find an N+1 in a system you did not write |
| `lock_waits` / `pool.waits` | **USE** metrics: utilisation, saturation and errors for every pool, queue and semaphore |
| the correctness invariant | a consistency check or reconciliation job that runs continuously, not a unit test |

The single highest-value row in that table is **span counts per trace**: the N+1 in this lesson was invisible in every percentage and obvious in a count, and in a real distributed system that count is sitting in your traces already. Measure at the edge. A latency histogram recorded inside the handler measures the same thing the service's own timer measured in stage 0 — the work, never the queue — and it will under-report your worst incident by 60×, exactly as it did here.

### Establishing a baseline you can trust when you do not control the environment

- **Compare like with like.** Same hour of the week, same traffic mix, same instance type, same cache state. A Tuesday 14:00 baseline versus a Sunday 03:00 "after" is not a measurement.
- **Prefer A/B over before/after.** Run old and new side by side on the same traffic at the same moment — a canary, a shadow deploy, or a flag splitting requests. That cancels the environment out instead of hoping it held still.
- **Establish the noise floor first.** Deploy the *identical* build twice and measure the difference. Whatever number that gives you is the smallest improvement you are entitled to claim, and never claim better than a few percent on a wall clock no matter how tight your probes look.
- **Percentiles do not average.** You cannot take the mean of ten instances' p99s (Phase 9, Lesson 5). Aggregate the histogram buckets, then compute the quantile once.

### Changing one thing at a time when a deploy is the unit of change

The fix-one-thing loop assumes you can change one thing cheaply. In production you often cannot, so buy that property with tooling:
- **Feature-flag every optimisation.** A flag turns a deploy into a runtime experiment you can revert in seconds without a rollback, and it lets you A/B the change on live traffic.
- **Canary, then ramp.** 1% → 10% → 50%, comparing RED metrics between the canary and the rest at each step. Most performance regressions announce themselves at 1%.
- **Shadow traffic** for anything you cannot risk: mirror real requests to the new version and discard the responses. You get a real production profile with zero user exposure. (Watch for side effects — shadowing a handler that writes is how you double-charge people.)
- **Annotate deploys on your dashboards.** Half of all "when did this get slow" questions are answered by a vertical line.

### Holding the line afterwards

An optimisation you do not defend is a temporary one; performance regresses the same way it arrived, one reasonable change at a time.
- **A regression benchmark in CI**, on the critical path only, failing the build on a threshold set from the measured noise floor rather than from a hope. Benchmarks that fail spuriously get disabled within a month, and a disabled benchmark is worse than none because it looks like coverage.
- **An SLO with an error budget** (Phase 9, Lesson 9). This is what makes "fast enough" a decision the whole company shares rather than an argument between two engineers.
- **A saturation alert on every pool, queue and semaphore** — utilisation above ~80% for ten minutes is a ticket, not a page. That is the signal that moves first, minutes before any user-facing metric does.
- **Capacity headroom above the knee.** Run at a load where the latency-versus-load curve is still flat. If you are operating past the knee, every 10% of traffic growth costs you far more than 10% of latency, and a routine Tuesday spike becomes an incident.
- **Keep the load test.** The one that proved the win is the one that proves next quarter that it is still there.

### When to stop

This is the part nobody teaches, so here it is plainly. **Stop when any one of these is true:**

- **The next win is smaller than your noise floor.** If you cannot measure it, you cannot defend it, and you certainly cannot maintain it. Ours was 3%; a claimed 2% gain was not a result.
- **The Amdahl ceiling on everything left is small.** When the biggest remaining component is 6% of the budget, your maximum possible speedup is 1.07×. Compute this before you plan the work, not after you do it.
- **You are comfortably inside your SLO with headroom.** Being 10× inside the objective is not 10× as good. It is unspent engineering time.
- **Hardware is cheaper than engineering.** Three weeks of a senior engineer costs far more than a year of a larger instance. Optimise when the fix is structural and permanent (an N+1 is a bug, and it scales with your data), buy hardware when the fix is a constant factor you would have to keep re-earning. Saying this out loud is a senior move, not a lazy one.
- **The remaining work trades correctness or clarity for speed.** Stage 3 is the cautionary tale: a fast service with a metric that is 47% wrong is a worse service.

## Think about it

1. A service you have never seen reports p50 = 40 ms, p99 = 12 s, CPU at 8%, and a 0.00% error rate under a load of 200 req/s. You may take exactly one measurement before proposing a fix. Which one, and what would each possible answer rule out?
2. Your team ships a change that makes a batch job 30% faster in the benchmark and 0% faster in production. Give three distinct explanations that are all consistent with both observations, and say what you would measure to tell them apart.
3. You make a synchronous endpoint concurrent and a downstream service starts reporting duplicate records — but only under load, and only sometimes. Explain precisely why the concurrency change is likely to be the cause even if the duplicate-creating code was not touched, and design a check that will fail deterministically in CI.
4. A service has an SLO of p99 ≤ 300 ms and currently runs at p99 = 90 ms with capacity 4× its peak. A staff engineer proposes a two-month rewrite that would make it 3× faster. Build the argument against it in numbers, then describe the one circumstance in which you would support it anyway.
5. You add deadline-aware shedding and your error rate rises from 0.1% to 9%, while p99 falls from 4 s to 200 ms. Support wants it reverted. What do you measure to settle it, and what would have to be true about your callers for support to be right?

## Key takeaways

- **Waiting is the enemy, and almost none of it is computation.** The three changes that produced nearly all of this speedup — shrinking the lock's scope (**12.2×** capacity), deleting the N+1 (**2.03×**), overlapping independent calls (**1.70×**) — removed *waiting*, not work. The one function everyone was certain about was **6.2% of the wall clock**, with an Amdahl ceiling of **1.07×**, and was never touched.
- **Measure at the user's clock or you will measure nothing.** The same service, in the same run, reported **p99 = 92 ms** closed loop, **92.8 ms** from its own in-handler timer, and **5,515 ms** from the intended arrival time. A 60× error, produced twice, by two careful instruments that both started counting after the queue.
- **Concurrency does not create races; it collects the ones you already had.** Making three calls concurrent lost **47% of the increments** to `upstream_calls_total` — 153 counted of 288 real — while the service got faster, the tests passed and the error rate stayed at 0.00%. The lock had been protecting that counter *by accident* for years. Ship an invariant check with every concurrency change, because nothing else will tell you.
- **Every queue needs a bound and every call needs a deadline.** Under 3× capacity the unbounded build achieved **802 responses/second of throughput and 115/second of goodput, at a 0.00% error rate** — flat out for two seconds, delivering nothing. A 96-deep queue with deadline-aware shedding took goodput to **801/s (6.9×)** and p99 from 1,565 ms to 160 ms, at a **60% error rate**. An error rate is not a quality measure; goodput is.
- **Know your noise floor before you interpret a result.** Three probes of the *identical* build spanned 792–799 req/s, and the harness still refuses to resolve better than **3%** on a wall clock it does not own. That number made stage 7 a five-minute decision: throughput −0.4% is *flat*, a 5.8× tail regression is real, revert. Without it, someone argues for a week about 791 versus 794.
- **Little's Law tells you both what to buy and when to stop.** Forwards it sized the pool — 40 req/s × 32 ms of held connection time = **1.3 connections**, so 16 for burst headroom, not 96. Backwards it predicted the failed stage: at saturation, `latency = in-flight / throughput`, so 24 → 128 workers gave **30 ms → 162 ms predicted, 46 ms → 265 ms measured**, with upstream concurrency unchanged at 16. Concurrency above the knee does not buy throughput; it buys latency and moves your queue somewhere you cannot see it.

You've reached the end of Phase 8. Next: [Why Systems Go Dark](../../09-logging-monitoring-and-observability/01-why-systems-go-dark/) — you just made a service fast with a profiler attached, a load generator you controlled, and every number printed to your own terminal. Production gives you none of that. The next phase is how you keep this much visibility into a system you cannot attach a debugger to, using only the instruments you had the foresight to build in before it broke.
