# Dashboards: RED, USE & Grafana

> A dashboard is not a picture of your system — it is a set of pre-answered questions, and a panel that answers no question is decoration you pay for in incident minutes. Two frameworks turn a wall of graphs into an instrument you can read under stress: **RED** for the services you write, **USE** for the resources they depend on. This lesson builds a Grafana dashboard from a declarative spec, then lints it against its own rules.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Prometheus: Pull, Exposition & PromQL](../06-prometheus-and-promql/), [SLIs, SLOs & Error Budgets](../09-slis-slos-and-error-budgets/)
**Time:** ~65 minutes

## The Problem

An incident starts at 03:07. You open the dashboard folder and there are **214 dashboards**, six of them named some variant of *Service Overview*. You pick one. It has **40 panels** in no particular order. Three of them are permanently blank — someone renamed a metric eight months ago and nothing told anyone. And the panel your eye lands on first, top-left, where attention is most expensive, is **average CPU across the fleet**.

Ten minutes of the incident are gone and you have learned nothing.

The shallow problem is that the dashboard is ugly. The deeper problem is how it got that way: it was built **by accretion**. Every incident added a panel; no incident ever removed one; and nobody ever wrote down *which question* each panel was supposed to answer. A panel with no question is a panel nobody can ever justify deleting, so it stays forever, and the signal-to-noise ratio only goes one way.

Then it gets worse than useless. Scroll down and there's a big reassuring panel titled `Latency` reading a comfortable **120 ms**, so you rule out slowness and go hunting elsewhere. That panel is a **mean across every route and every request**. What's actually happening is the tail you met in Lesson 5: p50 is 45 ms, p99 is 9.4 s, and roughly a tenth of your users are watching a spinner until their client times out. The mean is arithmetically correct and operationally a lie — it is the single most confidently wrong number in operations, and it is on the wall of nearly every company that has ever had an outage.

So: what does a dashboard that *helps* look like, and how do you get one without hand-clicking forty of them?

## The Concept

### A dashboard answers known questions fast — nothing more

Lesson 1 drew the line between **monitoring** (watching numbers you decided in advance mattered, for **known unknowns**) and **observability** (a property of the system: can you answer a question nobody anticipated, from data you already emit?). A dashboard sits squarely on the monitoring side of that line, and it is worth saying plainly:

**Dashboards do not make you observable. They make known answers fast.**

For the failure nobody predicted — "checkout fails only for Android clients on the new coupon path" — no pre-built panel exists, and building one takes longer than querying ad hoc. That's what PromQL (Lesson 6), log search (Lesson 4), and trace exploration (Lesson 7) are for. What a dashboard *is* extraordinarily good at is the first ninety seconds: is it broken, how badly, since when, and which layer. Judge every panel by that job, and by one test — **what question does this answer, and would I miss it at 03:00?**

### RED — the three numbers for a request-driven service

The **RED method** (named by Tom Wilkie) says every request-driven service — an HTTP API, a gRPC service, a queue consumer — is adequately summarised by exactly three signals, measured **per service and per route**:

- **R**ate — requests per second. Not a total; a rate. It's the context that makes the other two legible: 3 errors out of 4 requests and 3 out of 40,000 look identical on an error *count* panel.
- **E**rrors — failed requests, expressed as a **ratio** of the rate.
- **D**uration — how long requests take, as a **distribution** (p50/p90/p99), never a mean.

Here they are as real PromQL against the metric names you exposed in Lesson 6 (`$service` and `$route` are Grafana template variables — more on those below):

```text
# R — rate, per route
sum by (route) (rate(http_requests_total{service="$service", route=~"$route"}[5m]))

# E — error ratio. Both sides grouped by (route), so PromQL matches them
#     one-to-one on that label. Drop `by (route)` from one side and the
#     expression returns EMPTY — silently.
  sum by (route) (rate(http_requests_total{service="$service", route=~"$route", status=~"5.."}[5m]))
/ sum by (route) (rate(http_requests_total{service="$service", route=~"$route"}[5m]))

# D — duration, from histogram buckets. Sum the bucket RATES by `le` first,
#     then take the quantile: quantiles are not averageable across instances.
histogram_quantile(0.99,
  sum by (le) (rate(http_request_duration_seconds_bucket{service="$service", route=~"$route"}[5m])))
```

### USE — the three numbers for a resource

RED tells you a service is unhappy. It never tells you *why*. For that you need the **USE method** (Brendan Gregg), which applies not to services but to **resources** — anything with a finite capacity that requests queue for: CPU, memory, disk, network, **connection pools**, thread pools, work queues. For each one:

- **U**tilization — what fraction of the resource is busy.
- **S**aturation — how much work is **waiting** for it. Queue depth, wait time, number of blocked callers.
- **E**rrors — how often the resource refuses: timeouts, allocation failures, dropped packets.

**Saturation is the signal that predicts the outage, and it is the one almost nobody has.** Read that pair of sentences carefully, because it inverts the intuition most people bring:

> A resource at **100% utilization with an empty queue** is fine — it is fully used, which is what you paid for. A resource at **70% utilization with a growing queue** is about to fall over.

