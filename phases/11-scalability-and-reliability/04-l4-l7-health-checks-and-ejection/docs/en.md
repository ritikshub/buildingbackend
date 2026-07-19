# Layer 4 vs Layer 7, Health Checks & Outlier Ejection

> Your load balancer divided 24 client connections across 8 backends perfectly evenly — three each, no bug, no misconfiguration. Measured here: the hottest backend still took **22.6% of the requests and the coldest 6.8%, a 3.3× spread**, and a ninth instance that joined a healthy pool received **0 requests in 600 seconds**. Then the failure with a body count: a fleet with 8% headroom left, nothing crashed and no deploy out, health-checked itself from **20 healthy instances to 0 in 44 seconds** and delivered 21.3% of its traffic on time. Two knobs — neither of which adds a single request per second of capacity — put that back to 99.7%.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Load Balancing Algorithms](../03-load-balancing-algorithms/), [Transport Layer: TCP vs UDP](../../01-networking-and-protocols/05-transport-layer-tcp-vs-udp/), [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/)
**Time:** ~75 minutes

## The Problem

The migration was uncontroversial. Your internal services talked HTTP/1.1 (Hypertext Transfer Protocol version 1.1, one request per connection at a time) and you moved them to gRPC — a remote-procedure-call framework that runs over HTTP/2 and multiplexes many concurrent requests down a single connection. The benchmark was unambiguous: fewer connections, no per-request handshake, header compression, 40% less CPU in the network stack. It shipped on a Tuesday.

**Tuesday 16:40 — the deploy completes.** Every client instance reconnects, gets a backend, and settles in. Latency drops. Everyone is pleased.

**Wednesday 09:15 — the first page.** Instance `api-7f3` is at 91% CPU. Nothing else is. You look at the other thirteen instances in the pool and they are averaging 34%. Somebody suggests a memory leak, somebody else suggests a noisy neighbour, and the instance is restarted. It comes back, picks up connections, and within an hour it is at 88% again — or rather, a *different* instance is, and `api-7f3` is now idle.

**Wednesday 11:00 — the graph that ends the debate.** Someone finally graphs **requests per second per instance** instead of CPU. Three instances are serving nearly all the traffic. Eleven are nearly idle. And the load balancer's own dashboard — the one everybody has been staring at — shows what it has shown all along: **connections are distributed perfectly evenly.** Fourteen instances, forty-two connections, three apiece. The balancer is doing exactly what it was configured to do, and has been correct on its own terms for eighteen months.

**Wednesday 14:30 — the worse discovery.** Autoscaling added two instances at 09:20, during the incident. They passed their health checks immediately. They have been in the pool, healthy and advertised, for **five hours**. They have served **zero requests**. Not few — zero. There is no error to find, because nothing failed. The new instances are waiting for a connection to arrive, and every client already has all the connections it intends to open.

Here is the mechanism, and it is one sentence. **A Layer 4 balancer chooses a backend once, when the connection is established, and that choice is then frozen for the life of the connection.** Under HTTP/1.1 that was invisible, because connections were short: a client opened one, made a few requests, and closed it, so the balancer got a fresh decision every few seconds and the law of large numbers did the rest. Under gRPC, a connection opens at deploy time and lives until the next deploy. The balancer now makes **one decision per client per week**, and everything in between rides whatever that decision was.

Nothing is broken. No packet was lost, no instance is sick, no threshold was misconfigured. The balancer is balancing the thing it can see — connections — and connections stopped being a proxy for load the moment one connection started carrying thousands of requests. **The layer is wrong.**

And then there is the other half of this lesson, which is the part that turns a bad afternoon into a full outage. The instrument you rely on to remove a broken backend — the health check — is a **feedback control system wired into the thing it measures**. It observes latency, and its response to bad latency is to remove capacity, which raises latency. Section 4 of the Build It runs that loop with a 12-point step in demand as the only trigger and measures the fleet ejecting itself to zero healthy instances. Everything in it is a correct component behaving as designed.

## The Concept

### What each layer can see

The names come from the OSI (Open Systems Interconnection) reference model, which numbers the layers of a network stack. **Layer 4 is the transport layer** — TCP and UDP, ports and connections. **Layer 7 is the application layer** — HTTP, gRPC, requests and responses. Where your balancer sits determines what information it has, and information is the entire difference.

An **L4 balancer** sees a **4-tuple**: source IP, source port, destination IP, destination port. That is the whole of its input. It picks a backend at connection setup — by hashing the tuple, or by round-robin, or by connection count — writes an entry into a connection-tracking table, and from then on forwards packets. It never parses a byte of what you are sending. It cannot, because after the handshake the payload is an opaque stream, and under TLS (Transport Layer Security) it is opaque *and* encrypted.

An **L7 balancer** terminates the connection, parses the request, and picks a backend **per request**. It reads the method, the path, the headers, the HTTP/2 stream identifier.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 512" width="100%" style="max-width:840px" role="img" aria-label="Layer 4 and layer 7 load balancing side by side. The layer 4 balancer sees only a TCP four-tuple and opaque bytes, makes one backend choice at connection setup, and every request that follows on that connection travels the same frozen path to the same backend, while the other two backends are never reconsidered; the response can bypass the balancer entirely by direct server return. The layer 7 balancer parses each request, so the same single HTTP/2 connection fans out across all three backends and can be retried and rerouted per request, at the cost of terminating and parsing everything.">
  <defs>
    <marker id="p11-04-a1" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker> <marker id="p11-04-a1g" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker> <marker id="p11-04-a1b" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker> <marker id="p11-04-a1r" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The decision point is the whole difference</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="42" width="418" height="404" rx="12" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff"/> <rect x="446" y="42" width="418" height="404" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="225" y="68" font-size="13" font-weight="700" fill="#7c5cff">LAYER 4 — TRANSPORT</text> <text x="225" y="84" font-size="9.5" opacity="0.9">one decision, taken at connection setup</text> <text x="655" y="68" font-size="13" font-weight="700" fill="#0fa07f">LAYER 7 — APPLICATION</text> <text x="655" y="84" font-size="9.5" opacity="0.9">one decision per request, every request</text>
    </g>
    <g fill="none" stroke-width="1.6" stroke-linejoin="round">
      <rect x="30" y="96" width="188" height="82" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/> <rect x="232" y="96" width="190" height="82" rx="8" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/> <rect x="460" y="96" width="188" height="82" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/> <rect x="662" y="96" width="190" height="82" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/>
    </g>
    <g fill="currentColor">
      <text x="42" y="112" font-size="8.5" font-weight="700" opacity="0.7">ALL IT CAN SEE</text> <text x="42" y="128" font-size="9">src 10.2.4.9:53211</text> <text x="42" y="142" font-size="9">dst 10.0.0.7:443</text> <text x="42" y="156" font-size="9">proto TCP</text> <text x="42" y="170" font-size="9" opacity="0.7">then: opaque bytes</text> <text x="244" y="112" font-size="8.5" font-weight="700" fill="#d64545">WHAT IT CANNOT DO</text> <text x="244" y="128" font-size="9">retry a failed request</text>
      <text x="244" y="142" font-size="9">route on path or header</text> <text x="244" y="156" font-size="9">see where a request ends</text> <text x="244" y="170" font-size="9" font-weight="700">rebalance a live connection</text> <text x="472" y="112" font-size="8.5" font-weight="700" opacity="0.7">WHAT IT PARSES</text> <text x="472" y="128" font-size="9">POST /v1/checkout</text> <text x="472" y="142" font-size="9">:authority api.acme.io</text> <text x="472" y="156" font-size="9">x-tenant: acme-eu</text> <text x="472" y="170" font-size="9" opacity="0.7">HTTP/2 stream 4711</text> <text x="674" y="112" font-size="8.5" font-weight="700" fill="#e0930f">WHAT IT COSTS</text> <text x="674" y="128" font-size="9">terminates TCP and TLS</text> <text x="674" y="142" font-size="9">parses every byte, twice</text> <text x="674" y="156" font-size="9">its bandwidth is the ceiling</text> <text x="674" y="170" font-size="9">CPU per request, not per conn</text>
    </g>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="30" y="252" width="62" height="42" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/> <rect x="122" y="252" width="70" height="42" rx="8" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/> <rect x="300" y="208" width="120" height="36" rx="7" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 4"/> <rect x="300" y="254" width="120" height="36" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/> <rect x="300" y="300" width="120" height="36" rx="7" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.4" stroke-dasharray="5 4"/> <rect x="460" y="252" width="62" height="42" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/> <rect x="552" y="252" width="70" height="42" rx="8" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/> <rect x="730" y="208" width="120" height="36" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="730" y="254" width="120" height="36" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/> <rect x="730" y="300" width="120" height="36" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="10">
      <text x="61" y="277" font-weight="700" fill="#3553ff">client</text> <text x="157" y="271" font-weight="700" fill="#7c5cff">L4 LB</text> <text x="157" y="285" font-size="8">4-tuple hash</text> <text x="360" y="231">backend A</text> <text x="360" y="277" font-weight="700">backend B</text> <text x="360" y="323">backend C</text> <text x="491" y="277" font-weight="700" fill="#3553ff">client</text> <text x="587" y="271" font-weight="700" fill="#7c5cff">L7 proxy</text> <text x="587" y="285" font-size="8">parses first</text> <text x="790" y="231">backend A</text> <text x="790" y="277">backend B</text> <text x="790" y="323">backend C</text>
    </g>
    <path d="M92 273 L 116 273" fill="none" stroke="#3553ff" stroke-width="6" opacity="0.35"/> <path d="M192 273 L 294 273" fill="none" stroke="#0fa07f" stroke-width="6.5" opacity="0.5" marker-end="url(#p11-04-a1g)"/>
    <g fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 5" opacity="0.4">
      <path d="M157 252 C 157 212, 240 208, 294 222"/> <path d="M157 294 C 157 334, 240 338, 294 324"/>
    </g>
    <path d="M360 336 C 360 388, 130 392, 61 300" fill="none" stroke="#0fa07f" stroke-width="1.7" stroke-dasharray="7 4" marker-end="url(#p11-04-a1g)"/>
    <path d="M522 273 L 546 273" fill="none" stroke="#3553ff" stroke-width="6" opacity="0.35"/>
    <g fill="none" stroke="#0fa07f" stroke-width="2">
      <path d="M626 259 L 724 228" marker-end="url(#p11-04-a1g)"/> <path d="M626 273 L 724 273" marker-end="url(#p11-04-a1g)"/> <path d="M626 287 L 724 316" marker-end="url(#p11-04-a1g)"/>
    </g>
    <g fill="currentColor">
      <text x="243" y="259" font-size="9" font-weight="700" fill="#0fa07f" text-anchor="middle">SYN — pick B</text> <text x="243" y="290" font-size="8.5" text-anchor="middle" opacity="0.85">and never again</text> <text x="250" y="240" font-size="8" text-anchor="middle" opacity="0.6">not reconsidered</text> <text x="250" y="314" font-size="8" text-anchor="middle" opacity="0.6">not reconsidered</text> <text x="205" y="382" font-size="8.5" fill="#0fa07f" font-weight="700" text-anchor="middle">direct server return: the response never touches the LB</text> <text x="650" y="240" font-size="8" fill="#0fa07f" font-weight="700">req 1</text> <text x="650" y="266" font-size="8" fill="#0fa07f" font-weight="700">req 2</text> <text x="644" y="312" font-size="8" fill="#0fa07f" font-weight="700">req 3</text>
    </g>
    <g fill="none" stroke-width="1.6" stroke-linejoin="round">
      <rect x="30" y="196" width="390" height="42" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" opacity="0"/>
    </g>
    <g fill="currentColor">
      <text x="30" y="200" font-size="9" font-weight="700" fill="#d64545">ONE gRPC connection · thousands of requests · hours · every one to B</text> <text x="460" y="200" font-size="9" font-weight="700" fill="#0fa07f">ONE gRPC connection · thousands of requests · spread over all three</text> <text x="30" y="410" font-size="9" opacity="0.9">A backend that joins later missed the only moment that ever</text> <text x="30" y="424" font-size="9" opacity="0.9">mattered. Measured: <tspan font-weight="700" fill="#d64545">0 requests in 600 s</tspan> of being healthy.</text> <text x="30" y="438" font-size="9" opacity="0.75">Fix by forcing reconnects — max_connection_age — or move to L7.</text> <text x="460" y="410" font-size="9" opacity="0.9">Every request is a fresh decision, so a new backend is used</text>
      <text x="460" y="424" font-size="9" opacity="0.9">on the next request. Measured: <tspan font-weight="700" fill="#0fa07f">11.1% share immediately</tspan>.</text> <text x="460" y="438" font-size="9" opacity="0.75">You pay for it in proxy CPU and in the proxy's own bandwidth.</text>
    </g>
    <text x="440" y="474" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Same round-robin algorithm on both sides. L4 round-robins connections; L7 round-robins requests.</text> <text x="440" y="492" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">When one connection carries thousands of requests, those are not the same thing.</text>
  </g>
