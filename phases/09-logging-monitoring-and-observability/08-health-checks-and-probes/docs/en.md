# Health Checks, Readiness & Graceful Shutdown

> Every signal you've built so far in this phase was for a human to read. A health check is different: nobody reads it. A load balancer and an orchestrator poll it, see a status code, and *act* — routing traffic to you, or killing your process — with no human in the loop. This lesson is about getting those semantics exactly right, because the classic way to turn a 30-second database blip into a two-hour outage is a health check that told the automation the wrong thing.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Metrics: Counters, Gauges & Histograms from Scratch](../05-metrics-from-scratch/), [HTTP in Depth](../../01-networking-and-protocols/08-http-in-depth/)
**Time:** ~65 minutes

## The Problem

Four incidents. Every one of them is a real, repeatedly-reproduced production failure, and every one is caused by a health check that was technically working.

**1. The pod that got traffic before it could serve.** A new container starts, binds port 8080, and 200 ms later the orchestrator's check succeeds — the socket is up, so the pod joins the load balancer. But it hasn't connected to Postgres, hasn't read its config, and hasn't imported half its modules. The first 3,000 requests routed to it time out. The deploy "succeeded"; your error rate sat at 4% for ninety seconds.

**2. The corpse that kept accepting connections.** A thread-pool deadlock leaves your service unable to complete a single request — but the listening socket is still open, and the kernel still completes the TCP (Transmission Control Protocol) handshake for anyone who connects. Your load balancer uses a **TCP-level** check: connect, succeed, disconnect. It passes. Forever. A fifth of your traffic goes to a process that will never answer.

**3. The blip that restarted the fleet.** Your database has a 30-second failover. All 40 instances run a health check that queries the database, so all 40 report unhealthy at the same instant — and the orchestrator does what you told it to: it kills and restarts all 40. The blip ends, and now you have zero warm instances, forty cold starts hitting a just-recovered database, empty caches, cold pools. This is Phase 5's [thundering herd](../../05-caching/06-cache-stampede/) with your own orchestrator as the stampede. A recoverable 30-second event became a full outage, and *the health check caused it.*

**4. The deploy that killed 4,000 requests.** A rollout sends `SIGTERM` to each old pod. Your process installs no handler, so the default action applies and it dies instantly. Every in-flight request — including the one that just charged a card but hasn't written the order row — is severed. The client sees a connection reset, not a 500, so your own error metrics never record it. Multiply by 40 pods per deploy, a dozen deploys a day.

Notice what these have in common. Nothing was *monitored* wrong. The dashboards were fine. What failed is the small, boring contract between your process and the machines that manage it.

## The Concept

### A health check is an API for machines

Everything else in this phase produces evidence for a person: a log line you grep, a graph you squint at, a trace you click through. A health check produces a **decision for a program**. The consumer is a load balancer (LB) deciding where to send the next request, or an orchestrator deciding whether to kill your container. Its entire vocabulary is:

- **2xx** — I am fine. Act accordingly.
- **anything else, or no answer within the timeout** — I am not. Act accordingly.

The status code *is* the contract — RFC 9110 §15.6.4 defines **503 Service Unavailable** as "the server is currently unable to handle the request due to a temporary overload or scheduled maintenance", and *temporary* is the load-bearing word. Any JSON body is a courtesy for the human who curls it mid-incident; no automation reads it. Which means: **an incorrect health check is more dangerous than none**, because it converts a small problem into a large automated action. Incident 3 is the whole argument.

### The three probes

