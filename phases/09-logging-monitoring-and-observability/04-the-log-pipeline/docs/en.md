# The Log Pipeline: Ship, Store, Query — and What It Costs

> A log line that never leaves the machine that wrote it is worthless the moment that machine dies — and a log line that *does* leave costs real money, every day, forever. This lesson takes the structured events of Lesson 2 and the correlation IDs of Lesson 3 and follows them off the box: through the container runtime, into an agent, across a bounded buffer that must decide what to drop, into two very different storage engines, and finally onto an invoice. Getting that invoice under control is a backend engineering skill, and almost nobody teaches it.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Logs: From `print()` to Structured Events](../02-structured-logging/), [Correlation: Request IDs, Trace Context & Propagation](../03-correlation-and-request-context/)
**Time:** ~70 minutes

## The Problem

Your service logs beautifully. Every line is JSON (JavaScript Object Notation), every line carries a `trace_id`, every level is used with discipline. And then, in order, three things happen.

**Failure one: the logs kill the application.** You wrote to `/var/log/app.log` because that's what logs do. At 04:40 the disk hits 100%. The next write returns `ENOSPC` (no space left on device), your logging call raises, the exception escapes a handler nobody thought needed one, and the process dies. Worse are the quiet versions: Postgres refuses to accept writes on a full data volume; the container runtime can't write its own metadata; `journald` starts rate-limiting and silently discards the very lines describing the incident. A feature you added to *observe* the service has taken the service down.

**Failure two: the evidence dies with the witness.** You fix that with rotation, and a week later a pod gets rescheduled — memory limit exceeded, `SIGKILL`, container gone. You go looking for the logs from the sixty seconds before the kill and there is nothing: the container's filesystem was ephemeral, and it went away with the container. The single most valuable log lines you will ever write are the ones immediately before a crash, and they were stored **inside the thing that crashed**.

**Failure three: it works, and then the bill arrives.** So you ship logs off the box to a managed backend. Now do the arithmetic, because nobody does it until the invoice:

```text
2,000 requests/sec  ×  1.2 KB per structured event  =  2.4 MB/sec
2.4 MB/sec  ×  86,400 sec/day                        =  ~200 GB/day
200 GB/day  ×  30                                     =  ~6 TB/month ingested

at $2.00/GB ingested+indexed  →  ~$12,000/month  →  ~$144,000/year
```

A hundred and forty-four thousand dollars a year, for text. That is frequently **more than the compute being observed** — and it is not a made-up number; observability commonly runs 10–30% of infrastructure spend (Lesson 1), with log storage the single largest line item in that bucket. Traffic doubles, the bill doubles, and it never goes down on its own.

Then comes the twist that reframes the whole problem. Instrument your log backend's own query logs and you will find the same thing every team finds: **you queried well under 1% of what you paid to store.** You paid full retail price to index, replicate, and retain a hundred gigabytes a day of `"request completed"` at `INFO`, and the lines you actually read at 03:14 were the errors, the slow requests, and their neighbours. The pipeline was correct. The economics were nobody's job.

This lesson makes the economics your job.

## The Concept

### Rule zero: the application writes to stdout and nothing else

Before any pipeline, one rule that removes an entire category of failure: **your application writes its log stream to `stdout` (standard output — file descriptor 1) and takes no further interest in it.** No file paths. No rotation. No size limits. No shipping.

This is factor XI of the **Twelve-Factor App** methodology ("treat logs as event streams"), and the reasoning is that the application is the *wrong component* to own log storage. It doesn't know how much disk exists, whether it's sharing the volume with a database, how long lines must be retained for compliance, or where they need to be sent. Every one of those is a **platform** decision that changes without redeploying your code.

What happens to `stdout` then? The container runtime captures it. With Docker's default `json-file` logging driver, the runtime wraps each line as `{"log": "...", "stream": "stdout", "time": "..."}` and appends it to a file on the *node* — under Kubernetes, at a predictable path like `/var/log/pods/<namespace>_<pod>_<uid>/<container>/0.log`. The runtime, not your app, enforces `max-size` and `max-file` rotation. With the `journald` driver it goes to the systemd journal instead, with its own rate limits and retention. Either way, a well-known location on the node is now the single place an agent has to look, for every container on that node, in every language, with no per-application configuration.

In-app rotation is an anti-pattern for a concrete reason beyond taste: **two processes now believe they own the file.** Your app rotates by renaming, the agent is still holding the old inode, and lines vanish. Two replicas of your app share a volume and interleave partial writes into the same file. Your rotation policy is compiled into your image, so changing retention means a deploy. Write to `stdout`; let the platform be the platform.

### The four stages, and what runs at each

