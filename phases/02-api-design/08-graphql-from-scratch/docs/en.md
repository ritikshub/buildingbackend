# GraphQL from Scratch

> One endpoint, many shapes. The client declares the exact tree of data it wants — which fixes over-fetching and waterfalls, and creates a brand-new class of caching and security problems.

**Type:** Build
**Languages:** Python
**Prerequisites:** [REST Principles & Resource Modeling](../01-rest-principles-resource-modeling/)
**Time:** ~90 minutes

## The Problem

REST has three pains that worsen as clients diversify (web, iOS, Android, partners):

1. **Over-fetching** — `GET /users/42` returns 40 fields; the mobile header needs 3.
2. **Under-fetching / the N-round-trip waterfall** — rendering "order + customer name
   + 3 products" is five sequential-ish REST calls, each paying network latency.
3. **One endpoint per view shape** — teams build `/orders/1001/mobile-summary`,
   `/admin-detail`, … each a bespoke, versioned contract. The backend becomes the
   bottleneck for frontend iteration.

GraphQL's answer: **one endpoint, many shapes.** The client sends a query describing
the exact tree it wants; the server returns JSON matching that tree, nothing more:

```graphql
query {
  order(id: "1001") {
    status
    customer { name }
    items(first: 3) { product { name priceCents } quantity }
  }
}
```

One round trip, zero over-fetch. GitHub's v4 API is GraphQL-only for exactly this
reason. **The trade:** the server no longer knows in advance what queries arrive.
That single fact drives everything hard about GraphQL below.

## The Concept

### Schema Definition Language (SDL)

GraphQL is schema-first and strongly typed — every query is validated before
execution. Object `type`s, scalars (`Int`/`String`/`ID`/custom), `!` non-null,
`[Type]` lists, `input` types for arguments, `interface`/`union`, `enum`, and the
three roots `Query`/`Mutation`/`Subscription`.

Nullability is **failure-semantics design**, not documentation: if a resolver for a
non-null field (`customer: Customer!`) throws, the server can't return `null` there
— the `null` **propagates upward** to the nearest nullable ancestor, potentially
nulling a large chunk of the response. Make top-level fields like `product(id:)`
nullable so a missing ID yields `"product": null` rather than destroying everything.

### How execution works: resolvers

The server walks the selection tree and calls **one resolver per field**. A
resolver's return value becomes the **parent** for its sub-selections. Every
resolver gets parent, arguments, a request-scoped **context** (current user, DB
session, loaders), and info. Two properties matter enormously:

- **Lazy by construction** — `Product.reviews` costs nothing unless the query asks.
- **Each resolver is independent and naive** — the `reviews` resolver knows only its
  own parent product; it has no idea it's called 50 times inside a list. That's N+1.

### The N+1 problem and DataLoader

A list of 50 products, each selecting `reviews`, executes as 1 query for the list +
50 queries for the children. Nest deeper and it compounds multiplicatively. This is
the #1 cause of "GraphQL is slow" in production.

**The fix: DataLoader.** It sits between resolvers and the data source and per
request (1) **batches** all `.load(key)` calls made in one event-loop tick into a
single fetch (`WHERE product_id = ANY(...)`), and (2) **caches** per request. The
50-product query drops from 51 queries to **2**. Rules: the batch function must
return results in the **same order and length** as the input keys; instantiate
loaders **per request** (a shared loader leaks one user's cache into another's).

### Partial data: `data` and `errors` coexist

GraphQL returns two top-level channels *together*, and HTTP status is usually `200`
even on failure. A failed sub-resolver nulls its field and appends to `errors` with
a `path`; the rest of `data` still returns. **Monitor the `errors` array, not just
5xx rates** — a "100% HTTP-200" GraphQL service can be failing everywhere.

### Caching and security are harder — by construction

**Caching:** everything is a `POST` to one URL, so HTTP/CDN caching is lost by
default. Recover it with **persisted queries** (hash known operations at build time
— tiny requests, CDN-cacheable GETs, and an **allow-list** the server can enforce:
the strongest single GraphQL hardening), and rely on **normalized client caches**
(Apollo `InMemoryCache` keyed on `__typename:id`) for UI consistency — which is why
"mutations return the mutated object with `id`" is the convention.

**Security** is query-shaped — you've handed clients a query planner:

- **Depth limits** (10–15) reject pathological recursive documents at validation.
- **Cost/complexity budgets** weight fields and multiply through list args before
  executing. GitHub and Shopify rate-limit on computed query cost, not request count.
