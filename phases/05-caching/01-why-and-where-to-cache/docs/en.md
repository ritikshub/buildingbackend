# Why & Where to Cache

> The fastest query is the one you never run. A cache is a copy of an expensive answer, kept close to whoever needs it, so the expensive work happens once instead of every time.

**Type:** Learn
**Languages:** —
**Prerequisites:** none
**Time:** ~45 minutes

## The Problem

Your API asks the database the same question thousands of times a second: *what's on
the product page for item 42?* The database dutifully re-runs the query, re-joins the
tables, re-serializes the rows — and returns the identical bytes it returned a
millisecond ago. Nothing changed. You paid the full cost anyway.

Now multiply that across every popular page, every logged-in user's profile, every
price lookup. The database isn't slow because the work is hard; it's slow because it's
doing the *same* hard work over and over. Add more users and the repeated work grows
linearly until the database tips over — not from new questions, but from re-answering
old ones.

Caching is the discipline of **not redoing work**. Compute the answer once, keep a
copy somewhere fast and close, and hand out the copy until it's no longer true. That's
the whole idea. Everything else in this phase is *where* to keep the copy, *how* to
know when it's stale, and *what breaks* when you get it wrong.

## The Concept

### Why caching works: the memory hierarchy

Computers are built as a hierarchy of storage, and every step down is dramatically
slower but dramatically bigger and cheaper. The single most important fact in all of
performance engineering is *how far apart these steps are*. The numbers below are
approximate but the **ratios** are what matter — and to feel them, scale every latency
up so that one CPU cycle takes **one second**:

| Where the data lives | Real latency | If 1 cycle = 1 second |
|---|---|---|
| L1 CPU cache | ~1 ns | **1 second** |
| Main memory (RAM) | ~100 ns | ~1.7 minutes |
| SSD random read | ~100 µs | ~1.2 days |
| Same-datacenter network round trip | ~500 µs | ~6 days |
| Spinning-disk seek | ~10 ms | ~4 months |
| Cross-continent network round trip | ~150 ms | ~4.7 years |

Read that table again. Reaching across a datacenter to a database is, on the human
scale, a **six-day errand**. Answering from RAM instead is a **two-minute** one.
Caching is simply the act of moving the answer up this hierarchy — from a four-month
disk seek to a two-minute memory read — so the next request pays a tiny fraction of the
original cost. (These canonical figures come from Jeff Dean and Peter Norvig's
oft-cited "Latency Numbers Every Programmer Should Know.")

### Why it *keeps* working: locality and skew

Caching would be useless if every request asked something brand new. It works because
real traffic is deeply repetitive, in two ways first named by cache researchers in the
1960s:

- **Temporal locality** — if something was requested just now, it's likely to be
  requested again very soon. The item that's trending is trending for *everyone*.
- **Spatial locality** — if one thing was requested, nearby things often follow (the
  next page of results, the sibling record, the rest of the row).

On top of locality sits **skew**: real access patterns follow a Zipf/Pareto curve, not
a flat one. A small set of "hot" keys — the front-page article, the celebrity's
profile, today's featured product — absorbs the overwhelming majority of traffic. Cache
just that hot head and you deflect most of the load with very little memory. This is
why a cache holding **1%** of your data can serve **90%** of your reads.

### The vocabulary: hits, misses, and hit ratio

Every cache access ends one of two ways:

- A **hit** — the answer was in the cache; return it, cheaply.
- A **miss** — it wasn't; do the expensive work, *store the result*, then return it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 450" width="100%" style="max-width:880px" role="img" aria-label="The hit and miss decision for a single cache access. A request arrives for key K and reaches one decision: is this key in the cache? On the yes branch it is a HIT — the cached copy is returned straight from RAM in about one millisecond, with no database work at all. On the no branch it is a MISS — the answer is fetched from the source of truth, which costs the full query, roughly fifty milliseconds; the result is then STORED in the cache so the next request for the same key will hit; only then is the answer returned. Both branches end at the same place: the caller receives the answer and cannot tell which path ran. The hit ratio decides how often each path is taken, and because the miss is so much more expensive, raising the hit ratio pays off non-linearly.">
  <defs>
    <marker id="p5l1a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l1a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l1a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Every cache access ends one of two ways — a hit or a miss</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="340" y="46" width="220" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <path d="M450 124 L562 172 L450 220 L338 172 Z" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.6"/>
      <rect x="620" y="138" width="258" height="70" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="22" y="138" width="258" height="70" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
      <rect x="22" y="248" width="258" height="62" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="330" y="344" width="240" height="48" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="450" y="66" font-size="11.5" font-weight="700" fill="#3553ff">Request for key K</text>
      <text x="450" y="82" font-size="8.5" opacity="0.75">e.g. product:42</text>

      <text x="450" y="170" font-size="12" font-weight="700">In cache?</text>
      <text x="450" y="187" font-size="8" opacity="0.75">(one cheap lookup)</text>

      <text x="749" y="160" font-size="12" font-weight="700" fill="#0fa07f">HIT</text>
      <text x="749" y="178" font-size="9.5">return the cached copy</text>
      <text x="749" y="195" font-size="9" opacity="0.85">served from RAM — no DB work, ~1 ms</text>

      <text x="151" y="160" font-size="12" font-weight="700" fill="#e0930f">MISS</text>
      <text x="151" y="178" font-size="9.5">fetch from the source of truth</text>
      <text x="151" y="195" font-size="9" opacity="0.85">full query cost — DB / compute, ~50 ms</text>

      <text x="151" y="270" font-size="10" font-weight="700" fill="#7c5cff">STORE the copy in the cache</text>
      <text x="151" y="288" font-size="8.5" opacity="0.85">so the next request for K is a hit</text>

      <text x="450" y="366" font-size="11" font-weight="700">Return the answer</text>
      <text x="450" y="382" font-size="8.5" opacity="0.75">the caller can't tell which path ran</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M450 90 L450 120" marker-end="url(#p5l1a-ar)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M564 172 L614 172" marker-end="url(#p5l1a-arg)"/>
      <path d="M749 208 L749 368 L578 368" marker-end="url(#p5l1a-arg)"/>
    </g>
    <g fill="none" stroke="#e0930f" stroke-width="1.8">
      <path d="M336 172 L286 172" marker-end="url(#p5l1a-arm)"/>
      <path d="M151 208 L151 244" marker-end="url(#p5l1a-arm)"/>
      <path d="M151 310 L151 368 L322 368" marker-end="url(#p5l1a-arm)"/>
    </g>

    <g text-anchor="middle" font-size="9" font-weight="700">
      <text x="589" y="164" fill="#0fa07f">yes</text>
      <text x="311" y="164" fill="#e0930f">no</text>
    </g>
    <g text-anchor="middle" font-size="8" opacity="0.8">
      <text x="589" y="188" fill="#0fa07f">~90%</text>
      <text x="311" y="188" fill="#e0930f">~10%</text>
      <text x="664" y="358" fill="#0fa07f">fast path — the whole point</text>
      <text x="237" y="358" fill="#e0930f">slow path — paid once</text>
    </g>
  </g>
  <text x="450" y="418" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Hit ratio decides how often each branch runs: at 90% hits the average is 5.9 ms, at 99% it is 1.5 ms.</text>
  <text x="450" y="438" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.75">The STORE step is what turns this miss into the next request's hit — a cache that never stores never helps.</text>
