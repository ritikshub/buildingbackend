# Service Discovery, Client-Side Balancing & Subsetting

> One thousand clients calling eight hundred backends, each client holding a connection to each backend, is **800,000 sockets** — 16.8 GB of memory for zero requests in flight, 100 health probes per second against every backend, and 2,667 TLS handshakes per second on every deploy. Nothing is broken. The topology is quadratic and it grew past the size where quadratic is affordable. This lesson builds the fix: deterministic subsetting, which cuts the same fleet to **20,000 connections — 2.5% — while giving every backend exactly 25 clients, measured min 25, max 25, standard deviation 0.00.**

**Type:** Build
**Languages:** Python
**Prerequisites:** [Layer 4 vs Layer 7, Health Checks & Outlier Ejection](../04-l4-l7-health-checks-and-ejection/), [Names on the Network: DNS](../../01-networking-and-protocols/06-dns-names-on-the-network/)
**Time:** ~75 minutes

## The Problem

Your checkout service has 1,000 instances. It calls the pricing service, which has 800. Both numbers grew slowly, over about two years, and neither of them is wrong.

Two years ago checkout ran on twelve machines and reached pricing through a load balancer. Someone measured the extra network hop at 1.4 ms, and the pricing team observed — correctly — that the balancer itself had been the outage twice that year. So checkout moved to **client-side balancing**: each instance resolves the full list of pricing endpoints and picks a backend itself. No middle box, no extra hop, no single thing whose failure takes down the path. It was a straightforwardly good decision. It is still a straightforwardly good decision at twelve instances.

At 1,000 clients and 800 backends it is 800,000 open TCP connections, and every one of them lives on both ends.

**Monday 09:40 — checkout scales up.** Peak season starts Friday and someone raises the checkout autoscaler's maximum from 1,000 to 1,200 pods. Thirty new pods come up over the next four minutes. Each one does exactly what it was designed to do: resolves the pricing endpoint list, and opens 800 connections. Pricing's inbound connection count per pod goes from 1,000 to 1,030.

**09:44 — pricing starts logging `accept4: too many open files`.** `RLIMIT_NOFILE` — the per-process cap on open file descriptors, and a socket is a file descriptor — has a soft default of **1024** on a great many systems. Pricing needs descriptors for its database pool, its log file, its metrics socket, and the listening socket itself. The 1,024th inbound connection is the one that ends it. There is nothing in the pricing code that is wrong. There is nothing in the checkout code that is wrong. Somebody typed `1200` in a YAML file.

**09:44:30 — the accept loop starts spinning.** This is the part that turns a limit into an outage. A connection that cannot be accepted **does not go away**: it sits in the kernel accept queue, so epoll keeps reporting the listening socket readable, `accept()` keeps returning `EMFILE`, and the event loop keeps trying. CPU on every pricing pod goes to 100% doing nothing at all. Requests already on established connections now queue behind a loop that is burning the core they need.

**09:45 — the health checks turn on their owner.** Every checkout instance probes every pricing instance every ten seconds. That is `1030 / 10 = 103 probes per second` arriving at each pricing pod — before a single user request. Those probes are connections too, and they now fail. So does Kubernetes' liveness probe, which is also just a connection. The kubelet does exactly what it was told to do and restarts the pod.

**09:46 — the reconnect storm.** A restarted pricing pod comes back with zero connections, and 1,030 checkout instances immediately reconnect, all at once, each with a TLS handshake. It hits `EMFILE` on the way up, fails its probe again, and is restarted again. Meanwhile every other pricing pod inherits the traffic, sees its own connection count climb, and follows it down. The blast radius is the entire pricing fleet, and the trigger was thirty extra pods.

**09:52 — the mitigation.** Somebody raises `RLIMIT_NOFILE` to 65536 and the immediate fire goes out. This is the right emergency action and it is not a fix. It moves the wall from 1,024 clients to 65,536 clients and changes none of the other four numbers: 16.8 GB of socket state across the two fleets, 100 probes per second per backend, 2,667 handshakes per second on every deploy, and a connection count that grows as the **product** of two fleet sizes you intend to keep growing.

The uncomfortable observation from the post-mortem: **the two fleets doubled and the connection count quadrupled.** Go from 500×400 to 1,000×800 and you go from 200,000 connections to 800,000. Go to 2,000×1,600 and it is 3,200,000. That is the κ (kappa) term from Lesson 2 wearing a costume — a cost that grows quadratically in fleet size, which is exactly the shape that makes adding machines stop helping and then start hurting.

The fix is not to go back to a proxy, and it is not a bigger ulimit. It is to notice that **no client needs all 800 backends.** A client needs enough backends to spread its load and survive a few of them dying. Twenty is plenty. Getting from "each client picks twenty" to "and every backend still gets exactly the same number of clients, with nobody coordinating" is the interesting part, and it is the algorithm this lesson builds.

## The Concept

### The discovery problem: instances are ephemeral

Before you can balance across a fleet you have to know what is in it, and the answer changes constantly. Autoscaling adds and removes instances. Deploys replace every one of them. Hardware fails. Spot instances get reclaimed with two minutes' notice. A config file listing IP addresses answers the question "where is service B?" correctly for about as long as it takes to run one deploy.

So you run a **registry** — a service whose entire job is the current membership list — and instances participate in three operations:

- **Register.** "I am `10.2.3.4:8080`, I serve `pricing`, here is my zone and my version." This happens on startup, after the process is actually ready to serve (which is not the same moment as "the process started" — see [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/)).
- **Heartbeat / renew.** "I am still here." Sent on an interval.
- **Deregister.** "I am going away." Sent on shutdown.

Two of those three are easy and one of them decides how your incidents go. **The case that dominates real outages is the instance that dies without deregistering** — `SIGKILL`, a kernel OOM kill, a hypervisor that vanished, a network partition. There is no shutdown hook on the other side of a power cut. Deregistration is a best-effort optimisation; it is never a guarantee.

Which is why registration is a **lease**, not a fact. A lease has a **TTL** (Time To Live): the registry holds the entry for `ttl` seconds after the last renewal and then drops it. A live instance renews often enough that the lease never lapses; a dead instance stops renewing and ages out. The registry never has to detect death, which is good, because detecting death over a network is not a solvable problem — it can only detect the **absence of a renewal**, which is a very different thing that looks the same from the outside.

That distinction produces both of the failure modes worth knowing:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 396" width="100%" style="max-width:840px" role="img" aria-label="Two lease timelines. On the top track a lease with a fifteen second TTL and a five second heartbeat: renewals land at zero, five and ten seconds, the process is killed at twelve and a half seconds, three renewals are then never sent, the lease expires at twenty-five seconds and the client learns at its next two-second poll at twenty-six seconds, leaving a shaded stale window of about thirteen and a half seconds during which traffic still arrives at a dead process. On the bottom track a thirty second TTL with a twenty-five second heartbeat: one lost renewal opens a fifty second gap, so the lease expires at thirty seconds and a perfectly healthy instance receives no traffic until it re-registers at fifty seconds.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A lease does not detect death. It detects a missing renewal.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="42" y="58" font-size="11.5" font-weight="700" fill="#0fa07f">TRACK A · ttl 15s · heartbeat 5s · client poll 2s — the process really died</text>

    <rect x="248" y="102" width="172" height="42" fill="#e0930f" fill-opacity="0.17" stroke="none"/>
    <path d="M90 144 L 470 144" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.6"/>
    <g fill="none" stroke="#0fa07f" stroke-width="2.6">
      <path d="M90 144 L 90 118"/><path d="M153 144 L 153 118"/><path d="M217 144 L 217 118"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.6" stroke-dasharray="3 3" opacity="0.85">
      <path d="M280 144 L 280 137"/><path d="M343 144 L 343 137"/><path d="M407 144 L 407 137"/>
    </g>
    <g stroke="#d64545" stroke-width="2.6" fill="none">
      <path d="M242 84 L 254 96"/><path d="M254 84 L 242 96"/>
    </g>
    <path d="M407 100 L 407 152" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
    <path d="M420 100 L 420 152" fill="none" stroke="#3553ff" stroke-width="2.4"/>
    <text x="334" y="118" text-anchor="middle" font-size="10.5" font-weight="700" fill="#e0930f">STALE WINDOW</text>
    <text x="334" y="134" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">renewals that never came</text>
    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="90" y="160" opacity="0.85">0s</text><text x="153" y="160" opacity="0.85">5s</text>
      <text x="217" y="160" opacity="0.85">10s</text><text x="248" y="80" fill="#d64545" font-weight="700">12.5s</text>
      <text x="404" y="168" fill="#7c5cff" font-weight="700">25s</text><text x="437" y="168" fill="#3553ff" font-weight="700">26s</text>
    </g>

    <g font-size="9.5">
      <rect x="500" y="76" width="10" height="10" rx="2" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/>
      <rect x="500" y="96" width="10" height="10" rx="2" fill="#d64545" fill-opacity="0.35" stroke="#d64545" stroke-width="1.4"/>
      <rect x="500" y="116" width="10" height="10" rx="2" fill="#7c5cff" fill-opacity="0.35" stroke="#7c5cff" stroke-width="1.4"/>
      <rect x="500" y="136" width="10" height="10" rx="2" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/>
      <g fill="currentColor">
        <text x="520" y="85"><tspan font-weight="700">0 / 5 / 10s</tspan>  renewals arrive, lease extended</text>
        <text x="520" y="105"><tspan font-weight="700" fill="#d64545">12.5s</tspan>  SIGKILL. No deregister, no goodbye</text>
        <text x="520" y="125"><tspan font-weight="700" fill="#7c5cff">25.0s</tspan>  lease expires: last renewal 10s + ttl 15s</text>
        <text x="520" y="145"><tspan font-weight="700" fill="#3553ff">26.0s</tspan>  client's next 2s poll drops the endpoint</text>
      </g>
    </g>
    <text x="440" y="184" text-anchor="middle" font-size="10.5" fill="currentColor">Measured over 20,000 random death times: mean stale window <tspan font-weight="700" fill="#e0930f">13.5s</tspan>, worst <tspan font-weight="700" fill="#e0930f">17.0s</tspan>. Every request inside it hits a closed socket.</text>

    <path d="M42 206 L 850 206" fill="none" stroke="currentColor" stroke-width="1" opacity="0.25"/>

    <text x="42" y="234" font-size="11.5" font-weight="700" fill="#d64545">TRACK B · ttl 30s · heartbeat 25s — the process is perfectly healthy</text>

    <rect x="280" y="272" width="127" height="42" fill="#d64545" fill-opacity="0.15" stroke="none"/>
    <path d="M90 314 L 470 314" fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.6"/>
    <g fill="none" stroke="#0fa07f" stroke-width="2.6">
      <path d="M90 314 L 90 288"/><path d="M407 314 L 407 288"/>
    </g>
    <g stroke="#d64545" stroke-width="2.4" fill="none">
      <path d="M242 254 L 254 266"/><path d="M254 254 L 242 266"/>
    </g>
    <path d="M248 314 L 248 270" fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="3 3"/>
    <path d="M280 270 L 280 322" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
    <text x="343" y="292" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">EVICTED WHILE ALIVE</text>
    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="90" y="330" opacity="0.85">0s</text><text x="240" y="250" fill="#d64545" font-weight="700">25s</text>
      <text x="277" y="338" fill="#7c5cff" font-weight="700">30s</text><text x="407" y="330" opacity="0.85">50s</text>
    </g>

    <g font-size="9.5">
      <rect x="500" y="246" width="10" height="10" rx="2" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/>
      <rect x="500" y="266" width="10" height="10" rx="2" fill="#d64545" fill-opacity="0.35" stroke="#d64545" stroke-width="1.4"/>
      <rect x="500" y="286" width="10" height="10" rx="2" fill="#7c5cff" fill-opacity="0.35" stroke="#7c5cff" stroke-width="1.4"/>
      <rect x="500" y="306" width="10" height="10" rx="2" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/>
      <g fill="currentColor">
        <text x="520" y="255"><tspan font-weight="700">0s</tspan>  renewal arrives, lease good until 30s</text>
        <text x="520" y="275"><tspan font-weight="700" fill="#d64545">25s</tspan>  ONE renewal lost — 2% of them are</text>
        <text x="520" y="295"><tspan font-weight="700" fill="#7c5cff">30s</tspan>  lease expires; next gap would be 50s &gt; 30s</text>
        <text x="520" y="315"><tspan font-weight="700" fill="#0fa07f">50s</tspan>  re-registers. It was never unhealthy.</text>
      </g>
    </g>
    <text x="440" y="354" text-anchor="middle" font-size="10.5" fill="currentColor">Measured: <tspan font-weight="700" fill="#d64545">2.857</tspan> bad evictions per healthy instance per hour at hb=25s/ttl=30s — versus <tspan font-weight="700" fill="#0fa07f">0.005</tspan> at hb=5s/ttl=15s.</text>
    <text x="440" y="380" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Long ttl buys a long stale window. A heartbeat close to the ttl makes healthy instances flap. Keep heartbeat &lt;= ttl/3.</text>
  </g>
