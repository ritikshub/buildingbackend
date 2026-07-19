# Chaos Engineering & Testing in Production

> Take one dependency and kill it outright: **0 failed requests, 0.0 minutes of error budget**, and the circuit breaker trips **10 times** doing its job. Take the same dependency and make it merely **5× slower** for the same 20 seconds: **2,744 failed requests, 130.7 minutes of error budget**, a median user latency of **2,006 ms**, a queue **675 deep** on a service two hops away — and the breaker trips **zero** times, because a slow dependency does not produce errors to count. Then the result that should change your retry config today: against a 30-second latency spike, adding retries was **worse than having no defence at all** — 267.8 minutes of budget against 230.1 — and the retried system was the only one of five that **never recovered after the fault was removed**.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/), [SLIs, SLOs & Error Budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/), [Failure Domains, Blast Radius & Shuffle Sharding](../../11-scalability-and-reliability/09-failure-domains-and-shuffle-sharding/)
**Time:** ~80 minutes

## The Problem

**09:14.** The architecture review closes with the resilience slide, and it is a good slide. Every outbound call has a timeout. Every timeout has a retry with exponential backoff. Every retry sits behind a circuit breaker with a documented threshold. Somebody wrote all of it, somebody else reviewed all of it, and all of it is in the repository under `resilience/`.

**11:02.** `inventory` starts answering in 200 ms instead of 40. Not failing. Not returning 500s. Not refusing connections. Just slower — a new index build, a noisy neighbour, a GC pause that got longer, it does not matter which. Every response is a correct response.

**11:02:00.4.** The first user request crosses 400 ms.

**11:02:03.** The dependency's own error-rate dashboard is still flat, because there are no errors. The circuit breaker on that dependency is closed and will stay closed for the entire incident, because a circuit breaker counts failures and there are none to count. The one defence in the repository designed for exactly this dependency is, at this moment, working perfectly and doing nothing.

**11:02:15.** `orders` has 16 worker threads. Each one is holding a connection-pool slot, waiting on `inventory`. The pool that comfortably held 2.8 concurrent calls at 40 ms is now being asked to hold 14 at 200 ms, and it has 6 slots. The queue behind it is 675 requests deep. Median user latency is **2,006 ms**. The 99th percentile is **3,395 ms**. Nothing has crashed. Every process is running. Every health check is green, because every health check asks "are you alive" and the answer is yes.

**11:02:35.** Someone finds it and rolls back the index build. `inventory` is fully healthy again, immediately, from this second onward.

**11:02:56.** Twenty-one seconds after the trigger was removed, the system finally comes back. The outage outlived its cause by longer than its cause lasted.

Now run the controlled version of that. On the same model system, the same experiment window, the same dependency: **kill the process outright** and the cost is **zero failed requests**. Users do not notice, because a hard failure produces an error, an error hits an `except` block someone wrote, and the fallback returns an order without a stock badge. **Make it 5× slower** and the cost is **2,744 failed requests and 130.7 minutes of error budget.**

Same dependency. Same duration. The difference is not the severity of the fault. The difference is that one of them had a code path and the other did not.

> **A failure mode you have never executed is not a feature. It is a hypothesis, and the ones written down in `resilience/` have never once been tested.**

## The Concept

Everything below is measured by [`code/chaos.py`](code/chaos.py): a discrete-event simulation of four services — `api → orders → {payments, inventory}` — with connection pools, timeouts, retries, retry budgets and circuit breakers, driven by open-loop arrivals at 70 requests per second. No number here is quoted from anywhere. Every one of them is printed by that file, which runs in about ten seconds and is byte-identical on two runs.

### Chaos engineering is the scientific method, not "break things"

The name is unfortunate and it has cost the discipline a decade of credibility with the people who have to approve it. Nothing about it is chaotic. The technique is stated precisely in Basiri, Behnam, de Rooij, Hochstein, Kosewski, Reynolds & Rosenthal, *Chaos Engineering*, IEEE Software 33(3), 2016, and it is five steps that will be familiar to anyone who has run any experiment at all:

1. **Define a steady state** as a measurable output of the system — not its internals.
2. **Hypothesise** that this steady state continues in both the control group and the experimental group.
3. **Introduce variables that reflect real-world events** — a server dies, a dependency gets slow, a disk fills.
4. **Try to disprove the hypothesis** by looking for a difference between control and experimental group.
5. **Minimise the blast radius**, and automate the experiment so it runs continuously.

The load-bearing word is *disprove*. A demonstration can only confirm what you already believe; an experiment can refute it. If you inject a fault and watch what happens without having written down what you expected, you have not run an experiment — you have run an outage with an audience.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 428" width="100%" style="max-width:840px" role="img" aria-label="The five steps of the chaos engineering method drawn as a left-to-right pipeline: define a steady state, hypothesise it holds, vary a real-world event, try to disprove it, then bound and automate. Beneath it, the measured steady state of this lesson's four-service system: 2070 requests, 100.0000 percent good, p50 89 milliseconds, p99 150 milliseconds, hypothesis holds. Beneath that, the four prerequisites without which the exercise is simply an outage: an SLO to hypothesise on, observability to see the effect, a rollback that works, and a blast radius you can bound.">
  <defs>
    <marker id="p12-14-arrow-a" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Chaos engineering is the scientific method with a rollback plan</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">Basiri et al., Chaos Engineering, IEEE Software 33(3), 2016</text>

    <g stroke-width="1.8">
      <rect x="24" y="64" width="152" height="80" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="194" y="64" width="152" height="80" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="364" y="64" width="152" height="80" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="534" y="64" width="152" height="80" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="704" y="64" width="152" height="80" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.8">
      <path d="M176 104 L 190 104" marker-end="url(#p12-14-arrow-a)"/>
      <path d="M346 104 L 360 104" marker-end="url(#p12-14-arrow-a)"/>
      <path d="M516 104 L 530 104" marker-end="url(#p12-14-arrow-a)"/>
      <path d="M686 104 L 700 104" marker-end="url(#p12-14-arrow-a)"/>
    </g>

    <g text-anchor="middle" font-size="10.5" font-weight="700">
      <text x="100" y="86" fill="#0fa07f">1 · STEADY STATE</text>
      <text x="270" y="86" fill="#3553ff">2 · HYPOTHESISE</text>
      <text x="440" y="86" fill="#e0930f">3 · VARY AN EVENT</text>
      <text x="610" y="86" fill="#3553ff">4 · TRY TO REFUTE</text>
      <text x="780" y="86" fill="#7c5cff">5 · BOUND, AUTOMATE</text>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">
      <text x="100" y="104">an OUTPUT of the</text><text x="100" y="117">system, not an</text><text x="100" y="131">internal metric</text>
      <text x="270" y="104">write the number</text><text x="270" y="117">down BEFORE you</text><text x="270" y="131">touch anything</text>
      <text x="440" y="104">real-world: slow,</text><text x="440" y="117">dead, full disk,</text><text x="440" y="131">partition, skew</text>
      <text x="610" y="104">a demo confirms;</text><text x="610" y="117">an experiment can</text><text x="610" y="131">come back wrong</text>
      <text x="780" y="104">a percentage dial,</text><text x="780" y="117">an SLO-tied abort,</text><text x="780" y="131">then a schedule</text>
    </g>

    <rect x="24" y="162" width="832" height="60" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="40" y="182" font-size="10" font-weight="700" fill="#0fa07f">STEP 1 AND 2, MEASURED ON THIS LESSON'S SYSTEM:</text>
    <text x="40" y="199" font-size="9.5" fill="currentColor" opacity="0.95">&#8220;over any 30-second window, at least 99.5% of user requests answer without an error in under 400 ms&#8221;</text>
    <text x="40" y="214" font-size="9.5" fill="currentColor" opacity="0.95">2,070 requests &#183; 100.0000% good &#183; p50 89 ms &#183; p99 150 ms  &#8594;  the hypothesis HOLDS, so there is an experiment to run</text>

    <text x="440" y="252" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">Without all four of these, this is not an experiment. It is an outage you scheduled.</text>

    <g stroke-width="1.6">
      <rect x="24" y="266" width="200" height="76" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
      <rect x="234" y="266" width="200" height="76" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
      <rect x="446" y="266" width="200" height="76" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
      <rect x="656" y="266" width="200" height="76" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">
      <text x="124" y="286">AN SLO</text><text x="334" y="286">OBSERVABILITY</text><text x="546" y="286">A ROLLBACK</text><text x="756" y="286">A BOUNDED RADIUS</text>
    </g>
    <g text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">
      <text x="124" y="304">no metric that says</text><text x="124" y="317">&#8220;fine&#8221; means no</text><text x="124" y="330">hypothesis to hold</text>
      <text x="334" y="304">measured here: the</text><text x="334" y="317">monitor lag alone</text><text x="334" y="330">is 3.0 s of blindness</text>
      <text x="546" y="304">one that has been</text><text x="546" y="317">used this quarter,</text><text x="546" y="330">not one on a wiki</text>
      <text x="756" y="304">a percentage you</text><text x="756" y="317">can turn down and</text><text x="756" y="330">an automatic abort</text>
    </g>

    <text x="440" y="368" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The hypothesis is the deliverable. The fault is just how you test it.</text>
    <text x="440" y="390" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Step 4 is the one teams skip: they inject, they watch, and because nothing was written down first,</text>
    <text x="440" y="404" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">whatever happened gets recorded as what they expected. That is a demonstration, and it can only agree with you.</text>
    <text x="440" y="422" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">Steady state measured by code/chaos.py section 1 &#183; 70 req/s open loop &#183; seed 20260718</text>
  </g>
