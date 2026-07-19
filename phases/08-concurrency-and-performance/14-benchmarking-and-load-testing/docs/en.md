# Benchmarking & Load Testing: Numbers You Can Trust

> Your load generator reports a p99 of 7.81 ms. The truth, measured on the same server in the same second, is 1,525 ms — 195 times worse. Nothing was broken and no error was logged; the generator simply stopped sending requests while the server was stalled, so the only requests that would have been slow were never made. This lesson builds an honest microbenchmark harness, three benchmarks that lie with the true number beside each, and an end-to-end demonstration of coordinated omission — plus the correction that recovers 92% of the real answer.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Profiling: Finding the Real Bottleneck](../13-profiling/), [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/)
**Time:** ~85 minutes

## The Problem

Someone opens a pull request. The description says: **"The optimization made it 3× faster."**

Four things are wrong with that sentence, and each one on its own is enough to invalidate it.

**It was measured on a laptop.** A browser with forty tabs was open and a build was running on the other cores. Modern CPUs (Central Processing Units) do not run at a fixed speed: they boost when cool and idle, and throttle when hot or when neighbouring cores are busy. The same code, unchanged, can measure 40% apart on the same machine ten minutes apart.

**It ran the same input over and over.** The second call read a warm cache — maybe your own memoization, maybe the CPU's L2, maybe the operating system's page cache. Production never sends the same key twice in a row, so production never gets that cache. In the Build It below, a benchmark that reuses one key reports **0.086 µs per call** for a function that costs **105.745 µs** when the key is fresh. That is a **1,235× false speedup**, produced by a loop that was, in fact, timing a dictionary lookup.

**It was one run.** The run-to-run variation on that machine is larger than the claimed improvement. You cannot detect a 3× difference with a measurement whose noise you never measured, because you do not know whether 3× is a signal or a Tuesday.

**It was summarized with a mean.** [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) already showed what a mean does to a distribution with a tail: it lands in the empty gap between the fast body and the slow tail and describes nobody.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 340" width="100%" style="max-width:840px" role="img" aria-label="Three panels showing benchmarks that lie next to their true numbers. A cache benchmark reported 0.086 microseconds per operation by reusing one key while production pays 105.7 microseconds, a false speedup of 1235 times. A benchmark with no warmup reported a mean of 0.110 milliseconds when steady state is 0.028 milliseconds, inflated 3.87 times by three cold iterations. A top-k benchmark on already-sorted data picked the wrong implementation by 21.7 times, and on realistic data the other implementation wins by 2 times.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three benchmarks that lie — and what the same code really costs</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="16" y="44" width="276" height="240" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="2"/><rect x="302" y="44" width="276" height="240" rx="12" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="2"/><rect x="588" y="44" width="276" height="240" rx="12" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="2"/>
    <text x="154" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#e0930f">1 · IT MEASURED A CACHE</text><text x="440" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#7c5cff">2 · IT HAD NO WARMUP</text><text x="726" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#3553ff">3 · THE DATA WAS FAKE</text>
    <text x="34" y="92" font-size="9" fill="currentColor" opacity="0.75">the loop reuses ONE key forever</text>
    <rect x="34" y="104" width="4" height="20" fill="#d64545" stroke="#d64545" stroke-width="1.4"/><text x="46" y="119" font-size="10" font-weight="700" fill="#d64545">0.086 us  "reported"</text>
    <text x="34" y="146" font-size="9" fill="currentColor" opacity="0.75">production sends a NEW key</text>
    <rect x="34" y="158" width="224" height="20" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="1.4"/><text x="46" y="173" font-size="10" font-weight="700" fill="#0fa07f">105.745 us  actual</text>
    <text x="154" y="206" text-anchor="middle" font-size="13" font-weight="700" fill="#d64545">1,235x too fast</text>
    <text x="154" y="234" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">the loop timed a dict lookup.</text><text x="154" y="248" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">f() was called exactly once.</text>
    <text x="154" y="270" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">FIX: a fresh key every call</text>
    <text x="320" y="92" font-size="9" fill="currentColor" opacity="0.75">per-iteration cost, first 6 of 40</text>
    <g stroke-width="1.4"><rect x="320" y="104" width="4" height="52" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/><rect x="332" y="152" width="4" height="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/><rect x="344" y="152" width="4" height="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/><rect x="356" y="152" width="4" height="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/><rect x="368" y="152" width="4" height="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/><rect x="380" y="152" width="4" height="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/></g>
    <line x1="316" y1="156" x2="392" y2="156" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.2"/>
    <text x="400" y="114" font-size="10" font-weight="700" fill="#d64545">3.290 ms</text><text x="400" y="128" font-size="8.5" fill="currentColor" opacity="0.75">lazy import +</text><text x="400" y="140" font-size="8.5" fill="currentColor" opacity="0.75">table build</text><text x="400" y="160" font-size="10" font-weight="700" fill="#0fa07f">0.028 ms steady</text>
    <text x="440" y="192" text-anchor="middle" font-size="10" fill="#d64545" font-weight="700">mean of all 40 = 0.110 ms</text><text x="440" y="208" text-anchor="middle" font-size="10" fill="#0fa07f" font-weight="700">mean of 4..40  = 0.028 ms</text>
    <text x="440" y="234" text-anchor="middle" font-size="13" font-weight="700" fill="#d64545">3.87x inflated</text>
    <text x="440" y="256" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">by three iterations out of forty</text><text x="440" y="272" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">FIX: discard warmup, then measure</text>
    <text x="606" y="92" font-size="9" fill="currentColor" opacity="0.75">top-10 of 20,000: A=sorted() B=nlargest()</text>
    <text x="606" y="112" font-size="9.5" fill="currentColor">already sorted</text>
    <rect x="606" y="118" width="10" height="11" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.3"/><text x="622" y="127" font-size="9" font-weight="700" fill="#0fa07f">A 0.149 ms</text>
    <rect x="606" y="133" width="216" height="11" fill="#d64545" fill-opacity="0.25" stroke="#d64545" stroke-width="1.3"/><text x="616" y="142" font-size="9" font-weight="700" fill="#d64545">B 3.234 ms</text>
    <text x="606" y="160" font-size="9.5" font-weight="700" fill="#d64545">-&gt; "A wins by 21.7x"  (WRONG)</text>
    <text x="606" y="180" font-size="9.5" fill="currentColor">realistic (5% out of order)</text>
    <rect x="606" y="186" width="56" height="11" fill="#d64545" fill-opacity="0.25" stroke="#d64545" stroke-width="1.3"/><text x="670" y="195" font-size="9" font-weight="700" fill="#d64545">A 0.839 ms</text>
    <rect x="606" y="201" width="28" height="11" fill="#0fa07f" fill-opacity="0.25" stroke="#0fa07f" stroke-width="1.3"/><text x="642" y="210" font-size="9" font-weight="700" fill="#0fa07f">B 0.414 ms</text>
    <text x="606" y="228" font-size="9.5" font-weight="700" fill="#0fa07f">-&gt; B wins by 2.0x  (the truth)</text>
    <text x="726" y="250" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">the WINNER flipped</text>
    <text x="726" y="265" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Timsort is O(n) on sorted input</text><text x="726" y="278" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">FIX: benchmark production's data</text>
    <text x="440" y="312" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Every one of these produced a confident, reproducible, precisely-formatted number. Reproducible is not the same as true.</text>
  </g>
