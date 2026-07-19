# Metrics: Counters, Gauges & Histograms from Scratch

> A log costs you money per request. A metric costs you a few bytes per *series*, forever, no matter how much traffic flows through it — because it throws the individual request away the instant it records it. That trade buys you the ability to watch every endpoint continuously for a year. This lesson builds the three metric types by hand, and proves the one property that makes histograms worth their cost: you can add them together across machines, and you can never do that with a percentile.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Systems Go Dark](../01-why-systems-go-dark/), [The Log Pipeline](../04-the-log-pipeline/), [Time-Series Databases](../../04-nosql-and-data-modeling/05-time-series-databases/)
**Time:** ~75 minutes

## The Problem

You just finished pricing the log pipeline in Lesson 4, and the number is still on the whiteboard. Now product asks a reasonable question: **"What's the error rate and the latency of every endpoint, right now, and how does it compare to last Tuesday?"**

You already know how to answer that with logs. One structured event per request, twenty endpoints, 3,000 requests per second, and a query that counts and sorts. You also know what it costs: at that traffic you are writing ~260 million events a day, and keeping a year of them so you can compare to last Tuesday means storing and indexing roughly 95 billion events whose only purpose is to be counted. Nobody buys that. So you shrink retention to 14 days, and the question "how does it compare to last Tuesday" quietly becomes unanswerable.

There is a second, worse problem, and it survives even if you *do* pay the bill: the cheap summary everyone reaches for first — an average — is a liar. Here is one minute of real traffic:

**1,000 requests. 950 of them take 50 ms. 50 of them take 6 seconds and the user gives up.**

The mean is `(950 × 0.05 + 50 × 6.0) / 1000` = **347 ms**. That is a number you would put on a dashboard next to a green dot. It is also a number that describes **zero** of your thousand requests — not one of them took anything near 347 ms. Meanwhile 5% of your users are staring at a spinner until it times out.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 330" width="100%" style="max-width:760px" role="img" aria-label="A bimodal latency distribution where 95 percent of requests take about 50 milliseconds and 5 percent take 6 seconds. The mean of 347 milliseconds falls in the empty gap between the two clusters, describing no real request, while p50 and p95 are both 50 milliseconds and p99 is 6 seconds.">
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Averages lie: 1000 requests, 950 fast and 50 timing out</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="300" y="70" width="290" height="56" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <g fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"><rect x="177" y="222" width="16" height="24"/><rect x="197" y="150" width="16" height="96"/><rect x="217" y="86" width="16" height="160"/><rect x="237" y="162" width="16" height="84"/><rect x="257" y="220" width="16" height="26"/></g>
    <g fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"><rect x="677" y="232" width="16" height="14"/><rect x="697" y="224" width="16" height="22"/><rect x="717" y="234" width="16" height="12"/></g>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6"><path d="M64 246 L 756 246"/><path d="M225 246 L 225 258"/><path d="M705 246 L 705 258"/></g>
  <path d="M419 134 L 419 246" fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 5"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="445" y="94" font-size="11" font-weight="700" fill="#e0930f">the mean lands here —</text><text x="445" y="112" font-size="11" font-weight="700" fill="#e0930f">where no request lives</text>
    <text x="225" y="70" font-size="10" opacity="0.9">95% of requests</text><text x="540" y="200" font-size="10" opacity="0.7">nothing lives here</text><text x="690" y="206" font-size="10" opacity="0.9">5%: timing out</text>
    <text x="64" y="266" font-size="9" opacity="0.6">10ms</text><text x="295" y="266" font-size="9" opacity="0.6">100ms</text><text x="525" y="266" font-size="9" opacity="0.6">1s</text><text x="750" y="266" font-size="9" opacity="0.6">10s</text>
    <text x="225" y="288" font-size="10.5" font-weight="700" fill="#3553ff">p50 = p95 = 50 ms</text><text x="419" y="288" font-size="10.5" font-weight="700" fill="#e0930f">mean = 347 ms</text><text x="705" y="288" font-size="10.5" font-weight="700" fill="#7c5cff">p99 = 6 s</text>
    <text x="400" y="316" font-size="11" opacity="0.9">The mean is an average of two populations that do not exist. Percentiles describe real users.</text>
  </g>
</svg>
```

So you agree: percentiles, not averages. Your services record a **p99 latency** — the value below which 99% of requests fall — and graph it. And now you hit the trap this lesson exists to defuse. You have ten servers, each reporting its own p99 every minute, and you want *the fleet's p99 for the last hour*. So you average the ten servers' p99s, then average those over sixty minutes, and put the number on the wall.

**That number is meaningless.** Not "slightly off" — arithmetically undefined. A percentile is not a quantity like a count or a sum; it's a *rank*, an answer already collapsed out of a distribution. Server A's p99 (881 ms over 6,000 requests) and server C's p99 (9,412 ms over 400 requests) do not combine into a fleet p99 any more than "the median height in Norway" and "the median height in a kindergarten" average into "the median height of both". Later in this lesson you'll measure the real error: **the average of three servers' p99s comes out 197% too high.** What you need is a metric type whose recorded form still contains enough of the distribution to be *added up* after the fact. That type is the histogram, and building one is the point of this lesson.

## The Concept

### What a metric actually is

A **metric** is three things: a **name**, a set of **labels** (key-value pairs, also called dimensions or tags), and a **numeric value**, sampled repeatedly over time.

```text
http_requests_total{route="/checkout", status="500", region="eu"}   412

  name    http_requests_total
  labels  route="/checkout", status="500", region="eu"
  value   412            (sampled again on every scrape)
