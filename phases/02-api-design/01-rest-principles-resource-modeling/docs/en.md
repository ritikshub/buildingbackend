# REST Principles & Resource Modeling

> REST isn't "JSON over HTTP" — it's six constraints from Fielding's dissertation, and statelessness is the one that buys you horizontal scaling.

**Type:** Learn
**Languages:** —
**Prerequisites:** Phase 1 · HTTP methods and semantics
**Time:** ~60 minutes

## The Problem

You can ship `POST /api/getUserData` with a server-side session and call it an
"API." It works — until you put a second server behind a load balancer, or try
to cache anything, or hand the contract to another team. REST is the named set of
constraints that make an HTTP interface scale and stay legible. Knowing them is
diagnostic: when someone proposes a design, you can say exactly which constraint
it breaks and what that costs.

## The Concept

### API styles: where REST fits

An **API** (Application Programming Interface) is the contract one program exposes
so another can use it without knowing its internals. Over the network, a handful of
*styles* dominate — each a different answer to "how do the two sides agree on what a
message means?" REST is one of them, and you should know the map before you commit:

| Style | Shape | You meet it in | Best when |
|---|---|---|---|
| **REST** | Resources (nouns) + HTTP verbs; one URL per thing | Stripe, GitHub, most public web APIs | Public/CRUD APIs, cache-heavy, many unknown consumers |
| **RPC** (JSON-RPC, XML-RPC) | Call a named function with arguments; usually one endpoint | Ethereum nodes, legacy internal services | Simple action-oriented internal calls |
| **gRPC** | RPC over HTTP/2 with Protocol Buffers — binary, typed `.proto` | Google, service meshes | Internal service-to-service, low latency, streaming |
| **GraphQL** | One endpoint; the client declares the exact data tree it wants | GitHub v4, Shopify | Many frontends over one rich, nested graph |
| **Webhooks / event-driven** | The server calls *you* (an HTTP POST) when something happens | Stripe events, GitHub hooks | Async "tell me when X happens" notifications |

These aren't rivals so much as tools. A real system often runs **gRPC** between its
own services, exposes **REST** to the public, adds a **GraphQL** layer for its apps,
and emits **webhooks** for integrators. This phase builds REST deeply (lessons 1–7),
then GraphQL from scratch (lesson 8); gRPC and Protocol Buffers were built back in
Phase 1. The rest of this lesson is the style that underlies the web itself: REST.

### What REST actually means: Fielding's constraints

REST is an *architectural style* defined by Roy Fielding (co-author of the HTTP
spec) in his 2000 dissertation. An API is "RESTful" to the degree it honors:

1. **Client–server.** Client and server evolve independently — your frontend and
   backend can be deployed, versioned, and rewritten separately.
2. **Stateless.** Every request carries everything the server needs. No per-client
   session in server memory. Payoff: any instance behind a load balancer can handle
   any request, so you scale horizontally without sticky sessions. Session *data* (a
   cart) can still exist — but as a **resource** with its own URI (`GET /carts/abc123`),
   not hidden server memory.
3. **Cacheable.** Responses label themselves cacheable or not (`Cache-Control`,
   `ETag`, `Last-Modified`) so clients and CDNs can reuse them.
4. **Uniform interface** — the heart of REST: stable resource URIs, manipulation
   through representations (send a JSON document, not an RPC call), self-descriptive
   messages, and hypermedia (HATEOAS).
5. **Layered system.** A client can't tell if it's talking to the origin or an
   intermediary (load balancer, cache, gateway).
