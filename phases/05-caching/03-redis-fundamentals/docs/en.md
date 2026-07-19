# Redis Fundamentals

> An in-process cache dies when your process dies and disagrees with every other instance. Redis is the same idea — a hash map — moved onto its own server so the whole fleet shares one copy. Under the hood it's simpler than its reputation: a big dictionary, a tiny wire protocol, and one thread.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Build an LRU Cache](../02-build-an-lru-cache/), [HTTP Server from a TCP Socket](../../01-networking-and-protocols/09-http-server-from-tcp/)
**Time:** ~75 minutes

## The Problem

The in-process cache from lesson 2 is the fastest cache there is — a map in your own
RAM, no network hop. But run 10 copies of your service behind a load balancer and three
cracks appear:

- **Inconsistency.** Each instance has its *own* map. Update a value on instance 3 and
  instances 1, 2, 4…10 keep serving the old one. Users get different answers depending
  on which server the load balancer picked.
- **Cold on restart.** Deploy a new version and every instance starts with an empty
  cache. All that traffic slams the database at once until the caches refill — a
  self-inflicted stampede on every deploy.
- **Capped size.** The cache can never exceed one machine's RAM, and you're duplicating
  the same hot entries in all 10 processes.

The fix is to pull the cache *out* of every process and put it on **one shared server**
they all talk to over the network. One copy, survives restarts, sized independently.
That server is **Redis** (REmote DIctionary Server), and this lesson shows you exactly
what it is by building a miniature version of it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 392" width="100%" style="max-width:880px" role="img" aria-label="Two ways to cache across a fleet of three application instances. On the left, the broken before picture: each of the three instances keeps its own in-process map in its own RAM, and they disagree about the same key x. App 1 holds x equals 1, which is stale; App 2 was just updated and holds x equals 2; App 3 holds x equals 1, also stale. Which value a user sees depends on which instance the load balancer picked. On the right, the fixed after picture: the same three instances keep no local map at all and instead read and write one shared Redis server over the network, which holds a single dictionary containing x equals 2. One copy means every instance agrees, the cache survives a process restart, it is sized on its own machine, and hot entries are not duplicated in ten processes.">
  <defs>
    <marker id="p5l3a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three private caches drift apart — one shared cache is one answer</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="424" height="286" rx="12" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.8"/>
    <rect x="460" y="42" width="424" height="286" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="228" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">BEFORE — a private cache per process</text>
    <text x="228" y="88" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">3 instances behind one load balancer</text>
    <text x="672" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">AFTER — one shared cache server</text>
    <text x="672" y="88" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the same 3 instances, one copy of x</text>

    <g fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.5">
      <rect x="78" y="102" width="300" height="46" rx="9"/>
      <rect x="78" y="158" width="300" height="46" rx="9"/>
      <rect x="78" y="214" width="300" height="46" rx="9"/>
    </g>
    <text x="94" y="124" font-size="11" font-weight="700" fill="#3553ff">App 1</text>
    <text x="94" y="139" font-size="8.5" fill="currentColor" opacity="0.7">own map in its own RAM</text>
    <text x="362" y="124" text-anchor="end" font-size="12" font-weight="700" fill="#d64545">x = 1</text>
    <text x="362" y="139" text-anchor="end" font-size="8" fill="#d64545" opacity="0.85">stale</text>

    <text x="94" y="180" font-size="11" font-weight="700" fill="#3553ff">App 2</text>
    <text x="94" y="195" font-size="8.5" fill="currentColor" opacity="0.7">own map in its own RAM</text>
    <text x="362" y="180" text-anchor="end" font-size="12" font-weight="700" fill="#0fa07f">x = 2</text>
    <text x="362" y="195" text-anchor="end" font-size="8" fill="#0fa07f" opacity="0.85">written here</text>

    <text x="94" y="236" font-size="11" font-weight="700" fill="#3553ff">App 3</text>
    <text x="94" y="251" font-size="8.5" fill="currentColor" opacity="0.7">own map in its own RAM</text>
    <text x="362" y="236" text-anchor="end" font-size="12" font-weight="700" fill="#d64545">x = 1</text>
    <text x="362" y="251" text-anchor="end" font-size="8" fill="#d64545" opacity="0.85">stale</text>

    <text x="228" y="284" text-anchor="middle" font-size="10" font-weight="700" fill="#d64545">Same key, three answers.</text>
    <text x="228" y="302" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Which one you get depends on which</text>
    <text x="228" y="316" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">instance the load balancer picked.</text>

    <g fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.5">
      <rect x="478" y="102" width="142" height="44" rx="9"/>
      <rect x="478" y="160" width="142" height="44" rx="9"/>
      <rect x="478" y="218" width="142" height="44" rx="9"/>
    </g>
    <text x="549" y="122" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">App 1</text>
    <text x="549" y="137" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">no local map</text>
    <text x="549" y="180" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">App 2</text>
    <text x="549" y="195" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">no local map</text>
    <text x="549" y="238" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">App 3</text>
    <text x="549" y="253" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">no local map</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.6">
      <path d="M624 124 L668 150" marker-end="url(#p5l3a-arg)"/>
      <path d="M624 182 L668 176" marker-end="url(#p5l3a-arg)"/>
      <path d="M624 240 L668 200" marker-end="url(#p5l3a-arg)"/>
    </g>

    <path d="M676 124 L676 214 A93 14 0 0 0 862 214 L862 124 Z" fill="#7c5cff" fill-opacity="0.09" stroke="#7c5cff" stroke-width="1.8"/>
    <ellipse cx="769" cy="124" rx="93" ry="14" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="769" y="160" text-anchor="middle" font-size="13" font-weight="700" fill="#7c5cff">Redis</text>
    <text x="769" y="183" text-anchor="middle" font-size="13" font-weight="700" fill="#0fa07f">{ x: 2 }</text>
    <text x="769" y="204" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">one dictionary, on its own box</text>
    <text x="769" y="252" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">every instance reads and writes THIS</text>

    <text x="672" y="284" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">One copy. Everyone agrees.</text>
    <text x="672" y="302" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Survives a deploy, sized on its own box,</text>
    <text x="672" y="316" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">no hot entry duplicated 10 times.</text>
  </g>
  <text x="450" y="352" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">An in-process map is the fastest cache there is — but it is one cache per process, so 10 instances means 10 caches that drift.</text>
  <text x="450" y="372" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Redis is that same hash map moved onto its own server, so the whole fleet shares one copy for the price of one network hop.</text>