```

Name plus labels identifies one **time series** — exactly the measurement-plus-tags model you built a database for in Phase 4, Lesson 5. The value is whatever that series was at each scrape.

The defining property, and the whole reason metrics are affordable, is that a metric is **aggregated at record time**. When a request fails, your code does `errors.inc()` — an integer goes from 411 to 412 — and the request itself is gone. There is no `user_id`, no stack trace, no URL. Lesson 1 named this the metric's fundamental trade: *aggregation destroys the individual*. That destruction is not a limitation you work around; it is the feature you're paying for. A counter costs the same handful of bytes whether it counted ten requests or ten billion, which is why you can afford to keep it at one-second resolution for a year while your logs get truncated at 14 days.

### The four metric types

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 410" width="100%" style="max-width:840px" role="img" aria-label="The four metric types compared: a counter which only rises and resets to zero on restart, a gauge which moves up and down, a histogram which buckets a distribution, and a summary which precomputes quantiles on the instance and therefore cannot be aggregated.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four metric types — what each is for, and what each will do to you</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="200" height="332" rx="12" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/><rect x="232" y="44" width="200" height="332" rx="12" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="448" y="44" width="200" height="332" rx="12" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/><rect x="664" y="44" width="200" height="332" rx="12" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <g stroke-opacity="0.4" stroke-width="1.2"><line x1="32" y1="240" x2="200" y2="240" stroke="#3553ff"/><line x1="248" y1="240" x2="416" y2="240" stroke="#0fa07f"/><line x1="464" y1="240" x2="632" y2="240" stroke="#e0930f"/><line x1="680" y1="240" x2="848" y2="240" stroke="#7c5cff"/></g>
  </g>
  <g fill="none" stroke-width="2" stroke-linecap="round">
    <path d="M34 164 L 70 140 L 104 112 L 118 104" stroke="#3553ff"/>
    <path d="M118 104 L 118 164" stroke="#3553ff" stroke-width="1.4" stroke-dasharray="4 4" opacity="0.7"/>
    <path d="M118 164 L 152 146 L 198 122" stroke="#3553ff"/>
    <path d="M248 138 L 266 116 L 284 152 L 302 124 L 320 154 L 338 120 L 356 146 L 374 114 L 392 140 L 414 126" stroke="#0fa07f"/>
    <path d="M680 150 L 848 150" stroke="#7c5cff" stroke-width="1.4" opacity="0.7"/>
    <g stroke="#7c5cff"><path d="M706 150 L 706 126"/><path d="M792 150 L 792 126"/><path d="M834 150 L 834 126"/></g>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.8">
    <rect x="466" y="154" width="14" height="10" fill="#e0930f" fill-opacity="0.16"/><rect x="484" y="142" width="14" height="22" fill="#e0930f" fill-opacity="0.16"/><rect x="502" y="124" width="14" height="40" fill="#e0930f" fill-opacity="0.16"/>
    <rect x="520" y="112" width="14" height="52" fill="#e0930f" fill-opacity="0.16"/><rect x="538" y="126" width="14" height="38" fill="#e0930f" fill-opacity="0.16"/><rect x="556" y="140" width="14" height="24" fill="#e0930f" fill-opacity="0.16"/>
    <rect x="574" y="150" width="14" height="14" fill="#e0930f" fill-opacity="0.16"/><rect x="592" y="156" width="14" height="8" fill="#e0930f" fill-opacity="0.16"/><rect x="610" y="158" width="14" height="6" fill="#e0930f" fill-opacity="0.16"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="116" y="72" font-size="13.5" font-weight="700" text-anchor="middle" fill="#3553ff">COUNTER</text><text x="116" y="88" font-size="9" text-anchor="middle" opacity="0.85">only ever goes up</text><text x="116" y="184" font-size="8.5" text-anchor="middle" opacity="0.7">restart resets it to 0</text>
    <text x="32" y="212" font-size="9" font-weight="700" opacity="0.75">FOR</text><text x="32" y="228" font-size="9.5" opacity="0.9">things that accumulate:</text><text x="32" y="244" font-size="9" opacity="0.75">requests, errors, bytes</text>
    <text x="32" y="262" font-size="9" font-weight="700" fill="#3553ff">TRAP</text><text x="32" y="280" font-size="9.5" opacity="0.9">the raw value is useless.</text><text x="32" y="296" font-size="9.5" opacity="0.9">Only rate() has meaning,</text><text x="32" y="312" font-size="9.5" opacity="0.9">and it must detect resets.</text>
    <text x="332" y="72" font-size="13.5" font-weight="700" text-anchor="middle" fill="#0fa07f">GAUGE</text><text x="332" y="88" font-size="9" text-anchor="middle" opacity="0.85">up and down</text><text x="332" y="184" font-size="8.5" text-anchor="middle" opacity="0.7">a level, sampled</text>
    <text x="248" y="212" font-size="9" font-weight="700" opacity="0.75">FOR</text><text x="248" y="228" font-size="9.5" opacity="0.9">a level right now:</text><text x="248" y="244" font-size="9" opacity="0.75">queue depth, memory</text>
    <text x="248" y="262" font-size="9" font-weight="700" fill="#0fa07f">TRAP</text><text x="248" y="280" font-size="9.5" opacity="0.9">you only see scrape</text><text x="248" y="296" font-size="9.5" opacity="0.9">instants. A spike between</text><text x="248" y="312" font-size="9.5" opacity="0.9">two scrapes never existed.</text>
    <text x="548" y="72" font-size="13.5" font-weight="700" text-anchor="middle" fill="#e0930f">HISTOGRAM</text><text x="548" y="88" font-size="9" text-anchor="middle" opacity="0.85">cumulative le buckets</text><text x="548" y="184" font-size="8.5" text-anchor="middle" opacity="0.7">the shape is preserved</text>
    <text x="464" y="212" font-size="9" font-weight="700" opacity="0.75">FOR</text><text x="464" y="228" font-size="9.5" opacity="0.9">distributions: latency,</text><text x="464" y="244" font-size="9" opacity="0.75">payload size, batch size</text>
    <text x="464" y="262" font-size="9" font-weight="700" fill="#e0930f">TRAP</text><text x="464" y="280" font-size="9.5" opacity="0.9">accuracy is capped by your</text><text x="464" y="296" font-size="9.5" opacity="0.9">bucket edges, and every</text><text x="464" y="312" font-size="9.5" opacity="0.9">edge is its own series.</text>
    <text x="764" y="72" font-size="13.5" font-weight="700" text-anchor="middle" fill="#7c5cff">SUMMARY</text><text x="764" y="88" font-size="9" text-anchor="middle" opacity="0.85">quantiles precomputed</text><text x="764" y="184" font-size="8.5" text-anchor="middle" opacity="0.7">computed on the instance</text>
    <text x="706" y="118" font-size="8" text-anchor="middle" opacity="0.8">p50</text><text x="792" y="118" font-size="8" text-anchor="middle" opacity="0.8">p95</text><text x="834" y="118" font-size="8" text-anchor="middle" opacity="0.8">p99</text>
    <text x="680" y="212" font-size="9" font-weight="700" opacity="0.75">FOR</text><text x="680" y="228" font-size="9.5" opacity="0.9">exact quantiles, one box:</text><text x="680" y="244" font-size="9" opacity="0.75">when buckets are unknown</text>
    <text x="680" y="262" font-size="9" font-weight="700" fill="#7c5cff">TRAP</text><text x="680" y="280" font-size="9.5" opacity="0.9">CANNOT be aggregated.</text><text x="680" y="296" font-size="9.5" opacity="0.9">No fleet p99, no new</text><text x="680" y="312" font-size="9.5" opacity="0.9">quantile after the fact.</text>
    <text x="440" y="398" font-size="11" text-anchor="middle" opacity="0.9">Only the histogram answers "how long, and for what fraction of users" AND still adds up across machines.</text>
  </g>
</svg>
```

