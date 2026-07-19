# SLIs, SLOs & Error Budgets

> "How reliable should we be?" is the most expensive unanswered question in engineering. Left unanswered, every incident becomes a values argument and every risky deploy is decided by whoever talks loudest. Answered — as a number, agreed in advance — it becomes arithmetic: here is the target, here is how much badness we can afford this month, here is how much is left. This lesson turns reliability from an opinion into a budget you can spend.

**Type:** Learn
**Languages:** —
**Prerequisites:** [Metrics: Counters, Gauges & Histograms from Scratch](../05-metrics-from-scratch/), [Prometheus: Pull, Exposition & PromQL](../06-prometheus-and-promql/)
**Time:** ~65 minutes

## The Problem

Thursday, 4pm, a conference room with two groups of people in it. On one side, the product engineers: they have a checkout redesign that's been ready for eleven days, it touches the payment path, and they want it out on Monday because the quarter ends in three weeks and this is the feature the quarter is about. On the other side, the operations engineers: they were paged twice last week — 02:40 and 05:15, both times a deploy that touched the payment path — and they want a two-week stabilization freeze.

Both sides are right. That's what makes the meeting unwinnable. A company that ships nothing dies; a company whose checkout fails also dies, and the ops engineers are the ones awake at 02:40 while everyone else sleeps. Nobody is being unreasonable, and yet after ninety minutes there is no decision — only a rescheduled meeting and two groups who trust each other slightly less.

Then someone, trying to help, says the sentence that ends every one of these meetings without resolving it:

> "Look, we should just aim for **100% uptime**."

It sounds unarguable. It is wrong three separate ways, and taking each apart is how you get to the real answer.

**100% is impossible.** Your service is one link in a chain you do not own. The user's phone drops off the cell tower. Their home router reboots. Their ISP's BGP route flaps. A backhoe finds a fiber run. Your cloud provider loses an availability zone. A DNS resolver caches a stale record for five minutes. Your code could be flawless, your servers eternal, and users would *still* see errors — because most of the path between you and them is other people's infrastructure. The only system with 100% availability is one nobody has ever used.

**100% is uneconomic.** Reliability does not get more expensive linearly; each additional **nine** costs roughly an order of magnitude more than the last. Going from 99.9% to 99.99% means shrinking your annual allowance of badness from **8 hours 45 minutes to 52 minutes**. You cannot buy that with effort. You buy it with multi-region deployment, automated failover tested continuously, canary deploys that roll back inside 90 seconds, and enough on-call staff to hold a rotation without burning anyone out — because at 99.99%, one ten-minute bad rollback is **19% of your entire year's budget**, consumed before lunch.

**100% is pointless.** Even if you could buy it, the user could not perceive it. Suppose your user's own network path is available 99.5% of the time — a fair estimate for a phone on a train. Over 30 days that's 3 hours 36 minutes of "the internet is broken" that has nothing to do with you. Now compare what your two options actually deliver to them:

```text
user-perceived badness over 30 days  =  their network + yours

  your SLO 99.9%   ->  216.0 min (their ISP)  +  43.2 min (you)  =  259.2 min
  your SLO 99.99%  ->  216.0 min (their ISP)  +   4.3 min (you)  =  220.3 min

  improvement to the user:  38.9 min out of 259.2  =  15% less badness
  cost to you:              roughly 10x the reliability engineering
```

You spent an order of magnitude to remove a fifteenth of the badness the user experiences — and they attributed most of what was left to their phone company anyway. Somewhere below 100% there is a point where more reliability stops being worth anything to anyone. **Finding that point, writing it down, and agreeing to live by it is the entire subject of this lesson**, because the practical failure of *not* doing it is exactly the room above: without a shared number, "is this deploy too risky?" has no evidence-based answer and gets decided by seniority, volume, or exhaustion, and "was last week bad?" is a feeling. Feelings do not survive a quarter-end.

## The Concept

The framework that fixes this comes from Google's **Site Reliability Engineering (SRE)** practice, published as *Site Reliability Engineering* (Beyer et al., O'Reilly, 2016) and its follow-up *The Site Reliability Workbook* (Beyer et al., 2018). It is three ideas and one piece of arithmetic. Start with getting the three acronyms exactly right, because they are constantly used interchangeably and they are not the same thing.

### SLI, SLO, SLA — three different promises

An **SLI — Service Level Indicator** — is a **measurement**. Specifically, it is a carefully chosen number that tracks something a *user* can feel. The canonical form is a ratio:

```text
SLI  =  good events / valid events
```

Both halves need definitions you could hand to a stranger. The ratio form is not decoration — it makes the SLI a fraction between 0 and 1, which is what makes everything downstream (budgets, burn rates) simple arithmetic. And the word doing the most work is **user**: CPU utilization is not an SLI, and neither is memory pressure, queue depth, GC pause time, or replica lag. Those are *causes*, and users do not experience causes — they experience slow pages and error messages. A service can run at 95% CPU and delight everyone, or at 12% CPU while every checkout fails. Measure the symptom.

