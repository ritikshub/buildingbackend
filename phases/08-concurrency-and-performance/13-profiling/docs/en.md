# Profiling: Finding the Real Bottleneck

> Optimizing without measuring is choosing a random number to divide by. This lesson builds a checkout endpoint whose true cost breakdown is known — 895 ms, of which 501 ms is spent waiting and 18 ms is spent in the function everyone blames — and then grades three profilers against it. The CPU profiler reports the wait as **0.0% of 1,476 samples**: not small, absent. The wall-clock profiler lands within **0.06 percentage points** of truth. Choosing the wrong profiler is how you measure carefully and still learn nothing.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Concurrency?](../01-why-concurrency/), [Coroutines & Async/Await](../05-coroutines-and-async-await/)
**Time:** ~85 minutes

## The Problem

The checkout endpoint takes 900 ms and everybody has a theory.

The senior engineer is sure it's the JSON serialization — it's a big response, and JSON serialization is famously slow. It's a plausible theory, argued confidently, by the person with the most context. So someone spends two weeks rewriting the serializer around a faster library and a hand-rolled encoder for the hot types. It ships. The endpoint now takes **880 ms**.

Two weeks. A 2% win. And here is the part that should frighten you: the outcome was **fixed before the work began.** When someone finally profiles the thing, serialization turns out to be 3% of the request. Not "3% and we could find more" — 3%, full stop. Which means that even if the rewrite had made serialization *infinitely* fast, taking it to literally zero nanoseconds, the endpoint would have gone from 900 ms to 873 ms. A 1.03x speedup was the theoretical ceiling of a two-week project, and it was computable in ten seconds, on the first day, from one number.

That ceiling is **Amdahl's Law**, which you met in [Why Concurrency?](../01-why-concurrency/), and it is the reason profiling is not a debugging technique you reach for when stuck. It is a *prerequisite*. Not because guesses are usually wrong — though they are — but because a guess gives you no way to know how much a fix is worth *before* you pay for it.

So: profile first. Except that the first tool most people reach for is a **CPU profiler**, and in this story a CPU profiler would have shown almost nothing useful. 700 of the 900 ms turn out to be a single unindexed query issued once per line item — the [N+1 pattern](../../03-relational-databases/14-connection-pooling-and-n-plus-1/) — and that 700 ms is spent *waiting on a socket*, not executing instructions. A CPU profiler samples a thread only while that thread is on the CPU. A thread blocked in `recv()` is not on the CPU. It generates no samples. It does not appear in the profile *at all* — not as a small number you might overlook, but as an absence.

That is this lesson's headline mistake, and it is measurable. Here is the same phenomenon reproduced by the code you're about to build, on a workload whose true breakdown is known in advance:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="One 900 millisecond checkout request broken into its on-CPU and off-CPU segments, shown three times: the true wall-clock timeline, what an on-CPU profiler records, and what a wall-clock profiler records. The on-CPU profiler assigns zero percent to the 500 millisecond payment wait that is 55 percent of the request.">
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One request, 895 ms. Two profilers. Only one of them can see the wait.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="16" y="60" font-size="11" font-weight="700" opacity="0.8">TRUTH · wall clock</text>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="16" y="70" width="46" height="34" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="62" y="70" width="184" height="34" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="246" y="70" width="137" height="34" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="383" y="70" width="456" height="34" rx="4" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="839" y="70" width="25" height="34" rx="4" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    </g>
    <text x="39" y="91" font-size="8" text-anchor="middle" opacity="0.85">32</text><text x="154" y="91" font-size="9.5" text-anchor="middle">price_line_items 194</text><text x="314" y="91" font-size="9.5" text-anchor="middle">compute_tax 150</text>
    <text x="611" y="87" font-size="10.5" text-anchor="middle" font-weight="700" fill="#d64545">charge_payment — 501 ms BLOCKED on a socket</text><text x="611" y="100" font-size="9" text-anchor="middle" opacity="0.85">55.9% of the request · zero instructions executed</text>
    <text x="851" y="91" font-size="8" text-anchor="middle" fill="#e0930f" font-weight="700">18</text><text x="16" y="130" font-size="9" opacity="0.7">0 ms</text><text x="864" y="130" font-size="9" text-anchor="end" opacity="0.7">895 ms</text>

    <text x="16" y="168" font-size="11" font-weight="700" fill="#7c5cff">ON-CPU PROFILER · py-spy default, perf, ITIMER_PROF</text><text x="16" y="184" font-size="9.5" opacity="0.85">samples only fire while the thread is executing instructions</text>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="16" y="194" width="94" height="32" rx="4" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="110" y="194" width="437" height="32" rx="4" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="547" y="194" width="223" height="32" rx="4" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="770" y="194" width="94" height="32" rx="4" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    </g>
    <text x="63" y="214" font-size="9" text-anchor="middle">6.4%</text><text x="328" y="214" font-size="10" text-anchor="middle" font-weight="700">price_line_items 59.5%</text><text x="658" y="214" font-size="10" text-anchor="middle">compute_tax 30.3%</text>
    <text x="817" y="214" font-size="9" text-anchor="middle">3.7%</text><text x="440" y="248" font-size="10.5" text-anchor="middle" font-weight="700" fill="#d64545">charge_payment: 0.0% — 0 of 1,476 samples. It is not in the profile at all.</text>

    <text x="16" y="290" font-size="11" font-weight="700" fill="#3553ff">WALL-CLOCK PROFILER · py-spy --idle, off-CPU sampling</text><text x="16" y="306" font-size="9.5" opacity="0.85">samples fire on a timer whether the thread runs or waits</text>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="16" y="316" width="47" height="32" rx="4" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="63" y="316" width="184" height="32" rx="4" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="247" y="316" width="137" height="32" rx="4" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="384" y="316" width="454" height="32" rx="4" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff" stroke-width="2.4"/>
      <rect x="838" y="316" width="26" height="32" rx="4" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    </g>
    <text x="39" y="336" font-size="8" text-anchor="middle">3.5</text><text x="155" y="336" font-size="9" text-anchor="middle">price 24.3%</text><text x="315" y="336" font-size="9" text-anchor="middle">tax 16.2%</text>
    <text x="611" y="336" font-size="10.5" text-anchor="middle" font-weight="700">charge_payment 54.1% ← the answer</text><text x="851" y="336" font-size="8" text-anchor="middle">1.9</text>
    <text x="440" y="386" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">Worst error vs the truth measured during the same run: on-CPU 49.8 points · wall-clock 0.06 points.</text>
    <text x="440" y="414" font-size="11" text-anchor="middle" opacity="0.9">Both profilers are correct. They answer different questions — and "why is this slow" is the wall-clock one.</text>
  </g>
