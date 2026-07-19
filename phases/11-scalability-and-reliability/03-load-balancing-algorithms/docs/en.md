# Load Balancing Algorithms: Why Round-Robin Lies

> Your request-rate graph is perfectly flat across all eight instances, and that is exactly why nobody suspects the balancer. Measured here: identical request counts produced a **24% spread in actual work**, one instance ran at **87.9% busy while the other seven averaged 30.4%**, and p99 sat at **32× p50** on a fleet using a third of its capacity. Then the result worth memorising — picking **two backends at random and taking the less loaded** beats one random pick exponentially, needs no shared state, and is the only reason "least loaded" does not stampede at fleet scale.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The Universal Scalability Law](../02-universal-scalability-law/), [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/)
**Time:** ~80 minutes

## The Problem

It is 09:41 and the checkout service has been breaching its p99 objective for six minutes. You open the dashboard. The first panel is requests per second, broken out per instance: eight lines, and the eight lines are drawn on top of each other. **31 requests per second each, flat, all morning.** Whatever this is, it is not the load balancer. The load balancer is doing precisely what it says on the tin.

The second panel is latency. p50 is **16.8 ms** — the number you would put in a slide. p99 is **538 ms**, which is **32× your own median**. The fleet is running at **33% of its total capacity**. Nothing is saturated. Nothing has restarted. There is no bad deploy to roll back, no error rate to point at, and every health check in the fleet is green.

The third panel is the one that breaks the story. CPU, per instance. Seven instances sit at about **30%**. One sits at **87.9%**.

**09:44 — you find it.** Instance 7 is slow. Not down, not erroring, not failing its health check — its health check returns `200 OK` in four milliseconds, because the health check is a handler that returns `200 OK` and does nothing else. Instance 7 takes **60 ms** to serve the request the other seven serve in 20 ms. Maybe its EBS volume is on a degraded host, maybe it lost the CPU-frequency lottery, maybe a neighbouring container is stealing cycles, maybe its runtime deoptimised a hot path four hours ago. The cause is not the point. The point is the number your balancer sent it.

That instance can do **33.3 requests per second**. Round-robin is giving it **31**.

```text
utilization rho = arrival rate / service rate = 31 / 33 = 0.92
```

Phase 8 Lesson 11 established what a queue does at ρ = 0.92, and it is not a gentle degradation: `W = S/(1−ρ)` puts the wait at roughly twelve times the service time, and the tail far beyond that. So one instance in eight has a deep queue, seven have none, and the p99 you are being paged for is entirely produced by the one server that is 12.5% of your traffic. **Your median is fine because seven eighths of your users are fine.** That is not comfort; that is the shape of the failure.

**09:52 — someone suggests adding instances.** Do the arithmetic in the incident channel rather than after it. Under round-robin every backend receives `offered / n`, so the whole fleet is capped by its *slowest* member:

```text
fleet capacity      = 7 x 100 req/s  +  1 x 33.3 req/s  =  733 req/s
round-robin ceiling = 8 x 33.3 req/s                    =  267 req/s   -> 64% unreachable
```

**A fleet that can serve 733 requests per second is capped at 267 by its routing policy.** And a ninth healthy instance does not fix the ratio — the ceiling moves to 300 req/s while the fleet gains another 100 req/s of capacity, so the unreachable share stays at **64%**. You are not short of capacity. You are short of a balancer that knows the difference between a request and a unit of work.

Here is the sentence the whole lesson turns on:

> **Round-robin equalises request count, and request count is not load.**

Three things are true at once, and each one alone is enough to break the equality. **Requests are not the same size** — the same endpoint costs 3 ms on a cache hit and 900 ms for the tenant with forty thousand rows. **Servers are not the same speed** — in any fleet above a handful of machines, at any moment, at least one member is degraded and still passing its health check. And the third, which is the one that turns a slow server into an outage: **under round-robin, a struggling server receives exactly as much work as a healthy one.** It is the one policy in this lesson with that guarantee. Every other policy on the list, including *uniform random*, will eventually notice. Round-robin never will, because it is not looking.

## The Concept

### What the balancer is actually choosing

Strip away the vocabulary and every load-balancing algorithm answers the same question, under the same three constraints.

**The question:** there are N backends and one request in your hand. Pick one.

**Constraint 1 — no perfect knowledge.** You cannot know how long this request will take, because you have not run it. You cannot know how loaded a backend is, because "loaded" means CPU, memory pressure, lock contention, GC state, page-cache warmth and the depth of a queue you cannot see. What you have is a proxy: a counter you keep, or a number the backend told you a while ago.

**Constraint 2 — very high rate.** This choice happens once per request, tens of thousands of times a second, inside your latency budget. An algorithm that scans and sorts all N backends has a cost that grows with your fleet, on every request. That is why most of the good answers are *sampling* answers.

**Constraint 3 — your information is stale, and you are not the only balancer.** Time passes between reading a backend's load and the request arriving there. And dozens or hundreds of balancers are making this same decision in the same millisecond, from the same stale numbers, without talking to each other. This constraint is invisible in a single-balancer diagram and it is where most production surprises live.

So the honest taxonomy is not "simple to sophisticated". It is **what signal do you have, and how stale is it** — and every algorithm below is one answer to that, with a failure mode attached.

### Round-robin, weighted round-robin, and the smooth variant

Round-robin keeps an integer and increments it. Backend `i = counter++ % N`. It needs no signal, no coordination, and no memory beyond one counter, and it produces the most even distribution of *arrivals* that exists: throw N requests at N backends and the busiest backend has exactly **1**. Measured, at every fleet size:

```text
       n   trials   RR max   random max   ln n / ln ln n   empty bins
      16      400        1         3.04             2.72       35.1%
    1000      120        1         5.53             3.57       36.7%
   10000       30        1         6.50             4.15       36.8%
```

That column of `1`s is genuinely optimal and genuinely worthless, because nobody has ever been paged for uneven request counts. Here is the same fleet, forty seconds, one heavy-tailed cost distribution, counting both things at once:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 492" width="100%" style="max-width:840px" role="img" aria-label="Two measured bar charts from the same forty-second round-robin run over eight identical backends. On the left, requests routed per backend: all eight bars are identical at 2522 or 2521 requests, a spread of one request. On the right, the work each backend actually performed in seconds: the bars range from 45.5 seconds to 56.5 seconds, a 24 percent spread, because round-robin cannot see request size. Below, the same arrival stream through three policies shows round-robin at a 900 millisecond p99 against least-connections at 587 milliseconds, and round-robin made 31 percent of all requests wait in a queue while another backend was completely idle.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Round-robin equalises request COUNT. Request count is not load.</text>

    <text x="235" y="56" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">requests routed — the graph on your dashboard</text><text x="655" y="56" text-anchor="middle" font-size="11.5" font-weight="700" fill="#e0930f">work actually done, seconds — the truth</text>

    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M58 300 L 412 300"/><path d="M58 300 L 58 106"/><path d="M478 300 L 832 300"/><path d="M478 300 L 478 106"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.5">
      <path d="M53 106 L 58 106"/><path d="M53 300 L 58 300"/><path d="M473 106 L 478 106"/><path d="M473 300 L 478 300"/>
    </g>

    <g fill="#3553ff" fill-opacity="0.30" stroke="#3553ff" stroke-width="1.6">
      <rect x="66" y="140" width="30" height="160"/><rect x="110" y="140" width="30" height="160"/><rect x="154" y="140" width="30" height="160"/><rect x="198" y="140" width="30" height="160"/><rect x="242" y="140" width="30" height="160"/><rect x="286" y="140" width="30" height="160"/><rect x="330" y="140" width="30" height="160"/><rect x="374" y="140" width="30" height="160"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.6">
      <rect x="486" y="134" width="30" height="166"/><rect x="530" y="121" width="30" height="179"/><rect x="574" y="139" width="30" height="161"/><rect x="618" y="134" width="30" height="166"/><rect x="662" y="136" width="30" height="164"/><rect x="706" y="156" width="30" height="144"/><rect x="750" y="138" width="30" height="162"/><rect x="794" y="156" width="30" height="144"/>
    </g>
    <rect x="530" y="121" width="30" height="179" fill="none" stroke="#d64545" stroke-width="2.4"/><rect x="706" y="156" width="30" height="144" fill="none" stroke="#0fa07f" stroke-width="2.4"/><rect x="794" y="156" width="30" height="144" fill="none" stroke="#0fa07f" stroke-width="2.4"/>

    <path d="M62 140 L 408 140" fill="none" stroke="#3553ff" stroke-width="1.5" stroke-dasharray="5 4" opacity="0.9"/><path d="M482 139 L 828 139" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.55"/>

    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.9">
      <text x="81" y="133">2522</text><text x="125" y="133">2522</text><text x="169" y="133">2522</text><text x="213" y="133">2522</text><text x="257" y="133">2522</text><text x="301" y="133">2522</text><text x="345" y="133">2521</text><text x="389" y="133">2521</text>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle">
      <text x="501" y="127">52.5</text><text x="545" y="114" font-weight="700" fill="#d64545">56.5</text><text x="589" y="132">50.9</text><text x="633" y="127">52.4</text><text x="677" y="129">51.8</text><text x="721" y="149" font-weight="700" fill="#0fa07f">45.5</text><text x="765" y="131">51.1</text><text x="809" y="149" font-weight="700" fill="#0fa07f">45.5</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.7">
      <text x="81" y="314">be0</text><text x="125" y="314">be1</text><text x="169" y="314">be2</text><text x="213" y="314">be3</text><text x="257" y="314">be4</text><text x="301" y="314">be5</text><text x="345" y="314">be6</text><text x="389" y="314">be7</text><text x="501" y="314">be0</text><text x="545" y="314">be1</text><text x="589" y="314">be2</text><text x="633" y="314">be3</text><text x="677" y="314">be4</text><text x="721" y="314">be5</text><text x="765" y="314">be6</text><text x="809" y="314">be7</text>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.7">
      <text x="49" y="303">0</text><text x="49" y="110">3000</text><text x="469" y="303">0</text><text x="469" y="110">60 s</text>
    </g>
    <text x="416" y="144" font-size="8.5" fill="#3553ff" font-weight="700">flat</text><text x="836" y="143" font-size="8.5" fill="currentColor" opacity="0.6">mean</text>

    <g font-size="10">
      <text x="235" y="338" text-anchor="middle" fill="#3553ff" font-weight="700">spread: 1 request  ·  0.04%</text><text x="655" y="338" text-anchor="middle" fill="#e0930f" font-weight="700">spread: 11.0 s  ·  24.14%  ·  busy 55.7% vs 69.2%</text>
    </g>
    <text x="440" y="360" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">why: the 900 ms tail is 1% of requests and 41% of the work — round-robin dealt 14 to 31 of them per backend, blind.</text>

    <rect x="58" y="376" width="774" height="82" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="76" y="394">SAME 20,174 REQUESTS · SAME WORK · 3 POLICIES</text><text x="392" y="394">p50</text><text x="470" y="394">p99</text><text x="556" y="394">MAX QUEUE</text><text x="656" y="394">QUEUED WHILE ANOTHER WAS IDLE</text>
    </g>
    <g fill="currentColor" font-size="10.5">
      <text x="76" y="412" font-weight="700" fill="#d64545">round-robin</text><text x="392" y="412">20.0 ms</text><text x="470" y="412" font-weight="700" fill="#d64545">900.0 ms</text><text x="556" y="412">93</text><text x="656" y="412" font-weight="700" fill="#d64545">31.1%  (6,271)</text><text x="76" y="431" font-weight="700">power of two choices</text><text x="392" y="431">3.0 ms</text><text x="470" y="431" font-weight="700">823.4 ms</text><text x="556" y="431">14</text><text x="656" y="431" font-weight="700">12.1%  (2,440)</text><text x="76" y="450" font-weight="700" fill="#0fa07f">least-connections</text><text x="392" y="450">3.0 ms</text><text x="470" y="450" font-weight="700" fill="#0fa07f">587.5 ms</text><text x="556" y="450">5</text><text x="656" y="450" font-weight="700" fill="#0fa07f">0.0%  (0)</text>
    </g>
    <text x="440" y="480" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Identical counts, 24% different work. A perfectly flat request-rate graph is exactly why nobody suspects the balancer.</text>
  </g>
