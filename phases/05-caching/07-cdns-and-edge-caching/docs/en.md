# CDNs & Edge Caching

> Your Redis cache is blindingly fast and sitting in Virginia. A user in Sydney still waits a third of a second for the first byte — not because your server is slow, but because light isn't fast enough to cross the planet and back in time. The only fix is to stop crossing the planet: keep a copy of the answer a few miles from the user.

**Type:** Learn
**Languages:** —
**Prerequisites:** [Cache Stampede & the Thundering Herd](../06-cache-stampede/)
**Time:** ~45 minutes

## The Problem

Everything so far cached *inside* your datacenter — a map in your process, Redis on the
next rack. But your users are spread across the planet, and one number you cannot
optimize away governs their experience: the **speed of light**.

Light in fiber travels about 200,000 km/s — roughly two-thirds of light in a vacuum.
Sydney to Virginia is ~16,000 km, so a single round trip is at best ~160 ms of pure
propagation, before any processing, and real routes are longer and messier — call it
250–300 ms. A page that makes even a handful of sequential requests to that origin feels
sluggish no matter how fast the origin answers, because most of the time is spent with
bytes *in flight over the ocean*. You cannot make a server in Virginia feel local to
Sydney. You can only stop sending Sydney's requests to Virginia.

There's a second problem stacked on the first: **static assets are big and identical for
everyone.** The same 2 MB hero image, the same JavaScript bundle, the same product video
gets served to millions of users — every byte crossing your origin's network, burning
bandwidth to deliver bytes that never change.

The answer to both is the **CDN**.

## The Concept

### What a CDN is

A **CDN** (Content Delivery Network) is a globally distributed fleet of caching servers.
The CDN operator runs **edge servers** grouped into **PoPs** (Points of Presence) — data
centers placed in hundreds of cities worldwide, deliberately close to where users are.
You put your content on the CDN; each edge caches a copy; and every user is routed to the
**nearest edge** instead of to your distant **origin** (your actual servers).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 414" width="100%" style="max-width:880px" role="img" aria-label="Two panels comparing life without and with a CDN. Without a CDN, a Sydney user and a London user both send every request to one origin server in Virginia: the Sydney round trip is about 280 milliseconds and the London round trip about 160 milliseconds, because each one crosses roughly sixteen thousand kilometres of ocean each way. That latency is set by distance, not by how fast the origin is, so buying a faster server changes nothing. With a CDN, each user instead reaches the edge PoP in their own city — Sydney to the Sydney edge, London to the London edge — in about 5 milliseconds, and only a cache miss, drawn as a dashed line and roughly one to two percent of requests, travels back to the origin in Virginia. The edge then keeps that copy so the next user gets a hit.">
  <defs>
    <marker id="p5l7a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p5l7a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">You cannot make the origin closer — so put a copy of the answer next door</text>
  <g fill-opacity="0.06" stroke-width="2" stroke-linejoin="round">
    <rect x="16" y="44" width="424" height="306" rx="12" fill="#e0930f" stroke="#e0930f" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="306" rx="12" fill="#0fa07f" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="228" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#e0930f">WITHOUT a CDN</text>
    <text x="228" y="89" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.75">every user crosses an ocean to one origin</text>
    <text x="672" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">WITH a CDN</text>
    <text x="672" y="89" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.75">every user hits the edge in their own city</text>

    <!-- ============ WITHOUT ============ -->
    <g fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8" stroke-linejoin="round">
      <rect x="36" y="104" width="104" height="40" rx="10"/>
      <rect x="36" y="196" width="104" height="40" rx="10"/>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">
      <text x="88" y="128">Sydney user</text>
      <text x="88" y="220">London user</text>
    </g>
    <rect x="294" y="142" width="120" height="56" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="354" y="165" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Origin</text>
    <text x="354" y="181" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Virginia</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.9">
      <path d="M140 124 L290 152" marker-end="url(#p5l7a-ara)"/>
      <path d="M140 216 L290 188" marker-end="url(#p5l7a-ara)"/>
    </g>
    <text x="214" y="128" text-anchor="middle" font-size="16" font-weight="700" fill="#e0930f">~280 ms</text>
    <text x="214" y="172" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.6">≈ 16,000 km each way</text>
    <text x="214" y="222" text-anchor="middle" font-size="16" font-weight="700" fill="#e0930f">~160 ms</text>
    <text x="228" y="266" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">Origin serves 100% of requests</text>
    <text x="228" y="288" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">Latency is set by distance, not by your server —</text>
    <text x="228" y="306" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">you cannot make Virginia feel local to Sydney.</text>
    <text x="228" y="328" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">Every byte of every asset crosses the ocean, every time.</text>

    <!-- ============ WITH ============ -->
    <g fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8" stroke-linejoin="round">
      <rect x="474" y="104" width="88" height="40" rx="10"/>
      <rect x="474" y="196" width="88" height="40" rx="10"/>
    </g>
    <g text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">
      <text x="518" y="128">Sydney user</text>
      <text x="518" y="220">London user</text>
    </g>
    <g fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round">
      <rect x="618" y="104" width="104" height="40" rx="10"/>
      <rect x="618" y="196" width="104" height="40" rx="10"/>
    </g>
    <g text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">
      <text x="670" y="128">Edge · Sydney</text>
      <text x="670" y="220">Edge · London</text>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.9">
      <path d="M562 124 L613 124" marker-end="url(#p5l7a-arg)"/>
      <path d="M562 216 L613 216" marker-end="url(#p5l7a-arg)"/>
    </g>
    <text x="588" y="116" text-anchor="middle" font-size="14" font-weight="700" fill="#0fa07f">~5 ms</text>
    <text x="588" y="208" text-anchor="middle" font-size="14" font-weight="700" fill="#0fa07f">~5 ms</text>
    <rect x="608" y="256" width="124" height="50" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="670" y="277" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Origin</text>
    <text x="670" y="293" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">Virginia</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.7" stroke-dasharray="5 4">
      <path d="M670 236 L670 251" marker-end="url(#p5l7a-ara)"/>
      <path d="M722 124 C 772 124, 772 281, 737 281" marker-end="url(#p5l7a-ara)"/>
    </g>
    <text x="825" y="186" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">MISS only</text>
    <text x="825" y="202" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">~1–2% of requests</text>
    <text x="825" y="226" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">then cached at the</text>
    <text x="825" y="240" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">edge, so the next</text>
    <text x="825" y="254" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.7">Sydney user HITs</text>
    <text x="530" y="276" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">the copy stays at the</text>
    <text x="530" y="292" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">edge for the next user</text>
    <text x="672" y="334" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">Origin serves ~1–2% — the edge absorbs the rest</text>
  </g>
  <text x="450" y="380" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A CDN does not make your origin faster — it moves the answer next door, so the request never crosses the ocean.</text>
  <text x="450" y="400" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">280 ms becomes 5 ms, and the origin stops seeing traffic it has already answered a million times.</text>
