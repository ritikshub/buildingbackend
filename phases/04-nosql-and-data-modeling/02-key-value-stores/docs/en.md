# Key-Value Stores

> Throw away every query except one — "give me the value for this key" — and something surprising happens: the database gets radically faster, and it becomes almost trivial to spread across a thousand machines. A key-value store is a dictionary that survives restarts and scales to the moon. Its power comes entirely from what it refuses to do.

**Type:** Build
**Languages:** Python
**Prerequisites:** [When Not to Use SQL](../01-when-not-to-use-sql/), [How Data Lives on Disk: Pages, Heaps & the Buffer Pool](../../03-relational-databases/08-storage-pages-and-heaps/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/)
**Time:** ~75 minutes

## The Problem

You need to store 50 million user sessions. Each one is looked up by a single session id, read
and written constantly, and needs to come back in under a millisecond. You reach for what you
know — a relational table `sessions(id, data, expires_at)` — and it works, but you're paying for
a mountain of machinery you never use. The B-tree index supports range scans you'll never run.
The query planner weighs join strategies for a query that has no joins. Every write updates the
index, checks constraints, appends to the WAL, respects MVCC visibility. You asked for a
dictionary and got a Swiss Army knife, and you're being billed for every blade.

The **key-value store** is the database you get when you take that dictionary — the humblest data
structure in programming, `d[key] = value` — and ask a serious question: *what if this were the
entire database?* No columns to query. No joins. No schema. Just three operations: `PUT(key,
value)`, `GET(key)`, `DELETE(key)`. It sounds too simple to be a category. It is one of the most
important categories in backend engineering, because that simplicity is not a limitation you
tolerate — it's a constraint you *exploit*.

In this lesson you'll build a real, persistent key-value store from an empty file: an
append-only log plus an in-memory hash index — the same design (called **Bitcask**) that ships
inside production databases. Then you'll see the same model in Redis and DynamoDB, and understand
exactly why "just a dictionary" is a superpower at scale.

## The Concept

### The model: an opaque value behind a key

