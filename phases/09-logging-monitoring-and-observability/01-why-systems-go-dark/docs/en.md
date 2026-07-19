# Why Systems Go Dark: Monitoring, Observability & the Three Pillars

> Your code works on your laptop because you can *see* it — you read the error, you add a `print`, you step through a debugger. In production you can do none of that: the process is on a machine you're not sitting at, serving thousands of strangers, and it will not reproduce the bug for you. Observability is how you get your eyes back. This lesson explains what actually went dark, why "monitoring" alone stopped being enough, and what logs, metrics, and traces each really are — before you build any of them.

**Type:** Learn
**Languages:** —
**Prerequisites:** none
**Time:** ~50 minutes

## The Problem

It's 03:14. Your phone buzzes: **"Checkout is broken."** That's the entire report. You open your laptop and try to answer three questions that a user has already decided the answer to:

1. **Is it actually broken?** For everyone, or for one person on bad hotel Wi-Fi?
2. **What is broken?** Your code, the database, a third-party payment API, DNS, the load balancer?
3. **When did it start, and what changed then?**

On your laptop these are trivial. You'd reproduce the checkout, watch the exception print to your terminal, and read the stack trace. But production is not your laptop, and every one of those moves is gone:

- **You cannot reproduce it.** The bug needs a specific user, with a specific coupon, on a specific database row, at a specific moment of load. It happened once, for them, four minutes ago.
- **You cannot attach a debugger.** Even if the machine let you, pausing a live process to inspect a variable freezes real people's checkouts.
- **You cannot "just look at the server."** There are forty of them behind a load balancer, and the request went to one — you don't know which.
- **The moment is already gone.** The request finished. Its memory was freed. Unless the program *wrote something down* while it was happening, the evidence has been garbage-collected.

That last point is the whole subject. **A running system tells you nothing by default.** It is a black box that accepts requests and returns responses, and every internal fact — which branch it took, how long the database call blocked, why it returned a 500 — is destroyed microseconds after it exists. What you know about production at 03:14 is exactly, and only, what your program deliberately emitted while it was running.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 300" width="100%" style="max-width:720px" role="img" aria-label="Production as a black box: requests go in and responses come out, but the internal state — variables, branches taken, timings — is invisible from outside unless the program emits signals.">
  <defs>
    <marker id="obs-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="390" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Production is a black box — you only get what it chose to emit</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M96 132 L 236 132" marker-end="url(#obs-a1)"/>
    <path d="M544 132 L 684 132" marker-end="url(#obs-a1)"/>
    <path d="M390 214 L 390 250" marker-end="url(#obs-a1)" stroke-dasharray="6 5"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="240" y="62" width="304" height="152" rx="14" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor"/>
    <rect x="272" y="92" width="110" height="40" rx="8" fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 5"/>
    <rect x="402" y="92" width="110" height="40" rx="8" fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 5"/>
    <rect x="272" y="146" width="240" height="40" rx="8" fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 5"/>
    <rect x="264" y="250" width="252" height="42" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="70" y="128" font-size="11.5">request</text>
    <text x="70" y="145" font-size="9.5" opacity="0.7">POST /checkout</text>
    <text x="712" y="128" font-size="11.5">response</text>
    <text x="712" y="145" font-size="9.5" opacity="0.7">500, 4.2s</text>
    <text x="392" y="52" font-size="11" opacity="0.85">your service, on a machine you are not sitting at</text>
    <text x="327" y="116" font-size="10" opacity="0.6">local variables</text>
    <text x="457" y="116" font-size="10" opacity="0.6">branch taken</text>
    <text x="392" y="164" font-size="10" opacity="0.6">how long the DB call blocked</text>
    <text x="392" y="182" font-size="9" opacity="0.5">all of it freed microseconds after it existed</text>
    <text x="390" y="268" font-size="11" font-weight="700" fill="#0fa07f">SIGNALS the program deliberately emitted</text>
    <text x="390" y="284" font-size="9.5" opacity="0.85">logs · metrics · traces — the only evidence that outlives the request</text>
  </g>
