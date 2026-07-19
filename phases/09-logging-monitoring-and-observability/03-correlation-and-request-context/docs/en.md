# Correlation: Request IDs, Trace Context & Propagation

> Lesson 2 made every log line queryable. It did not make the lines *belong to each other* — and a server handling 200 requests at once writes 200 stories into one stream, shuffled. Correlation is the fix: one identifier, minted once, that survives every function call, thread, queue, and network hop. The industry agreed on its exact byte layout so your service and a stranger's can share it.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Logs: From `print()` to Structured Events](../02-structured-logging/), [HTTP in Depth](../../01-networking-and-protocols/08-http-in-depth/)
**Time:** ~70 minutes

## The Problem

Your logger is good now: every line a JSON object, every field typed and queryable. At 03:14 the
page fires — **checkout is failing for some users** — and this is one second of production:

```text
{"ts":"03:14:07.901","level":"info","msg":"cart.loaded","user_id":"u_8842","items":3}
{"ts":"03:14:07.901","level":"info","msg":"http.received","user_id":"u_1197","route":"/checkout"}
{"ts":"03:14:07.902","level":"warn","msg":"coupon.expired","user_id":"u_8842","code":"SAVE20"}
{"ts":"03:14:07.902","level":"info","msg":"cart.loaded","user_id":"u_8842","items":1}
{"ts":"03:14:07.903","level":"error","msg":"payment.declined","user_id":"u_8842"}
{"ts":"03:14:07.903","level":"info","msg":"http.responded","user_id":"u_1197","status":200}
```

Six lines out of the ~1,200 that second produced. The process handles **200 concurrent requests**,
so 200 independent stories are written into one stream in whatever order the threads reach the
write. Both obvious filters fail. **Filter by `user_id`** and you get `u_8842`'s lines — but that's
*three* lines from two different carts (`items:3` and `items:1`), because they have three tabs open;
which `cart.loaded` preceded the `payment.declined`? **Filter by timestamp** and two users share
`03:14:07.902` exactly — millisecond resolution is not enough at 1,200 events per second, and
*sorting by time is not grouping by cause.*

Now make it real. That checkout crosses an API gateway, an order-service, a payment-service, and an
inventory worker fed by a queue — **four processes on four machines**, each writing perfect logs to
its own stream. A flawless per-process filter still gives you one quarter of the story, and the
payment-service holds *thousands* of `charge.authorized` lines with nothing saying which was this
checkout. Phase 1's HTTP (HyperText Transfer Protocol) request describes the *client*; nothing in it
says "this is the same unit of work you saw a moment ago."

You need one identifier, created **once**, where the request first touches your system, that then
survives every function boundary, thread, process, and network hop:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 890 350" width="100%" style="max-width:830px" role="img" aria-label="Left panel: eight interleaved log lines from three concurrent requests in one stream, colour-coded, impossible to follow. Right panel: the same stream filtered to a single trace id, showing four lines that form one clear failing-checkout story.">
  <defs><marker id="l03-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="445" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One field turns a pile of lines into one request's story</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="20" y="52" width="380" height="238" rx="12" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="470" y="52" width="400" height="238" rx="12" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.8"><path d="M406 171 L 462 171" marker-end="url(#l03-a1)"/></g>
  <g stroke="none">
    <rect x="36" y="99" width="6" height="11" fill="#3553ff"/><rect x="36" y="123" width="6" height="11" fill="#e0930f"/><rect x="36" y="147" width="6" height="11" fill="#0fa07f"/><rect x="36" y="171" width="6" height="11" fill="#e0930f"/>
    <rect x="36" y="195" width="6" height="11" fill="#3553ff"/><rect x="36" y="219" width="6" height="11" fill="#e0930f"/><rect x="36" y="243" width="6" height="11" fill="#0fa07f"/><rect x="36" y="267" width="6" height="11" fill="#e0930f"/>
    <rect x="488" y="115" width="6" height="11" fill="#e0930f"/><rect x="488" y="157" width="6" height="11" fill="#e0930f"/><rect x="488" y="199" width="6" height="11" fill="#e0930f"/><rect x="488" y="241" width="6" height="11" fill="#e0930f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="80" font-size="11" font-weight="700">raw stream: 3 requests, interleaved</text>
    <text x="52" y="108" font-size="9.5" opacity="0.9">.000  64fdfb26  http.received     u_8842</text>
    <text x="52" y="132" font-size="9.5" opacity="0.9">.007  3e2e8f3b  http.received     u_1197</text>
    <text x="52" y="156" font-size="9.5" opacity="0.9">.013  648028c3  http.received     u_5563</text>
    <text x="52" y="180" font-size="9.5" opacity="0.9">.022  3e2e8f3b  cart.loaded</text>
    <text x="52" y="204" font-size="9.5" opacity="0.9">.031  64fdfb26  cart.loaded</text>
    <text x="52" y="228" font-size="9.5" opacity="0.9">.045  3e2e8f3b  payment.declined</text>
    <text x="52" y="252" font-size="9.5" opacity="0.9">.058  648028c3  cart.loaded</text>
    <text x="52" y="276" font-size="9.5" opacity="0.9">.131  3e2e8f3b  http.responded    402</text>
    <text x="488" y="80" font-size="11" font-weight="700" fill="#0fa07f">filtered: trace_id = 3e2e8f3b…e41d</text>
    <text x="504" y="124" font-size="10">.007  http.received      user=u_1197</text>
    <text x="504" y="166" font-size="10">.022  cart.loaded        items=3</text>
    <text x="504" y="208" font-size="10">.045  payment.declined   insufficient_funds</text>
    <text x="504" y="250" font-size="10">.131  http.responded     status=402</text>
    <text x="504" y="272" font-size="9" opacity="0.72">arrived, cart fine, charge failed, user saw a 402</text>
    <text x="445" y="322" font-size="11" text-anchor="middle" opacity="0.9">Same lines, same order, same timestamps. The only thing added is a shared id.</text>
  </g>