</svg>
```

Look at what is identical and what is not. Every backend received **2522 requests** (two got 2521) — a spread of **one request across 20,174**, or 0.04%. Every backend did between **45.5 and 56.5 seconds of work** — a spread of **24.14%**. Nothing about the balancer changed between those two measurements; they are the same run, viewed through two different columns.

The mechanism is visible in the third column of the program's output. One percent of requests cost 900 ms and account for **41% of all the work**, and round-robin dealt between **14 and 31** of them per backend. It could not do otherwise: it does not know a 900 ms request from a 3 ms one, and by the time it could know, it has already sent it. The most damning single number is elsewhere in that run: **6,271 of 20,174 requests — 31.1% — were put into a queue while at least one other backend was completely idle.** Under least-connections, on the identical stream, that number is **zero**.

**Weighted round-robin** is the standard patch: give the bigger machine `weight=5` and the smaller one `weight=1`. Two problems. The first is that the weights are a static description of a dynamic system — you set them when the c5.4xlarge was new, and they are now describing a host with a degraded disk, a noisier neighbour, and a colder page cache. **Static weights rot, and they rot silently**, because nothing in the system ever checks them against reality. The second is subtler and is about *how* the weights are emitted.

The naive implementation emits each backend's weight as a run. With `A=5, B=1, C=1` that is `AAAAABC`, repeating. Over a full cycle the ratio is exactly 5:1:1 — and A receives five requests back to back, then nothing for two. At high rates that burst is a real queue on A while B and C idle. nginx solves this with **smooth weighted round-robin**: keep a running `current[i]`, add every weight to it on each pick, select the maximum, and subtract the total weight from the winner. Same ratio, no runs:

```text
  the sequence round-robin emits, weights A=5 B=1 C=1:
    naive weighted RR   AAAAABCAAAAABC   <- A gets a 5-deep burst
    smooth weighted RR  AABACAAAABACAA   <- same 5:1:1 ratio, spread out
```

Both sequences give A five of every seven requests. Only the second one keeps A's instantaneous queue flat. This is what you are actually running whenever you write `server ... weight=5;` in nginx, and it is worth knowing that the smoothing exists so you do not go looking for it elsewhere.

### Random, and what "balanced" costs when nobody coordinates

Uniform random is the opposite trade: worse distribution, zero state. It is genuinely the cheapest correct policy — no counter to share between threads, no counter to share between balancers, no cache line bouncing between cores at 50,000 requests per second. And the price is a classic result, **balls in bins**: throw `n` balls into `n` bins uniformly at random and the fullest bin holds

```text
max load  =  (1 + o(1)) * ln n / ln ln n
```

(Gonnet, 1981; tightened in Azar, Broder, Karlin & Upfal, *Balanced Allocations*, SIAM J. Comput. 29(1), 1999.) The table above is that result measured. At n = 10,000 the busiest backend holds **6.50×** the average while **36.8% of the fleet receives nothing at all** — and that 36.8% is not a coincidence, it is `1/e`, the probability that a given bin is missed by all n throws. Note that the asymptotic formula reads 4.15 where the measurement reads 6.50: the `(1 + o(1))` is doing real work at fleet sizes you will actually operate, which is the ordinary reason to trust the measurement over the closed form.

Keep the number 6.50 in mind for four paragraphs. Almost all of that gap is recoverable, and the recovery is astonishingly cheap.

### Least-connections: the first policy that measures load instead of counting arrivals

**Least-connections** — Envoy calls it *least request*, nginx `least_conn`, HAProxy `leastconn` — tracks how many requests you have dispatched to each backend and not yet received a response for, and sends the next one to the smallest count. That count is a much better proxy for load than arrivals, because a slow request stays counted for as long as it is slow. A backend that is 3× slower accumulates 3× the outstanding requests at the same arrival rate, and least-connections stops sending to it *without ever being told it is slow*. Measured, on the grey-failure fleet from The Problem:

```text
    policy                  p50      p99     p999   maxQ  b0 share  b0 busy%
    rr                    16.8ms  537.7ms   723.9ms    25    12.5%     87.9%
    random                19.0ms  860.0ms  1315.3ms    38    12.8%     92.0%
    least_conn            14.7ms  120.9ms   257.3ms     0     6.4%     44.0%
    p2c                   15.1ms  136.3ms   266.8ms     2     7.9%     56.1%