</svg>
```

The **hit ratio** — hits ÷ total accesses — is the number you live and die by. And the
payoff is non-linear. If a hit costs 1 ms and a miss costs 50 ms, then average latency
is:

```text
avg = hit_ratio × 1ms + (1 − hit_ratio) × 50ms
```

- 0% hits  → 50 ms average (no cache)
- 90% hits → **5.9 ms** average
- 99% hits → **1.5 ms** average

Going from 90% to 99% — just nine percentage points — nearly **quadruples** your
speed, because you're eliminating the rare, ruinously expensive misses. This is why
squeezing the last few percent of hit ratio is worth real engineering effort, and why a
cache that flaps between 70% and 95% feels wildly inconsistent to users.

### What caching actually costs

Caching is not free speed; it's a **trade**. You spend three things to buy latency and
throughput:

1. **Memory** — a second copy of the data, sized to hold the hot set.
2. **Staleness risk** — the copy can be out of date the instant the source changes. You
   are now serving a *possibly-wrong* answer on purpose.
3. **Complexity** — a second source of truth is a second thing that can be wrong,
   inconsistent, or fall over. Every cache adds a new failure mode and a new class of
   bug ("why is this user seeing yesterday's price?").

The famous line — *"There are only two hard things in computer science: cache
invalidation and naming things"* (Phil Karlton) — is about staleness. Deciding *when a
cached copy is no longer true* is the genuinely hard part, and it gets its own lesson.

### Where to cache: the whole stack

A request travels through many layers on its way from a browser to your database, and
**almost every layer can hold a cache.** The governing principle is: **cache as close
to the consumer as you can afford**, because the closer the copy, the more of the round
trip you skip.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 354" width="100%" style="max-width:880px" role="img" aria-label="The seven places a request can be answered on its way from a browser to the disk, drawn left to right from closest to the user to furthest away. One: the browser cache, private to one user, zero network cost, the fastest hit possible, governed by HTTP headers. Two: the CDN or edge, shared and near the user, so the request never crosses the ocean. Three: the API gateway or reverse proxy at your front door, caching whole responses with nginx or Varnish. Four: the in-process application cache, a plain map in your app's own RAM, with no network at all, but one copy per instance that dies on restart. Five: the distributed cache, Redis or Memcached, shared by every app instance and surviving restarts, at the cost of one network hop. Six: the database buffer pool and OS page cache, which hold hot pages in RAM below your code for free. Seven: the disk, the source of truth, the slowest and the place every miss eventually ends. Underneath, the layers group into four zones: the user's machine, near the user, inside your datacenter, and the source of truth. A hit at any layer sends the answer back and every layer to its right is never touched; a miss falls one layer deeper and costs more at every hop.">
  <defs>
    <marker id="p5l1b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l1b-arm" markerWidth="9" markerHeight="9" refX="9" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Almost every layer can hold a cache — closest to the user wins</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="46" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">A HIT anywhere turns the answer around here — every layer to its RIGHT is never touched</text>
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M885 58 L26 58" marker-end="url(#p5l1b-arg)"/>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="15" y="72" width="114" height="138" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="141" y="72" width="114" height="138" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="267" y="72" width="114" height="138" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="393" y="72" width="114" height="138" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="519" y="72" width="114" height="138" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="645" y="72" width="114" height="138" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="771" y="72" width="114" height="138" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1">
      <circle cx="72" cy="88" r="7.5"/><circle cx="198" cy="88" r="7.5"/><circle cx="324" cy="88" r="7.5"/><circle cx="450" cy="88" r="7.5"/>
      <circle cx="576" cy="88" r="7.5"/><circle cx="702" cy="88" r="7.5"/><circle cx="828" cy="88" r="7.5"/>
    </g>
    <g text-anchor="middle" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.6">
      <text x="72" y="91">1</text><text x="198" y="91">2</text><text x="324" y="91">3</text><text x="450" y="91">4</text>
      <text x="576" y="91">5</text><text x="702" y="91">6</text><text x="828" y="91">7</text>
    </g>

    <g text-anchor="middle" font-size="9.5" font-weight="700">
      <text x="72" y="109" fill="#3553ff">Browser</text><text x="72" y="122" fill="#3553ff">cache</text>
      <text x="198" y="109" fill="#7c5cff">CDN /</text><text x="198" y="122" fill="#7c5cff">edge</text>
      <text x="324" y="109" fill="#7c5cff">Gateway /</text><text x="324" y="122" fill="#7c5cff">reverse proxy</text>
      <text x="450" y="109" fill="#7c5cff">In-process</text><text x="450" y="122" fill="#7c5cff">app cache</text>
      <text x="576" y="109" fill="#7c5cff">Distributed</text><text x="576" y="122" fill="#7c5cff">cache</text>
      <text x="702" y="109" fill="currentColor">DB buffer pool</text><text x="702" y="122" fill="currentColor">+ OS page cache</text>
      <text x="828" y="109" fill="currentColor">Disk</text><text x="828" y="122" fill="currentColor">source of truth</text>
    </g>
    <g stroke="currentColor" stroke-opacity="0.22" stroke-width="1">
      <path d="M25 131 L119 131"/><path d="M151 131 L245 131"/><path d="M277 131 L371 131"/><path d="M403 131 L497 131"/>
      <path d="M529 131 L623 131"/><path d="M655 131 L749 131"/><path d="M781 131 L875 131"/>
    </g>

    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.9">
      <text x="72" y="147">private to ONE user</text><text x="72" y="160">zero network cost</text><text x="72" y="173">fastest hit possible</text>
      <text x="198" y="147">shared, near user</text><text x="198" y="160">no ocean crossing</text><text x="198" y="173">cacheable GETs</text>
      <text x="324" y="147">your front door</text><text x="324" y="160">caches responses</text><text x="324" y="173">nginx, Varnish</text>
      <text x="450" y="147">a plain map in RAM</text><text x="450" y="160">NO network at all</text><text x="450" y="173">per-instance copy</text>
      <text x="576" y="147">Redis / Memcached</text><text x="576" y="160">shared by every app</text><text x="576" y="173">survives restarts</text>
      <text x="702" y="147">hot pages in RAM</text><text x="702" y="160">OS caches blocks too</text><text x="702" y="173">below your code</text>
      <text x="828" y="147">the real bytes</text><text x="828" y="160">slowest of them all</text><text x="828" y="173">nothing below it</text>
    </g>

    <g text-anchor="middle" font-size="8" font-weight="700">
      <text x="72" y="192" fill="#3553ff">HTTP headers rule it</text>
      <text x="198" y="192" fill="#7c5cff">one copy, many users</text>
      <text x="324" y="192" fill="#7c5cff">first hop inside</text>
      <text x="450" y="192" fill="#7c5cff">dies on restart</text>
      <text x="576" y="192" fill="#7c5cff">costs a network hop</text>
      <text x="702" y="192" fill="currentColor" opacity="0.85">free, you get it</text>
      <text x="828" y="192" fill="currentColor" opacity="0.85">every miss ends here</text>
    </g>
    <g text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.6">
      <text x="72" y="205">lesson 8</text>
      <text x="198" y="205">lesson 7</text>
      <text x="450" y="205">lesson 2</text>
      <text x="576" y="205">lesson 3</text>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.2">
      <rect x="15" y="220" width="114" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.3"/>
      <rect x="141" y="220" width="114" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.3"/>
      <rect x="267" y="220" width="492" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.3"/>
      <rect x="771" y="220" width="114" height="24" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.3"/>
    </g>
    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.85">
      <text x="72" y="236">the user's machine</text>
      <text x="198" y="236">near the user</text>
      <text x="513" y="236">inside your datacenter — these hops never cross the user's network</text>
      <text x="828" y="236">no cache below</text>
    </g>

    <text x="450" y="266" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">A MISS falls one layer deeper — and every layer you fall through makes the answer cost more</text>
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M15 278 L878 278" marker-end="url(#p5l1b-arm)"/>
    </g>
  </g>
  <text x="450" y="304" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Cache as close to the consumer as you can afford: the closer the copy, the more of the round trip you skip.</text>
  <text x="450" y="322" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Each layer exists to catch the request before it reaches the next one down — the deeper you fall, the more a miss costs.</text>
  <text x="450" y="342" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Browser and CDN you steer with HTTP headers; gateway, in-process and Redis you operate; the buffer pool you get for free.</text>
</svg>
```