### Counter: the rate is the signal, not the value

A **counter** is a number that only ever increases, plus one exception: it goes back to **zero** when the process restarts. That's it. `http_requests_total`, `errors_total`, `bytes_sent_total`.

The counter's raw value is close to meaningless. "This process has served 8,412,904 requests" tells you nothing without knowing when it started. What you actually want is the **rate of change**: `rate(http_requests_total[5m])` — the per-second increase over a five-minute window. Rates are what dashboards and alerts are built from.

Because a counter can reset, the query layer cannot just subtract consecutive samples. If a scrape sees `1559` and the next sees `118`, the difference is `-1441`, which is nonsense: the process restarted, and those 118 requests are genuinely new. Every real metrics system therefore treats **any decrease as a reset** and counts the new value as the increase. That's why counters are defined as monotonic in the first place — the invariant is what makes the correction unambiguous. (Your `Counter.inc()` should reject a negative increment for the same reason.)

### Gauge: a snapshot of now

A **gauge** goes up and down. It answers "what is the level of this thing at this instant": queue depth, memory in use, in-flight requests, open database connections, temperature. Unlike a counter, its current value *is* the signal; a rate over a gauge is usually a mistake.

Its trap is **sampling**. A gauge is read once per scrape interval — commonly every 15 seconds. If your connection pool saturates for 4 seconds between two scrapes, that saturation never happened as far as your monitoring is concerned. When the thing you're watching is spiky, either record the max between scrapes as its own gauge, or count the *events* with a counter instead (`pool_exhausted_total`), because a counter cannot miss anything that happens between scrapes.

### Histogram: buckets that survive addition

A **histogram** records a *distribution* rather than a single number. You pick a ladder of upper bounds up front. Every observation increments the count of each bucket it fits in, and the histogram also keeps a running `_sum` of all observed values and a `_count` of all observations.

The critical design decision — the one everything else in this lesson rests on — is that the buckets are **cumulative**. A bucket labelled `le="0.5"` (le = *less than or equal*) does not hold "observations between 0.25 and 0.5". It holds **every observation ≤ 0.5 s**, including all the ones in the smaller buckets. `le="+Inf"` therefore always equals `_count`.