</svg>
```

## The Concept

### Redis is a data-structure server

Memcached, the older shared cache, maps a key to an opaque blob of bytes. Redis's leap
was to make the *value* a **rich data structure** the server understands and can mutate
in place — so you push the operation to the data instead of pulling the whole value
across the network to change one field.

| Type | Holds | Signature commands | Classic use |
|---|---|---|---|
| **String** | Bytes / number | `SET` `GET` `INCR` `SETEX` | Cached JSON, counters, flags |
| **Hash** | Field → value map | `HSET` `HGET` `HGETALL` | An object without re-serializing the whole thing |
| **List** | Ordered sequence | `LPUSH` `RPOP` `LRANGE` | Queues, recent-activity feeds |
| **Set** | Unique members | `SADD` `SISMEMBER` `SINTER` | Tags, unique visitors, relationships |
| **Sorted set** | Members ranked by score | `ZADD` `ZRANGE` `ZRANK` | Leaderboards, rate-limit windows, priority queues |
| **Stream** | Append-only log | `XADD` `XREAD` | Event logs, message queues (Phase 6) |

Because the server knows the type, `INCR page:views` is one atomic round trip, not a
read-modify-write race. That's the difference between a cache and a data-structure
server.

### Why Redis is fast — and single-threaded

Three design choices, and one surprising one:

1. **Everything is in RAM.** No disk on the read path. That alone buys the ~100 ns vs.
   ~10 ms gap from lesson 1.
2. **The right data structures.** Hash lookups are O(1); sorted sets are a skip list +
   hash giving O(log n) ranked queries.
3. **A single thread runs all commands.** This sounds like a bottleneck and is actually
   a superpower: with one thread, **each command runs to completion before the next
   begins**, so *every command is atomic for free* — no locks, no mutexes, no race
   conditions, no lock-contention tax. Modern Redis uses extra threads for network I/O
   and background saves, but command *execution* is still one serialized stream.

The flip side is the single most important operational rule about Redis: **a slow
command blocks every other client.** `KEYS *` on a million-key database, a huge `SORT`,
a giant `SMEMBERS` — each stalls the one thread while it runs, and every other request
queues behind it. Redis is fast *because* it's simple and single-threaded; you keep it
fast by never handing that one thread an O(n) command in production.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 400" width="100%" style="max-width:880px" role="img" aria-label="How Redis executes commands. Three clients send commands concurrently: Client 1 sends SET x 1, Client 2 sends INCR n, Client 3 sends GET x. Their commands arrive interleaved into a single command queue, so the queue holds a mixed sequence such as C1 SET x 1, C3 GET x, C2 INCR n, C1 GET x, C3 GET x. One single thread drains that queue strictly in order: it takes exactly one command, runs it to completion, and only then takes the next. Because nothing else can run in between, every command is atomic for free, with no locks or mutexes. The thread reads and writes the in-memory data structures — strings, hashes, lists, sets, sorted sets and streams — mutating them in place, and replies travel back to the clients one at a time in the exact order the thread finished them. The flip side is that one slow order-n command, such as KEYS star, a huge SORT or a giant SMEMBERS, holds the single thread while every other client waits behind it.">
  <defs>
    <marker id="p5l3b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l3b-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p5l3b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p5l3b-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One thread, one command at a time — that is why every command is atomic</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="85" y="58" text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">CONCURRENT CLIENTS</text>
    <g fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.6">
      <rect x="20" y="76" width="130" height="44" rx="9"/>
      <rect x="20" y="140" width="130" height="44" rx="9"/>
      <rect x="20" y="204" width="130" height="44" rx="9"/>
    </g>
    <text x="85" y="96" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">Client 1</text>
    <text x="85" y="111" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">SET x 1</text>
    <text x="85" y="160" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">Client 2</text>
    <text x="85" y="175" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">INCR n</text>
    <text x="85" y="224" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">Client 3</text>
    <text x="85" y="239" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">GET x</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M154 98 L186 120" marker-end="url(#p5l3b-arb)"/>
      <path d="M154 162 L186 158" marker-end="url(#p5l3b-arb)"/>
      <path d="M154 226 L186 196" marker-end="url(#p5l3b-arb)"/>
    </g>

    <rect x="190" y="64" width="156" height="204" rx="10" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.5"/>
    <text x="268" y="84" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">Command queue</text>
    <text x="268" y="97" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7">commands arrive interleaved</text>
    <g fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.5" stroke-width="1.2">
      <rect x="202" y="104" width="132" height="22" rx="5"/>
      <rect x="202" y="130" width="132" height="22" rx="5"/>
      <rect x="202" y="156" width="132" height="22" rx="5"/>
      <rect x="202" y="182" width="132" height="22" rx="5"/>
      <rect x="202" y="208" width="132" height="22" rx="5"/>
    </g>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="268" y="119">C1 · SET x 1</text>
      <text x="268" y="145">C3 · GET x</text>
      <text x="268" y="171">C2 · INCR n</text>
      <text x="268" y="197">C1 · GET x</text>
      <text x="268" y="223">C3 · GET x</text>
    </g>
    <text x="268" y="246" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">arrivals interleave —</text>
    <text x="268" y="258" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">drained strictly in order</text>

    <g fill="none" stroke="currentColor" stroke-width="1.6">
      <path d="M350 172 L416 172" marker-end="url(#p5l3b-ar)"/>
    </g>
    <text x="383" y="164" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">pops 1</text>

    <rect x="420" y="96" width="170" height="152" rx="11" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-width="2"/>
    <text x="505" y="122" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">THE SINGLE THREAD</text>
    <text x="505" y="146" text-anchor="middle" font-size="9" fill="currentColor">takes ONE command</text>
    <text x="505" y="162" text-anchor="middle" font-size="9" fill="currentColor">runs it to completion</text>
    <text x="505" y="178" text-anchor="middle" font-size="9" fill="currentColor">then takes the next</text>
    <path d="M436 192 L574 192" fill="none" stroke="#0fa07f" stroke-opacity="0.35" stroke-width="1.2"/>
    <text x="505" y="212" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">no locks, no mutexes</text>
    <text x="505" y="230" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">every command is ATOMIC</text>

    <g fill="none" stroke="#7c5cff" stroke-width="1.6">
      <path d="M594 172 L646 172" marker-end="url(#p5l3b-arp)"/>
    </g>
    <text x="620" y="164" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.8">mutates</text>

    <rect x="650" y="96" width="228" height="152" rx="11" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="764" y="120" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">In-memory data structures</text>
    <g fill="#7c5cff" fill-opacity="0.1" stroke="#7c5cff" stroke-opacity="0.6" stroke-width="1.2">
      <rect x="664" y="134" width="100" height="26" rx="6"/>
      <rect x="770" y="134" width="100" height="26" rx="6"/>
      <rect x="664" y="166" width="100" height="26" rx="6"/>
      <rect x="770" y="166" width="100" height="26" rx="6"/>
      <rect x="664" y="198" width="100" height="26" rx="6"/>
      <rect x="770" y="198" width="100" height="26" rx="6"/>
    </g>
    <g text-anchor="middle" font-size="9" fill="currentColor">
      <text x="714" y="151">strings</text>
      <text x="820" y="151">hashes</text>
      <text x="714" y="183">lists</text>
      <text x="820" y="183">sets</text>
      <text x="714" y="215">sorted sets</text>
      <text x="820" y="215">streams</text>
    </g>
    <text x="764" y="240" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">mutated in place, on the server</text>

    <path d="M505 252 L505 306 L85 306 L85 252" fill="none" stroke="#0fa07f" stroke-width="1.6" marker-end="url(#p5l3b-arg)"/>
    <text x="282" y="298" text-anchor="middle" font-size="9" fill="#0fa07f">replies go back one at a time, in the order the thread finished them</text>

    <rect x="20" y="326" width="858" height="38" rx="10" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.5"/>
    <text x="449" y="343" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">The flip side: one slow O(n) command holds the thread — KEYS *, a huge SORT, a giant SMEMBERS</text>
    <text x="449" y="357" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">and every other client queues behind it. Atomicity is free; head-of-line blocking is the price.</text>
  </g>
  <text x="450" y="384" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.8">Concurrency happens in the queue; execution never does — that serialization is the whole trick.</text>
</svg>
```