```

Round-robin sends the slow backend its full **12.5%**. Least-connections discovers, from the outstanding count alone, that it should get **6.4%**, and p99 falls from **538 ms to 121 ms**. The maximum queue depth anywhere in the fleet goes from 25 to **0** — under least-connections nothing ever waited. This is why least-connections is the sane default for variable request costs, and why you should reach for it before you reach for anything cleverer.

Now the two things that are wrong with it.

**It is a lagging signal.** The outstanding count only rises after a backend is *already* slow enough to accumulate work. It cannot warn you; it can only react, and it reacts on the timescale of your own request latency. Under a sharp change — a garbage-collection pause, a cold cache after a restart, a lock convoy — a batch of requests goes into the hole before the count reflects it.

**And it actively rewards failure.** This one deserves its own name, because it is the failure mode that turns a single broken instance into a fleet-wide outage.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The load-balancer death spiral drawn as a four-step feedback loop: a backend starts failing and returns errors in half a millisecond, so its load signal looks perfect with zero outstanding requests and the lowest latency in the fleet, so the balancer ranks it best, so it receives more traffic, which produces more instant failures. Below, the measured share of all traffic sent into that black hole under seven policies over the same 19,285 request stream: round-robin 12.5 percent, least-connections 50.3 percent, peak EWMA on latency alone 90.6 percent, power of two choices on outstanding requests 23.0 percent, peak EWMA with a failure penalty 1.1 percent, P2C with EWMA and penalty 1.6 percent, and the same with passive ejection 0.5 percent.">
  <defs>
    <marker id="p11-03-c1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The death spiral: a broken backend wins every load contest it enters</text>

    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="60" y="60" width="210" height="58" rx="10" fill="#d64545" fill-opacity="0.12" stroke="#d64545"/><rect x="610" y="60" width="210" height="58" rx="10" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/><rect x="610" y="164" width="210" height="58" rx="10" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/><rect x="60" y="164" width="210" height="58" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.9">
      <path d="M270 82 L 604 82" marker-end="url(#p11-03-c1)"/><path d="M715 118 L 715 158" marker-end="url(#p11-03-c1)"/><path d="M610 200 L 276 200" marker-end="url(#p11-03-c1)"/><path d="M165 164 L 165 124" marker-end="url(#p11-03-c1)"/>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="165" y="80" font-size="10.5" font-weight="700" fill="#d64545">1 · the backend breaks</text><text x="165" y="96" font-size="9" opacity="0.9">returns HTTP 500 in 0.5 ms,</text><text x="165" y="110" font-size="9" opacity="0.9">doing none of the work</text><text x="715" y="80" font-size="10.5" font-weight="700" fill="#e0930f">2 · its signal looks PERFECT</text>
      <text x="715" y="96" font-size="9" opacity="0.9">0 outstanding requests,</text><text x="715" y="110" font-size="9" opacity="0.9">0.5 ms latency — best in fleet</text><text x="715" y="184" font-size="10.5" font-weight="700" fill="#7c5cff">3 · the balancer ranks it #1</text><text x="715" y="200" font-size="9" opacity="0.9">least-conn: lowest count wins</text>
      <text x="715" y="214" font-size="9" opacity="0.9">peak EWMA: lowest latency wins</text><text x="165" y="184" font-size="10.5" font-weight="700" fill="#3553ff">4 · so it gets MORE traffic</text><text x="165" y="200" font-size="9" opacity="0.9">which it also fails instantly,</text><text x="165" y="214" font-size="9" opacity="0.9">which improves its score again</text>
    </g>
    <text x="440" y="134" font-size="10.5" text-anchor="middle" fill="#d64545" font-weight="700">the signal is correct — the interpretation is not</text><text x="440" y="152" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.85">0 outstanding really IS the lowest load in the fleet. Nothing here is a bug.</text>

    <text x="440" y="256" font-size="11.5" text-anchor="middle" font-weight="700" fill="currentColor">measured: share of all 19,285 requests routed into the black hole</text>

    <path d="M390 268 L 390 434" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.5"/><path d="M440 268 L 440 434" fill="none" stroke="#7c5cff" stroke-width="1.3" stroke-dasharray="5 4" opacity="0.8"/>

    <g>
      <rect x="340" y="272" width="50" height="15" fill="#7f7f7f" fill-opacity="0.45" stroke="#7f7f7f" stroke-width="1.2"/><rect x="340" y="296" width="201" height="15" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.2"/><rect x="340" y="320" width="362" height="15" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.2"/><rect x="340" y="344" width="92" height="15" fill="#e0930f" fill-opacity="0.45" stroke="#e0930f" stroke-width="1.2"/>
      <rect x="340" y="368" width="4.4" height="15" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2"/><rect x="340" y="392" width="6.4" height="15" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2"/><rect x="340" y="416" width="2" height="15" fill="#0fa07f" fill-opacity="0.55" stroke="#0fa07f" stroke-width="1.2"/>
    </g>

    <g fill="currentColor" font-size="9.5" text-anchor="end">
      <text x="332" y="284">round-robin (blind)</text><text x="332" y="308" font-weight="700" fill="#d64545">least-connections</text><text x="332" y="332" font-weight="700" fill="#d64545">peak EWMA, latency only</text><text x="332" y="356" font-weight="700" fill="#e0930f">P2C on outstanding</text>
      <text x="332" y="380" font-weight="700" fill="#0fa07f">peak EWMA + failure penalty</text><text x="332" y="404" font-weight="700" fill="#0fa07f">P2C + EWMA + penalty</text><text x="332" y="428" font-weight="700" fill="#0fa07f">the same + passive ejection</text>
    </g>
    <g fill="currentColor" font-size="10" font-weight="700">
      <text x="398" y="284">12.5%</text><text x="549" y="308" fill="#d64545">50.3%</text><text x="710" y="332" fill="#d64545">90.6%</text><text x="448" y="356" fill="#e0930f">23.0%</text><text x="353" y="380" fill="#0fa07f">1.1%</text><text x="355" y="404" fill="#0fa07f">1.6%</text><text x="351" y="428" fill="#0fa07f">0.5%</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.8">
      <text x="856" y="264" font-size="8.5" font-weight="700" opacity="0.8">500s SERVED</text><text x="856" y="284">2,411</text><text x="856" y="308">9,701</text><text x="856" y="332">17,465</text><text x="856" y="356">4,441</text><text x="856" y="380">209</text><text x="856" y="404">317</text><text x="856" y="428">100</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5">
      <path d="M340 438 L 740 438"/><path d="M340 438 L 340 443"/><path d="M440 438 L 440 443"/><path d="M540 438 L 540 443"/><path d="M640 438 L 640 443"/><path d="M740 438 L 740 443"/>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.7">
      <text x="340" y="454">0%</text><text x="440" y="454">25%</text><text x="540" y="454">50%</text><text x="640" y="454">75%</text><text x="740" y="454">100%</text>
    </g>
    <text x="386" y="266" font-size="8" text-anchor="end" fill="currentColor" opacity="0.7">1/n = 12.5%</text><text x="444" y="266" font-size="8" fill="#7c5cff" font-weight="700">P2C ceiling d/n = 25%</text>

    <text x="440" y="480" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">P2C bounds ANY pathological backend to d/n. Counting a failure as a slow sample is what actually fixes it.</text>
  </g>
</svg>
```

A backend that has crashed into a state where it returns `HTTP 500` in half a millisecond without touching the database has, at every instant, **zero outstanding requests**. It is, by the only measurement your balancer takes, the least loaded server you own. So it gets the next request. Which it fails instantly. Which keeps its count at zero. Which makes it the least loaded server again.

Measured, over 19,285 requests across eight backends with exactly one black hole:

| policy | traffic into the black hole | errors served |
|---|---|---|
| round-robin (blind) | 12.5% | 2,411 |
| least-connections | **50.3%** | 9,701 |
| peak EWMA, latency only | **90.6%** | 17,465 |
| P2C on outstanding | 23.0% | 4,441 |
| peak EWMA + failure penalty | 1.1% | 209 |
| P2C + EWMA + penalty + ejection | **0.5%** | 100 |

**Least-connections routed half of all traffic into a backend that answered nothing**, and the naive latency-aware policy routed **nine requests in ten**. Say the uncomfortable part plainly: *neither of those is a bug in the algorithm*. Zero outstanding requests really is the lowest load in the fleet, and 0.5 ms really is the lowest latency in the fleet. The signal is correct. The interpretation — "low load means send more" — is what is wrong, and it is wrong in exactly the case where being wrong is most expensive. This is the load-balancer **death spiral**, and any load-aware policy you deploy without an error signal has it.

Two fixes, and you want both. The first is to make failure *expensive in the signal itself*: record a failed request as though it took a very long time. Above, counting each failure as a 2,000 ms sample took the black hole's share from 90.6% to **1.1%**. The second is **passive outlier ejection** — take a backend out of rotation entirely once its error rate over a recent window crosses a threshold, and let it back in later. That took it to **0.5%**. Lesson 4 builds ejection properly, including the part where ejecting too many hosts is itself the outage.

### Latency-aware routing: peak EWMA

Outstanding-request count is a count. **Latency** is the thing your users actually experience, and a backend can be slow while holding very few requests. The standard latency-aware policy keeps a per-backend **EWMA — exponentially weighted moving average** — of observed response time and routes by it.

The arithmetic is worth writing out once, because EWMAs recur everywhere in this curriculum and people use them without holding the shape in their head. An EWMA is one line:

```text
value  =  (1 - alpha) * value  +  alpha * observation        0 < alpha <= 1
```

`alpha` is how much you believe the newest sample. `alpha = 1` is "no memory, trust the last request". `alpha = 0.01` is "one bad request barely moves me". The useful way to pick it is not to pick `alpha` at all but to pick a **decay window** τ (tau) in seconds and derive it, because that makes the parameter independent of your traffic rate:

```text
alpha  =  1 - e^(-dt/tau)         dt = seconds since the previous observation
```

At `dt = tau` the old value keeps `1/e ≈ 37%` of its weight; over `3 tau` it is down to 5%. So τ is, near enough, "how many seconds of history this average remembers" — and the code in this lesson uses `tau = 0.05`, a 50 ms memory, because a load balancer needs to react inside a request, not inside a dashboard refresh.