That redundancy looks wasteful. It is the entire point:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="On the left, one histogram's cumulative le buckets and the linear interpolation that estimates p99 inside the bucket holding the target rank. On the right, two servers' bucket counts added together element by element to produce a correct fleet-wide p99, which averaging their two p99s could not do.">
  <defs><marker id="l05-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Cumulative buckets: interpolate one, or add many</text>
  <path d="M38 232 C 24 250, 24 272, 36 286" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="5 5" opacity="0.75" marker-end="url(#l05-a1)"/>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="504" height="376" rx="12" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/><rect x="536" y="44" width="328" height="376" rx="12" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    <rect x="32" y="292" width="472" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/><rect x="552" y="292" width="296" height="112" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.45"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2"><line x1="36" y1="96" x2="500" y2="96"/><line x1="556" y1="118" x2="844" y2="118"/></g>
  <g fill="#3553ff" fill-opacity="0.20" stroke="#3553ff" stroke-width="1.4">
    <rect x="310" y="112" width="87" height="12" rx="3"/><rect x="310" y="138" width="120" height="12" rx="3"/><rect x="310" y="164" width="133" height="12" rx="3"/>
    <rect x="310" y="190" width="137" height="12" rx="3"/><rect x="310" y="242" width="140" height="12" rx="3"/><rect x="310" y="268" width="140" height="12" rx="3"/>
  </g>
  <rect x="310" y="216" width="139" height="12" rx="3" fill="#e0930f" fill-opacity="0.32" stroke="#e0930f" stroke-width="1.6"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="268" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">One server, 1000 observations</text>
    <text x="44" y="90" font-size="9" font-weight="700" opacity="0.7">le (s)</text><text x="200" y="90" font-size="9" font-weight="700" opacity="0.7" text-anchor="middle">in bucket</text><text x="278" y="90" font-size="9" font-weight="700" opacity="0.7" text-anchor="middle">cumulative</text>
    <text x="44" y="122" font-size="10">0.05</text><text x="200" y="122" font-size="10" text-anchor="middle" opacity="0.8">620</text><text x="278" y="122" font-size="10" text-anchor="middle">620</text>
    <text x="44" y="148" font-size="10">0.1</text><text x="200" y="148" font-size="10" text-anchor="middle" opacity="0.8">240</text><text x="278" y="148" font-size="10" text-anchor="middle">860</text>
    <text x="44" y="174" font-size="10">0.25</text><text x="200" y="174" font-size="10" text-anchor="middle" opacity="0.8">90</text><text x="278" y="174" font-size="10" text-anchor="middle">950</text>
    <text x="44" y="200" font-size="10">0.5</text><text x="200" y="200" font-size="10" text-anchor="middle" opacity="0.8">28</text><text x="278" y="200" font-size="10" text-anchor="middle">978</text>
    <text x="44" y="226" font-size="10" font-weight="700" fill="#e0930f">1.0</text><text x="200" y="226" font-size="10" text-anchor="middle" opacity="0.8">14</text><text x="278" y="226" font-size="10" text-anchor="middle" font-weight="700" fill="#e0930f">992</text><text x="468" y="226" font-size="9" font-weight="700" fill="#e0930f">p99</text>
    <text x="44" y="252" font-size="10">2.5</text><text x="200" y="252" font-size="10" text-anchor="middle" opacity="0.8">6</text><text x="278" y="252" font-size="10" text-anchor="middle">998</text>
    <text x="44" y="278" font-size="10">+Inf</text><text x="200" y="278" font-size="10" text-anchor="middle" opacity="0.8">2</text><text x="278" y="278" font-size="10" text-anchor="middle">1000</text>
    <text x="48" y="316" font-size="10.5" font-weight="700">rank = 0.99 × 1000 = 990</text>
    <text x="48" y="338" font-size="10" opacity="0.9">990 first appears in the le=1.0 bucket (978 to 992)</text>
    <text x="48" y="362" font-size="10" opacity="0.9">p99 ≈ 0.5 + (1.0 − 0.5) × (990 − 978) / (992 − 978)</text>
    <text x="48" y="386" font-size="10.5" font-weight="700">      = 0.929 s      interpolated inside that bucket</text>
    <text x="700" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">Two servers, one fleet</text>
    <text x="560" y="112" font-size="9" font-weight="700" opacity="0.7">le (s)</text><text x="672" y="112" font-size="9" font-weight="700" opacity="0.7" text-anchor="middle">web-1</text><text x="748" y="112" font-size="9" font-weight="700" opacity="0.7" text-anchor="middle">web-2</text><text x="828" y="112" font-size="9" font-weight="700" opacity="0.7" text-anchor="middle">fleet</text>
    <text x="560" y="146" font-size="10">0.5</text><text x="672" y="146" font-size="10" text-anchor="middle">978</text><text x="710" y="146" font-size="10" text-anchor="middle" opacity="0.6">+</text><text x="748" y="146" font-size="10" text-anchor="middle">470</text><text x="790" y="146" font-size="10" text-anchor="middle" opacity="0.6">=</text><text x="828" y="146" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">1448</text>
    <text x="560" y="176" font-size="10">1.0</text><text x="672" y="176" font-size="10" text-anchor="middle">992</text><text x="710" y="176" font-size="10" text-anchor="middle" opacity="0.6">+</text><text x="748" y="176" font-size="10" text-anchor="middle">496</text><text x="790" y="176" font-size="10" text-anchor="middle" opacity="0.6">=</text><text x="828" y="176" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">1488</text>
    <text x="560" y="206" font-size="10">+Inf</text><text x="672" y="206" font-size="10" text-anchor="middle">1000</text><text x="710" y="206" font-size="10" text-anchor="middle" opacity="0.6">+</text><text x="748" y="206" font-size="10" text-anchor="middle">500</text><text x="790" y="206" font-size="10" text-anchor="middle" opacity="0.6">=</text><text x="828" y="206" font-size="10.5" text-anchor="middle" font-weight="700" fill="#0fa07f">1500</text>
    <text x="560" y="242" font-size="10" opacity="0.9">rank = 0.99 × 1500 = 1485</text>
    <text x="560" y="264" font-size="10.5" font-weight="700">fleet p99 ≈ 0.963 s</text>
    <text x="568" y="318" font-size="10" opacity="0.9">Bucket counts are counts of the</text><text x="568" y="336" font-size="10" opacity="0.9">same thing, so they ADD.</text>
    <text x="568" y="364" font-size="10" opacity="0.9">Percentiles are already-collapsed</text><text x="568" y="382" font-size="10" opacity="0.9">answers: 0.929 and 0.981 combine</text>
    <text x="568" y="400" font-size="10" opacity="0.9">into nothing at all.</text>
    <text x="440" y="440" font-size="11" text-anchor="middle" opacity="0.9">Ten servers, one hour: sum every le bucket across every scrape, then interpolate once. That is a real fleet p99.</text>
  </g>
