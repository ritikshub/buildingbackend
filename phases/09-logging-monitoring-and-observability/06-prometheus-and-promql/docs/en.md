# Prometheus: Pull, Exposition & PromQL

> You built a metrics registry in the last lesson. It lives in the memory of one process, on one of forty machines, and it dies at every deploy. This lesson gets those numbers *out* — over HTTP, in a text format you can read with `curl` — and then makes them *answerable*: how do you ask "the 99th-percentile checkout latency across the fleet, per region, right now" when nobody ever stored that number?

**Type:** Build
**Languages:** Python
**Prerequisites:** [Metrics: Counters, Gauges & Histograms from Scratch](../05-metrics-from-scratch/), [Time-Series Databases](../../04-nosql-and-data-modeling/05-time-series-databases/)
**Time:** ~80 minutes

## The Problem

Your registry works. `http_requests_total{route="/checkout",status="500"}` is sitting at 412, incremented correctly, costing you nothing. It is also completely useless, for three reasons.

**It's inside a process.** The number lives in a Python dictionary in RAM on `web-17`. Nobody outside that process can read it — there's no port, no file, no API, just a variable a garbage collector will free the moment the process ends.

**It dies every deploy.** You ship four times a day; each deploy starts a fresh process with the counter at zero. So "412" answers nothing: 412 since *when*? The absolute value of a counter is an accident of uptime.

**There are forty of them.** Forty processes, forty registries, forty independent numbers. The question you get asked at 03:14 is never "what is the counter on web-17"; it's *"what is the error rate for `/checkout`, across everything, right now, and when did it change?"* Nobody stored that. It has to be **computed** from history — forty series, over a time window, corrected for the three processes that restarted inside that window.

So three questions, in order. **How does the number get out of the process?** **Who asks whom — does the app push, or does something pull?** And **once a year of samples from forty machines sits on a disk, what language turns them into an answer?** By the end of this lesson you'll have built a working version of each answer.

## The Concept

### Pull or push: who asks whom