</svg>
```

Neither profiler is broken. They answer different questions. The on-CPU profiler answers *"what is burning the processor"* — the right question when you are paying for compute or hunting a hot loop. The wall-clock profiler answers *"why is this request slow"* — the right question when a user is waiting. Backend latency work almost always needs the second one, and reaching for the first is the single most common profiling mistake there is.

## The Concept

### Amdahl's Law is a budget, not a footnote

Before optimizing anything, compute the ceiling. If a component is fraction **f** of total runtime and you make it **k** times faster, the whole thing speeds up by:

```text
speedup = 1 / ((1 − f) + f/k)
```

The two terms are the two halves of the program: `(1 − f)` is everything you did *not* touch, which still costs exactly what it cost, and `f/k` is what's left of the part you did touch. Set `k = ∞` — a perfect, free, instantaneous version of your component — and the whole expression collapses to `1 / (1 − f)`. **That is the most your change can ever be worth**, and it depends on nothing but f.

Do this arithmetic first, always, and write down the answer. The rule of thumb that falls out is blunt:

> **If f < 10%, walk away unless the fix is free.**

At f = 2%, the ceiling is 1.02x. At f = 5%, it's 1.05x. Neither is worth a sprint, a rewrite, or a new dependency, because *no amount of cleverness* pushes past it. This is not a claim about how hard the optimization is; it's a claim about arithmetic. Meanwhile at f = 56% — the payment wait in this lesson's workload — merely making it 10x faster yields 2.01x end to end. Same effort, and roughly twenty-eight times the milliseconds on the table (501 ms of headroom against 18).

### CPU time vs wall-clock time: the distinction that picks your tool

A request's duration is made of two disjoint kinds of time:

- **On-CPU time** — the thread is executing instructions. Parsing, looping, serializing, hashing.
- **Off-CPU time** — the thread is blocked in the kernel, waiting: a socket read, a disk seek, a lock, a `sleep`, a queue, a connection pool with no free connections.

For most backend work the second dominates, and [Why Concurrency?](../01-why-concurrency/) put numbers on why: a main-memory reference is ~100 ns, an SSD read ~100 µs, a same-datacenter round trip ~500 µs, a cross-continent round trip ~150 ms. An endpoint that makes six database calls and two service calls has spent milliseconds of *duration* per call and microseconds of *CPU* per call. The ratio is routinely 100:1.

Now the mechanism, because "a CPU profiler can't see waiting" is only obvious once you know how a CPU profiler fires. The classical one arms an interval timer with `setitimer(ITIMER_PROF, …)` (POSIX.1-2001). `ITIMER_PROF` counts down in **process CPU time**, not wall-clock time, and delivers `SIGPROF` when it expires. A blocked process accrues no CPU time. The countdown *stops*. The signal never arrives. There is no filtering step that discards I/O — the profiler is simply never woken up during it.

So name the two categories and keep them straight for the rest of your career:

| | answers | fires on | use it for |
|---|---|---|---|
| **on-CPU profiler** | "what is burning the processor?" | CPU-time ticks | throughput, cloud bill, hot loops |
| **wall-clock / off-CPU profiler** | "why is this request slow?" | wall-clock ticks | latency, p99, "the endpoint is slow" |

The trap has a specific shape in production: you profile a slow endpoint with an on-CPU profiler, get a clean flame graph, dutifully optimize the top frame, and ship a change that moves p99 by 1%. The profile wasn't wrong. It was an answer to a question nobody asked.

### Sampling vs deterministic profiling

There are two ways to build a profiler at all, and they fail differently.

A **deterministic** (or *instrumenting*) profiler hooks every function call and every return. Python's `cProfile` does this through the interpreter's C-level profile hook. You get **exact call counts** and an **exact call graph** — no statistics, no confidence intervals, no "probably". That exactness is genuinely valuable and no sampler can give it to you.

The price is a fixed tax **per call**, and it lands unevenly. In the Build It, a one-line function measured **46 ns/call** on its own and **190 ns/call** under `cProfile` — a **4.2x** inflation. A function that takes 5 ms doesn't notice a 150 ns hook; a function called 50,000 times pays it 50,000 times. So the profiler makes many-small-calls code look disproportionately hot: **it distorts the very profile you are reading**, and always in the same direction. In the measured run, the 50,000-call component went from a true 194.2 ms to 248.0 ms under observation (**+27.7%**) while the single-call component moved **−0.0%**.

A **sampling** profiler interrupts the program on a timer and records the current stack. Overhead is a tunable constant that depends on the *sample rate*, not on what the program does; drop from 1,000 Hz to 100 Hz and the cost drops tenfold. The result is statistical: a component that occupied 20% of the time collects about 20% of the samples, with an error that shrinks as samples accumulate. Short-lived functions may never be sampled at all — but the *shares*, which is what you're reading a profile for, converge on the truth.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="The same call sequence measured two ways. A deterministic profiler hooks every call and return, giving exact counts but adding a fixed tax per call that inflated a one-line function from 46 to 190 nanoseconds. A sampling profiler interrupts on a fixed timer, missing short calls entirely but costing a tunable constant regardless of how many calls happen.">
  <defs><marker id="l13-b" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Deterministic taxes every CALL. Sampling taxes every TICK.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="16" y="52" font-size="10.5" font-weight="700" opacity="0.85">the same call sequence, one long call then eight short ones</text>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="16" y="62" width="230" height="26" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="252" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="290" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="328" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="366" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="404" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="442" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="480" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="518" y="62" width="34" height="26" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    </g>
    <text x="131" y="79" font-size="10" text-anchor="middle">compute_tax — one call, 150 ms</text><text x="402" y="104" font-size="9.5" text-anchor="middle" opacity="0.9">fetch_price x 8 — 4 us each</text><text x="568" y="79" font-size="9.5" opacity="0.75">→ time</text>

    <text x="16" y="128" font-size="11" font-weight="700" fill="#7c5cff">DETERMINISTIC · cProfile hooks every call and return</text>
    <g stroke="#7c5cff" stroke-width="2">
      <path d="M16 138 L 16 160 M246 138 L 246 160"/>
      <path d="M252 138 L 252 160 M286 138 L 286 160 M290 138 L 290 160 M324 138 L 324 160"/>
      <path d="M328 138 L 328 160 M362 138 L 362 160 M366 138 L 366 160 M400 138 L 400 160"/>
      <path d="M404 138 L 404 160 M438 138 L 438 160 M442 138 L 442 160 M476 138 L 476 160"/>
      <path d="M480 138 L 480 160 M514 138 L 514 160 M518 138 L 518 160 M552 138 L 552 160"/>
    </g>
    <path d="M16 160 L 560 160" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2"/>
    <text x="16" y="180" font-size="9.5" opacity="0.9">18 hook events. Exact call counts, exact call graph, no statistics.</text><text x="16" y="196" font-size="9.5" font-weight="700" fill="#7c5cff">Cost scales with CALLS: the 8 tiny calls pay 16 hooks; the 150 ms call pays 2.</text>

    <text x="16" y="240" font-size="11" font-weight="700" fill="#3553ff">SAMPLING · a timer interrupt records the stack, 1 ms apart</text>
    <g stroke="#3553ff" stroke-width="2.4">
      <path d="M50 250 L 50 272 M118 250 L 118 272 M186 250 L 186 272 M254 250 L 254 272"/>
      <path d="M322 250 L 322 272 M390 250 L 390 272 M458 250 L 458 272 M526 250 L 526 272"/>
    </g>
    <path d="M16 272 L 560 272" fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2"/>
    <text x="16" y="292" font-size="9.5" opacity="0.9">8 samples, whatever the code does. Most short calls are never seen —</text><text x="16" y="308" font-size="9.5" opacity="0.9">but over 2,779 samples the SHARES converge on the truth anyway.</text>
    <text x="16" y="324" font-size="9.5" font-weight="700" fill="#3553ff">Cost scales with SAMPLE RATE: halve the rate, halve the overhead.</text>

    <rect x="588" y="108" width="276" height="212" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8" fill-rule="evenodd"/>
    <text x="602" y="130" font-size="10.5" font-weight="700" fill="#e0930f">MEASURED, THIS LESSON</text><text x="602" y="152" font-size="9.5" opacity="0.95">one-line function, 200,000 calls</text><text x="602" y="168" font-size="10" font-weight="700">46 ns → 190 ns per call = 4.2x</text>
    <text x="602" y="192" font-size="9.5" opacity="0.95">price_line_items (50,000 calls)</text><text x="602" y="208" font-size="10" font-weight="700">194.2 ms → 248.0 ms  (+27.7%)</text><text x="602" y="230" font-size="9.5" opacity="0.95">compute_tax (1 call)</text>
    <text x="602" y="246" font-size="10" font-weight="700">150.0 ms → 150.0 ms  (−0.0%)</text><text x="602" y="272" font-size="9.5" opacity="0.95">sampler overhead at 1 kHz:</text><text x="602" y="288" font-size="10" font-weight="700">+3.6% wall-clock · +12.3% on-CPU</text>
    <text x="602" y="306" font-size="9" opacity="0.85">— and it does not care how many calls happen.</text>

    <text x="16" y="368" font-size="10.5" font-weight="700" fill="#d64545">The trap: the per-call tax lands on many-small-calls code, so a deterministic profile</text>
    <text x="16" y="384" font-size="10.5" font-weight="700" fill="#d64545">makes exactly that code look hotter than it is. It distorts the profile you are reading.</text>
    <text x="440" y="424" font-size="11" text-anchor="middle" opacity="0.9">Use cProfile for call counts and call graphs on a laptop. Use a sampler for time, and in production.</text>
  </g>
</svg>
```

