# Logs: From `print()` to Structured Events

> A prose log line is written for a human reading one line, and then read by a machine searching a billion of them. That mismatch is why "grep the logs" stops working somewhere around your tenth server. This lesson turns `print("order failed")` into an event with typed fields you can group, count and filter — then collapses a dozen chatty lines per request into one wide event that answers questions you haven't thought of yet.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Systems Go Dark: Monitoring, Observability & the Three Pillars](../01-why-systems-go-dark/)
**Time:** ~65 minutes

## The Problem

It's 03:14 again, and this time you *do* have logs. You SSH to `web-07`, `tail` the file, and this is what production actually looks like:

```text
2026-03-14 04:14:06 INFO  Starting checkout for user 8842
[2026-03-14T04:14:06+01:00] gunicorn.access 10.0.4.11 "POST /orders HTTP/1.1" 200 1043
14/Mar/2026 04:14:07 - urllib3.connectionpool - WARNING - Retrying (Retry(total=2)) after connection broken by 'ReadTimeoutError'
2026-03-14 04:14:07 ERROR Failed to process order for user 8842 after 3 retries
Traceback (most recent call last):
  File "/app/orders/service.py", line 214, in place_order
    charge = gateway.charge(card, total)
  File "/app/payments/gateway.py", line 88, in charge
    raise GatewayTimeout("no response in 3000ms")
payments.gateway.GatewayTimeout: no response in 3000ms
2026-03-14 04:14:07 INFO  Starting checkout for user 1109
```

Eleven lines, and almost everything about them is hostile:

- **Three formats from three libraries.** Your app writes `TIME LEVEL message`, Gunicorn writes a bracketed ISO timestamp then Apache-ish fields, `urllib3` writes `dd/Mon/YYYY - logger - LEVEL - message`. No parser handles all three.
- **Three notions of time.** One line says `04:14:06`, another `04:14:06+01:00`. The server runs in Europe/Berlin, the database logs in UTC. Ordering events across machines becomes arithmetic you do in your head at 3am.
- **One event spans seven lines.** The traceback is a single failure, but line-oriented tooling sees seven records. `grep ERROR` returns line 4 and throws away the stack; a log shipper turns it into seven documents, or one truncated one.
- **The lines interleave.** User 1109's checkout starts *in the middle* of user 8842's failure, because forty threads share one stdout, and nothing marks which lines belong to which request.
- **Every useful fact is trapped in an English sentence.** `Failed to process order for user 8842 after 3 retries` contains a user ID, a retry count and an outcome — as *words*. Not fields. Words.

Now the question you actually have to answer, because your manager asked it and the payment provider wants evidence:

> How many order failures did we have for **premium-tier** users in **eu-west** in the last hour, grouped by **error kind**?

Every clause is a filter, and the log has none of them. `tier` and `region` were never written down. The error kind is buried in a sentence that also happens to contain the retry count. The best you can do is a regular expression:

```python
m = re.search(r"Failed to process order for user (\d+) after (\d+) retries", line)
```

That yields a user ID and a retry count — not the tier, not the region, not the kind of failure. And it is *load-bearing prose*: the day someone rewrites the message as `Order processing failed for user 8842 (3 retries)`, the regex matches nothing, the count silently drops to zero, and nobody notices until the next incident. You have built a dashboard on top of an English sentence that nobody knows they must not edit.

The fix is not a better regex. It's to stop writing sentences.

## The Concept

### A log is an append-only stream of immutable events

Strip away formatting and a log is one of the simplest structures in this curriculum: **an append-only sequence of timestamped, immutable records**. You only ever add to the end; you never update one, because a thing that happened at 03:14:07 is a historical fact. Same shape as the write-ahead log (Phase 3, Lesson 13) and the time-series chunk (Phase 4, Lesson 5).

Contrast the metric from Lesson 1. A metric is aggregated *as it is recorded* — the counter increments and the individual request is destroyed on the way in, which is exactly why it costs a few bytes whether it counts ten requests or ten billion. A **log event keeps the individual**: this request, this user, this error, at this instant. Maximum detail, and a cost that scales linearly with traffic. Logs are the only pillar that can name a specific user.

### Anatomy of a log event

Every log event in every language is built from the same five parts, and the first one causes the most damage when it's wrong.

