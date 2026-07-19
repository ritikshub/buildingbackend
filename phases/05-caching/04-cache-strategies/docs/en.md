# Cache Strategies: Aside, Through, Behind

> Now you have a cache and a database. The only real question left is choreography: who reads which first, who writes which first, and what happens when one of them fails mid-step. That order of operations is the whole design — and one wrong ordering serves stale data forever.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Redis Fundamentals](../03-redis-fundamentals/)
**Time:** ~75 minutes

## The Problem

You have two stores now: a fast cache (Redis) and a slow source of truth (the
database). Every request has to touch them in *some* order, and the ordering isn't a
detail — it decides three things at once:

- **Consistency** — how stale can a reader's answer be, and for how long?
- **Latency** — does a write pay for one store or both?
- **Failure behavior** — if the cache is down, do you degrade gracefully or fall over?

There is no single right answer; there's a small menu of named **strategies**, each a
different point on the trade-off curve. Knowing them by name — and knowing the one
subtle race that makes the naive version wrong — is what separates a cache that speeds
things up from one that quietly serves last week's price. This lesson names the
patterns, builds the dominant one, and shows the ordering that keeps cache and database
in agreement.

## The Concept

### Reads: cache-aside vs. read-through

**Cache-aside** (also *lazy loading*) puts your application in charge. The cache sits
"to the side"; your code orchestrates it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 516" width="100%" style="max-width:880px" role="img" aria-label="Cache-aside, also called lazy loading, drawn as a sequence between three participants: the application, the cache, and the database. The application always asks the cache first, with GET user colon 42. On a hit the cache returns the value straight from memory in well under a millisecond and the sequence ends there — the database is never touched. On a miss the cache returns nil, so the application does four more steps: it runs SELECT star FROM users WHERE id equals 42 against the database, waits roughly fifty milliseconds for the row to come back over disk and network, writes that row into the cache with SET user colon 42 and an expiry of 300 seconds, and finally returns the row to the caller. The miss path is deliberately drawn long and the hit path short, because that length difference is the entire point of the cache. Because the application — not the cache — orchestrates every step, only data that was actually requested is ever cached, and if the cache is unreachable every read simply degrades into a miss that still gets served from the database.">
  <defs>
    <marker id="p5l4a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l4a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l4a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Cache-aside: your app asks the cache first, and only pays for the database on a miss</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- actor headers -->
    <g stroke-width="1.7" stroke-linejoin="round">
      <rect x="70" y="46" width="160" height="30" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="370" y="46" width="160" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="670" y="46" width="160" height="30" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <text x="150" y="66" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">App</text>
    <text x="450" y="66" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">Cache</text>
    <text x="750" y="66" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">DB</text>
    <!-- lifelines -->
    <g stroke="currentColor" stroke-opacity="0.25" stroke-width="1.3" stroke-dasharray="4 5">
      <path d="M150 76 L150 132"/><path d="M150 154 L150 232"/><path d="M150 254 L150 460"/>
      <path d="M450 76 L450 132"/><path d="M450 154 L450 232"/><path d="M450 254 L450 460"/>
      <path d="M750 76 L750 132"/><path d="M750 154 L750 232"/><path d="M750 254 L750 460"/>
    </g>
    <!-- the one lookup every read starts with -->
    <path d="M156 110 L444 110" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p5l4a-ar)"/>
    <text x="300" y="104" text-anchor="middle" font-size="9.5" fill="currentColor">GET user:42</text>

    <!-- ===== HIT branch ===== -->
    <rect x="36" y="128" width="828" height="88" rx="10" fill="#0fa07f" fill-opacity="0.05"/>
    <rect x="52" y="132" width="796" height="22" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="450" y="147" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">alt · HIT — the key is already in the cache</text>
    <path d="M444 182 L156 182" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p5l4a-arg)"/>
    <text x="300" y="176" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">value (fast — RAM, sub-millisecond)</text>
    <text x="300" y="206" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">…and that's the whole read — the DB is never touched.</text>

    <!-- ===== MISS branch ===== -->
    <rect x="36" y="228" width="828" height="232" rx="10" fill="#e0930f" fill-opacity="0.055"/>
    <rect x="52" y="232" width="796" height="22" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-opacity="0.6" stroke-width="1"/>
    <text x="450" y="247" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.9">else · MISS — nothing cached under that key (the cold path, four extra steps)</text>
    <!-- slow path arrows -->
    <g fill="none" stroke="#e0930f" stroke-width="1.7">
      <path d="M444 284 L156 284" marker-end="url(#p5l4a-ara)"/>
      <path d="M156 322 L744 322" marker-end="url(#p5l4a-ara)"/>
      <path d="M744 360 L156 360" marker-end="url(#p5l4a-ara)"/>
    </g>
    <text x="300" y="278" text-anchor="middle" font-size="9.5" fill="#e0930f">nil — no entry for user:42</text>
    <text x="600" y="316" text-anchor="middle" font-size="9.5" fill="currentColor">SELECT * FROM users WHERE id = 42</text>
    <text x="600" y="354" text-anchor="middle" font-size="9.5" fill="#e0930f">row (slow — disk + network, ~50 ms)</text>
    <!-- populate -->
    <path d="M156 398 L444 398" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p5l4a-arg)"/>
    <text x="300" y="392" text-anchor="middle" font-size="9.5" fill="#0fa07f">SET user:42 = row  EX 300  ← populate, with a TTL</text>
    <!-- self-call: return -->
    <path d="M152 418 L212 418 L212 440 L158 440" fill="none" stroke="currentColor" stroke-width="1.5" marker-end="url(#p5l4a-ar)"/>
    <text x="224" y="434" font-size="9" fill="currentColor" opacity="0.85">return row — next read is a HIT</text>
  </g>
  <text x="450" y="484" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">The app — not the cache — runs this dance, so only data somebody actually asked for is ever stored (lazy loading).</text>
  <text x="450" y="502" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">If the cache is down, every read is just a miss: slower, but still serving. The first read of any key always pays full price.</text>