</svg>
```

Those are the microbenchmark failures, and they are at least *visible* once you know to look. The load-testing version of the same problem is worse, because it is invisible.

You run a load test. The tool reports **p99 = 40 ms**. Meanwhile your users are timing out. The tool is not lying about the requests it measured. It simply **stopped sending requests while the server was stalled** — so the stall was never sampled, and the requests that would have suffered were never issued at all. The distribution you are looking at systematically omits exactly the samples you care about.

That is **coordinated omission**, named by Gil Tene (the author of HdrHistogram), and it is the reason a great many published latency numbers are fiction. In the Build It, the same server under the same 200 requests-per-second target with the same 2-second stall reports a p99 of **7.81 ms** to a closed-loop generator and **1,525 ms** to an open-loop one. Same server. Same second. **195× apart.**

## The Concept

### What a benchmark is for

A benchmark has exactly two legitimate jobs:

1. **Decide between two implementations.** Is the new sort faster than the old one?
2. **Detect a regression.** Did today's commit make the checkout path slower than yesterday's?

Both of those are **comparisons**. Neither needs an absolute number. What both need is a *difference that is larger than your noise*. Say that out loud before you write a benchmark, because it makes everything else follow: if the job is to detect a difference, then measuring the noise is not statistical pedantry — it is the measurement. An absolute number ("this function takes 240 µs") is nearly worthless on its own, because it is true only of your machine, your build, your kernel version and your CPU's mood.

The trap: **people quote benchmark numbers as absolutes in customer-facing documents.** "Our API responds in 12 ms" is a claim about a laptop, and the moment it appears in a slide it becomes a promise you cannot keep.

### Microbenchmark hazards

A **microbenchmark** times one function in isolation. Five things routinely destroy one.

**Warmup.** The first calls are not representative. Caches are cold, imports are lazy, the first attribute lookup resolves through the full method-resolution order, connection pools are empty, and the first pass over a large array pulls every page in from the operating system. In runtimes with a **JIT** (Just-In-Time compiler) — the Java Virtual Machine, .NET, V8, PyPy — the first thousands of iterations run interpreted before the compiler kicks in and emits machine code, and the transition is a cliff, not a slope. In the Build It, one lazy import plus a table build makes iteration 1 cost **3.290 ms** against a **0.028 ms** steady state; averaging all 40 iterations reports **0.110 ms — 3.87× the truth** from three iterations out of forty.

**The benchmark measures a cache.** Feed the same input repeatedly and something will memoize it: your own `lru_cache`, the CPU's data cache, the operating system's page cache, the database's buffer pool. Production sees a different key on nearly every call and pays the miss. This is the single most common way a benchmark reports a number that is orders of magnitude off, and it always errs in the flattering direction.

**Dead-code elimination and constant folding.** If you compute a value and never use it, an optimizing compiler is entitled to delete the computation — so the benchmark times an empty loop and reports something absurd. This is a serious hazard in JIT and ahead-of-time compiled languages (Java, Go, Rust, C++), which is why their benchmarking frameworks all ship a "black hole" / `doNotOptimize` sink. **CPython is much milder**: it is a bytecode interpreter that does almost no cross-statement optimization, so your loop body genuinely executes. It is not immune to the *family* of problems, though — the peephole optimizer folds constant expressions like `2 ** 20` at compile time, so timing `x = 2 ** 20` times nothing. That is why `timeit`'s generated loop consumes the result rather than discarding it.

**Timer resolution.** Python offers four clocks and they measure different things. `time.perf_counter()` is the highest-resolution clock available, monotonic, and includes time spent asleep — this is the one for benchmarks. `time.process_time()` counts only CPU time used by *this process* and excludes sleep and I/O (Input/Output) waits, which makes it right for measuring pure computation and wrong for anything that waits. `time.monotonic()` never goes backwards but is coarser. `time.time()` is the wall clock, and **it is not monotonic** — NTP (Network Time Protocol) adjustments and daylight-saving changes can move it backwards, producing negative durations. Never measure with `time.time()`. Even with the right clock, **timing an operation faster than the clock measures the clock**: the Build It measures a `perf_counter` tick of **0.041 µs** and shows a single dict lookup "taking" **0.083 µs to 1.042 µs** — a 13× spread on an operation whose true cost is **0.0236 µs**. The fix is to time a batch of N and divide.

**Environment noise.** CPU frequency scaling and turbo boost, thermal throttling, other processes, hypervisor steal time, a container with a CPU quota that gets throttled mid-benchmark, and — genuinely — **address-space layout and code alignment**, which change between builds and can shift performance by a few percent for reasons that have nothing to do with your code. You cannot eliminate these. You can measure them, and then refuse to believe any difference smaller than them.

### Statistics that make a claim defensible

**Report the median and percentiles, never the mean.** A mean over a right-skewed distribution is pulled by the tail and describes no actual run.

**Report the spread.** Standard deviation or the interquartile range (IQR — the gap between the 25th and 75th percentiles), or simply max/min. Without it, your reader cannot tell whether a 5% difference is a result or a coin flip. The Build It prints a `spread` column for exactly this reason: in one run implementation A had a **2.12× spread** between its fastest and slowest sample and implementation B only **1.61×**, which tells you A is the noisier measurement before you compare anything.

**Run multiple independent trials, not more iterations inside one trial.** This is the subtle one. Ten thousand iterations back-to-back all execute under the *same* environmental state — the same CPU frequency, the same cache contents, the same scheduler mood — so they measure that one state very precisely. Separate trials re-sample the environment. A tight distribution within a trial and a wide spread *across* trials is the signature of an environment-dominated benchmark, and it is invisible if you only ever ran one trial.

**Understand why `timeit` reports the minimum.** The Python documentation is explicit: noise only ever makes a measurement *slower*, never faster, so the minimum of many runs is the least-contaminated estimate of the operation's intrinsic cost. That is exactly right for a microbenchmark ("how expensive is this operation, absent interference") and exactly wrong for anything user-facing, where the interference is the user's experience. **Minimum for microbenchmarks, percentiles for systems.**

**Check that the effect exceeds the noise.** A usable rule of thumb, and the one the Build It implements:

> Believe a difference only if (a) the per-trial medians of the two implementations **do not overlap** — the worst trial of the faster one still beats the best trial of the slower one — and (b) the gap is at least **3× the combined run-to-run spread**. Otherwise report "no detectable change."

The harness must be able to say *no*. In the Build It it compares the same implementation against itself and correctly returns **NOT PROVEN** (gap 27.0 µs against 103.4 µs of noise, ranges overlapping) while returning **REAL** for a genuine 10.35× difference (gap 3,181 µs against 586 µs of noise, ranges disjoint).

### Benchmark the right thing

Representative data, at representative **size** and representative **distribution**.

- **A sort benchmark on already-sorted data** measures Timsort's O(n) fast path for pre-ordered runs, not sorting. In the Build It this does not merely distort the number — it **flips the winner**: on sorted data `sorted(xs)[:10]` beats `heapq.nlargest` by **21.7×**, and on realistic 5%-out-of-order data `nlargest` beats `sorted` by **2.0×**. You would have shipped the wrong implementation with a benchmark to back it up.
- **A cache benchmark with a 100% hit rate** measures a dictionary. The Build It runs the same 1,000-entry cache over 10,000 keys two ways: uniform keys give a **10.0% hit rate and 9.006 ms effective latency**; realistically skewed keys give **53.7% and 4.685 ms**. Benchmarking with a warm 100% hit rate would have claimed **0.100 ms** — 90× optimistic against the uniform case.
- **A query benchmark on 10 rows** measures nothing. Index selection, join strategy and buffer-pool behaviour all change with table size.

**Cardinality and key skew are first-class inputs**, not details. How many distinct keys? How concentrated is the traffic on the hottest ones? A benchmark that gets those wrong is a machine for producing confident wrong conclusions.

### From microbenchmark to load test

They ask different questions:

- A **microbenchmark** asks *"how fast is this function?"* — one call at a time, no contention, no queue.
- A **load test** asks *"what does the system do as demand rises?"* — many concurrent requests, shared resources, queues.

**You cannot extrapolate the second from the first.** If a request takes 5 ms of service time, a microbenchmark says 200 requests per second per core and stops there. It has no way to know that at 185 rps the queue makes p99 latency **357.9 ms** — because queueing (the subject of [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/)) does not exist in a microbenchmark. Service time is a property of the function. Latency is a property of the system under load, and it is mostly *waiting*.

### Closed-loop vs open-loop load generation

This is the concept everything else in the load-testing half depends on.

A **closed-loop** generator has N **virtual users** (VUs). Each one sends a request, **waits for the response**, thinks for a while, and sends the next. The critical property is the feedback edge: the response gates the next request. So when the server slows down, the offered load automatically **falls**. Ten users that were producing 100 rps against a 10 ms server produce 5 rps against a 2-second server, all by themselves.

That makes a closed loop an excellent model of a fixed user population — a call centre with 40 agents, a batch job with 8 workers — and it makes it **structurally incapable of overloading the system**. It has a built-in negative feedback loop that protects the server from the test. If your question is "where is my capacity", a closed-loop generator cannot answer it, ever, at any setting.

An **open-loop** generator sends at a fixed arrival **rate**. Request *i* is scheduled for time *i/R* and goes out then, whatever the server is doing. That is how internet traffic behaves — the world does not slow its request rate because your service is having a bad afternoon — and it is what actually applies pressure.

Most simple homegrown harnesses are closed-loop, because a `for` loop with a blocking HTTP call is the obvious thing to write. So are several well-known tools by default.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Side by side comparison of two load generation models. On the left a closed loop with N virtual users, where a highlighted feedback edge carries the response back to the user before the next request can be sent, meaning the offered load automatically falls when the server slows and overload can never be reproduced. On the right an open loop where a fixed arrival schedule issues requests at a constant rate regardless of responses, so a backlog builds and the system can genuinely be pushed past capacity.">
  <defs><marker id="l14-b-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker><marker id="l14-b-red" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Closed loop measures a user population. Open loop measures a system.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="16" y="44" width="416" height="332" rx="12" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="2"/><rect x="448" y="44" width="416" height="332" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
    <text x="224" y="70" text-anchor="middle" font-size="13" font-weight="700" fill="#3553ff">CLOSED LOOP — "N virtual users"</text><text x="672" y="70" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">OPEN LOOP — "R requests per second"</text>
    <g fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.6"><rect x="36" y="96" width="86" height="30" rx="7"/><rect x="36" y="136" width="86" height="30" rx="7"/><rect x="36" y="176" width="86" height="30" rx="7"/></g>
    <g font-size="9.5" fill="currentColor" text-anchor="middle"><text x="79" y="115">user 1</text><text x="79" y="155">user 2</text><text x="79" y="195">user 3</text><text x="79" y="222" font-size="9" opacity="0.7">... user N</text></g>
    <rect x="286" y="120" width="112" height="62" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/><text x="342" y="146" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">SERVER</text><text x="342" y="164" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">1 at a time</text>
    <g fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#l14-b-arrow)" opacity="0.85"><path d="M124 111 L 282 133"/><path d="M124 151 L 282 149"/><path d="M124 191 L 282 165"/></g>
    <path d="M342 184 C 342 232, 200 240, 128 214 L 116 210" fill="none" stroke="#d64545" stroke-width="2.6" marker-end="url(#l14-b-red)"/>
    <text x="248" y="256" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">the response gates the next request</text>
    <text x="224" y="284" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">Server slows down  →  users wait  →</text><text x="224" y="300" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">fewer requests offered  →  server recovers.</text>
    <text x="224" y="326" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">It CANNOT overload the system.</text>
    <text x="224" y="348" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Right question: "what do N users experience?"</text><text x="224" y="364" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Wrong question: "where is my capacity?"</text>
    <text x="480" y="100" font-size="9.5" fill="currentColor" opacity="0.8">schedule fixed up front: t = i / R</text>
    <g stroke="#0fa07f" stroke-width="2.2"><line x1="480" y1="112" x2="480" y2="132"/><line x1="504" y1="112" x2="504" y2="132"/><line x1="528" y1="112" x2="528" y2="132"/><line x1="552" y1="112" x2="552" y2="132"/><line x1="576" y1="112" x2="576" y2="132"/><line x1="600" y1="112" x2="600" y2="132"/><line x1="624" y1="112" x2="624" y2="132"/><line x1="648" y1="112" x2="648" y2="132"/><line x1="672" y1="112" x2="672" y2="132"/><line x1="696" y1="112" x2="696" y2="132"/><line x1="720" y1="112" x2="720" y2="132"/><line x1="744" y1="112" x2="744" y2="132"/></g>
    <line x1="472" y1="132" x2="836" y2="132" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.2"/><text x="800" y="126" font-size="9" fill="currentColor" opacity="0.7">time →</text>
    <g fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.6"><rect x="596" y="164" width="128" height="16" rx="4"/><rect x="596" y="184" width="128" height="16" rx="4"/><rect x="596" y="204" width="128" height="16" rx="4"/></g>
    <text x="660" y="176" text-anchor="middle" font-size="9" fill="currentColor">waiting</text><text x="660" y="196" text-anchor="middle" font-size="9" fill="currentColor">waiting</text><text x="660" y="216" text-anchor="middle" font-size="9" fill="currentColor">waiting</text>
    <text x="740" y="186" font-size="10" font-weight="700" fill="#e0930f">QUEUE grows</text><text x="740" y="200" font-size="10" font-weight="700" fill="#e0930f">without limit</text>
    <path d="M660 136 L 660 158" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l14-b-arrow)"/>
    <rect x="616" y="256" width="88" height="30" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/><text x="660" y="276" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">SERVER</text>
    <path d="M660 224 L 660 250" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l14-b-arrow)"/>
    <text x="672" y="308" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">No edge comes back. Arrival rate is a constant,</text><text x="672" y="324" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">exactly like internet traffic, which does not</text><text x="672" y="340" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">slow down because your server is having a day.</text>
    <text x="672" y="364" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">This is the only model that finds capacity.</text>
    <text x="440" y="404" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Locust, Gatling and JMeter's thread groups are closed by default. wrk2 -R and k6's constant-arrival-rate are open.</text>
  </g>
</svg>
```