Kubernetes gave the industry the vocabulary, but the three ideas exist wherever a machine supervises a process. What distinguishes them is not what they check — it's **what happens when they fail**.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 416" width="100%" style="max-width:840px" role="img" aria-label="The three probes compared: liveness asks whether the process is broken and its failure kills and restarts the container, readiness asks whether the instance should receive traffic and its failure only removes it from the load balancer, startup asks whether booting has finished and suspends the other two probes until it passes.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three probes — the difference is the CONSEQUENCE of failing</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="46" width="268" height="302" rx="14" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="306" y="46" width="268" height="302" rx="14" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="588" y="46" width="268" height="302" rx="14" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <rect x="40" y="278" width="236" height="54" rx="9" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="322" y="278" width="236" height="54" rx="9" fill="#3553ff" fill-opacity="0.20" stroke="#3553ff"/>
    <rect x="604" y="278" width="236" height="54" rx="9" fill="#7c5cff" fill-opacity="0.20" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke-width="1.3">
    <line x1="44" y1="108" x2="272" y2="108" stroke="#e0930f" stroke-opacity="0.5"/>
    <line x1="326" y1="108" x2="554" y2="108" stroke="#3553ff" stroke-opacity="0.5"/>
    <line x1="608" y1="108" x2="836" y2="108" stroke="#7c5cff" stroke-opacity="0.5"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="158" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#e0930f">LIVENESS</text>
    <text x="158" y="95" font-size="10" text-anchor="middle" opacity="0.85">GET /healthz</text>
    <text x="40" y="130" font-size="9" opacity="0.6">ASKS</text>
    <text x="40" y="146" font-size="10.5">Is this process broken</text>
    <text x="40" y="161" font-size="10.5">beyond recovery?</text>
    <text x="40" y="186" font-size="9" opacity="0.6">READ BY</text>
    <text x="40" y="202" font-size="10">the node agent (kubelet)</text>
    <text x="40" y="227" font-size="9" opacity="0.6">MAY CHECK</text>
    <text x="40" y="243" font-size="10">event loop ticks, internal</text>
    <text x="40" y="258" font-size="10">invariants. NEVER a dependency.</text>
    <text x="158" y="300" font-size="11.5" font-weight="700" text-anchor="middle">KILL + RESTART</text>
    <text x="158" y="315" font-size="9" text-anchor="middle" opacity="0.9">irreversible — and it fires on</text>
    <text x="158" y="327" font-size="9" text-anchor="middle" opacity="0.9">every replica at the same time</text>
    <text x="440" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#3553ff">READINESS</text>
    <text x="440" y="95" font-size="10" text-anchor="middle" opacity="0.85">GET /readyz</text>
    <text x="322" y="130" font-size="9" opacity="0.6">ASKS</text>
    <text x="322" y="146" font-size="10.5">Should I receive traffic</text>
    <text x="322" y="161" font-size="10.5">right now?</text>
    <text x="322" y="186" font-size="9" opacity="0.6">READ BY</text>
    <text x="322" y="202" font-size="10">kubelet + the load balancer</text>
    <text x="322" y="227" font-size="9" opacity="0.6">MAY CHECK</text>
    <text x="322" y="243" font-size="10">HARD dependencies — with a</text>
    <text x="322" y="258" font-size="10">timeout and a cached result</text>
    <text x="440" y="300" font-size="11.5" font-weight="700" text-anchor="middle">REMOVE FROM ROTATION</text>
    <text x="440" y="315" font-size="9" text-anchor="middle" opacity="0.9">reversible — traffic returns the</text>
    <text x="440" y="327" font-size="9" text-anchor="middle" opacity="0.9">moment it passes again</text>
    <text x="722" y="76" font-size="14" font-weight="700" text-anchor="middle" fill="#7c5cff">STARTUP</text>
    <text x="722" y="95" font-size="10" text-anchor="middle" opacity="0.85">GET /startupz</text>
    <text x="604" y="130" font-size="9" opacity="0.6">ASKS</text>
    <text x="604" y="146" font-size="10.5">Has it finished booting</text>
    <text x="604" y="161" font-size="10.5">yet?</text>
    <text x="604" y="186" font-size="9" opacity="0.6">READ BY</text>
    <text x="604" y="202" font-size="10">the node agent (kubelet)</text>
    <text x="604" y="227" font-size="9" opacity="0.6">MAY CHECK</text>
    <text x="604" y="243" font-size="10">config loaded, pools warm,</text>
    <text x="604" y="258" font-size="10">caches primed. Local only.</text>
    <text x="722" y="300" font-size="11.5" font-weight="700" text-anchor="middle">SUSPEND THE OTHER TWO</text>
    <text x="722" y="315" font-size="9" text-anchor="middle" opacity="0.9">a slow boot can't be mistaken</text>
    <text x="722" y="327" font-size="9" text-anchor="middle" opacity="0.9">for a hung process</text>
    <text x="440" y="376" font-size="11.5" text-anchor="middle" font-weight="700">All three return the same 503. What that 503 causes is completely different.</text>
    <text x="440" y="398" font-size="10.5" text-anchor="middle" opacity="0.85">Put a check in the wrong probe and your automation does the damage for you.</text>
  </g>