From the reader's side inward:

- **Browser cache** — the response never leaves the user's machine. Governed by HTTP
  headers (lesson 8). Zero network cost, but only for that one user.
- **CDN / edge** — a shared copy in a datacenter physically near the user, so the
  request never crosses the ocean to your origin (lesson 7).
- **Reverse proxy / API gateway** — caches full responses at the entrance to your
  system (nginx, Varnish).
- **In-process (application) cache** — a plain map in your app's own RAM. The fastest
  possible hit (no network at all), but each instance has its own copy, and it dies on
  restart. This is the LRU cache you'll build in lesson 2.
- **Distributed cache** — a shared cache like Redis or Memcached that all app instances
  talk to over the network. Survives restarts, holds far more, stays consistent across
  the fleet — at the cost of a network hop. This is lesson 3.
- **Database buffer pool & OS page cache** — the database keeps hot pages in RAM, and
  the operating system caches disk blocks. You get these for free, below your code.

The deeper you fall, the more the miss costs — which is exactly why each layer exists
to catch requests before they reach the next one down.

### When *not* to cache

A cache is a liability you adopt on purpose. Skip it when the trade doesn't pay:

- **The data must be exactly right, right now.** A bank balance shown mid-transfer, an
  inventory count at checkout, a permissions check — serving a stale copy here isn't a
  minor glitch, it's a correctness bug or a security hole.