</svg>
```

The consequences follow mechanically from what each one holds:

| | L4 | L7 |
|---|---|---|
| Decision granularity | once per connection | once per request |
| Can route on path / header / tenant | no | yes |
| Can retry a failed request elsewhere | no — a retry is a new connection by a new client | yes, transparently |
| Can balance a multiplexed connection | **no** | yes |
| Sees HTTP status codes | no | yes — which is what passive ejection needs |
| Cost per request | near zero; forwards packets | parse, buffer, re-serialise, often re-encrypt |
| Bandwidth ceiling | can be bypassed entirely (see below) | **all traffic flows through it, both ways** |

The retry row deserves a sentence, because it is the one people are surprised by. An L4 balancer cannot retry a failed request for a structural reason, not a missing feature: it does not know where a request begins or ends. It is forwarding a byte stream. "Retry" is a concept that exists only at Layer 7, so if the backend accepts your connection and then returns a 500, an L4 balancer has no idea anything went wrong, and would have nothing to re-send if it did.

None of this makes L4 the worse choice. It makes L4 the *cheaper* choice, and cheap at the front of a large fleet is worth a great deal. Google's Maglev (Eisenbud et al., *Maglev: A Fast and Reliable Software Network Load Balancer*, NSDI 2016) is an L4 balancer built precisely because a software L4 forwarder can saturate a 10 Gbps NIC (Network Interface Card) from commodity hardware. The rule is not "L7 is better". The rule is that **L4 is balancing connections, so it is only balancing load when connections and load are the same thing.**

### The long-lived-connection trap

They stopped being the same thing. HTTP/2 (RFC 9113 §5) multiplexes concurrent **streams** over one TCP connection; gRPC keeps that connection open for the life of the process; and even plain HTTP/1.1 with aggressive keep-alive holds a connection open for minutes ([Keep-Alive, Pooling & Timeouts](../../01-networking-and-protocols/14-keep-alive-pooling-timeouts/) covers why you want that, and [HTTP/2 and HTTP/3](../../01-networking-and-protocols/11-http2-and-http3-quic/) covers the multiplexing itself). Each of those is a performance win. Each of them also extends the interval between the only moments an L4 balancer is allowed to think.

The Build It runs 24 client connections against 8 backends for 900 simulated seconds, round-robin in every configuration, with a 9th backend joining at t=300 s. The only variable is the layer, and the connection lifetime:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="Measured share of requests per backend after a ninth backend joined the pool at t equals 300 seconds. Under the layer 4 balancer the nine backends received 13.3, 10.9, 9.7, 9.1, 6.8, 14.4, 22.6, 13.1 and 0.0 percent of requests, a 3.3 times spread, with the newly added ninth backend receiving nothing at all across 600 seconds of being healthy. Under the layer 7 balancer every backend including the new one received exactly 11.1 percent. The same round-robin algorithm produced both distributions.">
  <defs>
    <marker id="p11-04-a2r" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Measured: the same round-robin, one layer apart</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M74 306 L 700 306"/> <path d="M74 306 L 74 58"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35">
      <path d="M70 265.7 L 74 265.7"/> <path d="M70 225.3 L 74 225.3"/> <path d="M70 185 L 74 185"/> <path d="M70 144.7 L 74 144.7"/> <path d="M70 104.3 L 74 104.3"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="64" y="310">0%</text> <text x="64" y="269">5%</text> <text x="64" y="229">10%</text> <text x="64" y="188">15%</text> <text x="64" y="148">20%</text> <text x="64" y="108">25%</text>
    </g>
    <text x="26" y="190" font-size="10" fill="currentColor" opacity="0.85" transform="rotate(-90 26 190)" text-anchor="middle">share of requests</text>
    <path d="M74 216.5 L 706 216.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-dasharray="6 5" opacity="0.55"/> <text x="712" y="213" font-size="9" fill="currentColor" opacity="0.85">perfectly even = 11.1%</text>
    <g stroke-width="1.5">
      <rect x="88"  y="198.8" width="26" height="107.2" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="156" y="218.1" width="26" height="87.9"  fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="224" y="227.8" width="26" height="78.2"  fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="292" y="232.6" width="26" height="73.4"  fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="360" y="251.2" width="26" height="54.8"  fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="428" y="189.9" width="26" height="116.1" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="496" y="123.8" width="26" height="182.2" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="2.4"/> <rect x="564" y="200.4" width="26" height="105.6" fill="#d64545" fill-opacity="0.28" stroke="#d64545"/> <rect x="632" y="303.2" width="26" height="2.8"   fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="2.4"/>
    </g>
    <g stroke-width="1.5">
      <rect x="118" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="186" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="254" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="322" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="390" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="458" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="526" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="594" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.28" stroke="#0fa07f"/> <rect x="662" y="216.5" width="26" height="89.5" fill="#0fa07f" fill-opacity="0.45" stroke="#0fa07f" stroke-width="2.4"/>
    </g>
    <g fill="#d64545" font-size="8.5" font-weight="700" text-anchor="middle">
      <text x="101" y="194">13.3</text> <text x="169" y="213">10.9</text> <text x="237" y="223">9.7</text> <text x="305" y="228">9.1</text> <text x="373" y="246">6.8</text> <text x="441" y="185">14.4</text> <text x="509" y="118">22.6</text> <text x="577" y="195">13.1</text> <text x="645" y="299">0.0</text>
    </g>
    <g fill="#0fa07f" font-size="8.5" font-weight="700" text-anchor="middle">
      <text x="131" y="211">11.1</text> <text x="199" y="211">11.1</text> <text x="267" y="211">11.1</text> <text x="335" y="211">11.1</text> <text x="403" y="211">11.1</text> <text x="471" y="211">11.1</text> <text x="539" y="211">11.1</text> <text x="607" y="211">11.1</text> <text x="675" y="211">11.1</text>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle">
      <text x="116" y="322">b1</text> <text x="184" y="322">b2</text> <text x="252" y="322">b3</text> <text x="320" y="322">b4</text> <text x="388" y="322">b5</text> <text x="456" y="322">b6</text> <text x="524" y="322">b7</text> <text x="592" y="322">b8</text> <text x="660" y="322" font-weight="700" fill="#d64545">b9</text>
    </g>
    <path d="M600 344 L 641 312" fill="none" stroke="#d64545" stroke-width="1.5" marker-end="url(#p11-04-a2r)"/> <text x="594" y="348" font-size="9.5" font-weight="700" fill="#d64545" text-anchor="end">b9 joined the pool at t=300 s and was healthy for the next 600 s</text>
    <g fill="none" stroke-width="1.6" stroke-linejoin="round">
      <rect x="712" y="58" width="152" height="120" rx="8" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/> <rect x="712" y="228" width="152" height="86" rx="8" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="724" y="76" font-size="10" font-weight="700" fill="#d64545">L4 · per connection</text> <text x="724" y="94">spread</text> <text x="856" y="94" text-anchor="end" font-weight="700">3.3x</text> <text x="724" y="110">hottest</text> <text x="856" y="110" text-anchor="end" font-weight="700">22.6%</text> <text x="724" y="126">coldest</text> <text x="856" y="126" text-anchor="end" font-weight="700">6.8%</text> <text x="724" y="142">new instance</text> <text x="856" y="142" text-anchor="end" font-weight="700" fill="#d64545">0.0%</text> <text x="724" y="164" font-size="8.5" opacity="0.8">24 conns / 8 backends</text> <text x="724" y="174" font-size="8.5" opacity="0.8">= exactly 3 each</text> <text x="724" y="246" font-size="10" font-weight="700" fill="#0fa07f">L7 · per request</text> <text x="724" y="264">spread</text> <text x="856" y="264" text-anchor="end" font-weight="700">1.00x</text>
      <text x="724" y="280">every backend</text> <text x="856" y="280" text-anchor="end" font-weight="700">11.1%</text> <text x="724" y="296">new instance</text> <text x="856" y="296" text-anchor="end" font-weight="700" fill="#0fa07f">11.1%</text>
    </g>
    <text x="440" y="376" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">L4 divided the connections perfectly evenly. Connections are not equal, so the requests were not.</text> <text x="440" y="392" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The flat bar is not a bug: b9 simply arrived after the last routing decision had already been taken.</text>
  </g>
</svg>
```

Read the first row carefully, because it is the whole argument. **The connections were divided perfectly: 24 ÷ 8 = 3 each, exactly.** By its own metric the balancer scored 100%. And the request distribution that came out of that perfect division ran from **22.6% on the hottest backend to 6.8% on the coldest — a 3.3× spread.** The reason is not subtle once you see it: real clients are not identical. The simulated per-connection rates are lognormal, from **0.85 req/s to 14.75 req/s** around a 5.84 req/s median, which is what production traffic looks like — a few chatty callers, a long tail of quiet ones. Round-robin over connections gives every connection equal weight; the requests inside them are not equally weighted, and nothing in the L4 balancer can see that.

Now the column that ends careers. **The 9th backend received 0 requests across 600 seconds of being healthy, registered and in the pool.** Not "a low share" — zero. It joined after every routing decision had already been taken, and under a never-closing connection there is no next decision. Your autoscaler scaled out. Your dashboard shows nine healthy instances. Your capacity did not change at all.

Four ways out, in increasing order of how much you have to change:

1. **Move the decision to L7.** The last row: spread **1.00×**, every backend at **11.1%**, and the new instance at **11.1% immediately**. You pay proxy CPU and you make the proxy's bandwidth the fleet's ceiling.
2. **Let connections churn.** The second row is the same L4 balancer with the same algorithm over ~15-second connections: spread falls to **1.31×** and the new instance gets **10.0%**. This is the configuration you had before the migration, and it is why nobody noticed the flaw for eighteen months.
3. **Bound connection age deliberately** — `max_connection_age`, which forces a graceful reconnect after a set time and hands the balancer a new decision. Rows three and four.
4. **Move the decision into the client** — client-side balancing, where the caller holds connections to many backends and picks per request. Lesson 5 builds this, along with the reason you cannot naively connect every client to every backend.