The honest guidance: **reach for a deterministic profiler when you need call counts or a call graph, on a laptop, on a workload you control.** Reach for a **sampler** when you need time attribution, when the code is call-heavy enough that instrumentation would lie, or when the process is in production and cannot be restarted or slowed down. Only one of the two is safe to leave running.

### Reading a profile without being fooled

Every profiler reports two kinds of time per function, and confusing them is the second most common mistake after picking the wrong tool.

- **Self time** (`tottime` in `pstats`) — time in *this function's own body*, excluding anything it called.
- **Cumulative time** (`cumtime`) — time in this function *and everything it called*, from entry to return.

Two classic misreadings follow directly:

**Sorting by cumulative and "discovering" that `main` takes 100% of the time.** Of course it does; it called everything. Cumulative is monotonically non-increasing as you walk down a call chain, so the top of a cumulative sort is always the least actionable entry in the file. Cumulative is for *following a chain downward* — "the endpoint is 100%, of which the pricing step is 26%, of which the row lookup is 24%" — not for picking a winner.

**Sorting by self time and missing the real problem.** Self time correctly finds hot loops. It cannot see the shape where a cheap function is called an absurd number of times by one caller, because self time is spread thin: 50,000 × 4 µs looks like nothing per call. What you want there is the **call count**. An N+1 query is a *count* pathology, not a *duration* one, and it announces itself as `ncalls = 50000` next to an unremarkable per-call time. Scan the count column before you scan the time columns.

Finally, both views tell you *where* time went and neither tells you *who* to blame. The **caller/callee view** — `pstats`' `print_callers()` — does. A hot utility function used by forty call sites is not a bug in the utility; it's a bug in whichever caller invokes it 50,000 times, and only the caller/callee view names that caller.

### Flame graphs: width is samples, x is not time

A flame graph is the standard visualization for sampled stacks, and it is much simpler than it looks.

- Every box is a **stack frame**.
- Box **width** is the proportion of samples in which that frame appeared — that is, how much time was spent in it and everything above it.
- The **y-axis is stack depth**. A box sits directly on top of its caller.
- **The x-axis is not time.** Children are laid out in *alphabetical* order, so that identical stacks merge into one wide box instead of scattering into hundreds of slivers. A left-hand box did not run before a right-hand one.

What you're hunting for are **plateaus**: wide boxes with little or nothing stacked above them. A plateau means samples landed *in that frame's own body* — that's where the time actually is. A tall thin tower is a deep call chain that costs nothing.

Three variants worth knowing. An **icicle graph** is the same thing drawn downward (root at the top), which reads better when you care about the entry points. A **differential flame graph** colors boxes by the *change* in sample counts between two profiles — red for wider, blue for narrower — and is the fastest way to see what a change actually did. And the input format underneath all of them is **folded stacks**, which is not a magic artifact but one line of text per unique stack:

```text
checkout;price_line_items;fetch_price;_spin 664
```

Frames joined by `;`, a space, a sample count. That's the entire format, and the Build It emits it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="An annotated flame graph of the checkout endpoint showing that box width is the share of samples, the y axis is stack depth, plateaus mark where time is spent, and the x axis is not time because children are sorted alphabetically. The folded stack text that produced the graph is shown below it.">
  <defs><marker id="l13-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Reading a flame graph: width is samples, height is depth, x is NOT time</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="150" y="150" width="256" height="28" rx="3" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="406" y="150" width="153" height="28" rx="3" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="150" y="122" width="256" height="28" rx="3" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="406" y="122" width="153" height="28" rx="3" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="26" y="178" width="124" height="28" rx="3" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="2.4"/>
      <rect x="150" y="178" width="256" height="28" rx="3" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="406" y="178" width="153" height="28" rx="3" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="559" y="178" width="34" height="28" rx="3" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="26" y="206" width="567" height="28" rx="3" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    </g>
    <text x="88" y="197" font-size="9.5" text-anchor="middle" font-weight="700" fill="#d64545">charge_pay~</text><text x="278" y="197" font-size="9.5" text-anchor="middle">price_line_items</text><text x="482" y="197" font-size="9.5" text-anchor="middle">compute_tax</text>
    <text x="576" y="197" font-size="8" text-anchor="middle">val</text><text x="278" y="169" font-size="9.5" text-anchor="middle">fetch_price</text><text x="482" y="169" font-size="9.5" text-anchor="middle">_burn</text><text x="278" y="141" font-size="9.5" text-anchor="middle">_spin</text>
    <text x="482" y="141" font-size="9.5" text-anchor="middle">_spin</text><text x="309" y="225" font-size="10" text-anchor="middle" font-weight="700">checkout   (100% of samples)</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.8">
      <path d="M614 122 L 640 122" marker-end="url(#l13-ar)"/>
      <path d="M614 234 L 640 234" marker-end="url(#l13-ar)"/>
      <path d="M26 250 L 26 262 L 593 262 L 593 250" stroke-opacity="0.5"/>
      <path d="M88 122 L 88 178" stroke-dasharray="4 4" stroke-opacity="0.55" marker-end="url(#l13-ar)"/>
    </g>
    <text x="646" y="112" font-size="10" font-weight="700" fill="#0fa07f">a PLATEAU: a wide box</text><text x="646" y="126" font-size="10" font-weight="700" fill="#0fa07f">with nothing above it</text><text x="646" y="140" font-size="9.5" opacity="0.9">is where the samples</text>
    <text x="646" y="154" font-size="9.5" opacity="0.9">actually landed. Fix that.</text><text x="646" y="228" font-size="10" font-weight="700" fill="#3553ff">the root: every sample</text><text x="646" y="242" font-size="9.5" opacity="0.9">has it, so it is always</text>
    <text x="646" y="256" font-size="9.5" opacity="0.9">100% and always useless</text><text x="88" y="112" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">no children:</text>
    <text x="88" y="100" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">a blocking leaf</text><text x="309" y="278" font-size="10" text-anchor="middle" opacity="0.9">width = share of samples · y = stack depth (callers below, callees above)</text>

    <rect x="26" y="300" width="567" height="130" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.6" fill-rule="evenodd"/>
    <text x="40" y="320" font-size="10" font-weight="700" opacity="0.8">the folded stacks that produced it — the entire file format</text><text x="40" y="340" font-size="9.5">checkout;charge_payment 1503</text><text x="40" y="356" font-size="9.5">checkout;price_line_items;fetch_price;_spin 664</text>
    <text x="40" y="372" font-size="9.5">checkout;compute_tax;_burn;_spin 451</text><text x="40" y="388" font-size="9.5">checkout;validate_cart;_burn;_spin 96</text><text x="40" y="404" font-size="9.5">checkout;serialize_response;_burn;_spin 53</text>
    <text x="40" y="422" font-size="9" opacity="0.75">frames joined by ';' then a space and a sample count. That is all.</text>

    <rect x="613" y="300" width="251" height="130" rx="9" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.8"/>
    <text x="627" y="322" font-size="10.5" font-weight="700" fill="#e0930f">THE X-AXIS IS NOT TIME</text><text x="627" y="342" font-size="9.5" opacity="0.95">Children are sorted</text><text x="627" y="356" font-size="9.5" opacity="0.95">ALPHABETICALLY so that</text>
    <text x="627" y="370" font-size="9.5" opacity="0.95">identical stacks merge</text><text x="627" y="384" font-size="9.5" opacity="0.95">into one wide box.</text><text x="627" y="404" font-size="9.5" opacity="0.95">charge_payment sits left</text>
    <text x="627" y="418" font-size="9.5" opacity="0.95">of compute_tax; it ran after.</text><text x="440" y="456" font-size="11" text-anchor="middle" opacity="0.9">Left-to-right is spelling. A graph whose x-axis IS time is a flame chart, and it cannot merge stacks.</text>
  </g>