Every logging stack — a three-container homelab or a vendor with a sales team — is the same pipeline, and Lesson 1's four-stage picture specialized to logs:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 450" width="100%" style="max-width:840px" role="img" aria-label="The log pipeline in five stages: the application writes JSON to standard output, the container runtime captures it to a file on the node, an agent tails and enriches and batches it, a bounded buffer ships it, and a backend stores and indexes it. Below, the four options when the buffer fills: block the producer, spill to disk, drop by severity, or sample at the source.">
  <defs>
    <marker id="l04-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The log pipeline — five stages, and one decision that decides everything</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M172 92 L 186 92" marker-end="url(#l04-a1)"/>
    <path d="M344 92 L 358 92" marker-end="url(#l04-a1)"/>
    <path d="M540 92 L 554 92" marker-end="url(#l04-a1)"/>
    <path d="M700 92 L 714 92" marker-end="url(#l04-a1)"/>
    <path d="M628 132 L 628 174" marker-end="url(#l04-a1)" stroke-dasharray="6 5"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="52" width="152" height="80" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="190" y="52" width="152" height="80" rx="11" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="362" y="52" width="176" height="80" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="558" y="52" width="140" height="80" rx="11" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="718" y="52" width="144" height="80" rx="11" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="18" y="178" width="844" height="200" rx="14" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="7 6"/>
    <rect x="36" y="218" width="190" height="140" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    <rect x="242" y="218" width="190" height="140" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="448" y="218" width="190" height="140" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="654" y="218" width="190" height="140" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="94" y="74" font-size="11.5" font-weight="700">1 · APP</text>
    <text x="94" y="93" font-size="9" opacity="0.9">one JSON object</text>
    <text x="94" y="108" font-size="9" opacity="0.9">per line, to stdout</text>
    <text x="94" y="123" font-size="8.5" opacity="0.7">no files, no rotation</text>
    <text x="266" y="74" font-size="11.5" font-weight="700">2 · RUNTIME</text>
    <text x="266" y="93" font-size="9" opacity="0.9">container log driver</text>
    <text x="266" y="108" font-size="9" opacity="0.9">json-file / journald</text>
    <text x="266" y="123" font-size="8.5" opacity="0.7">a file on the node</text>
    <text x="450" y="74" font-size="11.5" font-weight="700">3 · AGENT</text>
    <text x="450" y="93" font-size="9" opacity="0.9">tail · parse · ENRICH</text>
    <text x="450" y="108" font-size="9" opacity="0.9">batch · compress · retry</text>
    <text x="450" y="123" font-size="8.5" opacity="0.7">Fluent Bit · Vector · OTel</text>
    <text x="628" y="74" font-size="11.5" font-weight="700">4 · BUFFER</text>
    <text x="628" y="93" font-size="9" opacity="0.9">bounded queue</text>
    <text x="628" y="108" font-size="9" opacity="0.9">mem + disk spill</text>
    <text x="628" y="123" font-size="8.5" opacity="0.7">retry with backoff</text>
    <text x="790" y="74" font-size="11.5" font-weight="700">5 · BACKEND</text>
    <text x="790" y="93" font-size="9" opacity="0.9">store · index · query</text>
    <text x="790" y="108" font-size="9" opacity="0.9">Loki · Elasticsearch</text>
    <text x="790" y="123" font-size="8.5" opacity="0.7">retention tiers</text>
    <text x="440" y="202" font-size="11.5" font-weight="700">The backend slows down and the buffer fills — four options, one of them a lie</text>
    <text x="131" y="242" font-size="10.5" font-weight="700">BLOCK the producer</text>
    <text x="131" y="264" font-size="9" opacity="0.9">the app waits for the</text>
    <text x="131" y="280" font-size="9" opacity="0.9">log write to finish</text>
    <text x="131" y="296" font-size="9" opacity="0.9">one slow backend now</text>
    <text x="131" y="312" font-size="9" opacity="0.9">stalls every request</text>
    <text x="131" y="340" font-size="10.5" font-weight="700" fill="#e0930f">NEVER DO THIS</text>
    <text x="337" y="242" font-size="10.5" font-weight="700">SPILL to disk</text>
    <text x="337" y="264" font-size="9" opacity="0.9">overflow into a</text>
    <text x="337" y="280" font-size="9" opacity="0.9">filesystem buffer</text>
    <text x="337" y="296" font-size="9" opacity="0.9">survives a restart</text>
    <text x="337" y="312" font-size="9" opacity="0.9">still bounded — cap it</text>
    <text x="337" y="340" font-size="10.5" font-weight="700" fill="#3553ff">BUYS TIME</text>
    <text x="543" y="242" font-size="10.5" font-weight="700">DROP by severity</text>
    <text x="543" y="264" font-size="9" opacity="0.9">shed debug, then</text>
    <text x="543" y="280" font-size="9" opacity="0.9">info; keep warn and</text>
    <text x="543" y="296" font-size="9" opacity="0.9">error to the last byte</text>
    <text x="543" y="312" font-size="9" opacity="0.9">count every drop</text>
    <text x="543" y="340" font-size="10.5" font-weight="700" fill="#0fa07f">THE REAL ANSWER</text>
    <text x="749" y="242" font-size="10.5" font-weight="700">SAMPLE at source</text>
    <text x="749" y="264" font-size="9" opacity="0.9">emit less to begin</text>
    <text x="749" y="280" font-size="9" opacity="0.9">with: 100% of errors,</text>
    <text x="749" y="296" font-size="9" opacity="0.9">1–5% of the routine</text>
    <text x="749" y="312" font-size="9" opacity="0.9">never enters the queue</text>
    <text x="749" y="340" font-size="10.5" font-weight="700" fill="#7c5cff">DO THIS FIRST</text>
    <text x="440" y="406" font-size="10.5" opacity="0.95">Whatever you choose, the application never finds out — telemetry failure must never become service failure.</text>
    <text x="440" y="426" font-size="10" opacity="0.75">This is Phase 8 Lesson 6's load shedding, turned around and applied to your own observability data.</text>
  </g>