### Coordinated omission

Now put the two together. Your generator is closed-loop. The server stalls for two seconds — a stop-the-world garbage collection, a failover, a lock convoy, a cache flush.

During those two seconds your generator sends **zero requests**. Every virtual user is parked inside a blocking call. The requests that *would* have arrived during the stall — the ones that would have observed a 2-second, 1.9-second, 1.8-second wait — are never issued and never recorded. The distribution you end up with does not merely under-sample the tail; it **systematically omits exactly the samples the test existed to find**.

The error is not small. In the Build It, one 2-second stall in a 60-second run at 200 rps costs the closed-loop generator **380 requests it never sent** — only 3.2% of the intended 12,000. That 3.2% is the entire tail:

- closed loop: p50 **0.96 ms**, p99 **7.81 ms**, p99.9 **1,964 ms**
- open loop: p50 **0.74 ms**, p99 **1,525 ms**, p99.9 **1,959 ms**

The p99 is **195× understated**. Note that p99.9 is nearly identical in both — the closed loop *did* capture 20 slow samples, just far too few of them to reach the 99th percentile. That is the signature: a distribution that looks fine until you go deep enough, then jumps by three orders of magnitude with nothing in between.

**The fix** is to derive each request's **intended start time** from the target rate and measure latency from that, not from when you actually managed to send it. If request *i* was due at *i/R* and you did not manage to send it until 1.4 s later because you were blocked, its latency includes that 1.4 s — because a real user's request *would* have arrived on schedule and *would* have waited.

