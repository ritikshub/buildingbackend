# Service Discovery & Health-Aware Routing

> An instance stops answering at 14:02:00. Its callers keep sending it traffic until 14:02:47. Nothing is misconfigured — six layers each behave exactly as documented, and their delays add up. Measured here: an **assumed 30-second window that is actually 47.25 s (1.57×), with 315 failed requests**, and — with no maximum connection lifetime, which is the default in most HTTP clients — traffic that **never stops at all**, 1,067 failures and counting, because a keep-alive connection is pinned to an address and discovery closes no sockets. Then the reduction: 47.25 s → 2.65 s, and three shutdown orderings that drop **375, 228 and 0** requests.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Orchestration: Control Loops, Schedulers & Kubernetes](../07-orchestration-and-kubernetes/), [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/), [DNS: Names on the Network](../../01-networking-and-protocols/06-dns-names-on-the-network/)
**Time:** ~75 minutes

## The Problem

Lesson 7 built a control loop that moves replicas between machines without being asked. It works. A node died and the loop had full capacity back in two ticks, at 02:14, with nobody awake.

**Nobody told the callers.**

Here is the stopwatch. One instance of your orders service — `orders-3`, one of six behind a name your checkout service calls forty times a second.

**14:02:00.00 — it stops answering.** Not a crash. A thread-pool deadlock: the process is alive, the listening socket is open, the kernel still completes the TCP (Transmission Control Protocol) handshake for anyone who connects, and no request will ever be answered again. It also stops sending heartbeats to the registry, but nothing is watching for that yet.

**14:02:04.25 — the heartbeat that never came.** Instances heartbeat every 10 seconds. `orders-3` last checked in 5.75 seconds before it wedged, so the registry has been waiting 4.25 seconds for a message that is not coming. It does not know that yet. It has no way to know that yet — "quiet" and "dead" look identical from here.

**14:02:24.25 — the lease is still valid.** The registry gives every instance a 30-second lease, deliberately: three missed heartbeats, so one dropped UDP packet or one garbage-collection pause does not evict a healthy instance. That tolerance is correct. It is also 20 seconds of silence that the registry is contractually obliged to ignore.

**14:02:28.13 — the sweep runs.** The lease expired at 24.25, but nothing *checks* continuously. A background sweep scans for expired leases every 10 seconds, and it happens to run 3.88 seconds later. `orders-3` is finally marked gone in the registry.

**14:02:30.13 — the caller's routing layer hears about it.** The registry is not the caller. The change has to propagate — a watch event, a control-plane push, a config reload. Two seconds.

**14:02:45.57 — the caller's own cached list expires.** Your client does not re-read the instance list on every request; that would be a network round trip per call. It caches it for 30 seconds. The cycle it was in had 15.45 seconds left to run.

**14:02:47.25 — the last connection closes.** The address is finally out of the caller's list — and it is *still sending requests to it*, because it holds an established keep-alive connection to that IP (Internet Protocol) address and connections are not consulted about the list. Only when that connection hits its maximum lifetime does the traffic stop.

**Forty-seven seconds.** Every request in that window failed: **315 of them**, measured. And the number that matters more than 47 is this — ask anyone on the team how long it takes for a dead instance to stop receiving traffic and they will say "thirty seconds, the lease TTL". They are quoting **one of six terms**, and it is not even the largest one.

Nothing here was misconfigured. There is no bug. Every layer did precisely what its documentation says it does, and their delays are **additive**. Almost nobody can enumerate them on demand. That enumeration is this lesson.

## The Concept

### The registry is a lease, not a list

A **service registry** is a database with one job: map a logical service name (`orders`) to the set of network addresses currently serving it (`10.0.1.7:8080`, `10.0.1.9:8080`, …). Instances write to it, callers read from it.

If it were a plain list, it would be wrong within minutes. Machines die without warning. Processes get `SIGKILL`ed. Networks partition. Anything that requires a departing instance to politely remove its own row will eventually contain rows for instances that no longer exist, and there is no way for the registry to distinguish those from healthy ones.

So a registry entry is not a row. It is a **lease**: a claim that expires unless renewed.

- **Register** — "I am `orders-3` at `10.0.1.7:8080`, and I will keep saying so." The registry records the entry and starts a clock.
- **Heartbeat** — a periodic message, here every 10 seconds, that resets the clock. This is the *only* evidence the registry ever has that you still exist.
- **TTL (Time To Live)** — how long the entry survives without a heartbeat. Here 30 seconds: exactly three missed heartbeats.
- **Expire** — silence past the TTL revokes the lease. The registry does not need your cooperation, which is the whole point.
- **Deregister** — an explicit "I am leaving." The entry is removed immediately, with no TTL wait.

The ratio of TTL to heartbeat interval is the first real design decision, and it is the same dial as probe tuning from Phase 9's [health checks](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) lesson, pointed at a different consumer. A TTL of one heartbeat evicts a healthy instance on a single lost packet. A TTL of ten heartbeats tolerates anything and takes a hundred seconds to notice a corpse. Three is the conventional compromise, and it means **a dead instance stays registered for between 30 and 40 seconds** — the TTL, plus however long it had already been quiet.