An **SLO — Service Level Objective** — is an internal **target** for an SLI over a **window**. Both parts are required; a target without a window is not an SLO, it's a wish.

```text
99.9% of valid requests succeed, measured over 28 rolling days
^^^^^                                            ^^^^^^^^^^^^^
target                                           window
```

An **SLA — Service Level Agreement** — is an external **contract**, with financial consequences: breach it and you owe someone service credits or money. An SLA is a legal document that happens to contain a number; an SLO is an engineering decision. The relationship between the two is the part teams get wrong: **your SLO must always be stricter than your SLA.** You want your own alarm to go off long before the contractual one does, so that "we're burning budget fast" is an engineering conversation on Tuesday rather than a refund conversation on the 31st.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 436" width="100%" style="max-width:820px" role="img" aria-label="The relationship between SLI, SLO and SLA: the SLI is a measured ratio of good events over valid events, the SLO is an internal target for that ratio over a window, and the SLA is a looser external contract, with a deliberate safety margin between the internal target and the contractual one.">
  <defs>
    <marker id="l09-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three promises, three audiences, one deliberate gap</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M259 154 L 259 168" marker-end="url(#l09-a1)"/>
    <path d="M259 278 L 259 292" marker-end="url(#l09-a1)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="46" width="470" height="108" rx="12" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="24" y="170" width="470" height="108" rx="12" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="24" y="294" width="470" height="108" rx="12" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="568" y="72" width="56" height="308" rx="8" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.3"/>
    <rect x="568" y="170" width="56" height="130" fill="#7c5cff" fill-opacity="0.16" stroke="none"/>
  </g>
  <g fill="none">
    <path d="M556 72 L 636 72" stroke="currentColor" stroke-width="1.5" stroke-dasharray="5 5" opacity="0.55"/>
    <path d="M556 170 L 636 170" stroke="#0fa07f" stroke-width="2.5"/>
    <path d="M556 300 L 636 300" stroke="#e0930f" stroke-width="2.5"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="44" y="72" font-size="12.5" font-weight="700" fill="#3553ff">SLI — Service Level Indicator</text>
    <text x="44" y="91" font-size="9.5" opacity="0.9">what you MEASURE — a user-visible ratio</text>
    <text x="44" y="112" font-size="10.5" font-weight="700">good events / valid events</text>
    <text x="44" y="130" font-size="9.5" opacity="0.8">non-5xx responses  /  all valid requests</text>
    <text x="44" y="147" font-size="9" opacity="0.65">audience: whoever instruments the service</text>
    <text x="44" y="196" font-size="12.5" font-weight="700" fill="#0fa07f">SLO — Service Level Objective</text>
    <text x="44" y="215" font-size="9.5" opacity="0.9">the TARGET you hold yourself to, over a window</text>
    <text x="44" y="236" font-size="10.5" font-weight="700">99.9% of valid requests / 28 rolling days</text>
    <text x="44" y="254" font-size="9.5" opacity="0.8">budget: 0.1% = 40.3 min = 10,000 bad requests</text>
    <text x="44" y="271" font-size="9" opacity="0.65">audience: your team — this is what you alert on</text>
    <text x="44" y="320" font-size="12.5" font-weight="700" fill="#e0930f">SLA — Service Level Agreement</text>
    <text x="44" y="339" font-size="9.5" opacity="0.9">the CONTRACT — breaking it costs real money</text>
    <text x="44" y="360" font-size="10.5" font-weight="700">99.5% per calendar month, else 10% credit</text>
    <text x="44" y="378" font-size="9.5" opacity="0.8">budget: 0.5% = 3h 36m per 30 days</text>
    <text x="44" y="395" font-size="9" opacity="0.65">audience: customers, sales, lawyers</text>
    <text x="644" y="68" font-size="10.5" font-weight="700">100% — impossible</text>
    <text x="644" y="84" font-size="8.5" opacity="0.7">their ISP, DNS, power,</text>
    <text x="644" y="97" font-size="8.5" opacity="0.7">your cloud — all fail</text>
    <text x="644" y="166" font-size="10.5" font-weight="700" fill="#0fa07f">99.9%  ·  SLO</text>
    <text x="644" y="182" font-size="8.5" opacity="0.8">you notice and fix here</text>
    <text x="644" y="296" font-size="10.5" font-weight="700" fill="#e0930f">99.5%  ·  SLA</text>
    <text x="644" y="312" font-size="8.5" opacity="0.8">you write cheques here</text>
    <text x="556" y="228" font-size="9" text-anchor="end" font-weight="700">safety</text>
    <text x="556" y="242" font-size="9" text-anchor="end" font-weight="700">margin</text>
    <text x="440" y="424" font-size="11" text-anchor="middle" opacity="0.9">The gap is not slack. It is the time you get to fix the problem before it becomes a refund.</text>
  </g>
