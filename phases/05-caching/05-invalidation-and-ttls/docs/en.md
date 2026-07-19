# Invalidation & TTLs

> Every cached entry is a bet that the source of truth hasn't changed. Invalidation is knowing when you've lost the bet — and it's hard because the cache has no idea the database moved on. TTLs are the humble, powerful answer: don't try to be right forever, just be right for a bounded while.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Cache Strategies: Aside, Through, Behind](../04-cache-strategies/)
**Time:** ~60 minutes

## The Problem

A cache entry is a photograph of the truth at one instant. The moment the database
changes, that photo might be a lie — but the cache doesn't know, because nothing tells
it. The database doesn't call the cache when a row updates. So the cache confidently
serves a stale answer until *something* removes the entry.

That "something" is **invalidation**, and it's genuinely one of the two hard problems in
computer science (Phil Karlton's line). Get it wrong in one direction — TTLs too long,
no invalidation — and users see yesterday's price, a deleted post, a revoked
permission. Get it wrong in the other — TTLs too short, invalidate everything constantly
— and your hit ratio collapses and the database takes the load you built the cache to
spare it.

There's a second, separate force removing entries too: **memory pressure**. When the
cache fills, it must evict *something* to make room, whether or not that thing is stale.
People conflate these two. They're different mechanisms with different triggers, and you
must reason about both.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 350" width="100%" style="max-width:880px" role="img" aria-label="A cache entry can leave the cache in exactly three ways, and each has a different driver. Expiration is time-driven: the entry's TTL passed, so the clock removed it — noticed passively on read and by an active background sweep. Eviction is memory-driven: the cache hit its maxmemory ceiling and the maxmemory-policy, such as allkeys-lru, chose a victim to make room, even if that entry was perfectly fresh. Invalidation is event-driven: a write changed the underlying data, so your code removes the entry now by deleting the key, bumping a key version, or incrementing a generation counter. Only invalidation is something you control on the write path.">
  <defs>
    <marker id="p5l5a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p5l5a-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="p5l5a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three ways an entry leaves the cache — three completely different drivers</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- the entry -->
    <rect x="24" y="140" width="150" height="70" rx="11" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8" stroke-linejoin="round"/>
    <text x="99" y="168" text-anchor="middle" font-size="12" font-weight="700" fill="#7c5cff">Cache entry</text>
    <text x="99" y="188" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">key → value</text>

    <!-- branches -->
    <g fill="none" stroke-width="1.8">
      <path d="M178 166 C 235 166, 240 94, 290 94" stroke="#e0930f" marker-end="url(#p5l5a-ara)"/>
      <path d="M178 178 L 290 178" stroke="#d64545" marker-end="url(#p5l5a-arr)"/>
      <path d="M178 190 C 235 190, 240 262, 290 262" stroke="#3553ff" marker-end="url(#p5l5a-arb)"/>
    </g>

    <!-- panels -->
    <g fill-opacity="0.07" stroke-width="1.7" stroke-linejoin="round">
      <rect x="296" y="58" width="584" height="72" rx="10" fill="#e0930f" stroke="#e0930f"/>
      <rect x="296" y="142" width="584" height="72" rx="10" fill="#d64545" stroke="#d64545"/>
      <rect x="296" y="226" width="584" height="72" rx="10" fill="#3553ff" stroke="#3553ff"/>
    </g>

    <text x="312" y="80" font-size="12" font-weight="700" fill="#e0930f">① EXPIRATION — time-driven</text>
    <text x="312" y="100" font-size="10" fill="currentColor">its TTL passed: you only ever trusted this copy for N seconds</text>
    <text x="312" y="120" font-size="9" fill="currentColor" opacity="0.72">trigger: the clock · found passively on read, and by the active background sweep</text>

    <text x="312" y="164" font-size="12" font-weight="700" fill="#d64545">② EVICTION — memory-driven</text>
    <text x="312" y="184" font-size="10" fill="currentColor">the cache is full: something must go to make room — even if it is fresh</text>
    <text x="312" y="204" font-size="9" fill="currentColor" opacity="0.72">trigger: maxmemory reached · maxmemory-policy picks the victim (allkeys-lru / lfu)</text>

    <text x="312" y="248" font-size="12" font-weight="700" fill="#3553ff">③ INVALIDATION — event-driven</text>
    <text x="312" y="268" font-size="10" fill="currentColor">the data changed: a write just made this copy a lie, so it must go now</text>
    <text x="312" y="288" font-size="9" fill="currentColor" opacity="0.72">trigger: your write path · delete the key, bump a key version, or INCR a generation</text>
  </g>
  <text x="450" y="322" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" font-weight="700" fill="currentColor">Three exits, three drivers: a clock, a memory ceiling, and a write. Do not confuse them.</text>
  <text x="450" y="341" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">Only invalidation is yours to trigger — expiration and eviction happen to you, so you must design for both.</text>
</svg>
```

## The Concept

### TTL: being right for a bounded while

A **TTL** (Time To Live) is a per-entry expiry: "trust this copy for N seconds, then
throw it away." It's the single most valuable idea in caching because it converts an
*unsolvable* problem (know the instant every value changes) into a *tunable* one (how
stale can I tolerate this being?). Even with zero explicit invalidation, a TTL guarantees
the cache self-heals: worst-case staleness is exactly the TTL.

Choosing the number is a direct trade:

- **Short TTL** → fresher data, lower hit ratio, more load on the source.
- **Long TTL** → higher hit ratio, less load, staler data.

Set it from *how fast the data actually changes and how much staleness hurts.* A stock
price: seconds. A user's display name: minutes. A list of countries: a day. There is no
universal value — there's the value that matches this data's tolerance.

There are two flavors. An **absolute TTL** expires N seconds after it was written, full
stop. A **sliding TTL** resets the clock on every access, so hot keys live indefinitely
and only idle ones expire — great for sessions, dangerous for data that must eventually
refresh regardless of traffic.

### How expiration actually runs: passive + active

How does a cache *notice* a TTL has passed for millions of keys without a timer on each?
Redis — and the `TTLCache` you'll build — uses a two-part scheme, and understanding it
explains a real memory gotcha:

- **Passive (lazy) expiration** — when a key is *accessed*, check its expiry first; if
  it's past, delete it and report a miss. Cheap, but a key that's set with a TTL and then
  *never read again* would sit in memory forever, dead but taking space.
- **Active expiration** — a background sweep periodically samples keys and deletes the
  expired ones. Redis samples ~20 random keys with a TTL, ten times a second, and repeats
  if too many were expired — probabilistically keeping the dead fraction low without ever
  scanning the whole keyspace.

Neither alone is enough; together they bound both wasted memory (active reclaims
never-touched dead keys) and wasted work (passive avoids scanning on the hot path).

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 430" width="100%" style="max-width:880px" role="img" aria-label="Redis runs expiration two ways at once. On the left, passive or lazy expiry: a client GET on a key reaches the decision expired? If yes, the key is deleted and the caller gets a miss; if no, the value is returned as a hit. It costs nothing until somebody asks, but a key that is never read again is never checked, so it stays in memory dead. On the right, active expiry: a background cycle running about ten times a second samples roughly twenty random keys that have a TTL, and asks expired? Expired ones are deleted, and if many of the sample were expired the cycle immediately samples again. That reclaims dead keys nobody reads without ever scanning the whole keyspace. Passive alone leaks memory, which is exactly why active expiry exists.">
  <defs>
    <marker id="p5l5b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l5b-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p5l5b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l5b-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Expiration runs twice: lazily when you read, and by a background sampler</text>
  <g fill-opacity="0.05" stroke-width="2" stroke-linejoin="round">
    <rect x="16" y="44" width="424" height="330" rx="12" fill="#3553ff" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="460" y="44" width="424" height="330" rx="12" fill="#7c5cff" stroke="#7c5cff" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="228" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#3553ff">PASSIVE (lazy) — on read</text>
    <text x="672" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#7c5cff">ACTIVE — background cycle, ~10×/sec</text>

    <!-- ===== passive ===== -->
    <rect x="158" y="92" width="140" height="34" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="228" y="114" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">GET key</text>
    <path d="M228 126 L228 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p5l5b-ar)"/>
    <path d="M228 152 L304 186 L228 220 L152 186 Z" fill="currentColor" fill-opacity="0.07" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="228" y="190" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">expired?</text>
    <path d="M152 186 L120 186 L120 244" fill="none" stroke="#e0930f" stroke-width="1.7" marker-end="url(#p5l5b-ara)"/>
    <path d="M304 186 L338 186 L338 244" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p5l5b-arg)"/>
    <text x="136" y="180" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">yes</text>
    <text x="322" y="180" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">no</text>
    <rect x="30" y="252" width="180" height="56" rx="9" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="120" y="274" text-anchor="middle" font-size="10" fill="currentColor">delete the key</text>
    <text x="120" y="292" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">return a MISS</text>
    <rect x="248" y="252" width="180" height="56" rx="9" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="338" y="274" text-anchor="middle" font-size="10" fill="currentColor">return the value</text>
    <text x="338" y="292" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">cache HIT</text>
    <text x="228" y="336" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">Costs nothing until somebody asks for the key.</text>
    <text x="228" y="354" text-anchor="middle" font-size="9" fill="#d64545">But a key nobody reads again is never checked — dead, still in RAM.</text>

    <!-- ===== active ===== -->
    <rect x="572" y="92" width="200" height="42" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="672" y="110" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">sample ~20 random keys</text>
    <text x="672" y="126" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">that have a TTL</text>
    <path d="M672 134 L672 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p5l5b-ar)"/>
    <path d="M672 152 L748 186 L672 220 L596 186 Z" fill="currentColor" fill-opacity="0.07" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    <text x="672" y="190" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">expired?</text>
    <path d="M596 186 L564 186 L564 244" fill="none" stroke="#e0930f" stroke-width="1.7" marker-end="url(#p5l5b-ara)"/>
    <text x="580" y="180" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">yes</text>
    <rect x="474" y="252" width="180" height="56" rx="9" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-width="1.7" stroke-linejoin="round"/>
    <text x="564" y="274" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">delete it</text>
    <text x="564" y="292" text-anchor="middle" font-size="10" fill="currentColor">(reclaim the memory)</text>
    <path d="M748 186 L864 186 L864 113 L780 113" fill="none" stroke="#7c5cff" stroke-width="1.7" stroke-linejoin="round" marker-end="url(#p5l5b-arp)"/>
    <text x="754" y="177" font-size="9" font-weight="700" fill="#7c5cff">if many expired</text>
    <text x="754" y="205" font-size="9" fill="currentColor" opacity="0.75">→ sample again now</text>
    <text x="672" y="336" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">Probabilistic — it never scans the whole keyspace.</text>
    <text x="672" y="354" text-anchor="middle" font-size="9" fill="#0fa07f">Reclaims dead keys that no read will ever touch.</text>
  </g>
  <text x="450" y="398" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" font-weight="700" fill="currentColor">Passive alone leaks memory: a key with a TTL that nobody reads again is never checked, so it never dies.</text>
  <text x="450" y="418" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">That is exactly why active expiry exists — passive bounds wasted work, active bounds wasted memory.</text>
</svg>
```

### Jitter: don't let a crowd expire together

If you write 10,000 entries with the same 300-second TTL in one burst (say, warming a
cache after deploy), they all **expire at the same instant** — and 10,000 simultaneous
misses stampede the database. The fix is one line: **jitter** the TTL, `ttl + random(0,
spread)`, so expiries spread out over a window instead of firing as one wave. Jitter here
is the first defense against the stampede you'll study fully in lesson 6.

### Explicit invalidation strategies

TTLs bound staleness; explicit invalidation *ends* it early when you know the data
changed. The toolkit, from simplest to most powerful:

1. **TTL-only** — no explicit invalidation; accept staleness up to the TTL. Perfect for
   data where "a minute behind" is fine. Simplest thing that works.
2. **Write-triggered delete** — on every write, delete the affected key (lesson 4).
   Near-immediate freshness, but you must know *exactly* which keys a write touches.
3. **Key versioning** — bake a version into the key (`user:42:v3`). To invalidate, use a
   new version; old keys become unreachable and age out by TTL. No delete call, and it's
   deploy-safe: change the value's shape, bump the version, old-shape entries vanish on
   their own.
4. **Namespace (generation) versioning** — the elegant answer to *group* invalidation.
   Redis can't cheaply "delete every key for product 42" (no efficient wildcard delete).
   Instead, store a **generation counter** for the group and fold it into every key:

   ```text
   gen = get("gen:product:42")            # e.g. 7
   key = "product:42:v7:price"            # every key carries the generation
   ...to invalidate the WHOLE group:  INCR gen:product:42  → 8
   ```

   Bumping the counter to 8 instantly orphans *every* `...:v7:...` key at once — no scan,
   no wildcard, O(1). The old keys are unreachable and expire on their TTL. This one trick
   handles "flush everything about this product / tenant / user" cleanly.

### Negative caching: cache the misses too

Cache-aside has a blind spot: it only stores *found* values. Ask for a key that doesn't
exist and every request is a miss that falls through to the database — so a lookup for a
nonexistent user hammers the DB just as hard as a popular one, forever. Worse, it's an
attack vector: **cache penetration** is when someone floods you with requests for keys
they *know* aren't cached (random user IDs, garbage slugs), and every one becomes a DB
query the cache never absorbs.

The fix is **negative caching** — store the *absence* too, under a **short** TTL:

```text
row = db_read(key)
if row is None:
    cache.set(key, TOMBSTONE, ttl=30)   # remember "not found" for 30s
else:
    cache.set(key, row, ttl=300)
```

Use a distinct **tombstone** marker (not a bare `null` you can't tell from a cache miss),
and keep the negative TTL *short* — a "not found" that becomes "found" a second later must
not stay wrong for long. For adversarial key-space attacks, pair it with a **Bloom filter**
of keys that exist, so obviously-absent keys are rejected before they ever touch the cache
or DB.

### Eviction: when memory, not time, forces the choice

Separately from TTLs, a bounded cache must evict when full. Redis is governed by two
settings: `maxmemory` (the ceiling) and `maxmemory-policy` (who dies when you hit it):

| Policy | Evicts from | Using |
|---|---|---|
| `noeviction` | — | **rejects new writes** with an error (the default!) |
| `allkeys-lru` | all keys | least-recently-used |
| `allkeys-lfu` | all keys | least-frequently-used |
| `volatile-lru` | only keys **with a TTL** | least-recently-used |
| `volatile-ttl` | only keys with a TTL | soonest-to-expire first |
| `allkeys-random` | all keys | random |

The default `noeviction` is a **classic 3 a.m. outage**: a pure cache fills up, Redis
starts rejecting writes, and your app — which assumed it could always cache — begins
erroring. For a cache, set `allkeys-lru` (or `allkeys-lfu`) so it sheds cold data
gracefully. Note Redis approximates LRU/LFU by **sampling** a few keys rather than
maintaining the exact list you built in lesson 2 — a deliberate accuracy-for-memory
trade at scale. And `volatile-*` policies only consider keys that have a TTL, which is
one more reason to **give every cache key a TTL.**

### Name the guarantee: eventual consistency

Put it together and be honest about what a cache offers: **eventual consistency bounded
by your TTL and invalidation latency.** Readers may see a stale value for a while, but
the system converges. That's a perfectly good guarantee for most reads — as long as you
*chose* it deliberately and didn't cache the one thing that needed to be exactly right.

## Build It

A TTL cache from scratch showing passive expiry on read, an active sweep, jittered TTLs,
and generation-based group invalidation — the whole toolkit, stdlib only.

```python
# A TTL cache: passive (on-read) + active (sweep) expiry, jitter, generation busting.
# Ref: phases/05-caching/05-invalidation-and-ttls/docs/en.md
import random
import time
from dataclasses import dataclass

@dataclass
class Entry:
    value: object
    expires_at: float

class TTLCache:
    def __init__(self):
        self._data: dict[str, Entry] = {}

    def set(self, key, value, ttl, jitter=0.0):
        # jitter spreads expiries so a burst of keys doesn't die at one instant
        self._data[key] = Entry(value, time.monotonic() + ttl + random.uniform(0, jitter))

    def get(self, key):
        e = self._data.get(key)
        if e is None:
            return None                          # miss
        if time.monotonic() >= e.expires_at:     # PASSIVE expiry on access
            del self._data[key]
            return None                          # expired → miss
        return e.value

    def purge(self):                             # ACTIVE expiry: reclaim dead keys
        now = time.monotonic()
        dead = [k for k, e in self._data.items() if now >= e.expires_at]
        for k in dead:
            del self._data[k]
        return len(dead)

# Generation-based group invalidation: bump one counter to orphan a whole group.
generation: dict[str, int] = {}

def gkey(group, field):
    gen = generation.setdefault(group, 1)
    return f"{group}:v{gen}:{field}"

def invalidate_group(group):
    generation[group] = generation.get(group, 1) + 1   # O(1) — old keys now unreachable

if __name__ == "__main__":
    c = TTLCache()
    c.set("price:42", 999, ttl=0.05)             # 50 ms TTL
    print("fresh:", c.get("price:42"))           # 999
    time.sleep(0.06)
    print("expired:", c.get("price:42"))         # None — passive expiry deleted it

    # Group busting: every field of product 42 shares a generation.
    k1 = gkey("product:42", "price"); c.set(k1, 10, ttl=60)
    print("before bust:", c.get(gkey("product:42", "price")))   # 10 (same key)
    invalidate_group("product:42")                              # INCR the generation
    print("after bust: ", c.get(gkey("product:42", "price")))   # None — key changed
```

The expired read returns `None` because `get` checked the clock before returning (passive
expiry). After `invalidate_group`, `gkey` computes a *new* key (`v2`), so the old `v1`
entry is simply unreachable — no delete, no scan. That's how you flush a whole group in
one atomic increment.

## Use It

Redis gives you all of this natively:

```python
import os, redis
r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                   decode_responses=True)

r.set("user:42", data, ex=300)     # write WITH a TTL (absolute, 300s)
r.ttl("user:42")                   # seconds left; -1 = no expiry, -2 = key missing
r.expire("user:42", 60)            # (re)set the TTL on an existing key
r.persist("user:42")               # remove the TTL — make it permanent (rarely wise)

# Generation busting for group invalidation, in Redis:
gen = r.incr("gen:product:42")     # bump once to orphan every product:42:v*:* key
price_key = f"product:42:v{gen}:price"
r.set(price_key, "9.99", ex=300)
```

And set the memory policy so a full cache degrades instead of erroring — this belongs in
`redis.conf` or via `CONFIG SET`:

```text
maxmemory 2gb
maxmemory-policy allkeys-lru      # shed cold data under pressure; NOT the default
```

Leaving `maxmemory-policy` at its `noeviction` default is one of the most common
self-inflicted outages in backend engineering: the cache silently becomes a wall that
rejects writes the moment it fills.

The one hazard TTLs *create* is that a popular key's expiry can trigger a flood of
simultaneous misses — the cache stampede. Jitter softens it; lesson 6 defeats it.

## Key takeaways

- A cached entry is a **bet the source hasn't changed**; nothing tells the cache when it
  has, so you need **invalidation** — the genuinely hard half of caching.
- A **TTL** turns "be right forever" into "be right for a bounded while," making
  staleness a *tunable* (short = fresh + costly, long = cheap + stale). Add **jitter** so
  a burst of entries doesn't expire in one wave.
- Expiration runs as **passive** (checked on read) + **active** (background sampling)
  together — one bounds wasted work, the other bounds wasted memory.
- Invalidate explicitly with **write-triggered deletes**, **key versioning**, and
  **generation (namespace) versioning** — bump one counter to orphan an entire group in
  O(1).
- **Negatively cache** the misses too (a short-TTL tombstone) so lookups for absent keys
  don't hammer the DB — the defense against **cache-penetration** attacks.
- **Eviction is memory-driven, not time-driven**: set `maxmemory` + `allkeys-lru`
  (never leave the `noeviction` default on a pure cache). A cache offers **eventual
  consistency bounded by TTL + invalidation latency** — choose that guarantee on purpose.

Next: [Cache Stampede & the Thundering Herd](../06-cache-stampede/) — what happens the
instant a hot key expires, and how to stop the herd.