</svg>
```

Read the top row left to right. **Stage 1** you own: one JSON object per line on `stdout`. **Stage 2** is the container runtime, which you configure but do not code. **Stage 3** is the agent — one per node, reading every container's file. **Stage 4** is the bounded buffer, which is where all the interesting engineering lives. **Stage 5** is the backend, which is where all the money lives. The bottom panel is the decision this lesson exists to teach, and you'll build it in Python before the hour is out.

### What the agent actually does — and why *enrich* is the important verb

The agent (Fluent Bit, Vector, Filebeat, or the OpenTelemetry Collector — OTel = OpenTelemetry, the vendor-neutral telemetry standard from Lesson 1, hosted by the CNCF, the Cloud Native Computing Foundation) does six jobs:

1. **Tail** every container's log file, tracking a byte offset in a checkpoint database so a restart resumes rather than re-sends.
2. **Parse** each line into fields. If your app emitted JSON this is one `json` decode. If it emitted prose, this is a **grok** regular expression, and it is expensive and brittle — see below.
3. **Enrich** with metadata the application could not possibly know: `pod`, `namespace`, `node`, `container`, `image tag`, `cluster`, `region`, deployment labels. Your process knows it is `checkout-api`. It does not know it is pod `checkout-api-7d9f4b-2` on node `ip-10-0-2-17` in namespace `prod` of cluster `eu-west-1a` — and *that* is what you filter by when one node's disk is failing.
4. **Batch** — one network round trip per log line is absurd; agents accumulate a few thousand records or a few seconds and send one compressed payload.
5. **Compress** — log lines are highly repetitive text, so gzip/zstd routinely gives 8–12× on a batch. You'll measure it.
6. **Retry and buffer** — the backend will be down sometimes. The agent holds the batch, retries with exponential backoff, and holds a **bounded** buffer while it does.

That word *bounded* is the whole next section.

### Backpressure: a log pipeline must be lossy, and the skill is choosing the loss

Your app emits at whatever rate traffic demands. Your backend accepts at whatever rate it can. When emit rate exceeds accept rate — a traffic spike, an error storm, a backend deploy, a network partition — something has to give. You have exactly four choices, and the diagram above named them.

**Block the producer.** The logging call waits until the buffer has room. This is *correct* in the sense that no data is lost, and it is catastrophic in production: a slow log backend now adds latency to every request, saturates your thread pool or event loop, and takes down a perfectly healthy service. This is the failure mode where **your observability system causes the outage**. Never block on telemetry. (Phase 8 Lesson 6 makes the general argument: when a downstream is slow, shed load rather than queue it forever.)

**Buffer in memory.** Fast, and it absorbs short spikes beautifully — but memory is finite, so the buffer must be **bounded**, and "bounded" only relocates the question: *what happens when the bound is reached?* An unbounded in-memory buffer isn't a solution, it's a delayed OOM (out-of-memory) kill that takes your service with it.

**Spill to disk.** When memory fills, write to a filesystem buffer. This survives an agent restart and rides out a multi-minute backend outage. It is also bounded (or you are back to Failure One), and it costs disk I/O on a node that has other jobs.

**Drop.** Eventually, you drop. Accept it. The engineering question is never *whether* to drop — it's **what to drop**, and the answer is: by value. A `DEBUG` line about a cache hit and an `ERROR` line about an exhausted connection pool are not worth the same, so they should not have the same survival odds. A good buffer drops lowest-severity first, ships highest-severity first, and — critically — **counts what it dropped, by level**, and exposes that as a metric. Silent loss is how you end up debugging with a corrupted picture of reality and never knowing.

The severity ordering itself is standardized: RFC 5424 (*The Syslog Protocol*) defines eight numeric severities from 0 (Emergency) to 7 (Debug). Your levels map onto it, and that mapping is what a drop policy sorts by.

### Two ways to store a log, and why the bills differ by 6×

Once the batch reaches the backend, one design decision dominates everything downstream — **how much do you index?** There are two coherent answers, and they produce wildly different bills.

**Index everything (Elasticsearch, OpenSearch).** Every field of every document is analyzed into tokens, and an **inverted index** is built: for each token, a *posting list* of the document IDs containing it. That's exactly the structure that makes a full-text search engine fast — any term, in any field, is an O(1) dictionary lookup into a sorted posting list. You pay for it twice: the index is often as large as or larger than the data it indexes, and building it is CPU-expensive on the ingest path, which is why an Elasticsearch cluster's bottleneck is usually indexing throughput rather than disk.

**Index labels only (Grafana Loki).** Loki's design bet, stated in its own documentation, is that log *search* is cheap if you can first make the haystack small. So it indexes **only a small set of labels** — `service`, `level`, `namespace`, `pod` — and nothing from the log body. Each distinct combination of labels is a **stream**; each stream's lines are appended into **chunks**, compressed, and written to object storage. A query gives a label selector plus a line filter; Loki uses the tiny index to pick the streams, then **brute-force scans** the decompressed chunks. The index is a rounding error, storage is compressed object storage, and ingest is just compression. The cost is that a search *without* a good label selector has to read everything.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 476" width="100%" style="max-width:840px" role="img" aria-label="Two log storage models compared by where the bytes go. Index-everything builds an inverted index four times larger than the compressed bodies. Index-labels-only has an index of two kilobytes and stores everything else as compressed chunks, a fraction of the total footprint.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Where the bytes go — same 12,000 events, 7.0 MB of JSON</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="46" width="412" height="372" rx="14" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="450" y="46" width="412" height="372" rx="14" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="52" y="148" width="120" height="200" rx="4" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="52" y="348" width="120" height="52" rx="4" fill="#3553ff" fill-opacity="0.15" stroke="#3553ff"/>
    <rect x="484" y="356" width="120" height="6" rx="2" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="484" y="362" width="120" height="38" rx="4" fill="#3553ff" fill-opacity="0.15" stroke="#3553ff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.6">
    <path d="M616 352 L 604 358"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="224" y="74" font-size="13" font-weight="700" text-anchor="middle" fill="#e0930f">INDEX EVERYTHING</text>
    <text x="224" y="93" font-size="9.5" text-anchor="middle" opacity="0.85">Elasticsearch · OpenSearch</text>
    <text x="224" y="118" font-size="10" text-anchor="middle" opacity="0.9">the index IS the product</text>
    <text x="190" y="232" font-size="10.5" font-weight="700">inverted index</text>
    <text x="190" y="250" font-size="10">4,005,153 B</text>
    <text x="190" y="268" font-size="9.5" opacity="0.8">72,501 distinct terms</text>
    <text x="190" y="285" font-size="9.5" opacity="0.8">every token of every</text>
    <text x="190" y="301" font-size="9.5" opacity="0.8">field, both directions</text>
    <text x="190" y="370" font-size="10" font-weight="700">bodies (zlib)</text>
    <text x="190" y="388" font-size="10">1,035,052 B</text>
    <text x="224" y="414" font-size="9.5" text-anchor="middle" opacity="0.9">total 5,040,205 B  ·  72% of raw</text>
    <text x="656" y="74" font-size="13" font-weight="700" text-anchor="middle" fill="#0fa07f">INDEX LABELS ONLY</text>
    <text x="656" y="93" font-size="9.5" text-anchor="middle" opacity="0.85">Grafana Loki</text>
    <text x="656" y="118" font-size="10" text-anchor="middle" opacity="0.9">the index is a phone book</text>
    <text x="622" y="288" font-size="10.5" font-weight="700">label index</text>
    <text x="622" y="306" font-size="10">2,140 B</text>
    <text x="622" y="324" font-size="9.5" opacity="0.8">24 streams, 36 chunks</text>
    <text x="622" y="341" font-size="9.5" opacity="0.8">0.03% of the store</text>
    <text x="622" y="380" font-size="10" font-weight="700">chunks (zlib)</text>
    <text x="622" y="398" font-size="10">758,176 B</text>
    <text x="656" y="414" font-size="9.5" text-anchor="middle" opacity="0.9">total 760,316 B  ·  11% of raw</text>
    <text x="440" y="444" font-size="10" text-anchor="middle" opacity="0.95">Query A · label selector + line filter  →  labels read 0.23 MB  ·  index read 1.5 MB</text>
    <text x="440" y="464" font-size="10" text-anchor="middle" opacity="0.95">Query B · one rare token, no selector  →  labels read 7.0 MB (all of it)  ·  index read 19 KB</text>
  </g>
</svg>
```