</svg>
```

Read the right panel first, because it is the answer to *The Problem*. Both servers used **the same bucket ladder**, so `le="0.5"` means the identical thing on both: "requests that took at most half a second." Two counts of the same predicate can be added — 978 + 470 = 1448 — and the result is a valid bucket count for the combined population. Do that for every bound and you have a histogram of the whole fleet, from which you estimate a p99 exactly the way you would for one server. The same trick works across *time*: sum the buckets of every scrape in an hour and you get the hour's distribution. Neither of those is possible with a p99, which is why averaging them produced garbage.

### Summary: quantiles computed too early

A **summary** also tracks a distribution, but it computes the quantiles **on the instance, at observation time**, and exports the answers: `request_duration_seconds{quantile="0.99"} 0.94`. It's cheap to read (no interpolation at query time) and it's more accurate than a bucketed estimate for the instance that produced it, because it saw the actual values.

And it is a dead end the moment you have more than one instance. You exported `0.94`, not the data behind it, so there is nothing left to add up. You cannot get a fleet p99, you cannot get an hourly p99 from per-minute summaries, and you cannot ask for p99.9 later if you only configured p50/p95/p99 — the buckets you didn't keep are gone. Summaries also cost CPU on the hot path, since maintaining a streaming quantile estimate is real work, whereas a histogram observation is one array increment.

Use a summary when you genuinely have a single instance, or when you cannot guess a bucket ladder at all and only need a rough per-instance sense of the distribution. For anything you will alert on across a fleet, use a histogram.

### Estimating a quantile from buckets

Given cumulative buckets, estimating a quantile is short arithmetic, and it's worth doing by hand once. To find the q-quantile of `N` observations:

1. Compute the target **rank**: `rank = q × N`.
2. Walk the buckets and find the **first** one whose cumulative count is ≥ `rank`. That bucket contains the answer.
3. **Interpolate linearly** inside it, assuming observations are spread evenly across the bucket's width: `lower_bound + (upper_bound − lower_bound) × (rank − count_below) / (count_in_bucket)`.

Using the diagram's numbers: rank = 990, the `le=1.0` bucket is the first with cumulative ≥ 990, 978 observations sit below it and 14 sit inside it, so `p99 ≈ 0.5 + 0.5 × 12/14 = 0.929 s`. This is precisely what Prometheus' `histogram_quantile()` does — and step 3 is a guess — the 14 observations in that bucket are *not* evenly spread, and your p99 is only as good as your bucket edges. Two consequences:

- **A quantile that lands in the `+Inf` bucket is unbounded.** There is no upper bound to interpolate toward, so the honest answer is "at least the largest finite bound." If your p99 keeps reporting exactly your top bucket, your ladder does not reach far enough and you are blind to your worst latency.
- **Precision is highest where the boundaries are dense.** Which means you choose boundaries around the number you care about — your **SLO** (Service Level Objective, the latency target you promise; Lesson 9). If you promise "p99 under 300 ms", you need boundaries clustered around 300 ms, not a bound at 250 ms and the next at 1 s.

### Choosing bucket boundaries

Most client libraries ship a default exponential-ish ladder aimed at sub-second web requests — Prometheus' is `.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10` seconds. Defaults are a fine starting point and a bad ending point: a database driver whose calls take microseconds puts everything in the first bucket, and a video encoder whose jobs take minutes puts everything in `+Inf`. Both histograms are pure cost with zero information.

The cost is concrete: **every bucket is its own time series.** A 16-bucket histogram stores 19 series per label set (16 bounds + `+Inf` + `_sum` + `_count`). So the ladder is a direct trade of storage against resolution, and 10-20 well-placed buckets beat 60 evenly-spaced ones. Place them: a few below your SLO to prove you're comfortably under it, several tightly around it, and a couple well above it so a bad tail has somewhere to land other than `+Inf`.

### Cardinality: the series count is a product

You met this in Phase 4, Lesson 5, and it is the single most common way engineers destroy a metrics backend. It deserves restating as arithmetic, because that's all it is: **the number of series a metric creates is the product of the number of distinct values each label can take.**

```text
http_request_duration_seconds{route, status, region}, 10 buckets
    10 × 20 routes × 5 statuses × 3 regions           =        3,000 series   fine
add user_id (50,000 users)
    10 × 20 × 5 × 3 × 50,000                          =  150,000,000 series   dead database
```

Nothing warns you. The code compiles, the tests pass, and the first deploy quietly begins creating one time series per user, each with its own index entry and in-memory chunk in the TSDB you built in Phase 4. The rule is a one-liner, and it is the same rule as for tags in a time-series database:

> **Labels are dimensions you group by. Identity belongs in logs and traces.**

`route` (a route *template*, `/users/{id}`, never the raw URL), `status`, `method`, `region`, `version` — bounded, and you genuinely want to slice by them. `user_id`, `request_id`, `trace_id`, `session_id`, email, full URL, raw SQL — unbounded, and they belong in the pillars built to carry them.

### Naming and units

Conventions matter more for metrics than almost anywhere else in your codebase, because **dashboards and alerts are written against names**, often by people who did not write the instrumentation, months later. A renamed metric silently breaks a query that nobody runs until an incident. So:

- **`snake_case`, with a namespace prefix**: `payments_charge_attempts_total`, not `chargeAttempts`.
- **`_total` suffix for counters.** It tells a reader (and tooling) that the value is cumulative and must be `rate()`d.
- **Base units, always** — seconds, not milliseconds; bytes, not kilobytes; ratios in 0-1, not percentages. Then `0.25` means the same thing in every dashboard in the company, and nobody multiplies by 1000 at 3am.
- **Unit suffix in the name**: `_seconds`, `_bytes`, `_ratio`. `http_request_duration_seconds` is self-documenting; `http_request_duration` is a bug waiting for a reader to assume milliseconds.

### The four golden signals

"Which metrics do I even create?" has a canonical answer from Google's SRE book (Beyer et al., *Site Reliability Engineering*, 2016, Ch. 6): the **four golden signals**.

- **Latency** — how long requests take. Split successful from failed: a fast stream of 500s can otherwise make your latency graph look *better* during an outage.
- **Traffic** — demand on the system: requests/sec, messages consumed/sec.
- **Errors** — the rate of failures, explicit (500s) or implicit (a 200 with the wrong body).
- **Saturation** — how full your most constrained resource is: connection pool utilisation, queue depth, memory. Saturation is the leading indicator; the other three are how you find out you ignored it.

Instrument those four for every service before you instrument anything clever. Lesson 11 turns them into the **RED** (Rate, Errors, Duration) and **USE** (Utilisation, Saturation, Errors) dashboard methods.

### Push vs pull

Two ways metrics reach a store: your process **pushes** them to a collector (StatsD, OTLP, Graphite), or the store **pulls** them by scraping an HTTP endpoint your process exposes (Prometheus). Pull makes the target list explicit — a target that stops responding is itself a signal — and it gives you a `/metrics` URL you can `curl` while debugging. Push handles short-lived jobs and networks where the scraper can't reach the target. The exposition format your registry renders at the end of the Build It is exactly what a pull-based scrape reads; Lesson 6 serves it over HTTP and queries it.

## Build It

You'll build a real registry: series identity, the three types, quantile estimation validated against ground truth, cross-server aggregation, a cardinality demo, and Prometheus exposition output — standard library only. Start with identity, because everything else hangs off it. A series is a name plus a label set, and `{route="/a", status="200"}` must be the *same* series as `{status="200", route="/a"}`. Sorting the pairs makes the key canonical:

```python
LabelSet = tuple[tuple[str, str], ...]