**Timestamp** — use **ISO 8601** (the International Organization for Standardization's date format) in **UTC** (Coordinated Universal Time), with at least millisecond precision: `2026-03-14T03:14:07.912Z`. Local time is ambiguous (`2026-10-25 02:30:00` happens *twice* in Berlin when the clock falls back — two events, one timestamp, no way to order them); UTC is the only clock that makes a server in Frankfurt comparable to one in Virginia; and ISO 8601 **sorts correctly as plain text**, so a sorted log file is a sorted timeline with no parsing. Prefer that string over a raw `time.time()` float, which loses precision as the epoch grows, is unreadable to a human scanning a line, and rounds differently in different languages.

**Level** — one of a small fixed set of severities. **Event name** — a sentence in prose logging, a stable identifier in structured logging. **Source** — which logger, module, service, host and version emitted it. **Fields** — everything else, and this is where the whole lesson lives.

### Human-readable or machine-readable: the split, and the fix

The tension is real. A sentence is superb when you're reading one line. It is terrible when a machine reads a billion, because the machine must reverse-engineer your grammar to recover facts you already had in variables when you wrote the line. **Structured logging** resolves it: the message becomes a **stable event name** and every variable becomes a **typed field**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="The same log event as prose and as a structured event. Each fact trapped inside the English sentence — the time, the level, the action, the user id, the retry count — becomes a separate typed field, and three more fields exist that the sentence never carried at all.">
  <defs>
    <marker id="l02-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One event, two encodings — every fact leaves the sentence and becomes a field</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="44" width="820" height="62" rx="11" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="30" y="140" width="330" height="248" rx="12" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    <rect x="424" y="140" width="426" height="248" rx="12" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.75">
    <path d="M366 152 L 418 152" marker-end="url(#l02-a1)"/><path d="M366 182 L 418 182" marker-end="url(#l02-a1)"/><path d="M366 212 L 418 212" marker-end="url(#l02-a1)"/>
    <path d="M366 242 L 418 242" marker-end="url(#l02-a1)"/><path d="M366 272 L 418 272" marker-end="url(#l02-a1)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="44" y="64" font-size="10" opacity="0.75">PROSE — written for one human reading one line</text>
    <text x="44" y="90" font-size="11">2026-03-14 04:14:07 ERROR Failed to process order for user 8842 after 3 retries</text>
    <text x="44" y="128" font-size="10.5" font-weight="700" fill="#e0930f">FACT TRAPPED IN THE SENTENCE</text>
    <text x="438" y="128" font-size="10.5" font-weight="700" fill="#0fa07f">TYPED, QUERYABLE FIELD</text>
    <text x="44" y="156" font-size="10">"04:14:07"  local, no timezone</text><text x="438" y="156" font-size="10">"ts": "2026-03-14T03:14:07.912Z"</text><text x="700" y="156" font-size="9" opacity="0.7">UTC, ms</text>
    <text x="44" y="186" font-size="10">"ERROR"  a word in the middle</text><text x="438" y="186" font-size="10">"level": "ERROR"</text><text x="700" y="186" font-size="9" opacity="0.7">enum</text>
    <text x="44" y="216" font-size="10">"Failed to process order"</text><text x="438" y="216" font-size="10">"event": "order.failed"</text><text x="700" y="216" font-size="9" opacity="0.7">stable name</text>
    <text x="44" y="246" font-size="10">"user 8842"</text><text x="438" y="246" font-size="10">"user_id": "u_8842"</text><text x="700" y="246" font-size="9" opacity="0.7">string</text>
    <text x="44" y="276" font-size="10">"after 3 retries"</text><text x="438" y="276" font-size="10">"retries": 3</text><text x="700" y="276" font-size="9" opacity="0.7">number</text>
    <text x="44" y="310" font-size="10" opacity="0.55">— nowhere in the line —</text><text x="438" y="310" font-size="10">"error_kind": "payment_declined"</text>
    <text x="44" y="340" font-size="10" opacity="0.55">— nowhere in the line —</text><text x="438" y="340" font-size="10">"tier": "premium"</text>
    <text x="44" y="370" font-size="10" opacity="0.55">— nowhere in the line —</text><text x="438" y="370" font-size="10">"region": "eu-west"</text>
    <text x="440" y="424" font-size="11" text-anchor="middle">grep "Failed to process" works — until someone rewords the message, and the count silently becomes zero.</text>
    <text x="440" y="446" font-size="11" text-anchor="middle">event = "order.failed" survives every rewording, because it was never prose in the first place.</text>
    <text x="440" y="470" font-size="10" text-anchor="middle" opacity="0.8">The three bottom fields are the point: structured logging lets you add facts the sentence had no room for.</text>
  </g>
</svg>
```

Read the right column as a list of things you can now do. `level` is an enum, so "all errors" is an exact match, not a substring search. `retries` is a *number*, so `retries > 2` is a range query. `event` is a name you commit to, so a rewritten human message never breaks a dashboard. And the bottom three — `error_kind`, `tier`, `region` — are facts the sentence never carried at all, which is precisely why the question in *The Problem* was unanswerable. Structured logging isn't a formatting preference; it's the difference between data and text.

The wire format is almost always **JSON Lines** (JSON = JavaScript Object Notation): one JSON object per line, newline-delimited, no wrapping array — so the stream stays greppable, splittable, and resumable mid-file without losing framing.

### Severity levels: eight from syslog, five you use

Levels come from **syslog**, the Unix logging protocol standardized in **RFC 5424** (RFC = Request for Comments, the Internet Engineering Task Force's specification series). Section 6.2.1 defines eight severities numbered 0–7 — Emergency, Alert, Critical, Error, Warning, Notice, Informational, Debug. Nobody could reliably tell Emergency from Alert from Critical, so modern libraries collapsed them into five.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 872 442" width="100%" style="max-width:840px" role="img" aria-label="The five log severity levels as a ladder from CRITICAL at the top to DEBUG at the bottom, each annotated with the discipline rule for using it, its typical daily volume shown as a bar that grows toward the bottom, and whether it is enabled in production.">
  <text x="436" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The severity ladder — rarity at the top, volume at the bottom</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="32" y="70" width="170" height="56" rx="10" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/><rect x="32" y="132" width="170" height="56" rx="10" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="32" y="194" width="170" height="56" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="32" y="256" width="170" height="56" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/><rect x="32" y="318" width="170" height="56" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
  </g>
  <g stroke="currentColor" stroke-width="1.2" opacity="0.3">
    <line x1="214" y1="129" x2="840" y2="129"/><line x1="214" y1="191" x2="840" y2="191"/><line x1="214" y1="253" x2="840" y2="253"/><line x1="214" y1="315" x2="840" y2="315"/>
  </g>
  <g fill="#3553ff" fill-opacity="0.5" stroke="none">
    <rect x="592" y="100" width="10" height="8" rx="3"/><rect x="592" y="162" width="24" height="8" rx="3"/><rect x="592" y="224" width="46" height="8" rx="3"/><rect x="592" y="286" width="78" height="8" rx="3"/><rect x="592" y="348" width="116" height="8" rx="3"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="117" y="58" font-size="10" text-anchor="middle" opacity="0.75">LEVEL · severity</text>
    <text x="226" y="58" font-size="10" opacity="0.75">DISCIPLINE RULE — the test you apply before writing the call</text>
    <text x="649" y="58" font-size="10" text-anchor="middle" opacity="0.75">VOLUME / day</text>
    <text x="786" y="58" font-size="10" text-anchor="middle" opacity="0.75">ON IN PROD?</text>
    <text x="117" y="103" font-size="13" font-weight="700" text-anchor="middle">CRITICAL · 50</text><text x="649" y="94" font-size="10" text-anchor="middle">0 – 2</text><text x="786" y="102" font-size="10.5" text-anchor="middle">yes</text>
    <text x="226" y="94" font-size="10">The process cannot continue. Data loss, or the</text><text x="226" y="111" font-size="10">service is down. Wake someone regardless of hour.</text>
    <text x="117" y="165" font-size="13" font-weight="700" text-anchor="middle">ERROR · 40</text><text x="649" y="156" font-size="10" text-anchor="middle">~50</text><text x="786" y="164" font-size="10.5" text-anchor="middle">yes</text>
    <text x="226" y="156" font-size="10">A human should care. Not "something unusual" —</text><text x="226" y="173" font-size="10">something broken that needs a person to act.</text>
    <text x="117" y="227" font-size="13" font-weight="700" text-anchor="middle">WARNING · 30</text><text x="649" y="218" font-size="10" text-anchor="middle">~2,000</text><text x="786" y="226" font-size="10.5" text-anchor="middle">yes</text>
    <text x="226" y="218" font-size="10">Degraded but handled: a retry succeeded, a</text><text x="226" y="235" font-size="10">fallback fired, a quota is 80% used.</text>
    <text x="117" y="289" font-size="13" font-weight="700" text-anchor="middle">INFO · 20</text><text x="649" y="280" font-size="10" text-anchor="middle">~5M</text><text x="786" y="288" font-size="10.5" text-anchor="middle">yes</text>
    <text x="226" y="280" font-size="10">The story of normal operation, told once per</text><text x="226" y="297" font-size="10">request or per state change. Your default.</text>
    <text x="117" y="351" font-size="13" font-weight="700" text-anchor="middle">DEBUG · 10</text><text x="649" y="342" font-size="10" text-anchor="middle">~200M</text><text x="786" y="350" font-size="10.5" text-anchor="middle">no · opt-in</text>
    <text x="226" y="342" font-size="10">Developer-only internals — loop variables, cache</text><text x="226" y="359" font-size="10">keys, payload shapes. Never a permanent resident.</text>
    <text x="436" y="398" font-size="10.5" text-anchor="middle">Level is a runtime filter: a suppressed call costs one integer comparison — but the arguments are evaluated first, so</text>
    <text x="436" y="415" font-size="10.5" text-anchor="middle">log.debug("q", rows=fetch_all()) still runs fetch_all(). DEBUG in prod is a ~40x volume increase and a ~40x log bill.</text>
    <text x="436" y="435" font-size="10" text-anchor="middle" opacity="0.8">RFC 5424 §6.2.1 defines 8 syslog severities (0 Emergency … 7 Debug); every modern library exposes these 5.</text>
  </g>
</svg>
```

The most abused rung is **ERROR**, so hold onto the rule in that row: *a human should care*, not "something unexpected happened". A bad password is not an ERROR — it's the login system working. A validation failure on a malformed request is not an ERROR — it's a 400 and the API doing its job. If nobody will ever act on it, it is INFO at most. Teams that ignore this get 40,000 ERRORs a day, stop reading them, and miss the one that mattered — alert fatigue arriving through the log pipeline instead of the pager (Lesson 10).

The ladder also shows what a level *is*: a **numeric threshold** compared once per call. Set it to INFO and every `log.debug(...)` costs one integer comparison and returns. Note the footnote's trap — arguments are evaluated *before* the call, so `log.debug("rows", rows=fetch_all())` runs `fetch_all()` even when DEBUG is off.

### The canonical log line: one wide event per request

This is the idea that changes how your logs look more than any other. The instinct is to log the *steps* of a request — received, cache missed, query started, query finished, payment attempted, response sent — as a dozen narrow lines each carrying almost no context. The alternative is to accumulate facts in memory while the request runs and emit **exactly one very wide event at the end**: the **canonical log line**, also called a **wide event**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 476" width="100%" style="max-width:860px" role="img" aria-label="A comparison of twelve narrow log lines per request against a single wide canonical log line carrying twenty-two fields, annotated with the bytes written, the number of serialization calls on the request path, and how each is queried.">
  <defs>
    <marker id="l02-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One request, two logging strategies</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="44" width="384" height="360" rx="12" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    <rect x="468" y="44" width="408" height="360" rx="12" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="484" y="98" width="376" height="204" rx="9" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.5"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="1.2" opacity="0.75">
    <rect x="40" y="98" width="352" height="15" rx="4"/><rect x="40" y="118" width="352" height="15" rx="4"/><rect x="40" y="138" width="352" height="15" rx="4"/><rect x="40" y="158" width="352" height="15" rx="4"/>
    <rect x="40" y="178" width="352" height="15" rx="4"/><rect x="40" y="198" width="352" height="15" rx="4"/><rect x="40" y="218" width="352" height="15" rx="4"/><rect x="40" y="238" width="352" height="15" rx="4"/>
    <rect x="40" y="258" width="352" height="15" rx="4"/><rect x="40" y="278" width="352" height="15" rx="4"/><rect x="40" y="298" width="352" height="15" rx="4"/><rect x="40" y="318" width="352" height="15" rx="4"/>
  </g>
  <path d="M414 218 L 462 218" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l02-a2)"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="216" y="72" font-size="12" font-weight="700" text-anchor="middle" fill="#e0930f">12 NARROW LINES — one per step</text>
    <text x="672" y="72" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">1 WIDE EVENT — one per request</text>
    <text x="48" y="110" font-size="8.5">request.received   route=/orders</text>
    <text x="48" y="130" font-size="8.5">auth.ok</text>
    <text x="48" y="150" font-size="8.5">cache.miss   key=cart:8842</text>
    <text x="48" y="170" font-size="8.5">db.query.start   n=1</text>
    <text x="48" y="190" font-size="8.5">db.query.end   12ms</text>
    <text x="48" y="210" font-size="8.5">db.query.start   n=2</text>
    <text x="48" y="230" font-size="8.5">db.query.end   14ms</text>
    <text x="48" y="250" font-size="8.5">inventory.checked</text>
    <text x="48" y="270" font-size="8.5">price.computed   total=4999</text>
    <text x="48" y="290" font-size="8.5">payment.start</text>
    <text x="48" y="310" font-size="8.5">payment.retry   attempt=2</text>
    <text x="48" y="330" font-size="8.5">response.sent   status=500</text>
    <text x="498" y="118" font-size="9">"ts": "…07.912Z"</text><text x="686" y="118" font-size="9">"route": "/orders"</text>
    <text x="498" y="135" font-size="9">"level": "ERROR"</text><text x="686" y="135" font-size="9">"method": "POST"</text>
    <text x="498" y="152" font-size="9">"event": "http.request"</text><text x="686" y="152" font-size="9">"status": 500</text>
    <text x="498" y="169" font-size="9">"service": "order-api"</text><text x="686" y="169" font-size="9">"duration_ms": 75</text>
    <text x="498" y="186" font-size="9">"version": "3.14.2"</text><text x="686" y="186" font-size="9">"db_ms": 26</text>
    <text x="498" y="203" font-size="9">"env": "prod"</text><text x="686" y="203" font-size="9">"db_queries": 3</text>
    <text x="498" y="220" font-size="9">"host": "web-07"</text><text x="686" y="220" font-size="9">"cache_hit": false</text>
    <text x="498" y="237" font-size="9">"request_id": "req_0003"</text><text x="686" y="237" font-size="9">"retries": 1</text>
    <text x="498" y="254" font-size="9">"user_id": "u_1106"</text><text x="686" y="254" font-size="9">"bytes_out": 618</text>
    <text x="498" y="271" font-size="9">"tier": "premium"</text><text x="686" y="271" font-size="9">"outcome": "error"</text>
    <text x="498" y="288" font-size="9">"region": "eu-west"</text><text x="686" y="288" font-size="9">"error_kind": "…timeout"</text>
    <text x="216" y="358" font-size="9.5" text-anchor="middle" opacity="0.9">12 lines x ~180 B  =  ~2.2 KB / request</text><text x="672" y="358" font-size="9.5" text-anchor="middle" opacity="0.9">1 line x ~340 B  =  0.34 KB / request  (6.5x less)</text>
    <text x="216" y="374" font-size="9.5" text-anchor="middle" opacity="0.9">12 serialize + 12 writes, on the request path</text><text x="672" y="374" font-size="9.5" text-anchor="middle" opacity="0.9">1 serialize + 1 write, once, at the end</text>
    <text x="216" y="390" font-size="9.5" text-anchor="middle" opacity="0.9">"how slow was the DB?" = JOIN 12 lines by request_id</text><text x="672" y="390" font-size="9.5" text-anchor="middle" opacity="0.9">every question = one filter on one line, no join</text>
    <text x="438" y="206" font-size="9" text-anchor="middle" opacity="0.75">same</text><text x="438" y="234" font-size="9" text-anchor="middle" opacity="0.75">request</text>
    <text x="450" y="434" font-size="11" text-anchor="middle">Wide events win because the fields are on the SAME ROW: "premium users in eu-west whose db_ms &gt; 50 and</text>
    <text x="450" y="452" font-size="11" text-anchor="middle">cache_hit was false" is one filter. Across 12 narrow lines it is a self-join you cannot afford at a billion rows.</text>
  </g>