</svg>
```

This is the workhorse pattern — the one you'll write 90% of the time. Its properties fall
straight out of the diagram:

- **Only requested data is cached** (lazy) — you never waste memory on rows nobody reads.
- **Resilient to cache failure** — if Redis is down, every read is a miss and you fall
  through to the database. Slower, but *still serving*.
- **The cold-start miss is unavoidable** — the *first* read of any key always pays full
  price, because nothing populates the cache except a miss.
- **Staleness is possible** — the copy can drift from the DB until its TTL expires or you
  invalidate it, which is exactly the write problem below.

**Read-through** moves that orchestration *into* the cache layer. Your app asks only the
cache; on a miss the cache itself loads from the database, stores the result, and
returns it. Your application code no longer contains the miss-handling dance:

| | Cache-aside | Read-through |
|---|---|---|
| Who loads on miss | Your application code | The cache library / layer |
| App code | Cache and DB logic interleaved | Talks only to the cache |
| Cache down | Read falls through to DB | Often fails (cache is inline) |
| Best when | You want control + resilience | You want clean, uniform data access |

### Writes: through, behind, around

Reading is the easy half. On a **write** you must decide what happens to *both* stores:

- **Write-through** — write the cache **and** the database synchronously; return only
  after both succeed. The cache is never stale on a path you just wrote. The cost: every
  write pays *both* latencies, and you cache data that may never be read.
- **Write-behind** (write-back) — write the cache, return immediately, and flush to the
  database **asynchronously** (often batched). Writes feel instant and bursts get
  absorbed — but if the cache dies before the flush, those writes are **lost**, and the
  database is momentarily behind. Powerful and dangerous; reserved for high write volume
  where some loss is tolerable (metrics, view counts).
- **Write-around** — write **only** to the database and *don't* touch the cache; let the
  next read populate it via cache-aside. Ideal for write-heavy, read-rarely data — you
  avoid filling the cache with entries no one will read. The cost: freshly written data
  is a guaranteed miss on its first read.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 352" width="100%" style="max-width:880px" role="img" aria-label="The three write strategies side by side, each showing the same three boxes — app, cache and database — wired differently. Write-through: the app writes the cache and the database at the same time, both synchronously, and only returns once both have succeeded; the win is that a key you just wrote is never stale, the cost is that every write pays both latencies and you cache rows nobody may ever read. Write-behind, also called write-back: the app writes only the cache and returns immediately, and a background flush copies the data to the database later, often in batches; the win is instant writes that absorb bursts, the cost is that if the cache dies before the flush those writes are gone and the database lags behind. Write-around: the app writes straight to the database and the link to the cache is drawn dashed and crossed out because it is skipped entirely; the win is that the cache never fills with entries nobody reads, the cost is that freshly written data is a guaranteed miss on its first read, which cache-aside then repairs.">
  <defs>
    <marker id="p5l4b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l4b-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three ways to write — the same three boxes, wired differently</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <!-- panels -->
    <g fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.3" stroke-width="1.5">
      <rect x="14" y="48" width="282" height="214" rx="11"/>
      <rect x="309" y="48" width="282" height="214" rx="11"/>
      <rect x="604" y="48" width="282" height="214" rx="11"/>
    </g>
    <text x="155" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">WRITE-THROUGH</text>
    <text x="450" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#e0930f">WRITE-BEHIND (write-back)</text>
    <text x="745" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#7c5cff">WRITE-AROUND</text>

    <!-- boxes: App / Cache / DB, coloured as in the sequence above -->
    <g stroke-width="1.6" stroke-linejoin="round">
      <rect x="108" y="86" width="94" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="403" y="86" width="94" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="698" y="86" width="94" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="30"  y="200" width="96" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="325" y="200" width="96" height="30" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="620" y="200" width="96" height="30" rx="8" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.45"/>
      <rect x="184" y="200" width="96" height="30" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="479" y="200" width="96" height="30" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="774" y="200" width="96" height="30" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    </g>
    <g font-size="10.5" font-weight="700" text-anchor="middle">
      <text x="155" y="105" fill="#3553ff">App</text>
      <text x="450" y="105" fill="#3553ff">App</text>
      <text x="745" y="105" fill="#3553ff">App</text>
      <text x="78"  y="220" fill="#0fa07f">Cache</text>
      <text x="373" y="220" fill="#0fa07f">Cache</text>
      <text x="668" y="220" fill="#0fa07f" opacity="0.5">Cache</text>
      <text x="232" y="220" fill="#7c5cff">DB</text>
      <text x="527" y="220" fill="#7c5cff">DB</text>
      <text x="822" y="220" fill="#7c5cff">DB</text>
    </g>

    <!-- WRITE-THROUGH: both links synchronous -->
    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M131 116 L82 192" marker-end="url(#p5l4b-arg)"/>
      <path d="M179 116 L228 192" marker-end="url(#p5l4b-arg)"/>
    </g>
    <text x="97" y="152" text-anchor="end" font-size="8.5" font-weight="700" fill="#0fa07f">sync</text>
    <text x="213" y="152" text-anchor="start" font-size="8.5" font-weight="700" fill="#0fa07f">sync</text>
    <text x="155" y="250" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">returns only after BOTH succeed</text>

    <!-- WRITE-BEHIND: cache now, database later -->
    <path d="M426 116 L377 192" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p5l4b-arg)"/>
    <text x="392" y="152" text-anchor="end" font-size="8.5" font-weight="700" fill="#0fa07f">now</text>
    <path d="M425 215 L473 215" fill="none" stroke="#e0930f" stroke-width="1.7" stroke-dasharray="4 4" marker-end="url(#p5l4b-ara)"/>
    <text x="450" y="207" text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">async</text>
    <text x="450" y="250" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">app returns now; flush is batched, later</text>

    <!-- WRITE-AROUND: straight to the database, cache skipped -->
    <path d="M769 116 L818 192" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#p5l4b-arg)"/>
    <text x="803" y="152" text-anchor="start" font-size="8.5" font-weight="700" fill="#0fa07f">write</text>
    <path d="M721 116 L676 186" fill="none" stroke="#d64545" stroke-width="1.7" stroke-dasharray="4 4" stroke-opacity="0.9"/>
    <g stroke="#d64545" stroke-width="2" stroke-linecap="round">
      <path d="M667 186 L677 196"/>
      <path d="M677 186 L667 196"/>
    </g>
    <text x="688" y="150" text-anchor="end" font-size="8.5" font-weight="700" fill="#d64545">skipped</text>
    <text x="745" y="250" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">next read fills it — via cache-aside</text>

    <!-- trade-off captions -->
    <g font-size="9" text-anchor="middle">
      <text x="155" y="286" fill="#0fa07f">✓ a key you just wrote is never stale</text>
      <text x="155" y="302" fill="#e0930f">✗ every write pays cache + DB latency</text>
      <text x="450" y="286" fill="#0fa07f">✓ instant writes; absorbs write bursts</text>
      <text x="450" y="302" fill="#d64545">✗ cache dies before flush → writes lost</text>
      <text x="745" y="286" fill="#0fa07f">✓ cache never fills with unread rows</text>
      <text x="745" y="302" fill="#e0930f">✗ first read after a write always misses</text>
    </g>
  </g>
  <text x="450" y="334" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">The common, robust pairing: cache-aside reads + write-around writes — write the database first, then DELETE the cached key.</text>
</svg>
```