</svg>
```

### Profiling async code is genuinely harder

This is the part most treatments skip, and it is where a lot of production Python lives.

Stack sampling assumes the thing you care about is *on a stack*. In an `async` service that assumption breaks. When a coroutine hits `await`, its frames are detached from the thread and parked on the task object; the thread goes back to the [event loop](../04-the-event-loop/). So a sampled stack taken during that time shows the **loop's** frames — `run_forever` → `_run_once` → `select` — and not the logical request that is suspended. A coroutine awaiting a 500 ms database call contributes **zero samples**, because there is nothing on the stack to sample. It's the same blindness as the CPU profiler, arriving by a completely different route.

Measured in the Build It: three concurrent requests, 1,202 ms of logical request time in total. The wall-clock sampler attributed **150 ms — 12%** — to the request handler. The other 88% is charged to the event loop's own `select()` frame, which no engineer can act on.

So for async services you need different instruments:

- **Event-loop lag** (from [The Event Loop](../04-the-event-loop/)): schedule a callback every 5 ms and measure how late it actually runs. Lag is the loop's saturation signal and the only thing that reliably catches a blocking call inside a coroutine. In the Build It, a p50 of 0.38 ms with a max of **150 ms** exactly fingerprints three 50 ms blocking bursts that refused to yield.
- **`asyncio` debug mode**, which logs any callback that runs longer than a threshold — a blocking call inside a coroutine, named, with its stack.
- **Task-aware or wall-clock tooling** (`yappi` understands coroutines and can aggregate by task).
- **Spans at the logical boundaries** — start a span when the request arrives, close it when it leaves, and record child spans around each `await`ed dependency. Which is precisely what distributed tracing does, and why: [Distributed Tracing & OpenTelemetry](../../09-logging-monitoring-and-observability/07-distributed-tracing-and-opentelemetry/) exists because stacks stop being the unit of work the moment concurrency arrives.

State it plainly: **for an async service, tracing is often the better profiler.** A trace follows the logical request across suspensions, threads and processes; a stack profiler follows a thread. Only one of those matches what a user experienced.

### Memory profiling is a different discipline

Time profilers cannot find memory problems, and the three things people call "a memory leak" are not the same bug:

1. **Genuine unbounded retention.** A cache with no eviction, a list you append to per request, a module-level dict keyed by user. Memory grows monotonically with traffic and the process eventually dies. This is a real leak.
2. **A high-water mark.** One request loads a 2 GB result set, builds it, returns it, and frees it. The allocator returns very little of that to the OS, so resident memory stays high forever. Nothing is leaking; your process is simply *sized* by its worst request. The fix is streaming or pagination, not leak-hunting.
3. **Fragmentation and allocator behaviour.** Freed memory that can't be coalesced into blocks the OS will take back. Looks like a slow leak, is not one, and is not fixable at the call site.

The only reliable way to tell them apart is a **snapshot diff**. `tracemalloc` records the allocation traceback for every live block; take a snapshot, run the workload, take another, and `compare_to()` shows you the per-line *delta* in bytes and block count. A single snapshot cannot distinguish case 1 from case 2 — both look like "a lot of memory was allocated here." The diff can: retention shows up as a positive delta that keeps growing across cycles, while a high-water mark nets out to roughly zero and shows up only as `peak` exceeding `current`.

One more thing that hides in plain sight: **allocation is a CPU cost too.** Allocating and garbage-collecting millions of short-lived objects burns real processor time, but it appears in a CPU profile as diffuse overhead spread across `gc` internals and allocator frames rather than as one hot function. It's easy to miss precisely because it never forms a plateau.

### The USE method: which resource, before which profiler

Before you profile anything you should know *which resource* is the problem, and the checklist for that is Brendan Gregg's **USE method** (Gregg, *Systems Performance*, Prentice Hall 2013). For every resource, check three things:

- **Utilization** — the fraction of time the resource was busy.
- **Saturation** — the amount of queued work it could not service. This is the leading indicator; utilization saturates at 100% and stops telling you anything, while the queue keeps growing.
- **Errors** — error events, which are often invisible in the other two.

Apply it per resource: CPU, memory, disk, network — *and your own software resources*, which is where backend engineers actually find things: the connection pool, the thread pool, the worker queue, the event loop. A connection pool at 100% utilization with a growing wait queue is the whole answer, and no code profiler would have told you.

USE comes **before** profiling, not after, because it decides which profiler you need. Saturated CPU → on-CPU profiler. Saturated pool or high off-CPU time → wall-clock profiler, or just fix the pool. Growing memory → memory profiler. The [RED and USE dashboards lesson](../../09-logging-monitoring-and-observability/11-dashboards-red-and-use/) builds exactly these panels.

### Profiling in production

**A profile of your laptop is a profile of your laptop.** Different CPU, different memory bandwidth, no network latency to the database, no noisy neighbours, no realistic cache hit rates, no concurrency, and a dataset a thousand times smaller. The bottleneck you find locally may not exist in production, and the one that's killing you in production may be invisible locally.

The modern answer is **continuous profiling**: a low-frequency sampler (10–100 Hz rather than 1,000) running always, in production, shipping folded stacks to a store you can query. Two properties make this acceptable:

- **Overhead is a knob.** Sampling cost is proportional to rate. At 100 Hz it is typically a percent or less, and it does not grow when your code makes more calls — the property a deterministic profiler cannot offer at any setting.
- **No code changes.** An attach-based sampler like `py-spy` reads the target process's memory from the *outside* using `process_vm_readv(2)`. It imports nothing into your process, requires no restart, and cannot deadlock your application. You point it at a PID.

What it buys you is the thing incident reviews always want and never have: **a flame graph of the incident, taken during the incident, available after the incident.** Rather than "we think it was the pricing path" you get the actual profile from 03:14, diffable against the profile from 02:14.

`py-spy` also has `dump`, which prints the current stack of every thread in a running process — including one that is hung. That is often the single fastest way to diagnose a [deadlock](../10-deadlock-livelock-and-starvation/): you see exactly which lock each thread is waiting on, without a debugger and without restarting anything.

### The optimization loop

Everything above assembles into a loop, and the loop has a gate in it.

**Measure → compute the ceiling → hypothesize with a predicted magnitude → change one thing → re-measure → keep or revert.**

The step people skip is the **predicted magnitude**. Not "this should help" but "*this should save 170 ms of the 895, taking p50 to about 725*." Insist on it, because it is what converts profiling from browsing into science: a prediction can be *wrong*, and a wrong prediction means your model of the system is wrong, which is worth more than the 170 ms. It is also what protects you when a change appears to help by less than the run-to-run noise — the trap [Benchmarking & Load Testing](../14-benchmarking-and-load-testing/) is entirely about. A 900 ms → 880 ms "win" measured once is not a win; it is a sample.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="The optimization loop drawn as a cycle: measure with the right profiler, then pass through Amdahl's ceiling as a gate that rejects any component below ten percent of runtime, then form a hypothesis with a predicted magnitude, change exactly one thing, and re-measure to keep or revert. Two exits leave the loop: walk away when the ceiling is too low, and revert when the measured gain is smaller than the noise.">
  <defs><marker id="l13-c" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l13-cr" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#d64545"/></marker></defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The optimization loop — with Amdahl's ceiling as the gate, not the retro</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="92" width="152" height="86" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="196" y="92" width="176" height="86" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2.6"/>
      <rect x="400" y="92" width="160" height="86" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="588" y="92" width="120" height="86" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="736" y="92" width="128" height="86" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#l13-c)">
      <path d="M168 135 L 190 135"/><path d="M372 135 L 394 135"/>
      <path d="M560 135 L 582 135"/><path d="M708 135 L 730 135"/>
      <path d="M800 178 L 800 232 L 92 232 L 92 182"/>
    </g>
    <text x="510" y="252" font-size="10" text-anchor="middle" opacity="0.85">the new profile becomes the next baseline — keep the old one to diff against</text>

    <text x="92" y="116" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">1 · MEASURE</text><text x="26" y="134" font-size="9">USE + golden signals</text><text x="26" y="148" font-size="9">to localize, THEN pick:</text>
    <text x="26" y="164" font-size="9" font-weight="700">latency → wall-clock</text><text x="26" y="176" font-size="9" font-weight="700">cost → on-CPU</text>

    <text x="284" y="116" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">2 · THE CEILING (GATE)</text><text x="206" y="136" font-size="9.5">f = this component's share</text><text x="206" y="152" font-size="10" font-weight="700">max gain = 1/(1 − f)</text>
    <text x="206" y="170" font-size="9.5">f=2% → 1.02x, forever</text>

    <text x="480" y="116" font-size="11" font-weight="700" text-anchor="middle" fill="#7c5cff">3 · HYPOTHESIS</text><text x="410" y="136" font-size="9.5">with a PREDICTED</text><text x="410" y="150" font-size="9.5">MAGNITUDE, in ms:</text>
    <text x="410" y="168" font-size="9.5" font-weight="700">"batching saves ~170 ms"</text>

    <text x="648" y="116" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">4 · CHANGE</text><text x="648" y="140" font-size="11" font-weight="700" text-anchor="middle" fill="#0fa07f">ONE THING</text>
    <text x="648" y="162" font-size="9" text-anchor="middle" opacity="0.9">two changes =</text><text x="648" y="174" font-size="9" text-anchor="middle" opacity="0.9">no attribution</text>

    <text x="800" y="116" font-size="11" font-weight="700" text-anchor="middle" fill="#3553ff">5 · RE-MEASURE</text><text x="746" y="138" font-size="9.5">same tool, same</text><text x="746" y="152" font-size="9.5">environment, same</text><text x="746" y="166" font-size="9.5">load. Keep/revert.</text>

    <g fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l13-cr)">
      <path d="M230 178 L 230 296"/><path d="M800 92 L 800 66 L 640 66 L 640 62"/>
    </g>
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="150" y="300" width="268" height="62" rx="10" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
      <rect x="452" y="300" width="412" height="62" rx="10" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>
    <text x="284" y="322" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">EXIT: f &lt; 10% → WALK AWAY</text><text x="284" y="340" font-size="9.5" text-anchor="middle">unless the fix is free. Measured here:</text>
    <text x="284" y="354" font-size="9.5" text-anchor="middle" font-weight="700">serialize_response, f=2.0%, ceiling 1.02x</text>

    <text x="658" y="322" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">EXIT: gain &lt; noise → REVERT, and say so</text><text x="658" y="340" font-size="9.5" text-anchor="middle">A 900 ms → 880 ms "win" on one run is not a win.</text>
    <text x="658" y="354" font-size="9.5" text-anchor="middle">You need a confidence interval before you keep a diff.</text><text x="640" y="52" font-size="9.5" text-anchor="middle" fill="#d64545" font-weight="700">not significant?</text>

    <text x="440" y="386" font-size="11" text-anchor="middle" opacity="0.9">The predicted magnitude is what turns profiling from browsing into science: a prediction can be wrong.</text>
  </g>
</svg>
```