Those are the real measured numbers from the program you're about to run, and the shape is the point. The orange block is an inverted index **four times bigger than the compressed log bodies it points at**; the green sliver is a label index at 0.03% of its store. Total footprint differs by 6.6×, and that ratio flows straight into storage cost, replication cost, and the RAM a query engine needs.

But read the two footer lines before you conclude one model wins. On **Query A** — where you *have* a good label selector — the label store reads less than the index does, because narrowing to 2 streams out of 24 beats fetching 133 scattered documents. On **Query B** — one rare token, no selector — the index answers in 19 KB and the label store reads the entire corpus. That is the honest trade: **cheap storage in exchange for expensive unfiltered search.** Loki is superb when you know *which* stream and roughly *when*; Elasticsearch is superb when you know only a needle.

### Cardinality strikes again: identifiers go in the body, never in the label set

If "one series per distinct label combination" gave you a flicker of recognition, good — it is precisely the failure mode from **Phase 4, Lesson 5**, where a `user_id` tag on a time-series metric multiplies your series count into the millions and kills the database. Loki's label set has the identical explosive property, because a label set *is* a series identifier.

Put `trace_id` in the label set and every single log line becomes its own stream. The index grows from tens of streams to one entry per event. Chunks become one line long, so compression — which needs repetition across many similar lines to work at all — stops working. The program measures this exactly: the same corpus goes from **24 streams / 760 KB** to **12,000 streams / 6.4 MB**, an index 678× larger and bodies 6.5× larger.

The rule, and it's short enough to memorize:

- **Labels** = the small, bounded set of dimensions you *select streams by*: `service`, `level`, `env`, `namespace`, `pod`. Aim for tens to low thousands of streams total.
- **Body** = everything else, including every identifier: `trace_id`, `user_id`, `order_id`, full URLs. They stay perfectly searchable with a line filter (`|= "u_07930"`) or a JSON-parse filter — they just don't get indexed.

Notice this is the same advice as the metrics lesson, arrived at from a different direction: high-cardinality identity belongs in the *payload*, never in the *index key*.

### Sampling: the single highest-leverage cost lever

You cannot afford to keep every routine event, and you don't need to. **Sampling** keeps a fraction and discards the rest. The naïve form — **head sampling**, "keep 1% of everything, decided at emit time" — is cheap and useless, because 99% of your errors also vanish.

**Error-biased (dynamic) sampling** is the version worth knowing, and it is the highest-return change in this entire lesson: **keep 100% of what is rare and interesting, and a few percent of what is common and boring.**

```text
level in (ERROR, FATAL)          -> keep 100%     (rare, and the reason you log)
level == WARN                    -> keep 100%     (still rare)
duration_ms >= 1000              -> keep 100%     (the tail is where bugs live)
status >= 400                    -> keep 100%
everything else (INFO)           -> keep 5%
DEBUG in production              -> keep 1%, or turn it off entirely
```

The catch: a sampled dataset lies about counts. If you kept 5% of INFO and count 400 of them, the truth is around 8,000 — and you must not make the reader do that division by hand. So **record the sampling rate on every kept event** (`"sample_rate": 0.05`) and reconstruct populations by summing the **weight** `1 / sample_rate` instead of counting rows. This is textbook Horvitz–Thompson estimation, and it makes "how many `/checkout` requests succeeded?" answerable from sampled data. It is also why every log line in the Build It carries a `sample_rate` field.

Two related techniques, so you recognize the names: **tail sampling** decides *after* a request completes, when you know whether it was slow or failed — strictly better quality, but it requires buffering all of a request's events until it ends (the OpenTelemetry Collector's `tail_sampling` processor does this for traces). And **per-tenant quotas** cap how much any one customer, service, or namespace can push, so one team's debug loop can't consume the org's budget or crowd out everyone else's errors.

### Retention tiers: the second lever

Volume is one axis; **time** is the other. The value of a log line collapses within hours — you read it during an incident and essentially never again — but compliance and forensics may require you to keep it for months. Charging searchable-hot-storage prices for a 90-day tail nobody queries is the second-biggest waste in most log bills.

The fix is tiering:

| Tier | Age | Where | What it costs | What you can do |
|---|---|---|---|---|
| **Hot** | 0–7 days | indexed, on fast disk, replicated | the expensive tier | interactive query, dashboards, alerting |
| **Warm** | 7–30 days | fewer replicas, compressed, colder disk | ~half | slower queries, still self-service |
| **Cold / archive** | 30 days–7 years | object storage (S3/GCS), compressed, no index | ~$0.023/GB/month | restore-then-query; minutes to hours |