</svg>
```

## The Concept

### Four names for one idea: request ID, correlation ID, trace ID, span ID

These four get used interchangeably, which is why they confuse. Pinned down: a **request ID**
identifies one inbound request to one service (Nginx generates one; its scope is a single hop). A
**correlation ID** is the older generic name for any identifier deliberately propagated across
services — a *pattern*, not a format. A **trace ID** is the standardized version: **16 random
bytes** naming one **request-journey**, everything caused by one user action across every service,
created once and never changed. A **span ID** is **8 random bytes** naming **one operation** inside
that journey — one service's handling, one query, one outbound call — with a start time, an end
time, and a **parent span ID**.

The relationship is a tree. One trace ID is shared by every span; each span records which span
caused it, and those parent pointers assemble a flat list into Lesson 1's waterfall:

```text
trace_id = 3e2e8f3b…e41d          (one per request-journey — never changes)
  span 47901df7  parent=none      gateway: POST /checkout       131 ms
    span 2b533d77  parent=47901df7    order-service: load cart    15 ms
    span 2c5b6f1f  parent=47901df7    payment-service: charge     23 ms
```

Lesson 7 builds spans properly. What matters here is the plumbing: getting these ids to *exist
everywhere* in the process, and to *survive* leaving it.

### Ambient context: why you cannot pass it as an argument

The naive fix is to thread the ID through every function: `def load_cart(user_id, trace_id)`. It
collapses immediately, because logging happens at the *bottom* of the call stack — inside a database
driver, a retry helper, a serializer — so threading a parameter means editing every function in
between, including library code you do not own. One new field, a thousand signatures.

So the ID lives in **ambient context**: state attached to the *current unit of work*, set once at
the edge and readable anywhere without being passed. Python offers two mechanisms; only one is
correct. **`threading.local()`** gives each OS thread its own copy, which works in a
thread-per-request server and is **wrong and dangerous** under `asyncio`, where one thread runs
thousands of coroutines that all share one slot: request A sets the trace ID, awaits a database
call, the loop switches to B, which overwrites the slot, and A resumes and logs B's ID. No error —
just a log stream that is confidently wrong, which is worse than an empty one.

**`contextvars.ContextVar`** (Python 3.7+) is built for this. It reads from the current **Context**,
and the rule that makes it work is **copy-on-task**: when `asyncio` creates a Task, the Task gets a
*snapshot copy* of the current Context, so writes inside it are invisible to its parent and
siblings; each thread likewise starts with its own empty Context. One variable therefore holds a
different value per concurrent request whether the concurrency is threads or coroutines — Phase 8's
two models, one mechanism. `.set()` returns a **Token**, and `.reset(token)` restores the previous
value exactly, which is what lets spans nest and unwind cleanly.

### The wire format: W3C `traceparent`

Ambient context solves *inside* a process. Crossing to another means putting the ID on the wire, and
that format is standardized: **W3C Trace Context** (W3C = World Wide Web Consortium), a
Recommendation since 2021. It defines two HTTP headers; `traceparent` carries identity.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 864 330" width="100%" style="max-width:820px" role="img" aria-label="Byte layout of the W3C traceparent header, split into four dash-separated fields: a two-hex version, a thirty-two-hex trace id, a sixteen-hex parent span id, and two hex trace flags, each explained in a legend below.">
  <text x="432" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">traceparent — 55 bytes of lowercase hex, four fields</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="60" width="80" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="128" y="60" width="380" height="46" rx="9" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    <rect x="526" y="60" width="210" height="46" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="754" y="60" width="80" height="46" rx="9" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="70" y="89" font-size="13">00</text><text x="119" y="89" font-size="13" opacity="0.55">-</text>
    <text x="318" y="89" font-size="12">4bf92f3577b34da6a3ce929d0e0e4736</text><text x="517" y="89" font-size="13" opacity="0.55">-</text>
    <text x="631" y="89" font-size="12">00f067aa0ba902b7</text><text x="745" y="89" font-size="13" opacity="0.55">-</text>
    <text x="794" y="89" font-size="13">01</text>
    <text x="70" y="128" font-size="10.5" font-weight="700">version</text><text x="70" y="144" font-size="9" opacity="0.8">2 hex</text>
    <text x="318" y="128" font-size="10.5" font-weight="700">trace-id</text><text x="318" y="144" font-size="9" opacity="0.8">32 hex  ·  16 bytes</text>
    <text x="631" y="128" font-size="10.5" font-weight="700">parent-id</text><text x="631" y="144" font-size="9" opacity="0.8">16 hex  ·  8 bytes</text>
    <text x="794" y="128" font-size="10.5" font-weight="700">flags</text><text x="794" y="144" font-size="9" opacity="0.8">2 hex</text>
  </g>
  <g stroke="none">
    <rect x="34" y="177" width="13" height="13" rx="3" fill="#3553ff"/><rect x="34" y="211" width="13" height="13" rx="3" fill="#0fa07f"/>
    <rect x="34" y="245" width="13" height="13" rx="3" fill="#e0930f"/><rect x="34" y="279" width="13" height="13" rx="3" fill="#7c5cff"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="58" y="188" font-size="10.5">version — "00" is the only version defined; "ff" is forbidden outright.</text>
    <text x="58" y="222" font-size="10.5">trace-id — the request-journey. Identical on every hop. All-zero is invalid.</text>
    <text x="58" y="256" font-size="10.5">parent-id — the CALLER's span-id. It becomes the parent of your new span.</text>
    <text x="58" y="290" font-size="10.5">trace-flags — bit 0 is 'sampled'. "01" = record this trace, "00" = do not.</text>
    <text x="432" y="318" font-size="10" text-anchor="middle" opacity="0.85">Lowercase hex only — "4BF9…" must be rejected. A receiver that cannot parse it starts a NEW trace.</text>
  </g>
</svg>
```