## Build It

The centerpiece is a **sampling profiler you write yourself**, because that's what turns `py-spy` and flame graphs from magic into forty lines of code you already understand.

Everything is graded against a workload whose true cost is known. `checkout()` has five components with deliberately chosen costs: one genuinely CPU-hot function, one that makes 50,000 cheap calls (the N+1 shape), one that sleeps (simulated I/O), and one red herring sized at 2% of the runtime. Ground truth comes from two `perf_counter()` calls per component — about 200 ns on a 900 ms request, cheap enough to leave running while the profilers work:

```python
def checkout(order: dict) -> int:
    """POST /checkout -- the endpoint everyone has a theory about."""
    with GT.time("validate_cart"):
        validate_cart(order)
    with GT.time("price_line_items"):
        subtotal = price_line_items(order)
    with GT.time("compute_tax"):
        tax = compute_tax(subtotal)
    with GT.time("charge_payment"):
        charge_payment(subtotal + tax)
    with GT.time("serialize_response"):
        return serialize_response(order, subtotal + tax)
```

Reading a stack is one function. Walk `f_back` to the root, keep the code object names, reverse. This is the whole primitive — `py-spy`'s version does the same walk, except over another process's memory:

```python
def stack_of(frame, root: str | None = "checkout", depth: int = 6) -> tuple[str, ...]:
    names: list[str] = []
    found = root is None
    while frame is not None and len(names) < 64:
        names.append(frame.f_code.co_name)
        if root is not None and frame.f_code.co_name == root:
            found = True
            break
        frame = frame.f_back
    if not found:
        return ()                      # not inside the endpoint: drop the sample
    names.reverse()
    return tuple(names[-depth:])
```