</svg>
```

### The steady-state hypothesis is the hard part

Everyone wants to skip to step 3, because step 3 is the fun one. Step 1 is where most chaos programmes actually die, and the reason is unglamorous: **you cannot state a hypothesis about a system that has no metric saying it is fine.**

A **service level indicator (SLI)** is a measurement of one aspect of the service from the user's side; a **service level objective (SLO)** is a target for that measurement. [SLIs, SLOs & Error Budgets](../../09-logging-monitoring-and-observability/09-slis-slos-and-error-budgets/) builds both properly. The one used throughout this lesson is deliberately boring:

```text
    a user request is GOOD if it returns without an error in under 400 ms
    the SLO is that >= 99.5% of user requests are good
```

Note the threshold. A latency SLI needs one; an *average* cannot be the steady state, because an average is exactly the statistic that a saturated tail hides in. Measured here: during the grey failure the median user request took **2,006 ms**, which is not a subtle signal — but the p50 of the *dependency* being injected stayed inside its own timeout the whole time, which is why nothing at the dependency noticed.

The **error budget** is the other half, and it is what makes an experiment's price legible. At 70 requests per second, a 99.5% objective permits **0.35 bad requests per second**. So a count of failures converts directly into wall time: 2,744 bad requests is **130.7 minutes** of the month's budget spent by a fault that lasted twenty seconds. That conversion is the sentence that gets a chaos programme approved or cancelled, and it is arithmetic, not advocacy.

One measured caution about step 1 that nobody puts on the slide. The monitor in this simulation scores a one-second window of traffic only after that window has closed and its requests have had time to finish — **a 3.0-second lag, by construction**. A request that has not answered yet has not yet failed, so a monitor reading the current second always reads it as healthy. Every time-to-detect number in this lesson has that 3.0 seconds underneath it, and so does yours.

### Grey failure: down is easy, slow is what kills you

Here is the experiment. One dependency, one 20-second window, two faults. **Kill** it — nothing listening, connections refused instantly. Or make it **5× slower** — every response still correct, just 200 ms instead of 40. Then run the identical pair against the other dependency, one the caller *cannot* do without, so the comparison is not resting on a single lucky pair.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 568" width="100%" style="max-width:840px" role="img" aria-label="A comparison of two faults injected into the same dependency for the same twenty seconds. The hard kill produced zero failed requests, zero minutes of error budget, a median user latency of 47 milliseconds which is faster than the 89 millisecond baseline because the call is skipped, a peak queue of 4 on the orders worker pool, 10 circuit breaker trips, and recovery in 1.0 seconds. The five times slowdown produced 2744 failed requests, 130.7 minutes of error budget, a median user latency of 2006 milliseconds and a 99th percentile of 3395, a peak queue of 675 on the orders worker pool, zero circuit breaker trips, and recovery 21 seconds after the fault was already removed. A second table shows the same pair of faults against the required payments dependency, where the costs are nearly identical at 66.8 and 64.1 minutes, because that dependency has no fallback.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same dependency. Same 20 seconds. One of them had a code path.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">inventory is OPTIONAL to an order &#8212; a fallback returns the order without a stock badge</text>

    <rect x="24" y="62" width="404" height="286" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <rect x="452" y="62" width="404" height="286" rx="10" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <text x="226" y="88" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">HARD KILL &#8212; the process is gone</text>
    <text x="654" y="88" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">5x SLOWER &#8212; every answer still correct</text>

    <g fill="currentColor" font-size="9" opacity="0.62" font-weight="700">
      <text x="44" y="116">FAILED USER REQUESTS</text><text x="472" y="116">FAILED USER REQUESTS</text>
      <text x="44" y="156">ERROR BUDGET SPENT</text><text x="472" y="156">ERROR BUDGET SPENT</text>
      <text x="44" y="196">USER LATENCY p50 / p99</text><text x="472" y="196">USER LATENCY p50 / p99</text>
      <text x="44" y="236">PEAK QUEUE, orders workers</text><text x="472" y="236">PEAK QUEUE, orders workers</text>
      <text x="44" y="276">CIRCUIT BREAKER TRIPS</text><text x="472" y="276">CIRCUIT BREAKER TRIPS</text>
      <text x="44" y="316">RECOVERS AFTER THE FAULT</text><text x="472" y="316">RECOVERS AFTER THE FAULT</text>
    </g>
    <g font-size="15" font-weight="700" text-anchor="end">
      <text x="408" y="116" fill="#0fa07f">0</text><text x="836" y="116" fill="#d64545">2,744</text>
      <text x="408" y="156" fill="#0fa07f">0.0 min</text><text x="836" y="156" fill="#d64545">130.7 min</text>
      <text x="408" y="196" fill="#0fa07f">47 / 99 ms</text><text x="836" y="196" fill="#d64545">2,006 / 3,395 ms</text>
      <text x="408" y="236" fill="#0fa07f">4</text><text x="836" y="236" fill="#d64545">675</text>
      <text x="408" y="276" fill="#0fa07f">10</text><text x="836" y="276" fill="#d64545">0</text>
      <text x="408" y="316" fill="#0fa07f">1.0 s</text><text x="836" y="316" fill="#d64545">21.0 s</text>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.8">
      <text x="44" y="130">the fallback ran, so nobody saw one</text><text x="472" y="130">no error existed to trigger a fallback</text>
      <text x="44" y="170">nothing was spent at all</text><text x="472" y="170">from a fault that lasted 20 s</text>
      <text x="44" y="210">FASTER than the 89 ms baseline &#8212; the call is skipped</text><text x="472" y="210">the SLI threshold is 400 ms</text>
      <text x="44" y="250">out of 16 workers</text><text x="472" y="250">out of 16 workers, two hops from the fault</text>
      <text x="44" y="290">it saw errors, so it opened, so it fell back</text><text x="472" y="290">it counts errors, and there were none</text>
      <text x="44" y="330">it never really left the steady state</text><text x="472" y="330">the outage outlived its cause</text>
    </g>

    <text x="440" y="376" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">and the control: the SAME pair of faults against payments, which has NO fallback</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="44" y="400">FAULT ON payments (REQUIRED)</text><text x="420" y="400" text-anchor="end">BAD REQUESTS</text><text x="580" y="400" text-anchor="end">BUDGET SPENT</text><text x="720" y="400" text-anchor="end">BREAKER TRIPS</text><text x="856" y="400" text-anchor="end">RECOVERS AFTER</text>
    </g>
    <path d="M24 406 L 856 406" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.42"/>
    <g fill="currentColor" font-size="10">
      <text x="44" y="426">hard kill</text><text x="420" y="426" text-anchor="end" font-weight="700">1,402</text><text x="580" y="426" text-anchor="end" font-weight="700">66.8 min</text><text x="720" y="426" text-anchor="end" font-weight="700" fill="#0fa07f">10</text><text x="856" y="426" text-anchor="end" font-weight="700">2.0 s</text>
      <text x="44" y="448">5x slower</text><text x="420" y="448" text-anchor="end" font-weight="700">1,346</text><text x="580" y="448" text-anchor="end" font-weight="700">64.1 min</text><text x="720" y="448" text-anchor="end" font-weight="700" fill="#e0930f">8</text><text x="856" y="448" text-anchor="end" font-weight="700">2.0 s</text>
    </g>

    <rect x="24" y="466" width="832" height="64" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="40" y="486" font-size="9.5" font-weight="700" fill="#e0930f">Read the control table first.</text>
    <text x="222" y="486" font-size="9.5" fill="currentColor" opacity="0.92">On a REQUIRED dependency the two faults cost the same: 66.8 vs 64.1 min.</text>
    <text x="40" y="502" font-size="9.5" fill="currentColor" opacity="0.92">The enormous gap on the optional dependency is not created by the fault. It is created by the existence of an error path &#8212;</text>
    <text x="40" y="518" font-size="9.5" fill="currentColor" opacity="0.92">and by the timeout that turns a slow call into an error the breaker can count: 8 trips on payments, 0 on inventory.</text>

    <text x="440" y="554" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A breaker counts errors. &#8220;Slow&#8221; is not an error until a timeout makes it one.</text>
  </g>
</svg>
```

Read the breaker row twice, because it is the whole lesson in one number. **Ten trips on the kill. Zero on the slowdown.** The circuit breaker is the defence that exists specifically to protect a caller from a sick dependency, it is correctly implemented, it is correctly configured, and against the fault that actually destroyed the service it did not fire once. Not because it is broken — because it counts *errors*, and every one of those 5×-slow responses was a `200 OK` with correct data in it.

Read the p50 row too. During the hard kill the median user request was **47 ms** — *faster than the 89 ms steady state*, because the failing call is skipped entirely. A dependency that is completely dead can make you faster. A dependency that is slightly slow can take you down. That inversion is why "is it up?" is the wrong question and has been for years.

Now the honest half, which is the payments control. On a dependency with **no fallback**, kill and slowdown cost almost the same: **66.8 versus 64.1 minutes**. The gigantic gap on `inventory` is not a property of grey failure in the abstract. It is a property of *whether an error path exists*, and a hard failure is cheap precisely because it is the failure mode somebody already wrote code for. Which is the argument for the whole discipline: the reason `kill` is survivable is that it has been thought about, and the only way to get `slow` into that same category is to execute it.