</svg>
```

## The Concept

### Telemetry: writing things down before they vanish

Everything in this phase is one idea applied three ways: **make the program write down what it is doing, in a form you can search later.** The generic name for that emitted data is **telemetry** (Greek *tele* "remote" + *metron* "measure" — measurement at a distance). Telemetry is not a debugging afterthought; it is a *feature of the program*, written deliberately, that turns a black box into something you can ask questions of.

You already know the crudest form:

```python
print("got here")           # the original telemetry
print("user:", user_id)     # ...and the original structured logging
```

That instinct is right. The rest of this phase is that instinct, made durable, searchable, cheap, and correlated across forty machines.

### Monitoring vs. observability (they are not synonyms)

These two words get used interchangeably in job ads, and the difference genuinely matters — it's the difference between the questions you thought of in advance and the ones you didn't.

**Monitoring** is the *activity*: you decide in advance which numbers matter, you collect them continuously, and you alert when one crosses a line. "CPU above 90% for five minutes → page someone." Monitoring answers **questions you already knew to ask**. It is excellent at *"is it broken?"* — and it has been the job since the first sysadmin graphed a disk filling up.

**Observability** is a *property of the system*: how well can you infer what's happening **inside** it from the signals it emits **outside**? The term is borrowed, precisely, from control theory — Rudolf Kálmán's 1960 work on control systems defined a system as *observable* if its internal state can be determined from its external outputs alone. Applied to software: can you answer a question you never anticipated, about a failure you've never seen, **without shipping new code**? Observability targets *"why is it broken?"*

The distinction has a practical shape — **known unknowns vs. unknown unknowns**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 344" width="100%" style="max-width:740px" role="img" aria-label="Monitoring versus observability: monitoring covers known failure modes with predefined dashboards and alerts, observability covers novel failures by letting you ask new questions of rich data after the fact.">
  <text x="400" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Two different jobs, often confused</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="48" width="360" height="248" rx="14" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="410" y="48" width="360" height="248" rx="14" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <line x1="54" y1="112" x2="366" y2="112" stroke="#3553ff" stroke-opacity="0.45" stroke-width="1.4"/>
    <line x1="434" y1="112" x2="746" y2="112" stroke="#7c5cff" stroke-opacity="0.45" stroke-width="1.4"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="210" y="80" font-size="14" font-weight="700" text-anchor="middle" fill="#3553ff">MONITORING</text>
    <text x="210" y="99" font-size="10" text-anchor="middle" opacity="0.85">an activity you perform</text>
    <text x="590" y="80" font-size="14" font-weight="700" text-anchor="middle" fill="#7c5cff">OBSERVABILITY</text>
    <text x="590" y="99" font-size="10" text-anchor="middle" opacity="0.85">a property your system has</text>
    <text x="54" y="140" font-size="11" font-weight="700">Known unknowns</text>
    <text x="54" y="160" font-size="10.5" opacity="0.9">You knew to watch disk usage.</text>
    <text x="54" y="177" font-size="10.5" opacity="0.9">You did not know today's value.</text>
    <text x="54" y="206" font-size="11" font-weight="700">Answers:  is it broken?</text>
    <text x="54" y="230" font-size="10.5" opacity="0.9">Predefined dashboards, thresholds,</text>
    <text x="54" y="247" font-size="10.5" opacity="0.9">alerts. Aggregate numbers.</text>
    <text x="54" y="276" font-size="10" opacity="0.75">Fails when: the failure is one</text>
    <text x="54" y="291" font-size="10" opacity="0.75">nobody wrote a check for.</text>
    <text x="434" y="140" font-size="11" font-weight="700">Unknown unknowns</text>
    <text x="434" y="160" font-size="10.5" opacity="0.9">"Checkout fails only for Android</text>
    <text x="434" y="177" font-size="10.5" opacity="0.9">users on the new coupon path."</text>
    <text x="434" y="206" font-size="11" font-weight="700">Answers:  why is it broken?</text>
    <text x="434" y="230" font-size="10.5" opacity="0.9">Ask a new question of rich data</text>
    <text x="434" y="247" font-size="10.5" opacity="0.9">after the fact — no code deploy.</text>
    <text x="434" y="276" font-size="10" opacity="0.75">Fails when: the data was never</text>
    <text x="434" y="291" font-size="10" opacity="0.75">emitted, or can't be joined up.</text>
    <text x="400" y="326" font-size="11" text-anchor="middle" opacity="0.9">You need both. Monitoring wakes you up; observability tells you what to do once you're awake.</text>
  </g>
</svg>
```