A key-value store maps a **key** (a unique identifier — a string or bytes) to a **value** (a
blob — bytes the store does not interpret). The defining word is **opaque**: to the store, the
value is a sealed envelope. It will hand you back exactly the bytes you gave it, but it will not
look inside them, cannot index a field within them, and cannot answer "find all values where
`country = 'DE'`." The *only* way in is the key.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 436" width="100%" style="max-width:880px" role="img" aria-label="The whole key-value model in one picture. On the left, a panel labelled THE ENTIRE API holds just three operations: PUT of a key and a value, which stores those bytes under that key; GET of a key, which hands back exactly those bytes; and DELETE of a key, which forgets it. There is no WHERE, no JOIN and no schema. An arrow leads from the API panel to the store panel on the right, which maps three keys — user colon 1042, session colon 9f3a and cart colon 1042 — each to one value. The keys are readable, but every value is drawn as a sealed grey block: rows of redacted bars behind a padlock, because the store never parses them. The store knows a key, a length and a run of bytes, and nothing more. A red band at the bottom spells out the consequence: a query like SELECT star FROM store WHERE value dot country equals DE is impossible, because there is no field, no type and no secondary index inside a value. The only way to a value is to already know its key.">
  <defs>
    <marker id="p4l2a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p4l2a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Three operations &#8212; and a value the store refuses to look inside</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="30" y="48" width="300" height="250" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.7" stroke-width="1.8"/>
    <text x="180" y="72" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">THE ENTIRE API</text>

    <rect x="48" y="86" width="264" height="52" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="180" y="110" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">PUT(key, value)</text>
    <text x="180" y="128" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.72">store these bytes under this key</text>

    <rect x="48" y="148" width="264" height="52" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="180" y="172" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">GET(key) &#8594; value</text>
    <text x="180" y="190" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.72">hand back exactly those bytes</text>

    <rect x="48" y="210" width="264" height="52" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="180" y="234" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">DELETE(key)</text>
    <text x="180" y="252" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.72">forget this key</text>

    <text x="180" y="282" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">no WHERE &#183; no JOIN &#183; no schema &#183; no planner</text>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M334 173 L364 173" marker-end="url(#p4l2a-ar)"/>
    </g>

    <rect x="370" y="48" width="500" height="250" rx="12" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff" stroke-opacity="0.7" stroke-width="1.8"/>
    <text x="620" y="72" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">THE STORE &#8212; key &#8594; opaque value</text>
    <text x="466" y="90" text-anchor="middle" font-size="8" font-weight="700" fill="#3553ff">KEY &#8212; the only way in</text>
    <text x="752" y="90" text-anchor="middle" font-size="8" font-weight="700" fill="#7f7f7f">VALUE &#8212; bytes, never parsed</text>

    <rect x="386" y="96" width="160" height="44" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="466" y="123" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">user:1042</text>
    <rect x="386" y="148" width="160" height="44" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="466" y="175" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">session:9f3a</text>
    <rect x="386" y="200" width="160" height="44" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.5"/>
    <text x="466" y="227" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">cart:1042</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M552 118 L666 118" marker-end="url(#p4l2a-arb)"/>
      <path d="M552 170 L666 170" marker-end="url(#p4l2a-arb)"/>
      <path d="M552 222 L666 222" marker-end="url(#p4l2a-arb)"/>
    </g>

    <rect x="672" y="96" width="160" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.5"/>
    <g fill="#7f7f7f" fill-opacity="0.6">
      <rect x="686" y="106" width="92" height="6" rx="3"/>
      <rect x="686" y="117" width="104" height="6" rx="3"/>
      <rect x="686" y="128" width="70" height="6" rx="3"/>
    </g>
    <g fill="#7f7f7f">
      <path d="M802 114 A4 4 0 0 1 810 114" fill="none" stroke="#7f7f7f" stroke-width="2"/>
      <rect x="798" y="114" width="16" height="12" rx="2"/>
    </g>

    <rect x="672" y="148" width="160" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.5"/>
    <g fill="#7f7f7f" fill-opacity="0.6">
      <rect x="686" y="158" width="104" height="6" rx="3"/>
      <rect x="686" y="169" width="78" height="6" rx="3"/>
      <rect x="686" y="180" width="96" height="6" rx="3"/>
    </g>
    <g fill="#7f7f7f">
      <path d="M802 166 A4 4 0 0 1 810 166" fill="none" stroke="#7f7f7f" stroke-width="2"/>
      <rect x="798" y="166" width="16" height="12" rx="2"/>
    </g>

    <rect x="672" y="200" width="160" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="1.5"/>
    <g fill="#7f7f7f" fill-opacity="0.6">
      <rect x="686" y="210" width="84" height="6" rx="3"/>
      <rect x="686" y="221" width="100" height="6" rx="3"/>
      <rect x="686" y="232" width="62" height="6" rx="3"/>
    </g>
    <g fill="#7f7f7f">
      <path d="M802 218 A4 4 0 0 1 810 218" fill="none" stroke="#7f7f7f" stroke-width="2"/>
      <rect x="798" y="218" width="16" height="12" rx="2"/>
    </g>

    <text x="620" y="272" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">a key, a length, and a run of bytes &#8212; that is everything the store knows</text>

    <rect x="30" y="312" width="840" height="68" rx="11" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.65" stroke-width="1.7"/>
    <text x="46" y="334" font-size="11" font-weight="700" fill="#d64545">&#10007; There is no query that reaches inside a value</text>
    <text x="46" y="352" font-size="9.5" fill="currentColor">SELECT * FROM store WHERE value.country = 'DE'   &#8212; impossible: no field, no type, no secondary index.</text>
    <text x="46" y="370" font-size="9" fill="currentColor" opacity="0.8">The only way in is the key. Need to query inside the value? Use a document store (Lesson 3) or hand-build a second key (Lesson 7).</text>
  </g>
  <text x="450" y="402" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Opaque is not an oversight &#8212; it is the whole trade: give up asking questions about the data, and get O(1) plus easy sharding.</text>
  <text x="450" y="420" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">The store will hand back byte-for-byte what you gave it. Interpreting those bytes is entirely your application's job.</text>