The widths *are* the spec: **2 + 32 + 16 + 2** hex digits, dash separated, 55 characters. The
**trace-id is 16 bytes** — the size of a UUID (Universally Unique Identifier), so 2^128 values and
no collisions between independent services. The **parent-id is 8 bytes**, and its name is the point:
what the caller sends as `parent-id` is *its own* span-id, which the receiver records as the parent
of the span it creates. That one field builds the tree. Three rejection rules are easy to miss and
all are in the spec — an **all-zero trace-id**, an **all-zero parent-id**, and **uppercase hex** are
each invalid, and version `ff` is forbidden. On any failure, discard the header and **start a fresh
trace**; never propagate something malformed.

### `tracestate` and baggage: the other two headers

**`tracestate`** is a comma-separated list of vendor key-value pairs — `congo=t61rcWkgMzE,rojo=00f067aa`
— letting a tracing vendor record its own position in the trace. Each vendor reads only its key and
passes the rest through, so a request crossing two vendors degrades instead of losing state.

**Baggage** is a separate W3C specification and a different idea: a `baggage` header of *arbitrary
user-defined* key-values — `baggage: tenant=acme,plan=enterprise` — propagated to every downstream
service. It is genuinely useful (a payment-service can log the tenant with no database lookup) and
it has two teeth. **It crosses trust boundaries:** it is an HTTP header, so anything downstream
reads it and anything upstream can forge it — never put secrets or authorization decisions there,
and strip inbound baggage at your public edge rather than forwarding a stranger's keys inward. **It
costs bytes on every hop:** it rides *every* outbound request in the journey, so a 200-byte baggage
set across a fan-out of 30 calls is 6 KB of extra header traffic per request, uncompressed on a
connection's first request (Phase 1, Lesson 11). Keep it to a few small, low-risk fields — tenant,
region, feature-flag cohort.

### Propagation: extract-or-generate in, inject out