There are only two ways telemetry moves. In **push**, the application opens a connection to a collector and sends its numbers. In **pull** (Prometheus's model, also called **scraping**), the monitoring system connects to the application, over ordinary HTTP, and asks for them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" width="100%" style="max-width:840px" role="img" aria-label="The Prometheus pull architecture: service discovery keeps a live target list, a scrape loop issues HTTP GET /metrics to each application instance every fifteen seconds, samples land in a local time-series database, and PromQL and rules read from it. A batch job that exits too quickly to be scraped pushes to a Pushgateway, which Prometheus then scrapes like any other target.">
  <defs>
    <marker id="l06-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Pull: Prometheus asks. The app only has to answer.</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M210 172 C 228 172, 228 116, 244 116" marker-end="url(#l06-a1)"/>
    <path d="M398 138 L 398 152" marker-end="url(#l06-a1)"/>
    <path d="M398 196 L 398 210" marker-end="url(#l06-a1)"/>
    <path d="M398 254 L 398 268" marker-end="url(#l06-a1)"/>
    <path d="M548 174 C 580 174, 580 116, 608 116" marker-end="url(#l06-a1)"/>
    <path d="M548 174 L 608 186" marker-end="url(#l06-a1)"/>
    <path d="M548 174 C 580 174, 580 256, 608 256" marker-end="url(#l06-a1)"/>
    <path d="M556 438 L 470 438 L 470 324" marker-end="url(#l06-a1)" stroke-dasharray="6 5" opacity="0.8"/>
    <path d="M708 400 L 708 414" marker-end="url(#l06-a1)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="118" width="186" height="108" rx="12" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="248" y="60" width="300" height="260" rx="14" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor"/>
    <rect x="266" y="94" width="264" height="44" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="266" y="152" width="264" height="44" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="266" y="210" width="264" height="44" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="266" y="268" width="264" height="44" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="612" y="88" width="244" height="56" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="612" y="158" width="244" height="56" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="612" y="228" width="244" height="56" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="560" y="356" width="296" height="44" rx="10" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="560" y="416" width="296" height="44" rx="10" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="117" y="148" font-size="10.5" font-weight="700">SERVICE DISCOVERY</text>
    <text x="117" y="170" font-size="9">kubernetes_sd · ec2_sd</text>
    <text x="117" y="186" font-size="9">consul_sd · dns · static</text>
    <text x="117" y="208" font-size="9" opacity="0.75">keeps the list live</text>
    <text x="398" y="82" font-size="11.5" font-weight="700">PROMETHEUS  (one process)</text>
    <text x="398" y="114" font-size="10.5" font-weight="700">1 · target list</text>
    <text x="398" y="130" font-size="9" opacity="0.85">job="api", 40 instances</text>
    <text x="398" y="172" font-size="10.5" font-weight="700">2 · scrape loop</text>
    <text x="398" y="188" font-size="9" opacity="0.85">every 15s, timeout 10s</text>
    <text x="398" y="230" font-size="10.5" font-weight="700">3 · local TSDB</text>
    <text x="398" y="246" font-size="9" opacity="0.85">2h blocks · WAL · XOR</text>
    <text x="398" y="288" font-size="10.5" font-weight="700">4 · PromQL + rules</text>
    <text x="398" y="304" font-size="9" opacity="0.85">queries, alerts, recording</text>
    <text x="734" y="110" font-size="10.5" font-weight="700">app instance 1</text>
    <text x="734" y="127" font-size="9" opacity="0.85">serves GET /metrics</text>
    <text x="734" y="180" font-size="10.5" font-weight="700">app instance 2</text>
    <text x="734" y="197" font-size="9" opacity="0.85">serves GET /metrics</text>
    <text x="734" y="250" font-size="10.5" font-weight="700">app instance 40</text>
    <text x="734" y="267" font-size="9" opacity="0.85">serves GET /metrics</text>
    <text x="734" y="308" font-size="9.5" opacity="0.85">each replies 200 + text exposition</text>
    <text x="734" y="324" font-size="9.5" opacity="0.85">the response body IS the samples</text>
    <text x="708" y="376" font-size="10.5" font-weight="700">batch job</text>
    <text x="708" y="392" font-size="9" opacity="0.85">runs 20s, exits — nothing to scrape</text>
    <text x="708" y="436" font-size="10.5" font-weight="700">Pushgateway</text>
    <text x="708" y="452" font-size="9" opacity="0.85">holds it; scraped like a target</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="start">
    <text x="30" y="352" font-size="10">A scrape is an ordinary HTTP GET.</text>
    <text x="30" y="370" font-size="10">A failed one sets up=0 — liveness</text>
    <text x="30" y="388" font-size="10">for free, nothing to instrument.</text>
  </g>
</svg>
```

Read the diagram left to right. **Service discovery** hands Prometheus a live list of addresses. The **scrape loop** walks that list on a fixed interval and issues a plain `GET /metrics` against each one. Each target replies with a text body — the samples *are* the response. They land in a **local time-series database**, and **PromQL** (Prometheus Query Language) and the rule evaluator read out of it. Nothing in that path requires the application to know Prometheus exists.

Pull wins on four things that matter more than they sound:

- **A failed scrape is itself a signal.** Prometheus writes a synthetic series called **`up`** for every target on every scrape: `1` if it succeeded, `0` if it failed. You did not instrument that. `up == 0` is a working "the process is dead" alert that exists the moment you add a target. Under push, a silent app and a healthy app look identical — absence of data is ambiguous.
- **Central control of the sample rate.** Scrape interval is Prometheus's config, not the app's: change it in one file, not in forty deploys.
- **Trivial local debugging.** HTTP endpoint, text format. `curl localhost:8000/metrics` shows you exactly what the monitoring system will see, right now, from your laptop.
- **The app doesn't know the backend.** No collector address, no credentials, no client library that blocks when the backend is slow. Its only job is to answer a GET.

And it loses on two, honestly:

- **It needs to know where the targets are.** Push targets self-announce; pull requires **service discovery**, which is real machinery. Anything Prometheus can't reach — behind NAT (Network Address Translation), in a customer's network, on a laptop — can't be scraped at all.
- **Short-lived jobs vanish between scrapes.** A cron job that runs for 20 seconds on a 15-second interval may never be observed. For this one case Prometheus ships the **Pushgateway**: the job pushes its final numbers to a small server that holds them, and Prometheus scrapes *that*. It is deliberately narrow — the Pushgateway never expires values and has no `up` of its own, so using it for long-running services gives you stale numbers forever.

There is also a push path *out* of Prometheus: **`remote_write`**, which streams every scraped sample onward to a long-term store. That's the modern architecture — pull at the edge where liveness matters, push in the backbone where durability and global query matter.

### Service discovery: how the target list writes itself

Hardcoding forty addresses is fine for four and unworkable for four hundred that change hourly, so Prometheus asks an authority. `static_configs` is the literal list. `kubernetes_sd_configs` talks to the Kubernetes API and gets every pod, service, and endpoint with all their labels and annotations; `ec2_sd_configs`, `consul_sd_configs`, and `dns_sd_configs` do the same against AWS, Consul, and DNS SRV records.

Discovery returns raw metadata, not a clean target list — Kubernetes hands over `__meta_kubernetes_pod_annotation_prometheus_io_scrape`, `__meta_kubernetes_namespace`, and dozens more. **`relabel_configs`** is the rule engine that turns that metadata into a decision and a label set: keep this target or drop it, rewrite its address, copy the metadata you care about into real labels like `namespace` and `pod`. It runs *before* the scrape, so it decides *whether and what* to scrape. (Its sibling `metric_relabel_configs` runs *after*, editing or dropping the samples themselves — the emergency brake when one target starts emitting a million series.)

### The exposition format: metrics as text over HTTP

The format is deliberately, almost insultingly simple: UTF-8 text, one sample per line, `name{labels} value`. Comment lines starting with `# HELP` and `# TYPE` carry the metadata.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:830px" role="img" aria-label="Anatomy of the Prometheus text exposition format: HELP and TYPE comment lines carry metadata, each sample line is a metric name, a brace-delimited label set and a value, and a histogram is exposed as cumulative bucket series with an le label plus a sum and a count series.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The response body of GET /metrics, line by line</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="52" width="490" height="248" rx="12" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor"/>
    <rect x="556" y="60" width="292" height="40" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="556" y="112" width="292" height="40" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="556" y="164" width="292" height="40" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="556" y="216" width="292" height="84" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 4" opacity="0.55">
    <path d="M420 84 L 552 80"/>
    <path d="M420 104 L 552 132"/>
    <path d="M400 128 L 552 184"/>
    <path d="M400 216 L 552 250"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" font-size="10">
    <text x="44" y="84">#&#160;HELP http_requests_total Total HTTP requests.</text>
    <text x="44" y="104">#&#160;TYPE http_requests_total counter</text>
    <text x="44" y="124">http_requests_total{route="/cart",status="200"} 27</text>
    <text x="44" y="144">http_requests_total{route="/cart",status="500"} 1</text>
    <text x="44" y="172">#&#160;TYPE http_request_duration_seconds histogram</text>
    <text x="44" y="192">http_request_duration_seconds_bucket{le="0.05"} 8</text>
    <text x="44" y="212">http_request_duration_seconds_bucket{le="0.1"} 27</text>
    <text x="44" y="232">http_request_duration_seconds_bucket{le="+Inf"} 28</text>
    <text x="44" y="252">http_request_duration_seconds_sum 3.665850</text>
    <text x="44" y="272">http_request_duration_seconds_count 28</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" font-size="9.5">
    <text x="568" y="78" font-weight="700">#&#160;HELP</text>
    <text x="568" y="93" opacity="0.85">one description per family</text>
    <text x="568" y="130" font-weight="700">#&#160;TYPE</text>
    <text x="568" y="145" opacity="0.85">counter · gauge · histogram · summary</text>
    <text x="568" y="182" font-weight="700">one line = one SERIES</text>
    <text x="568" y="197" opacity="0.85">name + label set identify it</text>
    <text x="568" y="234" font-weight="700">a histogram is 3 kinds of series</text>
    <text x="568" y="250" opacity="0.85">_bucket{le="x"} — CUMULATIVE count</text>
    <text x="568" y="265" opacity="0.85">                 of obs &lt;= x</text>
    <text x="568" y="285" opacity="0.85">_sum and _count — for the mean</text>
  </g>
  <g fill="none" stroke-width="2.2">
    <path d="M60 342 L 208 342" stroke="#3553ff"/>
    <path d="M212 342 L 426 342" stroke="#0fa07f"/>
    <path d="M434 342 L 452 342" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.55">
    <path d="M134 344 L 134 360"/>
    <path d="M319 344 L 319 360"/>
    <path d="M443 344 L 443 360"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="60" y="332" font-size="13">http_requests_total{route="/cart",status="200"} 27</text>
    <text x="134" y="374" font-size="10" text-anchor="middle" font-weight="700">metric name</text>
    <text x="319" y="374" font-size="10" text-anchor="middle" font-weight="700">label set</text>
    <text x="443" y="374" font-size="10" text-anchor="middle" font-weight="700">value</text>
    <text x="440" y="400" font-size="10" text-anchor="middle" opacity="0.85">No timestamp: the scraper stamps every sample with the scrape time.</text>
  </g>
</svg>
```

The parts, in order. **`# HELP`** gives a family one human-readable sentence — what a dashboard shows on hover. **`# TYPE`** declares `counter`, `gauge`, `histogram`, or `summary`; this is metadata only (the wire format is identical) but it's what tells a UI, and you, that `rate()` is legal here. Then one line per **series**: metric name, optional brace-delimited label set, float. **Notice what's missing: a timestamp.** The format allows one but almost nobody sends it — the scraper stamps every sample with the time of the scrape, which is why all series from one target share exactly aligned timestamps, which is what makes arithmetic across them possible later.

A **histogram** has no special syntax — it decomposes into ordinary series, exactly as you built in Lesson 5. For `http_request_duration_seconds` you get `_bucket{le="0.05"}`, `_bucket{le="0.1"}`, … `_bucket{le="+Inf"}` — each a **cumulative** count of observations **l**ess than or **e**qual to that bound — plus `_sum` and `_count`. Cumulative is the design choice that makes everything downstream work: add two targets' `le="0.5"` buckets together and the result is still a valid bucket.

The format is served as `Content-Type: text/plain; version=0.0.4`. Its standardized successor is **OpenMetrics** — the same shape with tightened rules (an explicit `# EOF` terminator, native exemplars linking a bucket to a trace ID) and the content type `application/openmetrics-text; version=1.0.0`. Prometheus content-negotiates between the two; you rarely notice.

### Scraping mechanics: interval, timeout, `up`, staleness

**`scrape_interval`** (default 1 minute; 15 seconds is the common production value) is the resolution of everything you will ever see, and it sets your floor on detection: an alert needing three consecutive bad samples cannot fire in less than three intervals, so a 60-second interval means a 3-minute floor on time-to-page. **`scrape_timeout`** must be less than the interval — a target that takes 30 seconds to render `/metrics` on a 15-second interval is one you will never successfully scrape.

By default the scraper overwrites any `job` or `instance` label the target sends with the ones from its own config; that's what makes target labels trustworthy. **`honor_labels: true`** flips it, letting the target's labels win — exactly what you want when scraping a Pushgateway or a federation endpoint that is *reporting on behalf of* someone else.

**Staleness** is the subtle one. When a target disappears — scaled down, redeployed, dropped from discovery — its series don't return zero and don't stay at their last value forever. Prometheus writes an explicit **stale marker**, and any query evaluating after it sees no value. Separately, an instant query looks back at most **5 minutes** for a sample; if the newest is older than that, the series is simply absent from the result. This is why `absent()` exists, and why a graph goes to a gap rather than a flat line when a pod dies.

### Where the samples land: the TSDB you already built

You have built this store. Prometheus's **TSDB** (time-series database) writes **2-hour blocks** — your time-bucketed chunks from Phase 4 Lesson 5 — compressed with **delta-of-delta timestamp encoding** and **XOR value compression**, the Gorilla scheme from Pelkonen et al. (VLDB 2015): the exact two codecs you implemented by hand, storing a sample in roughly 1–2 bytes. That is not a coincidence of naming; it is the same algorithm.

Recent data lives in an in-memory **head block**, and because RAM doesn't survive a crash, every incoming sample is first appended to a **write-ahead log (WAL)** — the durability trick from Phase 3 Lesson 13, for the same reason. On restart Prometheus replays the WAL to rebuild the head. Every two hours the head is cut into an immutable on-disk block and the WAL is truncated; retention is then a directory delete, `O(blocks)`.

### PromQL, part 1: what a query returns

PromQL has three result shapes, and confusing them is the source of most beginner errors.

- An **instant vector** is one value per matching series, at one instant: `http_requests_total` returns forty numbers, one per series, each the latest sample.
- A **range vector** is a *slice of history* per matching series: `http_requests_total[5m]` returns, for each series, every sample in the last 5 minutes. You cannot graph a range vector. Its only purpose is to be fed to a function like `rate()` that collapses it back to one number per series.
- A **scalar** is a single plain number: `0.05`, or `time()`.

Selecting series uses four matchers inside the braces: `=` equals, `!=` not equals, `=~` matches a regex (anchored on both ends, RE2 syntax), `!~` doesn't match. The metric name is itself a label, `__name__`, so these compose:

```text
http_requests_total{route="/checkout"}                    # exact
http_requests_total{status=~"5.."}                        # regex: all 5xx
http_requests_total{route!="/health", env="prod"}         # exclusion + AND
{__name__=~"http_.*", job="api"}                          # name as a label
```

### PromQL, part 2: `rate()`, and the counter that goes backwards

Here is the central fact. **A counter's value is meaningless.** `http_requests_total = 412` tells you nothing, because 412 is measured from whenever the process last started. What carries information is how fast it's *increasing*. `rate(http_requests_total[5m])` gives you the **per-second average rate of increase over the last 5 minutes**, per series — a number that means the same thing on a process that started an hour ago and one that started last week.

Now the wrinkle. Processes restart, and when they do, the counter goes back to zero. Any naive "last value minus first value" produces a negative — or worse, a plausible-looking but far too small — answer.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 366" width="100%" style="max-width:840px" role="img" aria-label="A counter climbing, dropping to zero at a process restart, then climbing again. A naive last-minus-first calculation gives a negative rate, while rate detects the decrease as a reset and adds the pre-reset value back, giving the correct positive rate.">
  <defs>
    <marker id="l06-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
    <marker id="l06-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/>
    </marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">rate() over a counter that restarts</text>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M90 80 L 90 284"/>
    <path d="M90 280 L 600 280"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="5 5" opacity="0.35">
    <path d="M325 84 L 325 280"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="2.6" stroke-linejoin="round">
    <path d="M149 163 L 208 127 L 266 108"/>
    <path d="M384 260 L 443 234 L 501 204 L 560 178"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="7 5">
    <path d="M266 108 L 378 254" marker-end="url(#l06-a3)"/>
    <path d="M149 163 L 552 178" marker-end="url(#l06-a3)"/>
  </g>
  <g fill="#3553ff">
    <circle cx="149" cy="163" r="4"/><circle cx="208" cy="127" r="4"/><circle cx="266" cy="108" r="4"/>
    <circle cx="384" cy="260" r="4"/><circle cx="443" cy="234" r="4"/><circle cx="501" cy="204" r="4"/><circle cx="560" cy="178" r="4"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="620" y="96" width="228" height="102" rx="10" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="620" y="216" width="228" height="122" rx="10" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="325" y="68" font-size="9.5" fill="#e0930f" font-weight="700">RESTART · +105s scrape failed</text>
    <text x="149" y="152" font-size="8.5">86</text>
    <text x="208" y="116" font-size="8.5">113</text>
    <text x="266" y="97" font-size="8.5">127</text>
    <text x="404" y="268" font-size="8.5">15</text>
    <text x="443" y="223" font-size="8.5">34</text>
    <text x="501" y="193" font-size="8.5">56</text>
    <text x="560" y="167" font-size="8.5">75</text>
    <text x="149" y="298" font-size="9">+60s</text>
    <text x="266" y="298" font-size="9">+90s</text>
    <text x="384" y="298" font-size="9">+120s</text>
    <text x="560" y="298" font-size="9">+165s</text>
    <text x="345" y="320" font-size="9.5" opacity="0.85">scrape samples, 15s apart</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="start">
    <text x="90" y="68" font-size="10" font-weight="700">http_requests_total</text>
    <text x="160" y="234" font-size="9.5" fill="#e0930f">naive line: last minus first</text>
    <text x="160" y="250" font-size="9.5" fill="#e0930f">slopes DOWN across the reset</text>
    <text x="632" y="120" font-size="10.5" font-weight="700">NAIVE  last - first</text>
    <text x="632" y="140" font-size="9.5">75 - 86 = -11</text>
    <text x="632" y="157" font-size="9.5">-11 / 120s = -0.092 req/s</text>
    <text x="632" y="178" font-size="9" opacity="0.8">a counter cannot decrease,</text>
    <text x="632" y="192" font-size="9" opacity="0.8">so this answer is nonsense</text>
    <text x="632" y="240" font-size="10.5" font-weight="700">rate()  reset-aware</text>
    <text x="632" y="260" font-size="9.5">sees 127 then 15: a RESET</text>
    <text x="632" y="277" font-size="9.5">(75 + 127) - 86 = +116</text>
    <text x="632" y="294" font-size="9.5">116 over 105s, extrapolated</text>
    <text x="632" y="313" font-size="9.5" font-weight="700">= +1.105 req/s</text>
    <text x="632" y="331" font-size="9" opacity="0.8">matches the real traffic</text>
  </g>
</svg>
```

`rate()`'s rule is simple and it is the reason the function exists: **walk the samples in the window; whenever a sample is lower than the one before it, that can only be a reset, so add the pre-reset value back into a running correction.** The diagram shows the arithmetic — `(75 + 127) - 86 = 116` instead of `75 - 86 = -11`. Two honest caveats: traffic served *between* the last scrape and the restart is simply lost (nobody recorded it), and a counter that resets *and* climbs back above its old value between two scrapes is invisible. Scrape often enough that neither matters.

`rate()` also **extrapolates**. Your samples don't land exactly on the window edges, so Prometheus scales the observed delta up to the full window width — which is why `rate()` on an integer counter returns a non-integer, and why `increase()` (which is exactly `rate() × window`) can report "3.4 requests". Extrapolation is also why the window needs room: **make the range at least 4× the scrape interval.** With a 15-second interval, `[1m]` is the minimum and `[5m]` is the safe default. Fewer than two samples in the window and `rate()` returns nothing at all — the classic cause of a graph that's mysteriously empty.

Three functions, three jobs:

| Function | What it does | Use it for |
|---|---|---|
| `rate(c[5m])` | per-second average across the whole window, reset-aware | almost always — graphs, alerts, Service Level Objectives |
| `irate(c[5m])` | per-second rate from only the **last two** samples | short, spiky debugging graphs; too jumpy for alerts |
| `increase(c[1h])` | total increase over the window (`rate × seconds`) | "how many errors in the last hour" |

### PromQL, part 3: aggregation, and why `rate` comes before `sum`

`rate()` gives you one number per series — and you have forty instances × six routes × four statuses of them. **Aggregation operators** collapse that: `sum`, `avg`, `min`, `max`, `count`, `stddev`, `topk(k, …)`, `bottomk(k, …)`, `quantile(φ, …)`. Each takes `by (labels)` — keep only these labels — or `without (labels)` — keep all but these.

```text
sum by (route) (rate(http_requests_total[5m]))       # per-route request rate, whole fleet
sum without (instance) (rate(http_requests_total[5m]))   # fold away instances, keep the rest
topk(5, sum by (route) (rate(http_requests_total[5m]))) # the five busiest routes
```

Now the rule that separates people who use PromQL from people who fight it:

> **`rate` before `sum`. Always. `sum(rate(x[5m]))` is right; `rate(sum(x)[5m])` is wrong.**

Why: `rate()` detects a reset by seeing a *decrease* in one series. Sum forty counters together first and one instance's restart is buried — the other thirty-nine were still climbing, so the total may not visibly dip at all, and the reset becomes invisible. You've destroyed exactly the signal `rate()` needs, and you get a silently deflated number. (PromQL's grammar makes this hard to write by accident — you can't apply a range selector to an expression — but the same mistake reappears as `avg(rate(...))` where you meant `sum(rate(...))`, or as `sum` inside a recording rule that a later query rates.) Aggregate *after* you've turned each series into a rate. Rates are plain per-second numbers; adding them is always safe.

### PromQL, part 4: percentiles, ratios, and rules

**`histogram_quantile(φ, b)`** takes a quantile between 0 and 1 and an instant vector of *cumulative bucket* values carrying an `le` label, and estimates the quantile by interpolating inside whichever bucket contains it. The fleet-wide p99 you hand-computed in Lesson 5 is one line:

```text
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))
```

Read it inside out: `rate(..._bucket[5m])` turns every bucket counter into a per-second rate (reset-aware); `sum by (le)` adds those rates across every instance and route, keeping only `le`, which reassembles one fleet-wide histogram; `histogram_quantile` reads the answer off it. **You must keep `le` in the `by` clause** — dropping it collapses the histogram into meaningless mush. Accuracy is bounded by your bucket boundaries: if p99 lands in the `(1, 2.5]` bucket, the answer is a linear guess inside that range. Percentiles from histograms are estimates, and that is the price of being able to aggregate them at all.

**Binary operators** (`+ - * / % ^`, and comparisons) work between two vectors by matching series with **identical label sets**. When the label sets differ you say how: `on(labels)` matches only on those, `ignoring(labels)` matches on everything else, and `group_left` / `group_right` permit many-to-one matching (one denominator series serving many numerators). The canonical use is an error *ratio* — two rates divided — which is the second golden-signal query below.

**Recording rules** precompute an expensive expression on a schedule and store the result as a new series. A dashboard with twelve panels each running a fleet-wide `histogram_quantile` will crawl; the same dashboard reading `job:latency_p99:5m` is instant. **Alerting rules** are the same evaluation with a threshold: an `expr`, a `for` duration the expression must stay true before firing (this is what suppresses one-off blips), plus `labels` for routing severity and `annotations` for the human text on the page. Lesson 10 turns these into an on-call practice that doesn't destroy people; here, just know the shape.

### The golden signals, as four queries

Google's SRE book names four signals worth watching on any user-facing service. In PromQL they are:

```text
# Traffic  — requests per second, per route
sum by (route) (rate(http_requests_total[5m]))

