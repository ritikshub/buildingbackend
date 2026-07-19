# Cache Stampede & the Thundering Herd

> The cache was protecting the database from a million reads a minute. Then the one hot key expired, and in the same millisecond all those reads became database queries. The cache didn't just stop helping — it handed the database a synchronized punch it was never sized to take.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Invalidation & TTLs](../05-invalidation-and-ttls/)
**Time:** ~75 minutes

## The Problem

Picture the front-page article. Its cache entry serves 50,000 reads a second, every one
a cheap hit; the database sees nothing. Then the TTL expires.

For the next 50 milliseconds — however long the recompute takes — every incoming request
finds the key missing and does the "obvious" thing cache-aside tells it to: go read the
database and repopulate. But they *all* do it, at once. One expiry converts 50,000 hits
into 50,000 identical database queries fired in the same instant, all computing the exact
same value.

This is the **cache stampede**, also called the **thundering herd** or **dogpile**. And
it has a vicious feedback loop: the recompute is slow *because* the database is now
overloaded, so it takes longer, so more requests pile in behind it, so the database gets
slower still. A system that was completely healthy a moment ago can collapse into a
**metastable failure** — one that doesn't recover even after the traffic spike passes,
because the herd keeps re-forming on every failed recompute.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:880px" role="img" aria-label="The cache stampede. A TTL expires on one hot key, and the 50,000 concurrent requests that were being served as cheap cache hits all become misses in the same instant. Because cache-aside tells each miss to read the database and repopulate, every one of them fires its own query, so a fan of 50,000 identical queries collapses onto a single database that was never sized for them. The database becomes overloaded, which makes the recompute slower, which lets more requests pile up behind it, which makes the database slower still. That feedback arrow loops back to the requests: the herd re-forms on every failed recompute, so a healthy system can collapse and stay collapsed even after the traffic spike passes.">
  <defs>
    <marker id="p5l6a-am" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p5l6a-ad" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">One expiry turns 50,000 cache hits into 50,000 database queries</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="290" y="44" width="300" height="34" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.7"/>
    <text x="440" y="66" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">TTL expires on ONE hot key</text>
    <path d="M440 80 L440 96" fill="none" stroke="#e0930f" stroke-width="1.7" marker-end="url(#p5l6a-am)"/>

    <rect x="170" y="100" width="540" height="44" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.8"/>
    <text x="440" y="120" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">50,000 concurrent requests — every one now a MISS</text>
    <text x="440" y="136" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">cache-aside says "read the database and repopulate" — so all 50,000 do, at once</text>

    <g fill="none" stroke="#e0930f" stroke-width="1.4" stroke-opacity="0.85">
      <path d="M220 148 L352.0 286" marker-end="url(#p5l6a-am)"/>
      <path d="M260 148 L366.7 286" marker-end="url(#p5l6a-am)"/>
      <path d="M300 148 L381.3 286" marker-end="url(#p5l6a-am)"/>
      <path d="M340 148 L396.0 286" marker-end="url(#p5l6a-am)"/>
      <path d="M380 148 L410.7 286" marker-end="url(#p5l6a-am)"/>
      <path d="M420 148 L425.3 286" marker-end="url(#p5l6a-am)"/>
      <path d="M460 148 L440.0 286" marker-end="url(#p5l6a-am)"/>
      <path d="M500 148 L454.7 286" marker-end="url(#p5l6a-am)"/>
      <path d="M540 148 L469.3 286" marker-end="url(#p5l6a-am)"/>
      <path d="M580 148 L484.0 286" marker-end="url(#p5l6a-am)"/>
      <path d="M620 148 L498.7 286" marker-end="url(#p5l6a-am)"/>
      <path d="M660 148 L513.3 286" marker-end="url(#p5l6a-am)"/>
      <path d="M700 148 L528.0 286" marker-end="url(#p5l6a-am)"/>
    </g>
    <rect x="40" y="206" width="220" height="58" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.2"/>
    <text x="150" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">each MISS → 1 query</text>
    <text x="150" y="242" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">no lock, no queue —</text>
    <text x="150" y="256" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">nothing coordinates them</text>
    <rect x="645" y="206" width="190" height="58" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.2"/>
    <text x="740" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">×50,000, one instant</text>
    <text x="740" y="242" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">all computing the</text>
    <text x="740" y="256" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">exact same value</text>

    <path d="M340 292 L340 356 A100 13 0 0 0 540 356 L540 292" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.8"/>
    <ellipse cx="440" cy="292" rx="100" ry="13" fill="#d64545" fill-opacity="0.18" stroke="#d64545" stroke-width="1.8"/>
    <text x="440" y="320" text-anchor="middle" font-size="12" font-weight="700" fill="#d64545">DATABASE</text>
    <text x="440" y="338" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">OVERLOADED</text>
    <path d="M440 370 L440 388" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p5l6a-ad)"/>

    <rect x="120" y="392" width="640" height="54" rx="10" fill="#d64545" fill-opacity="0.08" stroke="#d64545" stroke-opacity="0.7" stroke-width="1.6"/>
    <text x="440" y="414" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">Recompute gets SLOWER → more requests pile up → database slower still</text>
    <text x="440" y="433" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the herd re-forms on every failed recompute — a healthy system collapses and stays collapsed</text>

    <path d="M762 419 L826 419 Q848 419 848 397 L848 144 Q848 122 826 122 L718 122" fill="none" stroke="#d64545" stroke-width="2" marker-end="url(#p5l6a-ad)"/>
    <text x="786" y="113" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">and it repeats</text>
    <text x="838" y="306" text-anchor="end" font-size="8.5" fill="#d64545" opacity="0.9">the death spiral:</text>
    <text x="838" y="320" text-anchor="end" font-size="8.5" fill="#d64545" opacity="0.9">worse, not just bad</text>

    <text x="440" y="468" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">One hot key + a hard expiry + high concurrency + a slow recompute = a synchronized punch at the database.</text>
    <text x="440" y="486" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">Remove any one of those four factors and the stampede shrinks. The next diagram removes one: 50,000 misses, ONE query.</text>
  </g>