</svg>
```

The cost annotations are the headline — **6.5× fewer bytes** and **one write instead of twelve**, which matters because logging is synchronous I/O on the request path. But the query story is the real prize: every field sits on the *same row*, so any combination is a single filter (`tier="premium" AND region="eu-west" AND db_ms > 50 AND cache_hit=false`). With twelve narrow lines that same question is a self-join across twelve rows grouped by `request_id`, which no log backend does cheaply at a billion rows a day.

Narrow lines still earn their place in three cases: **inside a long-running job**, where one event at the end arrives too late; for **state changes you may need to audit independently** (a permission grant, a refund); and at **DEBUG during development**, where you're reading, not querying. Everything else belongs on the wide line.

### Context: fields on every line, fields per request

Fields come from two places. Some are true for the whole process and belong on **every** line — `service`, `version`, `env`, `host`. Without them an entry that reached a central store is unattributable: you can't tell prod from staging, or whether the errors stopped after the 3.14.2 deploy.

The rest are true for one request — `request_id`, `user_id`, `tier`, `region`. Passing those into every call by hand is how they get forgotten on the one line that mattered. The fix is a **bound logger** (or child logger): `log.bind(request_id="req_0003", user_id="u_1106")` returns a *new* logger carrying those fields on everything it emits. Immutability matters — binding must return a child rather than mutate a shared logger, or two concurrent requests will smear each other's user IDs across the log. Carrying an ID *across* services is [Lesson 3](../03-correlation-and-request-context/), and is deliberately not implemented here.

### What never goes in a log

A log is plain text, copied to a central store, indexed for search, readable by everyone with a dashboard login, and retained for 30 days or more. Treat it as a *publication*. Never write:

- **Credentials** — passwords (even wrong ones; users mistype passwords into the username field), tokens, API keys, session cookies, `Authorization` headers, private keys.
- **Payment data** — full card numbers, CVV, expiry. The Payment Card Industry Data Security Standard (PCI DSS) forbids storing the CVV *at all*, and a log file is storage.
- **Whole request or response bodies.** `log.info(request.body)` is the most common leak there is, because the body contains whatever the client sent — including everything above.
- **Personal data** beyond an opaque ID — emails, phone numbers, addresses, full names. Under the EU's **GDPR** (General Data Protection Regulation) a log line containing personal data *is* personal data: it inherits deletion obligations, retention limits and access controls. A right-to-erasure request that means rewriting 90 days of log archives is a genuinely bad day.

The practical defense is **redaction by key name**: a deny-list of field names whose values become `[REDACTED]` before serialization, applied recursively so a secret nested three dicts deep is still caught. Know its limit — it matches *names*, not values, so a card number in a field called `note`, or a token concatenated into a URL you logged as `target`, sails straight through. The deeper rule: **log identifiers, not payloads.** Log `user_id`, never `user`; `card_last4`, never `card`.

### What logging costs

Logging is not free, and the cost lands in the worst place: synchronously, on the request path. Serializing a wide event to JSON is real CPU work — tens of microseconds for a 20-field object — and the `write()` to stdout is a syscall that blocks if the pipe's buffer fills and the consumer is slow. Three habits keep it honest: filter by level *before* building the message, prefer one wide event to a dozen narrow ones, and never do work purely in order to log it. The volume side of the bill — shipping, indexing, retention, and what a terabyte a day actually costs — is [Lesson 4](../04-the-log-pipeline/).

## Build It

Standard library only: a structured logger with severity filtering, immutable context binding, recursive redaction, exception capture and a canonical-log-line helper — then a query over the output that answers the question from *The Problem*.

The core is smaller than you'd expect. An event is a dict assembled in a fixed order, redacted, serialized, written as one line:

```python
def emit(self, level: str, event: str, **fields: Any) -> bool:
    """Assemble, redact, serialize, write. Returns False if level-filtered."""
    if LEVELS[level] < self._threshold:
        return False                       # cheapest possible path: one int compare
    record: dict[str, Any] = {
        "ts": iso_utc(self.clock.now()),   # first key: JSONL sorts by time as text
        "level": level,
        "event": event,                    # a STABLE name, never an English sentence
    }
    record.update(self.context)            # bound fields (service, request_id, ...)
    record.update(fields)                  # call-site fields win
    line = json.dumps(redact(record, self.sensitive_keys),
                      separators=(",", ":"), default=str)
    self.stream.write(line + "\n")
    return True