Why this became urgent rather than academic: in 2005 your system was **one program on one machine**. Something broke, you SSH'd in, ran `tail -f app.log`, and read it. The whole system's state fit in one file on one box. Today one checkout click can fan out across a dozen services, a queue, three databases, and a payment provider (Phase 6 builds exactly this world). No single machine holds the story anymore, and the *number of ways* it can fail exploded past the number of dashboards anyone can pre-build. The failure that pages you at 03:14 is, increasingly, one nobody anticipated — which is precisely the failure monitoring alone cannot explain.

### The three pillars: logs, metrics, traces

Telemetry comes in three shapes. They are not three competing products — they are three different **trade-offs between detail and cost**, and a real system emits all three because each answers a question the others can't.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 430" width="100%" style="max-width:820px" role="img" aria-label="The three pillars of observability: metrics are cheap aggregate numbers answering whether something is wrong, logs are detailed discrete events answering what exactly happened, traces follow one request across services answering where the time went.">
  <text x="430" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The three pillars — three trade-offs between detail and cost</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="46" width="264" height="300" rx="14" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="298" y="46" width="264" height="300" rx="14" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="572" y="46" width="264" height="300" rx="14" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <line x1="44" y1="146" x2="268" y2="146" stroke="#3553ff" stroke-opacity="0.4" stroke-width="1.3"/>
    <line x1="318" y1="146" x2="542" y2="146" stroke="#0fa07f" stroke-opacity="0.4" stroke-width="1.3"/>
    <line x1="592" y1="146" x2="816" y2="146" stroke="#e0930f" stroke-opacity="0.4" stroke-width="1.3"/>
    <line x1="44" y1="262" x2="268" y2="262" stroke="#3553ff" stroke-opacity="0.3" stroke-width="1.1" stroke-dasharray="4 4"/>
    <line x1="318" y1="262" x2="542" y2="262" stroke="#0fa07f" stroke-opacity="0.3" stroke-width="1.1" stroke-dasharray="4 4"/>
    <line x1="592" y1="262" x2="816" y2="262" stroke="#e0930f" stroke-opacity="0.3" stroke-width="1.1" stroke-dasharray="4 4"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="156" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#3553ff">METRICS</text>
    <text x="156" y="96" font-size="10" text-anchor="middle" opacity="0.85">numbers over time</text>
    <text x="156" y="123" font-size="11.5" text-anchor="middle" font-weight="700">"Is something wrong?"</text>
    <text x="44" y="170" font-size="10" opacity="0.9">A count or measurement,</text>
    <text x="44" y="186" font-size="10" opacity="0.9">aggregated as it is recorded.</text>
    <text x="44" y="210" font-size="9.5" opacity="0.75">http_requests_total</text>
    <text x="44" y="225" font-size="9.5" opacity="0.75">  {route="/checkout",</text>
    <text x="44" y="240" font-size="9.5" opacity="0.75">   status="500"}  = 412</text>
    <text x="44" y="286" font-size="10" font-weight="700">Cost: tiny, constant</text>
    <text x="44" y="304" font-size="9.5" opacity="0.85">Detail: none — no user,</text>
    <text x="44" y="319" font-size="9.5" opacity="0.85">no request, no stack</text>
    <text x="44" y="337" font-size="9.5" opacity="0.85">Retention: months–years</text>
    <text x="430" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#0fa07f">LOGS</text>
    <text x="430" y="96" font-size="10" text-anchor="middle" opacity="0.85">discrete events</text>
    <text x="430" y="123" font-size="11.5" text-anchor="middle" font-weight="700">"What exactly happened?"</text>
    <text x="318" y="170" font-size="10" opacity="0.9">A timestamped record of one</text>
    <text x="318" y="186" font-size="10" opacity="0.9">thing, with full context.</text>
    <text x="318" y="210" font-size="9.5" opacity="0.75">{"ts":"03:14:07.912",</text>
    <text x="318" y="225" font-size="9.5" opacity="0.75"> "level":"error",</text>
    <text x="318" y="240" font-size="9.5" opacity="0.75"> "user_id":"u_8842", ...}</text>
    <text x="318" y="286" font-size="10" font-weight="700">Cost: high, scales w/ traffic</text>
    <text x="318" y="304" font-size="9.5" opacity="0.85">Detail: maximum — every</text>
    <text x="318" y="319" font-size="9.5" opacity="0.85">field you chose to attach</text>
    <text x="318" y="337" font-size="9.5" opacity="0.85">Retention: days–weeks</text>
    <text x="704" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#e0930f">TRACES</text>
    <text x="704" y="96" font-size="10" text-anchor="middle" opacity="0.85">causal request paths</text>
    <text x="704" y="123" font-size="11.5" text-anchor="middle" font-weight="700">"Where did the time go?"</text>
    <text x="592" y="170" font-size="10" opacity="0.9">One request's journey across</text>
    <text x="592" y="186" font-size="10" opacity="0.9">every service that touched it.</text>
    <text x="592" y="210" font-size="9.5" opacity="0.75">api ─────────── 4200ms</text>
    <text x="592" y="225" font-size="9.5" opacity="0.75"> └ cart ──── 120ms</text>
    <text x="592" y="240" font-size="9.5" opacity="0.75"> └ payment ── 4050ms  ←</text>
    <text x="592" y="286" font-size="10" font-weight="700">Cost: high → usually sampled</text>
    <text x="592" y="304" font-size="9.5" opacity="0.85">Detail: structure &amp; timing</text>
    <text x="592" y="319" font-size="9.5" opacity="0.85">across service boundaries</text>
    <text x="592" y="337" font-size="9.5" opacity="0.85">Retention: days</text>
    <text x="430" y="380" font-size="11.5" text-anchor="middle" font-weight="700">The workflow: a METRIC alerts you · a TRACE localizes the slow or failing hop · a LOG explains that hop</text>
    <text x="430" y="404" font-size="10.5" text-anchor="middle" opacity="0.85">Detail increases left to right. So does cost. That is the entire trade-off.</text>
  </g>