Option 3 comes with a trap severe enough that the mitigation is mandatory rather than advisable. In the third row `max_connection_age` is 300 s with no jitter, and the reconnect burst is **24 connections in a single second — every connection in the fleet, simultaneously.** The cause is a detail from the incident above: every connection was opened in the same second, at deploy time. Give them all an identical lifetime and you have not staggered anything, you have built a **synchronised** fleet whose connections expire together, forever, on a 300-second metronome. Every 300 seconds your backends take a full fleet's worth of TLS handshakes at once.

Add ±10% jitter — a random factor per connection — and the same row peaks at **2 reconnects per second, a 12× reduction**, with the rebalancing benefit intact (new instance at 10.7% versus 11.3%). This is the same thundering-herd result Phase 8 Lesson 11 proved for retry backoff, and the same fix: **the correlation is the problem, so randomise it away.** gRPC's own implementation multiplies `MAX_CONNECTION_AGE` by a random factor for exactly this reason. Configuring `max_connection_age` without jitter converts a load-distribution problem into a periodic self-inflicted connection storm — the fix and the outage are the same feature.

### Direct server return

Worth thirty seconds because it explains why L4 survives at the front of very large fleets. In a normal proxy topology every byte of the response travels back through the balancer, so **the balancer's bandwidth is the fleet's bandwidth ceiling**. Responses are usually far larger than requests, so that ceiling binds sooner than you expect.

**Direct server return** (DSR) breaks the symmetry. The balancer forwards the inbound packet to the chosen backend without rewriting the source address, and the backend replies **straight to the client**, bypassing the balancer entirely. The balancer now handles only the request path — often a twentieth of the bytes — so one balancer fronts far more backends than its own NIC could otherwise carry. Maglev uses this, as do hardware L4 balancers and IPVS in DSR mode.

The price is exactly the thing this lesson is about: **the balancer never sees the response.** It cannot know the status code, the response latency, or whether the backend answered at all. Passive outlier detection is impossible by construction, and health checking must be active, because the balancer's only remaining source of truth about a backend is a probe it sends on purpose. DSR is a bandwidth optimisation that costs you your entire feedback channel.

### Active vs passive health checking

There are two ways to learn that a backend is broken, and they fail in opposite directions.

**Active health checking**: the balancer sends a probe on an interval — an HTTP GET to `/healthz`, a gRPC health RPC, a bare TCP connect — and marks the backend down after some number of consecutive failures. It works on a backend receiving no traffic, which is what makes it the only way to bring a *new* or *recovered* instance into rotation. It costs traffic, and it tests the path the probe takes rather than the path your users take.

**Passive health checking** (Envoy calls it **outlier detection**): the balancer watches the outcomes of real requests it is already forwarding, and ejects a backend whose responses are anomalous — consecutive 5xx, consecutive gateway failures, or a success rate far below its peers. It costs nothing, it sees exactly the code path your users are on, and it detects failures a shallow probe can never see. It also **cannot see a backend that is receiving no traffic** — which is precisely the starved 9th instance from the section above. A passively-monitored backend with zero requests is indistinguishable from a healthy one, forever.

The Build It puts a number on the difference. A backend starts returning 500s on real requests while its `/healthz` keeps returning 200 — a shallow probe that does not touch the broken code path, which is the common case, not a contrived one. At a 100% error rate and 500 req/s, Envoy's `consecutive_5xx: 5` rule ejects it after **5 requests — 10 milliseconds.** No active probe on any interval in this lesson comes within three orders of magnitude of that, because the probe is testing something that works.

Then the same table's uncomfortable half. Drop the error rate to 20% and the identical rule needs **3,705 requests — 741× longer — and serves 741 users a 500 first, 148× the damage.** `consecutive_5xx` is a **total**-failure detector. Against the partial, intermittent failure that is far more common in production, it is nearly blind, and you need a success-rate rule instead — which brings its own trap, below.

**Active and passive are not alternatives. Run both**, because each is blind exactly where the other sees.

Now the arithmetic of active probing at fleet scale, which is the part that gets skipped. Every balancer probes every backend independently. With **M** balancers and **N** backends at interval **I**, the fleet-wide probe rate is:

```text
probes per second = M * N / I
```

That is a product, and both terms grow when you scale out. The Build It prices M = 6 balancers × N = 200 backends: at a 10-second interval that is **120 probes/s**, at 2 seconds it is **600 probes/s**, and at the 1-second interval of the twitchy row, **1,200 probes/s** — of traffic that serves no user. Worse, it is **quadratic in fleet size**: double both the balancer count and the backend count and the probe load goes up 4×. This is the Universal Scalability Law's **κ (kappa) term** from Lesson 2 — the coherency cost that grows with the square of the number of participants — wearing a different costume. Lesson 5 shows the same quadratic appearing in connection counts, and the same fix: subsetting, so that not every prober probes every target.

For a fleet in the low hundreds this cost is genuinely negligible, and the Build It's conclusion is that **probe traffic is the cheapest thing on the page** — you should spend it. At tens of thousands of backends it stops being negligible, and the answer is to reduce M and N (subsetting, hierarchical checking), not to lengthen I.

### Detection latency vs flapping

Four knobs decide when a backend leaves rotation: **interval** (how often you probe), **timeout** (how long you wait for an answer), **unhealthy_threshold** (consecutive failures before ejection) and **healthy_threshold** (consecutive successes before re-admission). The naive reading is that they trade off against one dimension — sensitivity. They do not, and the whole tuning strategy falls out of the difference.

Start with the arithmetic everyone should be able to do from memory. A Kubernetes readiness probe at its defaults — 10-second interval, 3 consecutive failures — takes:

```text
worst case  = interval x (unhealthy_threshold + 1) + timeout
            = 10 x 4 + 1  =  41 seconds
```

The measured mean over 2,000 trials, with the failure starting at a uniformly random moment inside a probe interval, is **25.9 seconds**. That is 25.9 seconds, on average, of the balancer **routing live user traffic into a backend that is already dead**. The AWS Application Load Balancer's out-of-the-box target group is worse: a 30-second interval and 2 failures give **49.8 s mean, 95 s worst case.** Nobody chose those numbers for your service. They are what you inherit.

So turn the threshold down to 1 and probe every second. Detection falls to **1.5 seconds** — and the cost arrives immediately. Consider a backend that is not broken but merely *jittery*: 3% of its probes exceed the timeout because of a garbage-collection pause, a noisy neighbour, a log rotation. With `unhealthy_threshold = 1`, every one of those is an ejection: **108 false ejections per hour per backend, which is 21,600 spurious ejections an hour across a 200-backend fleet.** You have not built a health check. You have built a random capacity remover.

The resolution is that **interval and threshold are different dials with different exponents.** Detection time is *linear* in both. But the probability of `k` consecutive false failures is `p^k` — **exponential in the threshold, and only linear in 1/interval.** So you can buy both properties at once by moving them in opposite directions:

```text
detection time     ~  interval x threshold          (linear, linear)
false ejections    ~  (probes/hour) x p^threshold   (linear, EXPONENTIAL)
```

Shorten the interval 5× (10 s → 2 s) *and* raise the threshold from 3 to 5, and the measured result beats the Kubernetes default in **both** columns simultaneously: detection **10.0 s instead of 25.9 s (2.6× faster)** and false ejections **4.4 × 10⁻⁵/hr instead of 9.7 × 10⁻³/hr (221× fewer)**. The entire bill is probe traffic: 600/s fleet-wide instead of 120/s.

`healthy_threshold` is the other half of the asymmetry, and it points the opposite way from everything above. It governs re-admission, and there you want to be *slow*, because a host that has been failing is a host you have evidence about. At `healthy_threshold = 5` a jittery backend is re-added after **11.0 s**; at 1, after **1.0 s** — one lucky probe. The second one flaps: in, out, in, out, with a share of live traffic taking the consequences on every cycle. The rule that comes out of this is worth memorising:

> **Fail fast, recover slow.** Short interval, high `unhealthy_threshold`, higher `healthy_threshold`. Detection stays quick because the interval is short; false ejections collapse because the threshold is an exponent; and recovery is deliberately unhurried because re-admitting a marginal host costs more than leaving it out.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 536" width="100%" style="max-width:840px" role="img" aria-label="A tuning table for the six health-check and outlier-detection knobs. For each knob it gives the cost of raising it, the cost of lowering it, and the recommended direction with the measured number that justifies it. Interval should be lowered to 2 seconds because detection time is linear in it and the only cost is probe traffic. Timeout should be raised to at least the p99.9 of the probe path, 3 seconds here, because a 1 second timeout fails 2.22 percent of probes to a healthy backend. Unhealthy threshold should be raised to 5 because false ejections fall exponentially as p to the power of the threshold. Healthy threshold should be raised to 5 so a marginal host cannot flap back in on one lucky probe. Max ejection percent should be held at 10 percent and panic threshold at 50 percent, because without them the measured fleet ejected itself from 20 healthy instances to zero. The first, third and fourth rows are bracketed as the asymmetry: fail fast, recover slow.">
  <defs>
    <marker id="p11-04-d4dn" markerWidth="9" markerHeight="9" refX="4" refY="6" orient="auto"><path d="M0,0 L8,0 L4,7 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="25" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Six knobs, and which way each one is wrong</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="43" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Detection time is LINEAR in interval and threshold. False ejections go as p^threshold — EXPONENTIAL.</text> <text x="440" y="57" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">That asymmetry is the whole tuning strategy: poll fast, count high, re-admit slowly.</text>
    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.6">
      <text x="34" y="80">KNOB &#183; THE DEFAULT YOU INHERIT</text> <text x="248" y="80">RAISING IT COSTS</text> <text x="470" y="80">LOWERING IT COSTS</text> <text x="866" y="80" text-anchor="end">GO THIS WAY &#183; MEASURED</text>
    </g>
    <path d="M28 86 L 866 86" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.45"/>
    <g fill="none" stroke-width="1.1" opacity="0.22" stroke="currentColor">
      <path d="M28 158 L 866 158"/> <path d="M28 230 L 866 230"/> <path d="M28 302 L 866 302"/> <path d="M28 374 L 866 374"/> <path d="M28 446 L 866 446"/>
    </g>
    <g fill="none" stroke-width="1.6">
      <rect x="28" y="94" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="28" y="166" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="28" y="238" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="28" y="310" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="28" y="382" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="28" y="454" width="184" height="56" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/> <rect x="694" y="94" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="694" y="166" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="694" y="238" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="694" y="310" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="694" y="382" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/> <rect x="694" y="454" width="172" height="56" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g fill="#7c5cff" font-size="10.5" font-weight="700">
      <text x="40" y="114">interval</text> <text x="40" y="186">timeout</text> <text x="40" y="258">unhealthy_threshold</text> <text x="40" y="330">healthy_threshold</text> <text x="40" y="402">max_ejection_percent</text> <text x="40" y="474">healthy_panic_threshold</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.8">
      <text x="40" y="128">k8s 10s &#183; ALB 30s</text> <text x="40" y="142">how often you ask</text> <text x="40" y="200">k8s 1s &#183; ALB 5s</text> <text x="40" y="214">how long you wait</text> <text x="40" y="272">k8s 3 &#183; ALB 2</text> <text x="40" y="286">fails in a row to eject</text> <text x="40" y="344">k8s 1 &#183; ALB 5</text> <text x="40" y="358">oks in a row to re-add</text> <text x="40" y="416">Envoy 10%</text> <text x="40" y="430">cap on hosts ejected</text> <text x="40" y="488">Envoy 50%</text> <text x="40" y="502">below this, ignore health</text>
    </g>
    <g fill="#e0930f" font-size="9" font-weight="700">
      <text x="224" y="112">detection time, linearly</text> <text x="224" y="184">detection time, directly</text> <text x="224" y="256">detection time, linearly</text> <text x="224" y="328">recovered capacity idles</text> <text x="224" y="400">THE DEATH SPIRAL</text> <text x="224" y="472">you route to known-dead hosts</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.85">
      <text x="224" y="126">10s x 3 fails = 25.9s mean of</text> <text x="224" y="139">live traffic into a dead host</text> <text x="224" y="198">worst case = interval x (th+1)</text> <text x="224" y="211">+ timeout. ALB: 95s</text> <text x="224" y="270">3 -&gt; 5 at a 2s interval moves</text> <text x="224" y="283">detection 6.0s -&gt; 10.0s only</text> <text x="224" y="342">a healed host waits 11.0s at 5</text> <text x="224" y="355">to be trusted again</text> <text x="224" y="414">at 100% the fleet went 20 -&gt; 0</text> <text x="224" y="427">healthy, 23s with NOTHING routed</text> <text x="224" y="486">panic is a last resort, not a</text> <text x="224" y="499">routing policy</text>
    </g>
    <g fill="#d64545" font-size="9" font-weight="700">
      <text x="452" y="112">probe traffic. That is all.</text> <text x="452" y="184">FALSE EJECTIONS, steeply</text> <text x="452" y="256">FALSE EJECTIONS, exponentially</text> <text x="452" y="328">flapping</text> <text x="452" y="400">broken hosts stay in rotation</text> <text x="452" y="472">the fleet ejects itself</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.85">
      <text x="452" y="126">M=6 balancers x N=200 backends</text> <text x="452" y="139">at 2s = 600 probes/s fleet-wide</text> <text x="452" y="198">1.0s is under the 1396ms p99, so</text> <text x="452" y="211">2.22% of HEALTHY probes fail</text> <text x="452" y="270">threshold 1 = 108 false ej/hr per</text> <text x="452" y="283">backend = 21,600/hr over 200</text> <text x="452" y="342">at 1, a marginal host is re-added</text> <text x="452" y="355">after 1.0s on one lucky probe</text> <text x="452" y="414">at 0% ejection is off; a host</text> <text x="452" y="427">serving 100% 5xx keeps traffic</text> <text x="452" y="486">at 0% panic never fires and the</text> <text x="452" y="499">spiral runs to completion</text>
    </g>
    <g fill="#0fa07f">
      <path d="M704 105 L 716 105 L 710 115 Z"/> <path d="M704 187 L 716 187 L 710 177 Z"/> <path d="M704 259 L 716 259 L 710 249 Z"/> <path d="M704 331 L 716 331 L 710 321 Z"/> <rect x="704" y="393" width="12" height="3.4" rx="1.2"/> <rect x="704" y="399.6" width="12" height="3.4" rx="1.2"/> <rect x="704" y="465" width="12" height="3.4" rx="1.2"/> <rect x="704" y="471.6" width="12" height="3.4" rx="1.2"/>
    </g>
    <g fill="#0fa07f" font-size="10" font-weight="700">
      <text x="724" y="115">LOWER &#183; 2s</text> <text x="724" y="187">RAISE &#183; 3s</text> <text x="724" y="259">RAISE &#183; 5</text> <text x="724" y="331">RAISE &#183; 5</text> <text x="724" y="403">HOLD &#183; 10%</text> <text x="724" y="475">KEEP &#183; 50%</text>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.85">
      <text x="706" y="130">the cheapest knob</text> <text x="706" y="143">on this page</text> <text x="706" y="202">= p99.9 of the probe</text> <text x="706" y="215">path (3225 ms)</text> <text x="706" y="274">4.4e-05 false ej/hr</text> <text x="706" y="287">vs 0.0485 at 3</text> <text x="706" y="346">re-add 11.0s, not 1.0s</text> <text x="706" y="359">fail fast, recover slow</text> <text x="706" y="418">min healthy 18/20 and</text> <text x="706" y="431">99.7% on time</text> <text x="706" y="489">21.3% -&gt; 65.4% on time</text> <text x="706" y="502">from this knob alone</text>
    </g>
    <path d="M20 96 L 12 96 L 12 364 L 20 364" fill="none" stroke="#3553ff" stroke-width="1.8" opacity="0.85"/> <text x="8" y="230" font-size="9.5" font-weight="700" fill="#3553ff" transform="rotate(-90 8 230)" text-anchor="middle">THE ASYMMETRY</text>
    <text x="440" y="524" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Net result of the top four rows: detection 25.9s -&gt; 10.0s AND 221x fewer false ejections. The bill is 480 extra probes/s.</text>
  </g>