# Errors   — fraction of requests failing, per route
sum by (route) (rate(http_requests_total{status=~"5.."}[5m]))
  / ignoring(status) sum by (route) (rate(http_requests_total[5m]))

# Latency  — 99th percentile seconds, per route
histogram_quantile(0.99,
  sum by (le, route) (rate(http_request_duration_seconds_bucket[5m])))

# Saturation — how full the constrained resource is (here: the DB connection pool)
max by (instance) (db_pool_in_use / db_pool_size)
```

## Build It

Let's build the entire loop — endpoint, scraper, storage, query engine — in one standard-library file. Two application "instances" each run a real HTTP server on an ephemeral port; a scraper pulls both on a simulated 15-second interval; one of them fails a scrape and restarts, so its counters fall to zero.

Rendering the exposition format is nothing clever — string building, sorted for stable output. The histogram is where the shape shows: one `_bucket` line per boundary carrying `le` as a label, then `_sum` and `_count`. The buckets are cumulative because `observe()` incremented every bucket whose bound is `>=` the value:

```python
def render(self) -> str:
    """Emit the Prometheus text exposition format, byte for byte."""
    out: List[str] = []
    for name in sorted({n for n, _ in self.counters}):
        out.append("# HELP %s %s" % (name, self.help.get(name, "")))
        out.append("# TYPE %s counter" % name)
        for (n, lk), v in sorted(self.counters.items()):
            if n == name:
                out.append("%s%s %s" % (n, _fmt_labels(dict(lk)), _fmt_value(v)))
    # ... and for each histogram family:
    for i, upper in enumerate(BUCKETS):
        out.append("%s_bucket%s %d" % (
            n, _fmt_labels(labels, ("le", _fmt_le(upper))), counts[i]))
    out.append("%s_bucket%s %d" % (n, _fmt_labels(labels, ("le", "+Inf")), h["count"]))
    out.append("%s_sum%s %s" % (n, _fmt_labels(labels), _fmt_value(float(h["sum"]))))
    out.append("%s_count%s %d" % (n, _fmt_labels(labels), h["count"]))