Unless you deregister. That is the same transition with the clock deleted.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="The registry lease lifecycle drawn as a state machine. An absent instance registers and enters the UP state, where it must heartbeat every ten seconds to hold its lease. From UP there are two exits: silence past the thirty second TTL, noticed only by a sweep that runs every ten seconds, which expires the lease after a measured thirty-eight seconds; or an explicit deregister, which removes the entry in zero seconds. The timing knob on each transition is labelled.">
  <defs>
    <marker id="l08-a1" markerWidth="10" markerHeight="10" refX="6.5" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A registry entry is a lease — and it has two very different exits</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2.2" stroke-linejoin="round">
      <rect x="26" y="176" width="150" height="72" rx="11" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.55"/>
      <rect x="300" y="164" width="204" height="96" rx="13" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="646" y="86" width="208" height="80" rx="11" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="646" y="262" width="208" height="80" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.8">
      <path d="M176 212 L 292 212" marker-end="url(#l08-a1)"/>
      <path d="M486 168 C 520 118, 580 106, 638 118" marker-end="url(#l08-a1)"/>
      <path d="M486 256 C 520 306, 580 318, 638 306" marker-end="url(#l08-a1)"/>
      <path d="M354 164 C 344 122, 460 122, 452 160" marker-end="url(#l08-a1)"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="101" y="208" font-size="12.5" font-weight="700">ABSENT</text>
      <text x="101" y="226" font-size="9" opacity="0.85">not in the registry</text>
      <text x="101" y="240" font-size="9" opacity="0.85">no traffic reaches it</text>
      <text x="402" y="196" font-size="13.5" font-weight="700" fill="#0fa07f">UP — lease held</text>
      <text x="402" y="216" font-size="9.5" opacity="0.9">the caller may route here</text>
      <text x="402" y="232" font-size="9.5" opacity="0.9">renewed only by heartbeats</text>
      <text x="402" y="250" font-size="9.5" opacity="0.9">the registry knows nothing else</text>
      <text x="750" y="114" font-size="13" font-weight="700" fill="#d64545">EXPIRED</text>
      <text x="750" y="134" font-size="9.5" opacity="0.9">the registry gave up on you</text>
      <text x="750" y="150" font-size="9.5" opacity="0.9">measured: 38.0 s after it wedged</text>
      <text x="750" y="290" font-size="13" font-weight="700" fill="#3553ff">DEREGISTERED</text>
      <text x="750" y="310" font-size="9.5" opacity="0.9">you said so, so no clock runs</text>
      <text x="750" y="326" font-size="9.5" opacity="0.9">measured: 0.0 s</text>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="234" y="200" font-size="10" font-weight="700">register</text>
      <text x="222" y="284" font-size="8.5" opacity="0.8">gate this on READINESS,</text>
      <text x="222" y="296" font-size="8.5" opacity="0.8">not on process start</text>
      <text x="403" y="112" font-size="10" font-weight="700" fill="#0fa07f">heartbeat every 10 s</text>
      <text x="403" y="98" font-size="8.5" opacity="0.8">the only evidence you exist</text>
      <text x="566" y="96" font-size="10" font-weight="700" fill="#d64545">silence &gt; ttl 30 s</text>
      <text x="614" y="196" font-size="8.5" opacity="0.85">+ up to 10 s of sweep granularity:</text>
      <text x="614" y="208" font-size="8.5" opacity="0.85">nothing checks continuously</text>
      <text x="566" y="338" font-size="10" font-weight="700" fill="#3553ff">deregister</text>
      <text x="566" y="352" font-size="8.5" opacity="0.85">removed at once — no TTL,</text>
      <text x="566" y="364" font-size="8.5" opacity="0.85">no sweep, no waiting</text>
    </g>
    <text x="440" y="396" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">Same registry, same knobs. 38.0 s versus 0.0 s is a decision in your shutdown handler.</text>
    <text x="440" y="416" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">And expiry is only the FIRST of six delays between a death and the last request sent to it.</text>
  </g>