</svg>
```

That single restriction is the whole trade. Compare it to the relational model, feature for
feature, and you can see precisely what you gave up and what you got:

| | Relational table | Key-value store |
|---|---|---|
| Look up by primary key | Fast (`O(log n)` via B-tree) | **Fastest** (`O(1)` via hash) |
| Look up by any other field | Yes (`WHERE`, secondary indexes) | **No** — the value is opaque |
| Joins across data | Yes | **No** |
| Range scan (`age BETWEEN…`) | Yes (ordered index) | **No** (hash has no order)¹ |
| Schema / types enforced | Yes | **No** — bytes in, bytes out |
| Sharding across machines | Hard (breaks joins/transactions) | **Trivial** — hash the key → node |

<sub>¹ Pure hash-indexed stores can't range-scan. Ordered KV stores (built on B-trees or
LSM-trees — FoundationDB, RocksDB, etcd) *can* scan key ranges, trading a little lookup speed for
ordered iteration. The model has both flavors.</sub>

You lost the ability to ask questions *about* the data. In return you got the two things at the
bottom of the table, and they are enormous.

### Why the constraint buys speed

A `GET` is a hash-table lookup: hash the key, jump to the slot, return the value. That's `O(1)`
— constant time whether you hold a thousand keys or a billion. There's no tree to descend, no
planner to consult, no rows to filter. When the whole store lives in RAM (Redis), a `GET` is a
handful of memory accesses and returns in **microseconds**. This is why key-value stores are the
reflexive choice for the hottest paths in a system: caches, session lookups, rate-limiter
counters, feature flags — anything read so often that even a fast `O(log n)` B-tree lookup is too
much ceremony.

### Why the constraint buys horizontal scale

This is the deeper win, and it's the reason KV stores anchor the largest systems on earth. Recall
Pressure 4 from Lesson 1: relational databases are hard to scale *out* because joins and
transactions want all the data in one place. A key-value store has **no joins and no
cross-key transactions to protect** — so there is nothing stopping you from splitting the keyspace
across many machines. Given a key, every node in the cluster can independently compute *which node
owns it* by hashing the key. No coordinator, no lookup table.

The naïve way — `node = hash(key) % N` — works until `N` changes. Add or remove one machine and
the modulus shifts, so *almost every key* now maps to a different node and the entire dataset has
to move. **Consistent hashing** (Karger et al., 1997) fixes this: imagine the hash space as a
ring, place both nodes and keys on it, and a key belongs to the next node clockwise. Now adding a
node only steals the slice of the ring between it and its neighbor — roughly `1/N` of the keys
move, not all of them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 616" width="100%" style="max-width:880px" role="img" aria-label="Consistent hashing drawn as a real circle. The entire hash space, zero up to two to the thirty-two minus one, is bent round into a ring with degree markings at 0, 90, 180 and 270. Three nodes sit on it: Node A at 0 degrees at the top, Node B at 120 degrees at the lower right, and Node C at 240 degrees at the lower left. A key belongs to the next node clockwise from where it hashes, so each node owns the arc behind it: B owns 0 to 120 degrees, C owns 120 to 240 degrees, and A owns 240 degrees round through 360. Two example keys are placed at their hashed angles. The key user colon 1042 hashes to 95 degrees, just past the 90 degree mark, and a short green arc runs clockwise from it to Node B at 120 degrees, so B owns it. The key cart colon 77 hashes to 300 degrees, past Node C, and because there is no node anywhere between 300 and 360 degrees, an amber arc sweeps clockwise up over the 0 slash 360 seam to Node A, which owns it — the wrap-around case. A dashed green circle shows Node D being added later at 60 degrees; only the slice of ring from 0 to 60 degrees is remapped, moving from B to D, and both example keys stay exactly where they are. That is the point: the naive node equals hash of key modulo N would change the modulus and relocate almost every key, while the ring relocates roughly one over N of them.">
  <defs>
    <marker id="p4l2b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p4l2b-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
    <marker id="p4l2b-pt" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The hash ring &#8212; a key belongs to the next node clockwise</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="24" y="76" font-size="8.5" fill="currentColor" opacity="0.75">The whole hash space (0 &#8230; 2^32-1)</text>
    <text x="24" y="92" font-size="8.5" fill="currentColor" opacity="0.75">bent round into a circle.</text>
    <text x="24" y="108" font-size="8.5" fill="currentColor" opacity="0.75">Nodes and keys both live on it.</text>

    <circle cx="450" cy="300" r="170" fill="none" stroke="#7f7f7f" stroke-width="2.2" stroke-opacity="0.55"/>

    <g stroke="#7f7f7f" stroke-width="1.6" stroke-opacity="0.6">
      <path d="M450 142 L450 130"/>
      <path d="M608 300 L620 300"/>
      <path d="M450 458 L450 470"/>
      <path d="M280 300 L292 300"/>
    </g>
    <g font-size="8.5" fill="currentColor" opacity="0.7" text-anchor="middle">
      <text x="450" y="170">0&#176; / 360&#176;</text>
      <text x="590" y="296">90&#176;</text>
      <text x="450" y="438">180&#176;</text>
      <text x="312" y="304">270&#176;</text>
    </g>
    <text x="450" y="184" text-anchor="middle" font-size="7.5" font-weight="700" fill="#e0930f">the wrap point</text>

    <text x="450" y="288" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.8">a key belongs to</text>
    <text x="450" y="308" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">the NEXT NODE CLOCKWISE</text>
    <text x="450" y="328" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.7">&#8635; clockwise = increasing angle</text>

    <path d="M481.60 151.32 A152 152 0 0 1 569.78 206.42" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="5 4" stroke-opacity="0.9"/>
    <text x="502" y="212" text-anchor="middle" font-size="7.5" font-weight="700" fill="#0fa07f">0&#176;&#8211;60&#176;: B &#8594; D</text>

    <path d="M635.29 316.21 A186 186 0 0 1 622.46 369.68" fill="none" stroke="#0fa07f" stroke-width="2.2" marker-end="url(#p4l2b-arg)"/>
    <path d="M288.92 207.00 A186 186 0 0 1 417.70 116.83" fill="none" stroke="#e0930f" stroke-width="2.2" marker-end="url(#p4l2b-ara)"/>

    <circle cx="597.2" cy="215" r="22" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 4"/>
    <text x="597.2" y="214" text-anchor="middle" font-size="14" font-weight="700" fill="#0fa07f">D</text>
    <text x="597.2" y="228" text-anchor="middle" font-size="7" font-weight="700" fill="#0fa07f">new</text>

    <g fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2">
      <circle cx="450" cy="130" r="26"/>
      <circle cx="597.2" cy="385" r="26"/>
      <circle cx="302.8" cy="385" r="26"/>
    </g>
    <g text-anchor="middle" font-size="17" font-weight="700" fill="currentColor">
      <text x="450" y="137">A</text>
      <text x="597.2" y="392">B</text>
      <text x="302.8" y="392">C</text>
    </g>

    <text x="450" y="76" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor">Node A &#183; 0&#176;</text>
    <text x="450" y="90" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.75">owns 240&#176; &#8594; 360&#176;</text>
    <text x="634" y="380" font-size="10" font-weight="700" fill="currentColor">Node B &#183; 120&#176;</text>
    <text x="634" y="394" font-size="8" fill="currentColor" opacity="0.75">owns 0&#176; &#8594; 120&#176;</text>
    <text x="266" y="380" text-anchor="end" font-size="10" font-weight="700" fill="currentColor">Node C &#183; 240&#176;</text>
    <text x="266" y="394" text-anchor="end" font-size="8" fill="currentColor" opacity="0.75">owns 120&#176; &#8594; 240&#176;</text>

    <path d="M619.4 306.8 L627.4 314.8 L619.4 322.8 L611.4 314.8 Z" fill="#3553ff"/>
    <path d="M302.8 207 L310.8 215 L302.8 223 L294.8 215 Z" fill="#3553ff"/>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.4" stroke-dasharray="3 4" stroke-opacity="0.9">
      <path d="M268 213 L290 214.5" marker-end="url(#p4l2b-pt)"/>
      <path d="M668 276 L628 308" marker-end="url(#p4l2b-pt)"/>
    </g>

    <rect x="14" y="168" width="252" height="88" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.7"/>
    <text x="28" y="192" font-size="10.5" font-weight="700" fill="#3553ff">hash('cart:77') = 300&#176;</text>
    <text x="28" y="212" font-size="8.5" fill="currentColor" opacity="0.8">no node between 300&#176; and 360&#176;</text>
    <text x="28" y="230" font-size="8.5" fill="currentColor" opacity="0.8">so it wraps over the 0&#176;/360&#176; seam</text>
    <text x="28" y="249" font-size="9.5" font-weight="700" fill="#e0930f">&#8594; owned by Node A</text>

    <rect x="672" y="196" width="214" height="88" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.7" stroke-width="1.7"/>
    <text x="686" y="220" font-size="10.5" font-weight="700" fill="#3553ff">hash('user:1042') = 95&#176;</text>
    <text x="686" y="240" font-size="8.5" fill="currentColor" opacity="0.8">just past the 90&#176; mark</text>
    <text x="686" y="258" font-size="8.5" fill="currentColor" opacity="0.8">next node clockwise is 120&#176;</text>
    <text x="686" y="277" font-size="9.5" font-weight="700" fill="#0fa07f">&#8594; owned by Node B</text>

    <rect x="30" y="490" width="840" height="68" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1.7"/>
    <text x="46" y="512" font-size="11" font-weight="700" fill="#0fa07f">Why a ring instead of node = hash(key) % N ?</text>
    <text x="46" y="532" font-size="9.5" fill="currentColor">Add Node D at 60&#176; (dashed): only keys hashing into 0&#176;&#8211;60&#176; move, and they move from B to D. Both keys above stay put.</text>
    <text x="46" y="550" font-size="9.5" fill="currentColor" opacity="0.8">With % N, changing N changes the modulus &#8212; nearly every key lands on a different machine and the whole dataset moves.</text>
  </g>
  <text x="450" y="582" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Only the arc between a new node and its counter-clockwise neighbour is remapped &#8212; about 1/N of the keys, not all of them.</text>
  <text x="450" y="600" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">That is why Dynamo-lineage stores (DynamoDB, Cassandra, Riak) grow from three nodes to three hundred without downtime.</text>
</svg>
```