</svg>
```

The root cause is precise: **one hot key + a hard expiry + high concurrency + a slow
recompute.** Remove any one factor and the stampede shrinks. This lesson removes them.

## The Concept

### Defense 1: coalesce the herd (single-flight)

The requests are all computing the *same value*. So compute it **once** and share the
result with everyone else who's waiting. This is **request coalescing** / **single-flight**:
the first request to miss becomes the "leader," runs the recompute, and every other
request for the same key parks until the leader finishes, then takes the leader's result.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 676" width="100%" style="max-width:880px" role="img" aria-label="Single-flight, the fix for the stampede, drawn as the same picture as the stampede diagram down to the point where the flood lands. The same hot key expires and the same 50,000 concurrent requests all miss in the same instant, so the same fan of arrows forms. But instead of reaching the database, the fan collides with a single-flight gate that holds one lock per key. The first request to miss wins the lock and becomes the leader; the other 49,999 lose it and park. The leader runs the recompute exactly once, which means the database receives exactly one query instead of fifty thousand. The single result is then published back to every waiter, and all 50,000 requests end up with the value. There is no feedback arrow back to the requests, because nothing piles up: the flow terminates instead of feeding itself.">
  <defs>
    <marker id="p5l6b-am" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p5l6b-ag" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l6b-ab" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">Single-flight: the same 50,000 misses, but ONE of them reaches the database</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="290" y="44" width="300" height="34" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.7"/>
    <text x="440" y="66" text-anchor="middle" font-size="11" font-weight="700" fill="#e0930f">TTL expires on ONE hot key</text>
    <path d="M440 80 L440 96" fill="none" stroke="#e0930f" stroke-width="1.7" marker-end="url(#p5l6b-am)"/>

    <rect x="170" y="100" width="540" height="44" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.8"/>
    <text x="440" y="120" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">50,000 concurrent requests — every one now a MISS</text>
    <text x="440" y="136" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">nothing about the traffic changed — only what happens next</text>

    <g fill="none" stroke="#e0930f" stroke-width="1.4" stroke-opacity="0.85">
      <path d="M220 148 L352.0 286" marker-end="url(#p5l6b-am)"/>
      <path d="M260 148 L366.7 286" marker-end="url(#p5l6b-am)"/>
      <path d="M300 148 L381.3 286" marker-end="url(#p5l6b-am)"/>
      <path d="M340 148 L396.0 286" marker-end="url(#p5l6b-am)"/>
      <path d="M380 148 L410.7 286" marker-end="url(#p5l6b-am)"/>
      <path d="M420 148 L425.3 286" marker-end="url(#p5l6b-am)"/>
      <path d="M460 148 L440.0 286" marker-end="url(#p5l6b-am)"/>
      <path d="M500 148 L454.7 286" marker-end="url(#p5l6b-am)"/>
      <path d="M540 148 L469.3 286" marker-end="url(#p5l6b-am)"/>
      <path d="M580 148 L484.0 286" marker-end="url(#p5l6b-am)"/>
      <path d="M620 148 L498.7 286" marker-end="url(#p5l6b-am)"/>
      <path d="M660 148 L513.3 286" marker-end="url(#p5l6b-am)"/>
      <path d="M700 148 L528.0 286" marker-end="url(#p5l6b-am)"/>
    </g>
    <rect x="40" y="206" width="220" height="58" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.2"/>
    <text x="150" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">the SAME flood</text>
    <text x="150" y="242" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">as the last diagram —</text>
    <text x="150" y="256" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">nothing upstream changed</text>
    <rect x="645" y="206" width="190" height="58" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.2"/>
    <text x="740" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">the only change:</text>
    <text x="740" y="242" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">what the flood</text>
    <text x="740" y="256" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">collides with</text>

    <rect x="240" y="292" width="400" height="48" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/>
    <text x="440" y="313" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">SINGLE-FLIGHT GATE · one lock per key K</text>
    <text x="440" y="331" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">the first request to miss wins the lock; the rest park on it</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.6">
      <path d="M440 342 L440 358"/>
      <path d="M255 358 L625 358"/>
      <path d="M255 358 L255 372" marker-end="url(#p5l6b-ag)"/>
    </g>
    <path d="M625 358 L625 372" fill="none" stroke="#3553ff" stroke-width="1.6" marker-end="url(#p5l6b-ab)"/>
    <text x="255" y="352" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">1 wins the lock</text>
    <text x="625" y="352" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">49,999 lose it</text>

    <rect x="110" y="376" width="290" height="66" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="255" y="398" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">THE LEADER — 1 request</text>
    <text x="255" y="416" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">runs the recompute exactly once</text>
    <text x="255" y="433" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">everyone's work, done a single time</text>

    <rect x="480" y="376" width="290" height="66" rx="10" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.8"/>
    <text x="625" y="398" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">THE WAITERS — 49,999</text>
    <text x="625" y="416" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">park until the leader finishes</text>
    <text x="625" y="433" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">zero database calls between them</text>

    <path d="M255 446 L255 466" fill="none" stroke="#0fa07f" stroke-width="2.4" marker-end="url(#p5l6b-ag)"/>
    <text x="272" y="462" font-size="11" font-weight="700" fill="#0fa07f">1 DB query</text>

    <path d="M160 482 L160 536 A95 12 0 0 0 350 536 L350 482" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.8"/>
    <ellipse cx="255" cy="482" rx="95" ry="12" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="255" y="508" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">DATABASE</text>
    <text x="255" y="526" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">exactly 1 query</text>

    <path d="M353 508 L600 508 Q625 508 625 483 L625 447" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p5l6b-ag)"/>
    <text x="490" y="500" text-anchor="middle" font-size="9" fill="#0fa07f">the one result, published to every waiter</text>

    <path d="M255 550 L255 570" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p5l6b-ag)"/>
    <path d="M772 409 L826 409 Q848 409 848 431 L848 578 Q848 600 826 600 L764 600" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p5l6b-ab)"/>
    <text x="838" y="470" text-anchor="end" font-size="8.5" fill="#3553ff" opacity="0.9">each waiter wakes with</text>
    <text x="838" y="484" text-anchor="end" font-size="8.5" fill="#3553ff" opacity="0.9">the leader's value</text>

    <rect x="120" y="574" width="640" height="54" rx="10" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.8" stroke-width="1.6"/>
    <text x="440" y="596" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">All 50,000 requests get the value — the database served exactly ONE query</text>
    <text x="440" y="615" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">no pile-up, no feedback loop — the flow ends here instead of feeding itself</text>

    <text x="440" y="650" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Same flood, same instant, same key — the only change is that one request does the work and 49,999 share it.</text>
    <text x="440" y="668" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">It coalesces within ONE process: 10 app instances elect 10 leaders, so a truly hot key escalates to a fleet-wide lock.</text>
  </g>
</svg>
```