</svg>
```

### Client-side and server-side discovery — who holds the list

Two shapes, and the difference is who has the list and who chooses.

**Server-side discovery.** The caller sends every request to one stable address — a load balancer, a virtual IP, a gateway. That thing holds the registry list and picks an instance. The caller knows one name and nothing else.

- Callers stay trivially simple. Any language, any client library, no discovery logic at all.
- One place to change routing policy, and one place to look during an incident.
- The balancer is on the request path: one more hop of latency, and a component whose failure takes down everything behind it.
- **Freshness is the balancer's problem, and it is usually good** — the balancer is the thing running health checks, so it can learn about a dead instance in seconds instead of waiting for a registry lease.

**Client-side discovery.** The caller fetches the instance list itself, caches it, and picks a target directly.

- One fewer network hop, and the caller can implement any policy it likes — zone-aware routing, weighted picks, hedged requests.
- **Freshness is now the caller's problem, and it is usually worse**: every caller caches its own copy, and a stale copy is invisible to everyone but that caller. This is layer 5 in the stopwatch above — 15.45 seconds of it.
- The blast radius of a bad list is bounded to one caller, which is genuinely better than a bad balancer config.
- Every language you ship needs a correct implementation. Three languages means three subtly different caching bugs.

The pattern that gets both is the **sidecar proxy**: a small proxy process running next to every instance of your application, on the same machine, taking all outbound traffic. The application speaks to `localhost` and holds no list — that is server-side discovery from the application's point of view. The proxy holds the list and picks the instance — that is client-side discovery from the network's point of view, with no shared central hop to fail. A **service mesh** is this proxy deployed everywhere plus a control plane that pushes the list to all of them. You pay for it in one more process per instance, a little latency, and a control plane that is now on your critical path for *changes*, if not for requests.

### DNS is discovery with four caches in front of it

DNS (Domain Name System) is the oldest service registry we have, and the one most people accidentally use. `orders.internal` resolves to a set of A records; your client connects to one. It works, it is universal, and it lies to you at four independent layers.

Every DNS record carries a **TTL** — the number of seconds a resolver may cache it (RFC 1035 §3.2.1; RFC 2181 §8 pins the field as a 32-bit value to be treated as unsigned). Set it to 5 and you expect 5 seconds of staleness. Then:

1. **The recursive resolver** caches the answer for the TTL. Correct behaviour. Some resolvers also enforce a *minimum* TTL of their own, silently raising your 5 to 30.
2. **The operating system** caches it again — `nscd`, `systemd-resolved`, or the platform equivalent — with its own policy.
3. **The language runtime** caches it a third time. This is where the classic disaster lives: the JVM (Java Virtual Machine) property `networkaddress.cache.ttl` defaults to 30 seconds, and with a security manager installed it defaults to **−1, meaning cache successful lookups for the entire lifetime of the process**. A long-running Java service that resolved a name at boot may hold that IP address until it is restarted, regardless of what DNS says. Entire on-call generations have learned this at 03:00.
4. **The client library** caches it a fourth time, or worse, never re-resolves because it is holding a connection (next section).

Two more sharp edges. Truncation: a DNS response over UDP (User Datagram Protocol) is limited, so a service with many instances may return a subset of its addresses, and different callers get different subsets. And **TTL cannot be revoked** — once an answer is cached, no signal you can send will invalidate it early. Lowering a TTL only helps *after* the old, higher TTL has expired everywhere, which is why "drop the TTL to 60 and fail over" has to be done a day in advance, not during the incident.

The rule that falls out: **a DNS change is not a completed rollout.** It is a request that other people's caches will honour on their own schedule.

### Connection reuse defeats discovery entirely

This is the one worth the lesson, and it survives every fix above.

DNS resolution, registry lookups and endpoint updates all answer the question *"where should I open a connection to?"* — asked once, when a connection is opened. A **keep-alive** connection (Phase 1's [Keep-Alive, Pooling & Timeouts](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/)) is deliberately kept open and reused for request after request, because handshakes are expensive. That reuse is why your p99 is not dominated by TCP and TLS setup.

It also means the connection is **pinned to an IP address**, and nothing in the discovery path ever revisits that decision.

Update DNS. Expire the lease. Deregister the instance. Push a new endpoint list to every proxy in the fleet. A client holding an established connection **keeps using it**, because it never asks again. Discovery updates lists; it does not close sockets. The list and the connection pool are two different data structures and only one of them was updated.

There are exactly three things that end it: the server closes the connection, an idle timeout closes it, or the client enforces a **maximum connection lifetime** — a hard cap on how long any single connection may be reused, after which it is closed and a new one is opened, which forces a fresh resolution. Most HTTP (Hypertext Transfer Protocol) clients ship with **no maximum lifetime at all**. In the Build It, that one default turns a 47.25-second blackhole into one that **never ends**: 1,067 failed requests over the full 160-second measurement window, still climbing when the run stops.

This is why "we updated DNS" is not a rollout, why blue-green cutovers leak traffic to the old side for minutes, and why `max_connection_duration` exists in every serious proxy.

### The blackhole window is a sum

Now put the six together. Each is individually reasonable; each was chosen by someone competent; nobody owns the total.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="The blackhole window drawn as a horizontal timeline of six additive segments totalling 47.25 seconds: heartbeat interval 4.25 seconds, registry lease grace 20 seconds, expiry sweep granularity 3.88 seconds, propagation to the caller 2 seconds, caller list cache TTL 15.45 seconds, and pooled connection reuse 1.67 seconds. A blue dashed line at 30 seconds marks the lease TTL that everyone assumes is the whole window; the first four segments fall inside it and the last two, in red, fall beyond it. 315 requests were sent into the window and every one failed.">
  <defs>
    <marker id="l08-a2" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The blackhole window is a SUM — measured, one representative death</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="currentColor">
      <text x="60" y="62" font-size="10.5" font-weight="700">orders-3 stops answering</text>
      <text x="60" y="77" font-size="9" opacity="0.8">socket still open · heartbeats stop</text>
      <text x="820" y="62" font-size="10.5" font-weight="700" text-anchor="end" fill="#d64545">the caller finally stops sending</text>
      <text x="820" y="77" font-size="9" opacity="0.8" text-anchor="end">t = 47.25 s</text>
    </g>

    <path d="M542 96 L 542 214" fill="none" stroke="#3553ff" stroke-width="1.8" stroke-dasharray="5 4"/>
    <text x="536" y="110" font-size="10" font-weight="700" fill="#3553ff" text-anchor="end">what everyone assumes: 30.00 s</text>
    <text x="536" y="124" font-size="9" fill="#3553ff" opacity="0.9" text-anchor="end">&#8220;it is the lease TTL&#8221; — one term of six</text>

    <g fill="none" stroke-width="1.8">
      <rect x="60" y="150" width="68" height="44" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
      <rect x="128" y="150" width="322" height="44" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
      <rect x="450" y="150" width="62" height="44" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
      <rect x="512" y="150" width="33" height="44" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f"/>
      <rect x="545" y="150" width="248" height="44" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/>
      <rect x="793" y="150" width="27" height="44" fill="#d64545" fill-opacity="0.18" stroke="#d64545"/>
    </g>
    <g fill="none" stroke-width="1.6">
      <circle cx="94" cy="172" r="9" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <circle cx="289" cy="172" r="9" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <circle cx="481" cy="172" r="9" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <circle cx="528" cy="172" r="9" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/>
      <circle cx="669" cy="172" r="9" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
      <circle cx="806" cy="172" r="9" fill="#d64545" fill-opacity="0.30" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="10.5" font-weight="700" text-anchor="middle">
      <text x="94" y="176">1</text><text x="289" y="176">2</text><text x="481" y="176">3</text>
      <text x="528" y="176">4</text><text x="669" y="176">5</text><text x="806" y="176">6</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.6">
      <path d="M60 200 L 60 210"/><path d="M820 200 L 820 210"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.75">
      <text x="60" y="224" text-anchor="middle">0 s</text>
      <text x="820" y="224" text-anchor="middle">47.25 s</text>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="60" y="258" font-size="9" font-weight="700" opacity="0.65">INSIDE THE ASSUMPTION</text>
      <text x="60" y="278">1 &#183; heartbeat interval</text>
      <text x="60" y="296">2 &#183; registry lease grace</text>
      <text x="60" y="314">3 &#183; expiry sweep granularity</text>
      <text x="60" y="332">4 &#183; propagation to the caller</text>
      <text x="396" y="278" text-anchor="end" font-weight="700">4.25 s</text>
      <text x="396" y="296" text-anchor="end" font-weight="700">20.00 s</text>
      <text x="396" y="314" text-anchor="end" font-weight="700">3.88 s</text>
      <text x="396" y="332" text-anchor="end" font-weight="700">2.00 s</text>
      <text x="466" y="258" font-size="9" font-weight="700" opacity="0.65" fill="#d64545">NOBODY COUNTS THESE</text>
      <text x="466" y="278">5 &#183; caller list cache TTL</text>
      <text x="466" y="296">6 &#183; pooled connection reuse</text>
      <text x="800" y="278" text-anchor="end" font-weight="700">15.45 s</text>
      <text x="800" y="296" text-anchor="end" font-weight="700">1.67 s</text>
      <text x="466" y="322" font-size="9.5" fill="#d64545" font-weight="700">315 requests sent into the window.</text>
      <text x="466" y="338" font-size="9.5" fill="#d64545" font-weight="700">Every one of them failed.</text>
    </g>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="60" y="356" width="360" height="62" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="460" y="356" width="360" height="62" rx="10" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>
    <g fill="currentColor">
      <text x="240" y="378" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">assumed 30.00 s</text>
      <text x="240" y="396" font-size="9.5" text-anchor="middle" opacity="0.9">measured 47.25 s this run &#183; mean 48.96 s</text>
      <text x="240" y="411" font-size="9.5" text-anchor="middle" opacity="0.9">p95 62.24 s &#183; worst 69.54 s of 2000 deaths</text>
      <text x="640" y="378" font-size="10.5" font-weight="700" text-anchor="middle" fill="#d64545">with no max connection lifetime</text>
      <text x="640" y="396" font-size="9.5" text-anchor="middle" opacity="0.9">segment 6 never ends: NEVER stopped in 160 s</text>
      <text x="640" y="411" font-size="9.5" text-anchor="middle" opacity="0.9">1067 failed requests &#183; and still climbing</text>
    </g>
    <text x="440" y="448" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Every layer behaved exactly as documented. Nobody owns the sum. Measure it before you need it.</text>
  </g>
</svg>
```