### Little's law is why your pool has a latency budget, and it is smaller than you think

The mechanism is not exotic and it is not about circuit breakers at all. It is a 1961 result. Little's law (Little, *A Proof for the Queuing Formula L = λW*, Operations Research 9(3), 1961) says that the average number of items concurrently in a stable system equals the arrival rate times the average time each one stays: **L = λW**. For a connection pool, `L` is how many slots you need.

At the steady state, `orders` calls `inventory` at 70 per second with a 40 ms hold, so it needs **L = 2.80** slots. The pool has **6**. Every pool in this system is under a third full at rest, and the program prints the whole table.

```text
    pool                    size   mean util   peak queue   L = lambda x W   slowdown it survives
    edge orders->payments    10      14.2%            1        2.45                4.1x
    edge orders->inventory    6      28.5%            3        2.80                2.1x
    edge api->orders         48       7.3%            0        6.30                7.6x
    svc payments workers      4      31.5%            6        2.45                1.6x
    svc inventory workers     8      21.4%            0        2.80                2.9x
    svc orders workers       16      21.8%            1        6.30                2.5x
```

The last column is the one nobody computes, and it re-reads the entire table. **A pool sized at 6 for a required concurrency of 2.80 is not "70% spare capacity". It is a latency budget of 2.1×**, because `λ` is fixed by your users and `W` is fixed by your dependency, so the only thing headroom buys you is tolerance of a *slower* `W`. Inject 5× and 2.1× of headroom is not enough — by a factor of two and a bit, which is precisely what 675 queued requests looks like.

And note where the queue formed. The `orders→inventory` pool peaked at 10 waiters; `orders`' own worker pool peaked at **675**. The saturation propagates *upward*, away from the fault, because a worker that is blocked waiting for a pool slot is a worker that is not free for anything else. This is the same argument as [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/), arriving from the other direction: the queue always forms at the resource you did not think to bound.

One modelling detail that matters, because it is how real clients behave: **the request timeout starts after a connection has been obtained.** Time spent waiting for a pool slot is governed by a separate acquire timeout that is usually unset — `httpx` calls it `pool`, and most codebases pass a single number that only ever reaches `read`. So the 250 ms timeout on the inventory edge bounded the part of the wait that was already fine, and did nothing about the part that had become unbounded.

### What you can actually inject

The fault taxonomy is short and worth memorising, because the interesting entries are not the ones people reach for first.

| fault | what it models | why it is on the list |
|---|---|---|
| **latency** | a slow dependency, a GC pause, a cold cache | the highest-value injection there is — measured above at 130.7 min versus 0.0 |
| **error** | a crash, a bad deploy, an exhausted quota | the cheapest to survive, because it produces an exception someone handled |
| **resource exhaustion** | pool, thread, file descriptor, memory | the failure that is *caused* by latency, one hop away |
| **dependency loss** | a whole service, a whole zone | [Failure Domains, Blast Radius & Shuffle Sharding](../../11-scalability-and-reliability/09-failure-domains-and-shuffle-sharding/) |
| **clock skew** | NTP drift, a leap second, a VM pause | breaks tokens, certificates, leases and ordering |
| **packet loss / partition** | a flaky link, a security-group change | both sides believe they are correct; nobody is down |
| **disk full, DNS failure** | the two everyone forgets | they take down the *observability* first, which is worse |

Two notes on ordering. Latency is first because it is the one your defences are least prepared for and the one your staging environment has never produced. And the last row is a genuine trap: a disk-full or DNS failure frequently disables the logging pipeline before it disables the service, so the instrument you were going to use to observe the experiment is inside the blast radius. Check that first.

### Retry storms and metastable failure

Now the experiment that should change a config file. `payments` runs **6× slower for 30 seconds and is then fully restored**. Real demand never changes — a flat 70 requests per second, before, during and after. The only question is what the system is doing at t = 90 s, forty-five seconds after the cause was removed.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="Two stacked timelines over 95 seconds of simulation, showing wire attempts to the payments service and good user requests per second. The trigger, a six times slowdown, runs from 15 to 45 seconds and is shaded. In the top panel, the naive three-attempt retry configuration: attempts fall to about 33 per second during the fault and goodput falls to zero, then after the trigger is removed attempts rise to 110 per second and stay there while goodput remains at exactly zero for the rest of the run, at 50, 60, 75 and 90 seconds. In the bottom panel, the budgeted configuration with jitter and a circuit breaker: goodput dips but attempts fall to as low as zero as the breaker opens, and within 4 seconds of the trigger being removed goodput is back to 65 per second and stays near 75. The naive configuration burned 267.9 minutes of error budget and never recovered; the budgeted one burned 102.4 minutes and recovered in 4 seconds.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The trigger leaves at t = 45 s. Only one of these systems notices.</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">payments 6x slower for 30 s, then FULLY restored &#183; user demand is a flat 70 req/s throughout</text>

    <rect x="134" y="66" width="265" height="144" fill="#e0930f" fill-opacity="0.10"/>
    <rect x="134" y="246" width="265" height="144" fill="#e0930f" fill-opacity="0.10"/>
    <text x="266" y="80" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">TRIGGER PRESENT</text>
    <text x="266" y="260" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">TRIGGER PRESENT</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M90 210 L 850 210"/><path d="M90 210 L 90 66"/>
      <path d="M90 390 L 850 390"/><path d="M90 390 L 90 246"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.18">
      <path d="M90 116.4 L 850 116.4"/><path d="M90 163.2 L 850 163.2"/>
      <path d="M90 296.4 L 850 296.4"/><path d="M90 343.2 L 850 343.2"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="end" opacity="0.7">
      <text x="84" y="213">0</text><text x="84" y="166">50</text><text x="84" y="119">100</text>
      <text x="84" y="393">0</text><text x="84" y="346">50</text><text x="84" y="299">100</text>
    </g>
    <text x="30" y="140" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">req/s</text>
    <text x="30" y="320" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.7">req/s</text>

    <text x="100" y="60" font-size="11" font-weight="700" fill="#d64545">NAIVE RETRY x3 &#8212; no jitter, no budget, no breaker</text>
    <text x="100" y="240" font-size="11" font-weight="700" fill="#0fa07f">RETRY BUDGET + FULL JITTER + CIRCUIT BREAKER</text>

    <path d="M107.6 128.8 L 178.2 179.2 L 266.5 176.4 L 354.7 181.1 L 390.0 179.2 L 407.6 181.1 L 442.9 173.6 L 531.2 107.4 L 663.5 107.4 L 795.8 110.2" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M107.6 128.8 L 178.2 210 L 266.5 210 L 354.7 210 L 390.0 210 L 407.6 210 L 442.9 210 L 531.2 210 L 663.5 210 L 795.8 210" fill="none" stroke="#d64545" stroke-width="3" stroke-linejoin="round"/>
    <g fill="#d64545"><circle cx="442.9" cy="210" r="3.4"/><circle cx="531.2" cy="210" r="3.4"/><circle cx="663.5" cy="210" r="3.4"/><circle cx="795.8" cy="210" r="3.4"/></g>

    <path d="M107.6 308.8 L 178.2 367.6 L 266.5 374.1 L 354.7 377.9 L 390.0 375.1 L 407.6 390 L 442.9 329.4 L 531.2 332.2 L 663.5 320.9 L 795.8 319.1" fill="none" stroke="#e0930f" stroke-width="2.4" stroke-linejoin="round"/>
    <path d="M107.6 308.8 L 178.2 387.2 L 266.5 390 L 354.7 390 L 390.0 382.5 L 407.6 390 L 442.9 329.4 L 531.2 331.2 L 663.5 320.9 L 795.8 320.0" fill="none" stroke="#0fa07f" stroke-width="3" stroke-linejoin="round"/>
    <g fill="#0fa07f"><circle cx="442.9" cy="329.4" r="3.4"/><circle cx="531.2" cy="331.2" r="3.4"/><circle cx="663.5" cy="320.9" r="3.4"/><circle cx="795.8" cy="320.0" r="3.4"/></g>

    <g fill="none" stroke="#d64545" stroke-width="1.4" stroke-dasharray="5 4">
      <path d="M398.8 66 L 398.8 210"/><path d="M398.8 246 L 398.8 390"/>
    </g>

    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.75">
      <text x="107.6" y="224">12</text><text x="178.2" y="224">20</text><text x="266.5" y="224">30</text><text x="354.7" y="224">40</text><text x="442.9" y="224">50</text><text x="531.2" y="224">60</text><text x="663.5" y="224">75</text><text x="795.8" y="224">90</text>
      <text x="107.6" y="404">12</text><text x="178.2" y="404">20</text><text x="266.5" y="404">30</text><text x="354.7" y="404">40</text><text x="442.9" y="404">50</text><text x="531.2" y="404">60</text><text x="663.5" y="404">75</text><text x="795.8" y="404">90</text>
    </g>

    <text x="560" y="100" font-size="9.5" font-weight="700" fill="#e0930f">attempts to payments: 110/s and holding</text>
    <text x="560" y="200" font-size="9.5" font-weight="700" fill="#d64545">good user requests: 0/s, forever</text>
    <text x="560" y="316" font-size="9.5" font-weight="700" fill="#0fa07f">back to 74/s within 4 s of the trigger leaving</text>

    <g font-size="9" font-weight="700">
      <rect x="90" y="416" width="11" height="11" rx="2" fill="#e0930f"/><text x="108" y="426" fill="#e0930f">wire attempts to payments</text>
      <rect x="300" y="416" width="11" height="11" rx="2" fill="#d64545"/><text x="318" y="426" fill="#d64545">good user requests (naive)</text>
      <rect x="520" y="416" width="11" height="11" rx="2" fill="#0fa07f"/><text x="538" y="426" fill="#0fa07f">good user requests (budgeted)</text>
    </g>

    <rect x="24" y="436" width="832" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="40" y="454" font-size="9.5" font-weight="700" fill="#d64545">naive: 267.9 min of budget, recovery NEVER.</text>
    <text x="330" y="454" font-size="9.5" font-weight="700" fill="#0fa07f">budgeted: 102.4 min, recovery 4.0 s.</text>
    <text x="600" y="454" font-size="9.5" fill="currentColor" opacity="0.9">Same fault. Same code. One config line.</text>
    <text x="40" y="470" font-size="9" fill="currentColor" opacity="0.85">Bronson, Aghayev, Charapko &amp; Zhu, Metastable Failures in Distributed Systems, HotOS 2021 &#8212; the trigger creates the state, the retries keep it.</text>
  </g>