Now the part that makes it work in production. Finagle (Twitter's RPC library) does not use a plain mean. It uses **peak EWMA**: a *decaying maximum*.

```text
decayed = value * e^(-dt/tau)
value   = observation             if observation > decayed        # jump up instantly
        = decayed*(1-alpha) + observation*alpha   otherwise       # ease down slowly
```

The asymmetry is the whole design and it is deliberate: **react fast to degradation, slowly to recovery.** One slow response is enough to raise a backend's score immediately; it then takes many fast responses over several decay windows to earn its traffic back. That is the correct bias, because the two errors are not symmetric. Believing a healthy backend is slow costs you a little spare capacity. Believing a slow backend is healthy costs you a queue, and queues compound. The final score multiplies by the in-flight count, so a backend that looks fast only because nothing has been sent to it does not win forever:

```text
cost(backend)  =  peak_ewma_latency  x  (outstanding + 1)
```

And now the trap, which the table above already measured: **on latency alone, a fast failure is the best score in the fleet.** Peak EWMA with no failure handling sent **90.6%** of traffic into a black hole — worse than least-connections, worse than blind round-robin, worse than doing nothing. A latency-aware balancer that does not treat an error as a very slow response is not a better balancer; it is a more efficient one, pointed at the wrong target.

### The power of two choices

This is the result to memorise. It is one extra line of code and it is the reason modern service meshes stopped needing global load state.

**Pick two backends uniformly at random. Send the request to whichever of the two has less load. That is the entire algorithm.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="On the left, the power of two choices drawn as a mechanism: a balancer draws two backends uniformly at random from a row of ten, compares their outstanding-request counts, and sends the request to the lighter of the two, with the probability argument that a single random pick hits the worst backend with probability one over n while two picks both have to be bad, which is one over n squared. On the right, measured maximum load for n balls thrown into n bins: with one sample the maximum grows from 4.24 at n equals one hundred to 7.92 at n equals one hundred thousand, while with two samples it barely moves from 2.64 to 3.50, and a third sample only reaches 3.00. The second sample removes 4.42 of maximum load and the third removes 0.50 more.">
  <defs>
    <marker id="p11-03-b1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker><marker id="p11-03-b2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One extra random sample buys an exponential improvement</text>

    <text x="215" y="54" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">the entire algorithm — no global state, no coordination</text>

    <rect x="30" y="66" width="150" height="34" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.9"/><text x="105" y="88" text-anchor="middle" font-size="11" font-weight="700" fill="#7c5cff">balancer</text>
    <g fill="none" stroke="#3553ff" stroke-width="1.7">
      <path d="M85 100 C 85 126, 126 124, 126 144" marker-end="url(#p11-03-b1)"/><path d="M140 100 C 190 118, 262 120, 262 144" marker-end="url(#p11-03-b1)"/>
    </g>
    <text x="70" y="122" font-size="8.5" fill="#3553ff" text-anchor="end" font-weight="700">draw 1</text><text x="196" y="114" font-size="8.5" fill="#3553ff" font-weight="700">draw 2</text>

    <g fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.4">
      <rect x="45" y="150" width="26" height="32" rx="5"/><rect x="79" y="150" width="26" height="32" rx="5"/><rect x="113" y="150" width="26" height="32" rx="5"/><rect x="147" y="150" width="26" height="32" rx="5"/><rect x="181" y="150" width="26" height="32" rx="5"/><rect x="215" y="150" width="26" height="32" rx="5"/><rect x="249" y="150" width="26" height="32" rx="5"/><rect x="283" y="150" width="26" height="32" rx="5"/><rect x="317" y="150" width="26" height="32" rx="5"/><rect x="351" y="150" width="26" height="32" rx="5"/>
    </g>
    <rect x="113" y="150" width="26" height="32" rx="5" fill="none" stroke="#3553ff" stroke-width="2.4"/><rect x="249" y="150" width="26" height="32" rx="5" fill="none" stroke="#3553ff" stroke-width="2.4"/><rect x="249" y="150" width="26" height="32" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="none"/>
    <g fill="currentColor" font-size="11" text-anchor="middle" font-weight="700">
      <text x="58" y="171">3</text><text x="92" y="171">1</text><text x="126" y="171">4</text><text x="160" y="171">1</text><text x="194" y="171">5</text><text x="228" y="171">9</text><text x="262" y="171">2</text><text x="296" y="171">6</text><text x="330" y="171">5</text><text x="364" y="171">3</text>
    </g>
    <path d="M262 186 L 262 198" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p11-03-b2)"/><text x="278" y="203" font-size="10" font-weight="700" fill="#0fa07f">2 &lt; 4 — send here</text><text x="215" y="223" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.72">outstanding requests per backend; the balancer reads exactly 2 of them</text>

    <rect x="30" y="236" width="380" height="104" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor">
      <text x="46" y="256" font-size="10" font-weight="700">why it works, in one line</text><text x="46" y="276" font-size="9.5" opacity="0.92">One random pick lands on the worst backend with</text><text x="46" y="291" font-size="9.5" opacity="0.92">probability 1/n. Two picks land there only if BOTH</text><text x="46" y="306" font-size="9.5" opacity="0.92">are bad — probability (1/n)². Quadratically unlikely.</text>
      <text x="46" y="329" font-size="10" font-weight="700" fill="#0fa07f">max load: Θ(log n / log log n)  →  Θ(log log n / log 2)</text>
    </g>

    <text x="670" y="54" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">measured: mean max bin, n balls into n bins</text>
    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M500 382 L 848 382"/><path d="M500 382 L 500 132"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.45">
      <path d="M495 382 L 500 382"/><path d="M495 328.7 L 500 328.7"/><path d="M495 275.3 L 500 275.3"/><path d="M495 222 L 500 222"/><path d="M495 168.7 L 500 168.7"/><path d="M520 382 L 520 387"/><path d="M620 382 L 620 387"/><path d="M720 382 L 720 387"/><path d="M820 382 L 820 387"/>
    </g>

    <path d="M520 266.9 L 620 232.3 L 720 202.7 L 820 168.8" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/><path d="M520 309.6 L 620 300.0 L 720 297.3 L 820 286.7" fill="none" stroke="#0fa07f" stroke-width="2.8" stroke-linejoin="round"/><path d="M520 325.1 L 620 316.3 L 720 300.5 L 820 300.0" fill="none" stroke="#7c5cff" stroke-width="1.8" stroke-dasharray="5 4"/>
    <g fill="#d64545"><circle cx="520" cy="266.9" r="3.6"/><circle cx="620" cy="232.3" r="3.6"/><circle cx="720" cy="202.7" r="3.6"/><circle cx="820" cy="168.8" r="3.6"/></g>
    <g fill="#0fa07f"><circle cx="520" cy="309.6" r="3.6"/><circle cx="620" cy="300.0" r="3.6"/><circle cx="720" cy="297.3" r="3.6"/><circle cx="820" cy="286.7" r="3.6"/></g>

    <path d="M838 168.8 L 838 286.7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="3 3" opacity="0.75"/>
    <g fill="currentColor" font-size="9" opacity="0.85">
      <text x="844" y="222">4.42</text><text x="844" y="234">gap</text>
    </g>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="491" y="385">0</text><text x="491" y="331.7">2</text><text x="491" y="278.3">4</text><text x="491" y="225">6</text><text x="491" y="171.7">8</text>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.75">
      <text x="520" y="398">n=100</text><text x="620" y="398">1,000</text><text x="720" y="398">10,000</text><text x="820" y="398">100,000</text>
    </g>
    <text x="466" y="258" font-size="9.5" fill="currentColor" opacity="0.85" transform="rotate(-90 466 258)" text-anchor="middle">max load</text>

    <g font-size="10" font-weight="700">
      <text x="512" y="150" fill="#d64545">— d=1  uniform random</text><text x="512" y="166" fill="#0fa07f">— d=2  power of two choices</text><text x="686" y="333" fill="#7c5cff">- - d=3</text>
    </g>
    <text x="670" y="416" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">at n=100,000:  2nd sample &#8722;4.42 max load,  3rd sample &#8722;0.50 more</text>

    <text x="440" y="446" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">Random grows with the fleet. P2C barely moves — and needs no shared state to do it.</text><text x="440" y="466" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Mitzenmacher, The Power of Two Choices in Randomized Load Balancing, IEEE TPDS 12(10), 2001.</text>
  </g>
</svg>
```

The scaling changes category. With one random sample, maximum load is `Θ(log n / log log n)` and grows with your fleet. With two, it is

```text
max load  =  ln ln n / ln 2  +  Θ(1)
```

which is a **doubly** logarithmic function — for every practical n it is essentially a constant. Measured, over independent trials at four fleet sizes:

```text
        n  trials  d=1(random)  d=2(P2C)  d=3   ln n/ln ln n  ln ln n/ln2
       100     300         4.24      2.64  2.06           3.02         2.20
      1000     120         5.54      3.00  2.39           3.57         2.79
     10000      40         6.65      3.10  2.98           4.15         3.20
    100000      12         7.92      3.50  3.00           4.71         3.53