**Why is this legitimate and not double-counting?** Because the requests were genuinely owed and genuinely would have suffered. You are not inventing latency; you are re-creating the arrivals your generator failed to produce, and assigning each the wait it would actually have experienced given when it was due. This is exactly what HdrHistogram's `recordValueWithExpectedInterval(value, expectedInterval)` does: a recorded sample of L, where a request was due every `expectedInterval`, back-fills synthetic samples at L − interval, L − 2×interval, … down to zero. The Build It implements that in six lines and applies it per virtual user with that user's own cycle time — and the corrected p99 comes out at **1,401 ms against the open loop's 1,525 ms: 91.9% recovery**, from a sample count of **12,001 against 12,000**. The correction re-creates the *requests*, not the latency.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 552" width="100%" style="max-width:860px" role="img" aria-label="A timeline showing a server frozen for two seconds. The closed-loop generator stops sending during the stall, so 380 requests are never issued and appear as ghost marks, while the open-loop generator keeps sending at a fixed rate and 400 requests queue up. The resulting latency distributions differ by 195 times at the 99th percentile: 7.81 milliseconds recorded by the closed loop versus 1525 milliseconds recorded by the open loop.">
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Coordinated omission: the stall the closed loop never sampled</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="16" y="42" width="868" height="250" rx="12" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/><rect x="16" y="306" width="868" height="210" rx="12" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/>
    <rect x="366" y="76" width="236" height="176" rx="6" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.6" stroke-dasharray="5 4"/>
    <text x="30" y="62" font-size="10.5" font-weight="700" fill="currentColor" opacity="0.8">1 · WHAT EACH GENERATOR SENT</text><text x="484" y="94" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">SERVER FROZEN — 2.0 s</text>
    <line x1="126" y1="124" x2="846" y2="124" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2" stroke-dasharray="4 4"/><line x1="126" y1="214" x2="846" y2="214" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.2" stroke-dasharray="4 4"/>
    <text x="30" y="120" font-size="10" font-weight="700" fill="#3553ff">closed loop</text><text x="30" y="134" font-size="8.5" fill="currentColor" opacity="0.7">20 users</text><text x="30" y="210" font-size="10" font-weight="700" fill="#0fa07f">open loop</text><text x="30" y="224" font-size="8.5" fill="currentColor" opacity="0.7">200 rps</text>
    <g stroke="#3553ff" stroke-width="2.2"><line x1="130" y1="112" x2="130" y2="136"/><line x1="160" y1="112" x2="160" y2="136"/><line x1="189" y1="112" x2="189" y2="136"/><line x1="219" y1="112" x2="219" y2="136"/><line x1="248" y1="112" x2="248" y2="136"/><line x1="278" y1="112" x2="278" y2="136"/><line x1="307" y1="112" x2="307" y2="136"/><line x1="337" y1="112" x2="337" y2="136"/><line x1="366" y1="112" x2="366" y2="136"/><line x1="602" y1="112" x2="602" y2="136"/><line x1="632" y1="112" x2="632" y2="136"/><line x1="661" y1="112" x2="661" y2="136"/><line x1="691" y1="112" x2="691" y2="136"/><line x1="720" y1="112" x2="720" y2="136"/><line x1="750" y1="112" x2="750" y2="136"/><line x1="779" y1="112" x2="779" y2="136"/><line x1="809" y1="112" x2="809" y2="136"/></g>
    <g stroke="#7f7f7f" stroke-width="1.6" stroke-dasharray="2 3" opacity="0.75"><line x1="396" y1="112" x2="396" y2="136"/><line x1="425" y1="112" x2="425" y2="136"/><line x1="455" y1="112" x2="455" y2="136"/><line x1="484" y1="112" x2="484" y2="136"/><line x1="514" y1="112" x2="514" y2="136"/><line x1="543" y1="112" x2="543" y2="136"/><line x1="573" y1="112" x2="573" y2="136"/></g>
    <text x="484" y="158" text-anchor="middle" font-size="10" font-weight="700" fill="#7f7f7f">380 NEVER SENT</text><text x="484" y="173" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">no send, no sample</text>
    <g stroke="#0fa07f" stroke-width="2.2"><line x1="130" y1="202" x2="130" y2="226"/><line x1="160" y1="202" x2="160" y2="226"/><line x1="189" y1="202" x2="189" y2="226"/><line x1="219" y1="202" x2="219" y2="226"/><line x1="248" y1="202" x2="248" y2="226"/><line x1="278" y1="202" x2="278" y2="226"/><line x1="307" y1="202" x2="307" y2="226"/><line x1="337" y1="202" x2="337" y2="226"/><line x1="602" y1="202" x2="602" y2="226"/><line x1="632" y1="202" x2="632" y2="226"/><line x1="661" y1="202" x2="661" y2="226"/><line x1="691" y1="202" x2="691" y2="226"/><line x1="720" y1="202" x2="720" y2="226"/><line x1="750" y1="202" x2="750" y2="226"/><line x1="779" y1="202" x2="779" y2="226"/><line x1="809" y1="202" x2="809" y2="226"/></g>
    <g stroke="#e0930f" stroke-width="2.2"><line x1="366" y1="202" x2="366" y2="226"/><line x1="396" y1="202" x2="396" y2="226"/><line x1="425" y1="202" x2="425" y2="226"/><line x1="455" y1="202" x2="455" y2="226"/><line x1="484" y1="202" x2="484" y2="226"/><line x1="514" y1="202" x2="514" y2="226"/><line x1="543" y1="202" x2="543" y2="226"/><line x1="573" y1="202" x2="573" y2="226"/></g>
    <path d="M366 244 L 598 244 L 598 232 Z" fill="#e0930f" fill-opacity="0.28" stroke="#e0930f" stroke-width="1.4"/>
    <text x="484" y="190" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">400 sent anyway, all slow</text>
    <text x="640" y="158" font-size="9" fill="currentColor" opacity="0.75">the closed loop's users are</text><text x="640" y="172" font-size="9" fill="currentColor" opacity="0.75">all parked, waiting. Nothing</text><text x="640" y="186" font-size="9" fill="currentColor" opacity="0.75">is offered, so nothing is felt.</text>
    <line x1="130" y1="270" x2="838" y2="270" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.6"/>
    <g stroke="currentColor" stroke-width="1.4" stroke-opacity="0.6"><line x1="130" y1="270" x2="130" y2="276"/><line x1="366" y1="270" x2="366" y2="276"/><line x1="602" y1="270" x2="602" y2="276"/><line x1="838" y1="270" x2="838" y2="276"/></g>
    <g font-size="9" fill="currentColor" opacity="0.7" text-anchor="middle"><text x="130" y="286">t = 28 s</text><text x="366" y="286">30 s</text><text x="602" y="286">32 s</text><text x="838" y="286">34 s</text></g>
    <text x="30" y="326" font-size="10.5" font-weight="700" fill="currentColor" opacity="0.8">2 · WHAT EACH GENERATOR RECORDED — same server, same 60 s, same 2 s stall</text>
    <text x="240" y="348" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">closed loop · 11,620 samples</text><text x="670" y="348" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">open loop · 12,000 samples</text>
    <g fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.4"><rect x="83" y="368" width="20" height="100"/><rect x="110" y="408" width="20" height="60"/><rect x="137" y="446" width="20" height="22"/><rect x="164" y="460" width="20" height="8"/><rect x="380" y="462" width="20" height="6"/></g>
    <g fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.4"><rect x="513" y="368" width="20" height="100"/><rect x="540" y="408" width="20" height="60"/><rect x="567" y="446" width="20" height="22"/><rect x="594" y="460" width="20" height="8"/></g>
    <rect x="640" y="452" width="190" height="16" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/><text x="700" y="442" text-anchor="middle" font-size="9" fill="#e0930f" font-weight="700">400 slow samples</text>
    <g stroke="currentColor" stroke-width="1.3" stroke-opacity="0.55"><line x1="70" y1="468" x2="420" y2="468"/><line x1="500" y1="468" x2="850" y2="468"/></g>
    <line x1="178" y1="362" x2="178" y2="468" stroke="#3553ff" stroke-width="2" stroke-dasharray="5 4"/><line x1="814" y1="362" x2="814" y2="468" stroke="#0fa07f" stroke-width="2" stroke-dasharray="5 4"/>
    <text x="196" y="378" font-size="10" font-weight="700" fill="#3553ff">p99 = 7.81 ms</text><text x="808" y="378" text-anchor="end" font-size="10" font-weight="700" fill="#0fa07f">p99 = 1,525 ms</text>
    <g font-size="8.5" fill="currentColor" opacity="0.65" text-anchor="middle"><text x="97" y="484">1 ms</text><text x="187" y="484">10 ms</text><text x="277" y="484">100 ms</text><text x="367" y="484">1 s</text><text x="527" y="484">1 ms</text><text x="617" y="484">10 ms</text><text x="707" y="484">100 ms</text><text x="797" y="484">1 s</text></g>
    <text x="450" y="506" text-anchor="middle" font-size="11.5" font-weight="700" fill="#e0930f">195x apart — and the closed-loop run contained no errors, no warnings, nothing wrong at all</text>
    <text x="450" y="538" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The measurement was honest about the requests it made. It just stopped making requests exactly when they would have hurt.</text>
  </g>