</svg>
```

As a table you can keep:

| Probe | Question | Failure action | May check | Rarely fails? |
|---|---|---|---|---|
| **Liveness** | Is the process irrecoverably broken? | **Kill the container and restart it** | Only local, in-process state | Yes — should almost never fire |
| **Readiness** | Should this instance get traffic *now*? | **Remove from the load balancer** (reversible) | Hard dependencies, with timeouts + caching | No — this is the one that moves |
| **Startup** | Has initialization finished? | **Hold off** liveness and readiness | Local warmup progress | Fires once per start, by design |

The single most important rule in this lesson: **liveness must not check dependencies.** A liveness probe answers a question about *this process only* — is the event loop scheduling, is the worker thread ticking, are internal invariants intact. The instant it asks "can I reach the database?", you have wired a shared, external failure to a fleet-wide kill switch. That is incident 3.

Readiness is the opposite. It is *supposed* to be sensitive to the outside world, because its consequence is cheap and reversible: you stop getting traffic, and you start again when things recover. Nothing is destroyed.

Startup exists because liveness has one number that is impossible to pick well: how long to wait before the first check. Tune it for steady state (fail in 30 s) and a service needing 90 s to load a model crash-loops forever. Tune it for the slow boot (fail in 300 s) and a hung process runs unnoticed for five minutes. The startup probe splits that in two — a generous boot budget, then a tight steady-state one.

### Shallow, deep, and the middle path

A **shallow** check touches nothing but the process: return 200, maybe confirm a heartbeat. Fast, and it never lies about other people's problems — but it can't tell you the instance is useless because its connection pool is exhausted. A **deep** check exercises the real path: query the database, call the downstream. Honest about whether you can serve — and it drags every dependency's failure into your health signal, which is how one slow database takes out five services. Readiness lives in the middle, and three techniques get it there:

- **Timeouts, always.** A health check with no timeout is worse than no health check: when the dependency hangs, your handler hangs, the probe times out, and — if you put it in liveness — you get restarted for someone else's latency. Give each check a budget smaller than the probe's own `timeoutSeconds`.
- **Cache the result with a TTL (time to live).** Do the arithmetic. 40 replicas × one readiness probe per second = **40 QPS (queries per second) of pure health traffic** against your database, forever, before a single user request. That's the same load pattern as a real feature, generated by your monitoring of the feature. Cache the check result for 5–10 s and it drops to 4–8 QPS. The cost is that the TTL adds to your detection time — write it down as part of the budget.
- **Degraded mode.** If a non-critical dependency is down and you can still serve 90% of traffic, removing yourself from rotation makes things *worse* — you've cut capacity for a partial problem. Return **200** with a body saying `degraded`.

### Hard and soft dependencies

That last point only works if you have classified your dependencies in advance, on purpose:

- **Hard** — you cannot serve a meaningful response without it. The primary database for a checkout service. Its failure belongs in readiness.
- **Soft** — you can degrade: skip the feature, serve a stale value from cache, return a partial response. A recommendation service, an A/B config service, a metrics sink. Its failure belongs in a log line and a metric, **not** in your readiness status code.

Write the list down. For most services it is one or two hard dependencies and a long tail of soft ones, and the tail is where teams accidentally couple their availability to something that didn't matter.

### The anti-pattern, drawn

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="The same database blip under two probe designs: on the left a liveness probe that queries the database makes every replica fail liveness and be restarted at once, turning a 30 second blip into a full outage; on the right liveness stays local so only readiness fails, the processes survive with warm caches and traffic returns one probe period after the database recovers.">
  <defs>
    <marker id="l08-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One 30-second database blip, two probe designs</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="46" width="396" height="326" rx="14" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
    <rect x="460" y="46" width="396" height="326" rx="14" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="142" y="106" width="160" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="578" y="106" width="160" height="42" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-opacity="0.6"/>
    <rect x="44" y="196" width="72" height="48" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="134" y="196" width="72" height="48" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="224" y="196" width="72" height="48" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="314" y="196" width="72" height="48" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="480" y="196" width="72" height="48" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="570" y="196" width="72" height="48" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="660" y="196" width="72" height="48" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="750" y="196" width="72" height="48" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.65">
    <path d="M222 148 C 176 168, 116 172, 80 192" marker-end="url(#l08-a2)"/>
    <path d="M222 148 C 206 168, 186 174, 170 192" marker-end="url(#l08-a2)"/>
    <path d="M222 148 C 238 168, 258 174, 260 192" marker-end="url(#l08-a2)"/>
    <path d="M222 148 C 268 168, 328 172, 350 192" marker-end="url(#l08-a2)"/>
    <path d="M658 148 C 612 168, 552 172, 516 192" marker-end="url(#l08-a2)"/>
    <path d="M658 148 C 642 168, 622 174, 606 192" marker-end="url(#l08-a2)"/>
    <path d="M658 148 C 674 168, 694 174, 696 192" marker-end="url(#l08-a2)"/>
    <path d="M658 148 C 704 168, 764 172, 786 192" marker-end="url(#l08-a2)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="222" y="74" font-size="12.5" font-weight="700" fill="#e0930f">ANTI-PATTERN</text>
    <text x="222" y="92" font-size="9.5" opacity="0.85">liveness probe queries the database</text>
    <text x="658" y="74" font-size="12.5" font-weight="700" fill="#0fa07f">CORRECT</text>
    <text x="658" y="92" font-size="9.5" opacity="0.85">liveness is local; readiness owns deps</text>
    <text x="222" y="124" font-size="10.5" font-weight="700">database</text>
    <text x="222" y="140" font-size="9" opacity="0.85">30s failover blip</text>
    <text x="658" y="124" font-size="10.5" font-weight="700">database</text>
    <text x="658" y="140" font-size="9" opacity="0.85">30s failover blip</text>
    <text x="80" y="216" font-size="9.5" opacity="0.9">pod 1</text>
    <text x="170" y="216" font-size="9.5" opacity="0.9">pod 2</text>
    <text x="260" y="216" font-size="9.5" opacity="0.9">pod 3</text>
    <text x="350" y="216" font-size="9.5" opacity="0.9">pod 4</text>
    <text x="80" y="233" font-size="9">live 503</text>
    <text x="170" y="233" font-size="9">live 503</text>
    <text x="260" y="233" font-size="9">live 503</text>
    <text x="350" y="233" font-size="9">live 503</text>
    <text x="516" y="216" font-size="9.5" opacity="0.9">pod 1</text>
    <text x="606" y="216" font-size="9.5" opacity="0.9">pod 2</text>
    <text x="696" y="216" font-size="9.5" opacity="0.9">pod 3</text>
    <text x="786" y="216" font-size="9.5" opacity="0.9">pod 4</text>
    <text x="516" y="233" font-size="9">ready 503</text>
    <text x="606" y="233" font-size="9">ready 503</text>
    <text x="696" y="233" font-size="9">ready 503</text>
    <text x="786" y="233" font-size="9">ready 503</text>
    <text x="222" y="268" font-size="10.5" font-weight="700" fill="#e0930f">all 4 — all 40 in production — RESTART at once</text>
    <text x="222" y="290" font-size="10" opacity="0.9">every replica cold-starts simultaneously:</text>
    <text x="222" y="305" font-size="10" opacity="0.9">empty caches, cold pools, zero capacity</text>
    <text x="222" y="332" font-size="11.5" font-weight="700">30s blip  →  FULL OUTAGE</text>
    <text x="222" y="352" font-size="9.5" opacity="0.9">plus a thundering herd on the recovering DB</text>
    <text x="658" y="268" font-size="10.5" font-weight="700" fill="#0fa07f">all 4 pulled from the LB — liveness stays 200</text>
    <text x="658" y="290" font-size="10" opacity="0.9">caches, pools and warmed-up state all survive</text>
    <text x="658" y="305" font-size="10" opacity="0.9">the pool reconnects on its own, in the background</text>
    <text x="658" y="332" font-size="11.5" font-weight="700">30s blip  →  30s of 503s</text>
    <text x="658" y="352" font-size="9.5" opacity="0.9">traffic returns one probe period after recovery</text>
  </g>
</svg>
```