The discipline is two rules at every boundary. **Inbound — extract or generate:** read
`traceparent`; if present and valid, continue that trace (reuse the trace-id, take its parent-id as
your parent, mint a new span-id for yourself); if absent or malformed, generate a new trace.
**Outbound — inject:** before every call that leaves the process — HTTP request, queue publish,
remote procedure call — write the current context into the carrier's headers.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:830px" role="img" aria-label="Trace context propagating across boundaries: over HTTP from gateway to order-service to payment-service where it is injected and extracted at each hop, then across a message queue in the message headers to a worker that creates a linked span, and finally a broken path where a worker that never reads the headers starts an orphan trace.">
  <defs><marker id="l03-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="440" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Where context is injected, extracted — and where it is lost</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M204 98 L 282 98" marker-end="url(#l03-a2)"/><path d="M468 98 L 546 98" marker-end="url(#l03-a2)"/>
    <path d="M204 238 L 282 238" marker-end="url(#l03-a2)"/><path d="M468 238 L 546 238" marker-end="url(#l03-a2)"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="6 5" opacity="0.75"><path d="M378 266 L 378 328 L 546 328" marker-end="url(#l03-a2)"/></g>
  <g fill="none" stroke="currentColor" stroke-width="2" opacity="0.85"><path d="M456 320 L 470 336"/><path d="M470 320 L 456 336"/></g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="70" width="180" height="56" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="288" y="70" width="180" height="56" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="552" y="70" width="180" height="56" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="24" y="210" width="180" height="56" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="288" y="210" width="180" height="56" rx="10" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="552" y="210" width="180" height="56" rx="10" fill="#0fa07f" fill-opacity="0.15" stroke="#0fa07f"/>
    <rect x="552" y="300" width="180" height="56" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5" stroke-dasharray="6 5"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="114" y="94" font-size="11" font-weight="700">edge / gateway</text><text x="114" y="112" font-size="9" opacity="0.85">generate trace</text>
    <text x="378" y="94" font-size="11" font-weight="700">order-service</text><text x="378" y="112" font-size="9" opacity="0.85">extract + child span</text>
    <text x="642" y="94" font-size="11" font-weight="700">payment-service</text><text x="642" y="112" font-size="9" opacity="0.85">extract + child span</text>
    <text x="243" y="88" font-size="8.5" opacity="0.85">inject</text><text x="243" y="116" font-size="8.5" opacity="0.7">HTTP</text>
    <text x="507" y="88" font-size="8.5" opacity="0.85">inject</text><text x="507" y="116" font-size="8.5" opacity="0.7">HTTP</text>
    <text x="440" y="152" font-size="10">traceparent: 00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01</text>
    <text x="440" y="170" font-size="9" opacity="0.8">same 32-hex trace-id on every hop; a fresh 16-hex span-id per service</text>
    <text x="114" y="234" font-size="11" font-weight="700">order-service</text><text x="114" y="252" font-size="9" opacity="0.85">publish message</text>
    <text x="378" y="234" font-size="11" font-weight="700">queue: orders</text><text x="378" y="252" font-size="9" opacity="0.85">ctx in HEADERS</text>
    <text x="642" y="234" font-size="11" font-weight="700">worker</text><text x="642" y="252" font-size="9" opacity="0.85">extract + LINKED span</text>
    <text x="243" y="228" font-size="8.5" opacity="0.85">inject into</text><text x="243" y="256" font-size="8.5" opacity="0.7">msg headers</text>
    <text x="507" y="228" font-size="8.5" opacity="0.85">extract</text>
    <text x="642" y="324" font-size="11" font-weight="700">worker (forgets)</text><text x="642" y="342" font-size="9" opacity="0.85">NEW trace_id — orphan</text>
    <text x="500" y="314" font-size="8.5" opacity="0.8">headers ignored</text>
    <text x="440" y="404" font-size="10.5" opacity="0.9">Rule: extract-or-generate once at every inbound edge; inject on every outbound call, HTTP or queue.</text>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="start">
    <text x="28" y="316" font-size="9.5" opacity="0.85">The most common break</text><text x="28" y="332" font-size="9.5" opacity="0.85">in practice is the queue</text>
    <text x="28" y="348" font-size="9.5" opacity="0.85">hop, not the HTTP one.</text>
  </g>
</svg>
```

Along the top, three services share **one 32-hex trace-id** and each mints its own **16-hex
span-id** — inject out, extract in, three times. Along the bottom the same context crosses a queue,
and two things change. First, it goes in the **message headers, never the body**: bodies are the
application's schema, versioned and validated and sometimes consumed by teams who never agreed to
carry your metadata, while headers are the transport's metadata channel — which is exactly what this
is. Kafka has record headers, AMQP (Advanced Message Queuing Protocol) has message properties; both
exist for this (Phase 6).

Second, the consumer's span is **linked** to the producer's, not a child of it. A child span is
*contained* by its parent in time — the parent is still running, waiting. A queued message may be
consumed four hours later, long after the request that produced it returned 202 to the user;
modelling that as a child produces a nonsense trace with a four-hour parent. A **span link** says
"this work was *caused by* that span" without claiming containment. The same reasoning covers the
rest: **background jobs** have no inbound request, so generate a fresh trace at job start and carry
the enqueuing request's trace-id as a link; **fan-out** is the easy case and shows why context must
be *copied* rather than mutated, since each parallel call takes its own child span-id from the same
parent — which copy-on-task gives you free.

### Why the industry standardized this

Correlation IDs are not new; agreement on them is. Before W3C Trace Context every vendor shipped its
own header and none understood each other:

| Header | Origin |
|---|---|
| `X-Request-ID` | ad-hoc convention, no defined format at all |
| `X-B3-TraceId`, `X-B3-SpanId`, `X-B3-Sampled` | B3, from Twitter's Zipkin — several headers, 64- *or* 128-bit ids |
| `uber-trace-id` | Jaeger — one header, four colon-separated fields |
| `X-Amzn-Trace-Id` | AWS X-Ray — `Root=1-<8 hex>-<24 hex>` |

A request crossing two vendors' instrumentation arrived with a header the second did not recognize,
so it **started a new trace** and the journey split in half — broken exactly at the boundary you
most wanted to see across. W3C Trace Context ended that with one header everyone emits and parses.
**B3 is the legacy format you will still meet most often** (Zipkin, older Spring Boot services, some
service meshes), so real gateways accept both and normalize to `traceparent`.

### Automatic log enrichment, and the sampling flag

Once the context is ambient, the logger reads it. No call site passes an ID, no signature grows a
parameter, no developer has to remember: the logger looks up the ContextVar on every emit and stamps
`trace_id` and `span_id` on the event. That is the payoff — correlation becomes a property of the
*logging system* rather than a discipline you hope 40 engineers maintain.

One flag rides along and must be respected. Trace-flags **bit 0 is `sampled`**: `01` means this
trace is being recorded, `00` means it is not. The decision is made **once**, at the head of the
trace, and every downstream service must honour what it receives rather than rolling its own dice. A
service that re-decides independently produces **half-traces** — gateway span recorded, payment span
dropped — which is worse than no trace, because a missing hop looks like a hop that never ran.
Lesson 7 covers sampling *strategy*; the rule here is: propagate the flag you were given.

## Build It

Standard library only: `contextvars` for ambient context, `http.server` and `urllib` for a real
network hop, `asyncio` for the queue. Start with the context itself.

```python
@dataclass(frozen=True)
class SpanContext:
    trace_id: str                          # 16 bytes / 32 lowercase hex
    span_id: str                           # 8 bytes  / 16 lowercase hex
    parent_span_id: Optional[str] = None   # None at the root of the trace
    sampled: bool = True                   # traceparent trace-flags bit 0
    baggage: Dict[str, str] = field(default_factory=dict)
    links: tuple = ()                      # span ids this one is LINKED to