```

The scrape is one HTTP GET plus a parse. Two details matter more than the code: `up` is **synthetic** — the scraper writes it, the target never sends it — and **target labels are stamped on at scrape time**, which is how `job` and `instance` get onto samples the application knows nothing about:

```python
def scrape(app: App, ts: int, tsdb: TSDB, job: str):
    """One pull. Returns (up, samples stored, total request count seen)."""
    target = {"job": job, "instance": app.name}
    try:
        with urllib.request.urlopen(app.url, timeout=2.0) as resp:
            body, ok = resp.read().decode("utf-8"), resp.status == 200
    except OSError:                     # HTTPError and connection refusal both land here
        ok, body = False, ""
    # `up` is SYNTHETIC: the scraper writes it, the target never sends it.
    tsdb.append("up", dict(target), ts, 1.0 if ok else 0.0)
    if not ok:
        return False, 1, None
    for name, labels, value in parse_exposition(body):
        labels.update(target)          # target labels are attached at scrape time
        tsdb.append(name, labels, ts, value)
```

And here is the centerpiece — `rate()`, with the reset correction and the edge extrapolation:

```python
def rate(points, start, end):
    """rate(metric[window]) -- per-second increase, correcting for counter resets."""
    if len(points) < 2:
        return None                                    # a rate needs two points, minimum
    correction, prev = 0.0, points[0][1]
    for _, v in points[1:]:
        if v < prev:                                   # a decrease can only mean a RESET;
            correction += prev                         # add back everything counted before it
        prev = v
    delta = (points[-1][1] + correction) - points[0][1]
    sampled = points[-1][0] - points[0][0]             # extrapolate out to the window edges
    avg_gap = sampled / (len(points) - 1)
    to_start, to_end = points[0][0] - start, end - points[-1][0]
    if delta > 0 and points[0][1] >= 0:                # never extrapolate past where the
        to_start = min(to_start, sampled * (points[0][1] / delta))   # counter would be zero
    if to_start >= 1.1 * avg_gap:
        to_start = avg_gap / 2                         # a big gap means the series started late
    if to_end >= 1.1 * avg_gap:
        to_end = avg_gap / 2
    delta *= (sampled + to_start + to_end) / sampled
    return delta / (end - start)