def label_key(labels: Mapping[str, str]) -> LabelSet:
    """A series' identity is name + labels. Sorting makes label order irrelevant."""
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))

class Metric:
    def labels(self, **kw: str):
        """Return the child series bound to this label set, creating it if new."""
        key = label_key(kw)
        if key not in self.children:
            self.children[key] = self._new_child()
        return self.children[key]
```

The counter enforces monotonicity, and a free function does what a query engine's `rate()` does — sum the deltas, but treat any decrease as a process restart rather than negative traffic:

```python
class CounterChild:
    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("counters are monotonic: inc() cannot be negative")
        self.value += amount

def counter_increase(scrapes: Sequence[float]) -> float:
    """Total increase across scrapes, correcting for resets — what rate() does."""
    return sum(cur - prev if cur >= prev else cur for prev, cur in zip(scrapes, scrapes[1:]))
```

The histogram stores one count per bucket and accumulates on the way out. `bisect_left` finds the first bound that is ≥ the value, which is exactly the `le` bucket the observation belongs to:

```python
class HistogramChild:
    def observe(self, value: float) -> None:
        self.sum += value
        self.count += 1
        # bisect_left finds the first bound with value <= bound: that is the `le` bucket.
        self.bucket_counts[bisect.bisect_left(self.upper_bounds, value)] += 1

    def cumulative(self) -> list[tuple[float, int]]:
        """[(le, how many observations were <= le)] — the aggregatable form."""
        out, running = [], 0
        for i, bound in enumerate(self.upper_bounds):
            running += self.bucket_counts[i]
            out.append((bound, running))
        out.append((math.inf, self.count))      # +Inf always holds every observation
        return out
```

Quantile estimation is the three-step recipe from the diagram, plus the honest `+Inf` case. Below it, `merge_cumulative` is the whole argument of the lesson in four lines:

```python
def histogram_quantile(q: float, buckets: Sequence[tuple[float, int]]) -> float:
    total = buckets[-1][1]
    rank = q * total
    idx = next(i for i, (_, cum) in enumerate(buckets) if cum >= rank)
    if idx == len(buckets) - 1:
        return buckets[-2][0]        # inside +Inf: unbounded above, so report the last bound
    lower_bound = buckets[idx - 1][0] if idx > 0 else 0.0
    lower_count = buckets[idx - 1][1] if idx > 0 else 0
    in_bucket = buckets[idx][1] - lower_count
    return lower_bound + (buckets[idx][0] - lower_bound) * ((rank - lower_count) / in_bucket)

def merge_cumulative(hists):
    """Add bucket counts across instances. THIS is why histograms aggregate."""
    bounds = [b for b, _ in hists[0]]
    if any([b for b, _ in h] != bounds for h in hists[1:]):
        raise ValueError("bucket ladders must match before they can be summed")
    return [(bounds[i], sum(h[i][1] for h in hists)) for i in range(len(bounds))]
```

Note the guard: bucket ladders must be identical to be summed, so two services with different ladders cannot be combined — a good argument for standardising latency buckets across a platform. The file also has `exact_quantile`, which sorts the raw observations (something a real metrics system can never do) purely so we can grade the estimate.

The rest — the `Registry`, `Gauge`, the traffic simulation, the cardinality demo, and the Prometheus text exposition renderer — is in [`code/metrics.py`](code/metrics.py). Run it:

```bash
python3 metrics.py
```

```console
== 1 · WHY AVERAGES LIE ==
  1000 requests: 950 at 50ms, 50 at 6s
  mean =   347.5 ms   <- looks fine on a dashboard
  p50  =    50.0 ms
  p95  =    50.0 ms
  p99  =  6000.0 ms
  requests within 100ms of the mean: 0/1000  <- the mean describes nobody