Object storage is roughly an order of magnitude cheaper per gigabyte-month than indexed hot storage, so moving the 83-day tail out of hot is nearly free savings — and it usually lets you *extend* retention rather than shorten it. Your compliance officer wants a year; your finance team wants a smaller bill; tiering is how both win.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 840 496" width="100%" style="max-width:800px" role="img" aria-label="A funnel of cost levers: raw log volume of 94 gigabytes per day narrows after emitting less, then narrows sharply after error-biased sampling to 21 gigabytes per day, then splits into 7 days of hot storage and 83 days of cheap cold archive, arriving at a final bill 22 percent of the original.">
  <defs>
    <marker id="l04-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="420" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three levers, applied in order — the funnel from volume to invoice</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M420 104 L 420 140" marker-end="url(#l04-a2)"/>
    <path d="M420 202 L 420 238" marker-end="url(#l04-a2)"/>
    <path d="M420 300 L 420 322"/>
    <path d="M336 322 L 452 322"/>
    <path d="M336 322 L 336 336" marker-end="url(#l04-a2)"/>
    <path d="M452 322 L 452 336" marker-end="url(#l04-a2)"/>
    <path d="M336 392 L 336 402" marker-end="url(#l04-a2)"/>
    <path d="M452 392 L 452 402" marker-end="url(#l04-a2)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="70" y="48" width="700" height="52" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="140" y="144" width="560" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="308" y="242" width="224" height="52" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="308" y="340" width="56" height="52" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="372" y="340" width="160" height="52" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="250" y="406" width="340" height="56" rx="11" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="420" y="70" font-size="11.5" font-weight="700" text-anchor="middle">RAW — everything the application emits</text>
    <text x="420" y="89" font-size="10.5" text-anchor="middle" opacity="0.9">100%  ·  94 GB/day  ·  $20,281/yr</text>
    <text x="452" y="118" font-size="10.5" font-weight="700" fill="#3553ff">LEVER 1 · emit less</text>
    <text x="452" y="134" font-size="9.5" opacity="0.85">DEBUG off in prod · fix the top-3 loudest lines</text>
    <text x="420" y="166" font-size="11.5" font-weight="700" text-anchor="middle">AFTER THE FREE WINS</text>
    <text x="420" y="185" font-size="10.5" text-anchor="middle" opacity="0.9">~80%  ·  ~75 GB/day   (representative)</text>
    <text x="452" y="216" font-size="10.5" font-weight="700" fill="#0fa07f">LEVER 2 · error-biased sampling</text>
    <text x="452" y="232" font-size="9.5" opacity="0.85">100% of errors and slow requests · 5% info · 1% debug</text>
    <text x="420" y="264" font-size="11.5" font-weight="700" text-anchor="middle">AFTER SAMPLING</text>
    <text x="420" y="283" font-size="10" text-anchor="middle" opacity="0.9">23%  ·  21.3 GB/day  ·  $4,606/yr</text>
    <text x="560" y="312" font-size="10.5" font-weight="700" fill="#7c5cff">LEVER 3 · retention tiers</text>
    <text x="560" y="328" font-size="9.5" opacity="0.85">7 days hot, 83 days in object storage</text>
    <text x="336" y="364" font-size="10" font-weight="700" text-anchor="middle">HOT</text>
    <text x="336" y="380" font-size="9" text-anchor="middle" opacity="0.85">7d</text>
    <text x="452" y="364" font-size="9.5" font-weight="700" text-anchor="middle">COLD ARCHIVE</text>
    <text x="452" y="380" font-size="9" text-anchor="middle" opacity="0.85">83d @ $0.023/GB</text>
    <text x="420" y="432" font-size="12.5" font-weight="700" text-anchor="middle">THE BILL — $4,506/yr</text>
    <text x="420" y="452" font-size="10" text-anchor="middle" opacity="0.9">22% of raw, and 90 days retained instead of 30</text>
    <text x="420" y="482" font-size="10" text-anchor="middle" opacity="0.9">Errors, slow requests and audit events pass through every lever untouched — that is the constraint.</text>
  </g>
</svg>
```

The funnel's first stage is marked *representative* because "how much can you delete for free" depends on your codebase; the rest are the measured outputs of the program below. The direction is what matters: **cut volume before you negotiate price.** A 20% discount from a vendor is worth less than turning off one chatty `DEBUG` line in a hot loop.

### Redaction, compliance, and the audit log

Two more pipeline responsibilities that are not optional.

**Redaction, twice.** Lesson 2 redacted secrets at the source, where you know which field is a password. Do it again at the agent, as a **backstop**, because the source will fail eventually — a new endpoint logs a whole request body, a third-party library logs an `Authorization` header, someone dumps an exception carrying a card number. Agent-side redaction is a regex/transform filter that runs on every line regardless of which service produced it, and it is the only control that covers code you didn't write.

**PII (Personally Identifiable Information) makes retention a legal obligation, in both directions.** Under the GDPR (General Data Protection Regulation), personal data must not be kept longer than necessary for its purpose (Article 5(1)(e), *storage limitation*), and a data subject can demand erasure (Article 17). A log line containing an email or an IP address is personal data. This has a sharp engineering consequence: **you must be able to delete a specific person's data out of your logs**, which is very hard if logs are immutable compressed chunks in object storage — and much easier if you pseudonymize at the edge (log a stable `user_ref` hash instead of an email) so deleting the mapping is enough.

**Audit logs are a different stream.** "User X changed permission Y at time Z" is not an application log. It has different requirements — longer retention (often years), tamper-evidence or append-only storage, tighter access control — and it must **never** be sampled or dropped under backpressure. Route it to its own pipeline with its own backend. If your audit trail shares a bounded buffer with `DEBUG` chatter, you do not have an audit trail.

### Structured beats regex, for a reason you can price

One last argument for Lesson 2's discipline. If your app emits prose, the agent must parse it with **grok** patterns — layered regular expressions matching free text. That costs CPU on every line at every node (regex backtracking on a million lines a second is real load), and it *breaks silently* when someone reformats a message: the pattern stops matching, the line falls through as unparsed text, and your dashboard quietly goes empty. If your app emits JSON, the agent's parse step is one decode, the schema travels with the data, and adding a field breaks nothing. **Structured logging is not a style preference; it is the thing that makes the pipeline cheap and the parse step unbreakable.**

## Build It

`code/log_pipeline.py` simulates the whole pipeline on a virtual clock: emit, enrich, ship through a bounded buffer against a backend that goes slow at the worst moment, sample, store the same corpus in both storage models, query both, and price the result. Standard library only, seeded, deterministic.

The heart of it is the drop policy. The buffer keeps one queue *per severity*, so both the drop decision and the ship decision are O(1) — and there is no code path that makes the producer wait:

```python
def offer(self, ev: Event) -> None:
    if self.n >= self.capacity:
        victim = next((lvl for lvl in LEVELS if self.q[lvl]), None)   # lowest severity present
        if victim is not None and SEVERITY[victim] < SEVERITY[ev.level]:
            self.q[victim].popleft()                 # evict a cheap event...
            self.n -= 1
            self.stats.dropped[victim] += 1
        else:
            self.stats.dropped[ev.level] += 1        # ...or the arrival is itself the cheapest
            return
    self.q[ev.level].append(ev)
    self.n += 1