</svg>
```

Read the pillars as an **investigation funnel**, because that's how you'll actually use them:

- A **metric** is a number recorded over time, aggregated the moment it's taken — `http_requests_total{status="500"}`. It's tiny (a counter costs a few bytes no matter how many requests it counts), so you keep it for a year and graph it for the whole fleet at once. Its weakness is the flip side of that strength: **aggregation destroys the individual**. A metric can tell you 412 requests failed. It can never tell you *whose*.
- A **log** is a timestamped record of one specific event, with as much context as you cared to attach. It's the opposite trade: **maximum detail, maximum cost.** Log every request and your log bill scales linearly with traffic — which is why Lesson 4 is entirely about what that costs and how to control it.
- A **trace** follows **one request** across every service it touched, recording how long each hop took and which called which. It's the only pillar that captures **causality across process boundaries** — the thing that was free when everything ran in one process (you had a stack trace) and vanished the moment you split into services.

The funnel in practice: *the metric wakes you (error rate for `/checkout` jumped at 03:09) → the trace localizes it (the payment-service hop went from 40 ms to 4 s) → the log explains it (`"connection pool exhausted, waited 3980ms"`)*. Each pillar hands off to the next. This is why "just add more logging" is not a strategy: you'd pay log prices for metric-shaped questions and still not have the cross-service causality only a trace carries.

### The one thing that makes the three pillars work: correlation

Three separate piles of data are three separate haystacks. What turns them into one investigation is a shared identifier stamped on all of it — a **trace ID** (also called a correlation ID or request ID) generated once at the edge and carried through every service, every log line, and every span.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 320" width="100%" style="max-width:760px" role="img" aria-label="A trace ID generated at the edge is propagated through every service and stamped onto every log line and span, so logs, metrics exemplars and traces can be joined into one investigation.">
  <defs>
    <marker id="obs-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="410" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One ID, stamped on everything — the spine of every investigation</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M170 84 L 246 84" marker-end="url(#obs-a2)"/>
    <path d="M406 84 L 482 84" marker-end="url(#obs-a2)"/>
    <path d="M642 84 L 700 84" marker-end="url(#obs-a2)"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="34" y="62" width="136" height="44" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="248" y="62" width="158" height="44" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="484" y="62" width="158" height="44" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="702" y="62" width="84" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="34" y="176" width="228" height="112" rx="11" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    <rect x="296" y="176" width="228" height="112" rx="11" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="558" y="176" width="228" height="112" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="5 5" opacity="0.65">
    <path d="M102 108 L 102 172" marker-end="url(#obs-a2)"/>
    <path d="M327 108 L 380 172" marker-end="url(#obs-a2)"/>
    <path d="M563 108 L 640 172" marker-end="url(#obs-a2)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="102" y="88" font-size="11" text-anchor="middle" font-weight="700">edge / gateway</text>
    <text x="327" y="82" font-size="11" text-anchor="middle" font-weight="700">order-service</text>
    <text x="327" y="98" font-size="9" text-anchor="middle" opacity="0.8">receives the ID</text>
    <text x="563" y="82" font-size="11" text-anchor="middle" font-weight="700">payment-service</text>
    <text x="563" y="98" font-size="9" text-anchor="middle" opacity="0.8">receives the ID</text>
    <text x="744" y="88" font-size="10.5" text-anchor="middle">bank API</text>
    <text x="102" y="128" font-size="9" text-anchor="middle" opacity="0.9">generates</text>
    <text x="102" y="142" font-size="9" text-anchor="middle" opacity="0.9">trace_id=4bf9…c31</text>
    <text x="148" y="202" font-size="11.5" text-anchor="middle" font-weight="700" fill="#0fa07f">LOGS</text>
    <text x="48" y="226" font-size="9" opacity="0.9">every line carries</text>
    <text x="48" y="242" font-size="9" opacity="0.9">trace_id=4bf9…c31</text>
    <text x="48" y="266" font-size="9" opacity="0.75">→ grep one ID, get the</text>
    <text x="48" y="279" font-size="9" opacity="0.75">   whole request's story</text>
    <text x="410" y="202" font-size="11.5" text-anchor="middle" font-weight="700" fill="#e0930f">TRACES</text>
    <text x="310" y="226" font-size="9" opacity="0.9">spans share the trace_id</text>
    <text x="310" y="242" font-size="9" opacity="0.9">and nest by parent span</text>
    <text x="310" y="266" font-size="9" opacity="0.75">→ the waterfall of where</text>
    <text x="310" y="279" font-size="9" opacity="0.75">   the 4.2 seconds went</text>
    <text x="672" y="202" font-size="11.5" text-anchor="middle" font-weight="700" fill="#3553ff">METRICS</text>
    <text x="572" y="226" font-size="9" opacity="0.9">aggregate — no ID inside,</text>
    <text x="572" y="242" font-size="9" opacity="0.9">but exemplars pin a few</text>
    <text x="572" y="266" font-size="9" opacity="0.75">→ click the spike on the</text>
    <text x="572" y="279" font-size="9" opacity="0.75">   graph, land on a trace</text>
  </g>
</svg>
```