```

The ordering rule — timestamp, level, event, then bound context, then call-site fields — means every line has the same three leading keys, so a human can still scan a raw file. `bind()` builds a new `Logger` sharing the stream and clock but with `context={**self.context, **fields}`: a child, never a mutated self. Redaction then walks the whole structure, because secrets hide inside nested objects:

```python
def redact(value: Any, keys: frozenset[str] = SENSITIVE_KEYS) -> Any:
    """Blank sensitive keys, recursing into nested dicts and lists.
    Denies by KEY NAME, so field naming is a security control."""
    if isinstance(value, Mapping):
        return {k: REDACTED if k.lower() in keys else redact(v, keys)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v, keys) for v in value]
    return value
```

The canonical log line is a context manager around a request-scoped accumulator. Fields go in during the request; exactly one wide event comes out at the end — including when the request raises:

```python
@contextmanager
def canonical(logger: Logger, event: str, **initial: Any) -> Iterator[RequestLog]:
    """Accumulate fields for the life of a request; emit ONE wide event at the
    end. An exception is recorded as fields before re-raising, so even a failed
    request produces exactly one queryable line."""
    rl = RequestLog(dict(initial), logger.clock.now())
    try:
        yield rl
    except Exception as exc:
        rl.add(outcome="error", status=500, exc_message=str(exc),
               error_kind=getattr(exc, "kind", type(exc).__name__))
        raise
    finally:
        rl.fields.setdefault("outcome", "ok")
        rl.add(duration_ms=logger.clock.now() - rl.started_ms)
        level = "ERROR" if rl.fields["outcome"] == "error" else "INFO"
        logger.emit(level, event, **rl.fields)