Three things to take from the shape of that bar.

**The assumption is not wrong, it is incomplete.** Thirty seconds is a real number that appears in a real config file. It is the second of six terms, and nothing more.

**Ratios, not seconds, are the transferable result.** Measured over 2,000 simulated deaths — the same fault, only the *phase* of each layer's own cycle varying — the window averaged **48.96 s, with p95 62.24 s and a worst case of 69.54 s** against an assumed 30. That is **1.63× at the mean and 2.07× at p95**. Your numbers will differ. The multiplier will not, because the structure is the same everywhere.

**The window is a distribution, not a number.** Nothing about the fault changed across those 2,000 runs. What changed is where each independent clock happened to be — how long since the last heartbeat, how long until the next sweep, how much was left on the caller's cache. You do not get to pick, and a post-incident timeline that reads "it took 40 seconds" tells you about one draw from that distribution, not about your system.

### Registered ≠ healthy ≠ ready

Three states get collapsed into one, and collapsing them causes real outages.

- **Registered** — the registry has a live lease for this address. It means a process once said so and has kept saying so. It does not mean the process can serve.
- **Healthy** — the process is not broken. It answers, it has not deadlocked, it will not need to be restarted.
- **Ready** — this instance should receive traffic *right now*. Config loaded, pools warm, caches primed, dependencies reachable, and not currently draining.

The failure mode of collapsing them is the deploy that succeeds and takes 4% of traffic with it: a new instance registers at process start, before it has connected to Postgres or read its config, and the registry cheerfully hands its address to every caller. Every request it receives for the next ninety seconds fails, and the deploy is green.

The fix is one line of ordering: **register on readiness, not on start; deregister on drain, not on exit.** Phase 9's [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) builds the readiness signal itself — the probe separation, the hard/soft dependency classification, the TTL-cached checks. This lesson consumes it: **readiness is the registration signal.** A ready instance is registered; an unready one is not; and because readiness is reversible, an instance that fails a dependency check leaves rotation and comes back without ever being restarted.

The subtle version of the same bug is a registry that treats "registered" as "healthy" and never checks anything itself. That registry is a list of processes that once claimed to be able to serve, aged by up to a lease TTL. It is not a health signal, and if it is your only one, your detection time is the whole 47 seconds.

### Active health checks and passive outlier detection

Registry expiry is not a detection mechanism. It is a garbage collector. Two mechanisms actually detect, and they fail in opposite directions.

**Active health checking** — the router probes each instance on a schedule (here every second, ejecting after 3 consecutive failures) and ejects the ones that fail.

- Detection is fast and bounded: `period × threshold`, independent of your traffic.
- It works on instances receiving **no traffic at all** — a cold canary, an instance in a zone nobody is routing to.
- It costs probe traffic forever, healthy or not. Measured here: **7 probes/s across 6 instances, 18% of production request rate.** Scale that to 200 instances and the probe traffic is a service of its own, with its own capacity plan.
- It creates the **health-check stampede**: if 100 routers each probe 200 instances, that is 20,000 probes per interval, all of it hitting an endpoint that is often a shared code path with your real handlers.
- It can lie in both directions. A shallow probe passes on a deadlocked process; a deep probe couples every instance's health to a shared dependency, so one slow database ejects the entire fleet.

**Passive outlier detection** — no probes at all. The router watches the outcome of *real* requests and ejects an instance after N consecutive failures (here 5).

- **Zero added traffic.** The signal is work you were doing anyway.
- Often *faster* than active checking, and this is the counterintuitive result: at 40 req/s round-robin over 6 instances, each instance receives about **6.7 req/s** — a higher-frequency probe than a 1 Hz health check. Measured: **2.65 s to eject, against 3.50 s for active checking.**
- Its floor is hard and structural: it can only learn from failures, so it must **lose 5 requests first**. Those failures are the price of the signal.
- It is blind to any instance nobody is calling. A pool member receiving no traffic is never evaluated, which is precisely the instance you are about to shift traffic onto.

They are complementary, not alternatives: active checking covers the no-traffic case, passive covers the fast-detection case, and running both means whichever signal arrives first wins.

### Cap the ejection, or the protection becomes the outage

Both mechanisms share an assumption that is invisible until it breaks: **ejecting an instance is a bet that the rest of the pool is healthy.**

When the fault is *shared* — a degraded downstream, an expired certificate, a bad config rolled to everything, a database at connection limit — every instance starts failing at once. Every instance crosses the ejection threshold at roughly the same time. The pool empties, and now 100% of requests fail with "no healthy upstream" on a fleet where *no individual instance was broken*.

Measured in the Build It: 8 instances, a shared dependency failing 70% of requests. Uncapped, ejection removed **8 of 8 instances by t=22.50 s**, and **1,098 requests got no healthy upstream** — a **70%-failure partial fault converted into a 71.9%-failure outage by the protection mechanism itself.** Capped at 50%, four instances stayed in rotation, the pool never emptied, and **870 requests succeeded instead of 562 — 43.5% success against 28.1%.**

The cap is one number, it is the difference between degraded and down, and every serious proxy has it. Envoy's `max_ejection_percent` defaults to 10%.

### Graceful shutdown is an ordering problem

Every delay above is about an *unplanned* death, where detection is unavoidable. A planned shutdown — a deploy, a scale-down, a node drain — is different, because you know in advance. You can delete the entire detection term by *telling* the registry instead of letting it find out.

But telling it is not enough, because **deregistration is not synchronous.** The registry updates instantly; the caller learns about it 2 seconds later. If you stop the process at the moment you deregister, that 2-second gap is a window in which the caller is still routing to a process that no longer exists.

There is exactly one correct ordering, and it has four steps:

1. **Deregister** — or fail readiness, which deregisters you. Keep serving.
2. **Wait** — long enough for the deregistration to reach every caller and every proxy. This is the step everyone omits, and the wait must be set *from the measured propagation delay*, not guessed.
3. **Drain** — stop accepting new work; let in-flight requests finish.
4. **Stop.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="Three shutdown orderings measured on a timeline. Ordering A stops the process immediately and traffic keeps arriving for the 3.5 seconds active health checking needs to detect it, dropping 375 requests. Ordering B deregisters then stops immediately, deleting the detection term but still leaving the 2 seconds of propagation, dropping 228 requests. Ordering C deregisters, waits 4 seconds while still serving, drains in-flight work for 0.4 seconds and then stops, dropping zero requests.">
  <defs>
    <marker id="l08-a3" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Three orderings, one rolling replacement, measured drops</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="326" y="48" font-size="9.5" font-weight="700" fill="#3553ff">t = 2.00 s &#183; an explicit deregistration reaches the caller</text>
    <text x="453" y="64" font-size="9.5" font-weight="700" fill="#e0930f">t = 3.50 s &#183; detection alone, with active health checks</text>
    <g fill="none" stroke-width="1.6" stroke-dasharray="5 4" stroke-opacity="0.75">
      <path d="M320 72 L 320 84 M320 100 L 320 164 M320 180 L 320 244 M320 260 L 320 316" stroke="#3553ff"/>
      <path d="M448 72 L 448 84 M448 100 L 448 164 M448 180 L 448 244 M448 260 L 448 316" stroke="#e0930f"/>
    </g>

    <text x="150" y="94" font-size="11" font-weight="700" fill="currentColor">(a) stop the process immediately — tell nobody</text>
    <text x="830" y="94" font-size="11.5" font-weight="700" fill="#d64545" text-anchor="end">375 DROPPED</text>
    <g fill="none" stroke-width="1.8">
      <rect x="150" y="102" width="298" height="32" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="448" y="102" width="382" height="32" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
    </g>
    <text x="299" y="123" font-size="9" text-anchor="middle" fill="currentColor">still routed here &#183; in-flight severed</text>
    <text x="639" y="123" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">detected — traffic finally stops</text>

    <text x="150" y="174" font-size="11" font-weight="700" fill="currentColor">(b) deregister, then stop immediately — no wait</text>
    <text x="830" y="174" font-size="11.5" font-weight="700" fill="#d64545" text-anchor="end">228 DROPPED</text>
    <g fill="none" stroke-width="1.8">
      <rect x="150" y="182" width="170" height="32" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="320" y="182" width="510" height="32" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
    </g>
    <text x="235" y="203" font-size="9" text-anchor="middle" fill="currentColor">propagating</text>
    <text x="575" y="203" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">the caller knows — but you already exited</text>

    <text x="150" y="254" font-size="11" font-weight="700" fill="currentColor">(c) deregister &#8594; wait 4.0 s &#8594; drain 0.4 s &#8594; stop</text>
    <text x="830" y="254" font-size="11.5" font-weight="700" fill="#0fa07f" text-anchor="end">0 DROPPED</text>
    <g fill="none" stroke-width="1.8">
      <rect x="150" y="262" width="340" height="32" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
      <rect x="490" y="262" width="34" height="32" fill="#0fa07f" fill-opacity="0.32" stroke="#0fa07f"/>
      <rect x="524" y="262" width="306" height="32" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
    </g>
    <path d="M320 262 L 320 294" fill="none" stroke="#0fa07f" stroke-width="1.4" stroke-dasharray="3 3"/>
    <text x="235" y="283" font-size="9" text-anchor="middle" fill="currentColor">serving, propagating</text>
    <text x="405" y="283" font-size="9" text-anchor="middle" fill="currentColor">serving, nothing new arrives</text>
    <text x="677" y="283" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.7">exited with zero in flight</text>
    <text x="507" y="312" font-size="8.5" text-anchor="middle" fill="#0fa07f" font-weight="700">drain</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M150 330 L 840 330" marker-end="url(#l08-a3)"/>
      <path d="M150 326 L 150 334"/><path d="M235 326 L 235 334"/><path d="M320 326 L 320 334"/><path d="M405 326 L 405 334"/>
      <path d="M490 326 L 490 334"/><path d="M575 326 L 575 334"/><path d="M660 326 L 660 334"/><path d="M745 326 L 745 334"/><path d="M830 326 L 830 334"/>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.75" text-anchor="middle">
      <text x="150" y="348">0 s</text><text x="235" y="348">1</text><text x="320" y="348">2</text><text x="405" y="348">3</text>
      <text x="490" y="348">4</text><text x="575" y="348">5</text><text x="660" y="348">6</text><text x="745" y="348">7</text><text x="830" y="348">8 s</text>
    </g>
    <text x="20" y="334" font-size="9" fill="currentColor" opacity="0.7">time from the</text>
    <text x="20" y="346" font-size="9" fill="currentColor" opacity="0.7">decision to stop</text>

    <text x="440" y="382" font-size="11.5" text-anchor="middle" fill="currentColor" font-weight="700">(b) deletes the detection term. Only (c) also covers the propagation you cannot delete.</text>
    <text x="440" y="402" font-size="10.5" text-anchor="middle" fill="currentColor" opacity="0.9">The only new ingredient between 228 dropped and 0 is patience. Deregistering is not synchronous.</text>
  </g>
</svg>
```

Ordering (b) is the one worth staring at. It is what a careful engineer writes: catch `SIGTERM`, deregister, exit cleanly. It deletes the entire detection term — the largest single win available — and it still drops 228 requests, because it treats an asynchronous fact as a synchronous one.

## Build It

[`code/discovery.py`](code/discovery.py) is five numbered arguments, standard library only, seeded, about one second. Time is **simulated in discrete 50-millisecond ticks** rather than slept — the whole point is to observe minutes of registry behaviour, and doing that in real time would take minutes and produce a different answer on every run. Every clock in the model (heartbeats, sweeps, cache refreshes, probes, connection expiries) advances on the same tick, so the results are exactly reproducible.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/08-service-discovery-and-routing/code/discovery.py
```

**Section 1 is the lease.** The registry is genuinely just a dictionary of leases plus a sweep. `sweep()` is the entire expiry mechanism:

```python
def sweep(self, now: float) -> List[str]:
    """Expire every lease whose last heartbeat is older than the TTL."""
    expired = []
    for lease in self.leases.values():
        if lease.state == "UP" and now - lease.last_heartbeat > self.ttl:
            lease.state = "EXPIRED"
            expired.append(lease.instance)
    return expired
```

Note what it does *not* do: it does not run continuously. It runs every `SWEEP_INTERVAL`, which is why "the lease expired" and "the registry noticed" are two different moments.

```console
== 1 · A REGISTRY WITH LEASES ==
  heartbeat every 10s | lease ttl 30s (= 3 missed heartbeats) |
  expiry sweep every 10s

  t=  0.00s  REGISTER    orders-a   10.0.1.7:8080    lease ttl=30s
  t=  0.00s  REGISTER    orders-b   10.0.1.9:8080    lease ttl=30s
  t=  6.00s  REGISTER    orders-c   10.0.2.4:8080    lease ttl=30s
  t= 22.00s  WEDGES      orders-b   stops answering AND stops heartbeating —
                        but its listening socket stays open
  t= 30.00s  DEREGISTER  orders-c   removed at once — no TTL wait
  t= 60.00s  EXPIRE      orders-b   silent 40.0s > ttl 30s

  final registry view: orders-a
  orders-b left by TTL EXPIRY:     38.0s after it stopped answering.
  orders-c left by DEREGISTERING:   0.0s.
```

Two instances leave the same registry with the same configuration. `orders-b` wedges and takes **38.0 seconds** to disappear; `orders-c` deregisters and takes **0.0**. The 38 is not a tuning failure — it is 30 seconds of deliberate lease tolerance, plus 8 seconds of "it had already been quiet when it died and the sweep runs on its own schedule."

**Section 2 is the centrepiece.** Six delays, decomposed. The closed form for each layer is the interesting part, because it is where the arithmetic stops being hand-waving:

```python
hb_due  = last_hb + HEARTBEAT_INTERVAL     # 1. the heartbeat that never comes
ttl_ok  = last_hb + LEASE_TTL              # 2. grace, measured from the LAST GOOD one
reg_gone = next sweep tick after ttl_ok    # 3. nothing checks continuously
seen_at = reg_gone + PROPAGATION_DELAY     # 4. the registry is not the caller
list_gone = next cache refresh after seen_at   # 5. the caller re-reads on its own clock
stop = max(list_gone, conn_expiry[DEAD])   # 6. the connection outlives the list
```

Layer 2 is measured from the **last successful heartbeat**, not from the death — which is why layers 1 and 2 do not double-count, and why the pair together is always between 30 and 40 seconds regardless of when the instance dies.

The script does not report a single lucky run. It draws 2,000 independent deaths — varying only the *phase* of each clock — and picks the run whose every layer sits closest to that layer's own mean, so the representative profile is representative layer by layer rather than merely having a median total:

```console
== 2 · THE BLACKHOLE WINDOW IS A SUM ==
  layer                              this run   cumulative   mean over 2000
  ------------------------------------------------------------------------
  1  heartbeat interval               4.25s        4.25s          4.97s
  2  registry lease grace            20.00s       24.25s         20.00s
  3  expiry sweep granularity         3.88s       28.13s          4.95s
  4  propagation to the caller        2.00s       30.13s          2.00s
  5  caller list cache TTL           15.45s       45.57s         14.77s
  6  pooled connection reuse          1.67s       47.25s          2.27s
  ------------------------------------------------------------------------
  caller stops sending                           47.25s         48.96s  <-- TOTAL

  assumed window (everyone quotes the lease TTL):   30.00 s
  measured, this run:                              47.25 s
  measured, mean of 2000 deaths:                    48.96 s
  measured, p95:                                   62.24 s
  measured, worst:                                 69.54 s
  reality / assumption:   this run  1.57x   mean  1.63x   p95  2.07x

  tick simulation of the same run: 47.25s — closed form and simulation AGREE.
  requests sent into the blackhole: 315 — every one of them failed.
  traffic stopped because: pooled connection hit its max lifetime
```

The closed-form model and a full tick-by-tick simulation of the same seed produce the identical **47.25 s**, which is the check that the arithmetic above describes the system and not a plausible story about it. **315 requests** went into the blackhole. And read the last line: the thing that finally stopped the traffic was **not** the registry, and not the caller's list. It was a connection timer.

**Layer 6 on its own** is the result worth carrying out of this lesson. Same fault, same seed, one change — remove the maximum connection lifetime, which is the default in most HTTP clients:

```console
  max lifetime    60s -> traffic stopped after  47.25s —  315 failed requests
  max lifetime  unset -> NEVER stopped  in    160s — 1067 failed requests
```

The registry expired the lease. The caller's list dropped the address. The caller kept sending for the entire 160-second run, because a keep-alive connection is pinned to an address and **discovery closes no sockets.** Every fix in the next section works only because ejection also closes the pinned connection.

**Section 3 reduces it.** Identical fault, identical seed; only the detection mechanism changes:

```console
== 3 · REDUCE IT, MEASURABLY ==
  configuration                   window    failed   probes/s   what it costs
  ------------------------------------------------------------------------------
  registry heartbeats only        47.25s       315   -          nothing — and it is by far the slowest
  + active health checks           3.50s        24   7          steady probe load, healthy or not
  + passive outlier ejection       2.65s        18   -          5 sacrificial failures before it acts
  + both                           2.65s        18   7          both costs; the faster signal wins
```

Active checking is **14× faster than the registry path (3.50 s against 47.25 s) with 13× fewer failures**, and it costs **7 probes/s — 18% of production request rate**, paid forever, on healthy instances and sick ones alike.

Passive ejection is **faster still at 2.65 s, with zero probe traffic**, and the reason is the counterintuitive one: at 40 req/s over 6 instances, each instance is receiving **6.7 req/s of real traffic**, which is a six-times-higher-frequency probe than a 1 Hz health check. Your own traffic is the best health signal you have — right up until an instance has no traffic, at which point passive detection sees nothing at all. Its other cost is exact and unavoidable: **5 failed requests** are the price of the signal, every time.

Running both gives 2.65 s: whichever signal arrives first wins. That is the production answer, and it is why every mature proxy ships both.

**Section 4 caps it.** The same passive ejection, pointed at a fault it was never designed for — 8 instances, a shared downstream failing 70% of requests, no instance individually broken:

```console
== 4 · CAP THE EJECTION — WHEN EVERY INSTANCE LOOKS BAD ==
  max_ejection_percent  ejected  left in rotation  succeeded  no-healthy-upstream  success
  ----------------------------------------------------------------------------------------
  100%                      8/8                 0        562                 1098     28.1%
  50%                       4/8                 4        870                    0     43.5%
```

Uncapped, ejection removed **8 of 8 instances by t=22.50 s** and the pool went empty. **1,098 requests got "no healthy upstream"** — a total failure that the instances themselves never had. A 70%-failure partial fault became a **71.9%-failure outage, caused entirely by the protection mechanism.** Capped at 50%, four instances stayed in rotation and **870 requests succeeded instead of 562 — 43.5% against 28.1%** — with the pool never emptying.

Ejection is a bet that the rest of the pool is healthy. Cap the bet.

**Section 5 orders the shutdown.** A rolling replacement of all six instances, ten seconds apart, at 40 req/s with 400 ms of server work per request. The drain wait is not guessed — it is set *from* the measured propagation delay of 2.00 s, plus margin, giving 4.0 s:

```console
== 5 · GRACEFUL SHUTDOWN ORDERING, MEASURED ==
  ordering                                       sent   served   DROPPED
  ----------------------------------------------------------------------
  (a) stop the process immediately                2540     2165       375
  (b) deregister, then stop immediately           2480     2252       228
  (c) deregister -> wait 4.0s -> drain -> stop    2480     2480         0
```

**(a) drops 375.** For 3.50 s after each process dies the caller is still routing to it, and every request already in flight is severed.

**(b) drops 228.** Deregistering deletes the whole detection term — the single largest available win — but the caller still needs 2.00 s to hear about it, and you did not wait. This is the ordering most services actually ship.

**(c) drops 0.** Same deregistration, plus the wait, plus the drain. **Served 2,480 of 2,480.** The only new ingredient is patience.

The generalisable form: `drain wait > propagation delay`, where the propagation delay is a number you have measured rather than a number you feel good about. Everything else in the sequence is standard; this one inequality is the whole result.

## Use It

### Kubernetes is a registry, and readiness is the registration signal

You do not run a registry in Kubernetes — you already have one, spelled differently.

- A **Service** is the stable name and virtual IP. It is the server-side discovery front door.
- An **EndpointSlice** (the sharded successor to Endpoints) is the registry table: the actual pod IPs currently backing that Service. This is the list.
- **The readiness probe is the register/deregister call.** The kubelet reports readiness, the endpoint controller adds or removes the pod's address from the EndpointSlice, and kube-proxy (or your CNI's dataplane, or a mesh sidecar) reprograms routing on every node. There is no heartbeat and no lease TTL in the pod's hands at all — readiness *is* the lease renewal.