- **Low reuse.** Highly personalized or unique-per-request data (a one-off search with
  rare filters) is almost never asked for twice; you'll fill the cache with entries
  nobody hits again, spending memory to *lower* your hit ratio.
- **Write-heavy, read-light data.** If a value changes more often than it's read, the
  cache is stale more often than it's useful, and you pay invalidation cost for nothing.
- **The miss penalty is tiny.** If the "expensive" source is already a fast indexed
  lookup, adding a cache layer can cost more (serialization, a network hop, a second
  system to operate) than it saves.

And always remember **Amdahl's law**: a cache only speeds up the part it covers. If the
database is 20% of your request latency and the other 80% is business logic and
serialization, a *perfect* cache with a 100% hit ratio makes the whole request at most
20% faster. Measure where the time actually goes before you reach for a cache.

## Think about it

1. Your cache hit ratio is 50%. A hit costs 2 ms, a miss costs 80 ms. What's your
   average latency — and roughly how much does it improve if you raise the hit ratio to
   95%? (This is why the last few percent are worth chasing.)
2. You add an in-process cache to each of your 10 app servers. A value is updated in the
   database. How many stale copies might now exist, and for how long? What does that
   suggest about *where* the cache should live?
3. Name one piece of data in a system you know that you should **never** cache, and say
   exactly what would go wrong if you did.

## Key takeaways

- Caching is **not redoing work**: compute an expensive answer once, keep a copy close
  and fast, serve the copy until it's no longer true.
- It works because the **memory hierarchy** spans enormous latency gaps and because real
  traffic has **locality and skew** — a tiny hot set absorbs most requests.
- The **hit ratio** governs everything, and its payoff is non-linear: eliminating the
  rare expensive miss is where the big wins hide.
- Caching trades **memory, staleness, and complexity** for latency and throughput; a
  cache is a second source of truth, so it's a second thing that can be wrong.
- Cache **as close to the consumer as you can afford** — browser, CDN, proxy,
  in-process, distributed, database — and **don't cache** correctness-critical,
  low-reuse, or write-heavy data.

Next: [Build an LRU Cache](../02-build-an-lru-cache/) — the fastest cache of all, a map
in your own process, and the eviction policy that decides what to forget.