</svg>
```

Now the knob that produces outages all by itself. **A probe timeout shorter than your p99 latency does not detect slow backends — it schedules false ejections.** The reasoning is one line: the probe timeout defines the latency above which a response counts as a failure, so if that threshold sits inside your *healthy* latency distribution, a fixed percentage of probes to a perfectly healthy backend fail forever.

The Build It samples 200,000 probe responses from a healthy backend with **p50 121 ms, p90 465 ms, p99 1,396 ms, p99.9 3,225 ms** — a normal, unremarkable, right-skewed latency distribution:

| probe timeout | P(probe times out) | false ejections/hr | across 200 backends, per day |
|---|---|---|---|
| 500 ms | 8.867% | 1.2537 | **6,018** |
| 1,000 ms | 2.218% | 0.0196 | **94** |
| 1,500 ms | 0.834% | 0.0010 | 5.0 |
| 2,000 ms | 0.392% | 0.00011 | 0.52 |
| 3,000 ms | 0.124% | 0.0000034 | **0.0165** |
| 5,000 ms | 0.028% | 0.000000039 | 0.00019 |

At the Kubernetes default `timeoutSeconds: 1`, **2.22% of probes to a completely healthy backend fail**, so three in a row happens **94 times a day across a 200-backend fleet**. Every one of those removes capacity from a fleet that was fine — which raises everyone else's utilisation, which raises everyone else's latency, which makes the next false ejection more likely. That is not a hypothetical; it is the input to the next section.

The rule is mechanical, and it is not "set the timeout to the p99":

> **Probe timeout ≥ p99.9 of the probe path.** Here that is 3,225 ms, so 3 s — which yields 0.0165 false ejections per fleet per day, one every 61 days — and never 1 s.

You give up detection speed for slow-but-alive backends, which is the correct trade because *that* case is what passive outlier detection is for. And note what the table does **not** say: it never says "make the timeout huge". At 5 s you are waiting 5 s to notice a hard failure. The p99.9 is the floor, not the target.

### The health-check death spiral

Every mechanism above is now assembled into one loop, and the loop has a direction.

A fleet gets busy. Queueing delay rises — Phase 8 Lesson 11 derived exactly why, `W = S/(1−ρ)`, and why the rise is a cliff rather than a slope. Probes queue behind the same backlog as user requests, so probe latency rises with everything else. Probes start exceeding the timeout. Instances are marked unhealthy and removed. **The load they were carrying does not disappear — it is redistributed onto the survivors**, which are already busy, and whose queueing delay therefore rises further. Their probes now time out too.

This is a **metastable failure** in the sense of Bronson et al., *Metastable Failures in Distributed Systems* (HotOS 2021): a sustaining feedback loop that no longer needs its trigger. Phase 8 Lesson 11 built one out of retries inside a single service. This one is built out of health checks across a fleet, and the ingredient that makes it vicious is that **the health check's own reaction is the thing that feeds it.**

The Build It measures it with a deliberately unspectacular trigger. Twenty instances, 88–111 req/s each, 2,027 req/s of total capacity. Demand runs at 80% of capacity, then steps up to **92%**. That is the entire event: a 12-point step, on a fleet that still has 8% headroom and 100% of the capacity that 92% demand requires. No crash, no dependency failure, no deploy.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 546" width="100%" style="max-width:840px" role="img" aria-label="The health-check death spiral. The top panel plots the measured count of healthy instances out of twenty over 120 seconds: with no guard the fleet holds at twenty until demand steps from 80 to 92 percent at t equals 30, then collapses, reaching zero healthy at t equals 74 and oscillating between zero and eleven for the rest of the run, spending 23 seconds with nothing in rotation at all; with panic mode and a 10 percent max ejection percent the same run settles at eighteen healthy and never falls further. The bottom panel draws the sustaining feedback loop: rising load makes queues grow, growing queues make probes time out, timed-out probes make the balancer eject an instance, and the ejection raises every survivor's share of the same unchanged load, which grows the queues again. The guards cut exactly one edge of that loop, the one from ejection to lost capacity.">
  <defs>
    <marker id="p11-04-a3" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker> <marker id="p11-04-a3n" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker> <marker id="p11-04-a3e" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A fleet that ejected itself: 20 healthy to 0, with nothing broken</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="304" y="52" width="552" height="192" fill="#e0930f" fill-opacity="0.06" stroke="none"/>
    <g fill="none" stroke="currentColor" stroke-width="1.4">
      <path d="M70 240 L 856 240"/> <path d="M70 240 L 70 52"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.3">
      <path d="M66 60 L 70 60"/> <path d="M66 105 L 70 105"/> <path d="M66 150 L 70 150"/> <path d="M66 195 L 70 195"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="end" opacity="0.75">
      <text x="60" y="243">0</text> <text x="60" y="198">5</text> <text x="60" y="153">10</text> <text x="60" y="108">15</text> <text x="60" y="63">20</text>
    </g>
    <text x="24" y="150" font-size="10" fill="currentColor" opacity="0.85" transform="rotate(-90 24 150)" text-anchor="middle">healthy instances</text>
    <path d="M70 150 L 856 150" fill="none" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="7 4"/> <path d="M304 244 L 304 52" fill="none" stroke="#e0930f" stroke-width="1.6"/>
    <path d="M 70.0 60.0 L 76.5 60.0 L 83.0 60.0 L 89.5 60.0 L 96.0 60.0 L 102.5 60.0 L 109.0 60.0 L 115.5 60.0 L 122.0 60.0 L 128.5 60.0 L 135.0 60.0 L 141.5 60.0 L 148.0 60.0 L 154.5 60.0 L 161.0 60.0 L 167.5 60.0 L 174.0 60.0 L 180.5 60.0 L 187.0 60.0 L 193.5 60.0 L 200.0 60.0 L 206.5 60.0 L 213.0 60.0 L 219.5 60.0 L 226.0 60.0 L 232.5 60.0 L 239.0 60.0 L 245.5 60.0 L 252.0 60.0 L 258.5 60.0 L 265.0 60.0 L 271.5 60.0 L 278.0 60.0 L 284.5 60.0 L 291.0 60.0 L 297.5 60.0 L 304.0 69.0 L 310.5 69.0 L 317.0 78.0 L 323.5 78.0 L 330.0 78.0 L 336.5 78.0 L 343.0 78.0 L 349.5 78.0 L 356.0 78.0 L 362.5 78.0 L 369.0 78.0 L 375.5 78.0 L 382.0 78.0 L 388.5 78.0 L 395.0 78.0 L 401.5 78.0 L 408.0 78.0 L 414.5 78.0 L 421.0 78.0 L 427.5 78.0 L 434.0 78.0 L 440.5 78.0 L 447.0 78.0 L 453.5 78.0 L 460.0 78.0 L 466.5 78.0 L 473.0 78.0 L 479.5 78.0 L 486.0 78.0 L 492.5 78.0 L 499.0 78.0 L 505.5 78.0 L 512.0 78.0 L 518.5 78.0 L 525.0 78.0 L 531.5 78.0 L 538.0 78.0 L 544.5 78.0 L 551.0 78.0 L 557.5 78.0 L 564.0 78.0 L 570.5 78.0 L 577.0 78.0 L 583.5 78.0 L 590.0 78.0 L 596.5 78.0 L 603.0 78.0 L 609.5 78.0 L 616.0 78.0 L 622.5 78.0 L 629.0 78.0 L 635.5 78.0 L 642.0 78.0 L 648.5 78.0 L 655.0 78.0 L 661.5 78.0 L 668.0 78.0 L 674.5 78.0 L 681.0 78.0 L 687.5 78.0 L 694.0 78.0 L 700.5 78.0 L 707.0 78.0 L 713.5 78.0 L 720.0 78.0 L 726.5 78.0 L 733.0 78.0 L 739.5 78.0 L 746.0 78.0 L 752.5 78.0 L 759.0 78.0 L 765.5 78.0 L 772.0 78.0 L 778.5 78.0 L 785.0 78.0 L 791.5 78.0 L 798.0 78.0 L 804.5 78.0 L 811.0 78.0 L 817.5 78.0 L 824.0 78.0 L 830.5 78.0 L 837.0 78.0 L 843.5 78.0 L 850.0 78.0" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M 70.0 60.0 L 76.5 60.0 L 83.0 60.0 L 89.5 60.0 L 96.0 60.0 L 102.5 60.0 L 109.0 60.0 L 115.5 60.0 L 122.0 60.0 L 128.5 60.0 L 135.0 60.0 L 141.5 60.0 L 148.0 60.0 L 154.5 60.0 L 161.0 60.0 L 167.5 60.0 L 174.0 60.0 L 180.5 60.0 L 187.0 60.0 L 193.5 60.0 L 200.0 60.0 L 206.5 60.0 L 213.0 60.0 L 219.5 60.0 L 226.0 60.0 L 232.5 60.0 L 239.0 60.0 L 245.5 60.0 L 252.0 60.0 L 258.5 60.0 L 265.0 60.0 L 271.5 60.0 L 278.0 60.0 L 284.5 60.0 L 291.0 60.0 L 297.5 60.0 L 304.0 69.0 L 310.5 69.0 L 317.0 78.0 L 323.5 87.0 L 330.0 87.0 L 336.5 96.0 L 343.0 105.0 L 349.5 105.0 L 356.0 96.0 L 362.5 150.0 L 369.0 150.0 L 375.5 177.0 L 382.0 204.0 L 388.5 222.0 L 395.0 186.0 L 401.5 186.0 L 408.0 168.0 L 414.5 186.0 L 421.0 186.0 L 427.5 177.0 L 434.0 204.0 L 440.5 204.0 L 447.0 231.0 L 453.5 231.0 L 460.0 222.0 L 466.5 222.0 L 473.0 195.0 L 479.5 195.0 L 486.0 177.0 L 492.5 177.0 L 499.0 186.0 L 505.5 204.0 L 512.0 231.0 L 518.5 222.0 L 525.0 195.0 L 531.5 186.0 L 538.0 204.0 L 544.5 231.0 L 551.0 240.0 L 557.5 240.0 L 564.0 186.0 L 570.5 177.0 L 577.0 177.0 L 583.5 213.0 L 590.0 222.0 L 596.5 213.0 L 603.0 231.0 L 609.5 231.0 L 616.0 240.0 L 622.5 222.0 L 629.0 222.0 L 635.5 204.0 L 642.0 168.0 L 648.5 150.0 L 655.0 168.0 L 661.5 213.0 L 668.0 231.0 L 674.5 222.0 L 681.0 231.0 L 687.5 231.0 L 694.0 240.0 L 700.5 240.0 L 707.0 204.0 L 713.5 168.0 L 720.0 159.0 L 726.5 186.0 L 733.0 222.0 L 739.5 213.0 L 746.0 213.0 L 752.5 204.0 L 759.0 222.0 L 765.5 231.0 L 772.0 240.0 L 778.5 231.0 L 785.0 204.0 L 791.5 141.0 L 798.0 150.0 L 804.5 177.0 L 811.0 240.0 L 817.5 240.0 L 824.0 240.0 L 830.5 240.0 L 837.0 231.0 L 843.5 231.0 L 850.0 231.0" fill="none" stroke="#d64545" stroke-width="2.4" stroke-linejoin="round"/>
    <circle cx="551" cy="240" r="5" fill="none" stroke="#d64545" stroke-width="2.2"/>
    <g fill="currentColor">
      <text x="70" y="256" font-size="9" opacity="0.75">t=0</text> <text x="304" y="256" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">t=30 s</text> <text x="551" y="256" font-size="9" text-anchor="middle" font-weight="700" fill="#d64545">t=74 s</text> <text x="856" y="256" font-size="9" text-anchor="end" opacity="0.75">t=120 s</text> <text x="312" y="46" font-size="9.5" font-weight="700" fill="#e0930f">demand steps 80% -&gt; 92% of fleet capacity. That is the entire trigger.</text> <text x="80" y="145" font-size="9" font-weight="700" fill="#e0930f">panic threshold — 50% of 20</text> <text x="440" y="276" font-size="9.5" font-weight="700" fill="#d64545" text-anchor="middle">the first tick with nothing in rotation at all — 23 s of the run were spent there</text> <text x="84" y="196" font-size="10" font-weight="700" fill="#0fa07f">— panic 50% + max_ejection 10%</text>
      <text x="84" y="210" font-size="8.5" opacity="0.9" fill="#0fa07f">floors at 18/20 · 99.7% delivered on time</text> <text x="84" y="228" font-size="10" font-weight="700" fill="#d64545">— no guard</text> <text x="84" y="238" font-size="8.5" opacity="0.9" fill="#d64545">20 to 0 in 44 s · 21.3% on time</text>
    </g>
    <text x="440" y="300" font-size="12.5" font-weight="700" text-anchor="middle" fill="currentColor">the loop underneath it — and the one edge you are allowed to cut</text>
    <g fill="none" stroke-width="1.9" stroke-linejoin="round">
      <rect x="16" y="316" width="126" height="62" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="6 4"/> <rect x="182" y="316" width="176" height="62" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/> <rect x="392" y="316" width="176" height="62" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/> <rect x="602" y="316" width="176" height="62" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="79" y="338" font-size="10" font-weight="700" fill="#e0930f">TRIGGER</text> <text x="79" y="353" font-size="8.5" opacity="0.9">demand 80% -&gt; 92%</text> <text x="79" y="367" font-size="8.5" opacity="0.9">no failure anywhere</text> <text x="270" y="338" font-size="10.5" font-weight="700">backlogs grow</text> <text x="270" y="353" font-size="8.5" opacity="0.9">queueing delay passes the</text> <text x="270" y="367" font-size="8.5" opacity="0.9">400 ms probe timeout</text>
      <text x="480" y="338" font-size="10.5" font-weight="700">3 probes fail in a row</text> <text x="480" y="353" font-size="8.5" opacity="0.9">the balancer ejects the</text> <text x="480" y="367" font-size="8.5" opacity="0.9">instance, correctly</text> <text x="690" y="338" font-size="10.5" font-weight="700">capacity leaves rotation</text> <text x="690" y="353" font-size="8.5" opacity="0.9">survivors now split the same</text> <text x="690" y="367" font-size="8.5" opacity="0.9">unchanged load between fewer</text>
    </g>
    <path d="M142 347 L 176 347" fill="none" stroke="#e0930f" stroke-width="1.9" stroke-dasharray="5 4" marker-end="url(#p11-04-a3e)"/>
    <g fill="none" stroke="#d64545" stroke-width="1.9">
      <path d="M358 347 L 386 347" marker-end="url(#p11-04-a3)"/> <path d="M568 347 L 596 347" marker-end="url(#p11-04-a3)"/> <path d="M778 347 C 826 347, 838 404, 790 412 L 250 412 C 214 412, 208 392, 210 382" marker-end="url(#p11-04-a3)"/>
    </g>
    <text x="322" y="430" font-size="9.5" font-weight="700" text-anchor="middle" fill="#d64545">the loop is now self-sustaining: the trigger is no longer needed</text>
    <path d="M584 306 L 584 392" fill="none" stroke="#0fa07f" stroke-width="3.4"/> <path d="M572 316 L 596 300" fill="none" stroke="#0fa07f" stroke-width="3.4"/>
    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="330" y="446" width="510" height="60" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <path d="M584 392 L 584 434 C 584 442, 600 442, 620 446" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="5 4"/>
    <g fill="currentColor">
      <text x="344" y="464" font-size="10" font-weight="700" fill="#0fa07f">CUT HERE — the only edge the balancer controls</text> <text x="344" y="480" font-size="9">max_ejection_percent 10%: never remove more than 2 of 20, whatever health says</text> <text x="344" y="495" font-size="9">panic mode 50%: if most of the fleet looks dead, distrust the CHECK, not the fleet</text> <text x="16" y="464" font-size="9" opacity="0.85">You cannot stop</text> <text x="16" y="478" font-size="9" opacity="0.85">queues growing or</text> <text x="16" y="492" font-size="9" opacity="0.85">probes timing out.</text> <text x="176" y="464" font-size="9" opacity="0.85">You can stop the</text> <text x="176" y="478" font-size="9" opacity="0.85">ejection from being</text> <text x="176" y="492" font-size="9" opacity="0.85">unbounded.</text>
    </g>
    <text x="440" y="530" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Neither guard adds capacity. Measured: on-time delivery 21.3% without them, 99.7% with — from 12 points of extra load.</text>
  </g>
</svg>
```

**44 seconds after the step, the fleet has zero healthy instances**, and it spends **23 seconds of the run with nothing in rotation at all** — every request getting a 503 from a fleet of twenty working machines. The oscillation after the collapse is the flapping signature: instances drain their backlog while ejected, pass 5 probes, get re-admitted, immediately receive a share of a load that is now concentrated on a handful of hosts, and fail out again.

The measured outcome across the four configurations:

| guard | served | **on time** | min healthy | seconds with nothing routed |
|---|---|---|---|---|
| none (the out-of-the-box config) | 88.0% | **21.3%** | 0/20 | 23 |
| panic mode @ 50% healthy | 99.8% | **65.4%** | 0/20 | 0 |
| `max_ejection_percent` = 10% | 99.9% | **99.7%** | 18/20 | 0 |
| panic 50% + max_ejection 10% | 99.9% | **99.7%** | 18/20 | 0 |

"On time" counts responses delivered while the caller was still waiting — the goodput idea from Phase 8 Lesson 11, which is the only number here a user can feel. **21.3% without a guard, 99.7% with one.** Neither guard adds a single request per second of capacity to the fleet. They only stop the balancer from throwing away capacity it already had, and that was the entire gap.