Utilization is bounded at 100% and therefore *saturates as a signal* right when you need it most; queue depth is unbounded and keeps climbing, so it warns you before the cliff and keeps telling the truth after it. You built the machinery for this twice already: the connection pool in Phase 3 Lesson 14 (100% of connections checked out is normal; *twenty threads blocked waiting for one* is an outage forming), and backpressure in Phase 8 (a queue that grows without bound is a system that has already failed, it just hasn't noticed).

### The Four Golden Signals, and how the three frameworks fit together

Google's SRE book proposes a third list — the **Four Golden Signals**: **latency, traffic, errors, saturation**. Look at it next to the other two and the relationship is obvious: it is essentially **RED plus saturation**, which is exactly the seam where a service-only view goes blind.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 400" width="100%" style="max-width:790px" role="img" aria-label="A coverage matrix of six signals against three monitoring frameworks. RED covers traffic, errors and duration for services. USE covers utilization, saturation and errors for resources. The Four Golden Signals cover the three service signals plus saturation, which is the only signal appearing in both a resource framework and the golden signals.">
  <text x="410" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three frameworks, one coverage map — what each is actually for</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="106" width="290" height="104" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="20" y="226" width="290" height="104" rx="11" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="318" y="262" width="480" height="34" rx="8" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="322" y="50" width="142" height="42" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="478" y="50" width="142" height="42" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="634" y="50" width="160" height="42" rx="9" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="393" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">RED</text>
    <text x="393" y="85" font-size="8.5" text-anchor="middle" opacity="0.85">Wilkie · services</text>
    <text x="549" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">USE</text>
    <text x="549" y="85" font-size="8.5" text-anchor="middle" opacity="0.85">Gregg · resources</text>
    <text x="714" y="70" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">GOLDEN</text>
    <text x="714" y="85" font-size="8.5" text-anchor="middle" opacity="0.85">Google SRE · users</text>
    <text x="34" y="128" font-size="10" font-weight="700" fill="#3553ff">WHAT YOU WRITE — services</text>
    <text x="34" y="152" font-size="11">Rate / Traffic</text>
    <text x="34" y="176" font-size="11">Errors of requests</text>
    <text x="34" y="200" font-size="11">Duration / Latency</text>
    <text x="34" y="248" font-size="10" font-weight="700" fill="#e0930f">WHAT YOU DEPEND ON — resources</text>
    <text x="34" y="272" font-size="11" font-weight="700">Saturation</text>
    <text x="34" y="296" font-size="11">Utilization</text>
    <text x="34" y="320" font-size="11">Errors of the resource</text>
    <g text-anchor="middle" font-size="11" font-weight="700">
      <text x="393" y="156" fill="#3553ff">yes</text>
      <text x="393" y="180" fill="#3553ff">yes</text>
      <text x="393" y="204" fill="#3553ff">yes</text>
      <text x="393" y="276" opacity="0.35">—</text>
      <text x="393" y="300" opacity="0.35">—</text>
      <text x="393" y="324" opacity="0.35">—</text>
      <text x="549" y="156" opacity="0.35">—</text>
      <text x="549" y="180" opacity="0.35">—</text>
      <text x="549" y="204" opacity="0.35">—</text>
      <text x="549" y="276" fill="#e0930f">yes</text>
      <text x="549" y="300" fill="#e0930f">yes</text>
      <text x="549" y="324" fill="#e0930f">yes</text>
      <text x="714" y="156" fill="#0fa07f">yes</text>
      <text x="714" y="180" fill="#0fa07f">yes</text>
      <text x="714" y="204" fill="#0fa07f">yes</text>
      <text x="714" y="276" fill="#0fa07f">yes</text>
      <text x="714" y="300" opacity="0.35">—</text>
      <text x="714" y="324" opacity="0.35">—</text>
    </g>
    <text x="410" y="356" font-size="11" text-anchor="middle" font-weight="700" fill="#7c5cff">Saturation is the only row two frameworks reach across — the gap RED alone leaves open</text>
    <text x="410" y="378" font-size="11" text-anchor="middle" opacity="0.9">The synthesis: RED for your services · USE for the things they depend on · Golden Signals as the checklist</text>
  </g>
</svg>
```

Read the matrix column by column. **RED** fills the top three rows and nothing else — it is complete for "how is the service treating users" and blind to "what is the service running out of." **USE** fills the bottom three and nothing else — it can tell you a pool is exhausted and never that customers noticed. **Golden Signals** take RED's three and reach down for exactly one resource row, **saturation**, because that's the one resource signal that predicts user-visible pain early enough to act on. The practical rule falls out of the picture:

| Framework | Applies to | Signals | Reach for it when |
|---|---|---|---|
| **RED** | request-driven services (HTTP, gRPC, consumers) | Rate, Errors, Duration | Building the default dashboard for *any* service you own |
| **USE** | resources with finite capacity (CPU, memory, disk, pools, queues) | Utilization, Saturation, Errors | A symptom alert fired and you need to find the constrained thing |
| **Four Golden Signals** | the user-facing whole | Latency, Traffic, Errors, Saturation | Auditing coverage — "did we forget saturation?" (you did) |

### Measure the latency of failed requests separately

One refinement that costs a label and saves an incident. During an outage, a service that has given up returns `500` in 8 ms — instantly. Those fast failures land in your latency histogram and **drag the percentiles down**, so the latency panel gets *healthier* as the outage gets worse. Split the histogram by outcome:

```text
histogram_quantile(0.99, sum by (le) (
  rate(http_request_duration_seconds_bucket{service="$service", outcome="failure"}[5m])))
```

This costs one extra label with exactly two values, so it multiplies the bucket series count by two — bounded, unlike the cardinality disasters of Phase 4 Lesson 5. Now "latency improved" and "everything is failing fast" are two different pictures instead of one.

### The dashboard hierarchy and the drill-down path

Three dashboards, three audiences, three questions. Most organisations have the middle one and neither of the others.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 486" width="100%" style="max-width:760px" role="img" aria-label="The dashboard drill-down path: an alert enters at the top, then you move from a business or journey dashboard asking whether the product works, to a service dashboard showing RED and SLO status, to a resource dashboard showing USE signals, and finally to traces and logs for a single request.">
  <defs>
    <marker id="l11-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The drill-down: each level narrows the blast radius by one order</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M390 92 L 390 108" marker-end="url(#l11-a1)"/>
    <path d="M390 180 L 390 196" marker-end="url(#l11-a1)"/>
    <path d="M390 268 L 390 284" marker-end="url(#l11-a1)"/>
    <path d="M390 356 L 390 372" marker-end="url(#l11-a1)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="150" y="46" width="470" height="46" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6" stroke-dasharray="6 5"/>
    <rect x="150" y="108" width="470" height="72" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="150" y="196" width="470" height="72" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="150" y="284" width="470" height="72" rx="11" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="150" y="372" width="470" height="72" rx="11" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="166" y="66" font-size="11" font-weight="700">ALERT  ·  03:07</text>
    <text x="166" y="82" font-size="9.5" opacity="0.85">checkout error budget burning 14x — a symptom, not a cause</text>
    <text x="166" y="130" font-size="11.5" font-weight="700" fill="#0fa07f">1 · BUSINESS / JOURNEY</text>
    <text x="166" y="148" font-size="10" opacity="0.92">"Is the product working?"</text>
    <text x="166" y="166" font-size="9.5" opacity="0.75">checkouts/min · signups · revenue · payment success rate</text>
    <text x="166" y="218" font-size="11.5" font-weight="700" fill="#3553ff">2 · SERVICE</text>
    <text x="166" y="236" font-size="10" opacity="0.92">"Which service, which route, and how bad?"</text>
    <text x="166" y="254" font-size="9.5" opacity="0.75">RED per route + SLO / error-budget status</text>
    <text x="166" y="306" font-size="11.5" font-weight="700" fill="#e0930f">3 · RESOURCE</text>
    <text x="166" y="324" font-size="10" opacity="0.92">"What is it running out of?"</text>
    <text x="166" y="342" font-size="9.5" opacity="0.75">USE per resource — pool saturation, CPU, queue depth</text>
    <text x="166" y="394" font-size="11.5" font-weight="700" fill="#7c5cff">4 · TRACES, THEN LOGS</text>
    <text x="166" y="412" font-size="10" opacity="0.92">"Which hop, and what did it say?"</text>
    <text x="166" y="430" font-size="9.5" opacity="0.75">one request's waterfall, then its log lines (Lessons 3 and 7)</text>
    <text x="636" y="140" font-size="9" opacity="0.75">everyone,</text>
    <text x="636" y="153" font-size="9" opacity="0.75">incl. non-eng</text>
    <text x="636" y="228" font-size="9" opacity="0.75">the owning</text>
    <text x="636" y="241" font-size="9" opacity="0.75">team</text>
    <text x="636" y="316" font-size="9" opacity="0.75">whoever is</text>
    <text x="636" y="329" font-size="9" opacity="0.75">debugging</text>
    <text x="636" y="404" font-size="9" opacity="0.75">one engineer,</text>
    <text x="636" y="417" font-size="9" opacity="0.75">one request</text>
    <g font-size="9.5" opacity="0.8"><text x="26" y="222">carry the</text><text x="26" y="238">TIME RANGE</text><text x="26" y="254">down every</text><text x="26" y="270">level — else</text><text x="26" y="286">it is four</text><text x="26" y="302">separate tabs</text></g>
    <text x="400" y="470" font-size="11" text-anchor="middle" opacity="0.9">Level 1 exists because green infrastructure with a broken product is the most common bad incident of all.</text>
  </g>
</svg>
```

Level 1 is the one teams skip and the one that catches the worst failures. Every server healthy, every RED panel green, and **checkouts/min has been zero for forty minutes** because a third-party payment redirect started 302-ing to a dead host — from your services' point of view, nothing failed at all. Notice also the left-hand note: the drill-down only works if the **time range travels with you**. Landing on a resource dashboard defaulted to "last 6 hours" when the incident began four minutes ago throws away the one thing you'd already established.

### Design rules that actually matter

Each rule below exists because of a specific way dashboards fail people at 03:00.

- **Most important panel top-left.** Readers scan in an F-pattern, so the top-left is the page's most valuable real estate and you get one shot at it. Put "do I need to act?" there — error-budget status or error ratio, never fleet-average CPU.
- **One question per panel, and the question *is* the title.** `What fraction of requests are failing?`, not `Errors`. A forcing function: if you can't phrase the question, the panel shouldn't exist.
- **Percentiles, not averages.** p50/p90/p99 on one axis shows the *shape* — a p99 pulling away from p50 is a tail forming, which a mean can never show (Lesson 5).
- **Consistent time range and units.** If one panel silently overrides the range to "last 24h," spikes stop lining up and you draw a false conclusion from two graphs that don't share an x-axis.
- **Few series per panel.** A 200-line spaghetti graph conveys nothing. Aggregate, use `topk`, or plot max-and-median instead of one line per instance.
- **Deploy and incident annotations on every time series.** The highest-value feature in the tool: *"what changed at 03:09?"* becomes a vertical line you can see rather than a Slack archaeology expedition.
- **Thresholds drawn on the panel.** `0.6` means nothing alone; `0.6` against a line marked *SLO* means everything.
- **Links out** — to the runbook, to logs pre-filtered to the same time range and service, and via **exemplars** from a latency bucket straight to a trace in that bucket (Lessons 6 and 7, joined up).
- **Colour used sparingly.** Red means bad, and only bad. Roughly 1 in 12 men has a red-green colour vision deficiency, so colour must never be the *only* channel carrying meaning — pair it with position, a threshold line, or a label.

Here is what those rules look like assembled:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="An annotated wireframe of a good RED dashboard: template variable pickers and a shared time range at the top, an error budget stat panel top-left, an error ratio panel, a latency percentile panel with vertical deploy annotation markers, a traffic row, and a USE row for dependencies. Seven numbered callouts on the right explain which design rule each choice follows.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A RED dashboard on Grafana's 24-column grid — every choice has a reason</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="44" width="566" height="386" rx="13" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.65"/>
    <rect x="38" y="58" width="104" height="24" rx="7" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff" stroke-width="1.5"/>
    <rect x="150" y="58" width="88" height="24" rx="7" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff" stroke-width="1.5"/>
    <rect x="462" y="58" width="114" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.55" stroke-width="1.5"/>
    <rect x="38" y="106" width="124" height="118" rx="9" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    <rect x="170" y="106" width="190" height="118" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="368" y="106" width="208" height="118" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="38" y="252" width="256" height="100" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="302" y="252" width="274" height="100" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="38" y="380" width="172" height="36" rx="8" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="218" y="380" width="172" height="36" rx="8" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="404" y="380" width="172" height="36" rx="8" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke-width="1.7">
    <path d="M378 208 L 404 204 L 430 206 L 456 202 L 482 199 L 508 200 L 534 197 L 566 198" stroke="#0fa07f" opacity="0.9"/>
    <path d="M378 190 L 404 187 L 430 189 L 456 184 L 482 186 L 508 181 L 534 183 L 566 180" stroke="#e0930f" opacity="0.9"/>
    <path d="M378 172 L 404 170 L 430 173 L 456 168 L 482 171 L 508 146 L 534 138 L 566 134" stroke="#7c5cff"/>
    <path d="M456 130 L 456 216" stroke="#7c5cff" stroke-dasharray="4 4" opacity="0.85"/>
    <path d="M508 130 L 508 216" stroke="#7c5cff" stroke-dasharray="4 4" opacity="0.85"/>
    <path d="M178 196 L 352 196" stroke="#e0930f" stroke-dasharray="5 4" opacity="0.9"/>
  </g>
  <g fill="none" stroke-width="1.6" opacity="0.9">
    <circle cx="52" cy="70" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="52" cy="120" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="184" cy="120" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="382" cy="120" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="482" cy="232" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="316" cy="266" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <circle cx="52" cy="394" r="9" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <g text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">
      <text x="52" y="74">1</text><text x="52" y="124">2</text><text x="184" y="124">3</text>
      <text x="382" y="124">4</text><text x="482" y="236">5</text><text x="316" y="270">6</text>
      <text x="52" y="398">7</text>
    </g>
    <text x="86" y="75" font-size="9.5" opacity="0.9">$service</text>
    <text x="194" y="75" font-size="9.5" opacity="0.9">$route</text>
    <text x="519" y="75" font-size="9.5" text-anchor="middle" opacity="0.9">now-6h · 30s</text>
    <text x="38" y="99" font-size="9" opacity="0.7">row: Is the service healthy right now?</text>
    <text x="100" y="152" font-size="9" text-anchor="middle" opacity="0.9">error budget</text>
    <text x="100" y="180" font-size="21" text-anchor="middle" font-weight="700" fill="#0fa07f">62%</text>
    <text x="100" y="202" font-size="8.5" text-anchor="middle" opacity="0.75">left of 30d</text>
    <text x="265" y="124" font-size="9" text-anchor="middle" opacity="0.9">error ratio by route</text>
    <text x="348" y="192" font-size="8" text-anchor="end" fill="#e0930f">SLO</text>
    <text x="472" y="124" font-size="9" text-anchor="middle" opacity="0.9">latency p50 / p90 / p99</text>
    <text x="574" y="134" font-size="8" text-anchor="end" fill="#7c5cff">p99</text>
    <text x="574" y="184" font-size="8" text-anchor="end" fill="#e0930f">p90</text>
    <text x="574" y="202" font-size="8" text-anchor="end" fill="#0fa07f">p50</text>
    <text x="463" y="128" font-size="7.5" fill="#7c5cff">v412</text>
    <text x="515" y="128" font-size="7.5" fill="#7c5cff">v413</text>
    <text x="38" y="245" font-size="9" opacity="0.7">row: Traffic and failure latency</text>
    <text x="166" y="272" font-size="9" text-anchor="middle" opacity="0.9">requests/sec by route</text>
    <text x="439" y="272" font-size="9" text-anchor="middle" opacity="0.9">p99 failed vs. p99 succeeded</text>
    <text x="38" y="373" font-size="9" opacity="0.7">row: Dependency — db pool (USE)</text>
    <text x="124" y="403" font-size="8.5" text-anchor="middle" opacity="0.9">waiters (saturation)</text>
    <text x="304" y="403" font-size="8.5" text-anchor="middle" opacity="0.9">in-use / max</text>
    <text x="490" y="403" font-size="8.5" text-anchor="middle" opacity="0.9">acquire timeouts</text>
    <g font-size="9.5" font-weight="700">
      <text x="612" y="66">1  ONE dashboard, every service</text>
      <text x="612" y="116">2  Top-left = act, or not?</text>
      <text x="612" y="166">3  A ratio, with its threshold drawn</text>
      <text x="612" y="216">4  Percentiles on ONE axis</text>
      <text x="612" y="266">5  Deploy annotations</text>
      <text x="612" y="316">6  Failed latency kept separate</text>
      <text x="612" y="366">7  USE for the dependencies</text>
    </g>
    <g font-size="9.5" opacity="0.85">
      <text x="612" y="80">$service / $route variables, not 40 copies</text>
      <text x="612" y="130">F-pattern: the eye lands here first</text>
      <text x="612" y="180">a number needs a line to mean anything</text>
      <text x="612" y="230">the shape of the tail, not a mean</text>
      <text x="612" y="280">"what changed at 03:09?" answered visually</text>
      <text x="612" y="330">a fast 500 must not flatter the graph</text>
      <text x="612" y="380">saturation predicts, utilization confirms</text>
      <text x="612" y="424" opacity="0.8">every panel links out to a runbook, to logs,</text>
      <text x="612" y="438" opacity="0.8">and (via exemplars) to one real trace</text>
    </g>
  </g>
</svg>
```

The whole diagram is readable as one sentence: **glance top-left for "do I act?", scan right for "how bad and how slow?", look down for "what is it running out of?", and click out when you need one request instead of all of them.** Note callout 5 in particular — the two dashed vertical markers labelled `v412` and `v413` are deploy annotations, and the p99 line lifts off immediately after the second one. That is a root cause found in three seconds of looking, and no query was written.

### Anti-patterns, named

Name them so you can call them out in review:

- **Averages** — the mean latency panel reading 120 ms while a tenth of users time out.
- **Dual y-axes** — two unrelated scales on one plot; any apparent correlation is an artifact of where you set the bounds.
- **Vanity metrics** — total signups since launch, cumulative requests served. They only go up, so they can never signal anything.
- **The wall-of-TV dashboard** — sixty panels on an office screen nobody has looked at since the day it was mounted.
- **Dashboards that duplicate alerts** — if a condition matters enough to stare at, it should page you (Lesson 10). A dashboard is what you open *after* the page.
- **Per-instance panels at fleet scale** — one line per pod is fine at 3 pods and unreadable at 300.
- **Silent breakage on metric renames** — a panel querying a metric that no longer exists renders as an empty graph, which looks identical to "everything is fine."

### Dashboards as code

Click a dashboard together in the UI and you have an artifact with no history, no review, no test, and exactly one copy, living in a database you probably don't back up. At 40 services that collapses: nobody can answer "who changed this panel and why," fixing a bug in the error-ratio query means editing it 40 times, and a new service arrives with no dashboard at all.

Every Grafana dashboard is fundamentally a **JSON document** — the *dashboard JSON model*. Accept that and the whole software-engineering toolkit applies: generate it from a template, keep it in git, review changes in a pull request, and **provision it from files** so the running dashboard is a deployment artifact rather than mutable UI state. Terraform and Grafonnet (a Jsonnet library) are the two common production paths. The payoff: **one templated service dashboard, generated for N services, fixed once.**

### Grafana's vocabulary

Six words, so the rest reads cleanly. A **data source** is a backend Grafana queries (your Prometheus, Loki, Tempo). A **panel** is one visualization — `timeseries`, `stat`, `table`, `heatmap`. A **target** is one query on a panel; a panel may have several (p50, p90, p99 are three targets). A **variable** (templating) is a named placeholder like `$service`, filled from a dropdown or a `label_values()` query — this is what turns one dashboard into every service's dashboard. A **row** is a labelled, collapsible group of panels. **Time range and refresh** are shared by every panel (`now-6h`, refresh `30s`). Panels are positioned on a **24-column grid** via `gridPos: {h, w, x, y}`, where `w` is in columns (24 = full width) and `h` is in ~30-pixel units.

## Build It

[`code/dashboard_gen.py`](code/dashboard_gen.py) turns a declarative spec into a real Grafana dashboard JSON model, packs the panels onto the 24-column grid, and lints the result against the rules above. Standard library only.

The spec layer is deliberately tiny — this is everything a human writes:

```python
@dataclass(frozen=True)
class Service:
    """A request-driven service. RED applies to these."""
    name: str
    routes: tuple[str, ...]
    slo_target: float               # e.g. 0.999 = three nines of successful requests
    slo_window: str = "30d"


@dataclass(frozen=True)
class Resource:
    """A thing a service consumes and can run out of. USE applies to these."""
    name: str
    kind: str                       # "cpu" | "pool" | "queue"
```

`red_panels()` builds the three RED queries. The error-ratio expression is the one worth staring at — both sides are grouped `by (route)`, which is what lets PromQL match them one-to-one:

```python
def red_panels(svc: Service) -> list[Panel]:
    rate_expr = f'sum by (route) (\n  rate(http_requests_total{{{SEL}}}[5m])\n)'
    # The error ratio divides two vectors. Both sides are grouped `by (route)`, so
    # every label set on the left has exactly one partner on the right: PromQL's
    # one-to-one vector matching. Drop `by (route)` from one side and you get an
    # empty result, silently.
    err_expr = (f'sum by (route) (rate(http_requests_total{{{SEL}, status=~"5.."}}[5m]))\n'
                f'  /\n'
                f'sum by (route) (rate(http_requests_total{{{SEL}}}[5m]))')

    def quantile(q: float, extra: str = "") -> str:
        sel = SEL + extra
        return (f'histogram_quantile({q},\n'
                f'  sum by (le) (rate(http_request_duration_seconds_bucket{{{sel}}}[5m]))\n)')
```

`slo_panel()` derives its query arithmetically from the target — budget remaining is `1 − (observed bad ratio ÷ allowed bad ratio)`, so changing `0.999` to `0.9995` rewrites the divisor correctly, and the number goes negative when you've overspent.

The layout engine is a shelf-packing loop. Nothing hand-places a coordinate; importance decides what lands top-left:

```python
def layout(sections: list[Section]) -> list[dict]:
    """Assign gridPos by packing left-to-right, wrapping at column 24.

    Panels are sorted by descending importance first, so the panel you most need
    under stress lands at x=0, y=top -- where the eye starts (F-pattern reading).
    Python's sort is stable, so equal-importance panels keep declaration order.
    """
    out: list[dict] = []
    pid, y = 1, 0
    for sec in sections:
        out.append({"id": pid, "type": "row", "title": sec.title, "collapsed": False,
                    "gridPos": {"h": 1, "w": GRID_COLUMNS, "x": 0, "y": y}, "panels": []})
        pid, y = pid + 1, y + 1
        x = row_h = 0
        for panel in sorted(sec.panels, key=lambda p: -p.importance):
            if x + panel.w > GRID_COLUMNS:              # wrap to a new shelf
                y, x, row_h = y + row_h, 0, 0
            out.append(panel.to_json(pid, {"h": panel.h, "w": panel.w, "x": x, "y": y}))
            pid, x, row_h = pid + 1, x + panel.w, max(row_h, panel.h)
        y += row_h
    return out
```

The linter makes this lesson's rules executable — nine of them, one per design rule. The grid check is the neat one: walk every panel claiming each `(column, row)` cell it covers into a dict, and then **overlaps are the cells claimed twice** while **gaps are the cells inside the bounding box nobody claimed at all** — one pass, both failures.

The rest — the `Panel` dataclass and its Grafana JSON serialization, the USE query templates per resource kind, the templating and annotation blocks, the wireframe renderer, and a deliberately awful `legacy_dashboard()` fixture — is in [`code/dashboard_gen.py`](code/dashboard_gen.py). Run it:

```bash
python3 dashboard_gen.py
```

```console
$ python3 dashboard_gen.py
== 1 · THE SPEC (what a human writes) ==
  Service(name='checkout-service', routes=('/checkout', '/cart', '/health'), slo_target=0.999, slo_window='30d')
  Resource(name='db connection pool', kind='pool')
  Resource(name='cpu', kind='cpu')
  -> 11 panels, 4 rows, 13398 bytes of dashboard JSON

== 2 · PANELS THE GENERATOR PRODUCED ==
  gridPos (h,w,x,y)    unit         title
                                    [row] Is the service healthy right now?  (RED + SLO)
  8,6,0,1              percentunit  Is the error budget still healthy?
  8,9,6,1              percentunit  What fraction of requests are failing?
  8,9,15,1             s            How slow is a request, at each percentile?
                                    [row] Traffic and failure latency  (RED)
  8,12,0,10            reqps        How many requests per second, by route?
  8,12,12,10           s            How slow are the requests that FAILED?
                                    [row] Dependency: db connection pool  (USE)
  6,8,0,19             short        How many callers are waiting for a connection?
  6,8,8,19             percentunit  How much of the pool is checked out?
  6,8,16,19            ops          How often does acquiring a connection fail?
                                    [row] Dependency: cpu  (USE)
  6,8,0,26             short        Is work waiting for a CPU?
  6,8,8,26             percentunit  How much CPU is in use?
  6,8,16,26            percentunit  Is the CPU being throttled?

== 3 · THE PACKED GRID (24 columns, most important panel top-left) ==

  == Is the service healthy right now?  (RED + SLO) ========================
  +-----------------------+-----------------------------------+-----------------------------------+
  | Is the error budget   | What fraction of requests are     | How slow is a request, at each    |
  | still healthy?        | failing?                          | percentile?                       |
  +-----------------------+-----------------------------------+-----------------------------------+

  == Traffic and failure latency  (RED) ====================================
  +-----------------------------------------------+-----------------------------------------------+
  | How many requests per second, by route?       | How slow are the requests that FAILED?        |
  |                                               |                                               |
  +-----------------------------------------------+-----------------------------------------------+

  == Dependency: db connection pool  (USE) =================================
  +-------------------------------+-------------------------------+-------------------------------+
  | How many callers are waiting  | How much of the pool is       | How often does acquiring a    |
  | for a connection?             | checked out?                  | connection fail?              |
  +-------------------------------+-------------------------------+-------------------------------+

  == Dependency: cpu  (USE) ================================================
  +-------------------------------+-------------------------------+-------------------------------+
  | Is work waiting for a CPU?    | How much CPU is in use?       | Is the CPU being throttled?   |
  |                               |                               |                               |
  +-------------------------------+-------------------------------+-------------------------------+

[sections 4 and 5 print the panel, templating and annotation JSON — reproduced in Use It]

== 6 · LINT ==
  dashboard: checkout-service · RED + USE
  PASS -- 0 findings against 9 rules

  dashboard: Service Overview (legacy)
  FAIL -- 24 findings across 8 rules
    [title-is-a-question]  x17  a panel with no question is decoration
        - CPU
        - Average latency
        - Requests by pod
        - ... and 14 more
    [unit-declared]  x1  a bare number means nothing at 03:00
        - CPU
    [no-average-latency]  x1  averages hide the tail -- use histogram_quantile
        - Average latency
    [no-per-instance-fanout]  x1  one line per instance is spaghetti at fleet scale
        - Requests by pod
    [consistent-time-range]  x1  panel overrides the dashboard range (timeFrom='24h') -- spikes stop lining up
        - Errors last 24h
    [panel-budget]  x1  17 panels (limit 16) -- built by accretion, nobody ever deleted one
        - Service Overview (legacy)
    [grid-no-overlap]  x1  48 grid cells claimed twice -- panels stack unpredictably when the browser is narrow
        - Service Overview (legacy)
    [grid-no-gaps]  x1  48 empty grid cells inside the layout
        - Service Overview (legacy)
```

Read the numbers. **Three lines of spec produced 11 panels and 13,398 bytes of Grafana JSON** — that ratio is the entire argument for dashboards as code, and it is why regenerating for a 40th service costs one line. Section 2 shows the packer's output: the SLO stat got `x=0, y=1` — **top-left**, because it declared the highest importance — and each shelf sums to exactly 24 columns (`6+9+9`, `12+12`, `8+8+8`), which is why the grid check reports no gaps. Notice the USE rows too: `How many callers are waiting for a connection?` was placed *first* in its row, ahead of utilization, because saturation carries the higher importance in the generator. Section 3's wireframe is the layout as the browser will render it, drawn straight from the `gridPos` values rather than described.

Section 6 is the point of the exercise. The generated dashboard passes **9 rules with 0 findings** — not because it was written carefully, but because the generator cannot express a violation: every title is a question by construction, every panel carries a unit, and the packer cannot leave a hole. The legacy fixture — the *Service Overview* from The Problem — produces **24 findings across 8 rules** from 17 panels. `Average latency` trips `no-average-latency` because it divides `_sum` by `_count`, the classic mean-latency idiom. `Errors last 24h` sets `timeFrom: "24h"`, so its spikes will never line up with the panel beside it. And the grid check finds **48 cells claimed twice and 48 empty** — two panels literally overlapping, with a dead zone beside them, which is exactly what a dashboard grown by six years of drag-and-drop looks like from the inside.

## Use It

**The panel JSON.** Section 4 of the run prints a complete panel you could paste into Grafana's import dialog. The fields that matter:

```json
{
  "id": 2,
  "type": "stat",
  "title": "Is the error budget still healthy?",
  "datasource": { "type": "prometheus", "uid": "${datasource}" },
  "gridPos": { "h": 8, "w": 6, "x": 0, "y": 1 },
  "fieldConfig": {
    "defaults": {
      "unit": "percentunit",
      "thresholds": { "mode": "absolute", "steps": [
        { "color": "red", "value": null },
        { "color": "orange", "value": 0.0 },
        { "color": "green", "value": 0.25 } ] } } },
  "links": [ { "title": "SLO policy", "url": "https://runbooks.internal/slo/checkout-service" } ],
  "targets": [ { "refId": "A", "expr": "1 - (...) / 0.00100", "legendFormat": "budget remaining" } ]
}
```

`gridPos` places it. `unit` makes `0.62` render as `62%` instead of a naked float. `thresholds.steps` colour the number — the first step always has `"value": null`, meaning "everything below the next step." `links` is the runbook; `targets` holds the queries.

**Provisioning from files.** Point Grafana at a directory and it loads every dashboard JSON in it at startup — no clicking, no manual import, no drift:

```yaml
# /etc/grafana/provisioning/dashboards/dashboards.yaml
apiVersion: 1
providers:
  - name: 'services'
    orgId: 1
    folder: 'Services'
    type: file
    disableDeletion: true      # the files are the source of truth
    allowUiUpdates: false      # edits in the UI cannot silently diverge from git
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
```

The workflow that follows: `dashboard_gen.py` writes JSON into `/var/lib/grafana/dashboards/`, CI runs the linter and fails the build on findings, the pull-request diff shows exactly which query changed, and Grafana picks it up within 30 seconds. `allowUiUpdates: false` is the load-bearing line — without it a well-meaning browser edit gets silently overwritten on the next deploy, and everyone stops trusting the system.

**Variables and repeated panels.** `$route` is a query variable, populated from label values Prometheus already has:

```json
{
  "name": "route", "type": "query", "label": "Route",
  "query": "label_values(http_requests_total{service=\"$service\"}, route)",
  "refresh": 2, "includeAll": true, "allValue": ".*", "multi": true
}
```

`refresh: 2` re-runs the query when the time range changes, so routes that stopped existing drop out of the list. `includeAll` with `allValue: ".*"` is what makes `route=~"$route"` work as a match-everything default. Grafana can also **repeat** a panel or a whole row once per selected variable value — set `"repeat": "route"` and you get one row per route, generated at render time. Between templating and repeats, one dashboard file covers every service you own.

**Annotations for deploy markers.** The generated dashboard ships this annotation query:

```json
{
  "name": "Deploys", "enable": true, "iconColor": "purple",
  "datasource": { "type": "prometheus", "uid": "${datasource}" },
  "expr": "changes(process_start_time_seconds{service=\"$service\"}[$__interval]) > 0",
  "titleFormat": "deploy", "textFormat": "{{version}}"
}
```

`process_start_time_seconds` is a standard Prometheus client metric — the Unix time the process started — so `changes(...) > 0` fires exactly when a process restarted, which is what a deploy looks like from the metrics layer. Grafana draws a vertical line at each match, on every time-series panel. Alternatives: a **Loki** log query (`{job="deployer"} |= "deploy finished"`), or your CD pipeline `POST`ing to Grafana's annotations API at the end of each rollout — the most reliable option, because it carries the version and commit SHA:

```http
POST /api/annotations HTTP/1.1
Content-Type: application/json

{"dashboardUID":"svc-red-use","time":1721289600000,"tags":["deploy","checkout-service"],"text":"v413 · a1b2c3d"}
```

**Exemplars: from a latency bucket to a trace.** Lesson 6 showed histograms, Lesson 7 showed traces; exemplars are the wire that joins them. A Prometheus client can attach a trace ID to a histogram observation, exposed alongside the bucket:

```text
http_request_duration_seconds_bucket{route="/checkout",le="2.5"} 4711 # {trace_id="4bf92f3577b34da6"} 2.31 1721289612
```

Everything after the `#` is the exemplar: a sample observation, its value, and the labels identifying it. Set `exemplar: true` on the panel target (the generator does), configure the Prometheus data source with an exemplar trace-ID link pointing at Tempo or Jaeger, and every latency graph grows small diamonds. Click the diamond on the p99 spike and you land on the trace waterfall for a request *that was actually that slow* — Lesson 1's "metric alerts you, trace localizes it" handoff, made one click long.

**Grafana Alerting vs. Prometheus rules — one honest paragraph.** Both evaluate a PromQL expression on a schedule and fire. Prometheus alerting rules live next to the data, evaluate inside Prometheus, survive Grafana being down, and version cleanly as YAML alongside the rest of your infrastructure — which is why alerts that page a human generally belong there (Lesson 10). Grafana Alerting evaluates in Grafana, can join conditions **across data sources** (a Prometheus metric and a Loki log count in one rule), and is far easier for a team that doesn't own the Prometheus config. The failure mode is running both for the same condition: two systems, two thresholds, eventually two pages for one incident. Pick one per alert and write down which.

**The rollout that works.** One templated dashboard for all services beats 40 bespoke ones — one place to fix a query, and a new service gets a working dashboard on its first deploy. Then **delete aggressively**: track which dashboards were opened during the last three incidents, and treat the rest as candidates: deleting them is safe precisely because the generator can recreate any of them. Add one line to every incident review — *did the dashboard help, and what panel would have helped faster?* — then change the generator, and every service gets the improvement at once. That compounding return is what hand-clicked dashboards can never earn.

## Think about it

1. Your service dashboard is entirely green — rate normal, errors near zero, p99 flat — and support is drowning in reports that checkout is broken. Which level of the hierarchy would have caught this, and what specific panel would you add?
2. A connection pool sits at 100% utilization all day and the service is healthy. The next day it's at 70% and requests are timing out. Explain both observations using utilization and saturation, and say which panel you'd put top-left on that resource's row.
3. During an outage your p99 latency panel *improves* while the error ratio climbs. What is happening, which refinement in this lesson explains it, and what does it cost in metric cardinality (Phase 4, Lesson 5)?
4. You have 214 dashboards and want to get to 20. What criterion decides which survive, and what has to be true about how the survivors are built before deleting the rest is safe?
5. The linter enforces "every panel title ends with a question mark." That's a syntactic check standing in for a semantic property. What property is it actually trying to enforce, and what's a panel that passes the check while violating the spirit?

## Key takeaways

- A dashboard **answers known questions fast**; it does not make you observable. Unknown unknowns need ad-hoc querying, not a pre-built panel. Every panel must name the question it answers — put that question in the title, and delete the panel if you can't write one.
- **RED** (Rate, Errors, Duration) covers request-driven **services**, per route: `sum by (route) (rate(...))`, an error **ratio** with both sides grouped identically so PromQL matches one-to-one, and `histogram_quantile(0.99, sum by (le) (rate(..._bucket[5m])))` — never a mean.
- **USE** (Utilization, Saturation, Errors) covers **resources** — CPU, memory, disk, connection pools, queues. **Saturation is the predictive signal and the one most often missing**: 100% utilization with an empty queue is fine, 70% with a growing queue is about to fall over. The **Four Golden Signals** are essentially RED + saturation. The synthesis: **RED for your services, USE for what they depend on.**
- Build **three levels** — business/journey ("is the product working?"), service (RED + SLO), resource (USE) — and drill down through them **carrying the time range**, ending at traces and logs. Green infrastructure with a broken product is the most common bad incident there is.
- The rules that pay: most important panel **top-left**, one question per panel, **percentiles not averages**, consistent time ranges and units, few series per panel, **deploy annotations** on every time series, thresholds drawn on the panel, and links out to runbooks, logs and **exemplars** that jump to a trace. Measure **failed-request latency separately** — a fast 500 flatters the graph during an outage.
- A Grafana dashboard is a **JSON document** on a 24-column grid, so generate it, version it in git, review it, **provision it from files** with `allowUiUpdates: false`, and lint it in CI. One templated dashboard with `$service` / `$route` variables beats 40 hand-clicked ones, and makes deleting the other 194 safe.

Next: [Capstone: Debugging a Real Incident](../12-capstone-debugging-an-incident/) — everything in this phase pointed at one broken system: a page fires, and you use the logs, metrics, traces, SLOs, alerts and dashboards you built to find the cause and write the postmortem.