Every client's commands funnel into one queue and one thread drains it strictly in order
— which is *why* each command is atomic and *why* a single O(n) command makes everyone
else wait.

### The wire protocol: RESP

Clients and Redis speak **RESP** (REdis Serialization Protocol) — a deliberately dumb,
line-based, human-readable format over TCP. That simplicity is why Redis clients exist
for every language and why you can drive Redis with `telnet`. A command is an **array of
bulk strings**; the reply is type-prefixed by its first byte:

```text
Client sends  SET user:42 Ada  as:
*3\r\n              ← array of 3 elements
$3\r\nSET\r\n       ← bulk string, length 3, "SET"
$7\r\nuser:42\r\n   ← bulk string, length 7
$3\r\nAda\r\n       ← bulk string, length 3

Server replies:  +OK\r\n
```

The first byte names the type: `+` simple string, `-` error, `:` integer, `$` bulk
string (with a byte length, so binary-safe), `*` array. A `$-1\r\n` is the **null bulk
string** — Redis's way of saying "no such key" on a `GET` miss. Learn these five
prefixes and you can read any Redis exchange on the wire.

### Persistence: a cache that can remember

Redis is in-memory, but it can survive a restart via two mechanisms — worth knowing even
when you use Redis purely as a cache:

- **RDB** — periodic **point-in-time snapshots** of the whole dataset to a compact file.
  Fast restart, tiny files, but you lose everything written since the last snapshot.