_CURRENT: contextvars.ContextVar[Optional[SpanContext]] = contextvars.ContextVar(
    "request_span_context", default=None)

@contextmanager
def use(ctx: SpanContext):
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)              # restore EXACTLY what was there
```

One module-level variable holds a *different value per concurrent request*, because each thread and
each Task reads its own Context. The `Token` is what makes nesting safe: `.reset(token)` restores
the exact previous value, so a child span unwinds to its parent rather than to `None`. The wire
format is where correctness matters, so the parser enforces every rule the spec states:

```python
def parse_traceparent(header: str) -> SpanContext:
    parts = header.strip().split("-")
    if len(parts) < 4:
        raise TraceparentError(f"expected 4 dash-separated fields, got {len(parts)}")
    version, trace_id, parent_id, flags = parts[0], parts[1], parts[2], parts[3]
    if version == "ff":
        raise TraceparentError("version ff is forbidden by the spec")
    if version == "00" and len(parts) != 4:
        raise TraceparentError("version 00 permits exactly 4 fields, no trailing data")
    if not _is_hex(trace_id, 32):
        raise TraceparentError("trace-id must be 32 lowercase hex digits")
    if trace_id == INVALID_TRACE_ID:
        raise TraceparentError("an all-zero trace-id is invalid")
    # ...the same two checks for parent-id, then the flags width check...
    # THEIR span-id becomes OUR parent. Bit 0 of the flags byte is 'sampled'.
    return SpanContext(trace_id, parent_id, None, bool(int(flags, 16) & 0x01))
```

`_is_hex` tests a lowercase-only character set, so `4BF9…` is rejected. Note the last line: the
caller's `parent-id` lands in *our* `span_id` field, because from our side their span is the one we
descend from. ID generation makes the sizes concrete and builds the tree — `_hex_id` redraws until
it gets a non-zero value, since all-zero is invalid on the wire, and `child_span` changes only the
span, inheriting `trace_id`, `sampled` and `baggage` rather than re-rolling them:

```python
def new_trace(rng, sampled=True, **baggage) -> SpanContext:
    return SpanContext(_hex_id(rng, 16), _hex_id(rng, 8), None, sampled, dict(baggage))

def child_span(parent: SpanContext, rng) -> SpanContext:
    return replace(parent, span_id=_hex_id(rng, 8),
                   parent_span_id=parent.span_id, links=())
```

Now the payoff. The logger takes no trace argument anywhere, and the two propagation primitives are
a dozen lines — the whole of what OpenTelemetry's propagator API does:

```python
def event(self, msg: str, ts_ms=None, **fields) -> Dict[str, Any]:
    rec = {"ts": ..., "level": fields.pop("level", "info"),
           "service": self.service, "msg": msg}
    ctx = current()
    if ctx is not None:                      # <- the entire payoff of the lesson
        rec["trace_id"], rec["span_id"] = ctx.trace_id, ctx.span_id
        if ctx.parent_span_id:
            rec["parent_span_id"] = ctx.parent_span_id
        rec.update(ctx.baggage)
    rec.update(fields)

def inject(headers: Dict[str, str]) -> Dict[str, str]:
    ctx = current()
    if ctx is None:
        return headers
    headers["traceparent"] = format_traceparent(ctx)
    if ctx.baggage:
        headers["baggage"] = format_baggage(ctx.baggage)
    return headers

def extract(headers: Dict[str, str]) -> Optional[SpanContext]:
    raw = headers.get("traceparent")
    if not raw:
        return None
    try:
        ctx = parse_traceparent(raw)
    except TraceparentError:
        return None                          # malformed -> restart the trace
    bag = headers.get("baggage")
    return replace(ctx, baggage=parse_baggage(bag)) if bag else ctx
