# Capstone: Debugging a Real Incident

> Eleven lessons built the instruments. This one hands you a running, fully instrumented four-service checkout path that is quietly on fire, and a pager that just went off. You will not read the source to find the fault — you will follow the signals, the way you will at 03:11 on a Tuesday: a burn-rate alert wakes you, a dashboard narrows it to one service, an exemplar drops you into one trace, a waterfall names the guilty span, and one log line ends the argument. Ten million requests to one log line, in five queries.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Structured Logging](../02-structured-logging/) · [Correlation & Request Context](../03-correlation-and-request-context/) · [Metrics from Scratch](../05-metrics-from-scratch/) · [Prometheus & PromQL](../06-prometheus-and-promql/) · [Distributed Tracing & OpenTelemetry](../07-distributed-tracing-and-opentelemetry/) · [SLIs, SLOs & Error Budgets](../09-slis-slos-and-error-budgets/) · [Alerting & On-Call](../10-alerting-and-on-call/) · [Dashboards: RED, USE & Grafana](../11-dashboards-red-and-use/)
**Time:** ~120 minutes

## The Problem

Your phone goes off at **03:11:30**. Not a human this time — a machine:

```text
[PAGE]  SLOErrorBudgetFastBurn                     severity=critical
        slo        checkout-availability  99.9% over 30d
        burn_rate  72.9x
        runbook    /runbooks/checkout-availability
```

That is the entire report. Behind it, real people are failing to buy things, and you have about six minutes before someone senior asks what is happening. Your situation: **four services** touch one checkout — `gateway`, `orders`, `payments`, and a third-party `bank-api`, over a `postgres` shared by the first two of yours — and any of them could be the fault. **Nobody deployed to `gateway` or `orders`**; somebody deployed to `payments` four minutes ago, described as "add fraud-score lookup to charge path", which sounds like nothing. **CPU and memory are fine** — you will check, because everyone checks, and they will tell you nothing. And **you cannot reproduce it**: it only appears above a traffic level you cannot generate on your laptop.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 420" width="100%" style="max-width:920px" role="img" aria-label="The checkout path under investigation: a gateway calls orders, which calls payments, which holds one of four postgres connections while it works and then calls the bank API. Orders retries once on failure. Every service carries a question mark because at page time any of them could be the fault.">
  <defs>
    <marker id="l12-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="480" y="22" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The checkout path — at 03:11 the fault could be in any of these boxes</text>
  <g fill="none" stroke="currentColor" stroke-width="1.7">
    <path d="M148 105 L212 105" marker-end="url(#l12-a1)"/>
    <path d="M350 105 L418 105" marker-end="url(#l12-a1)"/>
    <path d="M702 105 L770 105" marker-end="url(#l12-a1)"/>
    <path d="M344 80 C 362 48, 242 48, 260 80" marker-end="url(#l12-a1)" stroke-dasharray="5 4" opacity="0.8"/>
    <path d="M258 132 C 258 226, 330 236, 392 300" marker-end="url(#l12-a1)" opacity="0.7"/>
    <path d="M520 216 C 520 262, 502 272, 488 300" marker-end="url(#l12-a1)" opacity="0.7"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="78" width="124" height="54" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="218" y="78" width="132" height="54" rx="11" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="424" y="62" width="278" height="176" rx="13" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    <rect x="776" y="78" width="160" height="54" rx="11" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="360" y="306" width="210" height="52" rx="11" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="444" y="104" width="238" height="112" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-opacity="0.75" stroke-dasharray="6 4"/>
    <g fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"><rect x="486" y="136" width="34" height="22" rx="5"/><rect x="526" y="136" width="34" height="22" rx="5"/><rect x="566" y="136" width="34" height="22" rx="5"/><rect x="606" y="136" width="34" height="22" rx="5"/></g>
  </g>
  <g fill="none" stroke-width="1.8" fill-opacity="0.20">
    <circle cx="140" cy="86" r="11" fill="#3553ff" stroke="#3553ff"/><circle cx="342" cy="86" r="11" fill="#7c5cff" stroke="#7c5cff"/><circle cx="694" cy="70" r="11" fill="#0fa07f" stroke="#0fa07f"/>
    <circle cx="928" cy="86" r="11" fill="#7f7f7f" stroke="currentColor" stroke-opacity="0.7"/><circle cx="562" cy="314" r="11" fill="#e0930f" stroke="#e0930f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <g font-size="12" font-weight="700"><text x="140" y="90">?</text><text x="342" y="90">?</text><text x="694" y="74">?</text><text x="928" y="90">?</text><text x="562" y="318">?</text></g>
    <text x="86" y="102" font-size="11.5" font-weight="700">gateway</text>
    <text x="86" y="119" font-size="8.5" opacity="0.75">the edge</text>
    <text x="284" y="102" font-size="11.5" font-weight="700">orders</text>
    <text x="284" y="119" font-size="8.5" opacity="0.75">checkout logic</text>
    <text x="563" y="84" font-size="12" font-weight="700">payments</text>
    <text x="856" y="102" font-size="11.5" font-weight="700">bank-api</text>
    <text x="856" y="119" font-size="8.5" opacity="0.75">third party</text>
    <text x="465" y="330" font-size="11.5" font-weight="700">postgres</text>
    <text x="465" y="347" font-size="8.5" opacity="0.8">shared by orders and payments</text>
    <text x="563" y="124" font-size="9.5" opacity="0.9">connection pool</text>
    <g font-size="8"><text x="503" y="151">c1</text><text x="543" y="151">c2</text><text x="583" y="151">c3</text><text x="623" y="151">c4</text></g>
    <text x="563" y="180" font-size="8.5" opacity="0.8">4 connections, held for the whole block of work</text>
    <text x="563" y="196" font-size="8.5" opacity="0.62">callers queue when all four are busy</text>
    <g font-size="8.5" opacity="0.8"><text x="180" y="97">POST /orders</text><text x="384" y="97">POST /charge</text><text x="736" y="97">/authorize</text></g>
    <text x="302" y="44" font-size="8.5" opacity="0.85">retry ×1 on failure</text>
    <text x="86" y="68" font-size="8.5" opacity="0.8">POST /checkout</text>
    <text x="480" y="400" font-size="10.5" opacity="0.9">Four services, one pool, one retry loop. The page says checkout is failing. It does not say where.</text>
  </g>