```

Draining runs the same ordering in reverse — `for lvl in reversed(LEVELS)` — so a batch is filled with errors first and debug last. Under pressure the buffer therefore both *drops* from the bottom and *ships* from the top, which is exactly the behaviour you want when the backend is slow and an error storm is in progress.

The sampler is error-biased and records its own rate, so the data stays countable:

```python
def sample(events, info_rate=0.05, debug_rate=0.01):
    """Keep every error, warning and slow request; a few percent of the rest."""
    rnd, kept = random.Random(SEED + 2), []
    for ev in events:
        if ev.level in ("warn", "error") or ev.duration_ms >= 1000:
            rate = 1.0
        else:
            rate = debug_rate if ev.level == "debug" else info_rate
        if rate >= 1.0 or rnd.random() < rate:
            kept.append(Event(**{**ev.__dict__, "sample_rate": rate}))
    return kept


def estimate(kept, predicate) -> float:
    """Reconstruct a population count from sampled events: sum of 1/sample_rate."""
    return sum(1.0 / ev.sample_rate for ev in kept if predicate(ev))
```

The label-stream store is Loki in miniature: a label set names a stream, lines accumulate into that stream, and each chunk is compressed on seal. The index is nothing but the label text and per-chunk metadata:

```python
class LabelStreamStore:
    def _key(self, doc: dict) -> str:
        return ",".join(f'{k}="{doc.get(k)}"' for k in self.label_keys)

    def _seal(self, key: str) -> None:
        raw = "\n".join(self._pending[key]).encode()
        self.streams.setdefault(key, []).append(zlib.compress(raw, 6))
        self.raw_sizes.setdefault(key, []).append(len(raw))
        self._pending[key] = []

    @property
    def index_bytes(self) -> int:
        # the label set text once per stream + 24 bytes of chunk metadata
        # (min ts, max ts, object-store offset) per chunk. That is the whole index.
        return sum(len(k) + 24 * len(self.streams[k]) for k in self.streams)
```

The inverted-index store is the other bet. Every token of every field gets a posting list, and its size is dominated by the postings, not the terms — one 4-byte document ID per token occurrence, and a 583-byte JSON event contains a lot of occurrences:

```python
    @property
    def index_bytes(self) -> int:
        # term dictionary entry (term text + 8 bytes of pointers) + 4 bytes per posting.
        # A floor: real engines also store positions, norms and doc values.
        return sum(len(t) + 8 for t in self.postings) + 4 * sum(len(p) for p in self.postings.values())
```

Both stores compress their log bodies with the same `zlib` settings, so the comparison isolates exactly one variable: **the index**. And the bill is a pure function of bytes, days, and price:

```python
def monthly_cost(bytes_per_day: float, hot_days: int, archive_days: int = 0) -> dict[str, float]:
    gb_day = bytes_per_day / GB
    ingest = gb_day * 30 * PRICE_INGEST_GB              # $0.50/GB ingested + indexed
    hot = gb_day * hot_days * PRICE_HOT_GB_MONTH        # $0.10/GB/month searchable
    archive = gb_day * archive_days * PRICE_ARCHIVE_GB_MONTH   # $0.023/GB/month in object storage
    total = ingest + hot + archive
    return {"gb_day": gb_day, "ingest": ingest, "hot": hot,
            "archive": archive, "total": total, "year": total * 12}
```

The rest — the emitter, the Kubernetes-style enrichment filter, the virtual-clock batching loop, the query engines, and the cardinality experiment — is in [`code/log_pipeline.py`](code/log_pipeline.py). Run it:

```console
$ python log_pipeline.py
== 1. EMIT + ENRICH ==
  emitted 12,000 events at 2,000/s over 6.0s
  levels: debug=2,563  info=7,247  warn=1,034  error=1,156
  agent enriched with 5 platform labels the app never knew (k8s_pod, k8s_node, ...)
  raw JSON 7,001,163 bytes, avg 583 bytes/event

== 2. SHIP: bounded buffer, slow backend, and the drop decision ==
  buffer capacity 2,000 events   batch 500   backend 50ms/batch, 1000ms while degraded
  shipped 9,000 in 18 batches   peak queue 2,000
  dropped 3,000 (25.0%) by level: debug=1,110  info=1,890  warn=0  error=0   <- cheapest events spent first

== 3. SAMPLE: error-biased, with the rate recorded on every event ==
  policy: error/warn/slow=100%   info=5%   debug=1%
  kept 2,701 of 12,000 events (22.5%)   1,590,124 bytes (22.7% of raw)
  reconstructed from 1/sample_rate weights:
    error  true  1,156   estimated    1,156   error  0.00%   (kept 100%)
    info   true  7,247   estimated    7,460   error  2.94%   (sampled 5%)
    debug  true  2,563   estimated    3,131   error 22.16%   (sampled 1%)
    TOTAL  true 12,000   estimated   12,781   error  6.51%
  re-shipping the sampled stream through the same buffer: 2,701 shipped, 0 dropped  <- sampling is also how you stop dropping

== 4. STORE: index everything vs index labels only ==
  corpus: 12,000 events, 7,001,163 bytes of JSON
  inverted index (72,501 terms) index 4,005,153 B  bodies 1,035,052 B  total 5,040,205 B   72.0% of raw
  label streams  (24 streams)   index     2,140 B  bodies   758,176 B  total   760,316 B   10.9% of raw
  index overhead: 1,872x     total footprint: 6.6x

== 4b. CARDINALITY: what one trace_id label does to the label store ==
  good labels (service, level, route):                 24 streams       36 chunks     760,316 B
  + trace_id as a LABEL:                           12,000 streams   12,000 chunks   6,362,530 B
  one stream per event: index 678x bigger, bodies 6.5x bigger (chunks too small to compress)

== 5. QUERY: the same needle, two engines ==
  A: {service="checkout-api", level="error"} |= "pool exhausted"
  label streams :  133 hits   read   234,396 B  (  3.3% of corpus)  decompress + grep 2 of 24 streams
  inverted index:  133 hits   read    23,584 B index + 1,499,261 B bodies (21.8%)
  B: {} |= "u_07930"   -- no label selector, one rare token
  label streams :    1 hits   read 7,001,127 B  (100.0% of corpus)  brute-force, every stream
  inverted index:    1 hits   read        27 B index + 18,657 B bodies (0.3%)
  ratio on this query: label store reads 375x more than the index