</svg>
```

This is a **metastable failure**, named and analysed in Bronson, Aghayev, Charapko & Zhu, *Metastable Failures in Distributed Systems*, HotOS 2021. The definition has two halves and both are necessary: a **trigger** pushes the system out of its stable state, and a **sustaining effect** — a feedback loop built entirely out of correct, well-intentioned components — holds it there after the trigger is gone. The system has two stable states, and it is now in the wrong one, and nothing about removing the cause returns it to the right one.

Read the naive panel left to right. During the fault, wire attempts *fall* to about 33 per second, which looks like the system protecting itself and is nothing of the sort — it is the connection pool being full, so admission is throttled at 10 slots divided by a 300 ms timeout. Goodput is zero. Then at t = 45 s the dependency is restored, attempts climb to **110 per second and stay there**, and goodput remains at **exactly zero at t = 50, 60, 75 and 90 seconds.**

The loop is: every request times out → every timed-out request is retried up to three times → the offered load on `payments` is now well above what it can serve → so every request times out. Removing the trigger does not touch a single term in that sentence. And there is a second, quieter sustaining effect in the same run: **a timed-out request does not stop the downstream work.** The caller abandons it at 300 ms, but `payments` keeps executing it to completion, so a saturated service spends its entire capacity computing answers that nobody is waiting for any more. Goodput can be zero while utilisation is 100%.

The budgeted configuration changes one thing that matters: a **retry budget** — a token bucket where each primary request mints 0.10 retry tokens, so amplification is capped at about 1.1× no matter how bad things get, instead of 3×. Measured peak amplification after the trigger: **1.24× versus 1.64×**. That is the difference between offered load landing below the service's capacity and above it, and therefore the difference between a system with one stable state and a system with two. Full jitter spreads the retries so they do not arrive as a synchronised wave; the breaker stops sending entirely once the failure rate is obvious. [Retries, Backoff, Dead-Letter Queues & Poison Messages](../../06-messaging-and-pub-sub/08-retries-backoff-and-dead-letter-queues/) builds those primitives; this lesson is where you find out whether yours are configured.

### Ablation: what each defence is actually worth against this fault

Five configurations, each adding exactly one thing to the one above it, against the identical fault, averaged over three seeds because a single run of a saturated system is one draw and not a result.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="A horizontal bar chart of error budget burned by five defence configurations against the same fault, averaged over three seeds. No defence at all burned 230.1 minutes and recovered in 41 seconds. Timeout only burned an identical 230.1 minutes and recovered in 40.7 seconds. Adding a naive three-attempt retry burned 267.8 minutes, 37.7 minutes worse than having no defence at all, and never recovered. Adding full jitter and a retry budget burned 240.7 minutes, still 10.7 minutes worse than no defence, and recovered in 43.7 seconds. Adding a circuit breaker and a bounded queue burned 101.8 minutes, 128.3 minutes better, and recovered in 2.7 seconds.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Two of the five defences made the outage worse than having none</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">identical fault: payments 6x slower for 30 s, then fully restored &#183; mean of 3 seeds</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="24" y="72">CONFIGURATION</text><text x="290" y="72" text-anchor="end">GOOD AFTER</text><text x="300" y="72">ERROR BUDGET BURNED (minutes)</text><text x="790" y="72" text-anchor="end">VS NONE</text><text x="856" y="72" text-anchor="end">RECOVERY</text>
    </g>
    <path d="M20 78 L 860 78" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45"/>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.16">
      <path d="M363.5 84 L 363.5 300"/><path d="M427 84 L 427 300"/><path d="M490.5 84 L 490.5 300"/><path d="M554 84 L 554 300"/><path d="M617.5 84 L 617.5 300"/>
    </g>
    <path d="M592.2 84 L 592.2 306" fill="none" stroke="#7f7f7f" stroke-width="1.6" stroke-dasharray="5 4"/>

    <g stroke-width="1.5">
      <rect x="300" y="88" width="292.2" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.20" stroke="#7f7f7f"/>
      <rect x="300" y="132" width="292.2" height="30" rx="4" fill="#7f7f7f" fill-opacity="0.20" stroke="#7f7f7f"/>
      <rect x="300" y="176" width="340.1" height="30" rx="4" fill="#d64545" fill-opacity="0.24" stroke="#d64545"/>
      <rect x="300" y="220" width="305.7" height="30" rx="4" fill="#e0930f" fill-opacity="0.24" stroke="#e0930f"/>
      <rect x="300" y="264" width="129.3" height="30" rx="4" fill="#0fa07f" fill-opacity="0.24" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor" font-size="10.5">
      <text x="24" y="108">no defence at all</text><text x="24" y="152">timeout only</text>
      <text x="24" y="196" fill="#d64545" font-weight="700">+ retry (naive x3)</text>
      <text x="24" y="240" fill="#e0930f" font-weight="700">+ full jitter + budget</text>
      <text x="24" y="284" fill="#0fa07f" font-weight="700">+ breaker + bounded queue</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="end" opacity="0.85">
      <text x="290" y="108">22.4%</text><text x="290" y="152">22.5%</text><text x="290" y="196" fill="#d64545" font-weight="700">0.0%</text><text x="290" y="240">16.1%</text><text x="290" y="284" fill="#0fa07f" font-weight="700">97.5%</text>
    </g>
    <g font-size="11" font-weight="700">
      <text x="600" y="108" fill="#7f7f7f">230.1</text><text x="600" y="152" fill="#7f7f7f">230.1</text>
      <text x="648" y="196" fill="#d64545">267.8</text><text x="613" y="240" fill="#e0930f">240.7</text><text x="437" y="284" fill="#0fa07f">101.8</text>
    </g>
    <g font-size="9" font-weight="700" text-anchor="end">
      <text x="790" y="196" fill="#d64545">+37.7</text><text x="790" y="240" fill="#e0930f">+10.7</text><text x="790" y="284" fill="#0fa07f">&#8722;128.3</text>
      <text x="790" y="108" fill="#7f7f7f" opacity="0.7">baseline</text><text x="790" y="152" fill="#7f7f7f" opacity="0.7">0.0</text>
    </g>
    <g font-size="9.5" text-anchor="end" fill="currentColor">
      <text x="856" y="108">41.0 s</text><text x="856" y="152">40.7 s</text>
      <text x="856" y="196" fill="#d64545" font-weight="700">NEVER</text><text x="856" y="240">43.7 s</text><text x="856" y="284" fill="#0fa07f" font-weight="700">2.7 s</text>
    </g>

    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.7">
      <text x="300" y="318">0</text><text x="427" y="318">100</text><text x="554" y="318">200</text>
    </g>
    <text x="592.2" y="332" text-anchor="middle" font-size="8" font-weight="700" fill="#7f7f7f">no-defence baseline, 230.1 min</text>

    <rect x="20" y="346" width="840" height="60" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="366" font-size="9.5" font-weight="700" fill="#d64545">A timeout changes HOW you fail, not HOW MUCH: rows 1 and 2 are identical to a tenth of a minute.</text>
    <text x="36" y="382" font-size="9.5" fill="currentColor" opacity="0.92">The winning row declined 2,141 calls at the breaker and the retry budget, and shed 0 at the bounded queue &#8212; the queue</text>
    <text x="36" y="396" font-size="9.5" fill="currentColor" opacity="0.92">limit never fired, because the breaker got there first. That is a defence you are paying for and do not yet own.</text>

    <text x="440" y="434" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The configuration that deliberately did the least work served the most users.</text>
  </g>
</svg>
```

Three results in that chart, in ascending order of how much they should annoy you.

**A timeout on its own is worth nothing here — 230.1 minutes with it, 230.1 without.** Identical to a tenth of a minute. That is not an argument against timeouts, which are load-bearing for other reasons; it is a precise statement about what a timeout does. It converts "slow" into "failed", which changes the *shape* of the failure and gives the breaker something to count. It does not change how many users had a bad time, because a user whose request takes 8 seconds and a user whose request returns a 503 are both users who had a bad time.