```

The rest — the ISO-8601 clock, the level table, exception capture that flattens a traceback into a one-line string field, and a 400-request simulation — is in [`code/structured_logger.py`](code/structured_logger.py). Run it:

```console
$ python3 structured_logger.py
== 1 - PROSE VS STRUCTURED ==
  prose      : 2026-03-14 04:14:07 ERROR Failed to process order for user 8842 after 3 retries
  structured : {"ts":"2026-03-14T03:14:07.912Z","level":"ERROR","event":"order.failed","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","user_id":"u_8842","retries":3,"error_kind":"payment_declined","tier":"premium","region":"eu-west"}

== 2 - LEVEL AS A RUNTIME FILTER (threshold=INFO) ==
{"ts":"2026-03-14T03:14:07.923Z","level":"WARNING","event":"db.pool.saturated","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","in_use":19,"size":20,"wait_ms":412}
  debug emitted? False   warning emitted? True

== 3 - REDACTION BY KEY NAME (recursive) ==
{"ts":"2026-03-14T03:14:07.960Z","level":"INFO","event":"auth.login","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","user_id":"u_8842","password":"[REDACTED]","upstream":{"api_key":"[REDACTED]","endpoint":"auth.internal"},"headers":{"authorization":"[REDACTED]","user-agent":"curl/8.4"}}