</svg>
```

**The stale window** is the price of the first one. An instance dies at some point after its last renewal; the registry evicts it `ttl` seconds after that renewal; the client discovers this at its next refresh. With a 15-second TTL, a 5-second heartbeat and a 2-second client poll, the measured mean is **13.5 seconds and the worst case is 17.0 seconds**, and the general shape is:

```text
mean stale window  =  ttl - hb/2 + poll/2
max  stale window  =  ttl + poll
```

Every request sent inside that window goes to a socket nobody is listening on. It is not lost — it fails fast with `ECONNREFUSED` if the host is up and the process is gone, or it hangs until timeout if the host itself vanished, which is much worse. This is why the registry is never your only line of defence: the client's own outlier ejection (Lesson 4) notices a dead endpoint in the time it takes to make two or three failed requests, which is far faster than any lease can expire.

**Spurious eviction** is the price of shortening the TTL to close that window. Renewals travel over a network and are produced by a process that garbage-collects; some fraction of them are late or lost. If the heartbeat interval is close to the TTL, a single lost renewal is enough to open a gap larger than the TTL, and the registry evicts a completely healthy instance. Measured with 2% renewal loss: a 30-second TTL with a 25-second heartbeat produces **2.857 bad evictions per healthy instance per hour** — on a 1,000-instance fleet that is a machine being wrongly removed and re-added roughly every 1.3 seconds, forever, with no error anywhere to explain it. The same 2% loss with a 15-second TTL and a 5-second heartbeat produces **0.005**.

The arithmetic is worth doing once, because it gives you a rule instead of a superstition. The registry evicts you when the gap between two received renewals exceeds the TTL. A gap of `(m+1) × hb` follows `m` consecutive losses, so the number of losses you survive is:

```text
misses tolerated = floor(ttl / hb) - 1
expected bad evictions/hour ≈ (3600 / hb) × loss^(misses_tolerated + 1)
```

> **Rule: heartbeat interval ≤ ttl/3.** That tolerates two consecutive lost renewals, which turns a 2% loss rate into a 0.0008% eviction rate per heartbeat — three orders of magnitude of safety for one division.

Real defaults sit exactly there. Kubernetes' node lease is 40 seconds with a 10-second renewal (a ratio of 4). Netflix's Eureka uses a 90-second lease with a 30-second renewal (a ratio of 3) — safe against loss, and the reason Eureka has a reputation for taking a minute or two to notice anything: the measured mean stale window at those settings, with a 30-second client fetch interval, is **89.9 seconds, and the worst case is 119.8 seconds.**

### DNS as service discovery, and how it lies

The oldest answer to "where is service B?" is a name. Put every instance's address in an A record, let the resolver return them all, done. [Names on the Network: DNS](../../01-networking-and-protocols/06-dns-names-on-the-network/) built the protocol; what matters here is why using it as a service registry produces a specific, recurring, deeply annoying incident: **"we removed that instance an hour ago and it is still getting traffic."**

Four separate reasons, all real.

**1 · The TTL is advisory and half your clients ignore it.** A DNS TTL is a hint the authoritative server publishes; nothing enforces it downstream. Java is the canonical offender: the JVM's `networkaddress.cache.ttl` security property historically defaulted to **`-1` — cache forever** — whenever a `SecurityManager` was installed, on the reasoning that a name-to-address binding is a security-relevant fact that should not change under you. Application code that resolved a hostname at startup got one address for the life of the process. Worse and more common: **a connection pool re-resolves nothing at all.** It resolved once, at connect time, and now holds a keep-alive socket ([Keep-Alive, Pooling & Timeouts](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/)). The TTL could be one second and that socket would still be pinned to the address it was opened against.

Simulated with a 30-second TTL, eight addresses behind the name, and a client population that is 60% TTL-respecting, 30% pinned by a connection pool with a 10-minute maximum lifetime, and 10% caching forever:

```text
        t    clients still resolving it  share of ALL fleet requests
       30s          781 ( 39.1%)            4.88%
      300s          516 ( 25.8%)            3.23%
     3600s          208 ( 10.4%)            1.30%
```

An hour after removal, **10.4% of clients are still sending it traffic — 1.30% of every request the fleet makes.** At a million requests an hour that is 13,000 requests aimed at an address that does not answer. There is no expiry you can set that fixes this, because the clients that are the problem are precisely the ones not honouring expiry.

**2 · A UDP answer has a hard size limit, and your fleet overflows it.** A DNS message over UDP was capped at **512 bytes** by RFC 1035 §2.3.4. Work out what fits. The header is 12 bytes. The question section is the encoded QNAME plus 4 bytes. Each A record in the answer, using the name compression of RFC 1035 §4.1.4, costs a 2-byte pointer + 2 type + 2 class + 4 TTL + 2 rdlength + 4 address = **16 bytes**. So:

```text
  name queried                          QNAME    classic UDP    EDNS(0) typical    EDNS(0) max
                                                   512 bytes         1232 bytes     4096 bytes
  api.internal                            14B         30 As              75 As         254 As
  backend.svc.cluster.local               27B         29 As              74 As         253 As
  checkout.prod.us-east-1.mesh.corp       35B         28 As              73 As         252 As