```yaml
apiVersion: v1
kind: Service
metadata: { name: orders }
spec:
  selector: { app: orders }
  ports: [{ port: 80, targetPort: 8080 }]
  # publishNotReadyAddresses: false is the default and the right answer.
  # Setting it true puts un-ready pods in the EndpointSlice — occasionally
  # needed for peer discovery in stateful systems, never for request traffic.
---
apiVersion: v1
kind: Service
metadata: { name: orders-headless }
spec:
  clusterIP: None          # headless: DNS returns every pod IP directly
  selector: { app: orders }
  # No virtual IP, no kube-proxy hop. This is CLIENT-SIDE discovery, and it
  # hands your client library the entire staleness problem from section 2 —
  # including the connection pinning, which DNS cannot fix.
```

**The race everyone hits.** A pod's termination has two things happening concurrently and *unordered*: the kubelet sends `SIGTERM` to your container, and the endpoint controller removes the address from the EndpointSlice and propagates that to every node. Kubernetes does not sequence these. If your process exits promptly on `SIGTERM`, it is gone before some nodes have heard, and those nodes route to a closed port — ordering (b), measured at 228 dropped.

This is exactly why a `preStop` sleep is standard practice, and it is worth being precise about what it buys: it is not a workaround for a bug, it is the **wait** step, implemented in the one place that runs before `SIGTERM` is delivered.