- **AOF** (Append-Only File) — logs **every write command** as it happens; on restart
  Redis replays the log. Far more durable (down to one second of loss), larger files,
  slower restart.

For a pure cache you often disable both — the source of truth is your database, so a
cold restart just means a few misses. For Redis-as-datastore you enable AOF. The point:
persistence is a *dial*, not a fixed property.

## Build It

Let's make Redis concrete by building a miniature server that speaks real RESP over a
raw TCP socket and implements `PING`, `SET`, `GET`, and `DEL` against a Python dict —
Python stdlib only. If you understand this, you understand what Redis *is*.

```python
# A tiny Redis-compatible server: RESP over a TCP socket, backed by a dict.
# Ref: phases/05-caching/03-redis-fundamentals/docs/en.md
# RESP spec: https://redis.io/docs/latest/develop/reference/protocol-spec/
# Demonstrates the wire format and the "big dictionary" at Redis's core.
from __future__ import annotations  # lazy annotations -> `bytes | None` works on 3.9 too

import socket
import threading

store: dict[bytes, bytes] = {}  # the entire "database" — one dict

def parse_command(f):
    """Read one RESP array of bulk strings: *N, then N × ($len, data)."""
    line = f.readline()
    if not line:
        return None                      # client closed the connection
    if line[:1] != b"*":
        return None
    argc = int(line[1:].strip())
    args = []
    for _ in range(argc):
        header = f.readline()            # $<length>\r\n
        length = int(header[1:].strip())
        data = f.read(length)            # exactly <length> bytes (binary-safe)
        f.read(2)                        # discard the trailing \r\n
        args.append(data)
    return args

def bulk(value: bytes | None) -> bytes:
    """Encode a RESP bulk string, or the null bulk string for a miss."""
    if value is None:
        return b"$-1\r\n"
    return b"$" + str(len(value)).encode() + b"\r\n" + value + b"\r\n"

def handle(conn):
    f = conn.makefile("rb")
    while (args := parse_command(f)) is not None:
        cmd = args[0].upper()
        if cmd == b"PING":
            conn.sendall(b"+PONG\r\n")
        elif cmd == b"SET":
            store[args[1]] = args[2]
            conn.sendall(b"+OK\r\n")
        elif cmd == b"GET":
            conn.sendall(bulk(store.get(args[1])))
        elif cmd == b"DEL":
            existed = 1 if store.pop(args[1], None) is not None else 0
            conn.sendall(b":" + str(existed).encode() + b"\r\n")   # RESP integer
        else:
            conn.sendall(b"-ERR unknown command\r\n")
    conn.close()

def encode(*parts) -> bytes:
    """Client-side: turn SET user:42 Ada into a RESP array of bulk strings."""
    out = b"*" + str(len(parts)).encode() + b"\r\n"
    for p in parts:
        b = p.encode() if isinstance(p, str) else p
        out += b"$" + str(len(b)).encode() + b"\r\n" + b + b"\r\n"
    return out

def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))           # ephemeral port — self-contained demo
    srv.listen()
    host, port = srv.getsockname()
    threading.Thread(target=lambda: handle(srv.accept()[0]), daemon=True).start()

    c = socket.create_connection((host, port))
    for cmd in [encode("PING"),
                encode("SET", "user:42", "Ada"),
                encode("GET", "user:42"),
                encode("GET", "nope"),      # miss → null bulk string
                encode("DEL", "user:42"),
                encode("GET", "user:42")]:  # gone → null bulk string
        c.sendall(cmd)
        print(cmd.split(b"\r\n")[2].decode(), "→", c.recv(64))
    c.close()
    srv.close()

if __name__ == "__main__":
    main()
```