```

**Twenty-nine instances is enough to overflow the classic limit.** When it does, the server sets the `TC` (truncated) bit and the resolver is supposed to retry the query over TCP (RFC 1035 §4.2.1). EDNS(0) (RFC 6891) lets a resolver advertise a larger UDP buffer — 1232 bytes is the widely-used modern default, which buys you 74 records. Both of these work most of the time, and when they do not, they fail silently: a middlebox that blocks DNS-over-TCP, or a path that drops fragmented UDP, gives the client a *truncated but syntactically valid* answer. Part of your fleet is now invisible to part of your clients, permanently, with no error to correlate.

**3 · There is no health in an A record.** An address record says the name maps to that address. It cannot say *and this one is currently failing 40% of requests*, because the record format has no field for it. DNS-based discovery therefore has exactly one liveness mechanism — removing the record — which puts you back in reason 1.

**4 · There is no weight and no drain state.** You cannot express "send this instance 10% of traffic because it is a new version" or "this instance is finishing in-flight work, send it nothing new." SRV records carry a priority and a weight, which is genuinely better, and almost nothing on the client side reads them. So DNS gives you a set with no gradations: in, or out.

DNS is a magnificent naming system. As a service registry it is a set-membership API with a cache you do not control, a size limit you will exceed, and no way to say anything about a member except that it exists.

### The three places the balancing decision can live

Something has to choose which backend gets this request. There are exactly three places to put that decision, and the choice is a set of trade-offs, not a ranking.

| | **Proxy in the middle** | **In the client library** | **Sidecar next to the client** |
|---|---|---|---|
| Extra network hop | yes, one | none | one, over loopback |
| Blast radius of the balancer | it is a fleet of its own, and its failure is everyone's | none — no shared component to fail | one instance's own sidecar |
| Upgrading the balancing logic | deploy the proxy fleet | **rebuild and redeploy every client, in every language** | deploy the sidecar, restart the pod |
| Who holds the connections | proxy↔backend, pooled and shared | **every client to every backend: N × M** | every sidecar to every backend: still N × M |
| Who knows about health | the proxy, centrally | each client, independently | each sidecar, independently |
| Language cost | zero — it is on the wire | one library per language you use | zero — it is on the wire |

Lesson 4 built the proxy case in detail. What client-side balancing actually buys is the second row: there is no middle box to be the outage, and no hop to pay for. What it costs is the third and fourth rows, and both are usually underestimated.

**The library-version problem is a fleet problem.** The moment your balancing logic lives in a library, a change to it — a bug in the health-check parser, a new load-balancing policy, a fix to the retry budget — requires every service that depends on it to take a dependency bump, rebuild, and redeploy. If you have services in Go, Java, Python and Node, that is four implementations that must agree on behaviour, and in practice they will not. At any given moment your fleet is running five versions of the balancing logic and the oldest one is eighteen months behind. When you need to change balancing behaviour during an incident, you cannot.

**The connection problem is the subject of the rest of this lesson.** It is the fourth row, and it is quadratic.

The sidecar is the compromise that got popular for a reason: the balancing logic is a separate process on the wire, so it upgrades like infrastructure and costs nothing per language, and the extra hop is over loopback rather than the network. It does not solve the connection count — a sidecar per client instance still opens a connection per backend — but it does put that connection pool somewhere you can reason about and configure centrally, which is exactly what makes subsetting deployable.

### The control plane / data plane split

The idea that makes the sidecar model work is a separation of concerns:

- The **control plane** decides *what the routing should be*. It watches the registry, computes the endpoint list, the weights, the drain states, and pushes configuration down.
- The **data plane** *moves the bytes*. It holds the connections and picks a backend for each request using the configuration it was last given.

The split buys you central control with distributed execution: one place to change policy, no central place for a request to pass through. It also creates the single most dangerous failure mode in the whole architecture, which is worth stating as a rule:

> **The data plane must keep working when the control plane is down.**

A mesh whose proxies stop routing when the discovery service is unreachable has taken a convenience and turned it into a global single point of failure — one worse than the load balancer you removed, because it is a dependency of *every* service simultaneously. The justification is a probability argument. The control plane is a stateful, relatively complex service that you deploy and upgrade; its availability will be lower than the aggregate availability of your data plane. If a data-plane request requires a live control plane, then **data-plane availability is bounded above by control-plane availability**, and you have just made your most reliable component inherit the reliability of your least reliable one.

The mechanism is the boring one: **cache the last-known-good endpoint list on disk or in memory, and serve it when the control plane is unreachable.** The measured difference over a 120-second registry outage, during which 5% of backends were actually replaced:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="A control plane and data plane split with the control plane failed. At the top a purple registry box marked unreachable, with its endpoint-push arrows to the clients drawn as broken red dashes. Below, three data planes are compared during the same two minute control-plane outage: a fail-closed client that cannot resolve and therefore sends nothing, measured at zero percent success; a client that serves its last-known-good cached endpoint list, measured at ninety-seven point eight percent; and the same client with outlier ejection, measured at ninety-nine point five percent.">
  <defs>
    <marker id="p11-05-a5" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p11-05-a5g" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p11-05-a5r" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The control plane is down. What does the data plane do?</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="290" y="46" width="300" height="52" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2" stroke-dasharray="7 5"/>
    <text x="440" y="68" text-anchor="middle" font-size="12" font-weight="700" fill="#7c5cff">CONTROL PLANE · the registry</text>
    <text x="440" y="86" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">who exists, who is healthy, who is draining</text>
    <g stroke="#d64545" stroke-width="3.4" fill="none">
      <path d="M604 56 L 628 80"/><path d="M628 56 L 604 80"/>
    </g>
    <text x="646" y="66" font-size="10.5" font-weight="700" fill="#d64545">UNREACHABLE</text>
    <text x="646" y="80" font-size="9" fill="currentColor" opacity="0.85">t = 60s to 180s</text>
    <text x="646" y="94" font-size="9" fill="currentColor" opacity="0.85">no endpoint updates get through</text>

    <g fill="none" stroke="#d64545" stroke-width="1.6" stroke-dasharray="4 5" opacity="0.9">
      <path d="M150 132 L 150 106 L 330 106"/><path d="M440 132 L 440 102"/><path d="M730 132 L 730 106 L 550 106"/>
    </g>
    <g stroke="#d64545" stroke-width="2.4" fill="none">
      <path d="M144 118 L 156 130"/><path d="M156 118 L 144 130"/>
      <path d="M434 118 L 446 130"/><path d="M446 118 L 434 130"/>
      <path d="M724 118 L 736 130"/><path d="M736 118 L 724 130"/>
    </g>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="20" y="140" width="270" height="200" rx="11" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="305" y="140" width="270" height="200" rx="11" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="590" y="140" width="270" height="200" rx="11" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <text x="155" y="162" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">A · FAIL CLOSED</text>
    <text x="440" y="162" text-anchor="middle" font-size="11.5" font-weight="700" fill="#e0930f">B · SERVE STALE</text>
    <text x="725" y="162" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">C · SERVE STALE + EJECT</text>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.85">
      <text x="155" y="178">resolve per request</text>
      <text x="440" y="178">keep last-known-good list</text>
      <text x="725" y="178">stale list + outlier ejection</text>
    </g>

    <g fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="1.7">
      <rect x="90" y="192" width="130" height="30" rx="7"/>
      <rect x="375" y="192" width="130" height="30" rx="7"/>
      <rect x="660" y="192" width="130" height="30" rx="7"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" font-weight="700">
      <text x="155" y="211">client</text><text x="440" y="211">client + cache</text><text x="725" y="211">client + cache</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="5 4">
      <path d="M155 224 L 155 258"/>
    </g>
    <text x="163" y="246" font-size="9" font-weight="700" fill="#d64545">blocked</text>
    <path d="M400 224 L 400 258" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p11-05-a5g)"/>
    <path d="M480 224 L 480 258" fill="none" stroke="#d64545" stroke-width="2.2" marker-end="url(#p11-05-a5r)"/>
    <path d="M685 224 L 685 258" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p11-05-a5g)"/>
    <path d="M765 224 L 765 244" fill="none" stroke="#7f7f7f" stroke-width="2.2" stroke-dasharray="4 4"/>
    <g stroke="#7f7f7f" stroke-width="2" fill="none">
      <path d="M759 246 L 771 258"/><path d="M771 246 L 759 258"/>
    </g>
    <text x="782" y="248" font-size="8.5" font-weight="700" fill="#7f7f7f">ejected</text>

    <g stroke-width="1.7">
      <rect x="120" y="262" width="70" height="28" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
      <rect x="365" y="262" width="70" height="28" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="445" y="262" width="70" height="28" rx="7" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
      <rect x="650" y="262" width="70" height="28" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="730" y="262" width="70" height="28" rx="7" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="155" y="280" opacity="0.55">backends</text>
      <text x="400" y="280">alive</text><text x="480" y="280">moved</text>
      <text x="685" y="280">alive</text><text x="765" y="280">moved</text>
    </g>

    <g text-anchor="middle">
      <text x="155" y="316" font-size="18" font-weight="700" fill="#d64545">0.00%</text>
      <text x="440" y="316" font-size="18" font-weight="700" fill="#e0930f">97.81%</text>
      <text x="725" y="316" font-size="18" font-weight="700" fill="#0fa07f">99.48%</text>
      <text x="155" y="332" font-size="8.5" fill="currentColor" opacity="0.85">144,000 of 144,000 failed</text>
      <text x="440" y="332" font-size="8.5" fill="currentColor" opacity="0.85">3,153 failed — only the churn</text>
      <text x="725" y="332" font-size="8.5" fill="currentColor" opacity="0.85">755 failed — three strikes, then out</text>
    </g>
    <text x="440" y="358" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">measured success rate during the 120-second outage · 600 clients · 5% of backends replaced while the registry was blind</text>

    <rect x="20" y="372" width="840" height="34" rx="8" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="440" y="394" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">RULE: the data plane must keep routing when the control plane is gone. Cache last-known-good and serve stale.</text>
  </g>
</svg>
```

Fail-closed delivers **0.00%**. Serve-stale delivers **97.81%** — and the 2.19% it loses is not a flaw in serve-stale, it is exactly the churn that happened while the client was blind, which no policy could have known about. Adding outlier ejection (Lesson 4) on top takes it to **99.48%**, because after three consecutive failures the client removes the moved backend from its own view without asking anyone. That is the composition worth remembering: **serve-stale handles the control plane being gone; outlier ejection handles the staleness.** Neither needs the registry.

The cost of serve-stale is honest and should be said: you will send traffic to instances that no longer exist, and you will not send traffic to instances that were added. If the outage is long and your fleet churns fast, the stale view degrades. That is a much better failure than a total one, and there is a bounded version of the compromise — expire the cache after some multiple of the normal refresh interval, then start failing — but pick that multiple in hours, not seconds.

### The N × M explosion, quantified

Now the arithmetic from *The Problem*, done properly. Every client holds one connection to every backend. The cost is not one number; it is five, and they scale differently:

```text
  connections            = N × M                  quadratic
  inbound conns/backend  = N                      linear in the CALLER fleet
  memory                 = N × M × bytes_per_conn quadratic
  health probes/backend  = N / probe_period       linear in the CALLER fleet
  reconnects on deploy   = N × M / deploy_window  quadratic
```

Assume a deliberately conservative floor of 12 KB per connection on the backend and 10 KB on the client — a `struct sock`, minimum receive and send buffers, TLS session state, HTTP/2 stream bookkeeping. A TLS-terminated HTTP/2 connection with default 64 KB flow-control windows is several times that, so treat every memory figure below as a lower bound:

```text
          N        M        N x M   inbound       mem      fleet          fds   probes/s  handshakes/s
    clients backends        conns  /backend  /backend     memory     /backend   /backend     on deploy
        100       80        8,000       100     1.2MB    171.9MB           ok         10            27
        500      400      200,000       500     5.9MB      4.2GB           ok         50           667
      1,000      800      800,000     1,000    11.7MB     16.8GB           ok        100         2,667
      2,000    1,600    3,200,000     2,000    23.4MB     67.1GB raise ulimit        200        10,667
      5,000    4,000   20,000,000     5,000    58.6MB    419.6GB raise ulimit        500        66,667
```

Read the `fds` column first, because it is the one that produced the outage: at 1,000 clients you are at 1,000 inbound descriptors per backend, and the common soft default is 1,024. That is not a margin, it is a coincidence.

Then read the last two columns, because they are the ones people forget. **A health check is a request.** At 1,000 clients probing every backend every ten seconds, each backend answers 100 probes per second of pure overhead — and if you tighten the probe interval to get faster failure detection, you multiply it. **A deploy is a reconnect storm.** Replacing the callee fleet over a five-minute rolling window re-establishes all 800,000 connections, which is 2,667 TLS handshakes per second, fleet-wide, sustained, every single release.

And then read the growth. Doubling both fleets quadruples everything quadratic:

```text
      500 x    400 =      200,000 connections   (   4.2GB,       667 handshakes/s on deploy)
    1,000 x    800 =      800,000 connections   (  16.8GB,     2,667 handshakes/s on deploy)
    2,000 x  1,600 =    3,200,000 connections   (  67.1GB,    10,667 handshakes/s on deploy)
    5,000 x  4,000 =   20,000,000 connections   ( 419.6GB,    66,667 handshakes/s on deploy)
```

Lesson 2 introduced the Universal Scalability Law's κ term — the **coherency** cost, the part that grows with the *square* of the number of participants and is the reason throughput does not merely plateau but goes **retrograde**. This table is that term with a unit you can read out of `ss -s` on a production box. Each new client instance you add makes every backend a little more expensive to run, so the marginal value of a machine falls, and past some fleet size adding a machine subtracts throughput.

### Subsetting: each client talks to only k backends