== 6. THE BILL: 2,000 events/s, 24x7 ==
  at 583 bytes/event and 2,000 events/s  ->  94 GB/day
  prices: $0.50/GB ingest, $0.10/GB/mo hot, $0.023/GB/mo archive
  raw, 30d hot               93.9 GB/day   ingest $    1,408   store $     282   = $    1,690/mo  ($     20,281/yr)
  sampled, 30d hot           21.3 GB/day   ingest $      320   store $      64   = $      384/mo  ($      4,606/yr)   saves  77.3%
  sampled, 7d+83d cold       21.3 GB/day   ingest $      320   store $      56   = $      376/mo  ($      4,506/yr)   saves  77.8%
  annual difference: $15,775  -- and the 90-day tail is now retained, not deleted
  sensitivity: a 1.2 KB production event at $2.00/GB ingest -> 193 GB/day = $145,998/yr for logs alone
```

Read the numbers, because almost every claim in The Concept is now measured rather than asserted.

**The drop policy worked exactly as designed.** The backend went slow for 2.5 seconds and the buffer hit its 2,000-event ceiling, so 3,000 events — 25% of everything emitted — had to go. Every single one came out of `debug` (1,110) and `info` (1,890); **zero warnings and zero errors were lost**, even though the error burst happened *inside* the degradation window. That is the entire argument for severity-aware dropping in one line of output: the pipeline lost a quarter of its volume and none of its meaning.

**Sampling reconstructs the truth, with variance you can predict.** Errors and warnings are kept at 100%, so their reconstructed counts are exact — 1,156 and 1,034, zero error. `info`, sampled at 5%, reconstructs to within 2.94%. `debug`, sampled at 1%, is off by 22% — and that is not a bug, it is the sampling rate telling you what precision you bought. Sample harder and your estimates get noisier; the weights keep them *unbiased*, not *precise*. The lesson: sample the things you count aggressively only if you can tolerate wide error bars, and never sample the thing you alert on.

**Sampling is also the fix for dropping.** Re-shipping the sampled stream through the *same* bounded buffer against the *same* degraded backend: 2,701 shipped, **0 dropped**. Cutting volume at the source didn't just cut the bill; it removed the backpressure event entirely.

**The index is the cost.** Both stores compressed the log bodies with identical settings — 1,035,052 B versus 758,176 B, close (the inverted store's blocks are smaller, so it compresses slightly worse). The difference in total footprint is 6.6×, and it is *entirely* the index: 4,005,153 B against 2,140 B. Note also that the inverted index alone is **4× larger than the compressed data it indexes** — this is the thing people find hard to believe until they measure it, and this measurement is a *floor*, since real engines also store term positions, field norms, and doc values.

**Cardinality behaves exactly as the metrics lesson warned.** Promoting `trace_id` from body to label turned 24 streams into 12,000, grew the index 678×, and — the subtle part — grew the *bodies* 6.5× too, because a chunk holding one line has nothing to compress against. The total store went from 11% of raw to 91% of raw. One label did that.

**Neither storage model wins in general.** Query A had a good label selector, and the label store read 234 KB where the index read 1.5 MB — narrowing to 2 streams out of 24 beat scattering across 47 document blocks. Query B had a rare token and no selector, and the index read 19 KB where the label store read all 7 MB, a 375× difference. Choose Loki when your queries know their service and time range; choose Elasticsearch when your queries are needle-hunts across everything.

**And the bill.** 583 bytes per event at 2,000 events/second is 94 GB/day and $20,281/year at these prices — for a single service. Error-biased sampling takes it to $4,606 (77.3% saved). Adding retention tiering takes it to $4,506 while *tripling* retention from 30 days to 90. The last line is the reality check: a realistic 1.2 KB production event at an index-everything vendor's $2.00/GB is **$145,998/year for one service's logs**, which is the number from The Problem, now derived rather than quoted.

## Use It

You will not write the agent; you will configure one. These are the fragments that carry the lesson.

**Fluent Bit** — the CNCF log processor usually run as a Kubernetes DaemonSet, one pod per node. Its four section types are your four stages:

```text
[INPUT]
    Name              tail
    Path              /var/log/containers/*.log
    Parser            cri                    # unwrap the runtime's line wrapper
    DB                /var/log/flb_kube.db   # byte offsets: a restart resumes, not re-sends
    Mem_Buf_Limit     32MB                   # BOUNDED memory buffer -- the drop decision
    storage.type      filesystem             # ...and spill to disk past that

[FILTER]
    Name       kubernetes                    # ENRICH: pod, namespace, node, labels
    Match      kube.*
    Merge_Log  On                            # parse the app's JSON into real fields
    Keep_Log   Off

[FILTER]
    Name    modify                           # agent-side redaction backstop (Lesson 2)
    Match   kube.*
    Remove  authorization
    Remove  password

[OUTPUT]
    Name          loki
    Match         kube.*
    labels        namespace=$kubernetes['namespace_name'], app=$kubernetes['labels']['app'], level=$level
    Retry_Limit   5
    compress      gzip
```

Two settings carry it. `Mem_Buf_Limit` plus `storage.type filesystem` is your bounded buffer with disk spill; without them Fluent Bit pauses the input, which is backpressure walking back toward your node. And the `labels` line is the cardinality decision — `namespace`, `app`, `level` are bounded; adding `$trace_id` there is the 12,000-stream experiment, in production.

**The OpenTelemetry Collector** does the same job for all three signals in one binary, with the pipeline written out explicitly:

```yaml
receivers:
  filelog: {include: [/var/log/pods/*/*/*.log], operators: [{type: json_parser}]}

processors:
  memory_limiter: {check_interval: 1s, limit_mib: 512, spike_limit_mib: 128}   # refuse work before OOM
  resource: {attributes: [{key: service.name, value: checkout-api, action: upsert}]}   # ENRICH
  attributes: {actions: [{key: http.request.header.authorization, action: delete}]}    # redact
  batch: {send_batch_size: 8192, timeout: 5s}          # one round trip per few thousand records

exporters:
  otlphttp/logs:
    endpoint: https://logs.internal:4318
    sending_queue: {enabled: true, queue_size: 10000}            # bounded -- drops past this
    retry_on_failure: {enabled: true, max_elapsed_time: 300s}

service:
  pipelines:
    logs:
      receivers: [filelog]
      processors: [memory_limiter, resource, attributes, batch]  # limiter FIRST
      exporters: [otlphttp/logs]
```

`memory_limiter` must be first: it is the component that refuses work rather than letting the collector die on the node it shares with your service. `queue_size: 10000` is where the drop happens.

**LogQL** (Loki's query language) executes in written order — cheap index work first, expensive scanning after:

```text
{service="checkout-api", level="error"}                   # 1. pick streams from the tiny index
  |= "pool exhausted"                                     # 2. line filter: grep the chunks
  | json | duration_ms > 1000                             # 3. parse the body, filter a field

sum by (route) (rate({service="checkout-api", level="error"}[5m]))   # a metric, built from logs
{namespace="prod"} |= "u_07930"       # legal -- and scans every stream in the namespace
```

Adding `level="error"` before a line filter routinely cuts bytes-scanned by 20×, which is why LogQL *requires* a selector: a query without one would read your whole log estate. The Elasticsearch/Kibana equivalent — KQL, Kibana Query Language — has no cheap-versus-expensive distinction between fields, because everything was indexed at ingest:

```text
service:"checkout-api" and level:"error" and message:"pool exhausted" and duration_ms > 1000
```

Shorter to write, and it finds a needle anywhere with no selector. You paid for that on every line, whether you ever search it or not.

**Label sets — get this right and most cost problems never appear:**

```text
GOOD  {cluster="eu-west-1a", namespace="prod", app="checkout-api", level="error"}
      1 cluster x 4 namespaces x 30 apps x 5 levels = 600 streams. Bounded. Fine.
BAD   {cluster="eu-west-1a", app="checkout-api", trace_id="4bf92f...", user_id="u_07930"}
      one stream per request: millions of streams, one-line chunks, no compression, an
      index bigger than the data. Put trace_id and user_id in the BODY -- |= "4bf92f" finds them.
```

**Retention** is configuration, not code — Loki's `limits_config` and compactor, an Elasticsearch **ILM** (Index Lifecycle Management) policy, or your vendor's per-index settings. The shape never changes: age maps to tier, with a separate, longer, unsampled policy for audit:

```yaml
application_logs: {hot: 7d,  warm: 30d, archive: 90d}      # sampled, cheap
error_logs:       {hot: 30d, warm: 90d, archive: 365d}     # never sampled
audit_logs:       {hot: 90d, archive: 7y, immutable: true} # never sampled, never dropped
```

**The cost checklist, in the order that pays best:** measure GB/day *per service* (you cannot manage what you can't attribute) → find your **top-3 loudest log lines** by message template, because three lines in hot loops routinely produce over half your volume → turn `DEBUG` off in production, and make the level runtime-configurable so you can turn it back on for one service for ten minutes → apply error-biased sampling with `sample_rate` recorded on every kept event → move identifiers out of label sets and into bodies → set retention per stream class and tier the tail into object storage instead of deleting it → and alert on your own pipeline (dropped-events-by-level, buffer utilization, GB/day against budget), because a drop counter nobody watches is the same as silent loss.

## Think about it

1. Your app writes to `stdout`, the node's disk fills anyway, and the container runtime starts discarding lines. Which of the three failures from The Problem have you actually prevented, and which have you only moved? What would you configure to bound the remaining one?
2. Your drop policy sheds `DEBUG` first. During an incident, a colleague turns on `DEBUG` for one service to investigate — and the error lines they need stop arriving. Explain the mechanism, and change one thing about the pipeline so it can't happen again.
3. You sample `INFO` at 1% and use the weights to reconstruct request counts for a dashboard. The run above showed 22% error at that rate. For which of these is that acceptable — a capacity-planning graph, a billing report, an SLO error-budget calculation — and why?
4. Loki's label index was 0.03% of its store, but only two of the 24 streams had to be scanned because the query named a service and a level. Sketch the query pattern that makes Loki the *wrong* choice, and say what you'd change first: the storage engine, or the way people query it?
5. A regulator sends a deletion request for one user. Your logs are immutable compressed chunks in object storage, keyed by service and hour. What do you actually do — and what should you have done at emit time, six months ago, to make this a five-minute job?

## Key takeaways

- **The app writes to `stdout` and nothing else** (Twelve-Factor, factor XI). The container runtime captures the stream to a file on the node via its log driver (`json-file`, `journald`); rotation, shipping, and retention are platform decisions that must change without a redeploy. In-app file rotation is an anti-pattern because two processes end up owning the same file.
- The pipeline is **emit → collect → buffer/ship → store/index → query**, and the agent's jobs are tail, parse, **enrich** (pod/node/namespace labels the app can't know), batch, compress, and retry. Structured JSON at the source turns the parse step from a brittle, CPU-hungry grok regex into one decode.
- **A log pipeline must be lossy under pressure.** Blocking the producer turns a slow log backend into a service outage; unbounded buffers are delayed OOM kills. Bound the buffer, spill to disk, and **drop by severity** — cheapest first, ship errors first, and count every drop by level. The measured run lost 25% of volume and zero errors.
- **Index everything vs. index labels only** is the storage decision that sets your bill: the inverted index measured **4× larger than the compressed bodies it indexes** (6.6× total footprint), and it buys needle-in-a-haystack search with no selector. Label-only indexing is ~11% of raw and wins when a query names its stream — 234 KB read versus 1.5 MB on the same query.
- **Cardinality kills the log store exactly as it kills the metric store** (Phase 4, Lesson 5). Promoting `trace_id` to a Loki label produced 12,000 streams instead of 24, a 678× index, and 6.5× larger bodies because one-line chunks won't compress. Identifiers go in the **body** (searchable with a line filter), never in the **label set**.
- **Cost discipline is two levers plus arithmetic.** Error-biased sampling — 100% of errors, warnings and slow requests, 1–5% of routine traffic, with `sample_rate` recorded so counts reconstruct via `1/rate` weights — cut the measured bill 77%. Retention tiering into object storage (~$0.023/GB/month) cut it further *while tripling retention*. Audit logs get their own stream: never sampled, never dropped, retained for years.

Next: [Metrics: Counters, Gauges & Histograms from Scratch](../05-metrics-from-scratch/) — the cheap pillar, where a counter costs a few bytes no matter how many events it counts, and the questions you just decided you couldn't afford to answer with logs get answered for almost nothing.