```

Read the two middle columns across. One sample: 4.24 → 7.92, climbing steadily with the fleet. Two samples: 2.64 → 3.50, almost flat over a thousand-fold increase in n. At n = 100,000 the second sample removes **4.42** of maximum load and the third removes **0.50** more — the first extra sample is worth about **nine times** the next one. That is the empirical reason every implementation you will meet uses exactly two and stops.

**The intuition** is worth having in words, because it makes the result feel inevitable instead of magical. A single random pick lands on the worst backend in the fleet with probability `1/n` — you have no defence against it at all. Two picks land there only if **both** draws are bad, and the probability of two independent bad draws is the square of one. Squaring a small number is what turns a linear-ish bound into a logarithmic one. The improvement does not come from having more information; it comes from having a *veto*.

And the practical consequence is the one that changed the industry:

- **No global state.** You never enumerate the fleet, never sort it, never maintain a shared minimum. You read two counters.
- **Stale information is fine.** The next section measures exactly how fine, and the answer is startling.
- **Trivially parallel.** Every balancer, thread and core does this independently with no coordination, so the decision cost does not grow with N or with the number of balancers.

The canonical reference is Mitzenmacher, *The Power of Two Choices in Randomized Load Balancing*, IEEE Transactions on Parallel and Distributed Systems 12(10), 2001, developed from the balanced-allocations analysis of Azar, Broder, Karlin and Upfal (SIAM J. Comput. 29(1), 1999).

There is one more property of P2C that the death-spiral table already showed and that is rarely stated: **it structurally bounds the damage from any single pathological backend.** A backend that always wins its comparison — because it is a black hole, or because its metrics are lying — can only win when it is one of the two sampled. That happens with probability `d/n`. With d = 2 and n = 8 that is **25%**, and the measurement came in at **23.0%** against least-connections' 50.3%. P2C is not error-aware and still needs the failure penalty. But it converts "unbounded" into "at most `d/n`" for free, and that guarantee holds against failure modes you have not thought of yet.

### The stale-state trap, and herding

Everything so far assumed one balancer with an accurate view. Neither assumption is true in production. You have many balancers — one per client process under client-side balancing, one per sidecar in a mesh, one per proxy instance — and they share a view of backend load that is refreshed periodically, not continuously.

Now re-read the instruction "send it to the least loaded backend" as what it actually is when a hundred processes execute it simultaneously from the same numbers: **every balancer computes the same argmin and they all pick the same server.** The least loaded backend instantly becomes the most loaded backend, everyone discovers this at the next refresh, and the herd moves as one to the next victim. This is **herding**, and it is why "just send to the least loaded" — the answer that sounds obviously correct — is the wrong answer at fleet scale.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 436" width="100%" style="max-width:840px" role="img" aria-label="Why least-loaded routing fails at fleet scale. On the left, four independent balancers all read the same load view that is 250 milliseconds old, all compute the same argmin, and all send their traffic to the same backend, which instantly becomes the most loaded one. On the right, the same four balancers running the power of two choices each draw their own random pair, so their picks are uncorrelated and spread across the fleet. The measured table below, from 22,582 requests across 32 identical backends, shows least-connections at a 93 millisecond p99 on a fresh view and 1,502 milliseconds on a 250 millisecond stale view with a maximum queue of 230, while the power of two choices goes from 96 to 162 milliseconds with a maximum queue of 21.">
  <defs>
    <marker id="p11-03-e1" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker><marker id="p11-03-e2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">"Send it to the least loaded" is a stampede instruction</text>

    <text x="215" y="52" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">least-connections · one shared view, 250 ms old</text><text x="665" y="52" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">power of two choices · the same stale view</text>

    <rect x="60" y="64" width="310" height="30" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.7"/><text x="215" y="84" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">one shared load report, read by all four</text><rect x="510" y="64" width="310" height="30" rx="7" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.7"/><text x="665" y="84" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">the identical report, equally stale</text>

    <g fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.6">
      <rect x="90" y="110" width="40" height="30" rx="6"/><rect x="160" y="110" width="40" height="30" rx="6"/><rect x="230" y="110" width="40" height="30" rx="6"/><rect x="300" y="110" width="40" height="30" rx="6"/><rect x="520" y="110" width="40" height="30" rx="6"/><rect x="590" y="110" width="40" height="30" rx="6"/><rect x="660" y="110" width="40" height="30" rx="6"/><rect x="730" y="110" width="40" height="30" rx="6"/>
    </g>
    <g fill="#3553ff" font-size="8.5" text-anchor="middle" font-weight="700">
      <text x="110" y="130">LB1</text><text x="180" y="130">LB2</text><text x="250" y="130">LB3</text><text x="320" y="130">LB4</text><text x="540" y="130">LB1</text><text x="610" y="130">LB2</text><text x="680" y="130">LB3</text><text x="750" y="130">LB4</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="1.8">
      <path d="M110 140 C 110 180, 200 172, 222 202" marker-end="url(#p11-03-e1)"/><path d="M180 140 C 180 178, 214 178, 224 202" marker-end="url(#p11-03-e1)"/><path d="M250 140 C 250 178, 236 178, 228 202" marker-end="url(#p11-03-e1)"/><path d="M320 140 C 320 180, 250 172, 231 202" marker-end="url(#p11-03-e1)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M540 140 C 540 172, 519 176, 519 202" marker-end="url(#p11-03-e2)"/><path d="M610 140 C 610 172, 587 176, 587 202" marker-end="url(#p11-03-e2)"/><path d="M680 140 C 680 172, 689 176, 689 202" marker-end="url(#p11-03-e2)"/><path d="M750 140 C 750 172, 757 176, 757 202" marker-end="url(#p11-03-e2)"/>
    </g>

    <g fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.4">
      <rect x="76" y="208" width="26" height="30" rx="5"/><rect x="110" y="208" width="26" height="30" rx="5"/><rect x="144" y="208" width="26" height="30" rx="5"/><rect x="178" y="208" width="26" height="30" rx="5"/><rect x="246" y="208" width="26" height="30" rx="5"/><rect x="280" y="208" width="26" height="30" rx="5"/><rect x="314" y="208" width="26" height="30" rx="5"/><rect x="506" y="208" width="26" height="30" rx="5"/><rect x="540" y="208" width="26" height="30" rx="5"/><rect x="574" y="208" width="26" height="30" rx="5"/><rect x="608" y="208" width="26" height="30" rx="5"/><rect x="642" y="208" width="26" height="30" rx="5"/><rect x="676" y="208" width="26" height="30" rx="5"/><rect x="710" y="208" width="26" height="30" rx="5"/><rect x="744" y="208" width="26" height="30" rx="5"/>
    </g>
    <rect x="212" y="208" width="26" height="30" rx="5" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="2.2"/><text x="225" y="228" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">230</text>

    <text x="215" y="258" text-anchor="middle" font-size="9.5" fill="#d64545" font-weight="700">same argmin, same instant — the least loaded is now the most loaded</text><text x="215" y="273" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.82">475 requests arrive between two refreshes and every one of them goes here</text><text x="665" y="258" text-anchor="middle" font-size="9.5" fill="#0fa07f" font-weight="700">each balancer draws its own pair — the picks are uncorrelated</text><text x="665" y="273" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.82">two balancers drawing the same pair out of 32 is rare by design</text>

    <rect x="34" y="288" width="812" height="98" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="50" y="306">22,582 REQUESTS · 32 IDENTICAL BACKENDS · ONLY STALENESS CHANGES</text><text x="500" y="306">p50</text><text x="576" y="306">p99</text><text x="666" y="306">p99.9</text><text x="760" y="306">MAX QUEUE</text>
    </g>
    <g fill="currentColor" font-size="10">
      <text x="50" y="326">least-connections, fresh view</text><text x="500" y="326">14.2 ms</text><text x="576" y="326">93.0 ms</text><text x="666" y="326">133.4 ms</text><text x="760" y="326">0</text><text x="50" y="345" font-weight="700" fill="#d64545">least-connections, 250 ms stale</text><text x="500" y="345">77.4 ms</text><text x="576" y="345" font-weight="700" fill="#d64545">1,501.9 ms</text><text x="666" y="345" fill="#d64545">2,044.6 ms</text><text x="760" y="345" font-weight="700" fill="#d64545">230</text><text x="50" y="364">power of two choices, fresh view</text><text x="500" y="364">15.9 ms</text><text x="576" y="364">96.0 ms</text><text x="666" y="364">133.9 ms</text><text x="760" y="364">3</text><text x="50" y="383" font-weight="700" fill="#0fa07f">power of two choices, 250 ms stale</text><text x="500" y="383">29.1 ms</text><text x="576" y="383" font-weight="700" fill="#0fa07f">162.2 ms</text><text x="666" y="383" fill="#0fa07f">246.6 ms</text><text x="760" y="383" font-weight="700" fill="#0fa07f">21</text>
    </g>
    <text x="440" y="408" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">Identical policies on fresh state. On stale state, exact least-loaded is 9.3x worse at p99.</text><text x="440" y="428" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">The busiest backend still took only 3.89% of traffic. Herding is an instant, not a total — averages will never show it.</text>
  </g>
</svg>
```

The measurement isolates it cleanly: 32 identical backends, no slow member, no failures, the same 22,582-request stream. The only thing that changes is whether the balancer's load view is current or 250 ms old, during which **475 requests arrive**.

```text
    policy                  p50      p99     p999   maxQ   busiest backend
    least_conn            14.2ms   93.0ms   133.4ms     0      3.32%  (even = 3.12%)
    least_conn_stale      77.4ms 1501.9ms  2044.6ms   230      3.89%  (even = 3.12%)
    p2c                   15.9ms   96.0ms   133.9ms     3      3.40%  (even = 3.12%)
    p2c_stale             29.1ms  162.2ms   246.6ms    21      3.29%  (even = 3.12%)
```

On fresh state the two policies are indistinguishable — 93.0 ms versus 96.0 ms at p99, and exact least-connections is marginally ahead, as theory says it should be. On stale state, least-connections degrades to a **1,502 ms p99 with a 230-deep queue**, while P2C degrades to **162 ms with a 21-deep queue**. Same staleness, same fleet, **9.3× the difference**, produced entirely by the fact that two balancers drawing independent random pairs out of 32 backends rarely draw the same pair.

Now look at the last column, because it is the reason this is hard to catch. The busiest backend under stale least-connections took **3.89%** of the traffic against an even share of 3.12%. That is a 25% overshoot on a per-day graph — utterly unremarkable, the kind of variance nobody opens a ticket about. **Herding is an instant, not a total.** It is 475 requests arriving at one server inside one refresh interval, and then it is over, and then it happens again somewhere else. Every averaged metric you own will hide it, and your p99 will not.

The rule that follows: **randomness is not a compromise in a load-balancing algorithm; it is a decorrelation mechanism.** It exists to stop independent actors from making the same decision at the same instant. Deterministically-optimal choices made from shared state are how a fleet synchronises itself into a stampede — the same mechanism that makes un-jittered retries and un-jittered health-check intervals dangerous ([Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) measured that version).

### Consistent hashing and bounded loads

Everything above assumes any backend can serve any request. Sometimes that is false: you want the same key on the same backend, because that backend has the cache entry, holds the session, owns the write lock, or has the shard open. That is **affinity**, and it needs a different kind of algorithm — one whose input is the request's key rather than the fleet's load.

`hash(key) % N` fails immediately: change N and almost every key moves. **Consistent hashing** (Karger, Lehman, Leighton, Panigrahy, Levine & Lewin, *Consistent Hashing and Random Trees*, STOC 1997) places both keys and backends on one circular hash space, and a key belongs to the first backend clockwise from it. Remove a backend and only *its* arc is reassigned — everything else stays put. Phase 4 covers the ring as a **data placement** mechanism ([Key-Value Stores](../../04-nosql-and-data-modeling/02-key-value-stores/)); the angle here is routing *requests*, so what follows is only what changes when the thing on the ring is traffic.

Two things change, and the measurement separates them. Eighty thousand requests, 20,000 keys, Zipf-distributed popularity, eight backends:

```text
    ring                        max/mean  min/mean  survives removal  on primary
    plain,        1 vnode         3.311     0.031          100.00%     100.00%
    plain,   150 vnodes           1.407     0.769          100.00%     100.00%
    bounded, 150 vnodes, 1.25x    1.250     0.778           98.03%      98.01%
```

**One node per backend is unusable** — 3.31× the mean on one backend and 0.03× on another, because eight random points on a circle do not cut it into eight equal arcs. Giving each backend 150 **virtual nodes** — 150 positions on the ring instead of one — averages the arcs out and takes the imbalance to 1.41×. That is the standard fix and it works on the problem it addresses.

But look at what 150 vnodes did *not* fix: 1.407 is still 41% above the mean. Virtual nodes solve **arc skew**; they do nothing about **traffic skew**. In this key space the single hottest key is **9.6% of all requests** — most of a backend's entire fair share, in one key — and a plain ring has no choice but to send all of it to one place. Real key spaces are Zipfian. One tenant is enormous, one product page is on the front of Reddit, one session belongs to a scraper.

**Consistent hashing with bounded loads** (Mirrokni, Thorup & Zadimoghaddam, *Consistent Hashing with Bounded Loads*, SIAM J. Comput. 47(3), 2018) fixes this with one rule: cap every backend at `(1+ε)` times the current average, and if the key's node is full, walk clockwise to the next one that is not. The measured result is exactly what the theorem promises — **1.250, the cap, by construction** — and the cost is stated in the last two columns: **98.03%** of requests survive a backend removal on the same node instead of 100%, and **98.01%** land on their primary node rather than an overflow node. You trade about 2% of your cache hit rate for a hard ceiling on imbalance. Take that trade; a 2% miss-rate increase is a rounding error next to a backend at 1.4× and climbing.

Choose ε honestly. Small ε (1.05) is tight balance and heavy overflow; large ε (1.5) is loose balance and almost no overflow. And the whole family only makes sense when you genuinely need affinity, because you are giving up load awareness to get it.