```

Every boundary in the program is then one expression: an HTTP handler does
`child_span(parent, rng) if parent else new_trace(rng)`, and a queue consumer does the same thing
with `links=(remote.span_id,)` instead of a parent — falling back to `new_trace()`, an orphan, when
no context arrived. The rest — deterministic clock, baggage percent-encoding, the `http.server`
payment-service on an ephemeral port, and the thread and `asyncio` demos — is in
[`code/request_context.py`](code/request_context.py). Run it with `python3 request_context.py`. It
opens by checking the parser against the spec's edge cases:

```console
== TRACEPARENT: PARSE AND VALIDATE ==
  00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
      accept  span=00f067aa0ba902b7  sampled=yes
  00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-00
      accept  span=00f067aa0ba902b7  sampled=no
  00-4BF92F3577B34DA6A3CE929D0E0E4736-00f067aa0ba902b7-01
      REJECT  trace-id must be 32 lowercase hex digits
  00-00000000000000000000000000000000-00f067aa0ba902b7-01
      REJECT  an all-zero trace-id is invalid
  00-4bf92f3577b34da6a3ce929d0e0e4736-0000000000000000-01
      REJECT  an all-zero parent-id is invalid
  00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-extra
      REJECT  version 00 permits exactly 4 fields, no trailing data
  ff-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01
      REJECT  version ff is forbidden by the spec
  01-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01-x9
      accept  span=00f067aa0ba902b7  sampled=yes