</svg>
```

Read the stack bottom-up and the incentives line up. The SLA is loose because you never want to be *near* it. The SLO sits well above it, so blowing the SLO is a Tuesday-afternoon problem, not a legal one. And the SLI underneath is just a fraction — the only part that is actually measured, and the part everything else is defined in terms of.

### Choosing good SLIs

Five categories are worth knowing, because almost every user complaint you will ever receive is one of these:

| Category | The user's complaint | The SLI |
|---|---|---|
| **Availability** | "It's down / it's erroring" | successful responses / valid requests |
| **Latency** | "It's slow" | requests faster than *T* / valid requests |
| **Quality / correctness** | "It gave me the wrong thing" | responses served in full fidelity / valid requests (e.g. non-degraded search results) |
| **Freshness / staleness** | "It's showing me old data" | records updated within *T* / total records (a replica, cache, or pipeline lag) |
| **Throughput / coverage** | "It never finished my job" | items processed within *T* / items submitted (batch jobs, queues) |

The temptation is to define all of them for every service. Resist it hard. **You want a handful of SLIs, not fifty**, and the filter is simple: *would a user actually complain if this got worse?* For a typical HTTP API, availability plus latency covers the overwhelming majority of real complaints; add freshness only if you have an asynchronous path (a replica, a cache, a queue — Phase 6) where staleness is visible. The reason to be ruthless is structural: every SLO comes with a budget and a policy attached, so forty SLOs means forty budgets, at least one of which is always exhausted. A freeze policy that fires every week gets ignored within a month — and then you have the meeting from *The Problem* again, but now with a spreadsheet nobody believes.

### Request-based vs window-based SLIs

There are two ways to compute the ratio. **Request-based:** count every request over the window — `good requests / valid requests`. This is what most people mean and what maps cleanly to error budgets. **Window-based:** chop the window into small slices (usually one minute), call a slice "good" if its own error ratio was below some threshold, then compute `good minutes / total minutes`. This is what most contractual "uptime" clauses actually mean.

They diverge whenever your traffic isn't flat, which is always. Take a service at 100 requests/second at peak and 5 requests/second at 04:00, and two 30-minute total outages:

```text
                              failed requests        bad minutes
outage at peak    (100 rps)    30 x 60 x 100 = 180,000        30
outage at 04:00   (  5 rps)    30 x 60 x   5 =   9,000        30