Two details worth noticing in that table. First, the `served` column barely moves (88.0% → 99.9%) while `on time` moves by 78 points: the fleet was *completing* most requests all along, just far too late for anyone to want them — throughput was never the symptom. Second, panic mode alone leaves `min healthy` at 0/20 and still gets 65.4% on time. That is the mechanism working as designed: panic mode does not stop instances being marked unhealthy, it stops the balancer from **acting** on it.

### Panic mode and minimum healthy percentage

Here is the mitigation that sounds like a bug until you see the loop above:

> **When more than X% of the fleet is unhealthy, ignore health status entirely and route to everything.**

State it as Bayesian reasoning and it stops being strange. You have two competing explanations for "80% of my backends just failed their health check". One: 80% of your backends genuinely broke, independently, in the same ten seconds. Two: **your health checking is wrong** — the probe timeout is too tight, a shared dependency is slow, a config push broke the probe path, or a spiral like section 4's is under way. The second explanation is overwhelmingly more likely, because independent failures do not correlate like that and correlated ones usually have a common cause that is not "the servers died".

And the decision is asymmetric in cost. If you are wrong to panic, you route some traffic to some broken backends and those requests fail — bad. If you are wrong *not* to panic, you route traffic to nothing at all and **every** request fails — catastrophic. Envoy's `healthy_panic_threshold` defaults to **50%**, and the measured effect of that one boolean in the table above is 21.3% → 65.4% on-time delivery.

Three more guards belong in the same family:

- **`max_ejection_percent`** (Envoy default **10%**) is a hard cap on how much of a cluster outlier detection may remove, whatever the health signals say. It is the strongest single guard measured here — **99.7% on time, floor of 18/20 healthy** — because it bounds the loop's gain directly rather than reacting after the fact. Panic mode is a rescue; `max_ejection_percent` is a constraint that means the rescue is never needed. The lower bound matters too: at 0% you have disabled ejection entirely, and a host serving 100% 5xx keeps its traffic forever.
- **Ejection backoff.** Envoy ejects for `base_ejection_time × (times ejected)`, capped by `max_ejection_time`. With a 30 s base and a 300 s cap, a host ejected 12 times is out for 30, 60, 90 … 300, 300, 300 seconds — **38 minutes total, not 6.** Repeat offenders earn increasing quarantine, which is what stops a marginal host from cycling back into rotation every 30 seconds forever.
- **Minimum request volume**, which is the one engineers most often omit when they write this themselves. A rule as reasonable-sounding as *"eject if the error rate exceeds 10% in the evaluation window"* is a **sample-size trap**. Give six backends an identical, healthy 1% true error rate and vary only their traffic:

| requests in the window | P(window looks >10% bad) | false ejections/hr | per day, across 200 such backends |
|---|---|---|---|
| 5 | 4.9010% | **17.64** | **84,689** |
| 10 | 0.4266% | 1.5358 | 7,372 |
| 20 | 0.1004% | 0.3613 | 1,734 |
| 50 | 0.0011% | 0.0039 | 18.8 |
| 100 (Envoy's default minimum) | ~0.0000% | 0.0000023 | **0.011** |
| 500 | ~0 | 8.8 × 10⁻³² | 4.2 × 10⁻²⁸ |

At 5 requests per window, one unlucky error reads as a **20% error rate**, and this perfectly healthy backend is ejected **17.6 times an hour — 7.8 million times more often than the identical backend measured over 100 requests.** Nothing about the backends differs except how many samples you took. This is why Envoy will not apply its success-rate rule until a host has served `success_rate_request_volume` (default **100**) requests in the interval and `success_rate_minimum_hosts` (default **5**) hosts qualify.

The sting: **the quietest backend is always the most likely victim**, and the quietest backend is often the newest one — the instance that just came up, that has the least traffic, and that you least want to eject. Low volume and "recently deployed" are the same population.

### Failing open, failing closed, and the deep health check

**Failing closed** means treating unknown as unhealthy: if you cannot confirm a backend is good, do not send it traffic. It is the right default for a single backend and the wrong default for a correlated signal, because "I cannot confirm anything about anyone" then removes everything. **Failing open** means treating unknown as healthy. Panic mode is failing open, applied at a threshold; `max_ejection_percent` is failing open, applied as a quota.

Which brings us to the most common self-inflicted outage in this lesson, and it is a design decision that looks like diligence. A **deep health check** verifies the backend's dependencies: `/healthz` opens a database connection, runs `SELECT 1`, pings the cache, and returns 200 only if all of it works. It feels more honest than a shallow check that returns 200 from the web layer. It is a **correlated failure generator**.

Trace it. All 200 instances share one database. The database has a 4-second hiccup — a failover, a lock convoy, a slow vacuum. All 200 health checks fail **in the same window**, because they are all asking the same question of the same machine. All 200 instances are ejected simultaneously. The database recovers 4 seconds later and there is now nothing in rotation to serve traffic; worse, all 200 instances then reconnect and re-warm at once against a database that just restarted. **A 4-second database blip became a total outage, and the health check is what converted it.**

The distinction to hold onto:

- **A health check should answer "can *this instance* serve traffic?"** — its own threads, its own memory, its own warm-up state, its own local config. That is a signal that is genuinely independent across instances, which is what makes ejecting on it safe.
- **A shared dependency being down is not something you fix by removing instances.** If the database is down, every instance is equally affected and ejecting any of them helps nobody. Handle it with the tools from Phase 8 Lesson 11 — circuit breakers, degraded responses, shedding — inside the instance, and let the instance keep reporting healthy so it can serve the degraded response and the endpoints that do not need the database at all.

If you want a dependency-aware check, make it a **separate endpoint on a separate signal**: `/healthz` (shallow, drives the balancer) and `/readyz` or a monitoring-only `/health/deep` (deep, drives alerts and dashboards). [Health Checks, Readiness & Graceful Shutdown](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/) covers what belongs inside those endpoints; the point here is the balancer's side of the contract — **only wire an independent signal to an action that removes capacity.**

## Build It

[`code/health_and_layers.py`](code/health_and_layers.py) is five numbered arguments — stdlib only, seeded with fixed values so every number reproduces, and about a second end to end. No sockets: the layer-4/layer-7 distinction and the death spiral are both *decision* problems, and simulating them is honest because every parameter is stated and printed.

**Section 1's entire L4-vs-L7 difference is where the loop over `k` sits.** In `l4` mode the backend is a property of the connection; in `l7` mode it is chosen per request. That is the whole change — the round-robin cursor is identical:

```python
if mode == "l4":
    b = assigned[c]          # decided at connection setup, frozen since
    total[b] += k
    ...
else:
    for _ in range(k):       # a fresh decision, every single request
        b = rr_req % n_live
        rr_req += 1
        total[b] += 1
```

And the moment an L4 balancer is allowed to think — the only one — is the reconnect:

```python
if t >= deadline[c]:
    # The connection went away and the client immediately reopened it.
    # THIS is the only moment an L4 balancer gets to make a decision.
    reconnects_per_s[t] += 1
    assigned[c] = rr_conn % n_live      # n_live now includes the new backend
    rr_conn += 1
    deadline[c] = min(expiry(float(t)), natural_close(float(t)))
```

`n_live` is what lets a new backend in, and `deadline[c]` is what decides how often that happens. With `max_age = None` and `conn_lifetime = None`, `deadline` is infinity and the block never runs — which is the starved 9th instance, in one line. The jitter is in `expiry`, and it is three characters of arithmetic doing all the work:

```python
def expiry(t: float) -> float:
    if max_age is None:
        return float("inf")
    # gRPC multiplies MAX_CONNECTION_AGE by a random factor in [1-j, 1+j].
    return t + max_age * (1.0 + rng.uniform(-age_jitter, age_jitter))
```

**Section 2's `Checker` is the balancer's health state machine**, and the detail that makes it honest is that a failing probe is not known to have failed until its timeout expires — so `timeout` is added to detection latency, not hidden inside the interval:

```python
def probe(self, t: float, ok: bool) -> None:
    # A failing probe is only KNOWN to have failed once the timeout expires.
    decided = t + (0.0 if ok else self.timeout)
```

Sections 2, 3 and 5 each pair a closed-form calculation with a straight simulation, so the arithmetic in the prose is checkable rather than asserted. The false-ejection rate is `(probes_per_hour − k + 1) × p^k`; 300 simulated backend-hours of the Kubernetes default produced 2 ejections (0.0067/hr) against the formula's 0.0097/hr, and 600 backend-hours at a 1.0 s probe timeout produced 14 (0.023/hr) against 0.020/hr. Section 5(c) uses an exact binomial tail rather than sampling, because the interesting probabilities are down at 10⁻³².

**Section 4 is the death spiral, and the line that makes it a spiral rather than a wobble is the backlog.** An ejected instance does not become fast instantly — it has to drain what it already accepted, and that lag is the loop's memory:

```python
wait = backlog[i] / cap[i]      # what a request arriving now must wait
work = backlog[i] + arrivals
done = min(cap[i], work)
backlog[i] = work - done
...
# Probe. The answer an instance gives is gated by the backlog in front of it.
for i in range(FLEET):
    w = backlog[i] / cap[i]
    checkers[i].probe(float(t), ok=(w <= PROBE_TIMEOUT))
```

The probe result is derived from the same backlog that serves users. Nothing is injected, no failure is simulated: **the health check is measuring the queueing delay that the health check's own ejections are creating.** The two guards are eight lines between them, applied before routing:

```python
# --- guard 1: max_ejection_percent — the balancer refuses to eject more.
if guard in ("maxeject10", "both"):
    keep = FLEET - int(FLEET * 0.10)
    if len(healthy) < keep:
        ranked = sorted(range(FLEET),
                        key=lambda i: (not checkers[i].healthy, checkers[i].fails))
        healthy = sorted(ranked[:keep])
# --- guard 2: panic mode — below the threshold, health status is ignored.
routed, panic = healthy, False
if guard in ("panic50", "both") and len(healthy) < 0.50 * FLEET:
    routed, panic = list(range(FLEET)), True
```

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/04-l4-l7-health-checks-and-ejection/code/health_and_layers.py
```

```console
Layer 4 vs Layer 7, Health Checks & Outlier Ejection — Phase 11, Lesson 04
All numbers below are produced by this file. Seeded; rerunning reproduces them.

== 1 · L4 BALANCES CONNECTIONS. L7 BALANCES REQUESTS. ==
  24 client connections, 8 backends, a 9th joins at t=300s.
  per-connection request rate is lognormal: min 0.85/s, median 5.84/s, max 14.75/s
  offered load 137 req/s for 900s; the balancer is round-robin in both modes.

  config                                     hottest  coldest  spread   new-inst   burst
                                              share    share    x        share      /s
  L4  gRPC: connections never close           22.6%     6.8%    3.3      0.0%       0
  L4  HTTP/1.1 churn: conn ~15s               12.5%     9.6%    1.3     10.0%       7
  L4  max_connection_age 300s, NO jitter      14.4%     7.7%    1.9     11.3%      24
  L4  max_connection_age 300s, +/-10% jitter  15.1%     7.9%    1.9     10.7%       2
  L7  proxy: decide per request               11.1%    11.1%    1.0     11.1%       0
  ...
  max_connection_age without jitter: every connection was opened in the same second,
  so every connection expires in the same second — 24 simultaneous reconnects,
  12x the 2/s peak with +/-10% jitter. The fix and the
  outage are the same feature; the jitter is the entire difference.
  ...
== 2 · DETECTION LATENCY VS FLAPPING: TWO DIALS, NOT ONE ==
  Backend A dies hard at a uniformly random moment inside a probe interval
  (2,000 trials per config), so 'detect' is measured, not best-cased.
  Backend B is merely jittery: p=0.03 of its probes exceed the timeout — a periodic
  GC pause, a noisy neighbour, a log rotation. Nothing about it is broken.
  False ejections are exact: (probes/hr - k + 1) x p^k. Probe cost prices M=6
  balancers x N=200 backends, every balancer probing every backend.

  config                                  detect     worst   false ej   re-add   probes/s
                                          mean       case    /hr        after    fleet-wide
  k8s readiness default   10s/1s   3 / 1   25.9s    41.0s   9.7e-03    10.3s       120
  AWS ALB default         30s/5s   2 / 5   49.8s    95.0s    0.1071   164.5s        40
  twitchy                  1s/1s   1 / 1    1.5s     3.0s  108.0000     1.0s      1200
  fast poll, same count    2s/1s   3 / 2    6.0s     9.0s    0.0485     4.2s       600
  ASYMMETRIC               2s/1s   5 / 5   10.0s    13.0s   4.4e-05    11.0s       600
  ...
  Validation: 300 simulated backend-hours of the k8s default gave 2 false
  ejections = 0.0067/hr; the arithmetic said 0.0097/hr.
  ...
  The ASYMMETRIC row wins BOTH columns against every default above:
    detect  10.0s   vs 25.9s (k8s) and 49.8s (ALB)  -> 2.6x faster
    false  4.4e-05/hr vs 0.00967 and 0.10710      -> 221x fewer
  ...
== 3 · A PROBE TIMEOUT BELOW YOUR p99 IS A SCHEDULED FALSE EJECTION ==
  A perfectly healthy backend, 200,000 sampled probe responses (lognormal):
    p50    121 ms   p90    465 ms   p99   1396 ms   p99.9   3225 ms
  Health checks at interval=2s, unhealthy_threshold=3 -> 1800 probes/hour/backend.

  probe     P(probe            expected false     ...across a 200-backend
  timeout   times out)         ejections/hr       fleet, per day
    500 ms    8.867%             1.2537       6017.7552  <- below p99
   1000 ms    2.218%             0.0196         94.1070  <- below p99
   1500 ms    0.834%            1.0e-03          5.0064
   2000 ms    0.392%            1.1e-04          0.5199
   3000 ms    0.124%            3.4e-06          0.0165
   5000 ms    0.028%            3.9e-08         1.9e-04  <- above p99.9
  ...
  Simulated 600 backend-hours at a 1.0 s timeout: 14 ejections = 0.023/hour
  (arithmetic said 0.020). Nothing was wrong with the backend in any of them.
  ...
  Rule: probe timeout >= p99.9 of the probe path. Here that is 3225 ms, so 3 s
  (0.0165 false ejections/fleet/day — one every 61 days) and never 1 s.
  ...
== 4 · THE HEALTH-CHECK DEATH SPIRAL, MEASURED ==
  20 instances, 88-111 req/s each (2027 req/s total). Round-robin.
  Demand is 80% of fleet capacity (1622 req/s) until t=30s,
  then steps up to 92% (1865 req/s). That is the entire trigger:
  a 12-point step in demand on a fleet with 8% headroom left.
  NO GUARD:
    tick  healthy  routed  req/inst    backlog   served   on time
       0     20/20     20      81.1          0   100.0%  100.0%
      10     20/20     20      81.1         13    99.9%   99.9%
      20     20/20     20      81.1          4   100.0%  100.0%
      30     20/20     20      93.2         30    99.9%   99.9%
    ...
      44     16/20     16     116.6        132    98.5%   98.3%
      46     10/20     10     186.5        284    97.5%   95.8%
      48      4/20      4     466.2        646    96.0%   92.2%
    ...
      84      0/20      0       0.0       4067    88.8%   55.7%  <-- NOTHING HEALTHY: every request 503s
      90      8/20      8     233.1       3535    87.9%   52.8%
  ...
  guard                              served   on time   min healthy   sec with
                                                                      nothing routed
  none (the out-of-the-box config)    88.0%     21.3%        0/20            23
  panic mode @ 50% healthy            99.8%     65.4%        0/20             0
  max_ejection_percent = 10%          99.9%     99.7%       18/20             0
  panic 50% + max_ejection 10%        99.9%     99.7%       18/20             0
  ...
  With no guard the fleet ejected itself to ZERO healthy instances at t=74s —
  44s after a 12-point step in demand — and spent 23s of the run with
  nothing in rotation at all. Nothing crashed. No dependency broke. No deploy went
  out. The health check measured the queueing delay it was itself creating, removed
  an instance, and thereby raised every remaining instance's share of the same
  unchanged load. The fleet always had 100% of the capacity the 92% demand needed.
  ...
  Delivered on time:   21.3% with no guard
                       65.4% with panic mode alone      (+44.1 points)
                       99.7% with max_ejection alone     (+78.4 points)
                       99.7% with both                   (+78.4 points)
  ...
== 5 · PASSIVE OUTLIER EJECTION: THE 5xx YOUR PROBE NEVER SEES ==
  A backend starts failing real requests at t=0. Its /healthz still returns 200 —
  it is a shallow check and does not touch the broken code path, so NO active health
  check will ever eject this host. Traffic to it: 500 req/s.

  true error rate   consecutive_5xx=5 ejects after   errors served first
       100%                 5 req /     10.0 ms             5
        80%                10 req /     20.0 ms             8
        60%                29 req /     58.8 ms            18
        40%               167 req /    334.6 ms            67
        20%              3705 req /   7410.2 ms           741
  ...
  At a 100% error rate, passive detection ejects in 10 ms after 5 bad responses —
  a detector no active probe can match, because the probe is testing a path that
  works. At a 20% error rate the same rule needs 3705 requests — 741x longer — and
  serves 741 users a 500 first, 148x the damage. consecutive_5xx is a
  TOTAL-failure detector; it is nearly blind to the partial failure that is far
  more common.
  ...
    ejection 1..12 -> 30 60 90 120 150 180 210 240 270 300 300 300 s   (total 38 min out of rotation)
  ...
  A rule everyone writes: 'eject if error rate > 10% in the evaluation window'.
  Every backend below has the SAME true error rate: 1.0%. None of them is broken.

  requests in     P(window looks       false ejections   ...per day across
  the window      >10% bad)           per hour          200 such backends
         5          4.9010%         17.6436      84689.1938
        10          0.4266%          1.5358       7371.9940
        20          0.1004%          0.3613       1734.1796
        50          0.0011%         3.9e-03         18.8297
       100          0.0000%         2.3e-06          0.0108  <- Envoy's default minimum
       500          0.0000%         8.8e-32         4.2e-28
  ...
  At 5 requests per window a single unlucky error reads as a 20% error rate, so this
  perfectly healthy backend is ejected 17.6 times an hour — 7.83e+06 times more often
  than the identical backend measured over 100 requests (2.3e-06/hr). That is not health.
  It is sample size. This is why Envoy will not apply its success-rate rule until a
  host has served success_rate_request_volume (default 100) requests in the interval,
  and until success_rate_minimum_hosts (default 5) hosts qualify: below that, the rule
  is ejecting noise, and the quietest backend is always the most likely victim.
  ...
  (total wall time 2.6 s)
```

Read the sections as an argument rather than a demo.

**Section 1** is the lesson's thesis in one table. The balancer divided the connections perfectly and produced a **3.3× request spread**, and the L7 row shows the same round-robin producing **1.00×** — so the algorithm was never the variable. The `new-inst` column is the operational sting: **0.0%** under never-closing connections against 11.1% at L7. The last two rows are the trap inside the fix: `max_connection_age` without jitter produced a **24-per-second reconnect burst**, 12× the jittered run's 2/s, for the same rebalancing benefit.

**Section 2** replaces intuition with two exponents. The Kubernetes default blackholes traffic into a dead backend for **25.9 s on average, 41 s worst case**; the ALB default for **49.8 s / 95 s**. Reacting by dropping the threshold to 1 costs **108 false ejections per hour per backend — 21,600/hr across 200 backends.** The asymmetric row wins both columns at once — **10.0 s detection and 4.4 × 10⁻⁵ false ejections/hr, 2.6× faster and 221× fewer** — because shortening the interval is linear and raising the threshold is exponential. The bill is 600 probes/s fleet-wide instead of 120.

**Section 3** makes the timeout rule non-negotiable. Against a healthy backend with a **1,396 ms p99**, a 1-second probe timeout fails **2.22% of probes**, which is **94 false ejections per day across 200 backends** — all of them removing capacity from a fleet that was fine. A 3-second timeout, just above the **3,225 ms p99.9**, gives one false ejection every 61 days. Same fleet, same code, one config value.

**Section 4** is the outage. A **12-point step in demand** — from 80% to 92% of capacity, with the capacity to serve it — took the fleet from 20 healthy instances to **0 in 44 seconds**, left **23 seconds with nothing in rotation**, and delivered **21.3% of requests on time**. Turning on `max_ejection_percent = 10%` — a cap, not a capability — returns **99.7%**. The `served` column moving only 88.0% → 99.9% while `on time` moves 21.3% → 99.7% is the tell: the fleet was completing the work all along and delivering it too late to matter.

**Section 5** prices passive detection in both directions. `consecutive_5xx: 5` ejects a totally-broken backend in **10 ms after 5 bad responses**, which no active probe can approach — and needs **3,705 requests and 741 burned users** at a 20% error rate, which is the failure mode you actually get. Then the sample-size table, which is the one to show anyone writing their own ejection rule: six backends with an **identical 1% error rate**, ejected **17.6 times an hour at 5 requests per window and 0.0000023 at 100** — a factor of **7.8 million**, entirely manufactured by sample size.

## Use It

**Envoy** is the reference implementation, and its knob names are the vocabulary the rest of the industry borrowed. Active checking lives on the cluster:

```yaml
clusters:
  - name: pricing
    type: EDS
    lb_policy: LEAST_REQUEST
    health_checks:
      - interval: 2s                  # poll fast: detection is LINEAR in this
        timeout: 3s                   # >= p99.9 of the probe path, NOT the p99
        unhealthy_threshold: 5        # false ejections are p^5 — exponential
        healthy_threshold: 5          # fail fast, recover slow
        interval_jitter: 500ms        # decorrelate probes across balancers
        no_traffic_interval: 60s      # idle clusters: probe lazily, save the traffic
        http_health_check:
          path: /healthz              # SHALLOW. No database. See below.
```

`interval_jitter` matters for the same reason `max_connection_age` jitter did: without it, M balancers configured identically probe every backend in lockstep, and your probe traffic arrives as a spike rather than a stream. `no_traffic_interval` (default 60 s) is the small optimisation that acknowledges the κ arithmetic — a cluster receiving no traffic is probed lazily until it does.

Passive detection is a separate block, and it is where the guards live:

```yaml
outlier_detection:
  consecutive_5xx: 5                     # total-failure detector: ~10 ms at 500 rps
  consecutive_gateway_failure: 5
  interval: 10s
  base_ejection_time: 30s                # x times-ejected: 12 ejections = 38 min out
  max_ejection_time: 300s
  max_ejection_percent: 10               # THE guard. 99.7% on time vs 21.3%.
  success_rate_minimum_hosts: 5          # partial-failure detector, with a sample-size floor
  success_rate_request_volume: 100       # below this, you are ejecting noise
  success_rate_stdev_factor: 1900        # 1.9 standard deviations below the fleet mean

common_lb_config:
  healthy_panic_threshold:
    value: 50                            # below 50% healthy, ignore health entirely
```

Envoy's defaults are mostly good and the two most commonly wrong are on the active side: **`timeout` and `unhealthy_threshold`**. Copying the Kubernetes-style `timeout: 1s` onto a service whose p99 is 1.4 s is the 94-false-ejections-per-day configuration measured above.

**AWS target groups** use different names for the same four dials, and their defaults are slower than most teams assume:

```bash
aws elbv2 modify-target-group --target-group-arn "$TG" \
  --health-check-interval-seconds 10 \
  --health-check-timeout-seconds 6 \
  --healthy-threshold-count 5 \
  --unhealthy-threshold-count 3
# and, separately, the one that is not a health check but behaves like one:
aws elbv2 modify-target-group-attributes --target-group-arn "$TG" \
  --attributes Key=deregistration_delay.timeout_seconds,Value=30
```

`HealthCheckIntervalSeconds` defaults to 30 and `HealthyThresholdCount` to 5, which is the 49.8 s mean / 95 s worst-case detection from section 2. Note the constraint AWS enforces: the timeout must be less than the interval, so you cannot set a 3 s timeout on a 2 s interval — you need `interval ≥ timeout + 1`, which is why the 10 s / 6 s pairing above. **`deregistration_delay.timeout_seconds`** (default 300) is the other half of this story and belongs in the same review: it is how long the balancer keeps draining in-flight requests to a target you removed on purpose. Too short and you cut live requests during a deploy; 300 s is usually far longer than your longest request and slows every rolling deploy accordingly. [Deployment Strategies](../../10-infrastructure-and-deployment/11-deployment-strategies/) covers the deploy side; the graceful-shutdown handshake on the application side is Phase 9 Lesson 8.

**Kubernetes** deserves its own warning, because the coupling is not obvious and it is the mechanism behind the deep-health-check outage above. A `readinessProbe` does not merely annotate a pod. **The kubelet's readiness result drives the pod's presence in the Service's EndpointSlice, and the EndpointSlice is what kube-proxy and every ingress controller route from.** In Kubernetes, **the readiness probe *is* the load-balancer health check.** There is no second, separate check that a more conservative balancer might weigh against it.

```yaml
readinessProbe:
  httpGet: { path: /healthz, port: 8080 }   # shallow: no database, no cache, no peers
  periodSeconds: 2                          # poll fast
  timeoutSeconds: 3                         # >= p99.9 of THIS endpoint
  failureThreshold: 5                       # exponential protection against jitter
  successThreshold: 1                       # k8s FORCES 1 here — see below
livenessProbe:
  httpGet: { path: /livez, port: 8080 }     # a DIFFERENT, even shallower endpoint
  periodSeconds: 10
  failureThreshold: 6                       # liveness restarts the container. Be slow.
```

Three consequences fall out of that coupling:

1. **A readiness probe that queries the database can eject an entire Deployment at once.** Every replica asks the same database the same question; a 4-second blip fails every replica's probe simultaneously; every pod leaves the EndpointSlice together. Kubernetes has **no panic mode and no `max_ejection_percent`** — nothing stops an Endpoints list from going empty. This is the single most important sentence in this section: **the guard that saved the fleet in section 4 does not exist in the layer most teams deploy on.** Keep readiness shallow and independent, or supply the guard yourself with a `PodDisruptionBudget` and a service mesh that has one.
2. **`successThreshold` is forced to 1 for readiness probes** — the API rejects anything else. You cannot express "recover slow" here, so a flapping pod re-enters rotation on one lucky probe. If flapping is hurting you, the answer is a mesh (Envoy sidecar, with `healthy_threshold` and outlier detection) or making the endpoint itself hysteretic — latch unhealthy for N seconds once it trips.
3. **Liveness and readiness must not share an endpoint.** Failing readiness removes traffic; failing liveness **restarts the container**. Point liveness at a deep or slow check and an overloaded pod gets killed and restarted, which is the death spiral with an added cold start. Keep `livenessProbe` close to "the process is not deadlocked", with a generous `failureThreshold`.

A recommended starting point, with the reasoning attached — these are the numbers from the measured tables, not folklore:

| knob | start at | why this number |
|---|---|---|
| `interval` / `periodSeconds` | **2 s** | detection is linear in it and the only cost is probe traffic: 600/s across 6 balancers × 200 backends |
| `timeout` | **≥ p99.9 of the probe path** (3 s here) | at the p99 (1.4 s) you get 94 false ejections/day per 200 backends; above p99.9, one per 61 days |
| `unhealthy_threshold` | **5** | false ejections go as `p⁵`: 4.4 × 10⁻⁵/hr versus 0.0485/hr at 3 |
| `healthy_threshold` | **5** (where the platform allows it) | re-admission in 11.0 s instead of 1.0 s — a marginal host cannot flap in on one lucky probe |
| `max_ejection_percent` | **10%** | the strongest single guard measured: 99.7% on time versus 21.3%, floor of 18/20 healthy |
| `healthy_panic_threshold` | **50%** (the default) | if most of the fleet looks dead, the check is likelier wrong than the fleet |
| `base_ejection_time` | **30 s**, capped at 300 s | 12 ejections = 38 minutes of quarantine, not 6 |
| `success_rate_request_volume` | **100** | at 5 requests/window an identical 1%-error backend is ejected 17.6×/hr |
| health-check endpoint | **shallow, no shared dependencies** | one database blip otherwise ejects every replica simultaneously |

Measure your probe path's p99.9 before setting `timeout` — it is the only entry in that table you cannot copy, because it is a property of your service, and it is the one that produces outages when guessed. If the probe endpoint shares a thread pool with your request handlers, its p99.9 includes your queueing delay, which is exactly the coupling that made section 4 a spiral. Giving the health endpoint its own thread or its own listener breaks that coupling for a few lines of code.

Finally, the two you should verify rather than assume:

- **Do you know what your balancer does when every backend is unhealthy?** Route to all of them, or to none? That is one line of config and it is the difference between a degraded fleet and a total outage. Test it — mark everything unhealthy in staging and watch.
- **Is your health check on the same connection path as your traffic?** A probe on a separate port or a separate listener can pass while the path users take is dead. That is the failure passive outlier detection catches and the probe never will, which is the argument for running both.

## Think about it

1. Your fleet runs gRPC behind an L4 balancer and you cannot move to L7 this quarter. You set `max_connection_age` to 300 s with ±10% jitter. Your connections take 40 ms to establish including TLS. At 1,000 client connections, what is the steady-state rate of reconnects, what fraction of connection-time is spent handshaking, and what happens to both numbers if you cut the age to 30 s to rebalance faster?
2. Section 3 says the probe timeout should exceed the p99.9 of the probe path. Your probe endpoint shares a thread pool with your request handlers, so under load its p99.9 *is* your queueing delay — the number you are trying to measure. Design a probe that does not have this problem. What is it allowed to check, and what has it stopped being able to tell you?
3. A team proposes: "if a backend is ejected 3 times in 10 minutes, eject it permanently and page a human." Trace this policy through section 4's death spiral run and through section 3's false-ejection run. In which one does it help, in which does it convert a recoverable incident into an unrecoverable one, and what would you add to make it safe?
4. Kubernetes forces `successThreshold: 1` on readiness probes and has no `max_ejection_percent`. You cannot change either. Write down every mechanism available to you — inside the application, in the manifest, and in the surrounding infrastructure — that recovers some part of what those two knobs would have given you.
5. Your balancer does direct server return, so it never sees a response and passive outlier detection is impossible. A backend starts returning 500s to 30% of requests while its `/healthz` stays green. How do you detect it, how long does your method take compared with the 10 ms of `consecutive_5xx`, and what does your answer say about where DSR is and is not appropriate?

## Key takeaways

- **L4 balances connections; that is only balancing load while connections are short.** A perfectly even split — 24 connections over 8 backends, exactly 3 each — produced a **22.6% / 6.8% request distribution, a 3.3× spread**, and a newly deployed 9th instance received **0 requests in 600 seconds of being healthy**. The identical round-robin at L7 gave **1.00× spread and 11.1% to the new instance immediately.** The algorithm was never the variable; the layer was.
- **`max_connection_age` without jitter is a scheduled outage.** Connections opened together expire together: **24 simultaneous reconnects versus 2/s with ±10% jitter — 12×** — for the same rebalancing benefit. Jitter is mandatory, not a refinement.
- **Detection time is linear in interval and threshold; false ejections go as `p^threshold`.** Exploit the difference. The Kubernetes default blackholes a dead backend for **25.9 s mean / 41 s worst**; dropping the threshold to 1 costs **108 false ejections/hr/backend (21,600/hr across 200)**; a 2 s interval with a threshold of 5 beats both at **10.0 s detection and 4.4 × 10⁻⁵/hr — 2.6× faster and 221× fewer**, for 480 extra probes/s. **Fail fast, recover slow.**
- **A probe timeout below your p99 is a scheduled false ejection.** Against a healthy backend with a **1,396 ms p99**, a 1 s timeout fails **2.22% of probes** and produces **94 false ejections/day across 200 backends**. Set `timeout ≥ p99.9` — **3,225 ms here, so 3 s** — for one every 61 days.
- **Health checking is a feedback loop, and it can eject a healthy fleet to zero.** A **12-point step in demand** on a fleet with the capacity to serve it took **20 healthy instances to 0 in 44 seconds**, spent **23 s with nothing in rotation**, and delivered **21.3% on time.** `max_ejection_percent = 10%` restored **99.7%** — and added no capacity whatsoever. It only stopped the balancer from discarding what it had.
- **Panic mode is correct reasoning, not a hack.** If 80% of backends look dead, the likelier explanation is that health checking is wrong. Envoy's `healthy_panic_threshold` defaults to **50%** and was worth **21.3% → 65.4%** on-time delivery on its own. **Kubernetes has no equivalent** — nothing prevents an EndpointSlice from emptying.
- **Active and passive detection are blind in opposite directions — run both.** `consecutive_5xx: 5` ejects a fully broken backend in **10 ms** where no probe could, and needs **3,705 requests and 741 burned users** at a 20% error rate. Passive detection cannot see a backend receiving no traffic; active detection cannot see a failure off the probe path.
- **Sample size masquerades as health.** Six backends with an **identical 1% error rate**, evaluated against a 10%-error rule, are ejected **17.6 times/hr at 5 requests per window and 0.0000023 at 100 — a factor of 7.8 million.** Always set a minimum request volume (Envoy: 100), and remember the quietest backend is usually the newest one.
- **A deep health check turns one dependency blip into a fleet-wide outage.** Every replica asks the same database the same question, so all of them fail together and all of them leave rotation together. Wire only **independent** signals to actions that remove capacity; put the deep check on a separate endpoint that pages a human instead.

Next: [Service Discovery, Client-Side Balancing & Subsetting](../05-service-discovery-and-subsetting/) — how backends find each other at all, what happens when you move the balancing decision into the client to escape the L4 trap, and why connecting every client to every backend is a quadratic bill you pay in sockets.