50,000 requests, **one** database query. Single-flight is the single highest-leverage
fix, and you'll build it in a few dozen lines. Its one limit: it coalesces *within one
process*. Ten app instances each elect their own leader, so the database sees up to ten
queries, not one — better than 50,000, but for a truly hot key you escalate to a
**distributed lock** (below) so the whole fleet elects a single leader.

### Defense 2: don't all expire at once (probabilistic early refresh)

The stampede needs a *synchronized* expiry. What if the key never expired for everyone at
the same instant? **Probabilistic early expiration** makes each reader roll dice on every
access to decide whether to refresh the value *early* — a little before the real
deadline. Almost everyone reads the still-cached value; one unlucky (or rather, elected)
request refreshes ahead of the cliff, so the deadline is never a synchronized event.

The elegant version is **XFetch** (Vattani, Chierichetti & Lowenstein, *Optimal
Probabilistic Cache Stampede Prevention*, VLDB 2015). You store, alongside the value, how
long its last recompute took (`delta`). On each read you refresh early when:

```text
now  -  delta × beta × ln(random())  ≥  expiry_time
```

Because `ln(random())` is negative, this pulls the effective deadline *earlier* by a
random amount that scales with `delta` — so **expensive-to-recompute keys start refreshing
sooner**, exactly the ones a stampede would hurt most. `beta` (default 1) tunes
eagerness. The result: recomputes get smeared across a window before the TTL, and the
cliff disappears — with no locking at all.