```

The rest — the exposition parser (including the `{le="0.5"}` label syntax), the `ThreadingHTTPServer` on an ephemeral port, the mini TSDB, `sum_by`, and `histogram_quantile` — is in [`code/prometheus_mini.py`](code/prometheus_mini.py). Run it:

```console
$ python3 prometheus_mini.py
== EXPOSITION FORMAT: the literal bytes of GET /metrics ==
  HTTP 200  Content-Type: text/plain; version=0.0.4; charset=utf-8
  # HELP http_requests_total Total HTTP requests served.
  # TYPE http_requests_total counter
  http_requests_total{route="/cart",status="200"} 27
  http_requests_total{route="/cart",status="500"} 1
  http_requests_total{route="/checkout",status="200"} 10
  http_requests_total{route="/checkout",status="500"} 2
  # HELP http_request_duration_seconds Request duration in seconds.
  # TYPE http_request_duration_seconds histogram
  ...
  http_request_duration_seconds_bucket{route="/cart",le="0.05"} 8
  http_request_duration_seconds_bucket{route="/cart",le="0.1"} 27
  ...
  http_request_duration_seconds_bucket{route="/cart",le="+Inf"} 28
  http_request_duration_seconds_sum{route="/cart"} 3.665850
  http_request_duration_seconds_count{route="/cart"} 28
  ... 13 more lines: buckets, and the same family for route="/checkout"
  (34 lines, 2097 bytes total)