The observation that dissolves the whole problem: **a client does not need every backend.** It needs enough to spread its own load, and enough that losing a few does not cost it a large fraction of its capacity. For most services that number is between 10 and 40, and it does not have to grow when the fleet grows.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Two topologies side by side. On the left, a full mesh: six clients each connected to every one of six backends, thirty-six edges, labelled with the real fleet numbers of one thousand clients by eight hundred backends giving eight hundred thousand connections and sixteen point eight gigabytes of socket state. On the right, the same twelve nodes with deterministic subsetting at k equals two: each client keeps only two connections, twelve edges, and every backend still receives exactly two clients, labelled twenty thousand connections and four hundred and thirty megabytes, two and a half percent of the mesh.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same fleet, same balancing, 40x fewer sockets</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="20" y="44" width="410" height="292" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545"/>
      <rect x="450" y="44" width="410" height="292" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    </g>
    <text x="225" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">FULL MESH — every client to every backend</text>
    <text x="655" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">DETERMINISTIC SUBSET — k = 2</text>

    <g stroke="#7f7f7f" stroke-width="0.9" opacity="0.55" fill="none">
      <path d="M55 118 L 55 232"/><path d="M55 118 L 123 232"/><path d="M55 118 L 191 232"/><path d="M55 118 L 259 232"/><path d="M55 118 L 327 232"/><path d="M55 118 L 395 232"/>
      <path d="M123 118 L 55 232"/><path d="M123 118 L 123 232"/><path d="M123 118 L 191 232"/><path d="M123 118 L 259 232"/><path d="M123 118 L 327 232"/><path d="M123 118 L 395 232"/>
      <path d="M191 118 L 55 232"/><path d="M191 118 L 123 232"/><path d="M191 118 L 191 232"/><path d="M191 118 L 259 232"/><path d="M191 118 L 327 232"/><path d="M191 118 L 395 232"/>
      <path d="M259 118 L 55 232"/><path d="M259 118 L 123 232"/><path d="M259 118 L 191 232"/><path d="M259 118 L 259 232"/><path d="M259 118 L 327 232"/><path d="M259 118 L 395 232"/>
      <path d="M327 118 L 55 232"/><path d="M327 118 L 123 232"/><path d="M327 118 L 191 232"/><path d="M327 118 L 259 232"/><path d="M327 118 L 327 232"/><path d="M327 118 L 395 232"/>
      <path d="M395 118 L 55 232"/><path d="M395 118 L 123 232"/><path d="M395 118 L 191 232"/><path d="M395 118 L 259 232"/><path d="M395 118 L 327 232"/><path d="M395 118 L 395 232"/>
    </g>

    <g stroke="#3553ff" stroke-width="1.9" opacity="0.85" fill="none">
      <path d="M485 118 L 485 232"/><path d="M485 118 L 553 232"/>
      <path d="M553 118 L 621 232"/><path d="M553 118 L 689 232"/>
      <path d="M621 118 L 757 232"/><path d="M621 118 L 825 232"/>
      <path d="M689 118 L 485 232"/><path d="M689 118 L 621 232"/>
      <path d="M757 118 L 553 232"/><path d="M757 118 L 757 232"/>
      <path d="M825 118 L 689 232"/><path d="M825 118 L 825 232"/>
    </g>

    <g fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.8">
      <circle cx="55" cy="110" r="13"/><circle cx="123" cy="110" r="13"/><circle cx="191" cy="110" r="13"/><circle cx="259" cy="110" r="13"/><circle cx="327" cy="110" r="13"/><circle cx="395" cy="110" r="13"/>
      <circle cx="485" cy="110" r="13"/><circle cx="553" cy="110" r="13"/><circle cx="621" cy="110" r="13"/><circle cx="689" cy="110" r="13"/><circle cx="757" cy="110" r="13"/><circle cx="825" cy="110" r="13"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.8">
      <circle cx="55" cy="240" r="13"/><circle cx="123" cy="240" r="13"/><circle cx="191" cy="240" r="13"/><circle cx="259" cy="240" r="13"/><circle cx="327" cy="240" r="13"/><circle cx="395" cy="240" r="13"/>
      <circle cx="485" cy="240" r="13"/><circle cx="553" cy="240" r="13"/><circle cx="621" cy="240" r="13"/><circle cx="689" cy="240" r="13"/><circle cx="757" cy="240" r="13"/><circle cx="825" cy="240" r="13"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle" opacity="0.9">
      <text x="55" y="113">C</text><text x="123" y="113">C</text><text x="191" y="113">C</text><text x="259" y="113">C</text><text x="327" y="113">C</text><text x="395" y="113">C</text>
      <text x="485" y="113">C</text><text x="553" y="113">C</text><text x="621" y="113">C</text><text x="689" y="113">C</text><text x="757" y="113">C</text><text x="825" y="113">C</text>
      <text x="55" y="243">B</text><text x="123" y="243">B</text><text x="191" y="243">B</text><text x="259" y="243">B</text><text x="327" y="243">B</text><text x="395" y="243">B</text>
      <text x="485" y="243">B</text><text x="553" y="243">B</text><text x="621" y="243">B</text><text x="689" y="243">B</text><text x="757" y="243">B</text><text x="825" y="243">B</text>
    </g>
    <g fill="currentColor" font-size="9" opacity="0.75">
      <text x="32" y="92">clients</text><text x="462" y="92">clients</text>
      <text x="32" y="270">backends</text><text x="462" y="270">backends</text>
    </g>

    <text x="225" y="292" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">6 x 6 = 36 edges drawn · every backend holds 6 inbound</text>
    <text x="655" y="292" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">6 x 2 = 12 edges drawn · every backend holds exactly 2</text>
    <text x="225" y="312" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">connections grow as N x M — quadratic in fleet size</text>
    <text x="655" y="312" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">connections grow as N x k — linear in fleet size</text>
    <text x="225" y="328" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">add ONE client: +800 sockets, +80 probes/s</text>
    <text x="655" y="328" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">add ONE client: +20 sockets, +2 probes/s</text>

    <g fill="currentColor" font-size="9.5">
      <text x="30" y="366" font-weight="700" opacity="0.7">AT THE REAL FLEET SIZE FROM THE PROBLEM — N = 1,000 clients, M = 800 backends</text>
      <text x="30" y="386"><tspan font-weight="700" fill="#d64545">full mesh</tspan>  800,000 connections · 16.8 GB of socket state · 100 health probes/s per backend · 2,667 handshakes/s on deploy</text>
      <text x="30" y="404"><tspan font-weight="700" fill="#0fa07f">k = 20   </tspan>  20,000 connections (2.5%) · 429.7 MB · 2.5 probes/s per backend · 67 handshakes/s on deploy</text>
    </g>
    <text x="440" y="424" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The mesh is not wrong. It is quadratic, and it grew past the size where quadratic is affordable.</text>
  </g>
</svg>
```

Fix `k` and the arithmetic changes character. Connections become `N × k`, which is **linear in the caller fleet and completely independent of the callee fleet**. At N=1000, M=800, k=20: 20,000 connections instead of 800,000 — **2.5%** — 429.7 MB instead of 16.8 GB, 2.5 health probes per second per backend instead of 100, and 67 handshakes per second on deploy instead of 2,667.

The question is which k backends each client picks, and the naive answer has a real problem.

**Random subsetting** — every client independently samples k backends uniformly — is one line of code and gives you the right *expected* load: each backend expects `N × k / M` clients. But independent random choices are **balls in bins**, the same structure Lesson 3 measured for random load balancing, and the spread is the binomial's, which is not small. Measured across four fleet shapes:

```text
       N     M    k  ideal  algorithm         min   max   stddev  max/ideal  idle backends
      60   120    6    3.0  random              0     8     1.64      2.67x              6
     200   120   12   20.0  random             10    30     4.43      1.50x              0
     600   120   10   50.0  random             32    68     6.81      1.36x              0
    1000   800   20   25.0  random             13    44     4.94      1.76x              0
```

Two things go wrong. The mild one is imbalance: at the real fleet size, one backend gets **44 clients where the ideal is 25 — 1.76× the mean load**, so it saturates while others idle, and your fleet's usable capacity is set by the unluckiest machine. The severe one shows up when the fleet is sparse, meaning `N × k / M` is small: at 60 clients over 120 backends with k=6, **six backends received zero clients**. They are running. They are healthy. They are in the registry. They are passing their probes. And no client will ever send them a request, because nobody happened to pick them.

**Deterministic subsetting** (Beyer et al., *Site Reliability Engineering*, O'Reilly, 2016, ch. 20) fixes this by making the choices **dependent** instead of independent — without any communication between clients. The idea in one sentence: *number the clients, group them into rounds of `M/k` clients, and have each round deal out the whole shuffled backend list in disjoint slices.*

```python
def subset(backends: list[str], client_id: int, subset_size: int) -> list[str]:
    subset_count = len(backends) // subset_size   # clients per round
    round_id     = client_id // subset_count      # which round am I in?
    shuffled     = list(backends)
    random.Random(round_id).shuffle(shuffled)     # SEEDED BY THE ROUND
    subset_id    = client_id % subset_count       # my slice within the round
    start        = subset_id * subset_size
    return shuffled[start:start + subset_size]