== 4 - EXCEPTION AS FIELDS, NOT A MULTI-LINE TRACE ==
{"ts":"2026-03-14T03:14:07.966Z","level":"ERROR","event":"order.failed","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","request_id":"req_0001","exc_type":"OrderError","exc_message":"gateway did not respond in 3000ms","traceback":"structured_logger.py:207 in _call_gateway <- structured_logger.py:203 in charge_card <- structured_logger.py:283 in main","order_id":"o_5512"}

== 5 - CANONICAL LOG LINES: ONE WIDE EVENT PER REQUEST ==
{"ts":"2026-03-14T03:14:08.051Z","level":"INFO","event":"http.request","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","request_id":"req_0001","user_id":"u_5506","method":"POST","route":"/orders","tier":"free","region":"eu-west","cache_hit":true,"db_queries":1,"db_ms":23,"retries":0,"bytes_out":3233,"outcome":"ok","status":200,"duration_ms":25}
{"ts":"2026-03-14T03:14:08.187Z","level":"INFO","event":"http.request","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","request_id":"req_0002","user_id":"u_1488","method":"POST","route":"/orders","tier":"enterprise","region":"eu-west","cache_hit":true,"db_queries":5,"db_ms":74,"retries":0,"bytes_out":2861,"outcome":"ok","status":200,"duration_ms":79}
{"ts":"2026-03-14T03:14:08.296Z","level":"ERROR","event":"http.request","service":"order-api","version":"3.14.2","env":"prod","host":"web-07","request_id":"req_0003","user_id":"u_1106","method":"POST","route":"/orders","tier":"enterprise","region":"us-east","cache_hit":false,"db_queries":3,"db_ms":26,"retries":1,"bytes_out":618,"outcome":"error","status":500,"exc_message":"order rejected after 1 retries","error_kind":"payment_gateway_timeout","duration_ms":75}
  ... 397 more requests logged to the same stream (not shown)