== SCRAPE LOG: the scraper drives the clock, 15s interval ==
      t | app-1  up  samples    total | app-2  up  samples    total
    +0s |         1       31       40 |         1       29       40
   +15s |         1       31       80 |         1       29       80
   +30s |         1       31      120 |         1       31      120
   +45s |         1       31      160 |         1       31      160
   +60s |         1       31      200 |         1       31      200
   +75s |         1       31      240 |         1       31      240
   +90s |         1       31      280 |         1       31      280
  +105s |         0        1        - |         1       31      320  <- app-1 scrape FAILED: only `up` stored
  +120s |         1       30       40 |         1       31      360  <- app-1 restarted: counter back to zero
  +135s |         1       31       80 |         1       31      400
  +150s |         1       31      120 |         1       31      440
  +165s |         1       31      160 |         1       31      480
  series in the mini TSDB: 62

== rate() vs NAIVE last-minus-first, ACROSS THE RESET ==
  series: http_requests_total{instance="app-1",job="api",route="/checkout",status="200"}
  rate(...[2m]) @ t=+165s  ->  samples in (+45s, +165s]
  raw values:  86  113  127  |RESET|  15  34  56  75
  naive (last - first) / 120s  =   -0.092 req/s   <- WRONG: the reset ate the traffic
  rate()  reset-aware          =   +1.105 req/s   <- correct

== sum by (route) (rate(http_requests_total[2m])) ==
  {route="/cart"}          2.50 req/s
  {route="/checkout"}      2.46 req/s
  fleet total              4.95 req/s   (8 series -> 2 groups, both instances folded in)
  error ratio              2.31 %       (sum(rate(...{status="500"})) / sum(rate(...)))

== histogram_quantile(0.99, sum by (le) (rate(..._bucket[2m]))) ==
  le=0.005    0.01 obs/s
  le=0.01     0.02 obs/s
  le=0.025    0.17 obs/s
  le=0.05     1.40 obs/s  #####
  le=0.1      4.61 obs/s  ##################
  le=0.25     4.72 obs/s  ##################
  le=0.5      4.72 obs/s  ##################
  le=1        4.72 obs/s  ##################
  le=2.5      4.92 obs/s  ###################
  le=5        4.95 obs/s  ###################
  le=+Inf     4.95 obs/s  ###################
  p50  =  0.067 s
  p90  =  0.098 s
  p99  =  2.343 s