Add "Node D" at 60° and only the keys between 0° and 60° move — from B to D. Every other key
stays put. That property — **scale by adding nodes, with minimal reshuffling** — is why
Dynamo-lineage stores (DynamoDB, Cassandra, Riak) can grow from three nodes to three hundred
without downtime. It falls directly out of the key-value model's refusal to relate keys to each
other. (Sharding gets its full treatment in a later phase.)

### How the bytes actually persist: the log-structured hash

An in-memory dictionary forgets on restart (Phase 3, Lesson 1). To make a key-value store
*durable*, we need the data on disk — and here the KV world made a design choice that's worth
understanding deeply, because it recurs in wide-column and time-series stores later in this phase.

A relational database stores rows in fixed pages and **updates them in place** via a B-tree
(Phase 3, Lessons 8–9). In-place updates mean random disk writes, and every write maintains the
tree. The key-value insight: **don't update in place — just append.** Keep one file, the **log**,
and every `PUT` writes a new record at the end. To find a key's *current* value, keep an in-memory
hash index mapping each key to the **byte offset** of its latest record in the log.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 518" width="100%" style="max-width:880px" role="img" aria-label="The log-structured hash, or Bitcask, design. Two tiers. On top, in RAM, a hash index maps each key to the byte offset of its latest record: user colon 1 points to offset 96, and user colon 2 points to offset 40. This index is volatile and is rebuilt on startup by replaying the log. Below, on disk, sits one append-only log with the newest record at the bottom and three records in it. At offset 0, PUT user colon 1 equals Ada — drawn faded, dashed and struck through in red, with a red cross where a pointer would enter, because it is dead: superseded, and nothing points at it any more. At offset 40, PUT user colon 2 equals Alan, live. At offset 96, PUT user colon 1 equals Ada Lovelace, live, which supersedes the record at offset 0. Dashed grey pointers run down from each index entry, past the dead record, into the offsets they actually point at. The offsets only ever increase, because every write is a sequential append at the end of the file rather than an edit in place. The old Ada record is still physically on disk but is unreachable — dead bytes waiting for compaction to sweep them away. Deletes work the same way: they append a tombstone record rather than erasing anything.">
  <defs>
    <marker id="p4l2c-pt" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Never edit in place &#8212; append forward, and point an index at the newest copy</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="450" y="54" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">IN RAM &#183; hash index &#8212; key &#8594; byte offset of its LATEST record</text>
    <rect x="40" y="64" width="820" height="88" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.65" stroke-width="1.8"/>

    <rect x="150" y="82" width="210" height="44" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.6"/>
    <text x="255" y="110" text-anchor="middle" font-size="12.5" font-weight="700"><tspan fill="#3553ff">user:1</tspan><tspan fill="currentColor" opacity="0.55"> &#8594; </tspan><tspan fill="#7c5cff">off 96</tspan></text>

    <rect x="530" y="82" width="210" height="44" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-width="1.6"/>
    <text x="635" y="110" text-anchor="middle" font-size="12.5" font-weight="700"><tspan fill="#3553ff">user:2</tspan><tspan fill="currentColor" opacity="0.55"> &#8594; </tspan><tspan fill="#7c5cff">off 40</tspan></text>

    <text x="54" y="142" font-size="8.5" fill="currentColor" opacity="0.7">lost on every crash</text>
    <text x="846" y="142" text-anchor="end" font-size="8.5" fill="currentColor" opacity="0.7">rebuilt by replaying the log</text>
    <text x="846" y="212" text-anchor="end" font-size="8.5" fill="currentColor" opacity="0.7">one dict lookup gives the offset &#183; one seek gives the bytes</text>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.5" stroke-dasharray="4 4" stroke-opacity="0.95">
      <path d="M180 126 L180 168 L92 168 L92 408 L145 408" marker-end="url(#p4l2c-pt)"/>
      <path d="M560 126 L560 178 L118 178 L118 356 L145 356" marker-end="url(#p4l2c-pt)"/>
    </g>

    <text x="450" y="254" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">ON DISK &#183; one append-only log &#8212; every write appends at the end, newest at the bottom</text>
    <rect x="40" y="264" width="820" height="178" rx="12" fill="#7c5cff" fill-opacity="0.05" stroke="#7c5cff" stroke-opacity="0.65" stroke-width="1.8"/>

    <rect x="150" y="282" width="680" height="44" rx="9" fill="#d64545" fill-opacity="0.05" stroke="#d64545" stroke-opacity="0.55" stroke-width="1.6" stroke-dasharray="5 4"/>
    <rect x="164" y="292" width="64" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.16"/>
    <text x="196" y="308" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.6">off 0</text>
    <text x="248" y="309" font-size="12" fill="currentColor" opacity="0.5">PUT user:1 = {Ada}</text>
    <path d="M244 305 L382 305" stroke="#d64545" stroke-width="1.6"/>
    <text x="816" y="309" text-anchor="end" font-size="8.5" font-weight="700" fill="#d64545">DEAD &#8212; superseded, nothing points here</text>
    <g stroke="#d64545" stroke-width="2.2">
      <path d="M138 298 L150 310"/>
      <path d="M150 298 L138 310"/>
    </g>

    <rect x="150" y="334" width="680" height="44" rx="9" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-width="1.7"/>
    <rect x="164" y="344" width="64" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.16"/>
    <text x="196" y="360" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.8">off 40</text>
    <text x="248" y="361" font-size="12" fill="currentColor">PUT user:2 = {Alan}</text>
    <text x="816" y="361" text-anchor="end" font-size="8.5" font-weight="700" fill="#0fa07f">LIVE &#8212; index[user:2] points here</text>

    <rect x="150" y="386" width="680" height="44" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.9"/>
    <rect x="164" y="396" width="64" height="24" rx="6" fill="#7f7f7f" fill-opacity="0.16"/>
    <text x="196" y="412" text-anchor="middle" font-size="10" font-weight="700" fill="currentColor" opacity="0.8">off 96</text>
    <text x="248" y="413" font-size="12" fill="currentColor">PUT user:1 = {Ada Lovelace}</text>
    <text x="816" y="413" text-anchor="end" font-size="8.5" font-weight="700" fill="#0fa07f">LIVE &#8212; supersedes off 0</text>

    <text x="450" y="462" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">off 0 &#8594; 40 &#8594; 96: the offsets only ever go up. Writes are sequential appends &#8212; the fastest thing a disk can do.</text>
  </g>
  <text x="450" y="488" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The {Ada} record at off 0 is still on disk &#8212; but no index entry points at it, so nothing can ever read it again.</text>
  <text x="450" y="506" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">Dead bytes, waiting for compaction. Deletes work the same way: append a tombstone, never go back and erase.</text>