</svg>
```

### The throughput/latency curve and the knee

Ramp the offered arrival rate and plot achieved throughput and p99 latency together. You get the shape [Backpressure & Load Shedding](../11-backpressure-and-load-shedding/) derived from queueing theory, now measured rather than argued:

- Throughput rises roughly linearly with offered load, then **plateaus** at the system's service capacity.
- Latency rises gently, then bends sharply upward — the **knee** — and climbs without bound past it.
- Past the knee, **achieved rate diverges from offered rate**. That divergence is the definitive, unambiguous sign of saturation, and it is why you must always report both numbers.

The number people quote is the plateau: "this box does 204 rps." That is not capacity, because at 204 rps the p99 is 722 ms and nobody is being served. **Maximum useful throughput** is the highest rate at which you still meet your latency SLO (Service Level Objective — the latency target you promise). In the Build It those are **204 rps** and **171.6 rps** respectively: quoting the peak overstates capacity by **1.19×**, and every request in that gap is a request that arrives, waits, and disappoints.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="A throughput and latency curve measured by ramping the offered arrival rate from 40 to 400 requests per second. Achieved throughput rises then plateaus at about 204 requests per second while p99 latency climbs from 27 milliseconds to over 700. The knee sits at 170 offered where p99 is still 127 milliseconds, giving a maximum useful throughput of 171.6 requests per second under a 200 millisecond SLO. Past the knee goodput collapses from 171.6 to 2.6 requests per second even though throughput barely changes.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Capacity is where the SLO breaks, not where the box stops</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="90" y="90" width="310" height="240" fill="#0fa07f" fill-opacity="0.07"/><rect x="400" y="90" width="128" height="240" fill="#e0930f" fill-opacity="0.10"/><rect x="528" y="90" width="292" height="240" fill="#d64545" fill-opacity="0.09"/>
    <g stroke="currentColor" stroke-opacity="0.18" stroke-width="1"><line x1="90" y1="270" x2="820" y2="270"/><line x1="90" y1="210" x2="820" y2="210"/><line x1="90" y1="150" x2="820" y2="150"/><line x1="90" y1="90" x2="820" y2="90"/></g>
    <g stroke="currentColor" stroke-width="1.5" stroke-opacity="0.7"><line x1="90" y1="330" x2="820" y2="330"/><line x1="90" y1="90" x2="90" y2="330"/><line x1="820" y1="90" x2="820" y2="330"/></g>
    <path d="M90 330 L 491 90" fill="none" stroke="#7f7f7f" stroke-width="1.6" stroke-dasharray="6 5" opacity="0.8"/><text x="470" y="84" text-anchor="end" font-size="9" fill="#7f7f7f">offered = achieved (ideal)</text>
    <line x1="90" y1="270" x2="820" y2="270" stroke="#d64545" stroke-width="1.8" stroke-dasharray="7 4"/><text x="96" y="264" font-size="9.5" font-weight="700" fill="#d64545">SLO: p99 = 200 ms</text>
    <polyline points="163,286 236,243 309,194 364,165 400,143 428,126 455,113 528,109 674,110 820,108" fill="none" stroke="#3553ff" stroke-width="2.4"/>
    <polyline points="163,286 236,243 309,194 364,165 400,143 428,147 455,219 528,325 674,327 820,327" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <polyline points="163,322 236,319 309,310 364,294 400,292 428,223 455,120 528,106 674,113 820,113" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-dasharray="5 3"/>
    <line x1="400" y1="90" x2="400" y2="330" stroke="#e0930f" stroke-width="2" stroke-dasharray="4 4"/><circle cx="400" cy="143" r="5" fill="#0fa07f" stroke="currentColor" stroke-width="1.4"/>
    <text x="394" y="126" text-anchor="end" font-size="10" font-weight="700" fill="#0fa07f">KNEE  171.6 rps</text><text x="394" y="140" text-anchor="end" font-size="9" fill="currentColor" opacity="0.85">p99 still 127 ms</text>
    <path d="M790 146 L 790 116" fill="none" stroke="#3553ff" stroke-width="1.4" stroke-dasharray="3 3" opacity="0.8"/><text x="816" y="162" text-anchor="end" font-size="9.5" font-weight="700" fill="#3553ff">peak 204 rps — at p99 722 ms</text>
    <text x="700" y="316" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">goodput 2.6 rps: nothing works</text>
    <g font-size="10" font-weight="700" text-anchor="middle"><text x="245" y="106" fill="#0fa07f" opacity="0.85">HEALTHY</text><text x="200" y="136" font-size="8.5" font-weight="400" fill="currentColor" opacity="0.7">throughput = goodput here</text><text x="464" y="106" fill="#e0930f">OVER THE KNEE</text><text x="674" y="106" fill="#d64545">SATURATED</text></g>
    <g font-size="9" fill="currentColor" opacity="0.75">
      <g text-anchor="end"><text x="82" y="334">0</text><text x="82" y="274">55</text><text x="82" y="214">110</text><text x="82" y="154">165</text><text x="82" y="94">220</text></g>
      <g text-anchor="start"><text x="828" y="334">0</text><text x="828" y="274">200</text><text x="828" y="214">400</text><text x="828" y="154">600</text><text x="828" y="94">800</text></g>
      <g text-anchor="middle"><text x="90" y="348">0</text><text x="272" y="348">100</text><text x="455" y="348">200</text><text x="638" y="348">300</text><text x="820" y="348">400</text></g>
    </g>
    <text x="455" y="366" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">OFFERED arrival rate (rps) — set by the generator, never by the server</text>
    <text x="30" y="212" font-size="9.5" fill="currentColor" opacity="0.75" transform="rotate(-90 30 212)" text-anchor="middle">rps</text><text x="866" y="212" font-size="9.5" fill="currentColor" opacity="0.75" transform="rotate(-90 866 212)" text-anchor="middle">p99 ms</text>
    <g font-size="9.5">
      <line x1="150" y1="390" x2="182" y2="390" stroke="#3553ff" stroke-width="2.4"/><text x="190" y="394" fill="currentColor">achieved throughput</text>
      <line x1="360" y1="390" x2="392" y2="390" stroke="#0fa07f" stroke-width="2.4"/><text x="400" y="394" fill="currentColor">goodput (inside SLO)</text>
      <line x1="580" y1="390" x2="612" y2="390" stroke="#e0930f" stroke-width="2.4" stroke-dasharray="5 3"/><text x="620" y="394" fill="currentColor">p99 latency</text>
    </g>
    <text x="440" y="424" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Past the knee throughput moved 171.6 → 204 rps (+19%) while goodput fell 171.6 → 2.6 rps (−98%). Only one of those is capacity.</text>
  </g>
</svg>
```

### Goodput vs throughput

**Throughput** counts every response the system produced. **Goodput** counts only the responses that were **correct** *and* **inside the deadline**. Under normal load they are the same number. Under overload they diverge violently, because the system is still doing work — it is just doing work nobody is waiting for any more.

The Build It's measured collapse: at the knee, throughput and goodput are both **171.6 rps**. At 400 rps offered, throughput is **204.0 rps** (+19%) and goodput is **2.6 rps** (−98%). A system that "handles 10,000 rps" while timing out on all of them handles **zero**. Always report both.

### The load generator is often the bottleneck

Before you believe any load test, prove the generator was not the thing that saturated. A single-threaded Python generator will run out of headroom long before a real server does.

**How to tell:** the generator's CPU is pinned at 100%; the achieved request rate is below the intended rate; or latency is rising in the *client's* measurement while the server's own metrics show it is idle. The Build It measures its own ceiling: at 20,000, 200,000 and 1,000,000 requests per second intended, it achieves **100.0%** of target with sub-millisecond scheduling lag. At 3,000,000 it achieves **59.7%** with a **69 ms median lag** and flags **GENERATOR SATURATED — result invalid**.

Note what a saturated generator does: it falls behind, and then it **stops sending while it is behind**. That is coordinated omission produced by your own client, on a healthy server. **What to do:** more processes or more machines, a compiled generator, and always — always — report achieved rate against intended rate.

### Test types and what each answers

- **Load test** — expected peak traffic, sustained. *Does the system meet its SLO at the load we actually expect?*
- **Stress test** — push past capacity deliberately. *Where does it break, and does it break gracefully?* This is where you exercise the shedding and backpressure from Lesson 11: the right answer to overload is fast, cheap rejection, not a slow death.
- **Soak / endurance test** — hold moderate load for hours or days. *Do we leak?* Memory leaks, file-descriptor leaks, heap fragmentation, connection-pool churn and unbounded caches are all invisible in a five-minute run.
- **Spike test** — jump from low to very high load instantly and back. *Does it recover?* Autoscaling lag, cold caches, thundering-herd reconnects and retry storms live here.
- **Capacity / scalability test** — measure throughput at 1, 2, 4, 8 instances. *Does doubling the resources double the throughput?* It will not, and the Universal Scalability Law from [Why Concurrency](../01-why-concurrency/) says why: contention makes the curve flatten, and crosstalk makes it turn back down.

### Benchmarking in CI

Regression detection in CI (Continuous Integration) is worth doing and easy to do badly.

- **Compare against a baseline, not an absolute threshold.** Run the benchmark on the merge-base commit and on the pull request in the *same job*, on the *same runner*, and compare. An absolute threshold encodes the speed of whatever machine you had in 2023.
- **Size the tolerance band from measured noise.** Run the benchmark twice on unchanged code and see what the spread is. If your runner's noise is ±15%, a 5% threshold produces nothing but alarm fatigue and people will start ignoring the check — which is worse than not having it.
- **Shared CI runners are noisy.** They are virtualized, they have noisy neighbours, and they are subject to CPU quota throttling. They can reliably catch a 2× regression; they cannot reliably catch a 3% one.