In practice the common, robust pairing is **cache-aside reads + write-around writes with
explicit invalidation**: reads populate lazily, writes go to the DB and *delete* the
cached key so the next read reloads fresh.

### The trap: update DB, then what?

Here's the subtlety that trips up nearly everyone. On a write, you must reconcile the
cache. Two choices — **update** the cached value, or **delete** it — and they are not
equal.

**Delete, don't update.** Two reasons:

1. **Concurrent writers can reorder.** Writer A sets the cache to *v1* and writer B sets
   it to *v2*; if their cache writes land in the opposite order from their DB writes, the
   cache ends up holding *v1* while the DB holds *v2* — stale forever. Deleting sidesteps
   this: whoever reads next reloads the current DB value.
2. **Don't compute what may never be read.** Updating recomputes and re-serializes a
   value on every write; deleting defers that cost to the next reader, who may never come.

And the ordering **within** the delete pattern matters. **Write the database first, then
delete the cache:**

```text
db.update(row)          # source of truth is correct first …
cache.delete(key)       # … then drop the stale copy; next read reloads
```

If you delete the cache *first* and then write the DB, a concurrent reader can slip in
between the two steps, miss the cache, read the **old** DB row, and repopulate the cache
with stale data that now outlives your write. DB-first closes most of that window.