</svg>
```

This is the **Bitcask** model (Basho, 2010), and it's beautiful for four reasons:

- **Writes are sequential appends** — the fastest thing a disk can do, ~no seeking. A `PUT` is
  one append plus one dict update: `O(1)`.
- **Reads are `O(1)`** — one dict lookup for the offset, one seek+read on disk (and the OS page
  cache keeps hot values in RAM).
- **Crash recovery is trivial** — on startup, replay the log start-to-end, and the *last* record
  for each key wins. A write torn in half by a crash is detected by its checksum and ignored;
  everything before it is intact (this is the write-ahead-log idea from Phase 3, Lesson 13, taken
  to its logical extreme — the log *is* the database).
- **Deletes are just another append** — a special **tombstone** record meaning "this key is
  gone." You never go back and erase; you write forward.

The obvious cost: the log only grows. Overwrite `user:1` a thousand times and all thousand old
versions still sit on disk, dead weight. The fix is **compaction**: periodically rewrite the log
keeping only the *live* record for each key, dropping superseded versions and tombstones, then
atomically swap the new file in. Append-forward, compact-in-the-background — you'll meet this exact
pattern again as the **LSM-tree** in Lesson 4, which is this idea plus sorting.

## Build It

Let's build the whole thing: a persistent key-value store with `PUT`/`GET`/`DELETE`, crash-safe
durability, log replay on startup, and compaction. Standard library only — `struct` for the
binary record format, `zlib.crc32` for corruption detection, `os` for the file. This is a real
storage engine, not a toy; the same design runs in production.

The on-disk record format is a header followed by the key and value bytes:

```text
[ crc32 (4) | key_len (4) | val_len (4) | key bytes | value bytes ]
                                  └─ val_len == 0xFFFFFFFF means "tombstone" (a delete)