### Putting it together

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="A decision table mapping the load signal a balancer can actually see to the algorithm it implies, that algorithm's failure mode, and the figure measured in this lesson. Six rows: no signal at all gives random with a maximum load of log n over log log n; a local counter gives round-robin which equalises count and not load; your own outstanding requests give least-connections which lags and rewards fast failure and herds on a stale shared view; observed latency gives peak EWMA which treats an instant error as the fastest backend; two random samples give the power of two choices which caps any single bad backend at d over n; and the request key gives consistent hashing which needs a one plus epsilon load cap to survive traffic skew.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Every algorithm is an answer to "what do I know, and how stale is it?"</text><text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">pick the row whose left-hand column matches the signal you can actually get</text>

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.62">
      <text x="32" y="66">THE SIGNAL YOU HAVE</text><text x="214" y="66">THE ALGORITHM</text><text x="396" y="66">ITS FAILURE MODE — SAY IT OUT LOUD</text><text x="666" y="66">MEASURED IN THIS LESSON</text>
    </g>
    <path d="M22 72 L 862 72" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.22">
      <path d="M22 142 L 862 142"/><path d="M22 208 L 862 208"/><path d="M22 274 L 862 274"/><path d="M22 340 L 862 340"/><path d="M22 406 L 862 406"/>
    </g>
    <path d="M22 472 L 862 472" fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.45"/>

    <g stroke-width="4" stroke-linecap="round">
      <path d="M24 82 L 24 134" stroke="#7f7f7f"/><path d="M24 148 L 24 200" stroke="#d64545"/><path d="M24 214 L 24 266" stroke="#e0930f"/><path d="M24 280 L 24 332" stroke="#e0930f"/>
      <path d="M24 346 L 24 398" stroke="#0fa07f"/><path d="M24 412 L 24 464" stroke="#7c5cff"/>
    </g>

    <g fill="currentColor" font-size="8.8" opacity="0.92">
      <text x="32" y="96">nothing at all —</text><text x="32" y="110">stateless, no shared</text><text x="32" y="124">state, no coordination</text><text x="32" y="162">a local counter</text><text x="32" y="176">and static weights</text><text x="32" y="190">you configured once</text><text x="32" y="228">outstanding requests</text><text x="32" y="242">you dispatched</text><text x="32" y="256">yourself and can count</text><text x="32" y="294">observed response</text><text x="32" y="308">latency, per backend</text><text x="32" y="322">and per request</text>
      <text x="32" y="360">two random samples</text><text x="32" y="374">of either signal —</text><text x="32" y="388">and nothing else</text><text x="32" y="426">the request's KEY:</text><text x="32" y="440">tenant, session id,</text><text x="32" y="454">cache URL, shard</text>
    </g>

    <g font-size="10" font-weight="700">
      <text x="214" y="96" fill="#7f7f7f">random</text><text x="214" y="162" fill="#d64545">round-robin</text><text x="214" y="228" fill="#e0930f">least-connections</text><text x="214" y="294" fill="#e0930f">peak EWMA</text>
      <text x="214" y="360" fill="#0fa07f">power of two choices</text><text x="214" y="426" fill="#7c5cff">consistent hashing</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.8">
      <text x="214" y="110">nginx: no built-in;</text><text x="214" y="124">HAProxy: random</text><text x="214" y="176">weighted RR, and</text><text x="214" y="190">nginx's smooth WRR</text><text x="214" y="242">"least outstanding</text><text x="214" y="256">requests" / least_conn</text><text x="214" y="308">a decaying MAX, not</text><text x="214" y="322">a mean — Finagle's</text>
      <text x="214" y="374">Envoy LEAST_REQUEST</text><text x="214" y="388">with choice_count = 2</text><text x="214" y="440">ring + virtual nodes,</text><text x="214" y="454">MAGLEV, RING_HASH</text>
    </g>

    <g fill="currentColor" font-size="8.8" opacity="0.92">
      <text x="396" y="96">max load ~ log n / log log n. One backend</text><text x="396" y="110">draws 6.5x the mean while 36.8% of the</text><text x="396" y="124">fleet is handed nothing at all.</text><text x="396" y="162">Equalises request COUNT, not load. The one</text><text x="396" y="176">policy guaranteed to hand a struggling</text><text x="396" y="190">backend exactly as much work as a healthy one.</text><text x="396" y="228">A LAGGING signal, and it rewards failing fast.</text><text x="396" y="242">On one shared, stale view every balancer</text><text x="396" y="256">computes the same argmin and stampedes it.</text><text x="396" y="294">An instant 500 is the lowest latency in the</text><text x="396" y="308">fleet. Worthless unless a failure is recorded</text><text x="396" y="322">as a very slow sample.</text>
      <text x="396" y="360">Still needs error awareness. But no global</text><text x="396" y="374">argmin exists, so ANY single bad backend is</text><text x="396" y="388">structurally capped at d/n of your traffic.</text><text x="396" y="426">Virtual nodes fix ARC skew, not TRAFFIC skew:</text><text x="396" y="440">a hot key has nowhere else to go until you</text><text x="396" y="454">add a (1+eps) load cap with overflow.</text>
    </g>

    <g font-size="8.5" font-weight="700">
      <text x="666" y="96" fill="#7f7f7f">6.50x the mean bin</text><text x="666" y="110" fill="currentColor" opacity="0.75">at n = 10,000</text><text x="666" y="162" fill="#d64545">24.1% work spread on</text><text x="666" y="176" fill="#d64545">identical counts; p99 900 ms;</text><text x="666" y="190" fill="currentColor" opacity="0.75">31.1% queued while idle</text><text x="666" y="228" fill="#e0930f">50.3% into a black hole;</text><text x="666" y="242" fill="#e0930f">p99 93 ms -&gt; 1,502 ms</text><text x="666" y="256" fill="currentColor" opacity="0.75">on a 250 ms stale view</text><text x="666" y="294" fill="#e0930f">90.6% into the black hole;</text><text x="666" y="308" fill="#0fa07f">1.1% once a failure counts</text><text x="666" y="322" fill="currentColor" opacity="0.75">as a 2,000 ms sample</text>
      <text x="666" y="360" fill="#0fa07f">max load 3.50 vs 7.92</text><text x="666" y="374" fill="#0fa07f">at n=100k; 23.0% capped;</text><text x="666" y="388" fill="currentColor" opacity="0.75">p99 162 ms on a stale view</text><text x="666" y="426" fill="#7c5cff">1.41x mean, plain ring;</text><text x="666" y="440" fill="#7c5cff">1.25x bounded, keeping</text><text x="666" y="454" fill="currentColor" opacity="0.75">98.0% of key affinity</text>
    </g>

    <text x="440" y="494" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">Default to the green row. Use the purple one only when you genuinely need the same key on the same backend.</text>
  </g>
</svg>
```

## Build It

[`code/load_balancing.py`](code/load_balancing.py) is six numbered arguments. Standard library only, every RNG seeded, about seven seconds. One discrete-event simulator drives sections 2, 3 and 5, and **every policy sees the identical arrival stream and the identical per-request work**, so any difference in the output was produced by the routing decision and nothing else.

The policy is a single function, and it is short on purpose — the entire lesson is a handful of expressions:

```python
if policy == "least_conn":
    return min(cl, key=lambda i: (inflight[i], rng.random()))
if policy in ("peak_ewma", "peak_ewma_nofail"):
    return min(cl, key=lambda i: (decayed(i, t) * (inflight[i] + 1),
                                  rng.random()))
if len(cl) == 1:
    return cl[0]
a = cl[rng.randrange(len(cl))]
b = cl[rng.randrange(len(cl))]
while b == a:
    b = cl[rng.randrange(len(cl))]
if policy == "p2c":
    return a if inflight[a] <= inflight[b] else b
```

`min(...)` over the whole fleet versus two `randrange` calls is the entire difference between the row that herds and the row that does not. Note the `rng.random()` tie-breaker inside `least_conn`: without it, ties resolve to the lowest index and the first backend in the list gets a systematic advantage — a real bug that has shipped in real balancers.

**Peak EWMA** is five lines, and the asymmetry is the third one:

```python
def observe(i: int, t: float, obs: float) -> None:
    prev = decayed(i, t)
    alpha = 1.0 - math.exp(-(t - stamp[i]) / tau)
    ewma[i] = obs if obs > prev else prev * (1.0 - alpha) + obs * alpha
    stamp[i] = t
```

`obs if obs > prev` is the peak: a worse sample is adopted immediately and in full, a better one only shifts the average by `alpha`. Deriving `alpha` from elapsed time rather than fixing it is what makes the decay window a property of *seconds* rather than of *request rate*, so the same τ behaves the same way at 50 req/s and 5,000 req/s.

**The stale view** is the herding experiment, and it is four lines. `view` is what the balancer believes; `inflight` is the truth:

```python
if policy in ("least_conn_stale", "p2c_stale") and t - last_refresh >= stale:
    view[:] = inflight
    last_refresh = t
```

**Consistent hashing with bounded loads** is the ring walk plus one comparison. The cap is recomputed as requests arrive so that it tracks the current average rather than a number you configured:

```python
cap = math.ceil((1.0 + eps) * i / ring.n)
b = None
for cand in ring.walk(kh):
    if load[cand] < cap:
        b = cand
        break
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/03-load-balancing-algorithms/code/load_balancing.py
```

```console
== 1 · BALLS IN BINS: WHAT AN 'EVEN' DISTRIBUTION ACTUALLY LOOKS LIKE ==
  n requests thrown at n backends, no coordination; max bin over trials
       n   trials   RR max   random max   ln n / ln ln n   empty bins
      16      400        1         3.04             2.72       35.1%
     100      300        1         4.24             3.02       36.8%
    1000      120        1         5.53             3.57       36.7%
   10000       30        1         6.50             4.15       36.8%
  round-robin's max is exactly 1: it is PERFECT by request count.
  uniform random puts 6.5x the average on some backend at n=10000
  while leaving 36.8% of them with nothing. That gap is the price of
  statelessness, and section 4 buys almost all of it back with ONE
  extra random sample.  (ln n / ln ln n is asymptotic and under-reads
   at these n; the measured column is the one to trust.)

  the sequence round-robin emits, weights A=5 B=1 C=1:
    naive weighted RR   AAAAABCAAAAABC   <- A gets a 5-deep burst
    smooth weighted RR  AABACAAAABACAA   <- same 5:1:1 ratio, spread out
  identical ratios over 7 picks; only one of them keeps A's queue flat.