</svg>
```

Every question mark is a hypothesis you must eliminate in order, under time pressure, with users losing money throughout. This lesson is that hour. The code you run builds the instrumented system *and* the tools to interrogate it; the investigation that follows never opens the source file.

## The Concept

### The investigation loop — and why mitigation comes before understanding

An incident is a loop, not a puzzle, and its steps have a fixed order: **detect → triage → mitigate → localize → explain → fix → learn**.

The counterintuitive part is that **mitigate sits third, before you understand anything**. Every instinct says "find the cause first" — that instinct is what turns a 9-minute incident into a 90-minute one. Users do not care why checkout is broken; they care that it is. So the moment triage implicates *a change or a knob*, you take the cheapest action that restores the signal: **roll back** the correlated deploy (usually best — fast, reversible, needs no theory of the bug), **shed load** so the surviving fraction succeeds (Phase 8's backpressure argument under duress), **flip the feature flag**, or **raise the limit** that is saturating. Only then do you localize and explain. This is Lesson 10's whole point: an alert is a call to action, and the action is "make it stop", not "start a research project". Note the tail of the loop too — **fix** (the durable change, shipped in daylight with tests) is not **mitigate**, and **learn** (the blameless postmortem) is the only step that shortens the *next* incident.

### MTTD and MTTR: where the time actually goes

Two averages measure how good you are at this. **MTTD — Mean Time To Detect** — runs from user impact to a human knowing; bad MTTD is "a customer emailed us", good MTTD is an alert on an **SLO** (Service Level Objective — the target you promise, e.g. 99.9% of checkouts succeed) measured by an **SLI** (Service Level Indicator — the number that actually measures it). It is almost purely a *monitoring* problem: you either wrote the alert or you didn't. **MTTR — Mean Time To Resolve** (some teams say Repair or Recover; pick one and be consistent) runs from user impact to impact ending.

Break MTTR into phases and one dominates. In a badly instrumented system, detection might cost 15 minutes, triage 20, **localization 100+**, explanation 20, mitigation 20. **Localization — "which of the eleven services is it?" — is where hours die**, because without traces the only way to answer is to open eleven dashboards, correlate eleven graphs by eyeball, and argue. Every other phase is bounded by human speed; localization is bounded by search-space size.

That is the honest case for distributed tracing, and it is a narrow one: **tracing detects nothing and explains nothing. It collapses localization from an hour to one click.** In the run below, detection is 45 seconds, localization is a single query, and total MTTR is 8 minutes 45 seconds.

### The funnel, restated as a procedure

Lesson 1 introduced the funnel as an idea: *a metric alerts you → a trace localizes the bad hop → a log explains it.* Here it is as five queries you can actually type, with the search space each one destroys.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 512" width="100%" style="max-width:920px" role="img" aria-label="The investigation funnel as five concrete queries: a burn-rate alert over ten million requests, a RED dashboard narrowing to one service, an exemplar narrowing to one trace, a span waterfall narrowing to one span, and a trace-id log filter narrowing to one log line — seven orders of magnitude in total.">
  <text x="470" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The funnel as a procedure — every query throws away an order of magnitude</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="54" width="556" height="70" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="30" y="142" width="556" height="70" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <rect x="30" y="230" width="556" height="70" rx="11" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="30" y="318" width="556" height="70" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="30" y="406" width="556" height="70" rx="11" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="618" y="78" width="290" height="28" rx="6" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff"/>
    <rect x="643" y="166" width="265" height="28" rx="6" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
    <rect x="726" y="254" width="182" height="28" rx="6" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="869" y="342" width="39" height="28" rx="6" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/>
    <rect x="886" y="430" width="22" height="28" rx="6" fill="#7f7f7f" fill-opacity="0.24" stroke="currentColor" stroke-opacity="0.7"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="48" y="78" font-size="11.5" font-weight="700" fill="#3553ff">1 · BURN-RATE ALERT — is it broken?</text>
    <text x="48" y="98" font-size="8.7" opacity="0.88">sum(rate(http_requests_total{service="gateway",status=~"5.."}[5m]))</text>
    <text x="48" y="113" font-size="8.7" opacity="0.68">  / sum(rate(http_requests_total{service="gateway"}[5m])) / 0.001  &gt;  14.4</text>
    <text x="48" y="166" font-size="11.5" font-weight="700" fill="#7c5cff">2 · RED DASHBOARD — which service?</text>
    <text x="48" y="186" font-size="8.7" opacity="0.88">sum by (service) (rate(http_requests_total[5m]))  ·  histogram_quantile(0.99, …)</text>
    <text x="48" y="201" font-size="8.7" opacity="0.68">eliminates: bank-api p99 24 ms · cpu 41% · memory 58% — every one of them normal</text>
    <text x="48" y="254" font-size="11.5" font-weight="700" fill="#e0930f">3 · EXEMPLAR — which request?</text>
    <text x="48" y="274" font-size="8.7" opacity="0.88">http_request_duration_seconds_bucket{service="gateway",le="3"}  →  trace_id</text>
    <text x="48" y="289" font-size="8.7" opacity="0.68">a metric can never name a request; the exemplar stapled to the bucket can</text>
    <text x="48" y="342" font-size="11.5" font-weight="700" fill="#0fa07f">4 · SPAN WATERFALL — which hop?</text>
    <text x="48" y="362" font-size="8.7" opacity="0.88">open trace 0e7650f8… in Tempo or Jaeger — nine spans, drawn to scale</text>
    <text x="48" y="377" font-size="8.7" opacity="0.68">one span is 1,985 ms of 2,031 ms: 98% of the request, sitting in plain sight</text>
    <text x="48" y="430" font-size="11.5" font-weight="700">5 · LOGS BY trace_id — why?</text>
    <text x="48" y="450" font-size="8.7" opacity="0.88">{service="payments"} | json | trace_id="0e7650f8…"</text>
    <text x="48" y="465" font-size="8.7" opacity="0.68">the fields that span could not carry — the sentence that ends the search</text>
    <g font-size="10" font-weight="700" text-anchor="end"><text x="908" y="70">10,000,000 requests</text><text x="908" y="158">2,500,000 requests</text><text x="908" y="246">25,000 requests</text><text x="908" y="334">9 spans</text><text x="908" y="422">1 log line</text></g>
    <g font-size="8.7" opacity="0.75" text-anchor="end"><text x="908" y="130">÷ 4</text><text x="908" y="218">÷ 100</text><text x="908" y="306">÷ 2,800</text><text x="908" y="394">÷ 9</text></g>
    <text x="470" y="500" font-size="11" text-anchor="middle" opacity="0.9">Five queries. Ten million requests down to one log line — seven orders of magnitude, in under two minutes.</text>
  </g>
</svg>
```

