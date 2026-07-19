# API Gateways & the BFF Pattern

> Once you have many services, someone has to own the front door — TLS, auth, rate limits, routing — so each service doesn't reinvent it, and each frontend doesn't drown talking to all of them.

**Type:** Learn
**Languages:** —
**Prerequisites:** [REST Principles & Resource Modeling](../01-rest-principles-resource-modeling/) · [Rate Limiting & Quotas](../09-rate-limiting-quotas/)
**Time:** ~45 minutes

## The Problem

A single service is simple: the client talks to one address. Split it into ten
services — orders, customers, products, payments, search — and two problems appear at
once.

First, **every service now re-implements the same edge concerns**: terminate TLS,
authenticate the caller, enforce rate limits, add request IDs, emit metrics. Ten
copies that drift apart, and a client that must know ten hostnames and ten auth
quirks.

Second, **one API can't be the right shape for every client**. A web dashboard, an
iOS app, and a partner integration each want a different slice of the same data at a
different chattiness. Serve them all from one general-purpose API and you either
over-fetch (lesson 8's complaint) or bloat the API with per-client endpoints.

Two patterns answer these — and they're often confused. An **API gateway** solves the
first (one front door for cross-cutting concerns). A **Backend for Frontend (BFF)**
solves the second (a tailored backend per frontend). They compose.

## The Concept

### The API gateway: one front door

An **API gateway** is a reverse proxy that sits in front of your services and handles
the concerns that don't belong to any one of them — *once*, at the edge:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 532" width="100%" style="max-width:880px" role="img" aria-label="An API gateway drawn as the single front door in front of three services. On the left, outside a dashed trust boundary, sit three untrusted clients on the public internet: a web app in a browser, a mobile app on a flaky network, and a partner integration. All three feed one rail into one address instead of ten hostnames. In the middle sits the gateway, a reverse proxy that understands your API's policies, with its seven jobs listed and the reason each belongs at the edge: one, TLS termination, meaning Transport Layer Security ends here and certificates live in one place; two, authentication, verify the token once and pass a trusted X-User-Id header inward; three, rate limiting and quotas, one global edge limit protects everything behind it; four, routing, map the public path slash v1 slash orders star to a service so clients never see the topology; five, aggregation and transformation, fan out to several services and compose one response; six, observability, stamp a request ID and record latency and error metrics and propagate a trace; seven, traffic management, canary and blue-green splits, retries, timeouts and circuit breaking. On the right, inside the boundary, three services speak plain HTTP and trust the injected identity: orders-service on slash v1 slash orders star, customers-service on slash v1 slash customers star, products-service on slash v1 slash products star. Curved arrows between those three services show east-west traffic, service to service inside the cluster, which never touches the gateway and is governed by a service mesh such as Istio or Linkerd. Four warnings run along the bottom: the gateway is a single point of failure, a god-object gateway recreates the Enterprise Service Bus mistake, it adds a latency tax of one extra network hop, and defense in depth still applies because the gateway removes duplication of the edge check, not each service's duty to guard its own data.">
  <defs>
    <marker id="p2l10a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l10a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One front door: the gateway does the edge work once, so ten services stop doing it ten times</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">A gateway governs north–south traffic: client to your system. A service mesh governs east–west: service to service.</text>

    <!-- trust boundary -->
    <rect x="186" y="62" width="700" height="344" rx="14" fill="none" stroke="currentColor" stroke-opacity="0.38" stroke-width="1.5" stroke-dasharray="7 5"/>
    <text x="198" y="80" font-size="8" font-weight="700" fill="currentColor" opacity="0.72">TRUST BOUNDARY — inside, services speak plain HTTP and can be small and trusting</text>

    <!-- clients -->
    <text x="84" y="80" text-anchor="middle" font-size="8.5" font-weight="700" fill="#3553ff">UNTRUSTED</text>
    <text x="84" y="92" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">the public internet</text>
    <text x="84" y="106" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">all three see ONE address</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="14" y="136" width="140" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="14" y="214" width="140" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="14" y="292" width="140" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g text-anchor="middle">
      <text x="84" y="158" font-size="10.5" font-weight="700" fill="#3553ff">Web app</text>
      <text x="84" y="172" font-size="7.5" fill="currentColor" opacity="0.8">a browser dashboard</text>
      <text x="84" y="236" font-size="10.5" font-weight="700" fill="#3553ff">Mobile app</text>
      <text x="84" y="250" font-size="7.5" fill="currentColor" opacity="0.8">a flaky network</text>
      <text x="84" y="314" font-size="10.5" font-weight="700" fill="#3553ff">Partner</text>
      <text x="84" y="328" font-size="7.5" fill="currentColor" opacity="0.8">a third-party integration</text>
    </g>

    <!-- fan-in rail -->
    <g fill="none" stroke="#3553ff" stroke-width="1.7">
      <path d="M156 162 L172 162"/>
      <path d="M156 240 L172 240"/>
      <path d="M156 318 L172 318"/>
      <path d="M172 162 L172 318"/>
      <path d="M172 240 L204 240" marker-end="url(#p2l10a-arb)"/>
    </g>

    <!-- gateway -->
    <rect x="210" y="104" width="372" height="272" rx="12" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.9" stroke-linejoin="round"/>
    <text x="396" y="126" text-anchor="middle" font-size="12.5" font-weight="700" fill="#7c5cff">API Gateway</text>
    <text x="396" y="140" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.82">a reverse proxy that understands your API's policies</text>
    <path d="M224 150 L568 150" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <g fill="none" stroke="#7c5cff" stroke-opacity="0.7" stroke-width="1.1">
      <circle cx="234" cy="164" r="7.5"/><circle cx="234" cy="194" r="7.5"/><circle cx="234" cy="224" r="7.5"/>
      <circle cx="234" cy="254" r="7.5"/><circle cx="234" cy="284" r="7.5"/><circle cx="234" cy="314" r="7.5"/>
      <circle cx="234" cy="344" r="7.5"/>
    </g>
    <g text-anchor="middle" font-size="8" font-weight="700" fill="#7c5cff">
      <text x="234" y="167">1</text><text x="234" y="197">2</text><text x="234" y="227">3</text>
      <text x="234" y="257">4</text><text x="234" y="287">5</text><text x="234" y="317">6</text>
      <text x="234" y="347">7</text>
    </g>
    <g font-size="8.8" font-weight="700" fill="#7c5cff">
      <text x="250" y="168">TLS termination</text>
      <text x="250" y="198">Authentication</text>
      <text x="250" y="228">Rate limiting &amp; quotas</text>
      <text x="250" y="258">Routing</text>
      <text x="250" y="288">Aggregation / transformation</text>
      <text x="250" y="318">Observability</text>
      <text x="250" y="348">Traffic management</text>
    </g>
    <g font-size="7.8" fill="currentColor" opacity="0.82">
      <text x="250" y="179">Transport Layer Security ends here; certificates in ONE place</text>
      <text x="250" y="209">verify the token ONCE, then pass a trusted X-User-Id inward</text>
      <text x="250" y="239">one global edge limit protects everything behind it</text>
      <text x="250" y="269">/v1/orders/* to a service; clients never see the topology</text>
      <text x="250" y="299">fan out to several services and compose one response</text>
      <text x="250" y="329">stamp a request ID, record latency + error metrics, trace</text>
      <text x="250" y="359">canary + blue-green splits, retries, timeouts, breakers</text>
    </g>

    <!-- fan-out rail -->
    <g fill="none" stroke="#7c5cff" stroke-width="1.7">
      <path d="M584 240 L612 240"/>
      <path d="M612 174 L612 306"/>
      <path d="M612 174 L644 174" marker-end="url(#p2l10a-arp)"/>
      <path d="M612 240 L644 240" marker-end="url(#p2l10a-arp)"/>
      <path d="M612 306 L644 306" marker-end="url(#p2l10a-arp)"/>
    </g>

    <!-- services -->
    <text x="725" y="118" text-anchor="middle" font-size="8.5" font-weight="700" fill="#7c5cff">plain HTTP inside</text>
    <text x="725" y="130" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">a trusted X-User-Id header</text>
    <text x="725" y="142" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">no certificates to manage</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="650" y="151" width="150" height="46" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="650" y="217" width="150" height="46" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
      <rect x="650" y="283" width="150" height="46" rx="10" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle">
      <text x="725" y="171" font-size="9.5" font-weight="700" fill="#7c5cff">orders-service</text>
      <text x="725" y="185" font-size="7.5" fill="currentColor" opacity="0.8">/v1/orders/*</text>
      <text x="725" y="237" font-size="9.5" font-weight="700" fill="#7c5cff">customers-service</text>
      <text x="725" y="251" font-size="7.5" fill="currentColor" opacity="0.8">/v1/customers/*</text>
      <text x="725" y="303" font-size="9.5" font-weight="700" fill="#7c5cff">products-service</text>
      <text x="725" y="317" font-size="7.5" fill="currentColor" opacity="0.8">/v1/products/*</text>
    </g>

    <!-- east-west -->
    <g fill="none" stroke="#7c5cff" stroke-width="1.4" stroke-dasharray="5 4">
      <path d="M802 186 C 846 194, 846 220, 806 230" marker-end="url(#p2l10a-arp)"/>
      <path d="M802 252 C 846 260, 846 286, 806 296" marker-end="url(#p2l10a-arp)"/>
      <path d="M802 316 C 872 300, 872 200, 806 174" marker-end="url(#p2l10a-arp)"/>
    </g>
    <g text-anchor="middle">
      <text x="760" y="350" font-size="8.5" font-weight="700" fill="#7c5cff">east–west traffic</text>
      <text x="760" y="363" font-size="7.5" fill="currentColor" opacity="0.82">service to service, and</text>
      <text x="760" y="374" font-size="7.5" fill="currentColor" opacity="0.82">it never touches the</text>
      <text x="760" y="385" font-size="7.5" fill="currentColor" opacity="0.82">gateway: a SERVICE MESH</text>
      <text x="760" y="396" font-size="7.5" fill="currentColor" opacity="0.82">(Istio, Linkerd) governs it</text>
    </g>

    <!-- pitfalls -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="16" y="420" width="208" height="64" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="236" y="420" width="208" height="64" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="456" y="420" width="208" height="64" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="676" y="420" width="208" height="64" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g font-size="8.6" font-weight="700">
      <text x="28" y="438" fill="#d64545">Single point of failure</text>
      <text x="248" y="438" fill="#d64545">The God-object gateway</text>
      <text x="468" y="438" fill="#e0930f">The latency tax</text>
      <text x="688" y="438" fill="#e0930f">Defense in depth still applies</text>
    </g>
    <g font-size="7.4" fill="currentColor" opacity="0.85">
      <text x="28" y="452">everything flows through it, so it</text>
      <text x="28" y="463">must be horizontally scaled,</text>
      <text x="28" y="474">stateless and health-checked.</text>
      <text x="248" y="452">business logic creeping in recreates</text>
      <text x="248" y="463">the Enterprise Service Bus mistake —</text>
      <text x="248" y="474">keep domain logic in the services.</text>
      <text x="468" y="452">it is one extra network hop. Fine</text>
      <text x="468" y="463">when lean; a problem when it does</text>
      <text x="468" y="474">heavy work in the request path.</text>
      <text x="688" y="452">the gateway removes DUPLICATION</text>
      <text x="688" y="463">of the edge check, not each service's</text>
      <text x="688" y="474">duty to guard its own data.</text>
    </g>
  </g>
  <text x="450" y="504" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">The gateway does the edge work once so ten services stop rebuilding it — and clients see one address, not ten hostnames.</text>
  <text x="450" y="520" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.8" fill="currentColor" opacity="0.75">It governs north–south only; east–west stays with the mesh — and neither one excuses a service from guarding its own data.</text>
</svg>
```

Its job list, and why each belongs at the edge rather than in every service:

| Responsibility | Why it lives in the gateway |
|---|---|
| **TLS termination** | Manage certificates in one place; services speak plain HTTP inside the trust boundary. |
| **Authentication** | Verify the token *once*, then pass a trusted identity (e.g. `X-User-Id`) inward. |
| **Rate limiting & quotas** | A global edge limit protects everything behind it (lesson 9). |
| **Routing** | Map a public path (`/v1/orders/*`) to an internal service; clients never see the topology. |
| **Aggregation / transformation** | Fan out to several services and compose one response (below). |
| **Observability** | Stamp a request ID, record latency/error metrics, and propagate a trace across services. |
| **Traffic management** | Canary and blue-green splits, retries, timeouts, circuit breaking at the edge. |

The payoff is that a service can be small and trusting: it assumes the request already
passed auth and rate limiting. (Trusting, not naive — see *defense in depth* below.)

### Gateway vs. load balancer vs. service mesh

These overlap and get muddled. The distinction that matters is **what each is aware of
and which traffic it governs**:

| Thing | Layer / awareness | Governs |
|---|---|---|
| **Load balancer** | L4/L7; "which healthy instance?" | Spreading load across replicas of one service |
| **Reverse proxy** (nginx) | L7; forwards + rewrites | Generic HTTP forwarding — a gateway's substrate |
| **API gateway** | L7; *API-aware* (routes, auth, quotas) | **North–south**: client ↔ your system |
| **Service mesh** (Istio, Linkerd) | L7 via per-pod sidecars | **East–west**: service ↔ service inside the cluster |

A gateway is a reverse proxy that understands your API's policies. A mesh handles the
*internal* calls between services (mTLS, retries, tracing) that never touch the
gateway. Most real systems run both: a gateway at the north–south edge, a mesh for
east–west. They are complements, not alternatives.

### The BFF pattern: one backend per frontend

A gateway routes and protects, but it doesn't fix *shape*. That's the BFF's job. A
**Backend for Frontend** is a thin backend, **owned by the frontend team**, that
exists to serve exactly one client:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 622" width="100%" style="max-width:880px" role="img" aria-label="The Backend for Frontend pattern drawn as two parallel stacks over one shared set of services. On the left, a web app running a dashboard in a browser calls the Web BFF, which returns rich, wide payloads: its response is drawn as eight long full-width bars, the wide object a dashboard renders. On the right, an iOS app on a flaky network calls the Mobile BFF, which returns lean payloads with few round trips: its response is drawn as only three short bars labelled order, customer name, and product names, with empty space underneath and the note that nothing else is sent and the data is pre-joined so the phone makes one round trip instead of three. The same data, a different shape. Between the two stacks a panel explains why it works: because a frontend team owns its BFF, it can iterate on its own contract without waiting on a shared, committee-owned API. Both BFFs feed down into the same shared services at the bottom, orders, customers and products, where the domain logic lives and where it must stay, because a BFF must never make business decisions. Three warnings close the diagram. The cost is duplication, since logic can sprawl across BFFs, one per client is fine but ten near-identical ones are not. The discipline is to keep a BFF thin, aggregation and shaping only, because a BFF that starts making pricing decisions has become a new monolith wearing a frontend team's badge. And GraphQL is a generalized, declarative BFF: one endpoint where each client declares its own shape, instead of one hand-written BFF per client.">
  <defs>
    <marker id="p2l10b-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l10b-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">BFF = Backend for Frontend — one thin backend per client, owned by that client's team</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">A gateway routes and protects, but it does not fix shape — shaping the payload is the BFF's job.</text>
    <text x="450" y="60" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">The pattern came out of Netflix and SoundCloud, for exactly this reason.</text>

    <!-- clients -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="135" y="72" width="190" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="575" y="72" width="190" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="94" font-size="11" font-weight="700" fill="#3553ff">Web app</text>
      <text x="230" y="107" font-size="7.5" fill="currentColor" opacity="0.8">a dashboard in a browser</text>
      <text x="670" y="94" font-size="11" font-weight="700" fill="#3553ff">iOS app</text>
      <text x="670" y="107" font-size="7.5" fill="currentColor" opacity="0.8">a phone on a flaky network</text>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.7">
      <path d="M230 118 L230 134" marker-end="url(#p2l10b-arb)"/>
      <path d="M670 118 L670 134" marker-end="url(#p2l10b-arb)"/>
    </g>

    <!-- BFF cards -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.9">
      <rect x="80" y="140" width="300" height="208" rx="12" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="520" y="140" width="300" height="208" rx="12" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="164" font-size="12.5" font-weight="700" fill="#7c5cff">Web BFF</text>
      <text x="230" y="178" font-size="8" fill="currentColor" opacity="0.82">rich, wide payloads</text>
      <text x="670" y="164" font-size="12.5" font-weight="700" fill="#7c5cff">Mobile BFF</text>
      <text x="670" y="178" font-size="8" fill="currentColor" opacity="0.82">lean, few round trips</text>
    </g>

    <!-- response shape panels -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.2">
      <rect x="95" y="186" width="270" height="120" rx="9" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.55"/>
      <rect x="535" y="186" width="270" height="120" rx="9" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.55"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.42">
      <rect x="102" y="194" width="240" height="8" rx="3"/>
      <rect x="102" y="207" width="206" height="8" rx="3"/>
      <rect x="102" y="220" width="252" height="8" rx="3"/>
      <rect x="102" y="233" width="184" height="8" rx="3"/>
      <rect x="102" y="246" width="232" height="8" rx="3"/>
      <rect x="102" y="259" width="256" height="8" rx="3"/>
      <rect x="102" y="272" width="212" height="8" rx="3"/>
      <rect x="102" y="285" width="244" height="8" rx="3"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f" stroke-width="1.1">
      <rect x="542" y="196" width="170" height="17" rx="4"/>
      <rect x="542" y="220" width="170" height="17" rx="4"/>
      <rect x="542" y="244" width="170" height="17" rx="4"/>
    </g>
    <g font-size="8" fill="currentColor">
      <text x="552" y="208">order</text>
      <text x="552" y="232">customer name</text>
      <text x="552" y="256">product names</text>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">
      <text x="670" y="282">and nothing else is sent</text>
      <text x="670" y="295">pre-joined: 1 round trip, not 3</text>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.85">
      <text x="230" y="320">the wide object a dashboard renders</text>
      <text x="670" y="320">three fields, pre-joined for a flaky network</text>
    </g>
    <g fill="none" stroke-linejoin="round" stroke-width="1.2">
      <rect x="120" y="326" width="220" height="18" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-opacity="0.7"/>
      <rect x="560" y="326" width="220" height="18" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-opacity="0.7"/>
    </g>
    <g text-anchor="middle" font-size="7.8" font-weight="700" fill="#7c5cff">
      <text x="230" y="338">owned by the WEB frontend team</text>
      <text x="670" y="338">owned by the iOS frontend team</text>
    </g>

    <!-- why it works -->
    <rect x="384" y="182" width="132" height="104" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.2"/>
    <text x="450" y="200" text-anchor="middle" font-size="8" font-weight="700" fill="#7c5cff">why it works</text>
    <g text-anchor="middle" font-size="7.4" fill="currentColor" opacity="0.85">
      <text x="450" y="214">Because a frontend</text>
      <text x="450" y="225">team OWNS its BFF, it</text>
      <text x="450" y="236">can iterate on its own</text>
      <text x="450" y="247">contract without a</text>
      <text x="450" y="258">shared, committee-</text>
      <text x="450" y="269">owned API.</text>
    </g>

    <!-- down to shared services -->
    <text x="450" y="366" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.85">both aggregate the SAME shared services</text>
    <g fill="none" stroke="#7c5cff" stroke-width="1.7">
      <path d="M230 350 L230 372"/>
      <path d="M670 350 L670 372"/>
      <path d="M230 372 L670 372"/>
      <path d="M450 372 L450 390" marker-end="url(#p2l10b-arp)"/>
    </g>

    <!-- shared services -->
    <rect x="180" y="396" width="540" height="84" rx="12" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff" stroke-width="1.9" stroke-linejoin="round"/>
    <text x="450" y="414" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">shared services</text>
    <g fill="none" stroke-linejoin="round" stroke-width="1.4">
      <rect x="195" y="422" width="160" height="32" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="370" y="422" width="160" height="32" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="545" y="422" width="160" height="32" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="#7c5cff">
      <text x="275" y="442">orders</text>
      <text x="450" y="442">customers</text>
      <text x="625" y="442">products</text>
    </g>
    <text x="450" y="470" text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">domain logic lives HERE — a BFF must never make business decisions</text>

    <!-- notes -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="16" y="496" width="282" height="78" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="308" y="496" width="282" height="78" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/>
      <rect x="600" y="496" width="284" height="78" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g font-size="8.6" font-weight="700">
      <text x="28" y="514" fill="#e0930f">The cost: duplication</text>
      <text x="320" y="514" fill="#d64545">Keep the BFF THIN</text>
      <text x="612" y="514" fill="#7c5cff">GraphQL is a generalized BFF</text>
    </g>
    <g font-size="7.4" fill="currentColor" opacity="0.85">
      <text x="28" y="528">logic can sprawl across BFFs. One BFF per</text>
      <text x="28" y="539">client is fine; ten near-identical BFFs is not.</text>
      <text x="28" y="550">Share libraries, keep them thin, and reach</text>
      <text x="28" y="561">for GraphQL when the shapes proliferate.</text>
      <text x="320" y="528">aggregation and shaping, never business</text>
      <text x="320" y="539">rules. "A BFF that starts making pricing</text>
      <text x="320" y="550">decisions has become a new monolith</text>
      <text x="320" y="561">wearing a frontend team's badge."</text>
      <text x="612" y="528">a generalized, declarative BFF: one endpoint</text>
      <text x="612" y="539">where each client declares its own shape,</text>
      <text x="612" y="550">instead of one hand-written BFF per client.</text>
      <text x="612" y="561">The same idea, without the hand-writing.</text>
    </g>
  </g>
  <text x="450" y="594" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">A gateway fixes who may call you; a BFF fixes what the answer looks like — routing and protection are not shaping.</text>
  <text x="450" y="610" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.8" fill="currentColor" opacity="0.75">Same data, different shape: aggregate and shape for one client, and leave every business rule in the services behind it.</text>
</svg>
```

Each BFF aggregates the shared services and shapes the result for *its* client: the
mobile BFF returns three fields and pre-joins data to save round trips on a flaky
network; the web BFF returns the wide object a dashboard renders. Because a frontend
team owns its BFF, it can iterate on its own contract without waiting on a shared,
committee-owned API — the coupling that made the backend a bottleneck in lesson 8.

The pattern came out of Netflix and SoundCloud for exactly this reason. And it's the
right lens on lesson 8's closing line: **GraphQL is a generalized, declarative BFF** —
one endpoint where each client declares its own shape, instead of one hand-written BFF
per client.

The cost is **duplication**: logic can sprawl across BFFs. The discipline is to keep a
BFF *thin* — aggregation and shaping, never business rules. Domain logic belongs in
the services; a BFF that starts making pricing decisions has become a new monolith
wearing a frontend team's badge.

### Aggregation and fan-out

The concrete power of a gateway or BFF is turning one client call into several
internal calls and composing the result. A mobile "order detail" screen needs the
order, the customer's name, and each product's name — three services, one response:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 580" width="100%" style="max-width:880px" role="img" aria-label="A sequence diagram of a BFF fanning one client call out to three services. Five lifelines run down the page: the mobile app, the mobile BFF, orders-svc, customers-svc and products-svc. First the mobile app sends GET /mobile/orders/1001 to the BFF. A note across the BFF and the three services reads: fan out in parallel, one timeout each. Then, inside a bracketed parallel band, the BFF issues all three downstream calls at the same instant from one activation: GET /orders/1001 to orders-svc, GET /customers/42 to customers-svc, and GET /products?ids=... to products-svc, each carrying its own timeout=0.3, which is per call and not for the whole request. Because they leave together, the total cost is the slowest call, not the sum of the three. Two come back inside the band: orders-svc returns the order and customers-svc returns the customer's name. The third does not: an amber line ending in a cross on the products-svc lifeline shows no response arrived by 0.3 seconds, so the BFF gives up and moves on. Finally the BFF returns one composed JSON to the mobile app in a single round trip, holding the order and the customer's name with product names omitted, so the screen still renders. Two rules close the diagram. Rule one: call in parallel, not in series, because sequential calls cost the sum of their latencies while parallel calls cost only the slowest. Rule two: put a timeout on every call and decide the partial-failure policy per field, so a slow dependency degrades the screen gracefully instead of hanging it.">
  <defs>
    <marker id="p2l10c-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l10c-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p2l10c-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Fan out in parallel, time-box every call — three services, one client round trip</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.85">Turning one client call into three internal calls and composing the result — the concrete power of a BFF.</text>

    <!-- actor headers -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.7">
      <rect x="10" y="62" width="148" height="38" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="176" y="62" width="148" height="38" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="376" y="62" width="148" height="38" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="556" y="62" width="148" height="38" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="736" y="62" width="148" height="38" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700">
      <text x="84" y="80" fill="#3553ff">Mobile app</text>
      <text x="250" y="80" fill="#7c5cff">Mobile BFF</text>
      <text x="450" y="80" fill="#7c5cff">orders-svc</text>
      <text x="630" y="80" fill="#7c5cff">customers-svc</text>
      <text x="810" y="80" fill="#7c5cff">products-svc</text>
    </g>
    <g text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">
      <text x="84" y="93">one order detail screen</text>
      <text x="250" y="93">Backend for Frontend</text>
      <text x="450" y="93">owns the order</text>
      <text x="630" y="93">owns the name</text>
      <text x="810" y="93">owns product names</text>
    </g>

    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M84 100 L84 434"/>
      <path d="M250 100 L250 146"/><path d="M250 170 L250 434"/>
      <path d="M450 100 L450 146"/><path d="M450 170 L450 386"/>
      <path d="M630 100 L630 146"/><path d="M630 170 L630 386"/>
      <path d="M810 100 L810 146"/><path d="M810 170 L810 386"/>
    </g>

    <!-- client request -->
    <text x="167" y="120" text-anchor="middle" font-size="9" fill="currentColor">GET /mobile/orders/1001</text>
    <path d="M90 128 L244 128" fill="none" stroke="#3553ff" stroke-width="1.7" marker-end="url(#p2l10c-arb)"/>

    <!-- note band -->
    <rect x="176" y="146" width="708" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/>
    <text x="530" y="161" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">fan out in parallel, one timeout each</text>

    <!-- parallel band -->
    <rect x="228" y="182" width="656" height="204" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.4" stroke-width="1.2" stroke-dasharray="6 5"/>
    <path d="M242 188 L232 188 L232 380 L242 380" fill="none" stroke="#7c5cff" stroke-width="1.9" stroke-linejoin="round"/>
    <g text-anchor="middle">
      <text x="158" y="256" font-size="9.5" font-weight="700" fill="#7c5cff">PARALLEL</text>
      <text x="158" y="270" font-size="7.5" fill="currentColor" opacity="0.85">all three calls</text>
      <text x="158" y="281" font-size="7.5" fill="currentColor" opacity="0.85">leave at the</text>
      <text x="158" y="292" font-size="7.5" fill="currentColor" opacity="0.85">same instant</text>
      <text x="158" y="308" font-size="7.5" fill="currentColor" opacity="0.85">total = the</text>
      <text x="158" y="319" font-size="7.5" fill="currentColor" opacity="0.85">SLOWEST call,</text>
      <text x="158" y="330" font-size="7.5" fill="currentColor" opacity="0.85">not the sum</text>
    </g>

    <!-- BFF activation -->
    <rect x="245" y="196" width="10" height="180" rx="3" fill="#7c5cff" fill-opacity="0.4" stroke="#7c5cff" stroke-width="1.1"/>

    <!-- fan out -->
    <g fill="none" stroke="#7c5cff" stroke-width="1.7">
      <path d="M257 210 L444 210" marker-end="url(#p2l10c-arp)"/>
      <path d="M257 242 L624 242" marker-end="url(#p2l10c-arp)"/>
      <path d="M257 274 L804 274" marker-end="url(#p2l10c-arp)"/>
    </g>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="350" y="202">GET /orders/1001</text>
      <text x="440" y="234">GET /customers/42</text>
      <text x="530" y="266">GET /products?ids=...</text>
    </g>
    <g text-anchor="end" font-size="7.5" font-weight="700" fill="#e0930f">
      <text x="438" y="221">timeout=0.3</text>
      <text x="618" y="253">timeout=0.3</text>
      <text x="798" y="285">timeout=0.3</text>
    </g>

    <!-- returns -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="6 4">
      <path d="M444 312 L260 312" marker-end="url(#p2l10c-arg)"/>
      <path d="M624 340 L260 340" marker-end="url(#p2l10c-arg)"/>
    </g>
    <g text-anchor="middle" font-size="9" fill="#0fa07f">
      <text x="353" y="304">the order</text>
      <text x="443" y="332">the customer's name</text>
    </g>
    <path d="M258 368 L794 368" fill="none" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="6 4"/>
    <g stroke="#e0930f" stroke-width="2.2" stroke-linecap="round">
      <path d="M802 360 L818 376"/>
      <path d="M818 360 L802 376"/>
    </g>
    <text x="529" y="360" text-anchor="middle" font-size="9" fill="#e0930f">no response by 0.3s — the BFF gives up and moves on</text>

    <!-- composed response -->
    <path d="M244 414 L92 414" fill="none" stroke="#0fa07f" stroke-width="1.7" stroke-dasharray="6 4" marker-end="url(#p2l10c-arg)"/>
    <text x="168" y="406" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">one composed JSON</text>
    <text x="168" y="428" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.85">1 round trip</text>
    <rect x="300" y="390" width="584" height="56" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.6" stroke-linejoin="round"/>
    <g text-anchor="middle">
      <text x="592" y="408" font-size="8.5" font-weight="700" fill="#0fa07f">composed for THIS client — 1 round trip for the phone</text>
      <text x="592" y="422" font-size="8" fill="currentColor" opacity="0.9">the order + the customer's name; product names OMITTED, because that one call timed out</text>
      <text x="592" y="436" font-size="8" fill="currentColor" opacity="0.8">the screen still renders — a good BFF degrades gracefully instead of hanging on the slowest dependency</text>
    </g>

    <!-- rules -->
    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="16" y="462" width="430" height="70" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="458" y="462" width="426" height="70" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <text x="30" y="482" font-size="9" font-weight="700" fill="#0fa07f">Rule 1 · Call in parallel, not in series</text>
    <text x="472" y="482" font-size="9" font-weight="700" fill="#e0930f">Rule 2 · A timeout on EACH call, and a decided policy</text>
    <g font-size="7.6" fill="currentColor" opacity="0.88">
      <text x="30" y="498">three calls in series cost the SUM of their latencies;</text>
      <text x="30" y="510">three in parallel cost only the SLOWEST one. That</text>
      <text x="30" y="522">difference is the entire point of the fan-out.</text>
      <text x="472" y="498">timeout=0.3 is per call, not for the whole request. Then</text>
      <text x="472" y="510">decide per field: if products-svc times out, does the screen</text>
      <text x="472" y="522">fail, or render the order with product names omitted?</text>
    </g>
  </g>
  <text x="450" y="552" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">One call in, three calls out, one composed answer back — and the client never learns there were three services.</text>
  <text x="450" y="568" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.8" fill="currentColor" opacity="0.75">Parallelism buys you the slowest call instead of the sum; the per-call timeout is what stops one slow service hanging the screen.</text>
</svg>
```

Two rules make fan-out safe. **Call in parallel**, not in series — the response is as
slow as the slowest downstream, not the sum. And **decide the partial-failure policy
per field**: if `products-svc` times out, does the screen fail, or render the order
with product names omitted? A good BFF sets a **timeout** on each call and degrades
gracefully rather than hanging on the slowest dependency. (The resilience machinery —
timeouts, circuit breakers, bulkheads — is Phase 11.)

Conceptually, that handler is just a parallel gather with per-call timeouts:

```python
# illustrative — the shape of a BFF aggregation handler
order, customer, products = await gather_with_timeout(
    orders.get(order_id),
    customers.get(customer_id),
    products.get(item_ids),
    timeout=0.3,          # each call, not the whole request
)
return compose_mobile_view(order, customer, products)   # shape it for THIS client
```

### Cross-cutting concerns, done once

The gateway is where lessons 3 and 9 get enforced at the edge. It **verifies the auth
token once** and injects a trusted `X-User-Id` header, so downstream services read
identity instead of re-parsing JWTs. It **applies the global rate limit** so a flood
never reaches your services. It **stamps a request ID** that every service logs, so
one user complaint maps to one correlated trace.

**Defense in depth still applies.** "The gateway checks auth" is not a reason for a
service to trust any caller unconditionally — an attacker inside the network, or a
misrouted internal call, must still be rejected. The gateway removes *duplication* of
the edge check; it doesn't remove each service's responsibility for its own data.

### Pitfalls

- **Single point of failure.** Everything flows through it, so it must be
  horizontally scaled, stateless, and health-checked. A gateway that falls over takes
  the whole surface with it.
- **The God-object gateway.** Business logic creeping into the gateway recreates the
  Enterprise Service Bus mistake — a central component every team must coordinate on
  to deploy. Keep it policy and routing; keep domain logic in services.
- **The latency tax.** It's an extra network hop. Fine when it's lean; a problem when
  it does heavy synchronous work in the request path.
- **BFF sprawl.** One BFF per client is fine; ten near-identical BFFs is duplication.
  Share libraries, keep them thin, and reach for GraphQL when the shapes proliferate.

## Key takeaways

- An **API gateway** is one front door handling cross-cutting concerns — TLS, auth,
  rate limiting, routing, aggregation, observability — so services don't each rebuild
  them and clients see one address.
- A gateway governs **north–south** (client ↔ system); a **service mesh** governs
  **east–west** (service ↔ service). They complement, not replace, each other.
- A **BFF** is a thin, frontend-owned backend that aggregates services and shapes the
  payload for one client; **GraphQL is a generalized BFF**.
- **Fan out in parallel with per-call timeouts** and a deliberate partial-failure
  policy; keep gateways and BFFs thin — routing and shaping, never business logic.
- The gateway removes duplicate edge checks, not each service's duty to guard its own
  data (**defense in depth**).