### Defense 3: serve stale while you revalidate

The reason a stampede blocks users is that everyone *waits* for the fresh value. But you
have a slightly-old value in hand — why not serve it? **Stale-while-revalidate** keeps the
expired entry around briefly; when a request arrives after expiry, it **returns the stale
value immediately** and kicks off a **background refresh**. Nobody blocks on the recompute;
the herd never forms because there's no pile of waiting requests. Readers accept a few
seconds of staleness (which a cache already implies) in exchange for never feeling the
miss. You'll see this exact directive again as an HTTP header in lesson 8.

### The layered defense

These aren't competitors — production systems stack them:

| Layer | Technique | Stops |
|---|---|---|
| TTL | **Jitter** (lesson 5) | Bursts of keys expiring together |
| Read | **Probabilistic early refresh** | The synchronized single-key cliff |
| Read | **Single-flight** (in-process) | Concurrent misses within an instance |
| Read | **Distributed lock** (fleet-wide) | Concurrent misses across instances |
| Read | **Serve-stale + async refresh** | Anyone blocking on a recompute |
| Hot keys | **Background refresh-ahead** | Known-hot keys ever expiring on the read path |

## Build It

Single-flight from scratch in Python: a class that guarantees a function runs **exactly
once per key**, no matter how many threads ask concurrently — they all share the one
result. Python's standard library has no built-in single-flight, so this small class *is*
the tool; async stacks get the same effect from a per-key `asyncio.Future` (as `aiocache`
does).

```python
# Single-flight: coalesce concurrent calls for the same key into one execution.
# Ref: phases/05-caching/06-cache-stampede/docs/en.md
# The first caller for a key computes; the rest wait and share the result.
import threading
import time

class _Call:
    __slots__ = ("done", "value", "error")
    def __init__(self):
        self.done = threading.Event()   # fired when the leader finishes
        self.value = None
        self.error = None

class Group:
    """Coalesce duplicate concurrent calls keyed by a string."""
    def __init__(self):
        self._lock = threading.Lock()
        self._calls = {}                # key -> _Call currently in flight

    def do(self, key, fn):
        self._lock.acquire()
        call = self._calls.get(key)
        if call is not None:            # a leader is already computing this key
            self._lock.release()
            call.done.wait()            # park until it finishes …
            if call.error:
                raise call.error
            return call.value           # … and share its result — no second DB call
        call = _Call()
        self._calls[key] = call         # become the leader for this key
        self._lock.release()

        try:
            call.value = fn()           # THE one execution
        except Exception as e:          # propagate the failure to every waiter
            call.error = e
        finally:
            call.done.set()             # wake everyone waiting
            with self._lock:
                del self._calls[key]    # clear so a later miss can recompute fresh

        if call.error:
            raise call.error
        return call.value

def main():
    g = Group()
    db_calls = 0
    db_lock = threading.Lock()

    def load():                         # stand-in for a slow DB recompute
        nonlocal db_calls
        with db_lock:
            db_calls += 1
        time.sleep(0.05)                # I/O releases the GIL, so other threads run
        return "front-page article"

    N = 500                             # 500 threads (goroutines would scale to 50k cheaply)
    start = threading.Event()           # a release valve so all requests fire at once

    def worker():
        start.wait()                    # park until every thread is ready …
        g.do("article:hot", load)

    threads = [threading.Thread(target=worker) for _ in range(N)]
    for t in threads:
        t.start()
    start.set()                         # … then let them all stampede simultaneously
    for t in threads:
        t.join()
    print(f"{N} concurrent misses → DB hit {db_calls} time(s)")

if __name__ == "__main__":
    main()
```