== 6 - THE QUERY PROSE COULD NOT ANSWER ==
  events on the stream : 404   canonical request lines: 400
  premium + eu-west order failures, grouped by error kind:
    address_invalid          10
    payment_gateway_timeout  7
    payment_declined         3
    inventory_unavailable    3
  slowest 3 requests (same lines, different question):
    req_0335   211ms  db= 90ms queries=5  cache_hit=True  error
    req_0367   211ms  db= 81ms queries=5  cache_hit=False  error
    req_0173   207ms  db= 80ms queries=5  cache_hit=False  error
```

Read what each section proves. **Section 1** is *The Problem* solved on one screen: the prose line says `04:14:07` in local time and buries four facts in grammar, while the structured line carries the same instant as `2026-03-14T03:14:07.912Z` in UTC and exposes `user_id`, `retries`, `error_kind`, `tier` and `region` as separate keys — plus `service`, `version`, `env`, `host`, which the prose line never had. **Section 2**: the DEBUG call returned `False`, so it never serialized and never touched the stream, while the WARNING returned `True` — one integer comparison doing all the filtering. **Section 3**: `password`, the nested `upstream.api_key` and the `authorization` inside `headers` all came out `[REDACTED]` two levels deep, while `endpoint` and `user-agent` survived untouched. **Section 4** is the traceback fix: a seven-line stack became one string field, `"structured_logger.py:207 in _call_gateway <- … in charge_card <- … in main"`, alongside `exc_type` and `exc_message` as separate queryable keys — and the event is still exactly one line, so nothing downstream has to guess where it ends.

**Section 5** shows three canonical lines of 21 fields each: `duration_ms=25` for a cache-hit request versus `duration_ms=79` for one that ran five queries costing 74 ms — the ratio of `db_ms` to `duration_ms` is right there, no second line needed. The failed request records `outcome=error`, `status=500`, `retries=1` and `error_kind=payment_gateway_timeout` on the same row that already carries `tier` and `region`.

**Section 6** is the payoff. Four hundred requests produced exactly 400 canonical lines out of 404 total events — one per request, not twelve. The question that needed a fragile regex over English is now one filter and one counter: `address_invalid` 10, `payment_gateway_timeout` 7, `payment_declined` 3, `inventory_unavailable` 3, for premium users in eu-west specifically. Then the *same 400 lines, unchanged*, answer a completely different question — the three slowest requests, all errors, all with five queries and 80–90 ms of database time. Nobody wrote a "slow request" log for that. That is Lesson 1's unknown-unknowns property made concrete: rich fields on one row let you ask questions you never anticipated.

## Use It

You won't ship your own logger. Python's standard `logging` module already has the parts — and understanding why it exists explains every logging library you'll meet.

`logging` separates four concerns a `print()` conflates. **Loggers** are named in a dotted hierarchy (`orders.payment` is a child of `orders`), so you can set the level for one subsystem without touching the rest — this is how you silence a chatty dependency. **Levels** filter numerically at each logger. **Handlers** decide *where* a record goes (stdout, a file, a socket). **Formatters** decide *how* it's rendered. Records **propagate** up the hierarchy to ancestors' handlers, which is why configuring the root logger once configures your whole app — and why a stray `logging.basicConfig()` inside a library duplicates every line.

To get JSON out, subclass `Formatter`. The key move is copying the caller's `extra` fields off the `LogRecord`, which is where the standard library stashes them:

```python
import json, logging, time

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}

class JsonFormatter(logging.Formatter):
    converter = time.gmtime                      # UTC, not the server's local timezone

    def format(self, record: logging.LogRecord) -> str:
        event = {
            "ts": f"{self.formatTime(record, '%Y-%m-%dT%H:%M:%S')}.{int(record.msecs):03d}Z",
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        event.update({k: v for k, v in record.__dict__.items() if k not in _RESERVED})
        if record.exc_info:                       # traceback as a field, not extra lines
            event["exc_type"] = record.exc_info[0].__name__
            event["traceback"] = self.formatException(record.exc_info)
        return json.dumps(event, default=str)
```

`converter = time.gmtime` is not incidental: `Formatter` uses **local time** by default, reproducing the timezone problem from *The Problem* on every line. Wire it up once, declaratively, with `logging.config.dictConfig` — the only configuration API worth using, because it's data you keep next to your app config:

```python
logging.config.dictConfig({
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"json": {"()": "myapp.log.JsonFormatter"}},
    "handlers": {"stdout": {"class": "logging.StreamHandler",
                            "stream": "ext://sys.stdout", "formatter": "json"}},
    "root": {"handlers": ["stdout"], "level": "INFO"},
    "loggers": {"urllib3": {"level": "WARNING"}},     # silence one chatty dependency
})