**Adding a naive retry made everything worse: 267.8 minutes against 230.1, and it is the only configuration of five that never recovered.** This is the result the brief for this lesson predicted might appear, and it did. A retry is a bet that the failure is independent and transient. Under a *saturation* failure the bet is not merely wrong, it is inverted: the failure is caused by load, and your response to it is more load. Every retry you add is a request the system had already decided it could not serve, offered again.

**And jitter plus a budget was still worse than nothing — 240.7 minutes, +10.7.** This is the uncomfortable one, and it is worth being precise rather than defensive about it. Jitter and a budget did their job: peak amplification dropped and the system recovered instead of hanging. But 1.1× amplification of a load that already exceeds capacity is still above capacity, so it bought a *recovery* (43.7 s versus never) and not a *reduction in damage*. The row that actually reduced damage is the one that stops sending requests altogether. Every fix in this table that worked, worked by doing less.

### Blast radius is a dial, and there is a threshold hiding in it

The experiment is only legitimate if it is stoppable. So run the identical grey failure at **1%, 5%, 25% and 100%** of user requests, with a stable cohort assignment so the injected slice is comparable, and an abort that halts the fault after three consecutive SLO-breaching seconds.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 482" width="100%" style="max-width:840px" role="img" aria-label="A chart comparing signal against damage at four blast radii for the same grey failure. At 1 percent injection the Mann-Whitney z statistic separating the injected cohort from the control is 6.2, at a cost of 2 failed requests and 0.1 minutes of error budget, and the experiment never aborted. At 5 percent the z is 10.3 for 7 failed requests and 0.3 minutes. At 25 percent the z falls slightly to 9.8 because the control cohort is itself degraded, at a cost of 107 failed requests and 5.1 minutes, aborting after 5 seconds. At 100 percent the z is 22.7 at a cost of 637 failed requests and 30.3 minutes. A second panel shows the emergent effect: the peak queue on the orders worker pool was 2 at 1 percent, 4 at 5 percent, 34 at 25 percent and 180 at 100 percent, so the cascade does not appear at all below 25 percent.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A 1% experiment buys most of the signal for 0.3% of the damage</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">same 5x slowdown, injected into a stable cohort &#183; abort after 3 consecutive SLO-breaching seconds</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="24" y="76">INJECTED</text><text x="120" y="76">SIGNAL: Mann-Whitney z, injected vs control</text><text x="500" y="76">DAMAGE: failed user requests</text><text x="856" y="76" text-anchor="end">ABORTED AT</text>
    </g>
    <path d="M20 82 L 860 82" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45"/>

    <g stroke-width="1.5">
      <rect x="120" y="90" width="32.8" height="24" rx="3" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff"/>
      <rect x="120" y="132" width="54.5" height="24" rx="3" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff"/>
      <rect x="120" y="174" width="51.8" height="24" rx="3" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff"/>
      <rect x="120" y="216" width="120.0" height="24" rx="3" fill="#3553ff" fill-opacity="0.30" stroke="#3553ff"/>
      <rect x="500" y="90" width="0.4" height="24" rx="0.2" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="500" y="132" width="1.3" height="24" rx="0.6" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="500" y="174" width="20.2" height="24" rx="3" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <rect x="500" y="216" width="120.0" height="24" rx="3" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
    </g>

    <g fill="currentColor" font-size="11" font-weight="700">
      <text x="24" y="107">1%</text><text x="24" y="149">5%</text><text x="24" y="191">25%</text><text x="24" y="233">100%</text>
    </g>
    <g font-size="10.5" font-weight="700" fill="#3553ff">
      <text x="160" y="107">6.2</text><text x="182" y="149">10.3</text><text x="179" y="191">9.8</text><text x="248" y="233">22.7</text>
    </g>
    <g font-size="10.5" font-weight="700" fill="#d64545">
      <text x="510" y="107">2  &#183; 0.1 min</text><text x="511" y="149">7  &#183; 0.3 min</text><text x="528" y="191">107  &#183; 5.1 min</text><text x="628" y="233">637  &#183; 30.3 min</text>
    </g>
    <g font-size="9.5" text-anchor="end" fill="currentColor">
      <text x="856" y="107" opacity="0.7">never</text><text x="856" y="149">11.0 s</text><text x="856" y="191" font-weight="700">5.0 s</text><text x="856" y="233" font-weight="700">5.0 s</text>
    </g>

    <text x="440" y="272" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">and the EMERGENT effect, which is NOT linear: peak queue on orders' 16 workers</text>

    <g stroke-width="1.5">
      <rect x="120" y="286" width="1.3" height="22" rx="0.6" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="120" y="316" width="2.7" height="22" rx="1.3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="120" y="346" width="22.7" height="22" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
      <rect x="120" y="376" width="120.0" height="22" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff"/>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="24" y="302">1%</text><text x="24" y="332">5%</text><text x="24" y="362">25%</text><text x="24" y="392">100%</text>
    </g>
    <g font-size="10.5" font-weight="700" fill="#7c5cff">
      <text x="132" y="302">2</text><text x="133" y="332">4</text><text x="152" y="362">34</text><text x="250" y="392">180</text>
    </g>
    <g font-size="9" fill="currentColor" opacity="0.85">
      <text x="300" y="302">no cascade &#8212; the direct latency effect only</text>
      <text x="300" y="332">no cascade &#8212; and the whole service is still at 99.7% good</text>
      <text x="300" y="362">the cascade appears; the control cohort's own p50 rises 90 &#8594; 252 ms</text>
      <text x="300" y="392">full collapse; there is no control cohort left to compare against</text>
    </g>

    <rect x="20" y="408" width="840" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <text x="36" y="426" font-size="9.5" font-weight="700" fill="#3553ff">1% recovers z = 6.2 for 2 failed requests. 100% recovers z = 22.7 for 637.</text>
    <text x="500" y="426" font-size="9.5" fill="currentColor" opacity="0.92">3.7x the signal for 318x the damage.</text>
    <text x="36" y="442" font-size="9" fill="currentColor" opacity="0.88">But read the lower panel before generalising. The DIRECT effect is linear and plainly visible at 1%;</text>
    <text x="36" y="456" font-size="9" fill="currentColor" opacity="0.88">the EMERGENT one has a threshold between 5% and 25%, and no 1% experiment will ever find it.</text>
  </g>