```

Read the numbers, because one of them is the whole lesson. The **exposition block** is 2,097 bytes of plain text — that is the entire wire protocol; nothing was serialized, negotiated, or compressed. In the **scrape log**, watch `app-1`: it climbs 40, 80, 120 … 280, then at `+105s` the scrape fails and the row shows `up=0` with **one** stored sample. That one sample is the whole liveness story, and it cost you zero instrumentation. At `+120s` the counter reads **40, not 320** — the process restarted.

Now the centerpiece. For one series across that reset, the raw values are `86 113 127 |RESET| 15 34 56 75`. The **naive** last-minus-first calculation returns **-0.092 req/s**: a negative request rate, which is not a thing that exists. **`rate()` returns +1.105 req/s** — it saw 127 drop to 15, concluded "reset", added the pre-reset 127 back, and computed `(75 + 127) - 86 = 116` over the sampled span before extrapolating to the window edges. The difference between those two numbers is the difference between a dashboard you can trust and one that goes blank every deploy.

The last two sections show aggregation doing its job: **8 series folded into 2 route groups** totalling 4.95 req/s across *both* instances including the restarted one, an error ratio of **2.31%** computed as a ratio of two summed rates, and a p99 of **2.343 s** against a p50 of **0.067 s** — a 35× gap between the typical request and the tail. Every one of those numbers came from cumulative bucket counts summed across instances, exactly the pattern in the query above.

## Use It

### Configuring a real Prometheus

`prometheus.yml` is the whole configuration surface. Globals, then one block per job:

```yaml
global:
  scrape_interval: 15s          # the resolution of everything you will ever graph
  scrape_timeout: 10s           # must be < scrape_interval
  evaluation_interval: 15s      # how often recording/alerting rules run
  external_labels: {cluster: eu-prod}   # stamped on data leaving this server

rule_files:
  - recording_rules.yml
  - alerting_rules.yml

scrape_configs:
  - job_name: api               # 1. the literal list
    static_configs:
      - targets: ["10.0.1.11:8000", "10.0.1.12:8000"]
        labels: {env: prod}

  - job_name: kubernetes-pods   # 2. discovery + relabeling
    kubernetes_sd_configs: [{role: pod}]
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep            # opt-in: only pods annotated prometheus.io/scrape="true"
        regex: "true"
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace         # let a pod override the metrics path
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace # promote metadata into real, queryable labels
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
    sample_limit: 20000         # refuse a target that explodes in cardinality
```

The `__`-prefixed labels are internal: they exist during relabeling and are discarded before storage. `__address__` and `__metrics_path__` are the ones the scraper reads to build the URL.

### Instrumenting a Python service

In production you use the official `prometheus_client` rather than your own registry — it handles multiprocess mode, the standard process/GC collectors, and the format's edge cases. The API is the one you built:

```python
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

app = FastAPI()
REQUESTS = Counter("http_requests_total", "Total HTTP requests.", ["route", "status"])
LATENCY  = Histogram("http_request_duration_seconds", "Request duration.", ["route"],
                     buckets=(.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10))

@app.middleware("http")
async def instrument(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    r = request.scope.get("route")
    route = r.path if r else "unmatched"          # the TEMPLATE, never the raw URL
    REQUESTS.labels(route=route, status=str(response.status_code)).inc()
    LATENCY.labels(route=route).observe(time.perf_counter() - start)
    return response

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```

`route` must be the **route template** (`/orders/{id}`), never the raw path. `/orders/8842` as a label value gives you one series per order — the cardinality catastrophe from Phase 4 Lesson 5, restated in Prometheus's terms below.

### Rules you'll actually write

```yaml
# recording_rules.yml — precompute the expensive things
groups:
  - name: api.rules
    interval: 30s
    rules:
      - record: job:http_requests:rate5m
        expr: sum by (job, route) (rate(http_requests_total[5m]))
      - record: job:http_errors:ratio5m
        expr: |
          sum by (job, route) (rate(http_requests_total{status=~"5.."}[5m]))
            / ignoring(status) sum by (job, route) (rate(http_requests_total[5m]))
      - record: job:http_latency:p99_5m
        expr: histogram_quantile(0.99,
                sum by (job, route, le) (rate(http_request_duration_seconds_bucket[5m])))
```

The naming convention is `level:metric:operation` — the aggregation level, what's measured, what was done to it. It is not enforced, and following it is the difference between forty legible recording rules and forty mysteries.

```yaml
# alerting_rules.yml — a threshold, a patience, a label, a sentence
groups:
  - name: api.alerts
    rules:
      - alert: TargetDown
        expr: up == 0
        for: 2m                        # ignore a single failed scrape
        labels: {severity: page}
        annotations:
          summary: "{{ $labels.job }}/{{ $labels.instance }} has been unreachable for 2m"

      - alert: HighErrorRatio
        expr: job:http_errors:ratio5m > 0.05
        for: 10m                       # 10 minutes of sustained badness, not one spike
        labels: {severity: page}
        annotations:
          summary: "{{ $labels.route }} error ratio {{ $value | humanizePercentage }}"
```

`for` is the single most important field: it demands the condition hold continuously before the alert fires, which is what turns a noisy expression into a page worth waking up for. Lesson 10 builds the practice around it.

### The PromQL cookbook

```text
up == 0                                    # which targets are down
absent(up{job="api"})                      # the whole job vanished from discovery
topk(5, sum by (route) (rate(http_requests_total[5m])))       # busiest five routes

# Fraction of requests slower than 1s (an SLO-shaped query — Lesson 9)
1 - (sum(rate(http_request_duration_seconds_bucket{le="1"}[5m]))
     / sum(rate(http_request_duration_seconds_count[5m])))

# Mean latency, where the tail genuinely doesn't matter: _sum over _count
sum by (route) (rate(http_request_duration_seconds_sum[5m]))
  / sum by (route) (rate(http_request_duration_seconds_count[5m]))

# Saturation: memory used vs limit, worst pod first
topk(3, container_memory_working_set_bytes / container_spec_memory_limit_bytes)

# Disk-full projection: extrapolate the last 6h forward 4h
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 4*3600) < 0