Run `python main.py` and you'll watch RESP go by:

```console
PING → b'+PONG\r\n'
SET → b'+OK\r\n'
GET → b'$3\r\nAda\r\n'
GET → b'$-1\r\n'
DEL → b':1\r\n'
GET → b'$-1\r\n'
```

That `$-1\r\n` after the `DEL` is a cache miss on the wire. There is no magic here: a
dict, a socket, and a five-symbol protocol. Real Redis adds hundreds of commands, the
rich data types, replication, and persistence — but the spine is exactly what you just
wrote.

## Use It

In production you talk to a real Redis server through a client library — for Python,
`redis`. The connection is cheap to reason about; the value is in the commands:

```python
import os
import redis

# Fail fast if the cache isn't configured — never silently run without it.
r = redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379"),
                   decode_responses=True)

# Strings + TTL: the bread-and-butter cache entry that expires itself.
r.set("user:42", '{"name":"Ada"}', ex=60)   # EX = expire in 60 seconds
r.get("user:42")                             # -> the JSON string
r.ttl("user:42")                             # -> seconds left before it vanishes

# Atomic counter — no read-modify-write race, because the server is single-threaded.
r.incr("page:42:views")                      # returns the new count

# Hash: update one field without re-serializing the whole object.
r.hset("session:abc", mapping={"user": "42", "csrf": "xyz"})
r.hget("session:abc", "user")                # -> "42"

# Sorted set: a live leaderboard, ranked by score, in O(log n).
r.zadd("leaderboard", {"ada": 100, "grace": 250})
r.zrevrange("leaderboard", 0, 2, withscores=True)   # top 3, highest first

# Batch reads in one round trip — amortize the network hop across many keys.
r.mget("user:42", "user:43", "user:44")
```