== 2 · COUNTERS, GAUGES AND THE RESET PROBLEM ==
  label order independence: {route,status} is {status,route} -> True
  http_requests_total{route="/checkout",status="200"} = 1560
  http_requests_total{route="/checkout",status="500"} = 15
  http_requests_total{route="/search",status="200"} = 2392
  http_requests_total{route="/search",status="500"} = 33
  http_requests_in_flight{route="/checkout"} = 7   (a gauge: a snapshot of now)
  counter scrapes 15s apart: [1240, 1402, 1559, 118, 297]  (restart before the 4th)
  naive sum of deltas      =    -943  <- nonsense: one interval is -1441
  reset-aware increase()   =     616  = 10.27 req/s over 60s
  inc(-5) on a counter -> ValueError: counters are monotonic: inc() cannot be negative

== 3 · QUANTILES FROM BUCKETS: LADDER CHOICE IS THE ERROR BAR ==
  GOOD le = 0.005 0.01 0.025 0.05 0.075 0.1 0.25 0.5 0.75 1 1.5 2 3 5 7.5 10
  BAD  le = 0.01 0.1 1 10
  q           exact          GOOD ladder           BAD ladder
  p50        47.2ms       47.3ms   (+0.2%)       60.0ms  (+27.2%)
  p90        99.7ms       99.8ms   (+0.1%)      100.0ms   (+0.3%)
  p99       775.3ms      798.4ms   (+3.0%)      975.5ms  (+25.8%)
  p99.9    1414.0ms     1433.3ms   (+1.4%)     8800.0ms (+522.4%)

== 4 · HISTOGRAMS AGGREGATE · PERCENTILES DO NOT ==
  web-1: n= 6000  p99 =    881.0 ms
  web-2: n= 3000  p99 =    825.0 ms
  web-3: n=  400  p99 =   9411.8 ms
  TRUE fleet p99 (all 9400 raw observations)   =   1246.7 ms
  (a) average of the three p99s           =   3705.9 ms  error  +197.3%   WRONG
  (b) sum the bucket counts, then estimate =   1262.8 ms  error    +1.3%   correct

== 5 · CARDINALITY: SERIES COUNT IS A PRODUCT ==
  8 routes x 5 statuses x 3 regions           =        120 series
  2 routes x 2 statuses x 1 region x 200 users=        800 series
  ...the same shape at 50,000 real users      =  6,000,000 series
  16-bucket histogram over 8 x 2 x 3 labels   =        912 series
  (a histogram costs 19 series per label set: 16 buckets + Inf + _sum + _count)

== 6 · PROMETHEUS TEXT EXPOSITION FORMAT ==
  # HELP http_request_duration_seconds HTTP request latency.
  # TYPE http_request_duration_seconds histogram
  http_request_duration_seconds_bucket{route="/checkout",le="0.005"} 0
  http_request_duration_seconds_bucket{route="/checkout",le="0.01"} 0
  ...
  http_request_duration_seconds_bucket{route="/search",le="+Inf"} 2425
  http_request_duration_seconds_sum{route="/search"} 183.148
  http_request_duration_seconds_count{route="/search"} 2425
  ...
  http_requests_total{route="/search",status="200"} 2392
  http_requests_total{route="/search",status="500"} 33
  (50 lines total, 44 series -- this is exactly what GET /metrics returns)
```

Read the numbers — four of these sections are arguments, not demos. **Section 2** proves the reset problem is not theoretical. Five scrapes, a restart before the fourth, and naively summing the deltas gives **−943 requests** — the reset alone contributes −1441. The reset-aware version reports **616 requests in 60 seconds = 10.27 req/s**, which is the truth. Every `rate()` you will ever write depends on this correction happening for you.

**Section 3** is your error bar, measured rather than asserted. With a 16-bucket ladder tuned to this distribution, the estimated p99 is **798 ms against a true 775 ms — 3.0% high** — and p50 and p90 are within 0.2%. With a four-bucket ladder the same data gives a p50 that is **27.2% wrong** (everything between 10 ms and 100 ms is one undifferentiated bucket) and a p99.9 of **8,800 ms against a true 1,414 ms: 522% wrong**, because the target rank lands in a bucket 9 seconds wide and linear interpolation has nothing to work with. Nobody warns you when this happens. The number just appears on the dashboard, wrong, with three significant figures of false confidence.

**Section 4 is the point of the lesson.** Three servers: two healthy with p99s of 881 ms and 825 ms, one small degraded box at 9,412 ms. The true p99 across all 9,400 requests is **1,246.7 ms**. Averaging the three p99s gives **3,705.9 ms — 197% too high**, because the arithmetic mean weights a 400-request server exactly as heavily as a 6,000-request one, and there is no way to fix that: you exported the answer, not the data. Summing the bucket counts and estimating once gives **1,262.8 ms, an error of 1.3%** — the same accuracy as a single server's estimate. That gap, **197% versus 1.3%**, is the whole argument for cumulative buckets. It is also why the "average of ten servers' p99s" on your wall is not a slightly-imprecise number; it is a number with no defined meaning that happens to be near-triple the truth today and could be half of it tomorrow.

**Section 5** is the multiplication, measured. Eight routes × five statuses × three regions is **120 series** — trivial. Add `user_id` and, with only 200 test users on two routes, you are already at **800 series**; at 50,000 real users the same shape is **6,000,000 series**. Note the histogram line too: 48 label combinations cost **912 series**, because each carries 19 (16 bounds + `+Inf` + `_sum` + `_count`). Histograms are the expensive type; that is the price of being able to aggregate them. **Section 6** is 50 lines with `# HELP`/`# TYPE` headers, the `_bucket{le=...}` series, `+Inf` equal to `_count` (2425 both times, as it must be), and `_sum` — a complete, valid Prometheus scrape response. Lesson 6 serves this exact string over HTTP.

## Use It

In production you use a client library. For Python that's `prometheus_client`, and everything you built has a direct counterpart:

```python
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST

REQUESTS = Counter("http_requests_total", "Total HTTP requests.",
                   ["method", "route", "status"])
IN_FLIGHT = Gauge("http_requests_in_flight", "Requests currently being served.", ["route"])
LATENCY = Histogram("http_request_duration_seconds", "Request latency.", ["method", "route"],
                    buckets=(.005, .01, .025, .05, .075, .1, .25, .5, .75, 1, 1.5, 2, 5))

def handle(request):
    route = match_route_template(request.path)      # "/users/{id}" — NEVER the raw URL
    with IN_FLIGHT.labels(route=route).track_inprogress(), \
         LATENCY.labels(method=request.method, route=route).time():
        response = dispatch(request)
    REQUESTS.labels(method=request.method, route=route, status=str(response.status)).inc()
    return response

def metrics_endpoint():                             # what Prometheus scrapes (Lesson 6)
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
```

`generate_latest()` is your `Registry.render()`. `.labels()` is your `.labels()`. `.time()` and `.track_inprogress()` are context managers (and decorators) that call `observe()` and `inc()`/`dec()` around a block so you can't forget the second half. One library detail worth knowing: `prometheus_client` manages the `_total` suffix itself, so `Counter("http_requests_total", ...)` and `Counter("http_requests", ...)` both expose `http_requests_total`.

Four rules that survive contact with production:

- **Follow the naming conventions from the official Prometheus documentation, not your team's taste.** Base units (seconds, bytes, ratios), unit suffix in the name, `_total` for counters, `snake_case`, one namespace prefix per service. Dashboards outlive the people who wrote them.
- **Histogram or summary?** Choose a **histogram** if you will ever aggregate across instances, slice by a label after the fact, ask for a quantile you didn't pre-declare, or alert on a fleet-wide percentile — that is nearly always. Choose a **summary** only for a single-instance exact quantile where no bucket ladder is guessable.
- **Native histograms are the modern escape hatch.** Prometheus' **native (exponential) histograms**, introduced experimentally in Prometheus 2.40, drop manual bucket boundaries entirely: buckets are generated on an exponential schedule at a configurable resolution, sparsely stored, and they still aggregate. They give you high resolution across many orders of magnitude at a fraction of the series cost. Where the tooling supports them, they remove the single hardest judgement call in this lesson.
- **Instrument every ingress and egress with the same three-metric shape.** Inbound HTTP handlers, outbound HTTP and gRPC calls, database queries, cache lookups, queue publishes and consumes — each gets a request counter with a `status` label, a duration histogram, and (where it matters) an in-flight gauge. When a dependency degrades, the difference between "our service got slow" and "the payments API got slow" is whether you instrumented the *call out* as well as the *call in*.

## Think about it

1. Your histogram's `le="+Inf"` bucket holds 4% of observations and your p99 always reports exactly your largest finite bound. What is actually happening, what have you lost, and what do you change?
2. You want to alert when p99 latency exceeds 300 ms. Sketch a bucket ladder for that SLO, and explain what each boundary buys you. Which boundaries would you *remove* to save series?
3. A teammate adds a `customer_id` label to a counter "just for the top 50 enterprise accounts" — a genuinely bounded set. Is this safe? What would you need to be sure of, and what happens the day the sales team closes account 51?
4. Requests taking 200 ms and requests taking 20 s both land in your `le="+Inf"` bucket, but the `_sum` and `_count` are still exact. What can you compute from `_sum`/`_count` that a quantile can't give you, and why is it *not* a substitute for the p99?
5. Your service instance is restarted by a deploy every twenty minutes. Which of your counters, gauges, and histograms lose information, and which do not? What does that imply about how long a scrape interval you can tolerate?

## Key takeaways

- A **metric** is name + labels + value, **aggregated at record time**. The individual event is destroyed on the way in, which is precisely why a series costs a few bytes regardless of traffic and can be kept for a year — the trade Lesson 1 named and Lesson 4 priced.
- A **counter** only rises (or resets to 0 on restart), so the value is meaningless and the **rate** is the signal; the query layer must treat any decrease as a reset. A **gauge** moves both ways and reports a level *at scrape time*, so spikes between scrapes are invisible — count them with a counter instead.
- A **histogram** bins observations into **cumulative `le` buckets** plus `_sum` and `_count`. Cumulative is what makes bucket counts **addable across servers and across time**, so a fleet-wide p99 is real. In the Build It, summing buckets gave a fleet p99 within **1.3%** of truth while averaging the three servers' p99s was **197% wrong** — averaging percentiles is not imprecise, it is undefined. A **summary** precomputes quantiles on the instance: cheap to read, impossible to aggregate.
- A bucketed quantile is `lower + width × (rank − count_below)/count_in_bucket` — an **estimate** whose accuracy is set entirely by your boundaries. A good ladder was 3.0% off at p99; a coarse one was **522% off at p99.9**, and a quantile inside `+Inf` is unbounded. Choose boundaries around your **SLO**, and remember every bucket is its own time series (19 per label set for a 16-bucket histogram).
- **Cardinality is a product**: 10 buckets × 20 routes × 5 statuses × 3 regions = 3,000 series (fine); add `user_id` and it's 150 million (dead database — Phase 4, Lesson 5). **Labels are dimensions you group by; identity belongs in logs and traces.**
- Name metrics `snake_case` with a namespace, `_total` for counters, and **base units with the unit in the name** (`_seconds`, `_bytes`) — dashboards and alerts are written against names by people who never read your code. Start every service with the **four golden signals** (latency, traffic, errors, saturation) and instrument every ingress *and* egress with the same counter + histogram + gauge shape.

Next: [Prometheus: Pull, Exposition & PromQL](../06-prometheus-and-promql/) — serving the exposition format you just rendered over HTTP, letting a real scraper pull it every 15 seconds, and writing the `rate()` and `histogram_quantile()` queries you implemented by hand.