== 2 · EQUAL COUNTS, UNEQUAL LOAD — THE LIE, MEASURED ==
  8 identical backends x 2 workers; 20174 requests over 40s (500/s offered)
  work per request: 70% 3ms / 25% 20ms / 4% 120ms / 1% 900ms (measured mean 20.1 ms)

  ROUND-ROBIN, per backend:
    backend   requests    share   900ms reqs   work(s)    share    busy%   maxQ
          0       2522    12.5%           26      52.5    12.9%    64.3%     57
          1       2522    12.5%           31      56.5    13.9%    69.2%     59
          2       2522    12.5%           22      50.9    12.5%    62.3%     41
          3       2522    12.5%           26      52.4    12.9%    64.2%     61
          4       2522    12.5%           24      51.8    12.7%    63.4%     93
          5       2522    12.5%           19      45.5    11.2%    55.7%     42
          6       2521    12.5%           25      51.1    12.6%    62.5%     56
          7       2521    12.5%           14      45.5    11.2%    55.7%     38
    request count spread: 1 requests (0.04% between the busiest and quietest)
    actual WORK spread:   11.0 s (24.14%) — same fleet, same second
    busy time: 55.7% on the quietest backend, 69.2% on the busiest
    the mechanism: the 900 ms tail is 1% of requests and 41% of the work, and round-robin
    dealt 14-31 of them per backend because it cannot see request size.

  the same stream, three policies:
    policy            p50      p99     p999    maxQ   queued while another backend was IDLE
    rr               20.0ms  900.0ms  1303.8ms      93       6271 = 31.1%
    p2c               3.0ms  823.4ms   911.8ms      14       2440 = 12.1%
    least_conn        3.0ms  587.5ms   900.0ms       5          0 =  0.0%
    round-robin made 6271 of 20174 requests wait in a queue while another backend sat completely idle.
    it had nowhere else to go: its turn had come, so it dealt the card.

== 3 · ONE BACKEND IS 3x SLOWER AND NOTHING IS 'DOWN' (GREY FAILURE) ==
  backend 0 runs at 0.33x speed (60 ms where the others take 20 ms)
  fleet capacity 733 req/s (7 x 100 + 1 x 33); offered 245 req/s = 33% of the fleet
  round-robin hands backend 0 31 req/s against its 33.3 req/s of capacity -> rho = 0.92
  every backend gets offered/n, so the SLOWEST one sets the ceiling:
    round-robin ceiling = 8 x 33.3 = 267 req/s out of 733 req/s of real capacity -> 64% unreachable
    a 9th healthy instance moves the ceiling to 300 req/s while adding 100 req/s of capacity — the unreachable share grows to 64%.

    policy                  p50      p99     p999   maxQ  b0 share  b0 busy%
    rr                    16.8ms  537.7ms   723.9ms    25    12.5%     87.9%
    random                19.0ms  860.0ms  1315.3ms    38    12.8%     92.0%
    least_conn            14.7ms  120.9ms   257.3ms     0     6.4%     44.0%
    least_conn_stale      19.2ms  180.6ms   345.1ms    11     7.2%     53.5%
    peak_ewma             17.0ms  239.0ms   691.7ms    26     6.8%     50.4%
    p2c                   15.1ms  136.3ms   266.8ms     2     7.9%     56.1%
    p2c_stale             17.6ms  179.5ms   331.0ms     9     7.9%     58.7%
    p2c_ewma              16.5ms  147.9ms   280.2ms    10     7.0%     49.5%
    under round-robin backend 0 was 87.9% busy while the other seven averaged 30.4%;
    p50 16.8 ms but p99 538 ms — 32x its own median.
    round-robin p99 538 ms; least-conn 121 ms; P2C 136 ms (3.9x better)
    least-connections and P2C both find the slow backend without being
    told it is slow: they measure load, and round-robin counts arrivals.

  fleet scale — 32 identical backends, every balancer reading ONE shared
  load view refreshed every 250 ms (a load report, not a local counter).
  22582 requests at 1900/s; 475 arrive between two refreshes
    policy                  p50      p99     p999   maxQ   busiest backend
    least_conn            14.2ms   93.0ms   133.4ms     0      3.32%  (even = 3.12%)
    least_conn_stale      77.4ms 1501.9ms  2044.6ms   230      3.89%  (even = 3.12%)
    p2c                   15.9ms   96.0ms   133.9ms     3      3.40%  (even = 3.12%)
    p2c_stale             29.1ms  162.2ms   246.6ms    21      3.29%  (even = 3.12%)
    on a stale view least-connections is 9.3x worse at p99 than
    P2C (1502 ms vs 162 ms) — every balancer computed the same
    argmin and stampeded the same backend. P2C's random pair breaks the
    correlation: two balancers rarely draw the same pair.

== 4 · THE POWER OF TWO CHOICES, MEASURED ==
  n balls into n bins; mean of the maximum bin over trials
        n  trials  d=1(random)  d=2(P2C)  d=3   ln n/ln ln n  ln ln n/ln2
       100     300         4.24      2.64  2.06           3.02         2.20
      1000     120         5.54      3.00  2.39           3.57         2.79
     10000      40         6.65      3.10  2.98           4.15         3.20
    100000      12         7.92      3.50  3.00           4.71         3.53
  d=1 grows with n; d=2 barely moves. At n=100000 the SECOND sample
  removes 4.42 of maximum load and the THIRD removes 0.50 more —
  the first extra sample is worth ~9x the next one, which is exactly
  why every service mesh ships choice_count = 2 and stops there.

== 5 · THE DEATH SPIRAL: FAILING FAST IS REWARDED BY EVERY LOAD SIGNAL ==
  backend 0 returns HTTP 500 in 0.5 ms without doing any work.
  19285 requests, 8 backends. A blind policy sends 1/8 = 12.5% into it.

    policy                          traffic into the black hole   errors
    round_robin                      12.5%  #####                                      2411
    least_conn                       50.3%  ####################                       9701
    peak_ewma (latency only)         90.6%  ####################################      17465
    p2c (outstanding)                23.0%  #########                                  4441
    peak_ewma + failure penalty       1.1%                                              209
    p2c_ewma + penalty                1.6%  #                                           317
    p2c_ewma + penalty + ejection     0.5%                                              100
    least-connections sent 50.3% of ALL traffic into a backend that answered
    nothing, and peak-EWMA on latency alone sent 90.6%. Neither is a bug:
    0 outstanding requests and 0.5 ms of latency genuinely ARE the best
    scores in the fleet. The signal is right; the interpretation is wrong.
    P2C caps the damage at d/n = 2/8 = 25% (measured 23.0%) because a bad backend can only
    win when it is one of the two sampled — no global argmin exists.
    counting a failure as a 2000 ms sample: 1.1%. Adding passive ejection: 0.5%.

== 6 · CONSISTENT HASHING, AND WHY IT NEEDS A BOUND ==
  80000 requests over 20000 keys, Zipf s=1.0 (the hottest key is 9.6% of traffic)
  8 backends, 150 virtual nodes each, eps = 0.25

    ring                        max/mean  min/mean  survives removal  on primary
    plain,        1 vnode         3.311     0.031          100.00%     100.00%
    plain,   150 vnodes           1.407     0.769          100.00%     100.00%
    bounded, 150 vnodes, 1.25x    1.250     0.778           98.03%      98.01%
    one virtual node per backend puts a random arc of the ring on each
    server, and random arcs are not equal — that is why vnodes exist.
    150 vnodes fixes the ARC problem but not the TRAFFIC problem: the
    hottest key alone is 9.6% of requests, and the ring has no
    choice but to send all of it to one backend.
    the bound caps every backend at 1.25x the mean by construction and
    pays for it in affinity, which is the trade stated honestly.

  (total wall time 7.5 s)
```

Four things in that output are arguments rather than demonstrations.

**Section 2 is the lesson's title, measured** — and note that p50 falls from **20.0 ms to 3.0 ms** the moment the policy looks at load. Under round-robin the *median* request is already waiting, because the median request is a 3 ms cache hit stuck behind a 900 ms tenant export.

**Section 3 shows least-connections and P2C solving a problem nobody told them about.** No health check reports backend 0; no configuration mentions it. Both policies work out from their own outstanding counts that it should get 6-8% instead of 12.5%, and p99 drops 4×. Load-aware routing degrades gracefully against failures you did not anticipate, which is the only kind you get.

**Section 3's second table is the one for design reviews.** On fresh state exact least-connections beats P2C (93.0 ms vs 96.0 ms) — of course it does, it has more information. On 250 ms-stale state it is **9.3× worse**. Being optimal on data that is 475 requests old is not being optimal.

**Section 5 is the one that will save you an outage.** The important row is 90.6%, not 50.3%: that is the *sophisticated* policy, the one you deploy feeling clever, performing worse than doing nothing. Every health proxy makes a broken server look excellent.

## Use It

You will almost never write this code. You will choose a string in a config file, and the whole point of the sections above is to know which string, and what it does when something breaks.

**Envoy** is the reference implementation of everything in this lesson. Its `LEAST_REQUEST` policy is not what most people assume: for hosts of equal weight it does **not** scan the fleet — it samples `choice_count` hosts at random and picks the one with fewest active requests, and **`choice_count` defaults to 2.** Envoy's "least request" *is* the power of two choices, and that surprises people who have been drawing it as a global minimum on whiteboards for years.

```yaml
clusters:
  - name: checkout
    lb_policy: LEAST_REQUEST            # P2C by default — this is your general-purpose answer
    least_request_lb_config:
      choice_count: 2                   # the default; 1 makes it plain random
    common_lb_config:
      healthy_panic_threshold: { value: 50 }   # below 50% healthy, ignore health and use all
    outlier_detection:                  # the failure signal least-request does NOT have
      consecutive_5xx: 5
      interval: 10s
      base_ejection_time: 30s
      max_ejection_percent: 10          # never eject the fleet and cause the outage yourself