Two habits that separate a cache that helps from one that hurts:

- **Every cache key should have a TTL.** Use `SET key val EX seconds` (or `SETEX`), not a
  bare `SET`. A cache without expiry slowly fills with keys nobody reads until it hits
  its memory limit and starts evicting your *hot* data to make room for cold. TTLs are
  lesson 5.
- **Never run O(n) commands on the hot path.** `KEYS *` scans the entire keyspace and
  blocks the single thread; use `SCAN` (cursor-based, incremental) instead. Watch for
  "big keys" — a hash or list with millions of members turns an innocent `HGETALL` into a
  server-wide stall.

You now have a shared cache the whole fleet reads and writes consistently. The next
question is *how* your application should coordinate that cache with the database — read
first? write first? — which is the subject of lesson 4.

## Key takeaways

- An in-process cache is fastest but **per-instance, cold on restart, and RAM-capped**;
  a shared **Redis** server gives one consistent copy the whole fleet uses.
- Redis is a **data-structure server** — strings, hashes, lists, sets, sorted sets,
  streams — so operations like `INCR` and `ZADD` run *on the server*, atomically.
- It's fast because it's **in-memory** with the right data structures and a **single
  command thread** — which makes every command atomic for free, but means **one slow
  command blocks everyone**.
- Clients speak **RESP**, a five-prefix, line-based protocol (`+ - : $ *`); a `$-1\r\n`
  null bulk string is a miss on the wire.
- **Persistence is a dial** — RDB snapshots vs. AOF write-logging; give every cache key a
  **TTL** and keep O(n) commands off the hot path.

Next: [Cache Strategies: Aside, Through, Behind](../04-cache-strategies/) — the patterns
that decide how your app keeps the cache and the database in agreement.