The left panel is not a straw man — it is the default thing people write, because "a health check should check that the service works, and the service needs the database" is a completely reasonable sentence. It's wrong only because of what the orchestrator *does* with the answer.

### Tuning: the detection-time arithmetic

Four numbers control every probe, and they are worth being able to compute in your head.

- `initialDelaySeconds` — wait this long after the container starts before the first check. (Largely obsolete once you have a startup probe.)
- `periodSeconds` — how often to check.
- `timeoutSeconds` — how long to wait for an answer before counting it a failure.
- `failureThreshold` — how many consecutive failures before acting.

Detection time is then:

```text
detection ≈ periodSeconds × failureThreshold + timeoutSeconds
worst case = periodSeconds × (failureThreshold + 1) + timeoutSeconds
   (the failure can start just after a probe that succeeded)

tolerated blip = periodSeconds × (failureThreshold − 1)
   (any transient shorter than this is absorbed and never acts)
```

Those last two lines are the entire trade-off: **fast detection and flap tolerance are the same dial pulled in opposite directions.** A liveness probe at `period=2s, failureThreshold=3` spots a deadlocked process in about 7 seconds — and restarts your pod over any 5-second garbage-collection pause. A liveness probe at `period=10s, failureThreshold=3` takes 31 seconds but shrugs off a 20-second hiccup.

The default posture: **liveness slow and forgiving** (it's a destructive action you want to be very sure about), **readiness fast and twitchy** (it's cheap and reversible, so react quickly). Concretely: liveness ~10 s / 3, readiness ~3 s / 2.

### Graceful shutdown, second by second