> A rare race still survives even DB-first-then-delete (a reader that loaded the old
> value *before* your DB write can repopulate *after* your delete). Facebook's "Scaling
> Memcache at Facebook" (NSDI 2013) closes it with **leases**; you'll meet the same idea
> as single-flight locking in lesson 6. For most systems, DB-first-then-delete plus a
> short TTL is enough — the TTL is your backstop when invalidation races.

## Build It

A runnable cache-aside implementation with a deliberately slow "database," showing the
cold miss, the warm hit, and the write path that keeps them consistent. Stdlib only — the
cache and DB are dicts, with the DB penalized to make hits visible.

```python
# Cache-aside reads + write-around writes with delete-on-write invalidation.
# Ref: phases/05-caching/04-cache-strategies/docs/en.md
# Source of truth = "db"; the cache is a side store the app orchestrates.
import json
import time

db = {42: {"id": 42, "name": "Ada", "plan": "free"}}   # the slow source of truth
cache: dict[str, str] = {}                              # our Redis stand-in

def db_read(uid):
    time.sleep(0.05)                 # pretend a query costs 50 ms
    return db.get(uid)

def db_write(uid, row):
    time.sleep(0.05)
    db[uid] = row

def get_user(uid):                   # CACHE-ASIDE read
    key = f"user:{uid}"
    hit = cache.get(key)
    if hit is not None:
        return json.loads(hit), "HIT"
    row = db_read(uid)               # miss → source of truth
    if row is not None:
        cache[key] = json.dumps(row) # populate for next time (a TTL belongs here)
    return row, "MISS"

def update_user(uid, changes):       # WRITE-AROUND + invalidate
    row = {**db.get(uid, {"id": uid}), **changes}
    db_write(uid, row)               # 1) DB first — source of truth correct
    cache.pop(f"user:{uid}", None)   # 2) then DELETE the cache (never update it)

if __name__ == "__main__":
    t = time.perf_counter(); print(get_user(42)[1], f"{time.perf_counter()-t:.3f}s")  # MISS ~0.05s
    t = time.perf_counter(); print(get_user(42)[1], f"{time.perf_counter()-t:.3f}s")  # HIT  ~0.000s
    update_user(42, {"plan": "pro"})                                                   # invalidates
    print(get_user(42))              # MISS then repopulates with the NEW value
```