log = logging.getLogger("orders")
log.info("order.failed", extra={"user_id": "u_8842", "retries": 3, "tier": "premium"})
```

One gotcha bites everyone exactly once. `extra` keys are set as attributes directly on the `LogRecord`, so a key colliding with a built-in attribute raises `KeyError: "Attempt to overwrite 'module' in LogRecord"`. The reserved names include `name`, `msg`, `args`, `levelname`, `module`, `filename`, `lineno`, `funcName`, `process`, `thread`, `created`, `exc_info` and `message`. Namespace or prefix your fields and the collision disappears.

Then the deployment rule, from the **twelve-factor app** methodology's *Logs* factor: **an application never manages its own log files.** No rotation, no directories, no compression. Write the event stream to **stdout** and let the execution environment — systemd, Docker, Kubernetes — capture and route it. The app stays identical in every environment, the container's stdout becomes the single contract, and rotation and retention move to the platform where they belong. What happens to that stream afterwards is [Lesson 4](../04-the-log-pipeline/).

The ecosystem by category, so you recognize the shape rather than memorize names: **`structlog`** (Python) is the mature version of everything you just built — bound loggers, processor pipelines, JSON renderers — and it can sit on top of stdlib `logging`. In Go, **`zerolog`** and **`zap`** are the zero-allocation structured loggers. In Node.js, **`pino`** is the fast JSON logger. In Rust, **`tracing`** unifies structured logs and spans in one API. And **OpenTelemetry** (OTel) now defines a **log data model** alongside metrics and traces, so a log record can carry a trace ID natively and be correlated with spans by the backend — which is where [Lesson 7](../07-distributed-tracing-and-opentelemetry/) picks this up.

## Think about it

1. Your team logs `log.error("user not found")` on every lookup miss, and it fires 12,000 times a day. Which level should it be, and what happens to the team's relationship with ERROR if it stays where it is?
2. You emit one canonical line per request with 25 fields. A colleague wants to add `cart_items` — the full list of products, prices and quantities. Give three separate arguments against it. Is there a version you'd accept?
3. Redaction by key name catches `password` and `api_key`. Name two realistic ways a secret still reaches your log store despite it, and what discipline (not code) prevents each.
4. Your logger binds `request_id` at the start of a request. A background thread spawned by that request logs an error 200 ms after the response was sent. Does that line carry the `request_id`? What does your answer imply about where bound context must actually live?
5. Twelve narrow lines cost 2.2 KB per request; one wide line costs 0.34 KB. At 5,000 requests per second, what's the daily difference in log volume — and which would you still choose for a 40-minute batch job, and why?

## Key takeaways

- A **log** is an append-only stream of timestamped, immutable **events**. Unlike a metric — which aggregates on the way in and can never name an individual — a log keeps the specific request, user and error, at maximum detail and a cost that scales linearly with traffic.
- Every event needs a **timestamp in ISO 8601, UTC, with milliseconds** (local time is ambiguous across daylight-saving transitions and incomparable across machines; ISO 8601 also sorts correctly as plain text), a **level**, a stable **event name**, its **source**, and **fields**.
- **Severity levels** descend from syslog's eight severities (RFC 5424 §6.2.1) to the modern five. The rule that matters most: **ERROR means a human should care**, not "something unusual happened". Level is a numeric runtime filter — cheap when suppressed, but the call's *arguments* are still evaluated, and DEBUG in production is roughly a 40× volume and cost increase.
- **Structured logging** turns the message into a stable `event` name and every variable into a typed field, emitted as **JSON Lines**. That's what makes `retries > 2`, `tier="premium"` and `error_kind` queryable — and what stops a reworded sentence from silently zeroing a dashboard.
- The **canonical log line** — one wide event per request with 20+ fields instead of a dozen narrow ones — was ~6.5× cheaper in bytes, cost one write instead of twelve on the request path, and put every field on the **same row**, so any combination is one filter rather than a self-join. Keep narrow lines for long-running jobs, auditable state changes and local DEBUG.
- Process-wide context (`service`, `version`, `env`, `host`) belongs on every line; request-scoped context belongs on an **immutably bound child logger**. Never log credentials, card data, whole bodies or personal data — under GDPR a log line containing personal data *is* regulated data — and remember redaction matches **key names**, not values, so the real rule is **log identifiers, not payloads**.

Next: [Correlation: Request IDs, Trace Context & Propagation](../03-correlation-and-request-context/) — your events are queryable inside one process, but a request crosses five of them; next you give it an identity that survives every hop.