The **wall-clock sampler** is a background thread that snapshots the target thread's frame on a fixed wall-clock schedule. `sys._current_frames()` returns the topmost frame of every live thread, which is the one hook that makes this possible from inside Python:

```python
def _loop(self) -> None:
    nxt = perf_counter()
    while not self._stop.is_set():
        frame = sys._current_frames().get(self.target_tid)
        if frame is not None:
            st = stack_of(frame, self.root)
            if st:
                self.counts[st] += 1
                self.samples += 1
        nxt += self.interval               # absolute deadlines, so no drift
        time.sleep(max(0.0, nxt - perf_counter()))
```

The **on-CPU sampler** is the same idea driven by a different clock, and the difference is only in which timer arms it:

```python
def __enter__(self):
    self._old = signal.signal(signal.SIGPROF, self._handler)
    signal.setitimer(signal.ITIMER_PROF, self.interval, self.interval)
    return self
```

`ITIMER_PROF` counts down in **process CPU time**. Nothing in the handler filters out I/O — the kernel simply never delivers the signal while the process is blocked. That is the entire mechanism behind "a CPU profiler is blind to waiting."

Finally, the flame graph. Folded stacks are one line of text per unique stack, and the renderer lays children out alphabetically at a width proportional to their sample count — which is exactly why the x-axis carries no time information:

```python
def fold(counts: dict[tuple[str, ...], int]) -> list[str]:
    """The folded-stack format: `a;b;c 42`. That is the entire file format."""
    return [f"{';'.join(st)} {n}" for st, n in sorted(counts.items())]
```

The rest — `cProfile` wrangling, the Amdahl table, the `tracemalloc` diff and the asyncio experiment — is in [`code/profiling.py`](code/profiling.py). Run it:

```bash
python3 profiling.py
```

```console
Python 3.12.13  ·  spin rate 13.3M iters/s  ·  fetch_price calibrated to 56 iters

== 1 · THE ENDPOINT, AND ITS GROUND TRUTH ==
  POST /checkout ->   895.1 ms wall clock, best of 3 (50,000 line items)
  component               wall ms    share   kind
  validate_cart              32.0    3.6%   on-CPU
  price_line_items          194.2   21.7%   on-CPU
  compute_tax               150.0   16.8%   on-CPU
  charge_payment            500.8   55.9%   waiting (0 CPU)
  serialize_response         18.0    2.0%   on-CPU
  ---- on-CPU  394.3 ms (44.1%)   off-CPU  500.8 ms (55.9%)
  Every profiler below is graded against this table.

== 2 · cProfile: EXACT COUNTS, DISTORTED TIME ==
  --- sorted by CUMULATIVE time: every caller of the slow thing ---
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1    0.000    0.000    0.950    0.950 profiling.py:214(checkout)
   1    0.000    0.000    0.502    0.502 profiling.py:202(charge_payment)
   1    0.502    0.502    0.502    0.502 {built-in method time.sleep}
   50576    0.426    0.000    0.426    0.000 profiling.py:65(_spin)
   ...
  --- sorted by TOTTIME (self time): where the work actually is ---
   ncalls  tottime  percall  cumtime  percall filename:lineno(function)
   1    0.502    0.502    0.502    0.502 {built-in method time.sleep}
   50576    0.426    0.000    0.426    0.000 profiling.py:65(_spin)
   50000    0.013    0.000    0.239    0.000 profiling.py:103(fetch_price)
   1    0.009    0.009    0.248    0.248 profiling.py:188(price_line_items)
   ...
  fetch_price: ncalls=50,000  tottime=  13.1 ms  cumtime= 239.3 ms  = 4.79 us per call
  Nothing about that per-call number says 'bug'. The COUNT does.
  workload alone         895.1 ms   (best of 3, no profiler)
  workload + cProfile    950.5 ms   = +6.2% wall
  That total UNDERSTATES the damage, because a sleep and three
  deadline-driven burns cannot be slowed down. Look per component:
    price_line_items (50,000 calls)   true  194.2 ms  ->  under cProfile  248.0 ms  (+27.7%)
    compute_tax (1 call)              true  150.0 ms  ->  under cProfile  150.0 ms  (-0.0%)
  the per-call tax, isolated: 200,000 calls to a one-line function
    plain     46 ns/call   under cProfile    190 ns/call   = 4.2x
  A deterministic profiler taxes CALLS, not time. It therefore makes
  many-small-calls code look hotter than it is.

== 3 · TWO SAMPLING PROFILERS, BUILT FROM SCRATCH ==
  on-CPU     (SIGPROF / ITIMER_PROF, 1 ms): 1,476 samples / 3 requests, +12.3% overhead
  wall-clock (thread + _current_frames, 1 ms): 2,779 samples / 3 requests, +3.6% overhead

  component               TRUTH   cProfile   on-CPU   wall-clock
  validate_cart             3.6%       3.4%      6.4%        3.5%
  price_line_items         21.7%      26.1%     59.5%       24.3%
  compute_tax              16.8%      15.8%     30.3%       16.2%
  charge_payment           55.9%      52.8%      0.0%       54.1%   <- INVISIBLE
  serialize_response        2.0%       1.9%      3.7%        1.9%
  worst error against the ground truth measured DURING each run:
    cProfile 0.00 pts · on-CPU 49.81 pts · wall-clock 0.06 pts
  The on-CPU sampler is not wrong about CPU. It answers a question
  nobody asked when the complaint is 'checkout takes a second'.
  Same sampler, default 5 ms GIL switch interval instead of 0.2 ms:
    charge_payment reads 91.4% (truth 49.4%), worst error 42.1 pts
  A sampler that must win the GIL is starved exactly while the target
  burns CPU, so it over-counts the idle parts. Real samplers read the
  target from OUTSIDE the process for precisely this reason.

== 4 · FOLDED STACKS AND A FLAME GRAPH ==
  2,779 samples collapsed into 7 unique stacks. The folded format is the whole artifact:
    checkout;charge_payment 1503
    checkout;price_line_items;fetch_price;_spin 664
    checkout;compute_tax;_burn;_spin 451
    checkout;validate_cart;_burn;_spin 96
    checkout;serialize_response;_burn;_spin 53
    ...
  Rendered (width = share of samples, y = stack depth):
  |                                       [  _spin   ][     _spin     ]|||||  depth 3  ( 45.5%)
  |                                       [  _burn   ][  fetch_price  ]|||||  depth 2  ( 45.6%)
  |[            charge_payment           ][compute_t~][price_line_ite~]|||||  depth 1  (100.0%)
  |[                               checkout                               ]|  depth 0  (100.0%)
  Plateaus are where the time is. Children are ordered
  ALPHABETICALLY so identical stacks merge -- the x-axis is not time.

== 5 · AMDAHL'S LAW: COMPUTE THE CEILING BEFORE YOU START ==
  speedup = 1 / ((1-f) + f/k)     f = fraction of runtime, k = factor faster
  component                 f     k=2     k=10    k=inf   ms saved   verdict
  validate_cart            3.6%   1.02x    1.03x    1.04x        32   walk away unless free
  price_line_items        21.7%   1.12x    1.24x    1.28x       194   worth a sprint
  compute_tax             16.8%   1.09x    1.18x    1.20x       150   worth a sprint
  charge_payment          55.9%   1.39x    2.01x    2.27x       501   worth a sprint
  serialize_response       2.0%   1.01x    1.02x    1.02x        18   walk away unless free
  The senior engineer's rewrite of serialize_response: at k=INFINITY the
  endpoint gets 2.0% faster. That is the whole prize. Two weeks for it.
  The wait is f=55.9%: making it 10x faster is 2.01x end to end.
  Do this arithmetic BEFORE the sprint, not in the retro.

== 6 · tracemalloc: ONLY THE DIFF CAN FIND A LEAK ==
  one snapshot at the end: current   4.46 MB   peak   8.93 MB
  A single number cannot tell a leak from a high-water mark. The diff can:
      +3.76 MB   +39,225 blocks  profiling.py:635  retained.append({"order": i, "blob": "x" * 96})
      +0.56 MB   +17,430 blocks  profiling.py:634  for i in range(n):
      +0.10 MB      +880 blocks  profiling.py:639  rows = [{"order": i, "blob": "y" * 96} for i in rang
  retained now holds 20,200 dicts and never shrinks: THE LEAK.
  transient_report allocated 4.47 MB more at its peak and gave
  it all back -- it inflates RSS, it is not a leak, and the diff ignores it.

== 7 · ASYNC: A SUSPENDED COROUTINE IS ON NO STACK AT ALL ==
  3 concurrent requests, 451 ms wall clock, 457 wall-clock samples
  logical request time actually elapsed: 1202 ms (3 x 401 ms)
  samples with order_handler anywhere on the stack: 150 (32.8%) ~= 150 ms
  Where every sample went:
     67.0%  run_until_complete;run_forever;_run_once;select
     32.8%  _run;order_handler;_burn;_spin
      0.2%  __enter__;start;wait;wait
  The 300 ms await is on NO stack: a suspended coroutine has no
  frames to sample. The profiler accounts for 150 ms of 1202 ms
  of request time -- 12%. The other 88% is charged to the event
  loop's own select() frame, which no engineer can act on.
  Loop lag finds what the stacks could not:
    55 probes: p50 0.38 ms   p95 1.4 ms   max 150 ms
  A p50 of 0.38 ms and a max of 150 ms is the signature of 3 x 50 ms
  of blocking CPU running back to back without yielding. That is the
  bug, and loop lag names it in one number.

Done. Measure, compute the ceiling, change one thing, measure again.
```