</svg>
```

The headline is the one the discipline promises: **a 1% experiment recovered a Mann-Whitney z of 6.2 — a separation you would see by chance roughly once in three billion — for a total cost of 2 failed requests and 0.1 minutes of error budget.** The 100% experiment recovered z = 22.7 for 637 failed requests. That is **3.7× the signal for 318× the damage**, and it is the entire argument for turning the dial down.

But the lower panel is where this lesson stops agreeing with the slogan, and the honest result is more useful than the slogan. **The cascade — the thing that actually caused the incident in The Problem — does not appear at 1% or 5% at all.** Peak queue on `orders`' workers: 2, then 4, then 34, then 180. There is a threshold somewhere between 5% and 25%, and there has to be, because queueing is a function of *aggregate* load: at 5% injection the required concurrency rises from 2.80 to about 3.4 against a pool of 6, and 3.4 is fine. Saturation is not a property that scales down.

So the correct statement is narrower than "1% finds the bug", and it is worth getting right because it determines what you schedule: **a small blast radius reliably finds direct effects — this call got slower, this cohort's latency moved — and reliably misses emergent ones.** Direct effects are what continuous automated chaos is for, because they are cheap. Emergent effects need a bigger radius, which means a game day with humans watching, a low-traffic window, and an abort you have tested.

Two further details from the same table. The 25% run scored a **lower** z (9.8) than the 5% run (10.3), which looks like an error and is not: at 25% injection **the control cohort's own p50 rose from 90 ms to 252 ms**. The uninjected group was no longer uninjected, because it shares the pools. Past some radius you lose your own baseline, and the experiment stops being able to measure itself. And the abort worked exactly as intended: at 25% and 100% it halted the fault **5.0 seconds** in, which is three one-second windows plus the 3.0-second monitor lag — meaning the fastest possible automated abort on this system is bounded below by how fast you can *see*, not by how fast you can act.

### Canary analysis is a statistical test, and a threshold is a bad one

Testing in production has a legitimate, boring, everyday form that predates the word chaos: **a canary** — release to a small fraction of traffic, compare it against the baseline, promote or roll back. [Deployment Strategies: Rolling, Blue-Green & Canary](../../10-infrastructure-and-deployment/11-deployment-strategies/) covers the mechanics and [Deploy ≠ Release: Feature Flags & Progressive Delivery](../../10-infrastructure-and-deployment/12-deploy-vs-release-feature-flags/) covers the control plane. What almost nobody does is notice that the comparison step is a **hypothesis test**, and that writing it as a threshold does not avoid the statistics — it just does them badly.

The rule everybody writes is some version of *"fail the canary if its error rate is more than 50% above baseline"*. Run it against a baseline error rate of 0.4% and a canary carrying a genuine 1.0-percentage-point regression, 4,000 trials at each traffic volume:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="Two line charts comparing a naive canary threshold against a two-proportion z test across traffic volumes from 200 to 100000 requests per arm. The left chart shows the false alarm rate: the naive rule starts at 33.1 percent at 200 requests, falls to 28.0 at 1000, 9.5 at 5000, 0.5 at 20000 and 0.0 at 100000, while the z test holds between 1.9 and 5.5 percent at every volume. The right chart shows the missed-regression rate: the naive rule misses 24.3 percent at 200 requests and 5.0 at 1000, while the z test misses 68.7 percent at 200 and 20.7 at 1000, both reaching zero by 5000. A summary strip reports that 1200 requests per arm are needed for 80 percent power, that Wald's sequential test reaches a verdict in a median of 305 samples on a bad canary with a 2.9 percent false alarm rate, and that a mean-based latency threshold calibrated to 5 percent false alarms requires plus 10.2 percent at 200 requests but only plus 2.4 percent at 3200.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The naive rule's false-alarm rate is a function of your traffic, not your code</text>
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">baseline 0.4% errors &#183; the bad canary carries a 1.0-point regression &#183; 4,000 trials per point</text>

    <text x="235" y="70" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">FALSE ALARM &#8212; a good canary rejected</text>
    <text x="655" y="70" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">MISSED &#8212; a bad canary promoted</text>

    <g fill="none" stroke="currentColor" stroke-width="1.3">
      <path d="M70 240 L 410 240"/><path d="M70 240 L 70 88"/>
      <path d="M490 240 L 830 240"/><path d="M490 240 L 490 88"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.18">
      <path d="M70 197 L 410 197"/><path d="M70 154 L 410 154"/><path d="M70 111 L 410 111"/>
      <path d="M490 197 L 830 197"/><path d="M490 154 L 830 154"/><path d="M490 111 L 830 111"/>
    </g>
    <g fill="currentColor" font-size="8" text-anchor="end" opacity="0.7">
      <text x="64" y="243">0%</text><text x="64" y="200">10%</text><text x="64" y="157">20%</text><text x="64" y="114">30%</text>
      <text x="484" y="243">0%</text><text x="484" y="200">20%</text><text x="484" y="157">40%</text><text x="484" y="114">60%</text>
    </g>

    <path d="M70 98.1 L 155.5 120.0 L 241.0 199.3 L 314.6 237.9 L 400 240" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M70 231.9 L 155.5 217.7 L 241.0 221.1 L 314.6 221.1 L 400 216.4" fill="none" stroke="#3553ff" stroke-width="2.8" stroke-linejoin="round"/>
    <g fill="#d64545"><circle cx="70" cy="98.1" r="3.4"/><circle cx="155.5" cy="120.0" r="3.4"/><circle cx="241" cy="199.3" r="3.4"/></g>
    <g fill="#3553ff"><circle cx="70" cy="231.9" r="3.4"/><circle cx="155.5" cy="217.7" r="3.4"/><circle cx="400" cy="216.4" r="3.4"/></g>

    <path d="M490 188.0 L 575.5 229.3 L 661.0 240 L 734.6 240 L 820 240" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M490 92.8 L 575.5 195.6 L 661.0 240 L 734.6 240 L 820 240" fill="none" stroke="#3553ff" stroke-width="2.8" stroke-linejoin="round"/>
    <g fill="#d64545"><circle cx="490" cy="188.0" r="3.4"/><circle cx="575.5" cy="229.3" r="3.4"/></g>
    <g fill="#3553ff"><circle cx="490" cy="92.8" r="3.4"/><circle cx="575.5" cy="195.6" r="3.4"/></g>

    <g fill="currentColor" font-size="8" text-anchor="middle" opacity="0.75">
      <text x="70" y="254">200</text><text x="155.5" y="254">1k</text><text x="241" y="254">5k</text><text x="314.6" y="254">20k</text><text x="400" y="254">100k</text>
      <text x="490" y="254">200</text><text x="575.5" y="254">1k</text><text x="661" y="254">5k</text><text x="734.6" y="254">20k</text><text x="820" y="254">100k</text>
    </g>
    <text x="235" y="270" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">requests per arm (log scale)</text>
    <text x="655" y="270" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">requests per arm (log scale)</text>

    <text x="120" y="94" font-size="9.5" font-weight="700" fill="#d64545">33.1%</text>
    <text x="250" y="150" font-size="8.5" font-weight="700" fill="#3553ff">z test: 1.9% &#8211; 5.5% at every volume</text>
    <path d="M296 156 L 272 210" fill="none" stroke="#3553ff" stroke-width="1" opacity="0.45"/>
    <text x="410" y="212" font-size="9.5" font-weight="700" fill="#3553ff">5.5%</text>
    <text x="506" y="88" font-size="9.5" font-weight="700" fill="#3553ff">68.7%</text>
    <text x="506" y="182" font-size="9.5" font-weight="700" fill="#d64545">24.3%</text>

    <g font-size="9" font-weight="700">
      <rect x="70" y="284" width="11" height="11" rx="2" fill="#d64545"/><text x="88" y="294" fill="#d64545">naive rule: &#8220;canary error rate &gt; 1.5x baseline&#8221;</text>
      <rect x="490" y="284" width="11" height="11" rx="2" fill="#3553ff"/><text x="508" y="294" fill="#3553ff">one-sided two-proportion z test, alpha = 0.05</text>
    </g>

    <rect x="20" y="308" width="840" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="38" y="328">HOW MUCH TRAFFIC A VERDICT COSTS</text><text x="470" y="328">A LATENCY THRESHOLD, CALIBRATED TO 5% FALSE ALARMS</text>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="38" y="348">fixed sample, 80% power at alpha=0.05</text><text x="440" y="348" text-anchor="end" font-weight="700">1,200 / arm</text>
      <text x="38" y="366">Wald SPRT, median on a BAD canary</text><text x="440" y="366" text-anchor="end" font-weight="700" fill="#0fa07f">305</text>
      <text x="38" y="384">Wald SPRT, median on a GOOD canary</text><text x="440" y="384" text-anchor="end" font-weight="700">417  (p90 949)</text>
      <text x="38" y="402">Wald SPRT false alarm / missed</text><text x="440" y="402" text-anchor="end" font-weight="700">2.9% / 5.1%</text>
      <text x="470" y="348">at 200 requests per arm, the threshold must be</text><text x="842" y="348" text-anchor="end" font-weight="700" fill="#d64545">+10.2%</text>
      <text x="470" y="366">at 800 requests per arm</text><text x="842" y="366" text-anchor="end" font-weight="700" fill="#e0930f">+5.0%</text>
      <text x="470" y="384">at 3,200 requests per arm</text><text x="842" y="384" text-anchor="end" font-weight="700" fill="#0fa07f">+2.4%</text>
      <text x="470" y="402" font-size="9" font-weight="700" fill="#3553ff">so a fixed &#8220;+5%&#8221; rule is correct at exactly one traffic level</text>
    </g>

    <text x="440" y="446" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A threshold is a hypothesis test whose false-alarm rate you did not choose.</text>
    <text x="440" y="466" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Mann &amp; Whitney, Ann. Math. Statist. 18(1), 1947 &#183; Wald, Sequential Analysis, Wiley, 1947</text>
  </g>
</svg>
```

**Look at the left panel and nothing else for a moment.** The naive rule's false-alarm rate is **33.1% at 200 requests per arm and 0.0% at 100,000**. Same rule, same code, same deploy — the probability of a spurious rollback is a function of how much traffic you happen to have. That is why a canary policy behaves like a different policy at 3 a.m. than at noon, and why "we tuned the threshold" is a statement about last quarter's traffic. The z test holds between **1.9% and 5.5%** at every volume on the sweep, because controlling that number is the *definition* of the test.

The right panel is the honest counterweight, and I am not going to hide it: **at 200 requests per arm the z test misses 68.7% of genuine regressions where the naive rule misses only 24.3%.** The naive rule is not more sensitive; it is *less strict*, and at that volume it is firing at random — the 24.3% and the 33.1% are the same phenomenon read from two directions. The right conclusion is neither rule works at 200 requests, and the honest thing a canary system can print at that point is **"not enough traffic to decide"**, which is a verdict almost no deploy pipeline is capable of returning.

How much traffic is enough? For this 1.0-point regression: **1,200 requests per arm for 80% power at α = 0.05** — power climbs 30.3% → 45.3% → 58.6% → 73.0% → 78.3% → 85.5% across the sweep. And you can do meaningfully better than a fixed sample. Wald's sequential probability ratio test (Wald, *Sequential Analysis*, Wiley, 1947) evaluates after every observation and stops as soon as the evidence crosses a boundary: measured, a **median of 305 samples to condemn a bad canary** and 417 to clear a good one, at a 2.9% false-alarm and 5.1% miss rate. Four times less exposure than the fixed sample, for the same error rates, because it stops early when the answer is obvious.

The same argument on latency, where the distribution has a long tail, produces the cleanest version of the point. Calibrate a "canary's mean is worse by X%" threshold so that it false-alarms exactly 5% of the time, and the X you need is **+10.2% at 200 requests per arm, +5.0% at 800 and +2.4% at 3,200**. The threshold is not a property of your service. It is a property of your sample size. A number hard-coded in a pipeline is right at one traffic level and wrong at every other one — and a rank test like Mann-Whitney (Mann & Whitney, *Annals of Mathematical Statistics* 18(1), 1947) simply does not have that failure mode, because it holds α at 5.9%, 4.8% and 5.6% across the same three volumes without being told anything about the distribution.

### The four prerequisites, and what this does not replace

Two closing statements, both of which need to be said plainly because the enthusiasm for this technique routinely outruns them.