```yaml
spec:
  # Must exceed preStop + drain + your longest request, with headroom.
  terminationGracePeriodSeconds: 45
  containers:
    - name: orders
      lifecycle:
        preStop:
          exec:
            # The wait. Runs BEFORE SIGTERM; the app keeps serving throughout.
            # Set it from your MEASURED endpoint propagation, not from a blog post.
            command: ["sh", "-c", "sleep 5"]
      readinessProbe:                 # this is your registration signal
        httpGet: { path: /readyz, port: 8080 }
        periodSeconds: 3
        failureThreshold: 2
```

The Build It's 47.25 s decomposition still applies here; the terms are just renamed. Layers 1-3 collapse (readiness replaces heartbeat-and-lease), layer 4 becomes endpoint propagation to every node, layer 5 becomes your client's own caching if you use a headless Service, and **layer 6 is unchanged and untouched by any of it**.

### Consul, etcd and the lease model in the wild

**Consul** implements exactly the lease vocabulary: an agent registers a service, and the check keeps it alive. Its two check styles map to this lesson's two mechanisms — a TTL check is a heartbeat the *application* pushes (register, then renew, or expire), while an HTTP or script check is an active health check Consul performs *for* you. `DeregisterCriticalServiceAfter` is the lease TTL by another name.

```json
{
  "service": {
    "name": "orders",
    "port": 8080,
    "check": {
      "http": "http://localhost:8080/readyz",
      "interval": "3s",
      "timeout": "1s",
      "DeregisterCriticalServiceAfter": "60s"
    }
  }
}
```

**etcd** exposes the lease primitive directly, and it is the cleanest illustration of the model: `Lease.Grant(ttl)` creates a lease, keys attached to it are deleted when it expires, and `Lease.KeepAlive` is the heartbeat. Kubernetes itself stores node heartbeats this way. If you ever build a registry, this is the primitive you are building on.

### Envoy: everything from sections 3 and 4, as config

The proxy config below is section 3 and section 4 with the names filled in — this is the mapping worth memorising:

```yaml
health_checks:                        # ACTIVE — section 3's 7 probes/s
  - timeout: 1s
    interval: 1s
    unhealthy_threshold: 3            # 1s x 3 = the measured 3.50s detection
    healthy_threshold: 2              # harder to come back than to leave: no flapping
    http_health_check: { path: /readyz }

outlier_detection:                    # PASSIVE — section 3's 2.65s, zero probes
  consecutive_5xx: 5                  # the 5 sacrificial failures
  interval: 1s
  base_ejection_time: 30s             # and it doubles on repeat ejections
  max_ejection_percent: 50            # SECTION 4. The default is 10.

common_http_protocol_options:
  max_connection_duration: 60s        # LAYER 6. Without this, nothing above helps.
  idle_timeout: 300s
```

`max_connection_duration` is the line to add today. It is the difference between the 47.25-second window and the one that never closes.

### DNS TTL and the runtime caches in front of it

```bash
# 1. What the record actually says — not what you configured six months ago.
dig +noall +answer orders.internal
# orders.internal. 30 IN A 10.0.1.7     <- 30 is the TTL, in seconds

# 2. Watch it count down in a resolver's cache; if it does not fall, you are
#    reading a cache that is ignoring you.
dig @10.0.0.2 orders.internal | grep -A1 'ANSWER SECTION'
```