crc32 covers everything after it, so a half-written tail record is caught on recovery.
```

Here is the store. Read `put`/`get`/`delete` first (the `O(1)` core), then `_replay` (durability)
and `compact` (space reclamation):

```python
import os, struct, zlib

HEADER = struct.Struct("<III")   # crc, key_len, val_len  (all little-endian uint32)
TOMBSTONE = 0xFFFFFFFF
MISS = object()                  # distinguishes "no such key" from a stored empty value

class KVStore:
    def __init__(self, path):
        self.path = path
        self.index = {}                     # key(bytes) -> byte offset of its LATEST record
        self.f = open(path, "a+b")          # append + read; create if missing
        self._replay()                      # rebuild the index from the log on disk

    def put(self, key, value):              # append a record, point the index at it
        self.index[key] = self._append(key, value, tombstone=False)

    def delete(self, key):
        if key not in self.index:
            return False
        self._append(key, b"", tombstone=True)   # a tombstone survives restart
        del self.index[key]
        return True

    def get(self, key):                     # O(1): one dict lookup + one seek
        offset = self.index.get(key)
        if offset is None:
            return MISS
        return self._read_at(offset)[1]

    def _append(self, key, value, tombstone):
        val_len = TOMBSTONE if tombstone else len(value)
        body = HEADER.pack(0, len(key), val_len)[4:] + key + (b"" if tombstone else value)
        crc = zlib.crc32(body) & 0xFFFFFFFF
        self.f.seek(0, os.SEEK_END)
        offset = self.f.tell()
        self.f.write(struct.pack("<I", crc) + body)
        self.f.flush(); os.fsync(self.f.fileno())   # force to disk: a crash now keeps the write
        return offset

    def _read_at(self, offset):
        self.f.seek(offset)
        header = self.f.read(HEADER.size)
        crc, key_len, val_len = HEADER.unpack(header)
        tomb = val_len == TOMBSTONE
        payload = self.f.read(key_len + (0 if tomb else val_len))
        if zlib.crc32(header[4:] + payload) & 0xFFFFFFFF != crc:
            raise ValueError(f"corrupt record at {offset}")
        return payload[:key_len], (None if tomb else payload[key_len:])

    def _replay(self):                      # last write wins; a tombstone removes the key
        self.f.seek(0); offset = 0
        while True:
            header = self.f.read(HEADER.size)
            if len(header) < HEADER.size:
                break
            crc, key_len, val_len = HEADER.unpack(header)
            tomb = val_len == TOMBSTONE
            n = 0 if tomb else val_len
            payload = self.f.read(key_len + n)
            if len(payload) < key_len + n:  # truncated tail from a crash mid-write -> stop
                break
            key = payload[:key_len]
            self.index.pop(key, None) if tomb else self.index.__setitem__(key, offset)
            offset += HEADER.size + key_len + n