Incident 4 is fixed by a sequence, and the step everyone omits is step 2.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="A graceful shutdown timeline from SIGTERM to exit: readiness fails immediately, the process keeps serving through a five-second drain wait while the load balancer notices, then stops accepting new connections, finishes in-flight requests, flushes telemetry and exits well before the SIGKILL deadline at thirty seconds.">
  <defs>
    <marker id="l08-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The drain: SIGTERM to exit, with the wait nobody remembers</text>
  <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 4" opacity="0.55">
    <path d="M170 90 L 170 156"/>
    <path d="M283 128 L 283 156"/>
    <path d="M442 90 L 442 156"/>
    <path d="M850 128 L 850 156"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="170" y="158" width="113" height="36" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="283" y="158" width="159" height="36" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="442" y="158" width="68" height="36" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="510" y="158" width="340" height="36" rx="8" fill="none" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="6 5"/>
    <rect x="170" y="240" width="91" height="30" rx="7" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    <rect x="261" y="240" width="589" height="30" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="170" y="298" width="113" height="8" rx="4" fill="#7c5cff" fill-opacity="0.35" stroke="#7c5cff" stroke-width="1.2"/>
    <rect x="170" y="310" width="204" height="8" rx="4" fill="#7c5cff" fill-opacity="0.35" stroke="#7c5cff" stroke-width="1.2"/>
    <rect x="170" y="322" width="272" height="8" rx="4" fill="#7c5cff" fill-opacity="0.35" stroke="#7c5cff" stroke-width="1.2"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M160 200 L 866 200" marker-end="url(#l08-a3)"/>
    <path d="M170 196 L 170 208"/>
    <path d="M283 196 L 283 208"/>
    <path d="M397 196 L 397 208"/>
    <path d="M623 196 L 623 208"/>
    <path d="M850 196 L 850 208"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="174" y="54" font-size="10.5" font-weight="700">1 · SIGTERM arrives</text>
    <text x="174" y="69" font-size="9.5" opacity="0.9">readiness → 503 NOW</text>
    <text x="174" y="83" font-size="9.5" opacity="0.9">but keep serving traffic</text>
    <text x="446" y="54" font-size="10.5" font-weight="700">3 · in-flight drained</text>
    <text x="446" y="69" font-size="9.5" opacity="0.9">flush logs, spans, metrics</text>
    <text x="446" y="83" font-size="9.5" opacity="0.9">close pools, then exit 0</text>
    <text x="287" y="106" font-size="10.5" font-weight="700">2 · stop accepting</text>
    <text x="287" y="121" font-size="9.5" opacity="0.9">close the listener; Connection: close</text>
    <text x="846" y="106" font-size="10.5" font-weight="700" text-anchor="end">4 · SIGKILL — hard deadline</text>
    <text x="846" y="121" font-size="9.5" opacity="0.9" text-anchor="end">terminationGracePeriodSeconds: 30</text>
    <text x="226" y="174" font-size="10" font-weight="700" text-anchor="middle">DRAIN WAIT</text>
    <text x="226" y="187" font-size="8.5" text-anchor="middle" opacity="0.9">still serving</text>
    <text x="362" y="174" font-size="10" font-weight="700" text-anchor="middle">FINISH IN-FLIGHT</text>
    <text x="362" y="187" font-size="8.5" text-anchor="middle" opacity="0.9">no new work taken</text>
    <text x="476" y="174" font-size="9.5" font-weight="700" text-anchor="middle">FLUSH</text>
    <text x="476" y="187" font-size="8.5" text-anchor="middle" opacity="0.9">EXIT 0</text>
    <text x="680" y="180" font-size="9.5" text-anchor="middle" opacity="0.8">unused grace — headroom, not a target</text>
    <text x="170" y="222" font-size="9" text-anchor="middle" opacity="0.8">T+0</text>
    <text x="283" y="222" font-size="9" text-anchor="middle" opacity="0.8">+5s</text>
    <text x="397" y="222" font-size="9" text-anchor="middle" opacity="0.8">+10s</text>
    <text x="623" y="222" font-size="9" text-anchor="middle" opacity="0.8">+20s</text>
    <text x="850" y="222" font-size="9" text-anchor="middle" opacity="0.8">+30s</text>
    <text x="24" y="252" font-size="10" font-weight="700">LOAD BALANCER</text>
    <text x="24" y="266" font-size="8.5" opacity="0.7">what it is doing</text>
    <text x="215" y="259" font-size="8.5" text-anchor="middle">still routing</text>
    <text x="555" y="259" font-size="9" text-anchor="middle">has noticed the 503s — no new connections sent here</text>
    <text x="24" y="310" font-size="10" font-weight="700">IN-FLIGHT WORK</text>
    <text x="24" y="324" font-size="8.5" opacity="0.7">already accepted</text>
    <text x="470" y="320" font-size="9" opacity="0.9">each one runs to completion — nothing is severed</text>
    <text x="440" y="362" font-size="10.5" text-anchor="middle" opacity="0.95">The gap between 1 and 2 is the DRAIN WAIT. Skip it — close the socket the instant SIGTERM</text>
    <text x="440" y="380" font-size="10.5" text-anchor="middle" opacity="0.95">arrives — and you kill every request the load balancer had already routed to you.</text>
  </g>
</svg>
```

Walk it once more in words, because the ordering is the whole thing:

1. **`SIGTERM` arrives** — the POSIX signal (IEEE Std 1003.1) meaning "please stop." Its default action is to terminate immediately, so with no handler installed everything below is skipped and you get incident 4.
2. **Fail readiness, keep serving.** Flip a flag; `/readyz` returns 503. You have not stopped doing work.
3. **Wait.** The step that gets left out. The load balancer — or `kube-proxy` on every node — learns you're unready by *polling*, and the endpoint change then has to propagate. That takes seconds. Close the socket now and every request already in flight, or just routed to you, dies. Waiting a few seconds while still serving is exactly what a `preStop: sleep 5` hook buys.
4. **Stop accepting; finish in-flight work with a deadline.** Close the listening socket; existing connections finish their current request. And handle keep-alive: Phase 1's [connection pooling](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/) means a client holding a pooled socket to you sends its *next* request down it no matter what the load balancer decided — so send `Connection: close` during the drain (RFC 9112 §9.6) and it will reconnect to a healthy instance.
5. **Close pools, flush telemetry, exit 0.** Your logger (Lesson 2), shipper buffer (Lesson 4) and span exporter (Lesson 7) all batch in memory. Exiting without flushing discards exactly the telemetry describing your shutdown — the data you want when a shutdown goes wrong.
6. **`SIGKILL` at the deadline.** After `terminationGracePeriodSeconds` the orchestrator sends the uncatchable signal. Drain wait plus longest request must fit inside it, with room to spare.

### Designing the endpoint itself

Small rules, each learned the hard way:

- **The status code is the contract.** 200 or 503. Never 200 with `{"healthy": false}` — no automation will parse it. Add `Cache-Control: no-store`; a cached health response is a lie with a timestamp.
- **A small JSON body is for humans** — per-dependency status, so whoever curls `/readyz` at 03:00 sees *which* thing is down. Never internal version numbers, connection strings, or anything an unauthenticated caller shouldn't see; these endpoints get exposed further than you think.
- **Never authenticate the liveness probe.** The kubelet has no credentials; a token expiry would become a fleet-wide restart.
- **Keep probes off the normal request path** — a separate route, excluded from your RED metrics (Rate, Errors, Duration — Lesson 11). Otherwise 40 replicas × 1 probe/s of trivial 200s dominates your request rate and flattens your latency percentiles into nonsense.

The request-time cousin of readiness is the **circuit breaker**: instead of asking "should I get traffic?", it asks "should I keep calling this failing dependency, or fail fast and shed load?" Same instinct — stop sending work where it can't succeed — applied per-call instead of per-instance. Phase 11 builds one.

## Build It

`code/health_service.py` is a real HTTP service — `ThreadingHTTPServer` on an ephemeral port — with all three probes implemented correctly, plus a deliberately wrong one so you can watch the anti-pattern fire. Standard library only.

First, the check abstraction. Each dependency check carries the four things that make a readiness check safe: a name, a **hard/soft** classification, a **timeout**, and a **TTL-cached result**:

```python
@dataclass
class DependencyCheck:
    name: str
    probe: Callable[[], None]
    hard: bool = True
    timeout_s: float = 0.25
    ttl_s: float = 0.5

    def status(self) -> Tuple[bool, str]:
        with self._lock:                       # concurrent probes share one check
            now = time.monotonic()
            if now < self._expires:
                self.cache_hits += 1
                return self._ok, self._detail  # served from cache: no DB traffic
            self.probes += 1
            ok, detail = self._run_with_timeout()
            self._ok, self._detail, self._expires = ok, detail, now + self.ttl_s
            return ok, detail
```

The lock does double duty: it protects the cache, and it collapses concurrent probes into a single in-flight check — the single-flight idea from Phase 5's [cache stampede](../../05-caching/06-cache-stampede/) lesson, applied to health checks. The timeout runs the probe on its own thread and abandons it at the deadline, so a hung dependency can never hang the endpoint:

```python
    def _run_with_timeout(self) -> Tuple[bool, str]:
        out: Dict[str, Any] = {}
        def run() -> None:
            try:
                self.probe()
                out["ok"], out["detail"] = True, "ok"
            except Exception as exc:
                out["ok"], out["detail"] = False, "down: %s" % exc
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(self.timeout_s)
        if worker.is_alive():
            return False, "timeout after %dms" % int(self.timeout_s * 1000)
        return bool(out.get("ok")), str(out.get("detail", "unknown"))
```

Liveness is deliberately tiny: it looks at one thing — has the worker loop ticked recently — and touches nothing external. The `check_db` branch is the anti-pattern, wired to a *second* endpoint so both behaviours are observable side by side:

```python
    def alive(self) -> Tuple[bool, str]:
        """Liveness: shallow and local. It never touches a dependency."""
        age = time.monotonic() - self.last_tick
        if age > LIVENESS_MAX_STALL:
            return False, "no worker tick for >%.1fs" % LIVENESS_MAX_STALL
        return True, "worker loop responsive"

    def _liveness(self, check_db: bool) -> None:
        ok, detail = STATE.alive()
        if ok and check_db:                                # THE ANTI-PATTERN
            ok, detail = CHECKS[0].status()
        self._send(200 if ok else 503,
                   {"status": "alive" if ok else "dead", "detail": detail})
```

Readiness is where the classification pays off: a failing **hard** check gives 503 and removal from rotation, a failing **soft** check gives 200 with `degraded`:

```python
    def _readiness(self) -> None:
        if not STATE.warm:
            return self._send(503, {"status": "starting"})
        if STATE.draining:
            return self._send(503, {"status": "draining", "detail": "SIGTERM received"})
        checks, hard_down, soft_down = {}, False, False
        for chk in CHECKS:
            ok, checks[chk.name] = chk.status()
            hard_down = hard_down or (not ok and chk.hard)
            soft_down = soft_down or (not ok and not chk.hard)
        status = "unready" if hard_down else ("degraded" if soft_down else "ready")
        self._send(503 if hard_down else 200, {"status": status, "checks": checks})
```

The `SIGTERM` handler only flips a flag — the drain itself is a sequence, not an event:

```python
    def on_sigterm(signum: int, frame: Any) -> None:
        STATE.draining = True                  # readiness fails; we keep serving
    signal.signal(signal.SIGTERM, on_sigterm)
    signal.raise_signal(signal.SIGTERM)
```

The rest — the endpoints, the fake toggleable dependencies, the drain loop that waits for `inflight` to reach zero, and the five scenarios — is in [`code/health_service.py`](code/health_service.py). Run it:

```bash
python3 health_service.py
```

```console
$ python3 health_service.py
== SCENARIO A - STARTUP ==
  GET /startupz       -> 503  {"status": "warming", "detail": "loading config, warming pool"}
  GET /readyz         -> 503  {"status": "starting"}
  ...booting (0.6s of config load + pool warm)
  GET /startupz       -> 200  {"status": "started"}
  GET /readyz         -> 200  {"status": "ready", "checks": {"database": "ok", "recommendations": "ok"}}
  startup probe gates the other two: no traffic before boot finished

== SCENARIO B - HARD DEPENDENCY DOWN ==
  GET /readyz         -> 503  {"status": "unready", "checks": {"database": "down: connection refused", "recommendations": "ok"}}
  GET /healthz        -> 200  {"status": "alive", "detail": "worker loop responsive"}
  -> removed from the load balancer, NOT restarted. Reversible.
  GET /readyz         -> 503  {"status": "unready", "checks": {"database": "timeout after 250ms", "recommendations": "ok"}}
  -> a 500ms database beats a 250ms check timeout: same verdict, no hang
  GET /readyz         -> 200  {"status": "ready", "checks": {"database": "ok", "recommendations": "ok"}}
  -> dependency recovered, instance back in rotation with no restart

== SCENARIO C - SOFT DEPENDENCY DOWN ==
  GET /readyz         -> 200  {"status": "degraded", "checks": {"database": "ok", "recommendations": "down: connection refused"}}
  -> 200 with status=degraded: serve without recommendations, stay in rotation

== DEPENDENCY CHECK CACHING ==
  database         real probes=1  cache hits=4  (ttl=0.5s)
  recommendations  real probes=1  cache hits=4  (ttl=0.5s)
  40 replicas x 1 probe/s = 40 QPS uncached; a 10s TTL makes it 4 QPS

== SCENARIO D - THE ANTI-PATTERNS ==
  GET /healthz        -> 200  {"status": "alive", "detail": "worker loop responsive"}
  GET /healthz-naive  -> 503  {"status": "dead", "detail": "down: connection refused"}
  naive liveness checks the DB, so with periodSeconds=5 failureThreshold=3
  every one of 40 replicas is SIGKILLed 15s into a 30s blip -- a recoverable
  blip becomes a full outage plus a cold-start thundering herd
  tcpSocket probe   -> PASS (the socket still accepts; the app is deadlocked)
  GET /healthz        -> 503  {"status": "dead", "detail": "no worker tick for >1.0s"}
  -> only an httpGet probe that exercises the app catches this. Restart is right.

== PROBE TUNING ARITHMETIC ==
  detection = periodSeconds x failureThreshold + timeoutSeconds
  period  threshold  timeout   detect   worst   tolerates blip up to
     10s         3        1s      31s      41s                   20s
      5s         3        1s      16s      21s                   10s
      5s         2        1s      11s      16s                    5s
      2s         3        1s       7s       9s                    4s
  faster detection costs flap tolerance: 2s/3 catches a corpse in 7s but
  restarts on any 5-second hiccup. Liveness slow, readiness fast.

== SCENARIO E - GRACEFUL SHUTDOWN ==
  (a /work request needing 900ms is already in flight)
  T+ 0.0s  SIGTERM received -> readiness fails NOW, but we keep serving
  GET /readyz         -> 503  {"status": "draining", "detail": "SIGTERM received"}
  GET /healthz        -> 200  {"status": "alive", "detail": "worker loop responsive"}
  T+ 0.0s  drain wait 0.5s -- the LB has not noticed yet (k8s: preStop sleep 5)
  T+ 0.2s  a request the LB routed before it noticed -> 200, still served
  T+ 0.5s  stop accepting new work (a real server closes its listening socket here)
  T+ 0.5s  new request -> 503 {"error": "shutting down"}  (Connection: close ends keep-alive)
  T+ 0.8s  in-flight drained -> the 900ms request returned 200 {"result": "ok", "took_ms": 900}
  T+ 0.9s  telemetry flushed: 2 buffered records (Lessons 2, 4 and 7)
  T+ 1.0s  worker stopped, connection pools closed
           listening socket closed -> exit 0
           a new connection is now refused: nothing died mid-request
  terminationGracePeriodSeconds=30 -> SIGKILL never fired
```

Read what each scenario proves. **A**: `/readyz` returns 503 while `/startupz` does — the startup probe gates the other two, so no traffic arrives during the 600 ms boot (incident 1, fixed). **B** is the load-bearing result: with the database down, readiness is **503** and liveness is **200** on the *same process at the same instant*. That is the pod being pulled from rotation and *not* restarted; when the database returns, readiness goes back to 200 with no restart, no cold start, no lost cache. The middle line shows the timeout doing its job — a 500 ms database against a 250 ms check budget produces `timeout after 250ms` in bounded time instead of hanging the endpoint. **C**: the recommendation service is down and readiness is still **200**, body `degraded` — a soft dependency costs you a feature, not your capacity.

The caching numbers are the arithmetic made real: five readiness probes produced **one** real database call and **four** cache hits. Scale that up — 40 replicas probing once a second is 40 QPS of database load created purely by health checking; a 10-second TTL cuts it to 4. **D** is the anti-pattern side by side: `/healthz` says alive, `/healthz-naive` says dead, *identical process, same millisecond* — the only difference is that one asked the database. With `periodSeconds=5, failureThreshold=3` that 503 becomes a `SIGKILL` on every replica 15 seconds into a 30-second blip. The second half of **D** is incident 2: with the worker loop stalled, a `tcpSocket` probe still **passes** — the kernel completes the handshake for a deadlocked app — while the HTTP probe correctly returns 503. That's the one time a restart *is* the right answer.

**E** is the timeline you drew. Readiness flips to 503 at T+0 while liveness stays 200 (you are draining, not broken). During the drain wait, a request that the load balancer had already routed still gets a **200**. Only at T+0.5 do new requests get refused. The 900 ms request that was in flight when `SIGTERM` arrived returns `200 {"result": "ok", "took_ms": 900}` — it was never severed, which is the entire point. Then telemetry flushes, pools close, the socket closes, and the next connection is refused because the process is genuinely gone — at T+1.0 of a 30-second grace period.

## Use It

### Kubernetes: all three probes plus the drain

```yaml
spec:
  # SIGTERM -> SIGKILL budget. Must exceed preStop sleep + your longest request,
  # with headroom. 30 is the default; raise it if p99.9 latency is seconds.
  terminationGracePeriodSeconds: 45
  containers:
    - name: api
      lifecycle:
        preStop:
          exec:
            # The drain wait. Runs BEFORE SIGTERM is delivered, and the app keeps
            # serving throughout. 5s is enough for endpoint changes to propagate
            # to every kube-proxy. This is step 2 of the timeline.
            command: ["sh", "-c", "sleep 5"]
      startupProbe:
        httpGet: { path: /startupz, port: 8080 }
        periodSeconds: 5
        failureThreshold: 30      # 5 x 30 = 150s of boot allowed, then restart.
                                  # While this runs, the other two are suspended,
                                  # so no initialDelaySeconds is needed anywhere.
      livenessProbe:
        httpGet: { path: /healthz, port: 8080 }
        periodSeconds: 10         # slow: this action is destructive
        timeoutSeconds: 2
        failureThreshold: 3       # 10 x 3 + 2 = 32s before a kill; absorbs a 20s pause
      readinessProbe:
        httpGet: { path: /readyz, port: 8080 }
        periodSeconds: 3          # fast: this action is cheap and reversible
        timeoutSeconds: 1
        failureThreshold: 2       # 3 x 2 + 1 = 7s out of rotation
        successThreshold: 1       # back in rotation on the first success
```

Two footguns hide in that file. `terminationGracePeriodSeconds` covers the `preStop` hook **and** the drain — 5 s of sleep plus a 30 s request does not fit in 30 s. And a startup probe's `failureThreshold × periodSeconds` is a hard boot deadline: exceed it and you get a crash loop that looks like a broken image.

### `exec`, `tcpSocket` and `httpGet`

- **`httpGet`** — hits an endpoint in your app. Prefer it: it exercises the HTTP server, router and handler, which is what your users exercise.
- **`tcpSocket`** — connects to a port. Proves the kernel is listening, not that your app works; scenario D showed exactly that. Use it only for non-HTTP servers.
- **`exec`** — runs a command in the container. Correct for things with no HTTP surface (`pg_isready`, `redis-cli ping`), but it forks a process on every probe — at `periodSeconds: 1` on a dense node that is real CPU. (There is also **`grpc`**, which speaks the standard gRPC Health Checking Protocol.)

### AWS: the load balancer's half of the contract

An ALB (Application Load Balancer) or NLB (Network Load Balancer) target group has the same four numbers, and one extra that matters enormously:

```text
HealthCheckPath                       /readyz     # readiness, never liveness
HealthCheckProtocol                   HTTP
HealthCheckIntervalSeconds            10
HealthCheckTimeoutSeconds             5
HealthyThresholdCount                 2           # back in rotation after 20s
UnhealthyThresholdCount               2           # out of rotation after ~25s
Matcher                               200

deregistration_delay.timeout_seconds  30          # <- the LB-side drain wait
```

**Deregistration delay** (AWS calls it connection draining) is the load balancer's twin of your `preStop` sleep: on deregistration the ALB stops sending a target *new* requests but lets existing ones finish for this long. Your `terminationGracePeriodSeconds` must be at least as large, or the orchestrator kills a pod the load balancer still believes is draining. Note also that it should be *harder* to come back than to leave — that asymmetry is what stops an instance flapping in and out of rotation.

### Docker and Compose

```dockerfile
# Docker has ONE health check, not three. --start-period is the startup probe.
HEALTHCHECK --interval=10s --timeout=2s --start-period=30s --retries=3 \
  CMD python3 -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/readyz')" || exit 1
```

Docker marks the container `unhealthy` but does not restart it — the value is in orchestration. This repo's own [`docker-compose.yml`](../../../docker-compose.yml) uses exactly this to solve the "app started before the database was ready" race:

```yaml
  postgres:
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U dev -d backend"]
      interval: 3s
      timeout: 3s
      retries: 10
  app:
    depends_on:
      postgres:
        condition: service_healthy    # wait for healthy, not merely started
```

`condition: service_healthy` is the whole idea in one line: a dependency is not "up" when its process starts, it is up when it says it can serve.

### Health checks are not monitoring

They overlap, and conflating them produces bad alerts:

| | Health checks / probes | Monitoring |
|---|---|---|
| **Consumer** | load balancer, orchestrator | humans, alerting rules |
| **Question** | route to this instance? restart it? | is the *service* healthy? |
| **Scope** | one instance, right now | the fleet, over time |
| **Reaction** | seconds, automatic | minutes, a person |

Never page on "one pod failed readiness" — that's the system working. Page on *aggregate* readiness (`sum(up) < N`, Lesson 6) or on user-facing symptoms (Lesson 9's SLIs — Service Level Indicators). Prometheus's own `up` metric and synthetic checks answer the human question; probes answer the machine one.

### Rules of thumb

- **Liveness should almost never fail.** If it fires more than rarely, it's checking too much. Many mature teams ship liveness as a bare `return 200` and rely on the orchestrator's crash detection.
- **Liveness never checks a dependency.** No exceptions. Not "just a fast ping."
- **Readiness is the probe you actually tune** — fast period, low threshold, timeouts on every check, results cached with a TTL you have chosen deliberately.
- **Classify every dependency hard or soft, in writing**, before it's 03:00.
- **Always flush telemetry before exit.** The last thing your process does should be making sure it told you what it did.

## Think about it

1. Your service reads from Postgres and writes to a Kafka topic for analytics. Which of those belongs in readiness, which in neither, and what changes if the analytics writes are buffered in memory and lost on restart?
2. A readiness check with a 10-second cache TTL and `periodSeconds=3, failureThreshold=2` — what is the true worst-case time between a dependency failing and this instance leaving rotation? Which term dominates?
3. You set `terminationGracePeriodSeconds: 30`, a `preStop` sleep of 10 s, and your p99.9 request takes 25 s. Walk through what happens to the slowest request during a deploy, and give two different fixes.
4. Every instance caches its readiness result for 10 s. All 40 instances started at the same moment. What does the database see, and which earlier lesson's technique (and which one-line change) fixes it?
5. Your liveness probe is a bare `return 200`. What class of failure now goes undetected, and which signal from an earlier lesson would catch it instead?

## Key takeaways

- A health check is an **API for machines**: a load balancer or orchestrator reads the status code (200 vs 503, RFC 9110 §15.6.4) and acts without a human. A wrong health check is more dangerous than none, because it converts a small failure into a large automated action.
- The three probes differ by **consequence**, not content. **Liveness** → kill and restart, so it must be shallow, local, and **must never check a dependency**. **Readiness** → remove from the load balancer, reversible, so this is where dependency checks belong. **Startup** → suspends the other two so a slow boot isn't mistaken for a hung process.
- A liveness probe that queries a shared database converts a 30-second blip into a **fleet-wide simultaneous restart**: every replica cold-starts at once, with empty caches and cold pools, stampeding the dependency that just recovered.
- Readiness checks dependencies **safely**: a timeout on every check, a **TTL-cached result** (40 replicas × 1 probe/s = 40 QPS of pure health load; a 10 s TTL makes it 4), and a **hard/soft** classification so a soft failure returns 200 with `degraded` instead of shedding your own capacity.
- Detection time is `periodSeconds × failureThreshold + timeoutSeconds`, and a blip shorter than `periodSeconds × (failureThreshold − 1)` is absorbed. Tune **liveness slow and forgiving** (~10 s / 3), **readiness fast and twitchy** (~3 s / 2).
- Graceful shutdown is a **sequence**: `SIGTERM` → fail readiness immediately but keep serving → **wait** for the load balancer to notice (`preStop: sleep 5`, the step everyone forgets) → stop accepting, send `Connection: close`, finish in-flight work → close pools and **flush telemetry** → exit 0, comfortably inside `terminationGracePeriodSeconds`.

Next: [SLIs, SLOs & Error Budgets](../09-slis-slos-and-error-budgets/) — probes decide whether one instance gets traffic; now you need a number that says whether the *service* is healthy enough, and a principled way to decide when to stop shipping and start fixing.