Stage 2 there is the **RED** method (Rate, Errors, Duration — Lesson 11), and stage 5 is **LogQL**, Loki's query language. Read the right-hand column as the honest measure of an observability stack: **how fast does the search space shrink per query you type?** A stack with logs only shrinks it by grep-luck. A stack with all three pillars and a shared `trace_id` shrinks it by construction, and each pillar hands the next one a *pointer* — the alert hands you a service, the exemplar hands you a trace ID, the span hands you a service and a time range, and the trace ID hands you the log lines. Take away the shared ID (Lesson 3) and every arrow in that diagram becomes a guess.

## Build It

`code/incident.py` builds three things with nothing but the standard library: **the system** (four services on a simulated clock, a real first-in-first-out connection-pool queue, retries), **the telemetry** (a metric store with cumulative counters and `le` histogram buckets, a log store, a head-sampled trace store), and **the tooling** (`promql_rate`, `histogram_quantile`, `burn_rate`, exemplar lookup, log filtering, a waterfall renderer).

**The file contains the fault. Do not read it yet.** Run it, and let the telemetry tell you — that is the entire exercise.

The metric store is Lesson 5's histogram with one addition that matters enormously here — an **exemplar**, the trace ID that OpenMetrics lets you staple onto a bucket so an aggregate can point back at an individual:

```python
def observe(self, name, labels, value, ts=0.0, trace_id=None):
    h = self.hists.setdefault((name, labels), [0.0] * (len(BUCKETS) + 2))
    for i, upper in enumerate(BUCKETS):        # cumulative: one observation
        if value <= upper:                     # lands in every bucket le >= value
            h[i] += 1
    h[-2] += value                             # _sum
    h[-1] += 1                                 # _count
    if trace_id is not None:                   # OpenMetrics exemplar: pin a trace
        le = next((b for b in BUCKETS if value <= b), math.inf)
        self.exemplars.setdefault((name, labels, le), []).append((ts, trace_id, value))
```

The connection pool is the one piece of the simulated system worth showing, because it is an ordinary queue and queues have ordinary, brutal mathematics. It hands out a fixed number of connections; a caller that arrives when all of them are busy waits for the earliest release, and that wait is recorded — as its own span *and* as a `pool_wait_seconds` histogram:

```python
class Pool:
    """A fixed-size FIFO connection pool. Every acquire reports the wait it paid."""

    def acquire(self, t, hold):
        """Return (wait, acquired_at), or None if the caller gave up waiting."""
        earliest = heapq.heappop(self.free_at)
        acquired_at = max(t, earliest)
        wait = acquired_at - t
        if wait > POOL_TIMEOUT_S:
            heapq.heappush(self.free_at, earliest)      # untouched: nobody was served
            return None
        heapq.heappush(self.free_at, acquired_at + hold)
        return wait, acquired_at
```

The query side rebuilds just enough of **PromQL** (Prometheus Query Language) — `promql_rate` differentiates a cumulative counter over a window exactly as Lesson 6 did, and `burn_rate` divides the resulting error ratio by the error budget:

```python
def burn_rate(m, start, end, slo=SLO_AVAILABILITY):
    """How many times faster than 'even' the error budget is being spent."""
    return promql_error_ratio(m, "gateway", start, end) / (1.0 - slo)
```

The rest — the four services, the retry logic, the log and trace stores, `promql_rate`, `histogram_quantile`, `exemplar()`, `waterfall()`, and the eight investigation steps — is in [`code/incident.py`](code/incident.py). Run it:

```bash
python3 incident.py
```

### Step 1 — Detect

```console
== STEP 1 . DETECT ==
  SLO   99.9% of POST /checkout requests succeed, 30-day window
  rule  sum(rate(http_requests_total{service="gateway",status=~"5.."}[5m]))
          / sum(rate(http_requests_total{service="gateway"}[5m])) / 0.001 > 14.4
  evaluated at     err ratio   burn rate
  03:10:00.000        0.000%        0.0x
  03:11:00.000        0.000%        0.0x
  03:11:30.000        7.286%       72.9x   <-- FIRING
  03:12:00.000        6.560%       65.6x
  03:13:00.000        4.313%       43.1x
  03:14:00.000        3.877%       38.8x
  03:15:00.000        3.160%       31.6x
  03:16:00.000        3.264%       32.6x

  [PAGE]  SLOErrorBudgetFastBurn                     severity=critical
          fired      03:11:30.000  ->  primary on-call
          slo        checkout-availability  99.9% over 30d
          burn_rate  72.9x   (>14.4x = 2% of a 30-day budget in one hour)
          exhausts   the whole 30-day error budget in 9.9 hours at this rate
          runbook    /runbooks/checkout-availability
```

Read what the alert did and did not do. It fired on **user-visible failure**, not a resource threshold: an SLO of 99.9% leaves an **error budget** of 0.1%, so an error ratio of 7.286% burns that budget **72.9× faster than the 30-day pace** — the whole month's allowance gone in under 10 hours. That is Lesson 9's arithmetic and Lesson 10's threshold: 14.4× is the burn rate at which 2% of a 30-day budget disappears in one hour, which is precisely what justifies waking a human. Notice it did *not* fire at 03:11:00 — the ratio was still zero over that window. **Detection costs you the width of the evaluation window**, and that cost is your MTTD.

### Step 2 — Triage

```console
== STEP 2 . TRIAGE ==
  RED per service, window 03:10:00.000 -> 03:16:00.000
  service        req/s    errors       p50       p99
  gateway         99.1     3.26%     2284ms     4825ms
  orders          99.1     3.26%     2276ms     4825ms
  payments       112.1    14.48%     2234ms     2985ms
  bank-api       191.7     0.00%       24ms       78ms

  the same table for the baseline 03:05:00.000 -> 03:07:00.000
  service        req/s    errors       p50       p99
  gateway         40.3     0.00%       39ms       95ms
  payments        40.3     0.00%       36ms       77ms

  the usual suspects -- avg_over_time(...[5m]), now vs baseline
  service           cpu   cpu base        mem   mem base
  gateway         33.8%      26.3%      58.0%      56.7%
  orders          39.8%      30.4%      58.0%      56.7%
  payments        41.5%      29.7%      58.2%      56.7%
```

This is Lesson 11's RED table, per service, and it eliminates three hypotheses in one screen. **`bank-api` is innocent**: 24 ms median, 78 ms at the 99th percentile, zero errors; the third party everyone blames first is fine. **`gateway` and `orders` are identical** — same rate, same error ratio, same p99 — the signature of a service merely *reporting* someone else's pain. And **`payments` is the deepest service that is still slow**, with a *higher* error ratio (14.48%) than its callers (3.26%), which is only possible if something upstream is masking failures.

Then the numbers that matter most by being boring. **CPU moved from ~30% to ~41%; memory did not move at all**, while traffic went from 40 to 99 requests per second. Whatever is broken is **not a resource the operating system knows how to report** — Lesson 10's symptom-versus-cause argument in one table. Had you alerted on CPU you would still be asleep; had you triaged by CPU you would now be arguing the system is healthy while checkout burns. Note the p50 too: **39 ms before, 2,284 ms during.** Not a tail problem — the *typical* checkout got 58× slower.

### Step 3 — Localize

```console
== STEP 3 . LOCALIZE ==
  exemplar attached to bucket le="3" of
    http_request_duration_seconds_bucket{service="gateway",route="/checkout"}
    -> 03:15:59.259  trace_id=0e7650f8e763c743092c63ad2ae38b8b  2031 ms
  find_traces(min_duration=1s): 3416 of 3711 sampled traces in the window (92%)

  WATERFALL  trace_id=0e7650f8e763c743092c63ad2ae38b8b
  SPAN                                         ms  0                                        2.03s
  gateway POST /checkout                   2030.9  ##############################################
    orders POST /orders                    2028.9  ##############################################
      postgres db.query order_insert          4.7  #
      orders POST payments/charge          2022.4  ##############################################
        payments POST /charge              2022.4  ##############################################
          payments pool.acquire            1985.1  #############################################  <--
          postgres db.query charge_txn       10.2  .............................................#
          bank-api GET /fraud-score          17.8  .............................................#
          bank-api POST /authorize            8.1  .............................................#
```

There it is, and it took one query. The **exemplar** is the bridge Lesson 5 built and Lesson 7 depends on: the bucket `le="3"` counts requests between 2 and 3 seconds but, being an aggregate, can never name one — except that Prometheus stapled a `trace_id` to the most recent observation that landed there. Click the spike, land on a request.

Now read the waterfall as a budget. The request took **2,030.9 ms**, and `pool.acquire` — waiting for a database connection, doing no work at all — took **1,985.1 ms, or 97.7%** of it. Every span that does actual work is tiny: the transactional write 10.2 ms, the fraud-score call 17.8 ms, the card authorization 8.1 ms. **36 ms of work, 1,985 ms of queueing.** And `find_traces` says this is not one unlucky request: 92% of sampled traces in the window are over a second. Nine spans drawn to scale, and the answer is visually unmissable. The alternative — reading four dashboards and inferring which service owns the missing two seconds — is the hour that tracing deletes.