The runtime caches are the ones that bite:

```text
JVM   networkaddress.cache.ttl=30            # default 30s; -1 with a security
      networkaddress.cache.negative.ttl=0    # manager = cache for process lifetime
Go    no DNS cache by default; http.Transport.IdleConnTimeout=90s, and
      NO max connection lifetime — set one yourself and re-resolve
Node  dns.lookup goes to the OS resolver; libraries add their own caching
glibc nscd / systemd-resolved cache independently of all of the above
```

Set the JVM one explicitly in any long-running service. `-1` in a containerised service means the process resolves its dependencies once, at boot, and never again.

### Bound the connection, everywhere

Every one of these exists because of layer 6:

```text
Envoy        common_http_protocol_options.max_connection_duration
nginx        keepalive_time (upstream), keepalive_timeout
HAProxy      hard-stop-after / server ... maxconn, "http-reuse" policy
Go           write it yourself: a Transport wrapper or a periodic CloseIdleConnections
HikariCP     maxLifetime (default 30 min) — the same idea for database pools
```

The database-pool version is the same bug with a different blast radius: after a failover, pooled connections still point at the old primary until something closes them.

### Rules that survive contact with an incident

- **Measure your real window; never assume the TTL.** Kill an instance in staging with the traffic on, and time it end to end with a stopwatch. If the measured number surprises you, it is because you were quoting one of six terms. Write the total down where the on-call can find it.
- **Deregister before you stop, and then wait.** The wait comes from your measured propagation delay, not from a default. Measured: 375 dropped with no deregistration, 228 with deregistration and no wait, **0 with both.**
- **Bound every connection's lifetime.** A discovery system that cannot close a socket cannot route around anything. Without a maximum lifetime, the window measured here never closed at all.
- **Cap outlier ejection at 50% or less.** Ejection assumes the rest of the pool is healthy; when the fault is shared, an uncapped ejector converts a 70%-failure partial fault into a **71.9%-failure outage**.
- **Register on readiness, deregister on drain.** Registered, healthy and ready are three states. An instance that registers at process start will receive traffic before it can serve it.
- **Run active and passive detection together.** Passive was faster here (2.65 s against 3.50 s) and free, but it is blind to instances with no traffic, and it always pays 5 failed requests for the signal.
- **A DNS change is not a completed rollout.** It is a request that other people's caches will honour on their own schedule — and it does not close a single existing connection.

## Think about it

1. Layers 1-3 (heartbeat, lease grace, sweep) sum to 28.13 s in the measured run, and section 5 shows that deregistering deletes all of it. So why keep a lease TTL at all? Describe the specific failure the TTL exists for, and what your system does in that case if you shorten the TTL to 5 seconds to "make detection faster."
2. Passive ejection beat active checking (2.65 s against 3.50 s) because each instance was receiving 6.7 req/s. At what request rate per instance does that reverse — and what does the answer imply about which mechanism protects a freshly scaled-up pod, or the first instance in a new zone?
3. You set `max_connection_duration` to 60 s across a fleet of 500 instances that all started at the same moment during a deploy. Trace what happens 60 seconds later, name the earlier lesson whose fix applies, and give the one-line change.
4. Section 4 capped ejection at 50%. Suppose the fault is *not* shared: exactly 5 of your 8 instances are genuinely broken. What does the 50% cap do now, and how would you distinguish the two situations automatically, using only signals a proxy already has?
5. Ordering (c) drops zero requests during a planned shutdown, and it does nothing at all for the unplanned case in section 2. List the mechanisms that reduce the *unplanned* window, in the order you would add them, with the cost of each — and say which one you would still add if you already had all the others.

## Key takeaways

- **The blackhole window is a sum, and everyone quotes one term of it.** Measured over 2,000 deaths: an assumed 30.00 s (the lease TTL) against a real **47.25 s in the representative run, 48.96 s mean, 62.24 s p95, 69.54 s worst — 1.57× to 2.07×**. The six terms are the heartbeat interval (4.25 s), lease grace (20.00 s), sweep granularity (3.88 s), propagation (2.00 s), the caller's cached list (15.45 s) and pooled connection reuse (1.67 s). **315 requests** went into that window and all of them failed.
- **Connection reuse defeats discovery entirely.** A keep-alive connection is pinned to an IP address and no discovery update closes a socket. With no maximum connection lifetime configured — the default in most HTTP clients — the caller **never stopped** sending to the dead instance: **1,067 failed requests over the full 160-second run**, after the lease had expired and the address had left the caller's list. Bound the lifetime, or nothing upstream of it matters.
- **A registry entry is a lease, and expiry is garbage collection, not detection.** Two instances left the same registry **38.0 s apart**: one waited out a TTL after wedging, the other deregistered in **0.0 s**. Register on *readiness*, not on process start — registered, healthy and ready are three different states, and collapsing them sends traffic to instances that cannot serve it.
- **Detection is cheap compared with the registry path, and passive is often the fastest.** Active health checks cut the window from **47.25 s to 3.50 s (14×, 315 → 24 failures — 13× fewer)** for a permanent cost of **7 probes/s, 18% of production request rate**. Passive outlier ejection reached **2.65 s with zero probe traffic** — real traffic at 6.7 req/s per instance is a higher-frequency probe than a 1 Hz check — but it must lose **5 requests** to learn anything and is blind to instances receiving no traffic. Run both.
- **Cap the ejection or the protection becomes the outage.** Against a shared 70%-failure fault, uncapped ejection removed **8 of 8 instances by t=22.50 s**, emptied the pool, and returned "no healthy upstream" to **1,098 requests** — turning a partial fault into a **71.9%-failure outage**. A 50% cap kept four instances serving: **870 successes against 562, 43.5% against 28.1%.**
- **Graceful shutdown is an ordering problem, and the wait is the step everyone omits.** Rolling all six instances dropped **375** requests when the process just stopped, **228** when it deregistered and exited immediately (the detection term deleted, the 2.00 s propagation ignored), and **0** when it deregistered, waited 4.0 s while still serving, drained, and then stopped. The rule is one inequality: `drain wait > measured propagation delay`.

Next: [Reverse Proxies, Load Balancers & Ingress](../09-reverse-proxies-and-load-balancers/) — you now have a fresh, health-aware list of instances; the next question is what sits in front of it, how it picks one, and what it does with the request on the way through.