6. **Code-on-demand** (optional) — servers may ship executable code (the web's JS).

The point of memorizing these is diagnostic. `POST /api/getUserData` with a
per-connection server session violates the uniform interface and statelessness —
which costs you caching and horizontal scaling without session affinity.

Statelessness is worth a picture, because it's the constraint that pays the rent.
Every request carries its own credentials and everything the server needs, so the
load balancer can hand it to *any* instance — that's how "stateless" turns into
"scale out by adding boxes." Session data still exists; it just lives in a shared
store as a resource, not in one instance's memory:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 612" width="100%" style="max-width:880px" role="img" aria-label="Two panels contrasting a stateless deployment with a sticky-session one. Left panel, STATELESS, which works: a client sends two successive requests, req 1 GET /carts/abc123 and req 2 POST /orders, and every request carries its own auth and full request state. Both reach a load balancer, which is the layered-system constraint in action because the client cannot tell whether it is talking to the origin or an intermediary. The load balancer sends req 1 to app instance 1 and req 2 to app instance 3, and instance 2 would have served either one identically; none of the three holds a session in memory, so they are interchangeable. All three instances read and write session state to a shared store, where the cart lives as a resource with its own URI, GET /carts/abc123. Because no box owns the client, adding a fourth box serves traffic immediately and losing a box costs nothing. Right panel, STICKY SESSION, which breaks: the same client sends req 1 and req 2, but the cart is not in them, so the load balancer must pin the client to app instance 2, the only box holding the cart in memory. Instances 1 and 3 are never used for this client and cannot serve it. The cart was never written to the shared store, so losing instance 2 loses the cart, and adding an instance 4 does not help clients already pinned elsewhere. Below both panels, a strip lists Fielding's six REST constraints: client-server, stateless, cacheable, uniform interface, layered system, and the optional code-on-demand, with stateless and layered system highlighted as the two this diagram demonstrates.">
  <defs>
    <marker id="p2l01a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l01a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p2l01a-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="p2l01a-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="p2l01a-arn" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Statelessness is what keeps the boxes interchangeable — a sticky session undoes it</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="14" y="40" width="432" height="428" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.8"/>
      <rect x="456" y="40" width="430" height="428" rx="12" fill="#d64545" fill-opacity="0.05" stroke="#d64545" stroke-opacity="0.8"/>
    </g>
    <text x="230" y="62" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">STATELESS — works</text>
    <text x="230" y="78" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.8">every request carries everything the server needs</text>
    <text x="671" y="62" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">STICKY SESSION — breaks</text>
    <text x="671" y="78" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.8">the cart is stashed in instance 2's memory</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="60" y="88" width="340" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="501" y="88" width="340" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="40" y="170" width="380" height="46" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="481" y="170" width="380" height="46" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="40" y="250" width="120" height="56" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="170" y="250" width="120" height="56" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="300" y="250" width="120" height="56" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <rect x="481" y="250" width="120" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.55"/>
      <rect x="611" y="250" width="120" height="56" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="741" y="250" width="120" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.55"/>
      <path d="M80 340 L80 394 A150 10 0 0 0 380 394 L380 340 A150 10 0 0 0 80 340 Z" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
      <ellipse cx="230" cy="340" rx="150" ry="10" fill="none" stroke="#7c5cff"/>
      <path d="M521 340 L521 394 A150 10 0 0 0 821 394 L821 340 A150 10 0 0 0 521 340 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.55"/>
      <ellipse cx="671" cy="340" rx="150" ry="10" fill="none" stroke="#7f7f7f" stroke-opacity="0.55"/>
    </g>

    <g text-anchor="middle">
      <text x="230" y="106" font-size="11" font-weight="700" fill="#3553ff">Client</text>
      <text x="230" y="121" font-size="8.5" fill="currentColor">carries auth + full request state, on every request</text>
      <text x="671" y="106" font-size="11" font-weight="700" fill="#3553ff">Client</text>
      <text x="671" y="121" font-size="8.5" fill="currentColor">sends the same requests — the cart is not in them</text>

      <text x="230" y="189" font-size="11" font-weight="700" fill="#7c5cff">Load balancer</text>
      <text x="230" y="205" font-size="8" fill="currentColor" opacity="0.85">layered system: the client can't tell origin from intermediary</text>
      <text x="671" y="189" font-size="11" font-weight="700" fill="#7c5cff">Load balancer + session affinity</text>
      <text x="671" y="205" font-size="8" fill="#d64545">must PIN this client to instance 2 (a "sticky session")</text>

      <text x="100" y="269" font-size="9.5" font-weight="700" fill="#7c5cff">App instance 1</text>
      <text x="100" y="285" font-size="8" fill="currentColor">no session in RAM</text>
      <text x="100" y="299" font-size="7.5" fill="currentColor" opacity="0.65">interchangeable</text>
      <text x="230" y="269" font-size="9.5" font-weight="700" fill="#7c5cff">App instance 2</text>
      <text x="230" y="285" font-size="8" fill="currentColor">no session in RAM</text>
      <text x="230" y="299" font-size="7.5" fill="currentColor" opacity="0.65">interchangeable</text>
      <text x="360" y="269" font-size="9.5" font-weight="700" fill="#7c5cff">App instance 3</text>
      <text x="360" y="285" font-size="8" fill="currentColor">no session in RAM</text>
      <text x="360" y="299" font-size="7.5" fill="currentColor" opacity="0.65">interchangeable</text>

      <text x="541" y="269" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.55">App instance 1</text>
      <text x="541" y="285" font-size="8" fill="currentColor" opacity="0.5">no cart here</text>
      <text x="541" y="299" font-size="7.5" fill="currentColor" opacity="0.45">can't serve them</text>
      <text x="671" y="269" font-size="9.5" font-weight="700" fill="#d64545">App instance 2</text>
      <text x="671" y="285" font-size="8" font-weight="700" fill="#d64545">CART IN MEMORY</text>
      <text x="671" y="299" font-size="7.5" fill="currentColor" opacity="0.7">the only box that works</text>
      <text x="801" y="269" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.55">App instance 3</text>
      <text x="801" y="285" font-size="8" fill="currentColor" opacity="0.5">no cart here</text>
      <text x="801" y="299" font-size="7.5" fill="currentColor" opacity="0.45">can't serve them</text>

      <text x="230" y="356" font-size="10" font-weight="700" fill="#7c5cff">Shared store</text>
      <text x="230" y="371" font-size="8.5" fill="currentColor">sessions live here as RESOURCES</text>
      <text x="230" y="386" font-size="8.5" fill="#0fa07f">GET /carts/abc123 — its own URI</text>
      <text x="671" y="356" font-size="10" font-weight="700" fill="currentColor" opacity="0.55">Shared store</text>
      <text x="671" y="371" font-size="8.5" fill="#d64545">the cart was never written here</text>
      <text x="671" y="386" font-size="8" fill="currentColor" opacity="0.6">it lives only in instance 2's RAM</text>
    </g>

    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M160 132 L160 166" marker-end="url(#p2l01a-arg)"/>
      <path d="M300 132 L300 166" marker-end="url(#p2l01a-arg)"/>
      <path d="M100 216 L100 246" marker-end="url(#p2l01a-arg)"/>
      <path d="M360 216 L360 246" marker-end="url(#p2l01a-arg)"/>
      <path d="M230 216 L230 246" stroke-dasharray="4 4" marker-end="url(#p2l01a-arg)"/>
    </g>
    <g fill="none" stroke="#7c5cff" stroke-width="1.6">
      <path d="M100 306 L100 341" marker-end="url(#p2l01a-arp)"/>
      <path d="M230 306 L230 336" marker-end="url(#p2l01a-arp)"/>
      <path d="M360 306 L360 341" marker-end="url(#p2l01a-arp)"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.6" stroke-opacity="0.8">
      <path d="M597 132 L597 166" marker-end="url(#p2l01a-ar)"/>
      <path d="M745 132 L745 166" marker-end="url(#p2l01a-ar)"/>
    </g>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.5" stroke-opacity="0.55">
      <path d="M541 216 L541 246" stroke-dasharray="3 4" marker-end="url(#p2l01a-arn)"/>
      <path d="M801 216 L801 246" stroke-dasharray="3 4" marker-end="url(#p2l01a-arn)"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="2.2">
      <path d="M671 216 L671 246" marker-end="url(#p2l01a-arr)"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.5" stroke-dasharray="3 4" stroke-opacity="0.8">
      <path d="M671 306 L671 328"/>
    </g>

    <text x="154" y="152" font-size="8" text-anchor="end" fill="#0fa07f">req 1: GET /carts/abc123</text>
    <text x="306" y="152" font-size="8" text-anchor="start" fill="#0fa07f">req 2: POST /orders</text>
    <text x="591" y="152" font-size="8" text-anchor="end" fill="currentColor" opacity="0.85">req 1</text>
    <text x="751" y="152" font-size="8" text-anchor="start" fill="currentColor" opacity="0.85">req 2</text>

    <g text-anchor="start" font-size="7.5">
      <text x="107" y="239" font-weight="700" fill="#0fa07f">req 1 ✓</text>
      <text x="237" y="239" fill="currentColor" opacity="0.6">or here ✓</text>
      <text x="367" y="239" font-weight="700" fill="#0fa07f">req 2 ✓</text>
      <text x="548" y="239" fill="currentColor" opacity="0.5">✗ never used</text>
      <text x="678" y="239" font-weight="700" fill="#d64545">req 1 + req 2, pinned</text>
      <text x="808" y="239" fill="currentColor" opacity="0.5">✗ never used</text>
    </g>
    <g text-anchor="start" font-size="7.5" fill="#7c5cff">
      <text x="240" y="317">reads/writes</text>
      <text x="240" y="328">session state</text>
    </g>
    <text x="681" y="322" font-size="7" text-anchor="start" fill="#d64545">cart never written</text>

    <g text-anchor="middle">
      <text x="230" y="424" font-size="9.5" font-weight="700" fill="#0fa07f">Add a 4th box → it serves traffic immediately.</text>
      <text x="230" y="440" font-size="8.5" fill="currentColor" opacity="0.85">Lose any box → the survivors serve every client.</text>
      <text x="230" y="455" font-size="8" fill="currentColor" opacity="0.7">Scale horizontally by adding boxes — no session affinity.</text>
      <text x="671" y="424" font-size="9.5" font-weight="700" fill="#d64545">Lose instance 2 → the cart is gone.</text>
      <text x="671" y="440" font-size="8.5" fill="currentColor" opacity="0.85">Add instance 4 → old clients are pinned; they don't benefit.</text>
      <text x="671" y="455" font-size="8" fill="currentColor" opacity="0.7">One box's RAM became a single point of failure for that client.</text>
    </g>

    <rect x="14" y="480" width="872" height="62" rx="10" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.2"/>
    <text x="450" y="498" font-size="9" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.8">Fielding's six REST constraints — this diagram demonstrates the two highlighted</text>
    <g fill="none" stroke-linejoin="round">
      <rect x="20" y="508" width="96" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.5" stroke-width="1.2"/>
      <rect x="156" y="508" width="86" height="24" rx="7" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.8"/>
      <rect x="282" y="508" width="86" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.5" stroke-width="1.2"/>
      <rect x="408" y="508" width="128" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.5" stroke-width="1.2"/>
      <rect x="576" y="508" width="112" height="24" rx="7" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="1.8"/>
      <rect x="728" y="508" width="150" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.07" stroke="#7f7f7f" stroke-opacity="0.5" stroke-width="1.2"/>
    </g>
    <g text-anchor="middle" font-size="8">
      <text x="68" y="523" fill="currentColor" opacity="0.65">client–server</text>
      <text x="199" y="523" font-weight="700" fill="#0fa07f">stateless</text>
      <text x="325" y="523" fill="currentColor" opacity="0.65">cacheable</text>
      <text x="472" y="523" fill="currentColor" opacity="0.65">uniform interface</text>
      <text x="632" y="523" font-weight="700" fill="#7c5cff">layered system</text>
      <text x="803" y="523" fill="currentColor" opacity="0.65">code-on-demand (optional)</text>
    </g>
  </g>
  <text x="450" y="568" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Stateless is the constraint that pays the rent: no box owns the client, so any box can answer — you scale out by adding boxes.</text>
  <text x="450" y="586" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Session data doesn't vanish; it moves out of one instance's RAM into a shared store, as a resource with its own URI.</text>
  <text x="450" y="604" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Sticky sessions are the tell: if the load balancer has to remember which box a client belongs to, statelessness is already broken.</text>
</svg>
```

Break statelessness — stash the cart in instance 2's memory — and the client is now
pinned to instance 2 (a "sticky session"). Lose that box and you lose the cart; add
boxes and old clients don't benefit. The constraint is what keeps the arrows above
interchangeable.

### The Richardson Maturity Model

A vocabulary for "how RESTful is this, really":

| Level | Name | Description |
|---|---|---|
| 0 | Swamp of POX | One URI, one method, operation name in the body. HTTP as a dumb tunnel. |
| 1 | Resources | Many URIs (one per resource), still one verb for everything. |
| 2 | HTTP verbs | Resources + proper methods and status codes. `DELETE /orders/7` → `204`. |
| 3 | Hypermedia | Responses embed links describing available next actions. |

Almost every well-regarded public API — Stripe, GitHub, Twilio — operates at
**level 2** with partial level-3 touches. Level 2 is the pragmatic target.

### Resource modeling: nouns, not verbs

URIs identify *things*; HTTP methods supply the *verbs*.

| Anti-pattern (verb in URI) | Resource-oriented |
|---|---|
| `POST /createOrder` | `POST /orders` |
| `GET /getOrderById?id=7` | `GET /orders/7` |
| `POST /orders/7/delete` | `DELETE /orders/7` |
| `POST /updateOrderStatus` | `PATCH /orders/7` |

**Plural collection names**, consistently: `/orders`, `/orders/{order_id}`. The
collection is `/orders`; `/orders/7` is member 7 of it. GitHub, Stripe, and Twilio
all use plurals.

**Nesting: two levels, then stop.** Nest a child under its parent only when it
can't exist without the parent (`GET /orders/{id}/line-items`). Beyond two levels
(`/restaurants/1/menus/2/sections/3/items/4`) is fragile — every segment is a
lookup and clients must carry every ID. If an entity has a globally unique ID and
is queried across parents (support staff querying all orders), promote it to
top-level with a filter: `GET /orders?user_id=42` beats `GET /users/42/orders`.

### Actions that don't fit CRUD

Cancel an order, capture a payment, merge two accounts. Three honest options, best
first:

1. **Controller sub-resource POST** — `POST /orders/{id}/cancel` with a body. This
   is what Stripe (`POST /v1/payment_intents/{id}/capture`) and GitHub (`PUT
   .../merge`) do. A verb in the URI used deliberately and sparingly; it gets its
   own body, permissions, and audit trail.
2. **State PATCH** — `PATCH /orders/{id}` with `{"status": "cancelled"}`. Fine for
   simple state machines; couples clients to internal state names.
3. **Action-as-resource** — `POST /orders/{id}/cancellations`, creating a record
   you can later `GET`. Best for anything asynchronous or record-producing
   (`POST /exports` → `202 Accepted` + `Location`, then poll).

## Key takeaways

- REST is a constraint set, not a wire format; **statelessness** is what buys
  horizontal scaling.
- Target **Richardson level 2** — resources + correct verbs and status codes.
- URIs are **plural nouns**; nest at most two levels; promote cross-parent entities
  to top level with filters.
- Model non-CRUD transitions as **controller sub-resources** (`POST /orders/{id}/cancel`).

Next: [URLs, Verbs & Status Codes](../02-urls-verbs-status-codes/) maps CRUD onto
HTTP method by method.