Without that shared ID you have three dashboards and a guess. With it you have one story you can pull end to end. It is the single highest-leverage thing in this phase, which is why Lesson 3 does nothing else, and why the industry standardized the wire format for it — the **W3C Trace Context** `traceparent` header, which every modern tool speaks.

### Where telemetry goes: the pipeline

The same four stages sit under every observability stack you will ever meet, whether it's three open-source containers or a vendor with a sales team:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 268" width="100%" style="max-width:800px" role="img" aria-label="The observability pipeline: instrument the application, collect and enrich the signals with an agent, store them in signal-specific backends, then query, visualize and alert on them.">
  <defs>
    <marker id="obs-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="430" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Every observability stack, regardless of vendor</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M212 108 L 244 108" marker-end="url(#obs-a3)"/>
    <path d="M410 108 L 442 108" marker-end="url(#obs-a3)"/>
    <path d="M608 108 L 640 108" marker-end="url(#obs-a3)"/>
    <path d="M746 152 L 746 186 L 430 186 L 430 206" marker-end="url(#obs-a3)" stroke-dasharray="6 5" opacity="0.75"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="66" width="188" height="84" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="246" y="66" width="164" height="84" rx="11" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="444" y="66" width="164" height="84" rx="11" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="642" y="66" width="194" height="84" rx="11" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="300" y="206" width="260" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="118" y="92" font-size="11.5" font-weight="700">1 · INSTRUMENT</text>
    <text x="118" y="112" font-size="9.5" opacity="0.9">your code emits the</text>
    <text x="118" y="127" font-size="9.5" opacity="0.9">signal (Lessons 2–8)</text>
    <text x="118" y="142" font-size="8.5" opacity="0.7">the only part you write</text>
    <text x="328" y="92" font-size="11.5" font-weight="700">2 · COLLECT</text>
    <text x="328" y="112" font-size="9.5" opacity="0.9">agent/collector reads,</text>
    <text x="328" y="127" font-size="9.5" opacity="0.9">enriches, batches, ships</text>
    <text x="328" y="142" font-size="8.5" opacity="0.7">OTel Collector, Fluent Bit</text>
    <text x="526" y="92" font-size="11.5" font-weight="700">3 · STORE</text>
    <text x="526" y="112" font-size="9.5" opacity="0.9">one backend per signal</text>
    <text x="526" y="127" font-size="9.5" opacity="0.9">shape (Phase 4, L5)</text>
    <text x="526" y="142" font-size="8.5" opacity="0.7">Prometheus · Loki · Tempo</text>
    <text x="739" y="92" font-size="11.5" font-weight="700">4 · USE</text>
    <text x="739" y="112" font-size="9.5" opacity="0.9">query, dashboard, alert</text>
    <text x="739" y="127" font-size="9.5" opacity="0.9">(Lessons 9–12)</text>
    <text x="739" y="142" font-size="8.5" opacity="0.7">Grafana · Alertmanager</text>
    <text x="430" y="224" font-size="10.5" font-weight="700">a page at 03:14 — or, better, a fix before anyone notices</text>
    <text x="430" y="240" font-size="9" opacity="0.8">the loop closes back into stage 1: what you couldn't answer becomes next week's instrumentation</text>
  </g>