</svg>
```

The transformation: a 280 ms trip becomes a 5 ms one, and your origin only sees the rare
**miss** instead of every request. For a well-cached site the origin might serve 1–2% of
traffic; the CDN absorbs the other 98%.

### How a user finds the nearest edge

Two mechanisms route a request to the closest PoP, often working together:

- **Anycast.** The CDN announces the *same* IP address from every PoP simultaneously.
  Internet routing (BGP) naturally delivers a packet to the *topologically nearest*
  announcement of that address — so `104.16.0.1` reaches the London edge from London and
  the Tokyo edge from Tokyo, with no per-user logic. One IP, hundreds of locations.
- **DNS geo-routing.** When the user's resolver looks up `cdn.yoursite.com`, the CDN's
  authoritative DNS answers with the IP of the PoP closest to that resolver.

Either way, the "closest server" decision is made by the network itself, transparently,
before your application is ever involved.

### The cache hierarchy: edge, shield, origin

A CDN isn't one layer of cache — it's a *hierarchy*, and the middle tier exists for a
reason you already understand. If every one of 300 edges independently missed and fetched
from origin, a newly published (or newly expired) object would trigger a **global
stampede** — 300 simultaneous origin fetches. So misses funnel through an intermediate
**origin shield**: a designated regional PoP that all edges consult on a miss. The shield
collapses 300 edge misses into (ideally) one origin fetch, then fans the result back out.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 404" width="100%" style="max-width:880px" role="img" aria-label="Two panels showing why a CDN needs an origin shield. Without a shield, the edges in Sydney, Tokyo and Mumbai each miss independently and each sends its own fetch straight to the origin, so three edge misses become three origin fetches — and with three hundred PoPs that is three hundred simultaneous fetches the instant a hot object expires, a global stampede. With an origin shield, all three edges consult one designated regional PoP first; the shield collapses their three misses into exactly one fetch to the origin, then fans that single answer back out to every edge. Three hundred PoPs still produce just one origin fetch. This is the single-flight idea from the stampede lesson, applied at planetary scale.">
  <defs>
    <marker id="p5l7b-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The shield is a cache in front of your cache — it collapses the fan-in</text>
  <g fill-opacity="0.06" stroke-width="2" stroke-linejoin="round">
    <rect x="16" y="44" width="424" height="300" rx="12" fill="#e0930f" stroke="#e0930f" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="300" rx="12" fill="#0fa07f" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="228" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#e0930f">WITHOUT an origin shield</text>
    <text x="228" y="89" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.75">every edge misses straight to the origin</text>
    <text x="672" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">WITH an origin shield</text>
    <text x="672" y="89" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.75">every edge consults one regional PoP first</text>

    <!-- ============ WITHOUT ============ -->
    <g fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round">
      <rect x="34" y="104" width="118" height="38" rx="10"/>
      <rect x="34" y="156" width="118" height="38" rx="10"/>
      <rect x="34" y="208" width="118" height="38" rx="10"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">
      <text x="93" y="127">Edge · Sydney</text>
      <text x="93" y="179">Edge · Tokyo</text>
      <text x="93" y="231">Edge · Mumbai</text>
    </g>
    <rect x="298" y="146" width="120" height="58" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="358" y="170" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Origin</text>
    <text x="358" y="188" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">3 fetches</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.8">
      <path d="M152 123 L294 158" marker-end="url(#p5l7b-ara)"/>
      <path d="M152 175 L294 175" marker-end="url(#p5l7b-ara)"/>
      <path d="M152 227 L294 192" marker-end="url(#p5l7b-ara)"/>
    </g>
    <text x="228" y="266" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">3 edge misses → 3 origin fetches</text>
    <text x="228" y="288" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">300 PoPs → 300 simultaneous fetches the</text>
    <text x="228" y="306" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">instant a hot object expires: a global stampede.</text>
    <text x="228" y="328" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">The origin absorbs the whole fan-in by itself.</text>

    <!-- ============ WITH ============ -->
    <g fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.8" stroke-linejoin="round">
      <rect x="478" y="104" width="112" height="38" rx="10"/>
      <rect x="478" y="156" width="112" height="38" rx="10"/>
      <rect x="478" y="208" width="112" height="38" rx="10"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">
      <text x="534" y="127">Edge · Sydney</text>
      <text x="534" y="179">Edge · Tokyo</text>
      <text x="534" y="231">Edge · Mumbai</text>
    </g>
    <rect x="630" y="142" width="118" height="66" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.9" stroke-linejoin="round"/>
    <text x="689" y="167" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">Origin shield</text>
    <text x="689" y="183" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">regional PoP</text>
    <text x="689" y="198" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.65">single-flight</text>
    <rect x="792" y="148" width="84" height="54" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="834" y="170" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Origin</text>
    <text x="834" y="188" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">1 fetch</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.8">
      <path d="M590 123 L626 152" marker-end="url(#p5l7b-ara)"/>
      <path d="M590 175 L626 175" marker-end="url(#p5l7b-ara)"/>
      <path d="M590 227 L626 198" marker-end="url(#p5l7b-ara)"/>
      <path d="M748 175 L788 175" stroke-width="2.4" marker-end="url(#p5l7b-ara)"/>
    </g>
    <text x="768" y="166" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">×1</text>
    <text x="672" y="266" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">3 edge misses → 1 origin fetch</text>
    <text x="672" y="288" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">300 PoPs → still 1 fetch; the shield then</text>
    <text x="672" y="306" text-anchor="middle" font-size="9.3" fill="currentColor" opacity="0.8">fans that single answer back out to every edge.</text>
    <text x="672" y="328" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.65">The origin sees one request, no matter the fleet size.</text>
  </g>
  <text x="450" y="372" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Count the arrows touching the origin: three become one. That ratio is the whole point of the shield tier.</text>
  <text x="450" y="392" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">It is single-flight from lesson 6 — one recompute shared by the herd — just with continents between the layers.</text>
</svg>
```