request-based:  the peak outage costs 20x more budget  <- tracks user harm
window-based:   both cost exactly the same             <- tracks "was it up?"
```

Neither is wrong; they answer different questions. Request-based tracks **how many humans were hurt**, which is usually what you want your engineering effort steered by. Window-based catches the pathology request-based misses: a long, low-traffic degradation — say your service is broken every night for six hours but only 2% of daily traffic arrives then — barely registers as failed requests but is unmistakably a broken service. Pick request-based by default; know that when the contract says "99.9% uptime," it almost certainly means minutes.

### What counts as a "valid event"

The denominator is where SLOs quietly become dishonest, so define it explicitly:

```text
valid   =  all requests to /api/*
           minus  /healthz, /readyz, /metrics     (your own probes — Lesson 8)
           minus  known crawler and scanner user-agents
           minus  400, 401, 403, 404, 422         (the client sent nonsense)

good    =  valid requests with status < 500
           AND duration < 300 ms
```

Excluding your own health checks matters more than it sounds: a Kubernetes readiness probe hitting `/readyz` every two seconds across 40 pods is 1.7 million requests a day of guaranteed-successful traffic. Leave it in the denominator and it silently inflates your SLI, so that a real outage affecting every human user still reads as 96% "available." Excluding client errors is likewise standard, and comes with an honest caveat: **not every 4xx is the client's fault.** A **429 Too Many Requests** is emitted by *you* when you shed load — your failure wearing the client's status code. A **404 spike** after a deploy usually means you dropped a route. A **401 storm** after you rotate a signing key is entirely yours. So the rule is: exclude 4xx by default, **never exclude 429**, and put a separate alert on the 4xx *rate* so a self-inflicted spike can't hide behind an exclusion meant for genuine client mistakes.

### Measure where the user is, not where it's convenient

Here is the failure mode that makes server-side SLIs dangerous: **your TLS certificate expires.** Every browser refuses the connection, zero requests reach your application, your application therefore records zero failures — and your server-side availability SLI reads a flawless **100%** through a total outage. The same holds for a DNS misconfiguration, a load balancer that 502s before it reaches you, and a BGP withdrawal. The general principle: *an SLI measured inside the thing that's broken cannot see the breakage.* Measure as far out toward the user as you can, and combine three vantage points:

- **One layer up** — load balancer or CDN access logs. Catches everything your app 502s or times out on. This is the best default for the availability SLI.
- **Black-box probes** — synthetic requests from outside your network, on a schedule, from several regions. This is the generalization of Lesson 8's health checks: same idea, run by a stranger. Probes are the only thing that catches DNS, TLS, and total-outage failures.
- **Real-user monitoring (RUM)** — telemetry from the client itself. The only source that includes the user's own network, and therefore the only honest latency measurement. Its weakness is the mirror image: when a user can't reach you *at all*, their RUM beacon can't reach you either.

None of the three is sufficient alone: server-side metrics for volume and detail, one layer up for the availability number, probes for the failures where nobody reached you.

### Latency SLIs need a threshold, not an average

"Average latency is 180 ms" is one of the most confidently wrong sentences in operations. An average blends the user whose request took 40 ms with the user whose request took 9 seconds and reports something true of neither — and it is *stable*: the 9-second requests can triple in number and the average barely twitches. A latency SLO is therefore always phrased as **a proportion under a threshold**: *99% of valid requests complete in under 300 ms, over 28 rolling days.*

That is exactly the shape a **histogram** produces — the structure you built in Lesson 5. A histogram counts, for each bucket boundary `le` (less-than-or-equal), how many observations fell at or below it. So the SLI is one division:

```text
# The latency SLI: the fraction of requests inside the 300 ms bucket
  sum(rate(http_request_duration_seconds_bucket{job="api", le="0.3"}[28d]))
/ sum(rate(http_request_duration_seconds_count {job="api"}[28d]))
```

Which surfaces a trap that catches real teams: **your histogram's bucket boundaries must include your SLO threshold, or you cannot measure your own SLO.** If your buckets are the common `0.1, 0.25, 0.5, 1, 2.5` and your SLO threshold is 300 ms, then `le="0.3"` does not exist. You can interpolate between the 0.25 and 0.5 buckets and get a plausible-looking estimate, but it is an estimate of a straight-line distribution that your latency emphatically is not — and you are now reporting compliance with a contract using a number you invented. Pick the threshold and the bucket boundary together, in the same conversation, and add `0.3` to your buckets before you publish the SLO.

### Percentiles, and why the tail is not an edge case

**p99** — the 99th percentile — is the value below which 99% of observations fall. "p99 latency is 300 ms" means 99 out of every 100 requests finished in under 300 ms, and one did not. That framing makes the tail sound negligible. Draw the actual distribution and it stops sounding that way:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 404" width="100%" style="max-width:830px" role="img" aria-label="A latency histogram of ten thousand requests with a vertical SLO threshold at three hundred milliseconds; ninety-nine percent of requests fall to the left of the threshold and one percent form a long right-hand tail beyond it.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One latency SLI, drawn — where the 300 ms threshold cuts</text>
  <rect x="569" y="56" width="233" height="244" fill="#e0930f" fill-opacity="0.07" stroke="none"/>
  <g fill="none" stroke-linejoin="round" stroke-width="1.8">
    <rect x="100" y="286" width="53" height="14" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="159" y="226" width="53" height="74" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="218" y="107" width="53" height="193" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="277" y="70" width="53" height="230" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="336" y="125" width="53" height="175" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="395" y="180" width="53" height="120" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="454" y="231" width="53" height="69" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="513" y="263" width="53" height="37" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="572" y="293" width="53" height="7" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
    <rect x="631" y="296" width="53" height="4" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
    <rect x="690" y="297" width="53" height="3" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
    <rect x="749" y="297" width="53" height="3" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.45">
    <path d="M94 300 L 810 300"/>
  </g>
  <path d="M569 56 L 569 310" fill="none" stroke="#e0930f" stroke-width="2.5"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="94" y="64" font-size="9" opacity="0.7">requests (per 10,000)</text>
    <text x="88" y="304" font-size="9" opacity="0.7" text-anchor="end">0</text>
    <text x="88" y="212" font-size="9" opacity="0.7" text-anchor="end">1,000</text>
    <text x="88" y="120" font-size="9" opacity="0.7" text-anchor="end">2,000</text>
    <text x="569" y="44" font-size="11" font-weight="700" text-anchor="middle" fill="#e0930f">SLO threshold = 300 ms</text>
    <g font-size="8.5" opacity="0.8" text-anchor="middle">
      <text x="126" y="316">10</text><text x="185" y="316">25</text><text x="244" y="316">50</text>
      <text x="303" y="316">75</text><text x="362" y="316">100</text><text x="421" y="316">150</text>
      <text x="480" y="316">200</text><text x="539" y="316">300</text><text x="598" y="316">500</text>
      <text x="657" y="316">750</text><text x="716" y="316">1k</text><text x="775" y="316">2.5k</text>
    </g>
    <text x="440" y="332" font-size="8.5" opacity="0.65" text-anchor="middle">histogram bucket upper bound (ms) — 300 must be one of these, or the SLO is unmeasurable</text>
    <text x="340" y="356" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">GOOD  ·  9,900 / 10,000  =  99.00%</text>
    <text x="690" y="356" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">TAIL  ·  100 / 10,000  =  1.00%</text>
    <text x="440" y="378" font-size="9.5" opacity="0.9" text-anchor="middle">A page that makes 20 such requests hits the tail with probability 1 - 0.99^20 = 18.2%.</text>
    <text x="440" y="394" font-size="9.5" opacity="0.9" text-anchor="middle">The tail is not an edge case. It is most of your users, some of the time.</text>
  </g>
</svg>
```

Read the last two lines carefully, because they are the whole argument. A modern page load is not one request — it's the HTML, a config call, an auth check, a dozen API calls to populate the view, a couple of analytics beacons. Call it 20. If each independently has a 1% chance of landing in the tail, the chance that *none* of them does is `0.99^20 = 0.818`, so **18.2% of page loads contain at least one p99-slow request**. Nearly one in five. The average number of slow requests per page is a reassuring 0.2 — and it hides the fact that a fifth of your users just watched a spinner.

Fan-out makes this dramatically worse — the **tail-at-scale** problem (Dean & Barroso, *The Tail at Scale*, CACM 2013). When a request fans out to *N* backends **in parallel and waits for all of them**, its latency is the *maximum* of N samples, not the average:

```text
one backend, 1% of responses slow:              1% of requests are slow
fan-out to  10 backends, wait for all:   1 - 0.99^10  =   9.6% slow
fan-out to 100 backends, wait for all:   1 - 0.99^100 =  63.4% slow
```

A p99 that is perfectly respectable at each individual service becomes a **majority-of-requests problem** at the aggregating service above it. This is why the SLO belongs on the user-facing edge, where fan-out has already happened, and why "each of our microservices meets its p99" tells you almost nothing about what users experience.

### The nines table

Now the arithmetic that makes "how many nines" concrete. The error budget of an SLO is `100% − SLO`, applied to the window:

| SLO | error budget | per day | per 7 days | per 30 days | per 365 days |
|---|---|---|---|---|---|
| **99%** (two nines) | 1% | 14m 24s | 1h 40m 48s | 7h 12m | 3d 15h 36m |
| **99.5%** | 0.5% | 7m 12s | 50m 24s | 3h 36m | 1d 19h 48m |
| **99.9%** (three nines) | 0.1% | 1m 26s | 10m 5s | 43m 12s | 8h 45m 36s |
| **99.95%** | 0.05% | 43.2s | 5m 2s | 21m 36s | 4h 22m 48s |
| **99.99%** (four nines) | 0.01% | 8.6s | 1m 1s | 4m 19s | 52m 34s |
| **99.999%** (five nines) | 0.001% | 0.9s | 6.0s | 25.9s | 5m 15s |

Three rows are worth reading as an engineer rather than a marketer. At **99.9%** you have 43 minutes a month: a bad deploy that takes ten minutes to notice and five to roll back costs a third of it. Survivable — which is why 99.9% is the most common starting SLO for an internal service. At **99.99%** you have 4 minutes 19 seconds a month, and human response is no longer in the loop; nobody gets paged, reads a dashboard, and decides anything in four minutes, so every remediation must be automatic (health-check-driven traffic draining from Lesson 8, automated rollback, cross-region failover). That is an architecture, not an effort level. At **99.999%** you have 26 seconds a month, so the deploy process itself must be invisible — a rolling restart that drops one connection has spent your quarter.

### Error budgets: reliability as a currency

Here is the reframe that dissolves the meeting from *The Problem*. An **error budget** is the amount of unreliability your SLO explicitly permits. It is `100% − SLO`, and — this is the whole trick — **it is not a failure. It is an allowance you are entitled to spend.** Work it in both currencies, because both are useful:

```text
SLO             = 99.9% of valid requests succeed over 28 rolling days
error budget    = 100% - 99.9% = 0.1%

as TIME:
  window        = 28 x 24 x 60                     = 40,320 minutes
  budget        = 0.001 x 40,320                   =     40.3 minutes of badness

as REQUESTS:
  traffic       = 10,000,000 valid requests / 28d
  budget        = 0.001 x 10,000,000               = 10,000 requests may fail
  ( = 248 requests/minute average, so 40.3 min of total outage ~= 10,000 requests )
```

The two agree *only* if traffic is uniform, which it never is: a 12-minute total outage at 4am might cost 3% of the request budget, the same 12 minutes at peak 60%. When they disagree, the request count is the one that tracks actual human harm. Now spend it. Budget remaining means you have room to take risk: **ship the feature, run the migration, do the chaos experiment, increase deploy frequency.** Budget exhausted means the policy — *agreed in advance, written down, not argued about during an incident* — takes over: **freeze risky changes, and the next work item for the team is reliability.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:830px" role="img" aria-label="An error budget burndown chart over a twenty-eight day window: the budget depletes slowly from background errors, drops at a small incident on day nine, drops steeply during a database failover on day eighteen, and is fully exhausted by day twenty-six, crossing into breach.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Error-budget burndown — the one picture both rooms look at</text>
  <g stroke="none">
    <rect x="90" y="60" width="710" height="135" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="90" y="195" width="710" height="67" fill="#e0930f" fill-opacity="0.10"/>
    <rect x="90" y="262" width="710" height="68" fill="#7c5cff" fill-opacity="0.13"/>
    <rect x="90" y="330" width="710" height="32" fill="#e0930f" fill-opacity="0.20"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.18">
    <path d="M90 127.5 L800 127.5"/>
    <path d="M90 195 L800 195"/>
    <path d="M90 262.5 L800 262.5"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55">
    <path d="M90 56 L 90 362"/>
    <path d="M90 362 L 800 362"/>
  </g>
  <path d="M90 330 L800 330" fill="none" stroke="#e0930f" stroke-width="2.2" stroke-dasharray="7 5"/>
  <path d="M90 60 L293 82 L318 114 L521 130 L547 271 L699 314 L749 330 L800 346" fill="none" stroke="#3553ff" stroke-width="2.8" stroke-linejoin="round" stroke-linecap="round"/>
  <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.6">
    <path d="M318 116 L 334 146"/>
    <path d="M566 208 L 550 246"/>
  </g>
  <circle cx="749" cy="330" r="4" fill="#e0930f" stroke="none"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <g font-size="9" opacity="0.7" text-anchor="end">
      <text x="80" y="64">100%</text><text x="80" y="131">75%</text><text x="80" y="199">50%</text>
      <text x="80" y="266">25%</text><text x="80" y="334">0%</text>
    </g>
    <g font-size="9" opacity="0.75" text-anchor="middle">
      <text x="90" y="380">day 0</text><text x="268" y="380">day 7</text><text x="445" y="380">day 14</text>
      <text x="622" y="380">day 21</text><text x="800" y="380">day 28</text>
    </g>
    <text x="98" y="100" font-size="9" font-weight="700" opacity="0.9">budget &gt; 50%  ·  SHIP FREELY</text>
    <text x="98" y="214" font-size="9" font-weight="700" opacity="0.9">50–25%  ·  SLOW DOWN</text>
    <text x="98" y="280" font-size="9" font-weight="700" opacity="0.9">&lt; 25%  ·  RELIABILITY WORK ONLY</text>
    <text x="98" y="350" font-size="9" font-weight="700" opacity="0.95">BREACHED  ·  FREEZE RISKY CHANGES</text>
    <text x="340" y="152" font-size="9.5" opacity="0.95">day 9 · bad deploy, rolled back in 5 min</text>
    <text x="340" y="166" font-size="9.5" opacity="0.8">1,240 bad requests = 12% of budget</text>
    <text x="574" y="196" font-size="9.5" opacity="0.95">day 18 · DB failover — 34 min degraded</text>
    <text x="574" y="210" font-size="9.5" opacity="0.8">5,200 bad requests = 52% of budget</text>
    <text x="440" y="402" font-size="10" text-anchor="middle" opacity="0.9">28-day rolling window · budget = 0.1% of valid requests = 40.3 min = 10,000 requests</text>
  </g>
</svg>
```

The burndown is the artifact to put on a wall. Read it left to right: the first eight days lose 8% to ordinary background errors — the noise floor of a real system, and completely fine. Day 9's bad deploy costs 12% in five minutes, which stings but is exactly what the budget is *for*. Day 18 is different: a database failover degrades the service for 34 minutes and takes **52% of the entire month's budget in half an hour**. From there the ordinary background rate — harmless when you had 74% left — walks the remainder down to zero by day 26, and the last two days are spent in breach.

Notice what the chart does to the Thursday-4pm meeting. Nobody has to argue about whether the checkout redesign is "too risky": on day 5 the answer is *ship it, we have 95% of the budget*; on day 19 it's *not this week*. The dispute over values became a lookup against a number both sides agreed to when nobody was angry. That is the whole mechanism, and it is why the error budget is the single most useful idea in this lesson.

#### Rolling vs calendar windows

Use a **rolling** window (28 days, recalculated continuously), not a calendar month. A calendar window resets to full at midnight on the 1st, which produces two pathologies: teams ship everything risky on the 1st because the budget is fresh, and a catastrophic outage on the 30th is forgiven twelve hours later while users are still angry. A rolling window has no cliff — day 18's incident stays on the books until day 46 — so the policy responds to *recent reality* instead of the calendar. And 28 rather than 30 because 28 days is exactly four weeks, so every window holds the same number of Mondays and Saturdays; a 30-day window holds four or five weekends depending on when you look, and weekend traffic differs enough to wobble the SLI for reasons that have nothing to do with your service.

### Burn rate: how fast you're spending

The burndown chart tells you where you are. **Burn rate** tells you how fast you're moving, and it's the number alerts are actually built on. **Burn rate is the multiple of the budget-consumption rate that would exactly exhaust the budget over the SLO window.** Rate 1 means you finish the window with the budget precisely used up; rate 2 means you exhaust it in half the window. The formula is a division:

```text
burn rate  =  observed error ratio / error budget ratio  =  observed error ratio / (1 - SLO)
```

For an SLO of 99.9% the budget ratio is 0.001, so:

| burn rate | observed error ratio | 30-day budget gone in |
|---|---|---|
| 1× | 0.1% | 30 days |
| 2× | 0.2% | 15 days |
| 3× | 0.3% | 10 days |
| 6× | 0.6% | 5 days |
| 14.4× | 1.44% | 50 hours |
| 100× | 10% | 7.2 hours |
| 1000× | 100% (total outage) | **43.2 minutes** |

The last row is the sanity check that proves the arithmetic: a total outage burns at 1000×, and `720 hours / 1000 = 43.2 minutes` — exactly the 30-day budget from the nines table. A complete outage spends a month's worth of 99.9% in 43 minutes; that is the correct emotional response to a total outage, expressed as a number. In PromQL (Lesson 6), the burn rate over the last hour is one expression:

```text
# Burn rate over the last hour, for an SLO of 99.9% (budget ratio = 0.001)
  (
    1 - (  sum(rate(http_requests_total{job="api", code!~"5.."}[1h]))
         / sum(rate(http_requests_total{job="api"}[1h])) )
  ) / 0.001
```

#### Multi-window, multi-burn-rate alerts

You cannot alert on a single burn rate over a single window without choosing badly. Alert on a 5-minute window and every transient blip pages someone. Alert on a 3-day window and you find out about a catastrophic outage on Thursday. The SRE Workbook's answer is to run **several burn-rate alerts at once**, each pairing a fast rate with a short window and a slow rate with a long one:

| burn rate | long window | short window | budget consumed if sustained | response |
|---|---|---|---|---|
| **14.4×** | 1 hour | 5 minutes | 2% | **page** |
| **6×** | 6 hours | 30 minutes | 5% | **page** |
| **1×** | 3 days | 6 hours | 10% | **ticket** |

The "budget consumed" column is where the numbers come from, and verifying one row stops the table looking arbitrary. One hour is `1/720` of a 30-day window; burning at 14.4× for that hour consumes `14.4 × 1/720 = 2%` of the budget. Same method for the others: `6 × 6/720 = 5%` and `1 × 72/720 = 10%`. Each threshold is chosen so that *the alert fires when a specific, agreed fraction of the budget is gone* — not because 14.4 is a nice number. (Teams who want the middle alert tighter substitute `3×` over 6 hours, which by the same arithmetic fires at `3 × 6/720 = 2.5%`.) Detection speed falls out of the same formula: for a constant burn rate *B* against a window *W* and threshold *T*, detection takes about `W × T / B`, so during a **total outage** (B = 1000) the 1-hour/14.4× alert fires in `1h × 14.4 / 1000 = 52 seconds`. A mild 2× degradation never trips it at all — correct, because the 3-day ticket alert catches that on a weekday morning.

**Why two windows per alert?** Each solves a different problem. **The long window suppresses false alarms**: a 30-second blip at 500× burn is a rounding error against a 1-hour window, so it never crosses the threshold, and without it every hiccup is a page. **The short window resets the alert**: with only a 1-hour window, an incident that ends at 09:00 keeps the alert firing until 10:00 as the bad minutes slowly age out. Requiring a **short window (1/12 of the long one) to also be over threshold** clears the alert within about five minutes of the burn actually stopping — the difference between an alerting system people trust and one they mute.

Lesson 10 is where these thresholds become routed, deduplicated pages with an on-call rotation attached. What you've built here is the input: a number that says *how bad, how fast, and how much of what we agreed we could afford is left*.

### The failure modes

Six ways teams get this wrong, in rough order of how often you'll see them:

- **An SLO nobody agreed to.** A senior engineer writes 99.95% on a wiki page. It is not an SLO; it is a preference with a decimal point. An SLO is a *joint commitment* — product, engineering, and operations all signed it — and the policy attached to it is the signature. Without the agreement, the budget can't settle any argument, because one side never conceded the premise.
- **SLOs on causes instead of symptoms.** "CPU under 80%", "replica lag under 5 seconds", "queue depth under 1000". These are diagnostics, and useful ones, but no user has ever filed a ticket about your queue depth. Every one of them can be green during a total outage, and red while everyone is perfectly happy.
- **Too many SLOs.** Forty SLOs is forty budgets, one of which is always exhausted, which means the freeze policy either fires permanently or is quietly ignored. One to three per user journey.
- **Measured only server-side.** Covered above: the expired certificate that reads as 100% availability. If your only SLI comes from inside the application, you are blind to exactly the failures that hurt most.
- **An SLO set to current performance.** You measure 99.94% and set the SLO to 99.94%. This encodes the status quo as a requirement and is self-defeating arithmetic: if your target equals your typical performance, then roughly **half of all windows will breach it by definition**, and the budget policy will fire constantly for no reason. Set the SLO where users start complaining — then find out whether you're above or below it. If you're comfortably above, that's information too: you may be over-invested in reliability and could be shipping faster.
- **Treating the budget as a quota to spend down.** Leftover budget at the end of a window is not waste, and nobody should be injecting failures to use it up. The budget licenses *risk* — a faster deploy cadence, a schema migration, a chaos experiment — not deliberate breakage. If you consistently end windows with 90% of the budget untouched, the right response is to ship faster or to consider whether the SLO is set too loose, not to break something.

## Think about it

1. Your service is a mobile API. Your server-side availability SLI has read 99.98% for six months. What specific failure modes is that number structurally incapable of seeing, and what two additional measurement points would you add to catch them?
2. A team proposes a 99.99% SLO on an internal admin tool used by twelve people during business hours. Using the nines table and the burn-rate arithmetic, argue against it — and propose a number, with the reason it's the right one.
3. Your latency SLO is "99% of requests under 300 ms," but your histogram buckets are `0.1, 0.25, 0.5, 1, 2.5` seconds. Explain precisely why you cannot measure your SLO, why interpolating between the 0.25 and 0.5 buckets is not a fix, and what the one-line remedy is.
4. Two 30-minute total outages, one at peak and one at 04:00. Under a request-based SLI they cost wildly different amounts of budget; under a window-based SLI they cost the same. Which is right — and what kind of failure would each one miss?
5. Your budget is exhausted on day 20 of a 28-day rolling window, and there's a security patch that must ship immediately. Your policy says "freeze risky changes." What does a *good* error-budget policy say about this case, and why must that exception be written down before day 20 rather than negotiated on it?

## Key takeaways

- **SLI** (Service Level Indicator) is a **measurement** — `good events / valid events`, of something a *user* can feel. **SLO** (Service Level Objective) is an internal **target** for that SLI over a **window**; both halves are required. **SLA** (Service Level Agreement) is an external **contract** with money attached, and it must always be looser than the SLO so you notice a problem long before you owe anyone a refund.
- **100% is the wrong target** three ways: impossible (the user's ISP, DNS, power, and your cloud all fail), uneconomic (each nine costs roughly 10× the last — 99.99% leaves 52 minutes a *year*), and pointless (a user on a 99.5%-reliable network cannot perceive the difference between your last two nines).
- Choose **few** SLIs from five categories — **availability, latency, quality, freshness, throughput** — measured **where the user is** (load balancer, black-box probe, RUM), never only inside the application, because an expired TLS certificate reads as 100% server-side availability. Define the denominator explicitly: exclude health checks and 4xx, but **never exclude 429**, which is your failure wearing the client's status code.
- Latency SLOs are a **proportion under a threshold**, never an average — and **your histogram bucket boundaries must include the threshold** (Lesson 5) or the SLO is unmeasurable. The tail is not an edge case: a 20-request page load hits p99 with probability `1 - 0.99^20 = 18.2%`, and a 100-way parallel fan-out turns a 1% slow rate into `1 - 0.99^100 = 63.4%` slow requests (Dean & Barroso, *The Tail at Scale*, 2013).
- The **error budget** is `100% − SLO` — for 99.9% over 28 days that's **40.3 minutes** or **10,000 of 10M requests**. Treat it as a **currency you spend on velocity**: budget remaining licenses risk (ship, migrate, run chaos tests), budget exhausted triggers a policy agreed *in advance*. Use a **rolling** window (28 days = 4 exact weeks) so there's no "it's the 1st, ship everything" cliff.
- **Burn rate** = `observed error ratio / (1 − SLO)`: rate 1 exhausts the budget exactly at the window's end, and a total outage burns at 1000×, spending a month of 99.9% in 43 minutes. Alert with **multi-window, multi-burn-rate** pairs — 14.4× over 1h (2% of budget) and 6× over 6h (5%) page, 1× over 3d (10%) tickets — where the **long window suppresses blips** and the **short window clears the alert** within minutes of recovery.

Next: [Alerting & On-Call That Doesn't Burn People Out](../10-alerting-and-on-call/) — turning these burn-rate thresholds into pages that route to a human who can act, and never into a 3am notification nobody can do anything about.