**Without all four of these, an experiment is an outage you scheduled.** An **SLO**, because without a metric that says "fine" there is no hypothesis and therefore no experiment. **Observability**, because an effect you cannot see is damage you inflicted for nothing — and note the floor measured here: a monitor that scores closed one-second windows is blind for **3.0 seconds** no matter how good it is. **A rollback that works**, meaning one that has been executed this quarter rather than documented on a wiki; the fault injection you cannot turn off is the definition of an incident. And **a bounded blast radius**, which is a percentage dial plus an automatic abort tied to the SLO — measured here, halting the fault **5.0 seconds** in at 25% and 100% injection.

**And this replaces nothing in lessons 1 through 13.** Chaos experiments find *emergent, systemic* failures: saturation, feedback loops, missing fallbacks, defences that were never executed. They are structurally incapable of finding a logic bug. Nothing in this lesson would notice that a discount boundary uses `<` instead of `<=`, that a status string is `"succeeded"` rather than `"success"` ([Test Doubles](../04-test-doubles/)), or that a consumer double-charges on a redelivered message ([Testing Async & Event-Driven Systems](../11-testing-async-and-event-driven/)). Those need a unit test, a contract test and a duplicate-delivery test respectively. The relationship is complementary and the ordering is not negotiable: a team that runs chaos experiments and cannot get a clean build has bought a very expensive way to discover that its retries are misconfigured while shipping the same bugs it always shipped.

## Build It

[`code/chaos.py`](code/chaos.py) is one file, standard library only, no network, seeded at `20260718`, and it prints every number above in about ten seconds. Two runs `diff` clean. Six numbered sections map onto the concepts.

The **simulator** is the part worth reading even if you never run a chaos experiment, because it is about a hundred lines and it removes all the magic. There is no sleeping: `now` is a float that jumps to the next scheduled event, so ninety-five seconds of a saturated fleet costs a fraction of a real second. Determinism comes from one detail — an incrementing sequence number breaking ties in the event heap, so equal timestamps always resolve in the same order:

```python
def at(self, delay: float, fn: Callable[[], None]) -> None:
    self._seq += 1
    heapq.heappush(self._heap, (self.now + delay, self._seq, fn))
```

A **request is a generator** that yields what it is waiting for. This is the whole concurrency model, and it makes a service's request handler read exactly like the blocking code it models — acquire a worker, do local work, call your dependencies, release:

```python
def handle(self, req: Req) -> Proc0:
    got = yield ("acquire", self.pool)          # a worker, or wait in line
    if not got:
        return SHED                             # the bounded-queue case
    work = self.local_ms * math.exp(self.rng.gauss(0.0, 0.30))
    if self._faulted(req) and self.fault.kind == "slow":
        work *= self.fault.factor
    yield ("sleep", work)
```

Note that the worker is held for the *entire* call, dependencies included. That single choice is what makes the cascade in section 2 happen: a worker blocked on a slow dependency is a worker unavailable to everyone else, and it is why the 675-deep queue formed on `orders` rather than on the pool next to the fault.

The **timeout** is one of the more instructive five lines in the file. A timer and the downstream call race to fire the same future, and whichever arrives first wins:

```python
fut = self.sim.spawn(self.dep.handle(req))
self.sim.at(self.policy.timeout_ms, lambda f=fut: self.sim.fire(f, TIMED_OUT))
outcome = yield ("wait", fut)
```

Losing that race does not *stop* anything. The downstream generator keeps running and keeps holding a downstream worker, which is exactly right — cancellation does not propagate across a network unless you build it to — and it is the second sustaining effect in the retry storm: a saturated service spending 100% of its capacity computing answers no caller is waiting for.

The **retry budget** is nine lines and it is the difference between the metastable row and the recovering one. Each primary request mints 0.10 tokens; each retry spends one; when the bucket is empty you get one attempt and no more:

```python
def credit(self) -> None:
    self.tokens = min(self.capacity, self.tokens + self.ratio)

def take(self) -> bool:
    if self.tokens >= 1.0:
        self.tokens -= 1.0
        return True
    self.denied += 1
    return False
```

The **blast radius** is a stable cohort on the request, not a coin flip, so that the injected slice and the control slice are comparable populations and the same request is always in the same group:

```python
req = Req(rid=rid, cohort=(rid * 37) % 100, t_start=sim.now)
```

And the **abort** is the part that makes the whole thing legitimate. It is the monitor, tied to the SLO, with the lag made explicit rather than hidden:

```python
t1 = sim.now - MONITOR_LAG_MS       # you cannot score a second until it has closed
...
breaches = breaches + 1 if rate < SLO_TARGET else 0
if breaches >= abort_after:
    result.aborted_at = sim.now
    fault.end = min(fault.end, sim.now)
```

Run it:

```bash
python3 phases/12-testing-and-quality/14-chaos-engineering-and-testing-in-production/code/chaos.py
```

```console
== 2 · GREY FAILURE: A HARD KILL VERSUS THE SAME DEPENDENCY 5x SLOWER ==
  identical experiment window: fault at t=15 s, removed at t=35 s, observed to t=75 s
  inventory is OPTIONAL to the order (a fallback exists); payments is REQUIRED.

    target      fault    dependency  dependency   first user    bad     error budget   good AFTER  recovers
                        SLI: errors  SLI: latency   impact     requests     burned       restored     after
    inventory   KILL          1.0 s        never       never         0       0.0 min      100.0%      1.0 s
    inventory   5x SLOW       3.0 s        1.0 s       0.0 s      2744     130.7 min       50.6%     21.0 s
    payments    KILL          1.0 s        never       0.0 s      1402      66.8 min       98.7%      2.0 s
    payments    5x SLOW       1.0 s        1.0 s       0.0 s      1346      64.1 min       99.0%      2.0 s

  the mechanism — where the queue formed, and whether anything noticed:
    scenario           peak queue depth       breaker trips      user p50/p99
                   inv pool  pay pool  orders  inv-edge pay-edge  while faulted
    inventory-kill         3         3       4        10        0       47 / 99     ms
    inventory-slow        10         5     675         0        0     2006 / 3395   ms
    payments-kill          3         1       4         0       10        8 / 45     ms
    payments-slow          3         6      32         0        8        9 / 800    ms

== 4 · ABLATION: THE SAME FAULT AGAINST FIVE DEFENCE CONFIGURATIONS ==
    configuration          good WHILE   good AFTER   post-trigger   error budget   recovery
                            degraded     restored    amplification     burned        time
    no defence at all           0.2%        22.4%         1.64x        230.1 min     41.0 s
    timeout only                0.1%        22.5%         1.64x        230.1 min     40.7 s
    + retry (naive)             0.1%         0.0%         1.65x        267.8 min      never
    + jitter + budget           0.1%        16.1%         1.65x        240.7 min     43.7 s
    + breaker + shed            2.5%        97.5%         1.24x        101.8 min      2.7 s

  how the last row won: it declined 2,141 calls at the circuit
  breaker and the retry budget, and shed 0 at the bounded queue.
```

Three things in that output are arguments rather than demonstrations.

**Section 2's `first user impact` column for the hard kill reads `never`.** Not "small" — the fault ran for twenty seconds and not one user request was affected, because the fallback that handles an inventory error was written years ago and works. Every other row in that table is a fault that had no such path.

**The `dependency SLI: errors` column reads `3.0 s` for the slowdown and `never` for its latency counterpart on the kill.** Those two columns are the two dashboards you have. Against a grey failure the error dashboard is three seconds late and the latency dashboard is one second early — so which of them is wired to your pager decides whether you find this in seconds or in the postmortem.

**Section 4's `+ retry (naive)` row is the only `never` in the recovery column.** The configuration that adds the most obviously helpful defence is the only one that does not come back on its own. If you take one thing from this lesson into a config file, it is that a retry without a budget is a load multiplier you have installed on the exact failure mode where multiplying load is fatal.

## Use It

You do not have a simulator at work. You have a real system and a reasonable colleague asking why you want to break it. Here is the toolchain, cheapest first.

**Toxiproxy is the right first tool, and it runs in CI.** It is a TCP proxy you put between your service and a dependency; you then add *toxics* over an HTTP API. It needs no cluster, no privileged container and no kernel modules, which is why it is the one that actually gets adopted.

```bash
docker run -d --name toxiproxy -p 8474:8474 -p 25432:25432 ghcr.io/shopify/toxiproxy

# your app connects to localhost:25432; toxiproxy forwards to the real postgres
curl -s -XPOST http://localhost:8474/proxies -d '{
  "name": "postgres", "listen": "0.0.0.0:25432", "upstream": "postgres:5432"
}'

# THE experiment from this lesson: not down, just slow — on 5% of connections
curl -s -XPOST http://localhost:8474/proxies/postgres/toxics -d '{
  "name": "grey", "type": "latency", "stream": "downstream",
  "toxicity": 0.05, "attributes": {"latency": 200, "jitter": 50}
}'

# ... run your integration suite against it, assert on your SLI, then:
curl -s -XDELETE http://localhost:8474/proxies/postgres/toxics/grey
```

`toxicity` is the blast-radius dial — `0.05` applies the toxic to 5% of connections. The toxics worth knowing are `latency` (grey failure), `bandwidth`, `slicer` (splits a response into pieces with delays between them, which finds partial-read bugs nothing else finds), `timeout` (accepts and never answers — the one that catches missing timeouts) and `limit_data`. To hard-kill instead, `POST /proxies/postgres` with `{"enabled": false}`. Two flags that bite: `stream` must be `downstream` to delay responses (`upstream` delays your requests, which is a different experiment), and a toxic with no `toxicity` defaults to `1.0`, meaning 100%.