The practical compromise most teams land on: **benchmark in CI for large regressions** (a wide band, cheap, catches the accidental O(n²)), and **benchmark on dedicated hardware for real numbers** (a quiet, pinned, frequency-locked machine on a schedule, with results tracked over time).

## Build It

[`code/benchmarking.py`](code/benchmarking.py) is a benchmark harness that behaves, three benchmarks that lie, a clock probe, and a full coordinated-omission demonstration. Standard library only.

The harness is the foundation. Note the three structural decisions: calibrate a batch size so a single timing is far above the clock's resolution, throw away warmup batches, and split the work into **independent trials** rather than one long run.

```python
def benchmark(fn, arg, trials=12, samples_per_trial=12, warmup_batches=5):
    n = calibrate(fn, arg)                      # batch >= 2 ms, so the clock is not the measurement
    for _ in range(warmup_batches):             # cold caches, lazy imports, first-call resolution
        for _ in range(n):
            fn(arg)
    all_samples, trial_medians = [], []
    for _ in range(trials):
        trial = []
        for _ in range(samples_per_trial):
            t0 = time.perf_counter()
            for _ in range(n):
                fn(arg)
            trial.append((time.perf_counter() - t0) / n)
        all_samples.extend(trial)
        trial_medians.append(statistics.median(trial))
    return {"batch": n, "samples": all_samples, "trial_medians": trial_medians}
```

The verdict is where most homegrown harnesses stop and where this one starts. It works on the **per-trial medians**, not the raw samples, because trials are the unit that independently re-samples the environment:

```python
def verdict(name_a, res_a, name_b, res_b):
    a, b = res_a["trial_medians"], res_b["trial_medians"]
    ma, mb = statistics.median(a), statistics.median(b)
    noise = statistics.stdev(a) + statistics.stdev(b)
    gap = abs(ma - mb)
    disjoint = max(a) < min(b) or max(b) < min(a)     # no plausible re-run flips the ordering
    real = disjoint and gap > 3 * noise               # and the gap dwarfs the run-to-run spread
```

The simulated server runs in **virtual time**, so the coordinated-omission result is bit-for-bit reproducible. Service time is exponential (a healthy tail of its own) and the server is completely unavailable for a fixed window:

```python
def serve(self, arrival):
    start = max(arrival, self.free_at)
    if self.stall_at <= start < self.stall_at + self.stall_s:
        start = self.stall_at + self.stall_s      # frozen: wait it out, then queue
    self.free_at = start + self.rng.expovariate(1.0 / self.service_s)
    return self.free_at
```

Now the two generators, and the whole lesson is in the difference between two lines. The open loop derives an **intended** time from the rate and measures from it. The closed loop measures from the actual send, and — crucially — cannot send while it is waiting:

```python
def run_open_loop(server, rate, duration):
    lat = []
    for i in range(int(rate * duration)):
        intended = i / rate                       # fixed by the schedule, not by the server
        lat.append(server.serve(intended) - intended)
    return lat

def run_closed_loop(server, users, cycle_s, duration):
    heap = [(u * cycle_s / users, u) for u in range(users)]
    heapq.heapify(heap)
    per_user = defaultdict(list)
    while heap:
        send, u = heapq.heappop(heap)
        if send >= duration:
            continue
        per_user[u].append(server.serve(send) - send)          # latency from ACTUAL send
        heapq.heappush(heap, (max(server.free_at, send + cycle_s), u))   # blocked until served
    return per_user
```

And the correction — HdrHistogram's `recordValueWithExpectedInterval` in six lines, applied per user with that user's own cycle time as the expected interval:

```python
def correct_for_omission(samples, expected_interval):
    out = []
    for v in samples:
        out.append(v)
        x = v - expected_interval
        while x > 0:            # back-fill the requests that were due and never sent
            out.append(x)       # each would have observed the remaining wait
            x -= expected_interval
    return out
```

Run it:

```bash
docker compose exec -T app python phases/08-concurrency-and-performance/14-benchmarking-and-load-testing/code/benchmarking.py
```

```console
== 1 · AN HONEST HARNESS: WARMUP, TRIALS, PERCENTILES, A VERDICT ==
  task: top-10 of 20,000 ints   A = sorted(xs)[:10]   B = heapq.nlargest(10, xs)
  A sorted(xs)[:10]          batch=      1  n= 144
       min  2346.250 us   median  3234.667 us    p95  4357.917 us
       p99  4974.000 us    stdev   643.188 us   spread     2.12x
  B heapq.nlargest           batch=     12  n= 144
       min   267.108 us   median   337.035 us    p95   400.462 us
       p99   417.042 us    stdev    40.486 us   spread     1.61x
  A median 3521.240 us   vs   B median 340.115 us
    gap 3181.124 us   combined trial noise 585.557 us   gap/noise = 5.4x
    trial-median ranges disjoint: True
    VERDICT: REAL — B is 10.35x faster than A
  control: the SAME implementation benchmarked twice — a harness must be able
  to say 'no difference', or every result it prints is a coin flip.
  B(run1) median 336.292 us   vs   B(run2) median 363.314 us
    gap 27.022 us   combined trial noise 103.382 us   gap/noise = 0.3x
    trial-median ranges disjoint: False
    VERDICT: NOT PROVEN — the difference is inside the noise. Report no change.

== 2 · THREE BENCHMARKS THAT LIE (WITH THE TRUE NUMBER BESIDE EACH) ==
  (a) THE BENCHMARK MEASURED A CACHE
      same input, 1 distinct key   :      0.086 us/op   <- what the benchmark reported
      fresh key every call         :    105.745 us/op   <- what production pays
      false speedup claimed        :     1234.9x
      The loop measured a dict lookup. The function was never called twice.
  (b) NO WARMUP
      iteration 1  :     3.290 ms
      iteration 2  :     0.028 ms
      iteration 3  :     0.026 ms
      iterations 4-40 median :     0.026 ms
      mean INCLUDING warmup  :     0.110 ms   <- reported
      mean EXCLUDING warmup  :     0.028 ms   <- steady state
      inflation from 3 cold iterations :   3.87x
  (c) UNREPRESENTATIVE DATA
      dataset                  A sorted()[:10]    B nlargest(10)   winner
      already sorted                  0.149 ms           3.234 ms   A by 21.70x
      uniform random                  2.447 ms           0.221 ms   B by 11.09x
      realistic (5% out)              0.839 ms           0.414 ms   B by 2.03x
      Timsort is O(n) on sorted input, so 'already sorted' answers a different question.
      key skew, same 1000-entry LRU cache over 10,000 keys:
        uniform keys     hit rate  10.0%   effective latency   9.006 ms
        zipf-ish keys    hit rate  53.7%   effective latency   4.685 ms
        benchmarking with a 100% hit rate would have claimed   0.100 ms

== 3 · TIMER RESOLUTION: TIMING ONE FAST OPERATION MEASURES THE CLOCK ==
  time.perf_counter  resolution=1e-09s  monotonic=True   adjustable=False
  time.process_time  resolution=1e-09s  monotonic=True   adjustable=False
  ...
  time.time          resolution=1e-09s  monotonic=False  adjustable=True
  measured perf_counter tick    :   0.0410 us  (median gap between distinct reads 0.0840 us)
  timing ONE dict lookup, 15 times: min 0.0830 us  max 1.0420 us  spread 13x
  the operation costs tens of nanoseconds; every number above is clock overhead.
  the fix — time a batch of N and divide:
      N=        1  total    0.0005 ms   per-op   0.5420 us
      N=       10  total    0.0008 ms   per-op   0.0791 us
      N=     1000  total    0.0219 ms   per-op   0.0219 us
      N=   100000  total    2.3432 ms   per-op   0.0234 us
      N=  5000000  total  118.1313 ms   per-op   0.0236 us
  per-op only converges once the batch is far larger than one clock tick.

== 4 · COORDINATED OMISSION: THE SAME SERVER, TWO GENERATORS, TWO REALITIES ==
  server: mean 1 ms/request (capacity ~1000 rps), frozen for 2s at t=30s
  target: 200 rps for 60s = 12000 requests
  closed loop: 20 virtual users, 100 ms cycle each = 200 rps

  generator                          samples     p50 ms     p99 ms    p99.9 ms     max ms
  closed loop (what most tools do)     11620       0.96       7.81     1964.12    2000.96
  open loop (intended start time)      12000       0.74    1525.07     1959.18    2000.96
  closed loop + HdrHistogram fix       12001       1.02    1400.96     1959.18    2000.96

  requests the closed loop never sent : 380   (3.2% of the intended 12000)
  achieved rate (closed)   193.7 rps  vs intended 200 rps  -> 96.8% — the tell, if you look
  p99 understated by the closed loop  :    195.2x   (7.81 ms reported vs 1525.07 ms real)
  back-filled p99 recovers the open-loop answer to 91.9% (1400.96 ms vs 1525.07 ms)
  corrected sample count 12001 vs open-loop 12000  — the correction re-creates the requests, it does not invent latency

== 5 · THE THROUGHPUT/LATENCY CURVE: WHERE CAPACITY ACTUALLY IS ==
  one server, mean service 5 ms -> theoretical ceiling 200 rps; queue cap 120; client deadline 1000 ms
  SLO: p99 < 200 ms. Goodput = responses delivered inside that SLO.

   offered  achieved  goodput   p50 ms    p99 ms   err %   note
        40      40.7     40.7      4.0      27.2     0.0   within SLO
        80      79.7     79.7      5.7      36.4     0.0   within SLO
       120     124.4    124.4      9.3      66.4     0.0   within SLO
       150     151.0    151.0     14.1     120.2     0.0   within SLO
       170     171.6    171.6     21.1     127.3     0.0   <- KNEE: max useful throughput
       185     187.3    167.6     47.6     357.9     0.0   over the knee: p99 climbing
       200     198.8    102.0    194.6     699.7     1.0   over the knee: p99 climbing
       240     202.4      4.8    561.7     745.9    16.1   SATURATED: achieved << offered
       320     201.5      2.6    594.7     721.8    36.9   SATURATED: achieved << offered
       400     204.0      2.6    591.1     722.5    49.4   SATURATED: achieved << offered

  peak throughput the box can produce      :  204.0 rps  (at any latency)
  MAXIMUM USEFUL THROUGHPUT (p99 < 200 ms) :  171.6 rps  at p99 127.3 ms
  quoting the peak overstates capacity by  :   1.19x
  at 400 rps offered: achieved 204.0 rps but goodput only 2.6 rps, 49.4% errors
  offered 400 -> achieved 204.0 rps (51% of offered): that gap IS saturation.
  goodput collapses from 171.6 rps at the knee to 2.6 rps under overload — a 65x drop while 'throughput' barely moved.

== 6 · GENERATOR HONESTY: THE HARNESS SATURATES BEFORE THE SERVER DOES ==
   intended rps  achieved rps   ratio  median lag ms  max lag ms   verdict
          20000         20003  100.0%         0.0001       0.022   ok
         200000        200002  100.0%         0.0001       0.066   ok
        1000000       1000001  100.0%         0.0001       0.456   ok
        3000000       1791389   59.7%       69.2670     141.004   GENERATOR SATURATED — result invalid
  A generator that cannot keep up stops sending while it is behind.
  That is coordinated omission produced by your own client. Always print this table.

== * · THE ONE NUMBER TO REMEMBER ==
  Same server, same 200 rps target, same 2-second stall.
  Closed-loop p99 7.81 ms.  Open-loop p99 1525.07 ms.  195x.
  Nothing was wrong with the measurement. The requests were never sent.
```