```

Everything hinges on the seed. `random.Random(round_id)` means every client in round 7 produces the *identical* shuffle — no coordination, no gossip, no shared state, just the same seed producing the same permutation. Within that round, client `subset_id` takes slice `[subset_id·k, subset_id·k + k)`. The slices are disjoint and there are exactly `M/k` of them, so **one round covers the backend list exactly once**. After R complete rounds, every backend is in exactly R subsets. Trace it with numbers small enough to check by hand:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 372" width="100%" style="max-width:840px" role="img" aria-label="The deterministic subsetting algorithm traced by hand with twelve backends and a subset size of three, giving four clients per round. Round zero shuffles the backend list with seed zero into 1 9 8 5 10 2 3 7 4 0 11 6 and hands consecutive slices of three to clients zero through three. Round one shuffles the same list with seed one into 7 11 0 8 5 6 3 10 4 1 9 2 and hands slices to clients four through seven. A tally strip underneath shows every one of the twelve backends holding exactly two clients.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Deterministic subsetting: one shuffle per round, then disjoint slices</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="48" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">M = 12 backends · k = 3 · subset_count = M / k = <tspan font-weight="700">4 clients per round</tspan> · round = client_id / subset_count</text>

    <text x="30" y="82" font-size="11" font-weight="700" fill="#7c5cff">ROUND 0 · shuffle(backends, seed = 0) →  clients 0-3</text>
    <g font-size="9.5" font-weight="700" fill="#3553ff" text-anchor="middle">
      <text x="165" y="102">client 0</text><text x="337" y="102">client 1</text><text x="509" y="102">client 2</text><text x="681" y="102">client 3</text>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.4" opacity="0.8">
      <path d="M90 108 L 90 106 L 240 106 L 240 108"/><path d="M262 108 L 262 106 L 412 106 L 412 108"/>
      <path d="M434 108 L 434 106 L 584 106 L 584 108"/><path d="M606 108 L 606 106 L 756 106 L 756 108"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6">
      <rect x="90" y="110" width="46" height="28" rx="5"/><rect x="140" y="110" width="46" height="28" rx="5"/><rect x="190" y="110" width="46" height="28" rx="5"/>
      <rect x="262" y="110" width="46" height="28" rx="5"/><rect x="312" y="110" width="46" height="28" rx="5"/><rect x="362" y="110" width="46" height="28" rx="5"/>
      <rect x="434" y="110" width="46" height="28" rx="5"/><rect x="484" y="110" width="46" height="28" rx="5"/><rect x="534" y="110" width="46" height="28" rx="5"/>
      <rect x="606" y="110" width="46" height="28" rx="5"/><rect x="656" y="110" width="46" height="28" rx="5"/><rect x="706" y="110" width="46" height="28" rx="5"/>
    </g>
    <g fill="currentColor" font-size="11.5" font-weight="700" text-anchor="middle">
      <text x="113" y="129">1</text><text x="163" y="129">9</text><text x="213" y="129">8</text>
      <text x="285" y="129">5</text><text x="335" y="129">10</text><text x="385" y="129">2</text>
      <text x="457" y="129">3</text><text x="507" y="129">7</text><text x="557" y="129">4</text>
      <text x="629" y="129">0</text><text x="679" y="129">11</text><text x="729" y="129">6</text>
    </g>
    <text x="778" y="129" font-size="9" fill="currentColor" opacity="0.75">backend ids</text>

    <text x="30" y="172" font-size="11" font-weight="700" fill="#7c5cff">ROUND 1 · shuffle(backends, seed = 1) →  clients 4-7</text>
    <g font-size="9.5" font-weight="700" fill="#3553ff" text-anchor="middle">
      <text x="165" y="192">client 4</text><text x="337" y="192">client 5</text><text x="509" y="192">client 6</text><text x="681" y="192">client 7</text>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.4" opacity="0.8">
      <path d="M90 198 L 90 196 L 240 196 L 240 198"/><path d="M262 198 L 262 196 L 412 196 L 412 198"/>
      <path d="M434 198 L 434 196 L 584 196 L 584 198"/><path d="M606 198 L 606 196 L 756 196 L 756 198"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6">
      <rect x="90" y="200" width="46" height="28" rx="5"/><rect x="140" y="200" width="46" height="28" rx="5"/><rect x="190" y="200" width="46" height="28" rx="5"/>
      <rect x="262" y="200" width="46" height="28" rx="5"/><rect x="312" y="200" width="46" height="28" rx="5"/><rect x="362" y="200" width="46" height="28" rx="5"/>
      <rect x="434" y="200" width="46" height="28" rx="5"/><rect x="484" y="200" width="46" height="28" rx="5"/><rect x="534" y="200" width="46" height="28" rx="5"/>
      <rect x="606" y="200" width="46" height="28" rx="5"/><rect x="656" y="200" width="46" height="28" rx="5"/><rect x="706" y="200" width="46" height="28" rx="5"/>
    </g>
    <g fill="currentColor" font-size="11.5" font-weight="700" text-anchor="middle">
      <text x="113" y="219">7</text><text x="163" y="219">11</text><text x="213" y="219">0</text>
      <text x="285" y="219">8</text><text x="335" y="219">5</text><text x="385" y="219">6</text>
      <text x="457" y="219">3</text><text x="507" y="219">10</text><text x="557" y="219">4</text>
      <text x="629" y="219">1</text><text x="679" y="219">9</text><text x="729" y="219">2</text>
    </g>
    <text x="778" y="219" font-size="9" fill="currentColor" opacity="0.75">same list,</text>
    <text x="778" y="230" font-size="9" fill="currentColor" opacity="0.75">new order</text>

    <path d="M30 250 L 850 250" fill="none" stroke="currentColor" stroke-width="1" opacity="0.25"/>
    <text x="30" y="272" font-size="11" font-weight="700" fill="#0fa07f">TALLY — clients holding each backend after both rounds</text>

    <g fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6">
      <rect x="90" y="282" width="46" height="26" rx="5"/><rect x="146" y="282" width="46" height="26" rx="5"/><rect x="202" y="282" width="46" height="26" rx="5"/>
      <rect x="258" y="282" width="46" height="26" rx="5"/><rect x="314" y="282" width="46" height="26" rx="5"/><rect x="370" y="282" width="46" height="26" rx="5"/>
      <rect x="426" y="282" width="46" height="26" rx="5"/><rect x="482" y="282" width="46" height="26" rx="5"/><rect x="538" y="282" width="46" height="26" rx="5"/>
      <rect x="594" y="282" width="46" height="26" rx="5"/><rect x="650" y="282" width="46" height="26" rx="5"/><rect x="706" y="282" width="46" height="26" rx="5"/>
    </g>
    <g fill="currentColor" font-size="11.5" font-weight="700" text-anchor="middle">
      <text x="113" y="300">2</text><text x="169" y="300">2</text><text x="225" y="300">2</text><text x="281" y="300">2</text>
      <text x="337" y="300">2</text><text x="393" y="300">2</text><text x="449" y="300">2</text><text x="505" y="300">2</text>
      <text x="561" y="300">2</text><text x="617" y="300">2</text><text x="673" y="300">2</text><text x="729" y="300">2</text>
    </g>
    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.75">
      <text x="113" y="320">B0</text><text x="169" y="320">B1</text><text x="225" y="320">B2</text><text x="281" y="320">B3</text>
      <text x="337" y="320">B4</text><text x="393" y="320">B5</text><text x="449" y="320">B6</text><text x="505" y="320">B7</text>
      <text x="561" y="320">B8</text><text x="617" y="320">B9</text><text x="673" y="320">B10</text><text x="729" y="320">B11</text>
    </g>
    <text x="778" y="300" font-size="9" font-weight="700" fill="#0fa07f">min = max = 2</text>

    <text x="440" y="344" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">One round covers the list exactly once: after R rounds every backend holds exactly R clients, with no coordination at all.</text>
    <text x="440" y="362" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Measured at N=1000, M=800, k=20: <tspan font-weight="700" fill="#0fa07f">min 25, max 25, stddev 0.00</tspan> — versus random subsetting's <tspan font-weight="700" fill="#e0930f">min 13, max 44, stddev 4.94</tspan>.</text>
  </g>
</svg>
```

That is the entire mechanism. The load result follows directly:

```text
       N     M    k  ideal  algorithm         min   max   stddev  max/ideal  idle backends
      60   120    6    3.0  deterministic       3     3     0.00      1.00x              0
     200   120   12   20.0  deterministic      20    20     0.00      1.00x              0
     600   120   10   50.0  deterministic      50    50     0.00      1.00x              0
    1000   800   20   25.0  deterministic      25    25     0.00      1.00x              0
     997   800   20   24.9  deterministic      24    25     0.26      1.00x              0
```

**Standard deviation zero.** Not "low" — zero, because it is a partition, not a sample. The last row is the only interesting case: when the client count is not a whole number of rounds, the final partial round covers some of the list and not the rest, so counts differ by **exactly one**. That is the worst it ever gets.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="A measured grouped bar chart of how many backends received each number of clients, for sixty clients over one hundred and twenty backends with a subset size of six, so the ideal is three clients per backend. Random subsetting spreads the backends across zero to eight clients each: six backends receive zero clients, fifteen receive one, twenty-seven receive two, thirty receive three, twenty-two receive four, thirteen receive five, two receive six, four receive seven and one receives eight. Deterministic subsetting puts all one hundred and twenty backends in a single bar at exactly three clients.">
  <defs>
    <marker id="p11-05-a4" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Measured: where the clients actually landed (N=60, M=120, k=6)</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.18">
      <path d="M90 242.5 L 640 242.5"/><path d="M90 185 L 640 185"/><path d="M90 127.5 L 640 127.5"/><path d="M90 70 L 640 70"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.6">
      <path d="M90 300 L 640 300"/><path d="M90 300 L 90 66"/>
    </g>
    <path d="M304 62 L 304 306" fill="none" stroke="#7c5cff" stroke-width="1.6" stroke-dasharray="5 4" opacity="0.85"/>

    <g fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-width="1.6">
      <rect x="95" y="288.5" width="24" height="11.5"/>
      <rect x="156" y="271.2" width="24" height="28.8"/>
      <rect x="217" y="248.2" width="24" height="51.8"/>
      <rect x="278" y="242.5" width="24" height="57.5"/>
      <rect x="339" y="257.8" width="24" height="42.2"/>
      <rect x="400" y="275.1" width="24" height="24.9"/>
      <rect x="461" y="296.2" width="24" height="3.8"/>
      <rect x="522" y="292.3" width="24" height="7.7"/>
      <rect x="583" y="298.1" width="24" height="1.9"/>
    </g>
    <rect x="95" y="288.5" width="24" height="11.5" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="2"/>

    <rect x="306" y="70" width="24" height="230" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="1.8"/>

    <g fill="currentColor" font-size="8.5" text-anchor="middle" opacity="0.9">
      <text x="107" y="282">6</text><text x="168" y="267">15</text><text x="229" y="244">27</text><text x="290" y="238">30</text>
      <text x="351" y="253">22</text><text x="412" y="271">13</text><text x="473" y="292">2</text><text x="534" y="288">4</text><text x="595" y="294">1</text>
    </g>
    <text x="318" y="62" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">120 — all of them</text>

    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="82" y="304">0</text><text x="82" y="246">30</text><text x="82" y="189">60</text><text x="82" y="131">90</text><text x="82" y="74">120</text>
    </g>
    <text x="40" y="185" font-size="10" fill="currentColor" opacity="0.85" transform="rotate(-90 40 185)" text-anchor="middle">backends</text>

    <g fill="currentColor" font-size="10" text-anchor="middle" opacity="0.9">
      <text x="107" y="318" fill="#d64545" font-weight="700">0</text><text x="168" y="318">1</text><text x="229" y="318">2</text><text x="290" y="318">3</text>
      <text x="351" y="318">4</text><text x="412" y="318">5</text><text x="473" y="318">6</text><text x="534" y="318">7</text><text x="595" y="318">8</text>
    </g>
    <text x="365" y="338" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">clients per backend  ·  ideal = 3.0</text>
    <text x="304" y="52" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">ideal</text>

    <g fill="currentColor" font-size="9.5">
      <text x="105" y="170" font-weight="700" fill="#d64545">6 backends got ZERO clients.</text>
      <text x="105" y="184" opacity="0.9">Provisioned, paid for, and</text>
      <text x="105" y="198" opacity="0.9">unreachable by any client.</text>
    </g>
    <path d="M152 206 L 124 285" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-05-a4)"/>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="660" y="70" width="200" height="86" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="660" y="170" width="200" height="86" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="674" y="90" font-size="11" font-weight="700" fill="#e0930f">RANDOM SUBSET</text>
      <text x="674" y="108">min 0   max 8</text>
      <text x="674" y="124">stddev 1.64</text>
      <text x="674" y="140" font-weight="700" fill="#d64545">6 idle · max is 2.67x ideal</text>
      <text x="674" y="190" font-size="11" font-weight="700" fill="#0fa07f">DETERMINISTIC</text>
      <text x="674" y="208">min 3   max 3</text>
      <text x="674" y="224">stddev 0.00</text>
      <text x="674" y="240" font-weight="700" fill="#0fa07f">0 idle · max is 1.00x ideal</text>
    </g>
    <text x="760" y="284" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">Both use exactly</text>
    <text x="760" y="298" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">60 x 6 = 360 connections.</text>
    <text x="760" y="316" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">The cost is identical.</text>

    <text x="440" y="368" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Random subsetting is balls-in-bins: independent choices, so the spread is the binomial's, not zero.</text>
    <text x="440" y="386" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Making the choices DEPENDENT — one shuffled round partitions the backend list — collapses the distribution onto the ideal.</text>
  </g>