**Envoy gives you percentage-based fault injection with no new infrastructure**, if you already run a service mesh or a sidecar. The `fault` HTTP filter does delay and abort, and — the part that makes it safe — it can be gated on a header, so the fault only applies to requests you explicitly mark:

```yaml
http_filters:
  - name: envoy.filters.http.fault
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.fault.v3.HTTPFault
      delay:
        fixed_delay: 0.2s
        percentage: { numerator: 5, denominator: HUNDRED }
      abort:
        http_status: 503
        percentage: { numerator: 1, denominator: HUNDRED }
      headers:
        - name: x-chaos-experiment
          string_match: { exact: "inventory-grey-failure" }
  - name: envoy.filters.http.router      # the router filter MUST be last
```

`denominator` also accepts `TEN_THOUSAND` and `MILLION`, which is how you get below 1%. Put the filter on the *upstream* cluster's listener so it models the dependency being slow rather than your own service being slow — they are different experiments and people conflate them constantly.

**On Kubernetes, Chaos Mesh and LitmusChaos** express experiments as custom resources, which means they go through code review and have a `duration`:

```yaml
apiVersion: chaos-mesh.org/v1alpha1
kind: NetworkChaos
metadata: { name: inventory-grey-failure, namespace: prod }
spec:
  action: delay
  mode: fixed-percent
  value: "5"                      # 5% of matching pods — the blast radius
  duration: 120s                  # it stops itself. Set this. Always.
  direction: to
  selector:
    namespaces: [prod]
    labelSelectors: { app: inventory }
  delay: { latency: 200ms, jitter: 50ms, correlation: "50" }
```

Underneath, that is `tc netem`, which you can run directly on a single host to prove the mechanism to yourself before you ask anyone for a CRD:

```bash
tc qdisc add dev eth0 root netem delay 200ms 50ms distribution normal
tc qdisc del dev eth0 root          # have this in your shell history BEFORE the add
```

**AWS Fault Injection Service** is the one to reach for when the fault is infrastructure rather than network — stopping instances, throttling an API, killing a task. Its genuinely important feature is not the actions; it is that **stop conditions are first-class**: an experiment template binds to CloudWatch alarms and AWS halts the experiment when one fires. That is the abort from section 5, enforced by something other than the person running the experiment. Configure the alarm on your user-facing SLI, not on the resource you are attacking. `pumba` is the equivalent for plain Docker, and Gremlin is the commercial version of all of the above with an approval workflow attached.

**And the cheapest fault injector of all is a feature flag in your own code.** A `if flags.enabled("chaos.inventory.latency", request): sleep(0.2)` behind your existing flag system inherits your existing percentage targeting, your existing kill switch and your existing audit log — which is three of the four prerequisites for free. [Deploy ≠ Release: Feature Flags & Progressive Delivery](../../10-infrastructure-and-deployment/12-deploy-vs-release-feature-flags/) is the mechanism.

**For canary analysis, do not write the comparison yourself.** Argo Rollouts' `AnalysisTemplate` and Spinnaker's Kayenta both run the statistical comparison and return a verdict; Flagger does the same for Istio and Linkerd. What this lesson should change is what you configure them with: a **duration derived from the traffic needed for the power you want** (1,200 requests per arm for 80% power on a 1.0-point regression), rather than "10 minutes". If your tooling only supports a threshold, at minimum recalibrate it per traffic level and make it refuse to decide below a minimum sample count.

**What to actually do, in order.** The first three experiments, and none of them needs a platform team:

1. **Add 200 ms of latency to one dependency, for 5% of requests, in staging, with your integration suite running.** Toxiproxy, twenty minutes of work. Assert on your SLI, not on "did it crash". This is the experiment that found 130.7 minutes of error budget in this lesson and it is the one nobody runs.
2. **Do it again for 30 seconds, then remove it, and watch whether the system comes back.** That is the metastability check. If recovery takes longer than the fault, you have a sustaining effect and a retry config to change — and the measured difference here was `never` versus `4.0 s`.
3. **Kill the dependency outright.** Do this one *third*, not first, because it is the one your code most likely already handles — and if it turns out it does not, you have learned that from the cheapest possible experiment.

Then, before any of it touches production: an **SLO** to hypothesise on, **observability** with a known lag, a **rollback you have used this quarter**, and a **blast radius with an automatic abort**. All four, or it is not an experiment.

## Think about it

1. The hard kill produced a median user latency of **47 ms** against an 89 ms steady state — the system got *faster* when a dependency died. Name the monitoring rule this defeats, and describe what a dashboard would have to plot for the kill and the 5× slowdown to look different from each other before a human reads them.
2. `timeout only` and `no defence at all` burned **identical** error budget (230.1 min both), yet timeouts are near-universal advice. Construct the specific failure for which the timeout row would separate from the no-defence row, and say what else in the ablation table would have to be true for that separation to be large.
3. The `+ jitter + budget` configuration recovered where naive retry did not (43.7 s versus never), but still burned **more** budget than having no defence at all (240.7 versus 230.1 min). You have one change to make and cannot add a circuit breaker. What do you change, and what measurement from this lesson tells you the size of the change?
4. At 1% and 5% injection the cascade never appeared — peak queue 2 and 4 — and at 25% it did, at 34. You are asked to run continuous automated chaos in production with a hard rule that no experiment may exceed 5%. Which class of failure have you permanently excluded from ever being found, and what *other* instrument would you point at that class instead?
5. At 200 requests per arm, the z test missed **68.7%** of real regressions and the naive threshold missed only 24.3% while false-alarming 33.1% of the time. A team reads this and concludes the naive rule is better for low-traffic services. Using the numbers in this lesson, construct the argument that changes their mind — and then say what a canary system for a genuinely low-traffic service should actually do instead.

## Key takeaways

- **Down is a code path; slow is not.** Killing a dependency outright cost **0 failed requests and 0.0 minutes of error budget**, because the error hit a fallback somebody wrote. Making the same dependency **5× slower** for the same twenty seconds cost **2,744 failed requests, 130.7 minutes of budget**, a p50 of **2,006 ms**, and a recovery that arrived **21 seconds after the fault was already gone**.
- **A circuit breaker counts errors, so grey failure is invisible to it.** Measured: **10 trips** on the hard kill, **0** on the 5× slowdown. Against the fault that actually caused the outage, the defence built for that dependency never fired — and it is not broken.
- **Your connection pool's spare capacity is a latency budget, and it is smaller than it looks.** By Little's law the `orders→inventory` pool needs `L = 2.80` slots and has 6 — which is not "70% spare", it is **2.1× of tolerance for a slower dependency**. Inject 5× and the queue two hops away peaks at **675**.
- **Retries without a budget are a load multiplier aimed at a saturation failure.** Against a 30-second latency spike that was then fully removed, naive 3× retry burned **267.8 minutes against 230.1 for no defence at all**, and was the only configuration of five that **never** recovered — wire attempts held at 110/s with goodput at exactly 0 for the rest of the run.
- **Metastable failure is a two-part definition and both parts are yours.** A trigger creates the state; a sustaining effect holds it. Here there were two sustaining effects: retries chasing requests that failed because of retries, and abandoned work that the downstream keeps computing after the caller has given up. Capping amplification at **1.24× instead of 1.64×** was the whole difference.
- **Every fix in the ablation that worked, worked by doing less.** The winning configuration declined **2,141 calls** at the breaker and the retry budget and served **97.5% good** after restoration against 0.0%. The bounded queue shed **0** — it never fired, because the breaker got there first, which is exactly the kind of thing you only learn by turning defences off one at a time.
- **A 1% blast radius buys most of the signal for almost none of the damage — for direct effects only.** 1% injection recovered a Mann-Whitney **z of 6.2 for 2 failed requests**; 100% recovered **z = 22.7 for 637**. But peak queue depth went **2 → 4 → 34 → 180**, so the emergent cascade has a threshold between 5% and 25% and no small experiment will ever find it.
- **Past some radius you lose your own control group.** At 25% injection the *uninjected* cohort's p50 rose from **90 ms to 252 ms** and the measured z fell from 10.3 to 9.8. An experiment that contaminates its own baseline can no longer measure itself.
- **A canary threshold is a hypothesis test whose false-alarm rate you did not choose.** The naive rule false-alarmed **33.1% at 200 requests per arm and 0.0% at 100,000**; a z test held between **1.9% and 5.5%** throughout. Detecting a 1.0-point regression at 80% power needs **1,200 requests per arm**, or a median of **305** with Wald's sequential test — and a latency threshold calibrated to 5% alarms must be **+10.2%** at 200 samples and **+2.4%** at 3,200.
- **Chaos experiments find emergent failures, not logic bugs, and replace nothing in lessons 1–13.** Nothing here would catch a `<` that should be `<=`, a status string renamed by a provider, or a double-charged redelivery. And without an SLO, observability with a known lag (**3.0 seconds** here), a rollback used this quarter, and an automatic abort (**5.0 seconds** measured), this is not an experiment — it is an outage you scheduled.

Next: [Capstone: A Suite That Catches Real Bugs](../15-capstone-a-suite-that-catches-real-bugs/) — thirty-one seeded bugs, nine layers of testing, and the marginal-value table that prices every technique in this phase against the others.