### Step 4 — Explain

A span tells you *where*, not *why*: it carries timing and a name, not the fifteen fields the code had in scope. For that you filter the logs by the same `trace_id` (Lesson 3's entire reason for existing):

```console
== STEP 4 . EXPLAIN ==
  {service=~".+"} | json | trace_id="0e7650f8e763c743092c63ad2ae38b8b"
  03:15:59.222 payments WARN  pool_acquire_slow   pool=postgres wait_ms=1985.1 pool_size=4 attempt=1
  03:15:59.258 payments INFO  charge_completed    pool_wait_ms=1985.1 db_ms=10.2 fraud_lookup_ms=17.8 bank_ms=8.1 duration_ms=2022.4
  03:15:59.258 orders   INFO  order_completed     status=200 attempts=1 duration_ms=2028.9
  03:15:59.259 gateway  INFO  http_request        route=/checkout method=POST status=200 duration_ms=2030.9

  one request proves nothing -- aggregate the same event over the window:
  sum(count_over_time({service="payments"} | json | event="pool_acquire_slow" [5m]))
    39428 lines over 360s = 109.5/s, against 112.1 charge attempts/s = 98% of them
    wait_ms among them:  p50 1968   p99 2000   max 2000
  the identical query over 03:05:00.000 -> 03:09:00.000 (before the ramp): 0 lines
```

`pool_size=4`. The `payments` service holds **four** connections to postgres, and a charge waited 1,985 ms for one of them. That is the sentence the whole funnel existed to deliver, and no dashboard could have shown it to you — `pool_size` is a field on an event, not a time series.

Then the discipline that separates an engineer from a guesser: **one request proves nothing; the aggregate does.** 39,428 `pool_acquire_slow` events over six minutes — 98% of every charge attempted — and **zero** over the four minutes before the ramp. The wait is not merely slow, it is *pinned*: p50 1,968 ms, p99 2,000 ms, max 2,000 ms. A distribution flat against a ceiling is a queue that is full and hitting a timeout every single time. Little's Law, uninvited: a pool of 4 serves at most `4 / hold_time` requests per second, and when arrivals exceed that the wait does not degrade gracefully — it grows until something caps it.

### Step 5 — Correlate with change

You know *what* is failing, but not *why tonight* — pool size 4 did not change tonight. Line the metrics up against the deploy annotations:

```console
== STEP 5 . CORRELATE WITH CHANGE ==
  deploy annotation  03:07:00.000  payments v2.4.1  "add fraud-score lookup to charge path"
  t               req/s    p99 gw  fraud p99   pool used pool wait p99
  03:06:00.000     40.9       95ms   no route        0.34          5ms
  03:07:00.000     39.9       95ms   no route        0.41          5ms  <-- deploy
  03:08:00.000     39.9      199ms       89ms        1.41         23ms
  03:09:00.000     40.7      217ms       89ms        1.69         34ms
  03:10:00.000     69.2      468ms       88ms        2.63        446ms  <-- ramp
  03:11:00.000     95.9     4103ms       89ms        3.96       1988ms
  03:12:00.000    100.9     4882ms       88ms        4.00       1995ms
  03:13:00.000     97.9     4838ms       88ms        4.00       1995ms
  03:14:00.000     99.4     4863ms       89ms        4.00       1995ms
  03:15:00.000     97.2     4787ms       89ms        4.00       1995ms
  03:16:00.000     99.9     4842ms       89ms        4.00       1995ms
```

Now the whole thing falls out, and it falls out of *one column*. At 03:06 and 03:07 there is **no `/fraud-score` route at all** — the endpoint does not exist. From 03:08 it does, and in that same minute **`pool used` jumps from 0.41 to 1.41 connections at identical traffic**: same 40 requests per second, 3.4× more of the pool consumed. v2.4.1 did not add load, it added *hold time*. The new fraud-score call sits **inside the block that holds a database connection**, so every charge now occupies a connection for the write *plus* an 89 ms round trip to a third party. That is the whole bug — and notice how ordinary it looks in review: a synchronous call, in the right service, doing a legitimate thing, two lines below where the transaction begins.

Then read the four minutes of silence. From 03:07 to 03:09 **nothing breaks**: p99 creeps from 95 ms to 217 ms, only 1.7 of 4 connections are in use, and nobody would notice. The change is a latent fault, armed and waiting. At 03:09 traffic climbs, at 03:10 `pool used` hits 2.63, and by 03:11 it is pinned at **4.00 of 4** — 100% utilization — with the wait exploding from 34 ms to 1,988 ms. A queue at 100% utilization has, in theory, infinite waiting time; in practice it has whatever your timeout is.

This is the shape of most serious production incidents: **a change ships, nothing happens, and the system fails later when an unrelated variable moves.** It is why "did it break right after the deploy?" is the wrong question, "did anything change today?" is the right one, and deploy annotations belong on every dashboard.

### Step 6 — Confirm the amplifier

```console
== STEP 6 . CONFIRM THE AMPLIFIER ==
  sum(rate(http_requests_total{service="orders"}[5m]))       99.1 /s  one per checkout
  sum(rate(http_requests_total{service="payments"}[5m]))    112.1 /s  one per ATTEMPT
  amplification                                             1.13x
  the same ratio in the baseline window                     1.00x
  {service="orders"} | event="payment_call_failed"          5077 lines (14.1/s)
  whole run: 49520 checkouts -> 53596 attempts (4076 retries)

  what the retry budget buys, and what it costs -- same traffic, same fault:
  max attempts           attempts     load    errors        p99
  1  (no retry)             49520    1.00x     3.20%      2968ms
  2  (as configured)        53596    1.08x     3.26%      4825ms
  4                         65113    1.31x     3.01%      9558ms
```

`orders` receives 99.1 requests per second and issues 112.1 to `payments`. In the baseline window that ratio was exactly **1.00×**; now it is **1.13×**. Those 13 extra requests per second are retries, aimed at **the one resource already acting as the bottleneck** — the positive feedback loop behind a retry storm, the same self-inflicted wound as the cache stampede in [Phase 5, Lesson 6](../../05-caching/06-cache-stampede/).

The three-row table is more interesting than "retries bad". More attempts **buy almost no availability** — a single attempt fails 3.20% of the time and four attempts still fail 3.01%, because the pool, not luck, is the constraint. What retries actually cost is **latency and load**: 8% more traffic and a 4,825 ms p99 at two attempts; 31% more traffic and a **9,558 ms** p99 at four. The user who "succeeds" after four attempts waited nine and a half seconds and has closed the tab, and every extra attempt lengthened the queue for everyone else. Retries transfer pain from the unlucky request to the whole system — which is why they need a **budget** (cap retries at a few percent of traffic) and a **circuit breaker** (stop calling a dependency that is failing), not just a `max_attempts` constant.

### Steps 7 and 8 — Mitigate, then learn

```console
== STEP 7 . MITIGATE ==
  re-run the identical timeline and traffic, one variable changed
  scenario                        errors       p50       p99   pool used
  as it happened                   3.26%     2284ms     4825ms        3.99
  roll back payments v2.4.1        0.00%       39ms       95ms        1.02
  keep v2.4.1, pool 4 -> 16        0.00%       75ms      182ms        4.12
  the hypothesis predicted both rows. Rolling back ships in one minute and
  needs no capacity review, so it is the MITIGATION; the pool size is the FIX.

== STEP 8 . LEARN ==
  deploy of payments v2.4.1  03:07:00.000
  onset                      03:10:45.000  (p99 crosses 1s)
  detected / paged           03:11:30.000  MTTD = 45 s
  rollback triggered         03:16:00.000
  SLI healthy again          03:19:30.000  MTTR = 525 s (8.8 min)
  localization -- the usual bulk of MTTR -- was STEP 3: one exemplar click.

  OBSERVABILITY GAPS FOUND (each becomes an action item)
  1 db_pool_utilization_ratio read 1.00 (baseline 0.09) with NO alert and NO
    dashboard panel. It was the first signal to move and nobody was watching.
  2 the RED dashboard has no saturation row: USE says every resource needs
    utilization + saturation + errors, and the pool is a resource.
  3 orders retries with no budget: 1.13x extra load onto the one resource
    that was already the bottleneck, and it doubled p99 (STEP 6). Add a
    retry budget and a circuit breaker so a slow dependency is not retried.
  4 no metric for time-a-connection-is-held per code path, so the deploy that
    quadrupled it looked identical to every other deploy on every dashboard.
```

A hypothesis you cannot test is a story. This one is testable: re-run the identical timeline with one variable changed and it must predict the outcome. **Rolling back v2.4.1 takes the error ratio to 0.00% and p99 from 4,825 ms to 95 ms** — the baseline, exactly. **Enlarging the pool from 4 to 16 while keeping the bad code also fixes it** (0.00% errors, p99 182 ms), and the `pool used` column shows why: 4.12 connections busy out of 16 instead of 4.00 out of 4. Both rows follow from "the pool saturated"; nothing else explains both.

They are not the same action, though. **Roll back** is one command, needs no theory, and cannot make things worse — the *mitigation*. **Raising the pool** spends postgres connections other services also need (Phase 3, Lesson 14: `max_connections` is a global budget and pools are how you spend it), so it needs a capacity review — the *fix*, shipped tomorrow in daylight alongside moving the fraud call out of the connection-holding block.

The last block is the only part of an incident that compounds. **MTTD was 45 seconds** because an SLO alert existed; **MTTR was 8 minutes 45 seconds** because localization cost one query. Every gap is the same species: the pool was a **resource nobody measured as a resource**. `db_pool_utilization_ratio` went 0.09 → 1.00 — the *first* signal to move, minutes ahead of any user-facing metric — and no alert and no panel were watching it.

## Use It

Everything above simulates a stack you will actually run. Here is the same investigation, tool by tool.

| Step | In the simulation | In production |
|---|---|---|
| Detect | `burn_rate()` over the metric store | Prometheus recording + alerting rule, routed by Alertmanager to PagerDuty |
| Triage | `promql_rate`, `histogram_quantile` | PromQL against a Grafana RED dashboard |
| Localize | `exemplar(...)` then `waterfall(...)` | Click the exemplar dot on a Grafana heatmap → Tempo/Jaeger trace view |
| Explain | `logs.query(trace_id=...)` | LogQL in Loki (or `trace.id:` in Elasticsearch) |
| Correlate | the `DEPLOYS` list | Grafana annotations fed by your CI/CD pipeline |
| Mitigate | re-run with a flag flipped | `kubectl rollout undo`, or flip the feature flag |

The **alert** is a Prometheus rule plus an Alertmanager route. `for: 2m` is what stops a 30-second blip from waking anyone (Lesson 10):

```yaml
groups:
  - name: checkout-slo
    rules:
      - record: slo:checkout_error_ratio:rate5m
        expr: |
          sum(rate(http_requests_total{service="gateway",status=~"5.."}[5m]))
            / sum(rate(http_requests_total{service="gateway"}[5m]))
      - record: slo:checkout_error_ratio:rate1h
        expr: |
          sum(rate(http_requests_total{service="gateway",status=~"5.."}[1h]))
            / sum(rate(http_requests_total{service="gateway"}[1h]))
      - alert: SLOErrorBudgetFastBurn
        expr: |
          slo:checkout_error_ratio:rate5m / 0.001 > 14.4
            and slo:checkout_error_ratio:rate1h / 0.001 > 14.4
        for: 2m
        labels: {severity: critical}
        annotations:
          summary: "checkout burning error budget at {{ $value | printf \"%.1f\" }}x"
          runbook_url: "https://runbooks.internal/checkout-availability"
```

Production pairs a **short window with a long one** (`5m and 1h`) so a brief spike cannot page you and a resolved incident stops paging quickly — the simulation had only ten minutes of data, so it evaluated the short window alone.

The RED panels are three PromQL queries; the **USE** panels below them — Utilization, Saturation, Errors, one row per resource — are the ones this incident proves you were missing. The **exemplar** turns the metrics-to-traces jump into one click, provided your histogram is scraped with exemplars enabled and Grafana's Prometheus data source has an internal link to Tempo. The **LogQL** filter narrows by label selector first — Loki charges for bytes scanned, so that is not style, it is your bill (Lesson 4):

```text
sum by (service) (rate(http_requests_total[5m]))                           # RED: rate
sum by (service) (rate(http_requests_total{status=~"5.."}[5m]))
  / sum by (service) (rate(http_requests_total[5m]))                       # RED: errors
histogram_quantile(0.99,
  sum by (service, le) (rate(http_request_duration_seconds_bucket[5m])))   # RED: duration
db_pool_connections_in_use / db_pool_max                                   # USE: utilization
histogram_quantile(0.99, sum by (le) (rate(pool_wait_seconds_bucket[5m]))) # USE: saturation

# The exposition line with an exemplar attached (OpenMetrics):
http_request_duration_seconds_bucket{service="gateway",le="3.0"} 25000 # {trace_id="0e7650f8e763c743092c63ad2ae38b8b"} 2.031 1773544559

# LogQL, in Loki:
{service="payments"} | json | trace_id="0e7650f8e763c743092c63ad2ae38b8b"
sum(count_over_time({service="payments"} | json | event="pool_acquire_slow" [5m]))
{service="orders"} | json | event="payment_call_failed" | line_format "{{.reason}}"
```

### The postmortem

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 940 392" width="100%" style="max-width:920px" role="img" aria-label="The incident timeline from the 03:07 deploy through onset at 03:10:45, the page at 03:11:30, rollback at 03:16 and recovery at 03:19:30, with the 99th-percentile latency curve overlaid on a log scale and MTTD and MTTR brackets marked underneath.">
  <text x="470" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The incident, end to end — MTTD 45 s, MTTR 8 min 45 s</text>
  <rect x="380" y="100" width="473" height="190" fill="#e0930f" fill-opacity="0.09"/>
  <g fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.28"><path d="M70 250 L880 250"/><path d="M70 110 L880 110"/></g>
  <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="5 5" opacity="0.5">
    <path d="M178 74 L178 290"/><path d="M380 74 L380 290"/><path d="M421 74 L421 290"/><path d="M664 74 L664 290"/><path d="M853 74 L853 290"/>
  </g>
  <path d="M70 290 L880 290" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <polyline points="124,250 178,250 232,224 286,221 340,193 394,116 448,110 502,110 556,110 610,111 664,110 718,142 772,199 853,250" fill="none" stroke="#3553ff" stroke-width="2.6" stroke-linejoin="round"/>
  <g fill="none" stroke-width="2"><path d="M380 322 L380 330 L421 330 L421 322" stroke="#0fa07f"/><path d="M380 352 L380 360 L853 360 L853 352" stroke="#7c5cff"/></g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="62" y="254" font-size="9" text-anchor="end" opacity="0.8">95 ms</text>
    <text x="62" y="114" font-size="9" text-anchor="end" opacity="0.8">4.9 s</text>
    <text x="74" y="90" font-size="9" opacity="0.8">p99 checkout latency (log scale)</text>
    <g font-size="9" text-anchor="middle" opacity="0.8"><text x="70" y="308">03:05</text><text x="340" y="308">03:10</text><text x="610" y="308">03:15</text><text x="880" y="308">03:20</text></g>
    <text x="178" y="54" font-size="9.5" text-anchor="middle" font-weight="700">03:07:00 deploy</text>
    <text x="178" y="68" font-size="8.5" text-anchor="middle" opacity="0.75">payments v2.4.1</text>
    <text x="374" y="54" font-size="9.5" text-anchor="end" font-weight="700">03:10:45 onset</text>
    <text x="374" y="68" font-size="8.5" text-anchor="end" opacity="0.75">p99 &gt; 1 s</text>
    <text x="427" y="54" font-size="9.5" font-weight="700" fill="#e0930f">03:11:30 PAGE</text>
    <text x="427" y="68" font-size="8.5" opacity="0.75">burn 72.9×</text>
    <text x="664" y="54" font-size="9.5" text-anchor="middle" font-weight="700">03:16:00 rollback</text>
    <text x="853" y="54" font-size="9.5" text-anchor="end" font-weight="700">03:19:30 recovered</text>
    <text x="374" y="334" font-size="9.5" text-anchor="end" font-weight="700" fill="#0fa07f">MTTD 45 s</text>
    <text x="616" y="352" font-size="9.5" text-anchor="middle" font-weight="700" fill="#7c5cff">MTTR 8 min 45 s   (onset → SLI healthy again)</text>
    <text x="470" y="384" font-size="10.5" text-anchor="middle" opacity="0.9">Detection was fast because the SLO was the alert. Localization was fast because the trace already existed.</text>
  </g>
</svg>
```

A postmortem has four jobs: say what happened, say what it cost, say why nobody caught it sooner, and produce **owned action items**. It is **blameless** — the target is the system that let a routine change arm a latent fault, never the engineer who wrote it.

| | |
|---|---|
| **Impact** | 8 min 45 s of degraded checkout; 3.26% of checkouts failed; p50 39 ms → 2,284 ms; ~7% of the 30-day error budget spent. |
| **Trigger** | `payments` v2.4.1 added a synchronous fraud-score call *inside* a block holding a postgres connection, raising hold time ~4×. Latent for 3 minutes at low traffic. |
| **Cause** | The `payments` postgres pool (size 4) saturated once traffic passed `4 / hold_time` ≈ 100 rps. Requests queued; `orders` retried, adding 13% more load to the bottleneck. |
| **Detect / mitigate** | `SLOErrorBudgetFastBurn` 45 s after onset; rollback of v2.4.1. |

| # | Action item | Gap it closes | Owner |
|---|---|---|---|
| 1 | Alert `db_pool_utilization_ratio > 0.8 for 10m` → ticket, not page | The first signal to move had no alert on it | payments |
| 2 | Add a USE row (utilization, saturation, errors) for every pool to the dashboard template | RED alone is blind to resource exhaustion inside a healthy-looking service | platform |
| 3 | Retry budget (≤10% of requests) + circuit breaker on the `orders` → `payments` client | Unbudgeted retries loaded the bottleneck and doubled p99 | orders |
| 4 | Histogram of connection **hold time** per code path; alert on p99 > 50 ms | The change that quadrupled hold time was invisible on every dashboard | payments |

Item 4 carries the general lesson: **this incident happened because a resource was consumed along a dimension nobody measured** — not requests, not CPU, but *time a connection was held*. When an incident ends with "we had no metric for that", the metric is the deliverable.

## Think about it

1. The `bank-api` p99 was 78 ms throughout, yet the bank was directly implicated in the cause. Explain how a fast dependency can still take down the service that calls it — and what that says about judging dependencies by their own latency.
2. At 03:08 the pool utilization jumped 3.4× at identical traffic, three minutes before any user noticed. What alert would have caught that, what threshold would you set, and would you page or ticket on it? What is the cost of getting that threshold wrong in each direction?
3. Retries at 4 attempts produced *fewer* errors and a *worse* p99 than at 2. Argue for and against raising the retry budget during an incident, then say what you would actually configure and why.
4. Suppose the trace store had been sampling at 1-in-10,000 instead of 1-in-10. Which step of the investigation breaks, and which pillar would you have had to fall back on? Estimate how much longer localization takes.
5. You cannot roll back — v2.4.1 also shipped a database migration. Rank your remaining mitigations by time-to-effect and by blast radius, and name the telemetry you would watch to confirm each one worked.

## Key takeaways

- The incident loop is **detect → triage → mitigate → localize → explain → fix → learn**, and **mitigation comes third, before understanding**. Roll back, shed load, flip the flag, or raise the limit first; diagnose second. A mitigation you can ship in one minute beats a diagnosis you can ship in one hour.
- **MTTD** (Mean Time To Detect) is a monitoring problem — you either wrote the SLO burn-rate alert or you didn't. **MTTR** (Mean Time To Resolve) is dominated by **localization**, and localization is the one phase distributed tracing genuinely collapses: 45 seconds to detect here, and one exemplar click to localize.
- The funnel is five concrete queries, each destroying an order of magnitude: **burn-rate alert → RED dashboard → exemplar → span waterfall → logs filtered by `trace_id`**. Ten million requests to one log line. The handoffs only work because a single **trace ID** is stamped on all three pillars.
- **Cause metrics lie by staying calm.** CPU 41%, memory 58%, `bank-api` p99 24 ms — all normal, all useless, while the typical checkout ran 58× slower. Saturation of a resource the OS cannot see (a connection pool, a thread pool, a semaphore) is the most common shape of a serious incident, which is why **USE** panels exist alongside RED ones.
- **A latent fault plus a traffic ramp is the standard incident.** The deploy at 03:07 broke nothing for three minutes; the fault armed itself and waited for load. Keep **deploy annotations** on every dashboard and ask "what changed today?", not "what changed one minute ago?".
- A hypothesis you cannot test is a story. **Re-run with one variable changed** — rollback and enlarged pool both restored a 0.00% error ratio — and distinguish the **mitigation** (fast, reversible, no theory required) from the **fix** (moving the call out of the connection-holding block, shipped in daylight). Then write the postmortem, because the action items are the only part of an incident that makes the next one shorter.

This is the end of Phase 9. You started with a black box that told you nothing and finished having instrumented it, shipped and priced its telemetry, alerted on it without burning anyone out, and used all of it to take a real distributed failure apart in nine minutes — following signals, never source. Next comes [Phase 10 — Infrastructure and Deployment](../../../README.md#phase-10), where the thing you have been observing finally gets built, packaged, and shipped on purpose: containers, orchestration, pipelines, and the rollback button you just reached for at 03:16.