```

And compaction — rewrite only the live records into a fresh file, then swap it in atomically:

```python
    def compact(self):
        live = {k: self._read_at(off)[1] for k, off in self.index.items()}
        tmp = self.path + ".compact"
        with open(tmp, "wb") as out:
            new_index = {}
            for key, value in live.items():
                body = HEADER.pack(0, len(key), len(value))[4:] + key + value
                crc = zlib.crc32(body) & 0xFFFFFFFF
                new_index[key] = out.tell()
                out.write(struct.pack("<I", crc) + body)
            out.flush(); os.fsync(out.fileno())
        self.f.close()
        os.replace(tmp, self.path)          # atomic: readers see old-or-new file, never half
        self.f = open(self.path, "a+b")
        self.index = new_index
```

Running `python kvstore.py` exercises the whole lifecycle — put, overwrite, delete, then *reopen
the store* to prove the data survived, then compact:

```console
$ python kvstore.py
== PUT / GET / DELETE ==
get user:1 -> {"name":"Ada"}
miss  user:9 -> True
after overwrite user:1 -> {"name":"Ada Lovelace"}
after delete session:xyz is MISS -> True
live keys: ['user:1', 'user:2']

== DURABILITY: reopen and replay the log ==
user:1 survived restart -> {"name":"Ada Lovelace"}
session:xyz still deleted -> True

== COMPACTION: reclaim superseded + tombstoned bytes ==
log size: 158 bytes -> 74 bytes  (reclaimed 84)
data intact after compaction -> {"name":"Ada Lovelace"}
```

Trace what just happened. The overwrite of `user:1` appended a *second* record without erasing
the first — that's why the log was 158 bytes with only two live keys. Reopening rebuilt the entire
index from disk with zero application involvement: the log *is* the source of truth. Compaction
then dropped the superseded `user:1` version and the `session:xyz` tombstone, halving the file.
Every operation was `O(1)`; nothing scanned. You've built the core of a production storage engine
in ~60 lines.

## Use It

You almost never write your own storage engine — you use one. The two you'll meet most are Redis
(in-memory, single-node, feature-rich) and DynamoDB (on-disk, distributed, managed). The Build-It
above is exactly what they do under the hood, so their APIs will feel familiar.

**Redis** is a key-value store that keeps everything in RAM (persisting to disk in the background,
much like our log), which is why it answers in microseconds. Its `SET`/`GET`/`DEL` are the
`PUT`/`GET`/`DELETE` you just built:

```python
import redis  # pip install redis; the sandbox's REDIS_URL points at the bundled server