changes(process_start_time_seconds[1h]) > 0   # did anything restart in the last hour?
count by (job) ({__name__=~".+"})             # how many series is each job costing you?
```

### Exporters: you rarely write one

For anything that isn't your own code there's already an **exporter** — a small process that translates some system's stats into the exposition format. `node_exporter` (CPU, memory, disk, network from a Linux host), `blackbox_exporter` (probes a URL, TCP port, or DNS name from the outside and reports success and latency), `postgres_exporter`, `redis_exporter`, `kafka_exporter`, `cloudwatch_exporter`. The rule: instrument your own code directly with a client library; use an exporter for everything else. Writing a new exporter is a thing you'll do roughly once in a career.

### Scaling out, honestly

One Prometheus goes remarkably far — millions of active series and hundreds of thousands of samples per second on a single well-provisioned machine. Its real limits are that it's a *single* node (no replication; the standard answer is to run two identical ones), its retention is bounded by local disk, and it can't answer a query spanning several clusters. Three escape hatches, in increasing order of commitment: **federation**, where one Prometheus scrapes *aggregated* series out of others (fine for a handful of top-level numbers, a trap if you try to copy everything); **`remote_write`**, which streams every sample to an external store; and a **long-term system** — Thanos, Mimir, or VictoriaMetrics — that takes those writes, deduplicates the pairs, downsamples for cheap long-range queries, and serves one global PromQL endpoint over all of it. Reach for them when you actually have the problem. Most teams add them years later than they think, and a single Prometheus with 30-day retention answers approximately every question anyone asks.

### Cardinality, in Prometheus's terms

Phase 4 Lesson 5 warned that cardinality kills a time-series database. Here is the same warning with the concrete numbers. Every unique label-value combination is a series, each costing roughly 1–3 KB of RAM in the head block. One `user_id` label on a busy endpoint is a million series — several gigabytes of memory for one metric, and an out-of-memory kill. The defences: keep label values low-cardinality and bounded (route *templates*, status *classes*, region, version — never IDs, emails, raw URLs, or error strings); set `sample_limit` per scrape config so a misbehaving target is dropped rather than absorbed; use `metric_relabel_configs` with a `drop` action as the emergency brake when something already shipped; and watch `prometheus_tsdb_head_series` and `scrape_samples_post_metric_relabeling` as first-class operational metrics. If you need per-user detail, that is what logs and traces are for — which is precisely the detail-versus-cost trade-off from Lesson 1.

## Think about it

1. Your service runs behind a NAT in a customer's data centre and cannot be reached by your Prometheus. Which of pull's advantages do you lose by switching that one service to `remote_write` through a local agent, and how would you replace the `up` signal you gave up?
2. A colleague sets `scrape_interval: 60s` to "reduce load" and keeps `rate(x[1m])` in every alert. Name two separate things that now break, and give the rule of thumb that prevents both.
3. `sum(rate(errors_total[5m]))` and `rate(sum(errors_total)[5m])` — the second isn't even valid PromQL, but the same mistake reappears as a recording rule that sums a counter and a later query that rates the result. Walk through what happens to the number when one of forty instances restarts.
4. Your p99 latency query returns exactly `2.5` for a straight hour, no matter what the traffic does. What does that tell you about your bucket boundaries, and what would you change?
5. A pod is deleted at 14:00. At 14:02 you query `sum(rate(http_requests_total[5m]))`. What does Prometheus do with that pod's series, and how would the answer differ if it instead reported zeros forever?

## Key takeaways

- **Prometheus pulls.** It scrapes `GET /metrics` on each target on a fixed interval, which buys you a free liveness signal (the synthetic **`up`** series — a failed scrape *is* the alert), central control of the sample rate, and `curl`-able local debugging. The costs are **service discovery** (`kubernetes_sd_configs` and friends, shaped by **`relabel_configs`**) and short-lived jobs, whose one sanctioned workaround is the **Pushgateway**.
- **The exposition format is plain text**: `# HELP`, `# TYPE`, then `name{label="value"} number` — one line per series, no timestamp (the scraper stamps it). A **histogram** decomposes into cumulative `_bucket{le="…"}` series plus `_sum` and `_count`. **OpenMetrics** is its standardized successor (`application/openmetrics-text`).
- **Storage is the TSDB you built in Phase 4 Lesson 5**: 2-hour blocks, delta-of-delta timestamps, XOR-compressed values (Gorilla), ~1–2 bytes per sample — plus an in-memory head block made durable by a **write-ahead log**, the Phase 3 Lesson 13 trick.
- **A counter's value is meaningless; its rate is not.** `rate(c[5m])` handles **counter resets** by treating any decrease as a restart and adding the pre-reset value back — the difference in the Build-It between `-0.092 req/s` (naive, and impossible) and `+1.105 req/s` (correct). Give it at least **4× the scrape interval** of window. `irate()` for spiky debugging, `increase()` for totals.
- **`rate` before `sum`, never the reverse** — summing counters first hides the individual resets that `rate()` needs to see. Aggregate with `sum by (…)` / `topk` *after* rating, compute percentiles with `histogram_quantile(0.99, sum by (le) (rate(..._bucket[5m])))` keeping `le`, and build ratios with `ignoring(…)` / `group_left` vector matching.
- **Operate it with rules and restraint**: **recording rules** (`level:metric:operation`) precompute expensive queries, **alerting rules** add `for`, `labels`, and `annotations`, exporters cover everything that isn't your code, and one Prometheus is enough for a very long time. The way you break it is **cardinality** — never a `user_id`, ID, or raw URL in a label; set `sample_limit` and watch your series count.

Next: [Distributed Tracing & OpenTelemetry](../07-distributed-tracing-and-opentelemetry/) — metrics told you *that* p99 is 2.3 seconds; only a trace can tell you *which hop* spent them.