</svg>
```

Note what did *not* change: both algorithms open exactly `N × k` connections. The random one is not cheaper. Deterministic subsetting is strictly better for the identical cost, which is unusual enough to be worth saying out loud.

Two properties make it deployable. It needs **no communication** — a client computes its subset from three numbers it already has (its own id, the backend list, and k), so the algorithm survives the control plane being down. And it is **stable**: a client's subset changes only when the backend list changes, so adding one client does not reshuffle anybody else's connections. That second property is why you must think about how `client_id` is assigned — a stable ordinal index (a StatefulSet ordinal, a slot from the registry, a hash of the pod name into a dense range) is the right shape. Assigning ids randomly on each restart works but gives up the stability.

The honest caveat: when the **backend** list changes, the shuffles change, and subsets churn. Removing one backend from a list of 800 will reshuffle every round and move a substantial fraction of connections. Production implementations soften this with a consistent-hashing variant instead of a plain shuffle — Envoy's deterministic aperture and gRPC's `RING_HASH` both do a version of this — but the plain algorithm above is the one that makes the property visible, and it is what the SRE book describes.

### Choosing k, and what it costs you

Subsetting buys memory with blast radius, and the exchange rate is set by k. Small k means fewer connections, but it also means each surviving backend in your subset absorbs a larger share when one dies — and, more importantly, it means the *variance* of what an individual client experiences goes up.

The fleet-wide loss is the same regardless of k: if 20% of backends die, 20% of capacity is gone and the survivors each absorb +25%, whether every client sees all 800 or only 3. What k determines is **whether some unlucky client loses far more than 20%.** Measured over 40 independent kill draws at N=1000, M=800:

```text
  --- 160 of 800 backends dead (20%) — survivors must absorb +25% each ---
      k      conns  vs mesh    clients <50%   worst  clients at 0   worst client
                            of subset (avg)    draw    (any draw)           kept
      3      3,000    0.4%           103.0     121           338            0%
      5      5,000    0.6%            56.9      67            14            0%
     10     10,000    1.2%             5.4      11             0           20%
     20     20,000    2.5%             0.5       2             0           40%
     40     40,000    5.0%             0.0       0             0           52%
     80     80,000   10.0%             0.0       0             0           62%
    800    800,000  100.0%             0.0       0             0           80%