```

The other policies are `ROUND_ROBIN` (weighted, smooth), `RANDOM`, `RING_HASH` and `MAGLEV`. `outlier_detection` is not optional decoration next to a load-aware policy — it is the 90.6%-to-1.1% fix from section 5, and Lesson 4 covers it properly. `healthy_panic_threshold` is worth reading twice: when too much of the fleet is unhealthy, Envoy deliberately stops honouring health status and load-balances across everything, on the theory that a fleet you believe is 90% dead is more likely a broken health check than a dead fleet.

For affinity, Envoy exposes bounded loads directly:

```yaml
    lb_policy: RING_HASH
    ring_hash_lb_config: { minimum_ring_size: 1024 }   # virtual nodes, effectively
    common_lb_config:
      consistent_hashing_lb_config:
        hash_balance_factor: 125        # cap each host at 1.25x the mean, then overflow
```

`hash_balance_factor` is section 6's `(1+ε)` expressed as a percentage. Leave it unset and you get the plain ring, with the 1.41× measured above waiting for your first hot tenant.

**nginx** defaults to smooth weighted round-robin and gives you the rest as directives. It also, since 1.15.1, ships P2C under a name nobody guesses:

```text
upstream checkout {
    least_conn;                       # least outstanding requests
    server a.internal:8080 max_fails=3 fail_timeout=15s;
    server b.internal:8080;
}

upstream sessions {
    hash $cookie_session consistent;  # consistent hashing (a plain ring — no bound)
    server a.internal:8080;
}

upstream fleet {
    random two least_conn;            # THIS is power of two choices
    server a.internal:8080;
}
```

`random two least_conn` draws two servers at random and picks the one with fewer active connections — section 4, in three words. Note that open-source nginx has no latency-aware policy; `least_time` is nginx Plus only. Note also that `hash ... consistent` has no load bound, so a Zipfian key space will hand you the plain-ring row from section 6.

**HAProxy**: `balance roundrobin` is the default, `balance leastconn` measures load, and `balance random(2)` is P2C explicitly parameterised — the `2` is the `d` from this lesson. `balance first` is the deliberately unbalanced one: fill the first server to its `maxconn` before touching the second, which is what you want when you are paying per instance and want to scale down, and exactly what you do not want for latency. `balance uri` with `hash-type consistent` gives you the ring.

**gRPC** ships `pick_first` as the **default**, and it is a trap worth naming. `pick_first` opens one connection to one backend and sends everything there until it breaks. With a long-lived HTTP/2 connection and no proxy in the path, a fleet of gRPC clients using the default will pin themselves to whichever backends they happened to resolve, and no amount of balancing at layer 4 will fix it because there is nothing to balance — the connection was established once ([Transport Layer: TCP vs UDP](../../01-networking-and-protocols/05-transport-layer-tcp-vs-udp/) covers why a persistent connection defeats connection-level balancing). Set `round_robin` at minimum; use xDS-driven `weighted_round_robin` with backend-reported utilization if you have a control plane.

**Finagle** (Twitter/X's RPC library) is where peak EWMA comes from, exposed as `P2CPeakEwma` — the two ideas from this lesson composed: sample two, score them by decaying-maximum latency times in-flight count. Its default balancer is `P2CLeastLoaded`. **Linux IPVS** at layer 4 gives you `rr`, `wrr`, `lc` (least connection), `wlc` and `sh` (source hashing). **AWS ALB** defaults to round-robin per target group and supports `least_outstanding_requests` as a target-group attribute; it is one checkbox and it is usually the right one.

**Maglev** (Eisenbud et al., *Maglev: A Fast and Reliable Software Network Load Balancer*, NSDI 2016) deserves its own note. It is consistent hashing rebuilt for a specific constraint: hundreds of balancer machines that never talk to each other must independently agree on which backend a packet belongs to, so that any machine can handle any packet without breaking an in-flight connection. Maglev builds a lookup table by permutation rather than walking a ring, which gives it near-perfect distribution *and* minimal disruption when the backend set changes, at O(1) lookup. Envoy's `MAGLEV` is this algorithm; prefer it over `RING_HASH` when you need hashing, since it disrupts fewer keys for the same memory.

**What to actually pick.** Two rules cover almost everything:

1. **Least-request with `choice_count: 2` for general traffic.** It measures load rather than counting arrivals, it needs no global state, it degrades gracefully under stale information, and it bounds any single pathological backend to `d/n`. Pair it with outlier detection, always — the algorithm has no error signal of its own and section 5 is what that costs.
2. **Ring hash or Maglev only when you genuinely need the same key on the same backend**, and can name what breaks without it: a cache hit rate that collapses, a session that lives in local memory, a shard lock. Affinity costs you load awareness — a hashing policy cannot route around a slow backend, because the key says where to go. If you take it, take the load bound with it (`hash_balance_factor`), and expect to give up a couple of percent of affinity for it.

Everything above is the *algorithm* layer. Running, deploying and observing the proxies themselves — ingress, sidecars, config reload, connection draining — is [Reverse Proxies, Load Balancers & Ingress](../../10-infrastructure-and-deployment/09-reverse-proxies-and-load-balancers/) in Phase 10.

## Think about it

1. Section 3 measured least-connections beating P2C on fresh state (120.9 ms vs 136.3 ms at p99) and losing badly on stale state (1,502 ms vs 162 ms with 32 backends). Where exactly is the crossover — what property of *your* system decides which of those two rows you are living in? What would you measure to find out, without breaking production to do it?
2. P2C bounds a single pathological backend at `d/n` of traffic. Your fleet is 6 instances and you deploy a change that makes 3 of them return errors instantly. Work out what share of traffic the broken half receives under P2C, and say whether the `d/n` bound helps you at all here. What does that tell you about which failures randomised sampling protects against?
3. Peak EWMA reacts instantly upward and slowly downward. Design the opposite bias — fast to recover, slow to condemn — and describe the specific production scenario where your version is better. Then say why nobody ships it as the default.
4. You add `hash $cookie_session consistent` to fix a cache hit rate, and three weeks later one backend is at 90% CPU while the rest are at 25%. Trace the two distinct causes this could have (section 6 measured both) and say which measurement distinguishes them.
5. Your balancer sends 12.5% of traffic to each of 8 backends and one of them has begun failing 40% of requests in 3 ms. Compute the share it receives under least-connections, then design the smallest change to the *signal* — not the algorithm — that fixes it. Why is changing the signal usually safer than changing the algorithm?

## Key takeaways

- **Round-robin equalises request count, and request count is not load.** Measured over 20,174 requests on 8 identical backends: request counts differed by **one request (0.04%)** while actual work differed by **24.14%**, and **31.1% of all requests were queued behind something while another backend sat completely idle** — zero under least-connections. A perfectly flat request-rate graph is not evidence that routing is fine; it is evidence that your balancer is not measuring anything.
- **Round-robin is the one policy guaranteed to overload whoever is already struggling.** One backend at 3× the service time received its full 12.5% and ran at **87.9% busy while the other seven averaged 30.4%**, producing a **538 ms p99 against a 16.8 ms p50 — 32×** — on a fleet at 33% capacity. The same arithmetic caps a 733 req/s fleet at **267 req/s — 64% of it unreachable** — because every member gets `offered/n` and the slowest member sets the ceiling.
- **The power of two choices is the result to memorise.** Sampling two backends at random and taking the less loaded cut maximum load from **7.92 to 3.50 at n = 100,000** and turned `Θ(log n / log log n)` into `Θ(log log n / log 2)`. A third sample buys only **0.50** more — the second sample is worth about **9×** the third, which is why every implementation stops at two. It needs no global state, works on stale data, and is trivially parallel (Mitzenmacher, IEEE TPDS 12(10), 2001).
- **"Send to the least loaded" is a stampede instruction at fleet scale.** With 32 backends and one shared load view refreshed every 250 ms — 475 requests per interval — exact least-connections went from a **93 ms p99 to 1,502 ms with a 230-deep queue**, while P2C went from 96 ms to **162 ms**, a **9.3×** difference. The busiest backend still took only 3.89% of the day's traffic: **herding is an instant, not a total**, and every averaged metric you own will hide it.
- **Every load signal rewards a server that fails fast.** A backend returning `500` in 0.5 ms drew **50.3% of all traffic under least-connections and 90.6% under latency-only peak EWMA** — worse than blind round-robin's 12.5%. Neither is a bug: zero outstanding requests really is the lowest load. Score a failure as a very slow sample (**1.1%**) and add passive ejection (**0.5%**).
- **EWMA arithmetic, once:** `alpha = 1 − e^(−dt/τ)`, `value = (1−alpha)·value + alpha·obs`, and **peak** EWMA replaces `value` outright when the new sample is worse. Fast up, slow down — because mistaking a healthy backend for a slow one costs spare capacity, and mistaking a slow one for healthy costs a queue.
- **Virtual nodes fix arc skew; only a load bound fixes traffic skew.** One vnode per backend gave **3.31×** the mean; 150 vnodes gave 1.41×; and 1.41× is still what a Zipfian key space does when the hottest single key is **9.6% of requests**. A `(1+ε)` cap with clockwise overflow delivered exactly **1.25×** and cost **2%** of key affinity (Mirrokni, Thorup & Zadimoghaddam, SIAM J. Comput. 47(3), 2018).
- **Default to least-request with `choice_count: 2`, and always pair it with outlier detection.** Reach for ring hash or Maglev only when you can name what breaks without affinity — and accept that a hashing policy cannot route around a slow backend, because the key already decided.

Next: [Layer 4 vs Layer 7, Health Checks & Outlier Ejection](../04-l4-l7-health-checks-and-ejection/) — where in the stack the balancing decision happens, why a health check that returns `200 OK` in four milliseconds told you nothing about the backend in this lesson's incident, and how to eject a bad host without ejecting the fleet.