```

Eight cases, six rejections, and the last is the interesting one: a **version `01`** header with a
trailing field is **accepted**, because the spec requires receivers to tolerate future versions by
parsing the first four fields and ignoring the rest — while the *same* trailing field under version
`00` is rejected. Forward compatibility is a rule, not a courtesy. The two accepted `00` headers
differ only in flags: `01` gives `sampled=yes`, `00` gives `sampled=no`, read from bit 0. Next, a
real HTTP request between two services — `http.server` on an ephemeral port, called with `urllib`:

```console
== HTTP HOP: TWO SERVICES, ONE TRACE ==
  03:14:07.003  gateway  trace=e58cb8cd span=4141573b  checkout.received  tenant=acme route=/checkout user=u_8842
  -> outbound header  traceparent: 00-e58cb8cd0fc7324f53ff3733fd19ecf9-c47ec9125d1ccb31-01
  -> outbound header  baggage:     tenant=acme
  03:14:07.006  payment  trace=e58cb8cd span=b55f7c72  charge.authorized  tenant=acme amount_cents=4999 parent=c47ec912
  03:14:07.009  gateway  trace=e58cb8cd span=4141573b  checkout.completed tenant=acme status=200
  gateway trace_id  e58cb8cd0fc7324f53ff3733fd19ecf9
  payment trace_id  e58cb8cd0fc7324f53ff3733fd19ecf9   same trace: True
  payment span_id   b55f7c728924d092   (a NEW span, not the gateway's)
```

Follow the identifiers. The gateway mints trace `e58cb8cd…` and root span `4141573b`; for the
outbound call it opens a **child span** `c47ec912…` and injects *that* as the `parent-id`, which is
why the header shows `c47ec9125d1ccb31` and not the root span. The payment-service, running in a
different thread with a completely empty Context, extracts it and logs `trace=e58cb8cd` with
`parent=c47ec912`: **same trace, new span `b55f7c72`, correct parent.** The trace survived a real
socket. And `tenant=acme` appears on the payment-service's line without that service knowing
anything about tenants — baggage arriving over the wire and merging into the log automatically.

Now the part that matters at 03:14. Three requests run on three threads, released together by a
`threading.Barrier` so they genuinely overlap, and every line lands in one stream:

```console
== THREE CONCURRENT REQUESTS, ONE INTERLEAVED STREAM ==
  03:14:10.000  gateway  trace=64fdfb26 span=f0aec93b  http.received      user=u_8842
  03:14:10.007  gateway  trace=3e2e8f3b span=47901df7  http.received      user=u_1197
  03:14:10.013  gateway  trace=648028c3 span=a2ac4934  http.received      user=u_5563
  03:14:10.022  gateway  trace=3e2e8f3b span=2b533d77  cart.loaded        items=3
  03:14:10.031  gateway  trace=64fdfb26 span=3826edb4  cart.loaded        items=3
  03:14:10.045  gateway  trace=3e2e8f3b span=2c5b6f1f  payment.declined   reason=insufficient_funds
  03:14:10.058  gateway  trace=648028c3 span=fb0744de  cart.loaded        items=3
  03:14:10.074  gateway  trace=648028c3 span=bcb18b17  payment.captured   amount_cents=4999
  03:14:10.089  gateway  trace=648028c3 span=a2ac4934  http.responded     status=200
  03:14:10.096  gateway  trace=64fdfb26 span=adced10a  payment.captured   amount_cents=4999
  03:14:10.118  gateway  trace=64fdfb26 span=f0aec93b  http.responded     status=200
  03:14:10.131  gateway  trace=3e2e8f3b span=47901df7  http.responded     status=402

== THE SAME STREAM, FILTERED TO ONE trace_id ==
  trace_id = 3e2e8f3bb7afa3b2b585e9ff7d30e41d
  03:14:10.007  gateway  trace=3e2e8f3b span=47901df7  http.received      user=u_1197
  03:14:10.022  gateway  trace=3e2e8f3b span=2b533d77  cart.loaded        items=3
  03:14:10.045  gateway  trace=3e2e8f3b span=2c5b6f1f  payment.declined   reason=insufficient_funds
  03:14:10.131  gateway  trace=3e2e8f3b span=47901df7  http.responded     status=402
```

This is the whole lesson in twelve lines and then four. Above, three requests are shredded into each
other — `3e2e8f3b`'s `cart.loaded` at `.022` is followed by a *different* request's `cart.loaded` at
`.031`, and nothing in the message text tells them apart. Below, one equality test on one field
reconstructs the failing checkout end to end: arrived `.007`, cart fine `.022`, **declined `.045`**,
402 returned `.131`. Read the span column too: `47901df7` bookends the story because it is the root
span, while `2b533d77` and `2c5b6f1f` are child spans opened inside `load_cart()` and
`charge_card()` — functions whose signatures contain **no trace argument at all**. They read the
ContextVar. The last blocks cross a queue, under `asyncio` rather than threads:

```console
== ACROSS A QUEUE: CONTEXT RIDES IN THE MESSAGE HEADERS ==
  03:14:07.012  worker   trace=1d5dbbd2 span=27f6ee32  order.placed       tenant=acme order_id=o_1
  03:14:07.015  worker   trace=a2727e3d span=7b1f8a8c  order.placed       tenant=acme order_id=o_2
  03:14:07.018  worker   trace=1d5dbbd2 span=27f6ee32  queue.published    tenant=acme queue=orders headers=2
  03:14:07.021  worker   trace=a2727e3d span=7b1f8a8c  queue.published    tenant=acme queue=orders headers=2
  03:14:07.024  worker   trace=1d5dbbd2 span=f2a74de4  order.processed    tenant=acme order=o_1 linked_to=f43b9807
  03:14:07.027  worker   trace=a2727e3d span=6513270e  order.processed    tenant=acme order=o_2 linked_to=96fd9077
  ...and now a consumer that forgets to read the headers:
  03:14:07.030  worker   trace=c393fd0e span=240f16a7  order.processed    order=o_3 linked_to=none
  producer 1 trace_id  1d5dbbd24b6a31aaa8e9b6116e64679e
  producer 2 trace_id  a2727e3da59d8a0845e037f4fc4186c2   (two Tasks, two contexts, no bleed)

== ONE RAW EVENT — WHAT IS ACTUALLY WRITTEN TO STDOUT ==
  {"ts":"03:14:10.022","level":"info","service":"gateway","msg":"cart.loaded","trace_id":"3e2e8f3bb7afa3b2b585e9ff7d30e41d","span_id":"2b533d7770344ba1","parent_span_id":"47901df75806216f","items":3}
```

Two producer coroutines ran concurrently and their traces never touched: every `o_1` line carries
`1d5dbbd2`, every `o_2` line carries `a2727e3d`, though both Tasks wrote to the *same* ContextVar.
That is copy-on-task doing its job — precisely what a `threading.local()` would have corrupted. The
consumer ran with an empty Context (the code asserts it) and rebuilt everything from `headers=2`,
producing a span **linked** to the producer's rather than parented by it. Then the counter-example:
the consumer that ignores the headers logs `trace=c393fd0e`, an ID appearing nowhere else in the run
and linking to nothing. That line is an orphan, and in production it is the line you search for at
03:14 and never find. The final block is what actually reaches stdout — plain JSON carrying
`trace_id`, `span_id` and `parent_span_id` on an event whose call site passed none of them.

## Use It

You will not write this by hand in production. You will configure it — and it will be the code you
just wrote. **A middleware does the inbound half.** In an ASGI (Asynchronous Server Gateway
Interface) application — Starlette, FastAPI — extract-or-generate belongs in one middleware every
request passes through:

```python
class TraceContextMiddleware:
    def __init__(self, app): self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        parent = extract(headers)                       # W3C traceparent, if any
        ctx = child_span(parent, rng) if parent else new_trace(rng)

        async def send_wrapper(message):                # echo the id back to the caller
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append(
                    (b"traceparent", format_traceparent(ctx).encode()))
            await send(message)

        with use(ctx):                                  # bound for the whole request
            await self.app(scope, receive, send_wrapper)
```

Everything downstream of that `with` — handlers, database calls, the logger — sees the context
without being handed it. **OpenTelemetry ships this as an API.** OpenTelemetry (OTel) is the
vendor-neutral instrumentation standard from Lesson 1, and its **propagators** are exactly
`inject`/`extract` over a "carrier":

```python
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

propagator = TraceContextTextMapPropagator()
propagator.inject(headers)                    # writes 'traceparent' into a dict
ctx = propagator.extract(carrier=headers)     # reads it back on the other side
```

`TraceContextTextMapPropagator` is the W3C implementation; `B3MultiFormat` speaks the legacy Zipkin
headers, and a `CompositePropagator` accepts both inbound — the standard configuration for a gateway
fronting a mixed estate. OTel's auto-instrumentation wraps common HTTP clients so `inject` happens
without your code calling it, but the mechanism is the one you built.

**Your infrastructure is probably already generating an ID** before your process sees the request:

| Component | Header it sets |
|---|---|
| Nginx | `$request_id` — a 32-hex value you forward via `proxy_set_header` |
| Envoy / Istio | `x-request-id`, and it propagates `traceparent` and B3 |
| AWS Application Load Balancer (ALB) | `X-Amzn-Trace-Id` |
| Cloudflare | `cf-ray` |

The operational rule is one sentence: **accept and reuse an inbound ID; never mint a new one when
one already arrived.** A service that overwrites the gateway's ID severs the trace at its own front
door and makes the load balancer's access logs unjoinable to the application's.

**Queues carry it in headers.** Kafka has record headers (`ProducerRecord.headers()`), RabbitMQ and
AMQP have `basic_properties.headers`, and both OTel instrumentations write `traceparent` there.
Whatever the broker, the Phase 6 discipline holds: metadata in headers, payload in the body, and the
consumer creates a **linked** span because the producer is long gone.

**Put the trace ID in the error response.** This is the highest-value change in the whole lesson:

```json
{"error": "payment_failed", "trace_id": "3e2e8f3bb7afa3b2b585e9ff7d30e41d"}
```

A user pastes that into a support ticket and you have their exact request — every service, every log
line, every timing — in one query, with no "what time was it, roughly?" round trip. Return it on
errors always, and consider returning it on every response as a `traceparent` header. Keep it
opaque: a trace ID is a lookup key, never a secret, and must never encode anything about the user.

## Think about it

1. Your service stores the trace ID in a `threading.local()` and works perfectly. You migrate to
   `asyncio`, the tests still pass, and production logs start attributing events to the wrong
   requests. What exactly happened, and why did the tests miss it?
2. A request arrives at your public API with `traceparent: 00-4bf9…-00f0…-01` and
   `baggage: tenant=acme,internal_admin=true`. Which do you propagate, which do you drop, and why is
   the answer different for the two headers?
3. A message is published during an HTTP request and consumed four hours later by a batch worker.
   Why is modelling the consumer's span as a *child* of the producer's wrong, and what does a span
   link claim instead?
4. Your gateway samples 1% of traces and sets the flag; the payment-service ignores the incoming
   flag and samples 1% independently. Roughly what fraction of gateway-sampled traces include their
   payment span, and why is a half-trace more misleading than no trace?
5. You are asked to put `user_email` in baggage so every downstream service can log it. Give three
   separate reasons to refuse — one about cost, one about security, and one from Phase 4 Lesson 5
   about what happens when someone then puts it in a metric label.

## Key takeaways

- Structured logs are still one shuffled stream: at 200 concurrent requests, `user_id` and
  millisecond-timestamp filters both fail. Correlation needs **one identifier minted once** — a
  **trace ID** (16 bytes, one per request-journey), a **span ID** (8 bytes, one per operation), and
  a **parent span ID** that assembles the spans into a tree.
- The ID cannot be a function parameter, so it lives in **ambient context**. Use
  **`contextvars.ContextVar`**, never `threading.local()`: a ContextVar is per-thread *and*
  snapshotted per `asyncio` Task (**copy-on-task**), while a thread-local under `asyncio` silently
  attributes events to the wrong request.
- The wire format is the **W3C Trace Context** Recommendation: `traceparent` =
  `version(2 hex)-trace-id(32 hex/16 B)-parent-id(16 hex/8 B)-trace-flags(2 hex)`, lowercase only.
  All-zero ids are invalid, version `ff` is forbidden, future versions must be parsed leniently, and
  an unparseable header means **start a new trace**. `tracestate` carries vendor state; **baggage**
  carries arbitrary key-values, costs bytes on every hop, and crosses trust boundaries — keep it
  tiny and never secret.
- Propagation is two rules at every boundary: **extract-or-generate inbound** (reuse an inbound ID,
  never overwrite it) and **inject outbound** on every HTTP call, queue publish and RPC. Across a
  queue the context travels in **message headers, not the body**, and the consumer's span is
  **linked** to the producer's rather than a child, because the parent finished long ago.
- The standard exists because `X-Request-ID`, B3/Zipkin, `uber-trace-id` and `X-Amzn-Trace-Id` all
  disagreed, so a request crossing two vendors lost its identity mid-journey. **B3 is the legacy
  format you will still meet**; accept both at the edge and normalize to `traceparent`.
- Once the context is ambient the **logger enriches every event automatically**, and the **sampled
  flag must be propagated, not re-decided** — half-traces make a missing hop look like a hop that
  never ran. Surface the trace ID in error responses so a user can hand you their exact request.

Next: [The Log Pipeline: Ship, Store, Query — and What It Costs](../04-the-log-pipeline/) — now that
every line is correlated, the question becomes how those lines leave the machine, where they land,
what querying them costs, and why log bills have been known to exceed the compute they watch.