```

Read the `clients at 0` column. At **k=3**, across 40 draws there were **338 client-draws where a client's entire subset was dead** — that client is now serving zero traffic and emitting 100% errors while 640 healthy backends sit idle. At **k=10** it never happens, and at k=20 essentially no client drops below half its capacity. The connection saving between k=3 and k=20 is 0.4% versus 2.5% of the mesh — which is to say, **nothing**. You are arguing over 17,000 connections out of 800,000 to buy away your worst failure mode.

The closed form behind that column makes the shape clear. A client loses everything only if **all k** of its backends are dead, so for a dead fraction `f` the probability is `f^k` — and the program prints it next to the measurement:

```text
  why that column collapses: P(a client's WHOLE subset is dead) = f^k.
  at f = 20% dead:
        k           f^k    as a percent           1 client in expected at N=1000
        3     8.000e-03            0.8%                   125                  8
        5     3.200e-04          0.032%                 3,125               0.32
       10     1.024e-07      1.024e-05%             9,765,625           0.000102
       20     1.049e-14    1.04858e-12%    95,367,431,640,625           1.05e-11
```

**Each +1 on k divides the risk by five**, because that is what multiplying by `f = 0.2` does. Read the last column against the measurement above it: at k=3 the formula expects **8 stranded clients per 1,000 per draw**, and 40 draws produced 338 — an average of 8.45, which is the arithmetic landing where it should. At k=10 it expects 0.000102 clients per draw, and 40 draws produced none. That is the asymmetry that decides the knob: **the failure disappears exponentially in k while the connections grow only linearly.**

> **Rule of thumb: k between 20 and 40 for most services.** Below 10 the tail failure is real; above 40 you are paying for connections that buy no additional smoothing. Start at 20, and raise it only if you measure imbalance you can attribute to too few connections — never lower it to save memory unless you have done the `f^k` arithmetic for your realistic `f`.

Two constraints ride along with that number. **k must be at least as large as the number of failure domains you want to survive** — if you have three availability zones and k=2, some client's whole subset can be in one zone (Lesson 9 makes this precise). And **N × k must be comfortably larger than M**, or you are back to idle backends: `N × k / M` is the clients-per-backend figure, and if it is below about 2 you have very little smoothing left even with a perfect partition.

The last piece is what happens *inside* the subset, and the good news is: nothing changes. Lesson 3's **P2C** (power of two choices — sample two endpoints at random, send to the one with fewer in-flight requests) over 20 endpoints behaves exactly like P2C over 20 endpoints, because it is. **Subsetting decides which backends you can see; the balancing algorithm decides which one gets this request.** They are orthogonal layers and they compose without interacting. The same is true of outlier ejection: eject a bad backend from a subset of 20 and you are balancing over 19, which is fine. The only thing you must not do is let ejection empty the subset — cap ejection at some fraction (Envoy's `max_ejection_percent` defaults to 10%) so a bad health-check signal cannot leave a client with nowhere to send.

### Draining, not deleting

Everything above assumes an instance leaves the fleet cleanly. Making that true is a sequence, and the ordering is the whole content:

1. **Mark draining.** The instance tells the registry (or fails its *readiness* probe, which is the Kubernetes spelling of the same statement) that it should receive no new requests. It keeps serving the ones it already has.
2. **Wait for propagation.** This is the step people skip. The control plane has to notice, recompute, and push; the clients have to receive it; connection pools have to stop handing out that endpoint. That takes at least one client refresh interval and usually a few seconds more. **If you shut down before propagation completes, "draining" was a comment, not a mechanism.**
3. **Finish in-flight work.** Let open requests complete, bounded by a timeout.
4. **Close connections cleanly.** For HTTP/2 and gRPC, send `GOAWAY` so the client knows to open a new connection elsewhere instead of retrying on a socket that is about to disappear. A `GOAWAY` is the difference between a graceful migration and a burst of `ECONNRESET`.
5. **Deregister, then exit.**

[Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) builds this shutdown path in detail, including the `SIGTERM` handling and the `preStop` sleep that buys step 2 its propagation time. What is specific to this lesson is *why* step 2 needs longer than it seems: with client-side balancing there is no single proxy to update. There are N clients, each with its own cached view and its own refresh timer, and the drain is not complete until the slowest of them has noticed. Your `terminationGracePeriodSeconds` needs to exceed **client refresh interval + longest in-flight request**, not just the second term.

And it is worth restating the reason all of this is best-effort: **the graceful path only exists when the process gets to run code.** The lease is what covers the other case, and the stale window from the top of this section is the residue you can never remove. Design for both: drain cleanly when you can, and keep the lease short enough — and the client's outlier ejection fast enough — that the ungraceful case is survivable.

## Build It

[`code/discovery_and_subsetting.py`](code/discovery_and_subsetting.py) is six numbered arguments. Standard library only, seeded, about 9 seconds. Four parts are worth reading before you run it.

**The subsetting algorithm** is nine lines, and the comment on the seed is the whole idea:

```python
def deterministic_subset(client_id: int, backends: list[int], k: int) -> list[int]:
    subset_count = len(backends) // k
    round_id = client_id // subset_count
    shuffled = list(backends)
    random.Random(round_id).shuffle(shuffled)   # every client in this round agrees
    subset_id = client_id % subset_count
    start = subset_id * k
    return shuffled[start:start + k]
```

**The lease model** simulates the two questions separately, because they have different shapes. The stale window is a Monte Carlo over death times; the eviction rate is a walk over heartbeat epochs where a renewal is lost with probability `HB_LOSS`:

```python
def measured_evictions(ttl: float, hb: float, rng: random.Random) -> float:
    epochs = int(3600 * LEASE_HOURS / hb)
    evictions = 0
    for _ in range(LEASE_INSTANCES):
        last = 0.0
        for i in range(1, epochs + 1):
            t = i * hb
            if rng.random() < HB_LOSS:
                continue                   # renewal lost in flight
            if t - last > ttl:
                evictions += 1             # the registry had already dropped us
            last = t
    return evictions / (LEASE_INSTANCES * LEASE_HOURS)
```

Note that the instance is never unhealthy anywhere in that loop. Every eviction it counts is a false positive.

**One detail exists purely to keep the measurement honest.** The published algorithm seeds its shuffle with the round number — a small integer, 0 to 999 at these fleet sizes. The first version of this program seeded its *kill-set* RNG with `random.Random(10)`, which collided with round 10's shuffle stream and produced three clients whose entire ten-backend subset was dead out of only forty dead backends — an event with probability around `10^-13`. Every simulation RNG is therefore given an explicit large seed, well outside the range of any round id:

```python
SIM_SEEDS = {
    "lease":         SEED * 1_000_000 + 11,
    "dns":           SEED * 1_000_000 + 22,
    ...
}
```

(Seeding with a tuple containing a string does *not* work here, because Python's string hashing is randomised per process by `PYTHONHASHSEED` and the run stops being reproducible. The program produces byte-identical output across runs and across hash seeds; that is checkable, and it was checked.)

**The DNS record-count calculation** is straight arithmetic from RFC 1035 rather than a remembered number:

```python
qname = sum(len(lbl) + 1 for lbl in name.split(".")) + 1   # length-prefixed labels + root
fits = (size - 12 - (qname + 4)) // 16                     # header, question, 16B per A record
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/05-service-discovery-and-subsetting/code/discovery_and_subsetting.py
```

```console
== 1 · LEASES: HOW LONG TRAFFIC KEEPS ARRIVING AT AN INSTANCE THAT DIED ==
  the instance is killed -9 mid-request: no deregister, no goodbye.
  renewals are lost 2% of the time (packet loss, GC pause, busy registry).
  stale window measured over 20,000 random death times per config;
  evictions measured over 400 healthy instances for 1 hour.

  config                    ttl   hb  poll    misses  mean stale  max stale  bad evictions/instance/hr
                                           tolerated      window     window        measured  predicted
  aggressive                 6s   2s    1s         2        5.5s       7.0s           0.013      0.014
  Consul-style TTL check    15s   5s    2s         2       13.5s      17.0s           0.005      0.006
  k8s node lease default    40s  10s    1s         3       35.5s      41.0s           0.000      0.000
  Eureka default            90s  30s   30s         2       89.9s     119.8s           0.000      0.001
  hb too close to ttl       30s  25s    2s         0       18.5s      31.9s           2.857      2.880
  hb ABOVE ttl (broken)     30s  35s    2s      none       13.5s      31.8s          99.955    102.857

  the last two rows are the trap. hb=25s under a 30s ttl tolerates ZERO lost
  renewals, so 2% renewal loss evicts each healthy instance ~2.8 times an hour;
  hb=35s under a 30s ttl evicts EVERY instance on EVERY renewal — a fleet that
  flaps in and out of the registry while every process is perfectly healthy.
  rule: heartbeat interval <= ttl/3, so two consecutive losses are survivable.

== 2 · DNS TTL vs REALITY: THE INSTANCE YOU REMOVED AN HOUR AGO ==
      60%  honours the TTL
      30%  pinned by a connection pool
      10%  caches forever (JVM ttl=-1)

         t    clients still resolving it  share of ALL fleet requests
        0s         2000 (100.0%)           12.50%   ########################################
       15s         1389 ( 69.5%)            8.68%   ############################
       30s          781 ( 39.1%)            4.88%   ################
       60s          747 ( 37.4%)            4.67%   ###############
      120s          690 ( 34.5%)            4.31%   ##############
      300s          516 ( 25.8%)            3.23%   ##########
      600s          208 ( 10.4%)            1.30%   ####
     3600s          208 ( 10.4%)            1.30%   ####

  one hour after removal, 10.4% of clients are still sending it traffic
  = 1.30% of every request the fleet makes, into a dead address.

  name queried                          QNAME       classic UDP (RFC 1035)   EDNS(0) typical (RFC 6891)              EDNS(0) maximum
  api.internal                            14B                        30 As                        75 As                       254 As
  backend.svc.cluster.local               27B                        29 As                        74 As                       253 As
  checkout.prod.us-east-1.mesh.corp       35B                        28 As                        73 As                       252 As

== 3 · THE N x M CONNECTION EXPLOSION: A KAPPA TERM YOU CAN COUNT ==
  assumed floor cost: 12 KB per connection on the backend, 10 KB on the client.

          N        M        N x M   inbound       mem      fleet          fds   probes/s  handshakes/s
    clients backends        conns  /backend  /backend     memory     /backend   /backend     on deploy
         10        8           80        10     0.1MB      1.7MB           ok          1             0
        100       80        8,000       100     1.2MB    171.9MB           ok         10            27
        500      400      200,000       500     5.9MB      4.2GB           ok         50           667
      1,000      800      800,000     1,000    11.7MB     16.8GB           ok        100         2,667
      2,000    1,600    3,200,000     2,000    23.4MB     67.1GB raise ulimit        200        10,667
      5,000    4,000   20,000,000     5,000    58.6MB    419.6GB raise ulimit        500        66,667

  read the 1000x800 row. 800,000 connections is 16.8 GB of socket
  state across the two fleets for ZERO requests in flight. Every backend
  answers 100 health probes per second before it serves one user, and a
  rolling deploy of the callee fleet re-establishes all 800,000 in 300s
  = 2,667 TLS handshakes per second, fleet-wide, on every release.

== 4 · RANDOM vs DETERMINISTIC SUBSETTING: SAME k, A DIFFERENT WORLD ==
       N     M    k  ideal  algorithm         min   max   stddev  max/ideal  idle backends
      60   120    6    3.0  random              0     8     1.64      2.67x              6
      60   120    6    3.0  deterministic       3     3     0.00      1.00x              0
                              -- sparse: fewer clients than backends
     200   120   12   20.0  random             10    30     4.43      1.50x              0
     200   120   12   20.0  deterministic      20    20     0.00      1.00x              0
                              -- balanced
     600   120   10   50.0  random             32    68     6.81      1.36x              0
     600   120   10   50.0  deterministic      50    50     0.00      1.00x              0
                              -- dense
    1000   800   20   25.0  random             13    44     4.94      1.76x              0
    1000   800   20   25.0  deterministic      25    25     0.00      1.00x              0
                              -- the fleet from The Problem
     997   800   20   24.9  random              9    45     5.04      1.81x              0
     997   800   20   24.9  deterministic      24    25     0.26      1.00x              0
                              -- clients NOT a whole number of rounds

  that first case drawn out — N=60 clients, M=120 backends, k=6,
  ideal = 3 clients per backend:
    random:
       0 clients |######                                          6 backends   <-- IDLE: paid for, unreachable
       1 clients |###############                                15 backends
       2 clients |###########################                    27 backends
       3 clients |##############################                 30 backends
       4 clients |######################                         22 backends
       5 clients |#############                                  13 backends
       6 clients |##                                              2 backends
       7 clients |####                                            4 backends
       8 clients |#                                               1 backends
      min 0  max 8  stddev 1.64  idle backends 6
    deterministic:
       0 clients |                                                0 backends
       1 clients |                                                0 backends
       2 clients |                                                0 backends
       3 clients |############ (bar truncated for width) ####### 120 backends
      min 3  max 3  stddev 0.00  idle backends 0

== 5 · CHOOSING k: CONNECTIONS SAVED vs BLAST RADIUS BOUGHT ==
  1000 clients, 800 backends, deterministic subsets. We kill a random
  fraction of backends and ask what each individual CLIENT lost, over
  40 independent kill draws.

  --- 80 of 800 backends dead (10%) — survivors must absorb +11% each ---
      k      conns  vs mesh    clients <50%   worst  clients at 0   worst client
                            of subset (avg)    draw    (any draw)           kept
      3      3,000    0.4%            26.8      36            36            0%
      5      5,000    0.6%             7.9      13             0           20%
     10     10,000    1.2%             0.1       1             0           40%
     20     20,000    2.5%             0.0       0             0           55%
     40     40,000    5.0%             0.0       0             0           68%
    800    800,000  100.0%             0.0       0             0           90%  <-- full mesh

  --- 160 of 800 backends dead (20%) — survivors must absorb +25% each ---
      k      conns  vs mesh    clients <50%   worst  clients at 0   worst client
                            of subset (avg)    draw    (any draw)           kept
      3      3,000    0.4%           103.0     121           338            0%
      5      5,000    0.6%            56.9      67            14            0%
     10     10,000    1.2%             5.4      11             0           20%
     20     20,000    2.5%             0.5       2             0           40%
     40     40,000    5.0%             0.0       0             0           52%
     80     80,000   10.0%             0.0       0             0           62%
    800    800,000  100.0%             0.0       0             0           80%  <-- full mesh

  k=20 at N=1000, M=800: 20,000 connections instead of 800,000 (2.5%),
  429.7MB of socket state instead of 16.8GB.
  2.5 health probes/s per backend instead of 100, and 67 handshakes/s
  on deploy instead of 2,667.

== 6 · CONTROL PLANE DOWN: THE DATA PLANE MUST NOT CARE ==
  600 clients, 120 backends, deterministic subsets of k=10,
  2 requests per client per second for 240s.
  the discovery service is unreachable from t=60s to t=180s.
  during the outage 5% of backends are replaced, so a cached view rots.

        window  no cache (fail closed)             serve stale     serve stale + eject
         0-20s                  100.0%                  100.0%                  100.0%
        40-60s                  100.0%                  100.0%                  100.0%
        60-80s                    0.0%                  100.0%                  100.0%  <-- CONTROL PLANE DOWN
       80-100s                    0.0%                   99.0%                   99.4%  <-- CONTROL PLANE DOWN
      100-120s                    0.0%                   98.2%                   99.4%  <-- CONTROL PLANE DOWN
      120-140s                    0.0%                   97.2%                   99.4%  <-- CONTROL PLANE DOWN
      140-160s                    0.0%                   96.7%                   99.4%  <-- CONTROL PLANE DOWN
      160-180s                    0.0%                   95.7%                   99.3%  <-- CONTROL PLANE DOWN
      180-200s                  100.0%                  100.0%                  100.0%
      220-240s                  100.0%                  100.0%                  100.0%

  no cache (fail closed)   whole run  50.00%   during the outage   0.00%   (144,000 of 144,000 failed)
  serve stale              whole run  98.91%   during the outage  97.81%   (3,153 of 144,000 failed)
  serve stale + eject      whole run  99.74%   during the outage  99.48%   (755 of 144,000 failed)
```

**Section 1 is the reason lease tuning is not a matter of taste.** The measured and predicted eviction columns agree wherever events are common enough to count (2.857 vs 2.880; 99.955 vs 102.857), which means the closed form `(3600/hb) × loss^(tolerated+1)` is a formula you can apply to your own numbers rather than a curve fit. And the two ends of the table are the two ways to get it wrong. Eureka's defaults give a **89.9-second mean stale window** — completely safe against false evictions, and completely unable to notice a dead instance quickly. `hb=25s` under a 30-second TTL notices fast and evicts a healthy instance nearly three times an hour. Neither is a bug; they are two positions on one dial, and the ratio `ttl/hb` is the dial.

**Section 2's DNS decay curve has a shape worth internalising.** It does not decay. It drops fast for thirty seconds as the TTL-respecting cohort expires, then flattens into a long shelf, then stops moving entirely at **10.4% of clients / 1.30% of all requests** and stays there until those processes restart. If your removal procedure is "take it out of DNS and wait," you are waiting for a number that has an asymptote above zero.

**Section 4 is the whole lesson in one contrast.** Same N, same M, same k, same number of connections — 360 in the sparse case, 20,000 at fleet scale. Random subsetting produces a binomial spread with **6 idle backends and a peak at 2.67× the ideal load**; deterministic subsetting produces **min 3, max 3, standard deviation 0.00**. There is no trade here, which is rare. The only thing you give up is that a client's subset is no longer independent of every other client's, and that dependency is precisely what buys the evenness.

**Section 5 prices k honestly.** The headline is the `clients at 0` column at 20% backend loss: **338 client-draws stranded at k=3, 14 at k=5, zero from k=10 upward.** The connection cost of moving from k=3 to k=20 is 0.4% of the mesh to 2.5% of the mesh — 17,000 connections out of 800,000. Anyone choosing k=3 to save memory is trading 2% of a budget for the possibility that a client goes to zero capacity while 640 healthy backends idle.

**Section 6 is a policy decision with a measured price.** Identical outage, identical churn, three client behaviours: **0.00%, 97.81%, 99.48%.** The gap between the first and second numbers is not an optimisation; it is the difference between an incident and a graph nobody looked at.

## Use It

Every production system here implements the same three ideas — a registry with leases, a control plane pushing endpoints, and some way to avoid the full mesh — and the interesting part is where each of them draws the line.

**Kubernetes Services and EndpointSlices.** A `Service` is a stable name and virtual IP; the actual membership lives in endpoint objects that the endpoint controller keeps in sync with pod readiness. The reason `EndpointSlice` exists is a genuine κ story and worth knowing precisely. The original `Endpoints` object held **every** address for a Service in a single resource. Every pod change rewrote the whole object, and that object was watched by every kube-proxy on every node. So the update traffic was `O(pods × nodes)`: a 5,000-endpoint Service produced a multi-megabyte object, and a rolling deploy rewrote it thousands of times, to thousands of watchers. Large clusters spent serious control-plane bandwidth on it. `EndpointSlice` shards the same data into chunks of at most **100 endpoints by default** (`--max-endpoints-per-slice`, up to 1000), so a pod change rewrites one small slice instead of one enormous object. It is subsetting applied to the *control plane's own data*, for exactly the same reason you apply it to connections.

```bash
kubectl get endpointslices -l kubernetes.io/service-name=pricing
# NAME             ADDRESSTYPE   PORTS   ENDPOINTS                     AGE
# pricing-7wxk2    IPv4          8080    10.2.1.4,10.2.1.9,+98 more    31d
```

**kube-proxy: iptables vs IPVS.** In `iptables` mode, kube-proxy programs a chain of rules per Service with `statistic --mode random --probability` to spread connections. It works and it is `O(n)` in rules: the rule set is evaluated linearly, and syncing it rewrites large rule tables, so at tens of thousands of Services the sync latency becomes minutes. `IPVS` mode uses the kernel's in-built load balancer with hash-table lookup, giving `O(1)` matching and real algorithms (`rr`, `lc`, `sh`, `dh`) instead of random-only. If your cluster has more than a few thousand Services, this is the setting to check. Both are **connection-level**, i.e. L4 — a single long-lived HTTP/2 connection is balanced exactly once, which is why gRPC through a plain ClusterIP Service pins to one backend and stays there. That surprise is the single most common reason teams move to client-side balancing in the first place.

**Headless Services** are how you opt out of the virtual IP entirely:

```yaml
apiVersion: v1
kind: Service
metadata:
  name: pricing
spec:
  clusterIP: None          # headless: DNS returns every pod IP, no VIP, no kube-proxy
  publishNotReadyAddresses: false
  selector: { app: pricing }
  ports: [{ port: 8080 }]
```

DNS now returns all pod addresses and the client balances itself — which is the setup from *The Problem*, and which brings every DNS limitation from earlier along with it. Note `publishNotReadyAddresses: false`: leaving it true publishes pods that are not ready, which is occasionally what a StatefulSet wants and never what a load-balanced client wants.

**Consul and Eureka** are standalone registries with opposite defaults. Consul is CP-leaning (Raft-replicated) and supports both agent-run health checks and TTL checks where the service pushes its own heartbeat; its DNS interface returns only *passing* instances, which is DNS-as-discovery with the health problem solved on the server side. Eureka is deliberately AP-leaning: its default **90-second lease with a 30-second renewal** and its client-side registry cache are exactly the "serve stale" posture from section 6, and its self-preservation mode explicitly stops expiring leases when it loses too many heartbeats at once, on the reasoning that a mass heartbeat failure is more likely to be a network problem than a mass death. That is a defensible choice and it is why Eureka is slow to notice real deaths — the 89.9-second mean stale window measured above is Eureka's advertised behaviour, not a flaw.

**gRPC name resolution and xDS.** gRPC has a pluggable resolver (`dns:///`, `unix:`, `xds:///`) feeding a pluggable load-balancing policy. The defaults matter: `pick_first` opens **one** connection to the first working address and keeps it — fine for a proxy, catastrophic for a fleet — while `round_robin` connects to *all* resolved addresses, which is the full mesh. The `xds://` scheme makes gRPC an xDS client, so a control plane can push endpoints and policy, including `RING_HASH` (consistent hashing over endpoints, so a given key lands on a stable backend and adding one endpoint moves only `1/n` of the keys) and `LEAST_REQUEST` (gRPC's implementation samples `choice_count` endpoints — default **2** — and picks the one with fewest active requests, which is Lesson 3's P2C).

**Envoy's subset load balancing and EDS.** Envoy gets endpoints from EDS (Endpoint Discovery Service) over xDS and can subset them itself:

```yaml
clusters:
- name: pricing
  type: EDS
  eds_cluster_config:
    service_name: pricing
    eds_config: { api_config_source: { api_type: GRPC, ... } }
  lb_policy: LEAST_REQUEST
  least_request_lb_config:
    choice_count: 2                   # P2C — Lesson 3
  lb_subset_config:                   # route only to endpoints with matching metadata
    fallback_policy: ANY_ENDPOINT     # if no subset matches, do NOT fail closed
    subset_selectors:
    - keys: [ "zone", "version" ]
  outlier_detection:
    consecutive_5xx: 5
    max_ejection_percent: 10          # never eject the whole subset
```

Two things to be precise about. `lb_subset_config` is **metadata-based** subsetting — "route to endpoints tagged `zone: us-east-1a`" — which is a routing feature, not the connection-count fix; the N×M reduction comes from Envoy's `deterministic_aperture` / aperture LB configuration, which is the consistent-hashing descendant of the SRE algorithm above. And `fallback_policy` is the fail-open switch: set it to `NO_ENDPOINT` and a metadata mismatch produces a total outage for that route.

**AWS.** Cloud Map is the registry (with a DNS interface and an API interface, and the DNS interface inherits every caching problem in this lesson). ALB and NLB target groups are the proxy model — the balancer holds the connections, so N×M never arises for your application, and you pay a hop plus a component whose failure is your failure. `deregistration_delay.timeout_seconds` on a target group is exactly the drain window from the previous section; its **default is 300 seconds**, which is usually far longer than you need and is worth setting deliberately rather than inheriting.

### What to actually do

- **A proxy hop is fine, and it is the right default for most teams.** One hop is on the order of a millisecond, the operational cost of client-side balancing is a permanent tax on every service in every language, and a managed load balancer is somebody else's on-call. If your service does thousands of requests per second and nobody has ever complained about the hop, stop here.
- **Client-side balancing earns its complexity in three situations**, and mostly only those: long-lived multiplexed connections where an L4 proxy pins you to one backend (gRPC, HTTP/2 — see [gRPC & Protocol Buffers](../../01-networking-and-protocols/13-grpc-and-protocol-buffers/)); latency budgets where a millisecond of hop against a two-millisecond backend is a real percentage; and paths where the balancer's own availability is the limiting factor. In every one of those, prefer a **sidecar** over a library, so the logic upgrades like infrastructure.
- **Subsetting stops being optional at roughly 100 backends, or 10,000 total connections.** Below that, a full mesh costs a few hundred megabytes and nobody notices. The concrete triggers: inbound connections per backend approaching your `RLIMIT_NOFILE`; health-probe traffic becoming a visible fraction of a backend's request rate (above ~10 probes/s per backend, look at it); or a deploy producing a handshake rate you can see on a graph. Any one of those means k should be a number in your config.
- **Set k to 20-40 and leave it.** Compute `f^k` for your worst realistic simultaneous-failure fraction before you lower it.
- **Cache endpoints, serve stale, and test it.** Kill your registry in a game day and watch request success. If it drops, you have a global single point of failure and did not know.
- **Set the drain window from the client refresh interval**, not from your request latency. Then verify it: deploy, and watch for `ECONNREFUSED` at the caller. If you see any, propagation is losing the race with shutdown.

Phase 10 covers actually deploying this — [Orchestration & Kubernetes](../../10-infrastructure-and-deployment/07-orchestration-and-kubernetes/) for Services and readiness gates, and [Reverse Proxies & Load Balancers](../../10-infrastructure-and-deployment/09-reverse-proxies-and-load-balancers/) for the proxy-side configuration.

## Think about it

1. Your registry's lease TTL is 30 seconds and the heartbeat is 10 seconds. You want dead instances noticed in under 5 seconds. Work out what happens to the false-eviction rate if you set `ttl=5s, hb=2s` at a 2% renewal loss rate — then propose a way to get 5-second detection *without* touching the lease at all.
2. A client's subset is computed from `client_id`, and `client_id` is assigned by hashing the pod name. Pods get new names on every restart. Explain precisely what happens to the connection topology during a rolling restart of the client fleet, and what it does to the backends' inbound connection counts mid-deploy.
3. Deterministic subsetting gives standard deviation 0.00 on *clients per backend*. Name two realistic situations where that still produces badly uneven **load**, and say what you would measure to detect each.
4. Your control plane has been down for 40 minutes. Serve-stale is working and success is at 96%. Someone proposes expiring the cache after 30 minutes so clients "fail loudly instead of routing to ghosts." Argue both sides with numbers, and say what the cache expiry should actually be and why.
5. You have 3 availability zones, 900 backends evenly spread, and k=20 chosen from the global list. One zone fails. What fraction of capacity does each client lose on average, what is the worst client's loss, and how would you change the subsetting so that a zone failure costs every client exactly the same? What does that change cost you?

## Key takeaways

- **A lease detects a missing renewal, not death, and both directions of that dial hurt.** With ttl=15s/hb=5s/poll=2s, traffic keeps arriving at a killed instance for a measured **mean of 13.5 s and worst case of 17.0 s** (`ttl − hb/2 + poll/2`, peaking at `ttl + poll`). Shorten the ratio instead of the TTL and you pay the other way: at 2% renewal loss, **hb=25s under a 30s TTL evicts each healthy instance 2.857 times an hour** versus 0.005 at hb=5s/ttl=15s. **Keep heartbeat ≤ ttl/3.**
- **DNS as a service registry has an asymptote above zero.** An hour after removing an address, **10.4% of clients were still resolving it — 1.30% of every request the fleet makes** — because connection pools never re-resolve and the JVM's `networkaddress.cache.ttl` historically defaulted to `-1`. A classic 512-byte UDP answer holds only **29 A records** for `backend.svc.cluster.local` (74 at the common 1232-byte EDNS(0) buffer), and an A record carries no health, no weight and no drain state.
- **Client-side balancing removes a hop and a single point of failure, and buys a library-version fleet problem plus an N×M connection explosion.** At 1,000 clients × 800 backends: **800,000 connections, 16.8 GB of socket state, 1,000 inbound descriptors per backend against a 1,024 default, 100 health probes/s per backend, and 2,667 TLS handshakes/s on every deploy.** Double both fleets and all of it quadruples — Lesson 2's κ term, counted in sockets.
- **The data plane must keep routing when the control plane is down.** Over an identical 120-second registry outage with 5% real backend churn, fail-closed delivered **0.00%**, last-known-good serve-stale delivered **97.81%**, and serve-stale plus outlier ejection delivered **99.48%**. A mesh that fails closed is a worse single point of failure than the load balancer it replaced.
- **Deterministic subsetting is free evenness.** Number the clients, group them into rounds of `M/k`, shuffle the backend list seeded by the round number, and hand out disjoint slices (Beyer et al., *Site Reliability Engineering*, 2016, ch. 20). One round covers the list exactly once, so R rounds give every backend exactly R clients: measured **min 25, max 25, stddev 0.00** at N=1000/M=800/k=20 — against random subsetting's **min 13, max 44, stddev 4.94**, and 6 permanently idle backends in the sparse case. **Both use exactly N×k connections.**
- **k trades memory for the variance an individual client sees, and the exchange rate is terrible below 10.** At a 20% backend loss over 40 draws, **k=3 stranded 338 client-draws with a completely dead subset and k=5 stranded 14; k=10 and above stranded none.** The cost of moving from k=3 to k=20 is 0.4% → 2.5% of the full mesh. `P(client loses everything) = f^k`. **Use 20-40.**
- **Subsetting and P2C compose because they are different layers** — subsetting picks which backends a client can see, the balancing algorithm picks which one gets this request. Cap outlier ejection (Envoy's `max_ejection_percent`, default 10%) so ejection can never empty a subset.
- **Drain, do not delete, and size the drain from the client refresh interval.** Mark draining → *wait for propagation* → finish in-flight → `GOAWAY` → deregister → exit. With client-side balancing there is no single proxy to update, so the drain is not complete until the slowest of N cached views has noticed; `terminationGracePeriodSeconds` must exceed **client refresh interval + longest in-flight request**.

Next: [Stateless Services: Where the State Actually Went](../06-stateless-services/) — every technique in this lesson assumed any backend can serve any request. That assumption is a design decision, and this is where you pay for it or make it true.