It's the stampede lesson's single-flight idea (lesson 6), applied at planetary scale: one
recompute, shared by the herd — just with continents between the layers.

### The cache key: what counts as "the same request"

An edge decides hit-or-miss by computing a **cache key** — normally the URL, plus any
request headers the origin declared relevant via **`Vary`**, plus (some of) the query
string. Two requests with the same key share a cached copy. This makes **cache-key
hygiene** a real hit-ratio lever:

- **Strip meaningless query params.** `?utm_source=twitter` and `?utm_source=email` point
  at the *same* asset but produce *different* keys — fragmenting your cache into
  near-duplicate copies and tanking the hit ratio. Configure the CDN to ignore tracking
  params in the key.
- **Mind `Vary`.** `Vary: Accept-Encoding` (gzip vs brotli vs none) is sensible.
  `Vary: User-Agent` is a disaster — thousands of UA strings means thousands of cache
  entries per URL, most never reused.

### Static vs. dynamic — and edge compute

CDNs were born to cache **static, immutable** assets (images, CSS/JS bundles, fonts,
video), and that's still where they shine: near-100% hit ratios, effectively infinite
TTLs. But the modern edge does more:

- **Dynamic content** with short TTLs (an API response cached for 5 seconds still
  deflects enormous traffic on a hot endpoint).