Running it prints a slow `MISS`, an instant `HIT`, then — after the update deletes the
key — another `MISS` that reloads the *new* `plan: pro`. If you had *updated* the cache
on write instead of deleting, this is exactly where a concurrent writer could have left
you serving `pro` when the DB said something else.

## Use It

The same pattern against real Redis, with the TTL that every cache-aside entry needs as
a safety net for missed invalidations:

```python
import json, os, redis

r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                   decode_responses=True)
TTL = 300  # seconds — the backstop if an invalidation is ever missed

def get_user(uid, db_read):
    key = f"user:{uid}"
    if (hit := r.get(key)) is not None:
        return json.loads(hit)
    row = db_read(uid)                          # your real SQL query
    if row is not None:
        r.set(key, json.dumps(row), ex=TTL)     # populate WITH a TTL
    return row

def update_user(uid, changes, db_write):
    db_write(uid, changes)                       # 1) database first
    r.delete(f"user:{uid}")                       # 2) delete, don't update
```

Production notes that ride on top of this:

- **Always set a TTL.** Even with perfect invalidation, a TTL bounds how long any bug can
  serve stale data. It converts "stale forever" into "stale for at most `TTL`."
- **Namespace and version your keys** (`user:v2:42`). Change the value's shape? Bump the
  version prefix and the old entries age out on their own — a deploy-safe invalidation.
- **Pick write-behind consciously.** It's tempting for its fast writes, but you're
  accepting possible data loss and DB lag. Use it for tolerant data (counters, analytics),
  never for money.

Every one of these strategies still leaves the same open question: *when exactly does a
cached entry stop being true, and how do you make it go away?* That is cache
invalidation — the genuinely hard part — and it's lesson 5.

## Key takeaways

- The **order** in which you touch cache and DB *is* the design — it fixes consistency,
  latency, and failure behavior all at once.
- **Cache-aside** (app orchestrates, lazy-loads on miss) is the default read pattern:
  memory-efficient and resilient to cache outages, at the cost of cold-start misses.
  **Read-through** hides the miss handling inside the cache layer.
- Writes choose among **write-through** (both stores, sync, always fresh), **write-behind**
  (cache now, DB later — fast but lossy), and **write-around** (DB only, populate on next
  read).
- On a write, **delete the cached key, don't update it**, and write the **database first,
  then delete** — the ordering that closes most staleness races.
- A short **TTL on every entry** is your backstop: it caps how long any missed
  invalidation can serve stale data.

Next: [Invalidation & TTLs](../05-invalidation-and-ttls/) — the hard half of caching, in
full.