r = redis.Redis.from_url("redis://localhost:6379/0")
r.set("session:9f3a", '{"user_id": 1042}')          # PUT
print(r.get("session:9f3a"))                          # GET  -> b'{"user_id": 1042}'
r.set("session:9f3a", "...", ex=3600)                 # with a 3600s TTL — auto-expire (Phase 5)
r.delete("session:9f3a")                              # DELETE

r.incr("ratelimit:ip:8.8.8.8")                        # atomic counter — a KV superpower
```

That last line hints at why Redis is more than a dictionary: because a single node owns each key,
it can offer **atomic** operations on values — `INCR`, `APPEND`, list pushes, set adds — without
the distributed-transaction problem. It also ships **typed values** (lists, hashes, sorted sets),
which is why people call it a "data structure server." You'll go deep on Redis in Phase 5.

**DynamoDB** (and Cassandra) is the other end: the value stays opaque, but the store is
**distributed by a partition key** using exactly the consistent-hashing idea above, so it scales
horizontally and stays available under partition (an AP choice from Lesson 1). The trade shows up
in the API — you must supply the partition key on every read, because that key is *how the cluster
finds which node holds your data*:

```python
# Conceptual DynamoDB access (boto3). The 'Key' is the partition key — the only way in.
table.put_item(Item={"pk": "user:1042", "profile": "...", "tier": "gold"})
table.get_item(Key={"pk": "user:1042"})               # O(1), routed to the owning node by hash
# There is deliberately no "scan all users where tier == gold" that's cheap —
# that would defeat the model. You'd add a secondary index or a different table (Lesson 7).
```

Three hard-won lessons that separate people who *use* KV stores from people who get burned by
them:

- **The value is opaque — model for it.** If you'll never need to query inside the value, a KV
  store is perfect. The moment you catch yourself wishing for "find all values where…", you've
  outgrown pure KV: you want a document store (Lesson 3, queryable values) or you must maintain a
  second key that acts as an index (Lesson 7, "data modeling by access pattern" — this is the
  whole discipline).
- **Choose your durability knob consciously.** In-memory stores trade durability for speed. Redis
  can lose the last fraction of a second of writes depending on its persistence config — fine for
  a cache, a real decision for a source of truth. Our Build-It `fsync`s every write (maximally
  durable, slower); production stores let you dial this.
- **Watch the value size.** KV stores assume small-ish values. Stuffing a 10 MB blob under one key
  makes that key a hot, expensive object to move and cache. Big blobs belong in object storage
  (S3); keep the *pointer* to them in the KV store.

## Key takeaways

- A **key-value store** is a durable, scalable dictionary with three operations — `PUT`, `GET`,
  `DELETE` — where the value is **opaque** (bytes the store won't look inside). You can only reach
  data by its key.
- That one constraint buys two huge things: **`O(1)` lookups** (a hash, not a tree — microseconds
  in RAM) and **trivial horizontal scaling** (no joins or cross-key transactions to protect, so
  the keyspace shards across machines via **consistent hashing**, which moves only ~`1/N` of keys
  when the cluster grows).
- The classic on-disk design is the **log-structured hash** (Bitcask): every write is an **append**
  to one log, an in-memory index maps key → latest byte offset, deletes are **tombstones**, and
  **compaction** reclaims superseded records. Sequential writes, `O(1)` reads, trivial crash
  recovery by replaying the log.
- **Redis** is the in-memory, single-node, feature-rich KV store (microsecond `GET`s, atomic
  counters, typed values); **DynamoDB/Cassandra** are the distributed, partition-key-routed stores
  that scale out and stay available. Both are the Build-It, hardened.
- Use KV when you look data up by one key and never query inside the value. When you start wishing
  you could query the value, you've outgrown it — reach for a **document** store (next) or design a
  second key by hand (Lesson 7). Keep values small; put big blobs in object storage.

Next: [Document Databases](../03-document-databases/) — keep the flexibility and scale of a
key-value store, but make the value a *queryable* JSON document, so you can finally ask questions
about what's inside.