- **Introspection off** for private APIs (it's free reconnaissance).
- **Alias/batch caps** against amplification (5,000 aliased `login` fields =
  credential stuffing in one request that request-count limiters miss).
- **Authorization lives in resolvers/business logic, never in schema-hiding** — the
  same `Customer` is reachable via `customer(id:)`, `order.customer`, `node(id:)`, …
  so enforce per-object using the principal from context.

## Build It

The concepts above stay abstract until you watch execution walk a tree.
`code/graphql_mini.py` is a real (tiny) GraphQL engine: a parser that turns query
text into a selection tree, and an executor that calls **one resolver per field.**

The query `{ products { name reviews { rating } } }` parses to this tree, and
execution is a depth-first walk of it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 580" width="100%" style="max-width:880px" role="img" aria-label="The selection tree for the query products, name, reviews, rating, drawn twice: once with naive resolvers and once with a DataLoader. In both panels the query root is the client-declared tree, and the products field resolves with one database query that returns a list of 3 products. That list fans the children out over each element, so the tree repeats under products index 0, 1 and 2. Under each element the walk forks into two children: name, a leaf, which ends the walk and costs nothing, and reviews, which returns a list of review objects and whose own child rating is another leaf. In the left panel the reviews resolver fires once per product element, so three separate resolver calls each go straight to the database: query 2, query 3 and query 4. Nothing sits between the resolvers and the database, and each call knows only its own parent product, which is exactly why it has no idea it ran three times. The counter reads: DB queries 4, that is 1 products plus 3 reviews, which is N plus 1; at 50 products it becomes 1 plus 50 equals 51 queries. In the right panel the tree and the data are identical and only the reviews resolver changed: each of the same three calls now calls loader dot load of the product id, and a DataLoader sitting between the resolvers and the data source batches every load made in one event-loop tick into a single fetch, WHERE product_id = ANY of the keys. The counter reads: DB queries 2, that is 1 products plus 1 batched reviews, and at 50 products it is still 2 queries. The DataLoader batch function must return results in the same order and length as its input keys, and the loader must be created fresh per request.">
  <defs>
    <marker id="p2l08a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p2l08a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p2l08a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p2l08a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">reviews fires once PER product — that is N+1; a DataLoader collapses it to one fetch</text>
  <text x="450" y="46" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" fill="currentColor"><tspan opacity="0.75">the client declares  </tspan><tspan fill="#3553ff" font-weight="700">{ products { name reviews { rating } } }</tspan></text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="16" y="60" width="428" height="452" rx="12" fill="#e0930f" fill-opacity="0.04" stroke="#e0930f" stroke-opacity="0.55"/>
      <rect x="456" y="60" width="428" height="452" rx="12" fill="#0fa07f" fill-opacity="0.04" stroke="#0fa07f" stroke-opacity="0.55"/>
    </g>
    <text x="230" y="80" text-anchor="middle" font-size="12" font-weight="700" fill="#e0930f">NAIVE RESOLVERS — one DB query per product</text>
    <text x="670" y="80" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">BATCHED WITH A DataLoader — one fetch for all 3</text>

    <g font-size="7" fill="currentColor" opacity="0.72">
      <text x="26" y="104">leaf = a scalar field;</text>
      <text x="26" y="115">the walk ends there</text>
      <text x="434" y="104" text-anchor="end">lazy: reviews costs</text>
      <text x="434" y="115" text-anchor="end">nothing unless asked</text>
      <text x="466" y="104">same query, same data —</text>
      <text x="466" y="115">byte-for-byte identical</text>
      <text x="874" y="104" text-anchor="end">only the reviews resolver</text>
      <text x="874" y="115" text-anchor="end">changed — nothing else</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="155" y="96" width="150" height="34" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="595" y="96" width="150" height="34" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="130" y="144" width="200" height="40" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="570" y="144" width="200" height="40" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="112" font-size="11" font-weight="700" fill="#3553ff">query root</text>
      <text x="230" y="124" font-size="7" fill="currentColor" opacity="0.75">depth-first walk starts here</text>
      <text x="670" y="112" font-size="11" font-weight="700" fill="#3553ff">query root</text>
      <text x="670" y="124" font-size="7" fill="currentColor" opacity="0.75">depth-first walk starts here</text>
      <text x="230" y="161" font-size="10" font-weight="700" fill="#3553ff">products → [product]</text>
      <text x="230" y="176" font-size="7.5" fill="currentColor" opacity="0.8">1 DB query · returns a list of 3</text>
      <text x="670" y="161" font-size="10" font-weight="700" fill="#3553ff">products → [product]</text>
      <text x="670" y="176" font-size="7.5" fill="currentColor" opacity="0.8">1 DB query · returns a list of 3</text>
    </g>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M230 130 L230 144" marker-end="url(#p2l08a-arb)"/>
      <path d="M670 130 L670 144" marker-end="url(#p2l08a-arb)"/>
      <path d="M230 184 L230 200"/>
      <path d="M91 200 L369 200"/>
      <path d="M91 200 L91 212" marker-end="url(#p2l08a-arb)"/>
      <path d="M230 200 L230 212" marker-end="url(#p2l08a-arb)"/>
      <path d="M369 200 L369 212" marker-end="url(#p2l08a-arb)"/>
      <path d="M670 184 L670 200"/>
      <path d="M531 200 L809 200"/>
      <path d="M531 200 L531 212" marker-end="url(#p2l08a-arb)"/>
      <path d="M670 200 L670 212" marker-end="url(#p2l08a-arb)"/>
      <path d="M809 200 L809 212" marker-end="url(#p2l08a-arb)"/>
    </g>
    <text x="222" y="194" text-anchor="end" font-size="7" fill="currentColor" opacity="0.8">a list fans the children out over EACH element</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.5">
      <rect x="35" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="174" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="313" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="475" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="614" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="753" y="212" width="112" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.5"/>
      <rect x="65" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="204" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="343" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="505" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="644" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="783" y="242" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="77" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="216" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="355" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="517" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="656" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="795" y="306" width="66" height="20" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
      <rect x="65" y="266" width="74" height="30" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="204" y="266" width="74" height="30" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="343" y="266" width="74" height="30" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="505" y="266" width="74" height="30" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="644" y="266" width="74" height="30" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="783" y="266" width="74" height="30" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.2">
      <path d="M53 236 L53 281"/><path d="M53 252 L65 252"/><path d="M53 281 L65 281"/><path d="M91 296 L91 306"/>
      <path d="M192 236 L192 281"/><path d="M192 252 L204 252"/><path d="M192 281 L204 281"/><path d="M230 296 L230 306"/>
      <path d="M331 236 L331 281"/><path d="M331 252 L343 252"/><path d="M331 281 L343 281"/><path d="M369 296 L369 306"/>
      <path d="M493 236 L493 281"/><path d="M493 252 L505 252"/><path d="M493 281 L505 281"/><path d="M531 296 L531 306"/>
      <path d="M632 236 L632 281"/><path d="M632 252 L644 252"/><path d="M632 281 L644 281"/><path d="M670 296 L670 306"/>
      <path d="M771 236 L771 281"/><path d="M771 252 L783 252"/><path d="M771 281 L783 281"/><path d="M809 296 L809 306"/>
    </g>

    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="91" y="228">products[0]</text>
      <text x="230" y="228">products[1]</text>
      <text x="369" y="228">products[2]</text>
      <text x="531" y="228">products[0]</text>
      <text x="670" y="228">products[1]</text>
      <text x="809" y="228">products[2]</text>
    </g>
    <g font-size="8.5" fill="currentColor">
      <text x="73" y="256">name</text><text x="212" y="256">name</text><text x="351" y="256">name</text>
      <text x="513" y="256">name</text><text x="652" y="256">name</text><text x="791" y="256">name</text>
      <text x="85" y="320">rating</text><text x="224" y="320">rating</text><text x="363" y="320">rating</text>
      <text x="525" y="320">rating</text><text x="664" y="320">rating</text><text x="803" y="320">rating</text>
    </g>
    <g font-size="6.5" fill="currentColor" opacity="0.6" text-anchor="end">
      <text x="126" y="256">leaf</text><text x="265" y="256">leaf</text><text x="404" y="256">leaf</text>
      <text x="566" y="256">leaf</text><text x="705" y="256">leaf</text><text x="844" y="256">leaf</text>
      <text x="138" y="320">leaf</text><text x="277" y="320">leaf</text><text x="416" y="320">leaf</text>
      <text x="578" y="320">leaf</text><text x="717" y="320">leaf</text><text x="856" y="320">leaf</text>
    </g>
    <g text-anchor="middle" font-size="9" font-weight="700">
      <text x="102" y="278" fill="#e0930f">reviews</text>
      <text x="241" y="278" fill="#e0930f">reviews</text>
      <text x="380" y="278" fill="#e0930f">reviews</text>
      <text x="542" y="278" fill="#0fa07f">reviews</text>
      <text x="681" y="278" fill="#0fa07f">reviews</text>
      <text x="820" y="278" fill="#0fa07f">reviews</text>
    </g>
    <g text-anchor="middle" font-size="7" fill="currentColor" opacity="0.85">
      <text x="102" y="289">→ [review]</text><text x="241" y="289">→ [review]</text><text x="380" y="289">→ [review]</text>
      <text x="542" y="289">→ [review]</text><text x="681" y="289">→ [review]</text><text x="820" y="289">→ [review]</text>
    </g>

    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M139 281 L151 281 L151 342" marker-end="url(#p2l08a-arm)"/>
      <path d="M278 281 L290 281 L290 342" marker-end="url(#p2l08a-arm)"/>
      <path d="M417 281 L429 281 L429 342" marker-end="url(#p2l08a-arm)"/>
      <path d="M151 382 L151 396" marker-end="url(#p2l08a-arm)"/>
      <path d="M290 382 L290 396" marker-end="url(#p2l08a-arm)"/>
      <path d="M429 382 L429 396" marker-end="url(#p2l08a-arm)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M579 281 L591 281 L591 342" marker-end="url(#p2l08a-arg)"/>
      <path d="M718 281 L730 281 L730 342" marker-end="url(#p2l08a-arg)"/>
      <path d="M857 281 L869 281 L869 342" marker-end="url(#p2l08a-arg)"/>
      <path d="M670 382 L670 396" marker-end="url(#p2l08a-arg)"/>
    </g>
    <g text-anchor="end" font-size="7.5" font-weight="700">
      <text x="145" y="338" fill="#e0930f">query 2</text>
      <text x="284" y="338" fill="#e0930f">query 3</text>
      <text x="423" y="338" fill="#e0930f">query 4</text>
      <text x="585" y="338" fill="#0fa07f">.load(id)</text>
      <text x="724" y="338" fill="#0fa07f">.load(id)</text>
      <text x="863" y="338" fill="#0fa07f">.load(id)</text>
    </g>
    <text x="680" y="391" font-size="7.5" font-weight="700" fill="#0fa07f">1 batched fetch</text>

    <g fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.5">
      <path d="M130 164 L22 164 L22 414 L26 414" marker-end="url(#p2l08a-ar)"/>
      <path d="M570 164 L462 164 L462 414 L466 414" marker-end="url(#p2l08a-ar)"/>
    </g>
    <g font-size="7" fill="currentColor" opacity="0.8">
      <text x="26" y="178">query 1 · the list</text>
      <text x="466" y="178">query 1 · the list</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="26" y="342" width="408" height="40" rx="9" fill="#e0930f" fill-opacity="0.05" stroke="#e0930f" stroke-opacity="0.5" stroke-dasharray="5 5"/>
      <rect x="466" y="342" width="408" height="40" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="360" font-size="8.5" font-weight="700" fill="#e0930f">nothing sits between the resolvers and the database</text>
      <text x="230" y="374" font-size="7.5" fill="currentColor" opacity="0.85">3 separate resolver calls — each knows only its own parent product</text>
      <text x="670" y="360" font-size="8.5" font-weight="700" fill="#7c5cff">DataLoader — batches every .load() made in one event-loop tick</text>
      <text x="670" y="374" font-size="7.5" fill="currentColor" opacity="0.85">the same 3 resolver calls collapse into ONE fetch · fresh loader per request</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="26" y="396" width="408" height="36" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="466" y="396" width="408" height="36" rx="9" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="414" font-size="10" font-weight="700" fill="#7c5cff">DATA SOURCE — the database</text>
      <text x="230" y="427" font-size="7.5" fill="currentColor" opacity="0.85">one round trip per resolver call — 4 in total</text>
      <text x="670" y="414" font-size="10" font-weight="700" fill="#7c5cff">DATA SOURCE — the database</text>
      <text x="670" y="427" font-size="7.5" fill="currentColor" opacity="0.85">WHERE product_id = ANY(...) — one round trip</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="26" y="442" width="408" height="60" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
      <rect x="466" y="442" width="408" height="60" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="464" font-size="13" font-weight="700" fill="#e0930f">DB queries: 4</text>
      <text x="230" y="480" font-size="8.5" fill="currentColor" opacity="0.9">1 products + 3 reviews = N+1</text>
      <text x="230" y="496" font-size="9" font-weight="700" fill="#d64545">at 50 products: 1 + 50 = 51 queries</text>
      <text x="670" y="464" font-size="13" font-weight="700" fill="#0fa07f">DB queries: 2</text>
      <text x="670" y="480" font-size="8.5" fill="currentColor" opacity="0.9">1 products + 1 batched reviews</text>
      <text x="670" y="496" font-size="9" font-weight="700" fill="#0fa07f">at 50 products: still 2 queries</text>
    </g>
  </g>

  <text x="450" y="532" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">One resolver per field; its return value becomes the parent for the sub-selections — execution is a depth-first walk.</text>
  <text x="450" y="550" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Product.reviews is lazy — free unless the query asks — but each call knows only its own parent, so it never learns it ran 3 times.</text>
  <text x="450" y="568" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">DataLoader rule: the batch function must return results in the same order and length as its input keys, and the loader is created per request.</text>
</svg>
```

The executor is a dozen lines — a resolver's return value becomes the parent for its
children, and a list fans the children out over each element:

```python
if not field.children:
    result[field.name] = value                 # scalar leaf
elif isinstance(value, list):
    result[field.name] = [execute(field.children, item, ctx, ...) for item in value]
else:
    result[field.name] = execute(field.children, value, ctx, ...)
```

**N+1, made visible.** Every DB access bumps a counter. The `reviews` resolver knows
only its one parent product, so a list of 3 products fires 1 + 3 queries — and the
only fix that changes is that one resolver:

```console
$ python graphql_mini.py
=== naive resolvers ===        DB queries: 4  (1 products + 3 reviews = N+1)
=== batched with a DataLoader === DB queries: 2  (1 products + 1 batched reviews)
```

The batched resolver calls a `DataLoader` primed with every product id in a single
query — the `data` is byte-for-byte identical, but 51 queries at scale become 2.

**`data` and `errors` coexist.** Make one product's `reviews` resolver throw and the
executor nulls just that field, appends an error carrying its `path`, and returns the
rest — the response is still HTTP `200`:

```json
"data":   { "products": [ {"name": "Espresso", "reviews": null}, … ] },
"errors": [ {"message": "reviews service unavailable for p2",
             "path": ["products", 1, "reviews"]} ]
```

That is why you monitor the `errors` array, not just 5xx rates: a "100% HTTP-200"
GraphQL service can be failing on half its fields.

## Use It

Strawberry (code-first) mounted in FastAPI, with the DataLoader fix in place:

```python
import strawberry
from strawberry.dataloader import DataLoader
from strawberry.fastapi import GraphQLRouter
from fastapi import FastAPI, Request

@strawberry.type
class Product:
    id: strawberry.ID
    name: str
    @strawberry.field
    async def reviews(self, info: strawberry.Info) -> list["Review"]:
        return await info.context["review_loader"].load(self.id)  # batched, not N+1

async def get_context(request: Request) -> dict:
    return {
        "db": request.app.state.db,
        # A FRESH loader per request — never share across requests.
        "review_loader": DataLoader(load_fn=batch_load_reviews),
    }

schema = strawberry.Schema(query=Query)
app = FastAPI()
app.include_router(GraphQLRouter(schema, context_getter=get_context), prefix="/graphql")
```

## When it beats REST

| | REST | GraphQL | gRPC |
|---|---|---|---|
| Contract | Per-endpoint, server-shaped | One typed schema, client-shaped | `.proto` service |
| CDN caching | Excellent, free | Poor by default | N/A |
| Over/under-fetch | Common | Solved by design | Fixed messages |
| Sweet spot | Public/CRUD/cache-heavy | Many frontends over a rich graph | Internal service-to-service |

Choose **GraphQL** when many client types render different shapes of the same rich,
nested domain and frontend teams out-iterate backend — *and* you can afford the
operational tax (DataLoaders, cost limits, persisted queries, `errors`-aware
monitoring). It's best understood as a **generalized, declarative BFF**. Prefer
REST for public/cache-heavy/CRUD; they compose (gRPC internally, GraphQL for
client-facing aggregation, REST for public/webhooks).

## Key takeaways

- One endpoint serving client-declared shapes fixes over/under-fetch; the price is
  the server not knowing queries in advance.
- **N+1 is the default performance failure**; DataLoader batches same-tick loads —
  instantiate it **per request**.
- `data` and `errors` coexist at HTTP 200 — monitor the `errors` array.
- Caching and security are query-shaped: persisted-query allow-lists, depth/cost
  limits, introspection off, authz in resolvers.