Read the numbers — five of these sections are arguments, not demos.

**Section 1** shows a harness that can say both yes and no. The real comparison gives a gap of **3,181 µs against 585 µs of combined trial noise (5.4×)** with disjoint trial-median ranges: **REAL**, and B is **10.35× faster**. The control — the identical function benchmarked twice — gives a gap of **27.0 µs against 103.4 µs of noise (0.3×)** with overlapping ranges: **NOT PROVEN**. A harness that always finds a difference is a random number generator with good formatting. Notice also the `spread` column: A's slowest sample was **2.12×** its fastest and B's only **1.61×**, and A's p99 (4,974 µs) is **54% above its median** (3,235 µs). That asymmetry is the environment, not the algorithm — and it is why the mean is useless here.

**Section 2** prices the three classic lies. The cache benchmark reports **0.086 µs** for work that costs **105.745 µs** with a fresh key: a **1,235× false speedup** for a loop that called the function exactly once and then read a dictionary on every subsequent iteration. The warmup lie is milder but far more common: one lazy import and a table build make iteration 1 cost **3.290 ms** against a **0.026 ms** median, so the naive mean over all 40 iterations is **0.110 ms — 3.87× the steady-state 0.028 ms**, entirely from three iterations. The data lie is the dangerous one, because it does not just distort the magnitude, **it reverses the decision**: on already-sorted input `sorted(xs)[:10]` wins by **21.70×**, on uniform random input `heapq.nlargest` wins by **11.09×**, and on realistic 5%-out-of-order data `nlargest` wins by **2.03×**. Ship the "winner" from the sorted benchmark and you have made production twice as slow, with a benchmark in the PR to prove you made it faster. The cache-skew lines say the same thing about distribution shape: the *same* cache over the *same* key space is **10.0%** or **53.7%** effective depending only on how the traffic is distributed.

**Section 3** is the clock, measured. `perf_counter` advertises a 1 ns resolution and actually ticks every **0.041 µs** here — advertised precision and achievable precision are different numbers. Timing a single dict lookup 15 times spans **0.083 µs to 1.042 µs**, a **13× spread** on an operation whose real cost the batch method pins at **0.0236 µs**. Watch the batch column converge: N=1 says **0.542 µs** (23× too high — that is pure timer overhead), N=10 says 0.079 µs, N=1,000 says 0.0219 µs, and from N=100,000 upward it settles at 0.023-0.024 µs. Below roughly 100 clock ticks per batch, you are measuring `perf_counter`.

**Section 4 is the point of the lesson.** One server, one 2-second stall, one 200 rps target, two generators. The closed loop reports p50 **0.96 ms** and p99 **7.81 ms** — a completely healthy-looking service. The open loop reports p50 **0.74 ms** and p99 **1,525.07 ms**. Both are honest about the requests they made; the closed loop made **380 fewer**, and those 380 were the entire tail. **195.2×.** The tells were there if you looked: the achieved rate was **193.7 rps against an intended 200 (96.8%)**, and the p99.9 was **1,964 ms** while the p99 was 7.81 ms — a 250× jump between two adjacent percentiles is never a real distribution, it is a sampling artifact. Then the correction: back-filling each user's samples at that user's 100 ms cycle interval produces **12,001 samples against the open loop's 12,000** and a p99 of **1,400.96 ms against 1,525.07 — 91.9% recovery**. The residual 8% is exactly what you would predict: the closed loop's back-fill can only reconstruct the omitted arrivals at its own 100 ms granularity, while the open loop actually sampled them every 5 ms. The correction is principled, and it is not as good as not needing it.

**Section 5** is the capacity curve, and the two right-hand columns are the argument. Throughput climbs to **171.6 rps** at 170 offered with p99 still at **127.3 ms**, then the knee: at 185 offered, throughput has moved to 187.3 (+9%) while p99 has gone **127.3 → 357.9 ms (+181%)**. Past 240 offered, achieved rate is pinned at ~202 rps no matter what you offer — at 400 offered you get **204.0 achieved, 51% of offered**, and that divergence *is* saturation. Now compare the two capacity numbers you could quote from this run: the peak is **204.0 rps** and the maximum useful throughput under a 200 ms SLO is **171.6 rps**. Only 1.19× apart, which sounds harmless, until you look at goodput across the same range: **171.6 rps at the knee, 2.6 rps at 400 offered — a 65× collapse while throughput rose 19%.** The system is working harder than ever and delivering essentially nothing. That is the number to put in the capacity plan.

**Section 6** turns the instrument on itself. Up to **1,000,000 requests per second** intended, the generator achieves 100.0% with a median scheduling lag of **0.0001 ms**. At 3,000,000 it achieves **59.7%**, its median lag jumps to **69.3 ms** and its max to **141 ms**. If you had not printed this table you would have concluded that the *server* degraded above 1M rps. Every load-test report should carry this row, and any run where achieved falls below ~95% of intended should be discarded rather than interpreted.

## Use It

**Microbenchmarks.** `timeit` is in the standard library and gets the fundamentals right (it disables the cyclic garbage collector during the run, reports the minimum, and consumes the result). For anything you will argue about, use **`pyperf`**, which does what `benchmark()` above does and more — it calibrates the loop count, discards warmups, runs **multiple independent processes** (which re-randomizes hash seeds and address-space layout, killing a whole class of false results), and tells you whether the difference is significant:

```bash
python -m timeit -s "import heapq; xs=list(range(20000))" "heapq.nlargest(10, xs)"

python -m pyperf timeit --rigorous -s "import heapq; xs=list(range(20000))" "heapq.nlargest(10, xs)"
python -m pyperf compare_to before.json after.json     # prints "Not significant!" when it is not
```

`pyperf compare_to` printing **"Not significant!"** is your `VERDICT: NOT PROVEN`. Take it as seriously.

**In CI**, `pytest-benchmark` stores results and compares against a saved baseline:

```bash
pytest --benchmark-only --benchmark-save=baseline           # on the merge-base commit
pytest --benchmark-only --benchmark-compare=0001 \
       --benchmark-compare-fail=median:20%                  # on the PR; band sized from measured noise
```

**Load generators.** The single most important configuration question is open versus closed:

```bash
# wrk2 — built by Gil Tene specifically to fix coordinated omission.
# -R is a real arrival rate, and latency is measured from the intended start time.
wrk2 -t4 -c200 -R2000 -d60s --latency http://target/checkout

# Vegeta — open by default; -rate is an arrival rate, and it reports the achieved rate.
echo "GET http://target/checkout" | vegeta attack -rate=2000/s -duration=60s | vegeta report
```

```typescript
// k6 — the executor IS the model. Choose deliberately.
export const options = {
  scenarios: {
    capacity: {                                  // OPEN: fixed arrival rate. Use this for capacity.
      executor: 'constant-arrival-rate',
      rate: 2000, timeUnit: '1s', duration: '60s',
      preAllocatedVUs: 500, maxVUs: 2000,        // if it runs out of VUs, k6 warns — heed it
    },
    // population: { executor: 'constant-vus', vus: 200, duration: '60s' },  // CLOSED: N users
  },
  thresholds: { 'http_req_duration{expected_response:true}': ['p(99)<200'] },
};
```

Know which model your tool defaults to. **`constant-vus`, Locust, Gatling's `atOnceUsers`/`rampUsers`, and JMeter's thread groups are closed-loop** — every one of them will quietly under-report your tail unless you switch to an arrival-rate mode (k6's `constant-arrival-rate` / `ramping-arrival-rate`, Gatling's `constantUsersPerSec`, JMeter's Throughput Shaping Timer, Locust's custom load shapes). Locust in particular is closed-loop by default and extremely widely used.

**HdrHistogram** is the recording structure: it stores latencies at configurable precision across many orders of magnitude in a fixed-size array, so you can record every single request instead of sampling, and it ships the correction built in:

```python
from hdrh.histogram import HdrHistogram

h = HdrHistogram(1, 60_000_000, 3)                 # 1 us .. 60 s, 3 significant figures
h.record_corrected_value(latency_us, expected_interval_us)   # your correct_for_omission()
print(h.get_value_at_percentile(99.0), h.get_value_at_percentile(99.9))
```

`record_corrected_value` is your `correct_for_omission`. `get_value_at_percentile` is your `pct`. And the corollary from [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) applies with full force here: **you cannot average your load generator's p99 across its worker processes**, for exactly the reason you cannot average ten servers' p99s. A percentile is a rank already collapsed out of a distribution. Merge the *histograms* (HdrHistogram supports `add()`; bucket counts are counts of the same predicate and therefore add), then compute the percentile once.

Production rules:

- **Use an open / arrival-rate model whenever the question is "what is our capacity".** A closed-loop test cannot overload the system and therefore cannot find the answer, at any VU count.
- **Always report achieved rate against intended rate, and discard runs below ~95%.** A generator that fell behind produced coordinated omission of its own.
- **Always report goodput next to throughput, with the deadline stated.** 204 rps of timeouts is 0 rps.
- **Never quote a mean.** Median, p95, p99, p99.9, max — and the sample count, because a p99 over 300 samples is three data points.
- **Run the generator off the machine under test.** Otherwise you are benchmarking a machine running both a server and a load generator, which is not a configuration you ship.
- **Benchmark against a baseline commit, not an absolute number**, and **state your environment when you state a result** — instance type, CPU model, kernel, runtime version, whether frequency scaling was pinned, and what else was running.

## Think about it

1. Your closed-loop test with 200 virtual users reports p99 = 40 ms and 4,000 rps achieved. Your open-loop test at 4,000 rps on the same service reports p99 = 900 ms. Both ran against the same build. Which number goes in the capacity plan, which goes in the SLO document, and is there any question the closed-loop run answers better?
2. The coordinated-omission correction back-fills a 2-second sample into 400 synthetic samples. A colleague argues this is fabricating data and inflates your p99 dishonestly. Construct the strongest version of their argument, then rebut it. Under what circumstances would they actually be right?
3. Your benchmark harness runs 12 trials. Trials 1-3 are 20% slower than trials 4-12, consistently, across many runs and both implementations. What are three distinct mechanisms that could cause this, and how would you distinguish them experimentally?
4. Your service's maximum useful throughput is 171 rps under a p99 < 200 ms SLO. Product asks for the number to put in the contract. What number do you give them, and what do you need to know about the traffic's *shape* — burstiness, key skew, request mix — before you can give any number at all?
5. A CI benchmark fails with "median regressed 8%". The runner is shared. Describe the cheapest experiment that would tell you whether this is a real regression or runner noise, and what you would change about the check afterwards either way.

## Key takeaways

- A benchmark's job is always a **comparison** — pick an implementation, or catch a regression — so the thing you must measure is the **noise**, not the absolute time. The harness must be able to return "no detectable difference": in the Build It, a real 10.35× gap cleared the bar (**3,181 µs gap vs 585 µs noise, ranges disjoint**) while the same function against itself correctly returned **NOT PROVEN** (**27 µs gap vs 103 µs noise, ranges overlapping**).
- **Microbenchmarks lie in one direction: optimistic.** Reusing one input measured a cache and claimed a **1,235× speedup** (0.086 µs vs a true 105.745 µs); skipping warmup inflated the mean **3.87×** from three iterations out of forty; and unrepresentative data did not merely distort the number but **flipped the winner** — `sorted()[:10]` beat `nlargest` by **21.70×** on pre-sorted input and lost by **2.03×** on realistic input. Report the **median and percentiles with the spread**, run **independent trials** (not more iterations in one trial), and remember that timing anything faster than the clock measures the clock: a single dict lookup "took" **0.083-1.042 µs** where a batch put it at **0.0236 µs**.
- **Coordinated omission is the largest measurement error in this lesson and the hardest to see.** A closed-loop generator stops sending while it is blocked, so a 2-second stall costs it **380 of 12,000 requests** — 3.2% — and those 3.2% are the entire tail. Measured p99: **7.81 ms closed-loop vs 1,525 ms open-loop, 195× apart**, with no errors and no warnings. The fix is to measure latency from each request's **intended start time**; HdrHistogram's back-fill recovers **91.9%** of the open-loop p99 from the closed-loop data, proving the correction is principled rather than invented.
- **Closed-loop generators cannot overload a system** — the response gates the next request, so offered load falls exactly when the server slows. Locust, Gatling and JMeter thread groups are closed by default; `wrk2 -R`, Vegeta and k6's `constant-arrival-rate` are open. If the question is capacity, only the open model can answer it.
- **Capacity is where the SLO breaks, not where the box stops.** Peak throughput was **204.0 rps**; maximum useful throughput under p99 < 200 ms was **171.6 rps**. Past the knee, throughput rose **19%** while **goodput collapsed 171.6 → 2.6 rps (−98%)** and achieved rate fell to **51% of offered** — that divergence is the definitive sign of saturation. Always report goodput and achieved-vs-intended rate alongside throughput.
- **Verify the instrument before the subject.** The generator achieved 100.0% of intended up to **1,000,000 rps** and only **59.7%** at 3,000,000, with median scheduling lag jumping from **0.0001 ms to 69.3 ms** — a run you would otherwise have read as server degradation. In CI, compare against a **baseline commit** on the same runner with a tolerance band sized from measured noise; shared runners can catch a 2× regression and cannot catch a 3% one.

Next: [Capstone: Make a Slow Service Fast](../15-capstone-make-a-slow-service-fast/) — profiling, concurrency, backpressure and the honest measurement discipline from this lesson, applied end to end to one real service until the p99 moves.