Run `python main.py`:

```console
500 concurrent misses → DB hit 1 time(s)
```

Five hundred concurrent threads, **one** database call. Every thread after the leader
found a `_Call` already registered for the key, waited on its `Event`, and walked away
with the shared result. (OS threads are far heavier than goroutines, so we demo with 500;
the mechanism is identical at 50,000 — and because the recompute is I/O, it releases the
GIL, so the waiting threads never spin.)

## Use It

In one process, the `Group` class you just built is the tool (and `aiocache` gives asyncio
the same coalescing via a shared future). But a hot key on a fleet needs a **fleet-wide**
leader — a distributed lock in Redis, so only *one* process recomputes while the others
briefly serve stale or wait:

```python
# Fleet-wide single-flight via a Redis lock (SET NX). Illustrative.
import os, time, redis

r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                   decode_responses=True)

def get_hot(key, load):
    v = r.get(key)
    if v is not None:
        return v                                 # fast path: hit
    # Only one caller across the whole fleet wins the lock (nx = set if not exists).
    won = r.set("lock:" + key, "1", nx=True, ex=5)
    if not won:
        time.sleep(0.05)                          # another instance is recomputing …
        return r.get(key)                         # … read the value it just wrote
    try:
        v = load()                                # exactly one recompute in the fleet
        r.set(key, v, ex=300)
        return v
    finally:
        r.delete("lock:" + key)
```

Two cautions that matter in production:

- **The lock TTL is load-bearing.** If the leader crashes mid-recompute without the TTL,
  the lock is held forever and *nothing* refreshes — you've traded a stampede for a
  deadlock. The TTL guarantees the lock self-releases. (Correct distributed locking —
  fencing tokens, the Redlock debate — is a distributed-systems topic; a single-instance `SET NX PX`
  with a token is enough for stampede control.)
- **Prefer serve-stale over block-and-wait for the losers.** Returning the slightly-stale
  value beats making 49,999 requests sleep. Combine the lock (one refresher) with
  stale-while-revalidate (everyone else keeps moving).

For the highest-traffic keys, sidestep the read path entirely with **refresh-ahead**: a
background job recomputes known-hot keys *before* they expire, so a user request never
triggers a recompute at all. And always keep lesson 5's **TTL jitter** on — it stops many
keys from expiring together, which single-flight (per-key) doesn't address.

## Key takeaways

- A **cache stampede** (thundering herd / dogpile) happens when a hot key expires and a
  flood of concurrent misses all recompute the same value at once — and its feedback loop
  can drive a healthy system into **metastable collapse**.
- **Single-flight / request coalescing** elects one leader per key so N concurrent misses
  cause **one** recompute; it's per-process, so a truly hot key escalates to a
  **fleet-wide distributed lock**.
- **Probabilistic early expiration (XFetch)** dissolves the synchronized cliff by having
  readers refresh slightly early, sooner for costlier keys — no locking required.
- **Serve-stale-while-revalidate** returns the old value instantly and refreshes in the
  background, so no one ever blocks on a recompute.
- Stack the defenses: **TTL jitter + early refresh + single-flight/lock + serve-stale +
  refresh-ahead** for known-hot keys. A distributed lock's **TTL is mandatory** or you
  swap a stampede for a deadlock.

Next: [CDNs & Edge Caching](../07-cdns-and-edge-caching/) — push the cache out of your
datacenter and to within a few milliseconds of the user.