</svg>
```

Two things worth internalizing now. First, **stage 1 is the only part you own** — and it is the part that decides whether the other three are useful. No dashboard recovers a field you never emitted. Second, notice stage 3 is *plural*: metrics go to a time-series database (Phase 4, Lesson 5 — you built one), logs to a search index, traces to a trace store. Three storage shapes because three data shapes, exactly the polyglot-persistence argument from Phase 4, Lesson 8.

### The tool landscape

You will meet these names constantly. Learn what *category* each occupies — categories outlive products.

| Layer | Open source | Hosted / commercial |
|---|---|---|
| **Instrumentation API** | **OpenTelemetry (OTel)** — the CNCF standard, one vendor-neutral API for all three signals | vendor agents (Datadog, New Relic) |
| **Collector / agent** | OTel Collector, Fluent Bit, Vector, Logstash | Datadog Agent, Splunk forwarder |
| **Metrics store** | **Prometheus**, VictoriaMetrics, Thanos, Mimir | Datadog, Grafana Cloud, CloudWatch |
| **Log store** | **Loki**, Elasticsearch/OpenSearch, ClickHouse | Splunk, Datadog Logs, Sumo Logic |
| **Trace store** | **Jaeger**, Tempo, Zipkin | Honeycomb, Lightstep, Datadog APM |
| **Dashboards** | **Grafana**, Kibana | Datadog, New Relic |
| **Alerting / on-call** | Alertmanager, Karma | PagerDuty, Opsgenie, Grafana OnCall |

The one name to actually care about is **OpenTelemetry**. Before it, instrumenting your code meant importing a *vendor's* SDK, and switching vendors meant rewriting every instrumented line — so teams got locked in by their own telemetry. OTel (formed in 2019 by merging OpenTracing and OpenCensus, now the CNCF's second-most-active project after Kubernetes) separates **how you instrument** from **where the data goes**: you write against one API, and swap backends with a config change. Lesson 7 uses it properly.

### The observability tax, stated honestly

Nobody tells beginners this part, so: **telemetry is not free, and it is not neutral.**

- **It costs money.** At real traffic, observability commonly runs **10–30% of infrastructure spend**, and there are well-known horror stories of log bills exceeding the compute bill they were watching. Lesson 4 does this math.
- **It costs latency.** Every log line is I/O; every span is allocation and network. Well-built telemetry is a small percentage of request time — badly-built telemetry (synchronous logging to a slow disk, unsampled tracing on a hot path) is an outage of its own.
- **It is a security surface.** Logs are where passwords, tokens, card numbers, and personal data leak, because a well-meaning `log.info(request_body)` doesn't know what's in the body. Under GDPR and similar regimes, a log line containing personal data is regulated data with a retention obligation.
- **It can lie.** A dashboard averaging latency across every endpoint will show a healthy 120 ms while your slowest endpoint times out for a tenth of users. Lesson 9 explains why percentiles exist and why averages are the most confidently wrong number in operations.

The goal is never "log everything." It's to emit **the smallest set of signals that answers the questions you'll actually be asked at 03:14** — and, when you get asked one you can't answer, to add exactly that signal and never be blind to it again.

## Think about it

1. A user reports "the site was slow around 2pm." Which pillar do you reach for first, and what specifically would each of the three tell you that the others cannot?
2. Your service logs one line per request, and traffic doubles every six months. What happens to your log bill in three years — and which pillar should absorb the questions you were using those logs to answer?
3. Why can't a metric answer "which users were affected?" — and what would go wrong if you tried to fix that by adding a `user_id` label to the metric? (Phase 4, Lesson 5 named this failure.)
4. Your system emits perfect logs, metrics, and traces, but nothing carries a shared request ID. Which questions become impossible, and which are still fine?
5. "We have 200 dashboards, so we're observable." Argue against this using the known-unknowns distinction.

## Key takeaways

- A running program is a **black box**: every internal fact is destroyed microseconds after it exists. You know only what the program **deliberately emitted** — that emitted data is **telemetry**, and writing it is a feature you build, not an afterthought.
- **Monitoring** is an activity (watch predefined numbers, alert on thresholds) that answers **"is it broken?"** for **known unknowns**. **Observability** is a property (can you infer internal state from external outputs — Kálmán's control-theory definition) that answers **"why is it broken?"** for **unknown unknowns**, ideally without deploying new code. You need both.
- The **three pillars** are three points on one detail-vs-cost trade-off: **metrics** (cheap aggregate numbers, kept for a year, can't identify an individual), **logs** (maximum detail per event, cost scales with traffic), **traces** (causality and timing for one request across services, usually sampled).
- The investigation funnel: **a metric alerts you → a trace localizes the bad hop → a log explains it.** What makes the handoff possible is a **shared trace/correlation ID** stamped on everything (the W3C `traceparent` standard) — without it you have three haystacks instead of one story.
- Every stack is the same four stages — **instrument → collect → store → query/alert** — and stage 1 is the only one you own; no backend can recover a field you never emitted. **OpenTelemetry** is the vendor-neutral standard for stage 1, which is why it's the one tool name worth memorizing.
- Telemetry has a real **tax**: money (often 10–30% of infra spend), latency, a PII/secret-leak surface, and the ability to mislead (averages hide the tail). Aim for the smallest signal set that answers the questions you're actually asked under pressure.

Next: [Logs: From `print()` to Structured Events](../02-structured-logging/) — the first pillar, built from scratch: why a human-readable log line is a machine-hostile one, and how to turn `print("user logged in")` into an event you can query a billion of.