- **Dynamic acceleration** for genuinely uncacheable requests: even a `MISS` benefits,
  because the edge already holds a warm, optimized, TLS-terminated connection over the
  CDN's private backbone to origin — faster than the user's raw path across the public
  internet.
- **Edge compute** — small functions that run *at* the PoP (Cloudflare Workers, Lambda@Edge,
  Fastly Compute) to personalize, authenticate, rewrite, or assemble responses without a
  trip to origin.

### Controlling and invalidating the edge

Here is the connective tissue to the next lesson: **the origin controls edge caching
almost entirely through HTTP response headers.** `Cache-Control` says whether and how long
to cache; `s-maxage` sets the TTL for *shared* caches like a CDN (distinct from `max-age`
for the user's browser); `ETag` enables cheap revalidation. Those headers are lesson 8 —
CDNs are, in large part, HTTP caching deployed globally.

When cached content must change *now*, you have three tools:

1. **TTL expiry** — just wait; the edge refetches when the object goes stale. Simplest,
   but not immediate.
2. **Purge / invalidate** — explicitly tell the CDN to drop an object (by URL, or by a
   surrogate tag that groups many objects). Propagates to all PoPs in seconds. Use it for
   "we published a correction, evict the old article."
3. **Versioned URLs (cache busting)** — the best practice for static assets. Put a content
   hash in the filename — `app.9f8c2a.js` — cache it with an effectively **infinite TTL**,
   and when the file changes, its URL changes, so browsers and edges fetch the new URL and
   the old one simply ages out. No purge call, no stale risk. This is why build tools
   fingerprint asset filenames.

### The bonus: the edge as a shield

Because a CDN already sits in front of everything with enormous, globally distributed
capacity, it's the natural place for defenses that have nothing to do with latency:

- **DDoS absorption** — an attack hits the edge's vast capacity, not your modest origin;
  the CDN soaks or filters the flood far from your servers.
- **TLS termination, WAF, and edge rate limiting** — handled once, at the door, close to
  the attacker.

### The dangerous pitfall: caching private data publicly

The one mistake that turns a CDN into a security incident: **caching a personalized or
authenticated response in a shared edge cache.** If the origin marks user A's account page
`Cache-Control: public` (or forgets to mark it `private`), the edge stores it — and then
*serves A's data to user B* who requests the same URL. This is a real, recurring class of
breach. The rule: anything personalized or authenticated must be `Cache-Control: private,
no-store` (or keyed so it can never be shared), and you must be deliberate about *never*
caching `Set-Cookie`. Shared caches are shared; treat every `public` as a promise that the
bytes are safe for a stranger to receive.

## Think about it

1. Your origin is fast (10 ms), but users in another hemisphere complain the site is
   slow. Adding a faster server won't help. Why — and what actually will?
2. A CDN has 300 edge PoPs. Without an origin shield, what happens to your origin the
   instant a hot object expires? How does the shield turn that back into the single-flight
   idea from lesson 6?
3. You add `?utm_campaign=...` tracking params to every link. What does that do to your
   CDN hit ratio, and how do you fix it without dropping the analytics?
4. Why is fingerprinting a filename (`app.9f8c2a.js`) with an infinite TTL *safer* than
   caching `app.js` for a day and purging on deploy?

## Key takeaways

- Even a perfect in-datacenter cache can't beat the **speed of light**; a **CDN** puts
  copies in **edge PoPs** near users, turning a cross-ocean round trip into a few
  milliseconds and offloading the vast majority of traffic from your **origin**.
- Users reach the nearest edge via **anycast** (one IP, many locations, routed by BGP)
  and **DNS geo-routing** — the network picks the closest server, transparently.
- A CDN is a **hierarchy** (edge → **origin shield** → origin); the shield collapses many
  edge misses into few origin fetches — global single-flight.
- Hit ratio hinges on the **cache key**: strip meaningless query params, keep `Vary`
  narrow. CDNs cache static assets best but also do **dynamic acceleration** and **edge
  compute**.
- The origin steers the edge with **HTTP caching headers** (lesson 8); invalidate via
  **TTL, explicit purge, or versioned URLs** (fingerprint + infinite TTL is best for
  static assets).
- The edge doubles as a **security shield** (DDoS absorption, TLS, WAF) — but **never
  cache personalized/authenticated responses in a shared cache**, or you'll serve one
  user's data to another.

Next: [HTTP Caching & ETags](../08-http-caching-and-etags/) — the exact headers browsers
and CDNs obey to make all of this work.