**Read the numbers — six of these sections are arguments, not demos.**

**Section 1** is the answer key, and its shape is the shape of a real endpoint: **895.1 ms**, of which **394.3 ms (44.1%) is on-CPU** and **500.8 ms (55.9%) is spent waiting**. The N+1 component costs 194.2 ms across 50,000 calls, the genuinely hot function costs 150.0 ms in one call, and `serialize_response` — the one everyone in the story blamed — costs **18.0 ms, or 2.0%**.

**Section 2** is more subtle than "cProfile is slow," and the subtlety matters. First, `cProfile` measures *wall-clock* time per call, so it does **not** miss the sleep: `{built-in method time.sleep}` sits at the top of the tottime sort with 0.502 s. That is worth internalizing, because it is the opposite of what people assume — the deterministic profiler sees the I/O, and the *sampling CPU* profiler is the one that can't. Second, look at `fetch_price`: **ncalls = 50,000, tottime 13.1 ms, cumtime 239.3 ms, 4.79 µs per call.** Nothing about "4.79 µs" says *bug*. The number that says bug is **50,000**, sitting in the leftmost column, which is why you scan counts before durations. Third, the distortion, quantified three ways: the total run grew only **+6.2%** (a sleep cannot be slowed down and neither can a deadline-driven burn), but the 50,000-call component grew **+27.7%** while the single-call component moved **−0.0%**, and a one-line function isolated on its own went from **46 ns to 190 ns per call — 4.2x**. The tax is per *call*, so it lands entirely on the code that makes the most calls, which is systematically the code you are trying to evaluate.

**Section 3 is the head-to-head, and the point of the lesson.** Same workload, three profilers, one answer key. `charge_payment` is **55.9% of the request** and the on-CPU sampler reports it as **0.0% — 0 of 1,476 samples**. Not underweighted; absent. And its absence doesn't just lose that row, it *inflates every other row*: `price_line_items` reads **59.5%** against a true 21.7%, because percentages must sum to 100 and the missing 56 points get redistributed across whatever was left. An engineer reading that profile would conclude the pricing loop is nearly 60% of the endpoint and spend a fortnight there. The wall-clock sampler, sampling the same thread with the same stack-walking code and differing only in which clock arms it, lands within **0.06 percentage points** of the truth measured during its own run. Worst-case error: **49.81 points versus 0.06.** One line of difference in the profiler; a completely different engineering decision.

The **GIL** (Global Interpreter Lock — the interpreter lock that lets only one thread execute Python bytecode at a time, from [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/)) delivers the section's last result, and it is a warning about home-made tooling. Our sampler is a Python thread, so it must acquire the GIL to take a sample — and the thread holding the GIL only offers it up every `sys.setswitchinterval()` seconds, 5 ms by default. During `time.sleep()` the GIL is free and the sampler runs at its full 1 kHz; during a CPU burn it is starved. Left at the default, the sampler reports `charge_payment` at **91.4% against a true 49.4% — 42.1 points of error**, systematically over-counting the idle parts. Dropping the switch interval to 0.2 ms fixes it, at a cost. This is the concrete reason production samplers live *outside* the process: `py-spy` reads your memory with `process_vm_readv(2)` and never asks your interpreter for permission.

**Section 5** puts a price on the opening story. `serialize_response` is f = 2.0%, so at k = ∞ — a free, instantaneous, perfect serializer — the endpoint improves by **2.0%**, ceiling **1.02x**. That was the entire available prize on day one, computable from one row of a table. Meanwhile `charge_payment` at f = 55.9% yields **2.01x for a 10x improvement** and **2.27x** at the limit — **501 ms of headroom against 18 ms**. Same two weeks, and the only thing separating the two decisions is having measured before choosing.

**Section 6** separates the three memory bugs. After the workload, a single snapshot reports **current 4.46 MB, peak 8.93 MB** — and from that pair alone you cannot say whether you have a leak. The diff can: `compare_to()` attributes **+3.76 MB across +39,225 blocks** to the line that appends to a never-evicted list, and only **+0.10 MB** to the line that builds a 20,000-row report — because that report was freed. The **4.47 MB gap between peak and current** *is* the transient allocation: it inflated resident memory, it is not a leak, and only the diff distinguishes them. **Section 7** shows the async blindness end to end: 1,202 ms of logical request time, of which the sampler can account for **150 ms (12%)**, with **67.0% of samples** charged to `run_forever;_run_once;select`. Loop lag, by contrast, reports **p50 0.38 ms, max 150 ms** — and that max is exactly three 50 ms blocking bursts run back to back, which is the bug, named, in one number the stacks could not produce.

## Use It

Nothing above needs to be hand-written in production. Here is the real toolbox, and when to reach for each.

**`cProfile` + `pstats`** — the stdlib deterministic profiler. Right for call counts, call graphs, and local work on a workload you control:

```bash
python -m cProfile -o out.prof -s cumulative myscript.py
python -m pstats out.prof            # then: sort tottime / stats 20 / callers fetch_price
pip install snakeviz && snakeviz out.prof     # an interactive sunburst of the same data
```

`pstats`' `print_callers()` is your caller/callee view — the one that names *who* invoked the cheap function 50,000 times.

**`py-spy`** — the default for a live or production Python process. It attaches to a running PID, requires no code changes, imports nothing into your process, and cannot deadlock it:

```bash
py-spy record -o flame.svg --pid 4242 --duration 60      # on-CPU flame graph
py-spy record -o flame.svg --pid 4242 --idle             # INCLUDE off-CPU time  <- latency work
py-spy record -o folded.txt -f raw --pid 4242            # folded stacks, for diffing
py-spy top --pid 4242                                    # a live `top` of your functions
py-spy dump --pid 4242                                   # every thread's stack, incl. a hung one
```

`--idle` is the single most important flag in this lesson: it is the switch between the two profilers in the first diagram. `py-spy record -f raw` emits precisely the `a;b;c 42` folded format your `fold()` produces, and `dump` is your `stack_of()` applied to every thread at once.

**`austin`** is a comparable attach-based sampler with very low overhead and its own frame-format output; **`yappi`** is the one to reach for when you need per-thread or coroutine-aware accounting, since it understands `asyncio` tasks and can report wall or CPU clock per task. **`tracemalloc`** (stdlib) and **`memray`** cover memory — `memray` adds native allocations and a live mode. For a whole-system view, **`perf`** plus Brendan Gregg's FlameGraph scripts profiles your process alongside the kernel, the allocator and every other process on the box:

```bash
perf record -F 99 -g -p 4242 -- sleep 30
perf script | stackcollapse-perf.pl | flamegraph.pl > system.svg
```

Two more stdlib notes. Python 3.12 added **`sys.monitoring`** (PEP 669), a low-overhead monitoring API that lets tools subscribe to specific events and disable them per code location — the foundation newer profilers build on to avoid `cProfile`'s blanket per-call tax. And know `cProfile`'s limits with threads: it profiles the thread that called `enable()`, so a thread pool needs a profiler per thread (or `yappi`).

Finally, **continuous profiling services** (Pyroscope, Parca, and the vendor equivalents) take low-frequency samples permanently from every instance and store them. That is what makes "show me the flame graph from during the incident, diffed against an hour earlier" a query rather than a wish.

Production rules that survive contact with reality:

- **Profile the environment that is slow, not your laptop.** Different CPU, no network to the database, a toy dataset, no concurrency. If the bug reproduces only in production, the profile has to come from production.
- **Wall-clock for latency, on-CPU for throughput and cost.** If a user is waiting, you need `--idle` or an off-CPU profiler; if you're trying to cut the instance bill or find a hot loop, you want on-CPU. Getting this backwards produces a beautiful profile of the wrong 44% of the request.
- **Compute Amdahl's ceiling before you start, and write the number in the ticket.** `1/(1−f)`. Below 10%, walk away unless the fix is free. This one habit would have prevented the two-week story.
- **Change one thing at a time, with a predicted magnitude.** Two changes in one deploy give you one unattributable result, and a change with no prediction can never be falsified.
- **Keep the before-profile.** Save the folded stacks and diff them; a differential flame graph tells you what your change actually did, including the parts that got *slower*.
- **If it is an async service, reach for tracing and loop lag before a stack profiler** — the suspended coroutine that holds your p99 is on no stack for any sampler to find.

## Think about it

1. Your on-CPU flame graph shows one function at 71% and you make it twice as fast, but p99 latency does not move at all. Give two distinct explanations that are both consistent with those observations, and say what you would measure next to tell them apart.
2. `cProfile` inflated the 50,000-call component by 27.7% and the 1-call component by 0%. If you used a `cProfile` run to decide *which of the two* to optimize, in which direction would the decision be biased — and does sampling have an analogous bias, or a different one?
3. Continuous profiling at 100 Hz on a service handling 3,000 requests/second: how many samples does a single request contribute, and what does that imply about what you can and cannot conclude from one request's flame graph versus an hour's?
4. Your service's resident memory climbs to 6 GB over a week and plateaus there, and `tracemalloc` snapshot diffs across that week show near-zero net growth. Which of the three memory patterns is this, what is the actual cause, and what would you change?
5. You need to profile a service that is currently on fire — p99 at 40 seconds, on-call paged, no profiler installed. Order your first three commands and justify each, including what you would refuse to do and why.

## Key takeaways

- **Compute Amdahl's ceiling before you optimize, not in the retro.** `speedup = 1/((1−f) + f/k)`, and at `k = ∞` it is just `1/(1−f)`. Measured here: `serialize_response` at **f = 2.0%** has a ceiling of **1.02x** no matter what you do to it, while `charge_payment` at **f = 55.9%** yields **2.01x** for a mere 10x improvement. If f < 10%, walk away unless the fix is free.
- **An on-CPU profiler is blind to waiting, and that is a definition, not a bug.** `ITIMER_PROF` counts down in CPU time, so a blocked thread generates no samples. The 500.8 ms payment wait — **55.9% of the request** — was reported as **0.0% of 1,476 samples**, and its absence inflated the pricing loop to **59.5%** against a true 21.7%. Worst-case error: **49.81 points on-CPU versus 0.06 wall-clock**. For latency work, use wall-clock (`py-spy --idle`); for throughput and cost, use on-CPU.
- **Deterministic profilers tax calls; samplers tax ticks.** `cProfile` took a one-line function from **46 ns to 190 ns per call (4.2x)** and inflated the 50,000-call component by **+27.7%** while leaving the single-call component at **−0.0%** — it makes many-small-calls code look hotter than it is. Sampling costs a tunable constant (**+3.6%** at 1 kHz here, and proportionally less at 100 Hz), which is what makes always-on production profiling possible.
- **`tottime` is this function; `cumtime` is this function plus everything it called** — so a cumulative sort always crowns `main` at 100%, and a self-time sort misses N+1s entirely. The N+1 here announced itself as **`ncalls = 50,000` at an unremarkable 4.79 µs per call**: read the count column first, and use the caller/callee view to find *who* to fix.
- **In a flame graph, width is the share of samples, y is stack depth, and the x-axis is not time** — children are sorted alphabetically so identical stacks merge. Plateaus are where the time is. The underlying artifact is folded stacks, `checkout;price_line_items;fetch_price;_spin 664`, which is all `py-spy record -f raw` emits and all a differential flame graph diffs.
- **Async breaks stack profiling and memory needs a diff.** A suspended coroutine has no frames: the sampler could account for only **150 ms of 1,202 ms (12%)** of request time, charging **67.0%** to the loop's own `select()`, while loop lag caught the bug at **max 150 ms** against a p50 of 0.38 ms. For memory, `current 4.46 MB / peak 8.93 MB` cannot distinguish a leak from a high-water mark — the snapshot diff, showing **+3.76 MB** on the retained line and **+0.10 MB** on the transient one, can.

Next: [Benchmarking & Load Testing: Numbers You Can Trust](../14-benchmarking-and-load-testing/) — building the statistical rigour that decides whether the 900 ms → 880 ms change you just profiled is a real win or run-to-run noise.
