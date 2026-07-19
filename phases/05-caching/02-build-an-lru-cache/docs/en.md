# Build an LRU Cache

> A cache with no memory limit is a memory leak with good intentions. The moment you bound it, you need a rule for what to forget — and "forget whatever I touched longest ago" is the one that best matches how programs actually behave.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why & Where to Cache](../01-why-and-where-to-cache/)
**Time:** ~75 minutes

## The Problem

The simplest cache is a map: `cache[key] = value`, check it before doing the expensive
work. It's also a trap. Memory is finite, but a map grows forever — every new key you
look up adds an entry that never leaves. Run it under real traffic and it climbs until
the process is killed by the out-of-memory reaper. An unbounded cache doesn't crash
today; it crashes at 3 a.m. under peak load.

So you cap it: *hold at most N entries.* But that cap creates a new decision. When the
cache is full and a new item arrives, **which existing item do you throw out to make
room?** That decision is the **eviction policy**, and it is the entire design of a
cache. Pick well and your hit ratio stays high with a fraction of the memory. Pick
badly and you evict the exact item you're about to need again.

In this lesson you'll build the most important eviction policy — **LRU, Least Recently
Used** — as a data structure that does every operation in **O(1)** time.

## The Concept

### The ideal we can't have

The provably optimal policy is **Bélády's algorithm**: when you must evict, remove the
item that will be needed *furthest in the future*. It's optimal — and impossible,
because it requires knowing the future. Every real policy is a cheap **guess** at
Bélády's oracle, and they differ only in what signal they use to predict future use:

| Policy | Evicts | Signal | Weakness |
|---|---|---|---|
| **FIFO** | Oldest inserted | Insertion order | Ignores how often an item is used |
| **Random** | A random entry | None | No smarts, but no pathological cases either |
| **LFU** (Least Frequently Used) | Fewest accesses | Frequency | Old-but-once-popular items get stuck; slow to adapt |
| **LRU** (Least Recently Used) | Longest since last use | Recency | A big one-time scan wipes the hot set |

**LRU wins in practice** because it leans directly on **temporal locality** (lesson 1):
what you touched most recently is what you're most likely to touch again, so what you
touched *least* recently is the safest thing to forget. It's a one-line theory of the
future that happens to match how programs really access data.

### The data-structure puzzle

To make LRU work at scale, every operation must be **O(1)** — constant time regardless
of cache size. We need three things to be fast:

1. **Look up a key** → a hash **map** gives O(1) lookup, but has no notion of order.
2. **Track recency order** → a **list** gives order, but finding an item in it is O(n).
3. **Evict the least-recently-used** → we must instantly find *and remove* the oldest.

Neither structure alone can do all three. The trick — the thing worth remembering long
after this lesson — is to **combine them**: a hash map for lookup, and a **doubly
linked list** for order, with the map's values pointing *directly at the list nodes*.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 448" width="100%" style="max-width:880px" role="img" aria-label="An LRU cache is two structures wired together. On top, a hash map called items maps each key to a node: it answers where is key K in constant time, but a hash map has no order at all. Below it, a doubly linked list holds the same nodes in recency order, running HEAD, then B, then A, then C, then TAIL. HEAD and TAIL are sentinel nodes that never hold data. The end next to HEAD is the most-recently-used end and the end next to TAIL is the least-recently-used end, so C is the oldest entry and the next one to be evicted. Dotted gray pointers run from each map entry straight down to its node in the list, and they cross, because the map's order says nothing about recency. Between every pair of neighbouring nodes there are two links: a next link pointing toward TAIL and a prev link pointing back toward HEAD. Because every node knows both of its neighbours, removing a node is a constant-time pair of pointer writes: n.prev.next = n.next and n.next.prev = n.prev.">
  <defs>
    <marker id="p5l2a-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p5l2a-pt" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two structures, one cache — a map for &#8220;where?&#8221;, a list for &#8220;how recently?&#8221;</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <text x="450" y="52" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">HASH MAP &#183; items[key] &#8594; node &#183; instant lookup, no notion of order</text>
    <rect x="46" y="62" width="808" height="90" rx="12" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.75" stroke-width="1.8"/>

    <rect x="145" y="82" width="150" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="375" y="82" width="150" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>
    <rect x="605" y="82" width="150" height="44" rx="9" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.6"/>

    <text x="178" y="110" text-anchor="middle" font-size="13" font-weight="700" fill="#7c5cff">&#8220;A&#8221;</text>
    <text x="214" y="110" text-anchor="middle" font-size="12" fill="currentColor" opacity="0.7">&#8594;</text>
    <circle cx="258" cy="105" r="4.5" fill="#7f7f7f"/>
    <text x="408" y="110" text-anchor="middle" font-size="13" font-weight="700" fill="#7c5cff">&#8220;B&#8221;</text>
    <text x="444" y="110" text-anchor="middle" font-size="12" fill="currentColor" opacity="0.7">&#8594;</text>
    <circle cx="488" cy="105" r="4.5" fill="#7f7f7f"/>
    <text x="638" y="110" text-anchor="middle" font-size="13" font-weight="700" fill="#7c5cff">&#8220;C&#8221;</text>
    <text x="674" y="110" text-anchor="middle" font-size="12" fill="currentColor" opacity="0.7">&#8594;</text>
    <circle cx="718" cy="105" r="4.5" fill="#7f7f7f"/>

    <text x="62" y="144" font-size="8" fill="currentColor" opacity="0.65">a hash map has no order</text>
    <text x="838" y="144" text-anchor="end" font-size="8" fill="currentColor" opacity="0.65">the list holds the order</text>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.5" stroke-dasharray="3 4" stroke-opacity="0.95">
      <path d="M258 112 L450 280" marker-end="url(#p5l2a-pt)"/>
      <path d="M488 112 L290 280" marker-end="url(#p5l2a-pt)"/>
      <path d="M718 112 L610 280" marker-end="url(#p5l2a-pt)"/>
    </g>

    <text x="52" y="262" font-size="11.5" font-weight="700" fill="#3553ff">DOUBLY LINKED LIST &#183; recency order</text>
    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M700 238 L728 238" marker-end="url(#p5l2a-ar)"/>
      <path d="M730 256 L702 256" marker-end="url(#p5l2a-ar)"/>
    </g>
    <text x="740" y="241" font-size="9" fill="currentColor" opacity="0.85">next</text>
    <text x="740" y="259" font-size="9" fill="currentColor" opacity="0.85">prev</text>

    <rect x="46" y="264" width="808" height="128" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.65" stroke-width="1.8"/>

    <text x="130" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">most-recently-used end</text>
    <text x="770" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">least-recently-used end</text>

    <rect x="78" y="284" width="104" height="58" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>
    <rect x="238" y="284" width="104" height="58" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="398" y="284" width="104" height="58" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="558" y="284" width="104" height="58" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="718" y="284" width="104" height="58" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>

    <text x="130" y="309" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">HEAD</text>
    <text x="290" y="310" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">B</text>
    <text x="450" y="310" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">A</text>
    <text x="610" y="310" text-anchor="middle" font-size="16" font-weight="700" fill="currentColor">C</text>
    <text x="770" y="309" text-anchor="middle" font-size="12.5" font-weight="700" fill="currentColor">TAIL</text>

    <text x="130" y="330" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>
    <text x="290" y="330" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">just used &#183; MRU</text>
    <text x="450" y="330" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">used before B</text>
    <text x="610" y="330" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">oldest &#183; evict next</text>
    <text x="770" y="330" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M184 300 L232 300" marker-end="url(#p5l2a-ar)"/>
      <path d="M344 300 L392 300" marker-end="url(#p5l2a-ar)"/>
      <path d="M504 300 L552 300" marker-end="url(#p5l2a-ar)"/>
      <path d="M664 300 L712 300" marker-end="url(#p5l2a-ar)"/>
      <path d="M232 326 L184 326" marker-end="url(#p5l2a-ar)"/>
      <path d="M392 326 L344 326" marker-end="url(#p5l2a-ar)"/>
      <path d="M552 326 L504 326" marker-end="url(#p5l2a-ar)"/>
      <path d="M712 326 L664 326" marker-end="url(#p5l2a-ar)"/>
    </g>

    <text x="450" y="372" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">unlink is O(1) because a node knows BOTH neighbours: n.prev.next = n.next &#183; n.next.prev = n.prev</text>
  </g>
  <text x="450" y="414" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The map hands you the node with no search; the list tells you the order with no scan. Neither alone can do both.</text>
  <text x="450" y="432" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">Pointers cross on purpose: where a key sits in the map says nothing about how recently it was used.</text>
</svg>
```

The list is ordered by recency: the **head** end is the most-recently-used (MRU), the
**tail** end is the least-recently-used (LRU). Now every operation is O(1):

- **Get(key):** map finds the node instantly → unlink it → move it to the head (it was
  just used). O(1) because the map handed us the node directly — no scanning the list.
- **Put(key, value):** if the cache is full, the item to evict is *right there* at the
  tail. Remove it, delete its map entry, insert the new node at the head. O(1).

Here's the eviction step in full — insert `D` into a full cache: the tail node `C` (the
least-recently-used) is unlinked and dropped from the map, and `D` goes in at the head as
the new MRU. No search, a constant number of pointer swaps:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 502" width="100%" style="max-width:880px" role="img" aria-label="One eviction, step by step. Before: the cache is full at capacity three and the list reads HEAD, B, A, C, TAIL, with sentinels at both ends. C sits at the tail, so C is the least-recently-used entry and the victim; the two links that attach C to its neighbours are drawn in red and crossed out. Then put of key D arrives and there is no room. Step one, unlink the tail: lru = tail.prev finds C with no search, _unlink rewrites two pointers so A and TAIL point at each other, and del items of C drops the map entry. Step two, push_front the newcomer: a new node for D is created, items of D is set to it, and it is spliced in right after HEAD. After: the list reads HEAD, D, B, A, TAIL, D is the new most-recently-used entry, A is now the least-recently-used one, and a get of C is a miss. Nothing was searched or scanned — the whole eviction is a fixed, constant number of pointer writes.">
  <defs>
    <marker id="p5l2b-ar" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="p5l2b-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p5l2b-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="p5l2b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Eviction in O(1) — the victim is already sitting at the tail</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="46" y="42" width="808" height="120" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.65" stroke-width="1.8"/>
    <text x="62" y="64" font-size="11.5" font-weight="700" fill="#3553ff">BEFORE &#183; full at capacity 3 &#183; HEAD = MRU, TAIL = LRU</text>
    <text x="610" y="78" text-anchor="middle" font-size="7.5" font-weight="700" fill="#d64545">tail.prev &#183; the victim</text>

    <rect x="78" y="86" width="104" height="52" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>
    <rect x="238" y="86" width="104" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="398" y="86" width="104" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="558" y="86" width="104" height="52" rx="10" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="1.9"/>
    <rect x="718" y="86" width="104" height="52" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>

    <text x="130" y="108" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">HEAD</text>
    <text x="290" y="110" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">B</text>
    <text x="450" y="110" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">A</text>
    <text x="610" y="110" text-anchor="middle" font-size="15" font-weight="700" fill="#d64545">C</text>
    <text x="770" y="108" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">TAIL</text>

    <text x="130" y="128" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>
    <text x="290" y="128" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">MRU</text>
    <text x="450" y="128" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">middle</text>
    <text x="610" y="128" text-anchor="middle" font-size="7.5" font-weight="700" fill="#d64545">LRU &#183; evict me</text>
    <text x="770" y="128" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M184 102 L232 102" marker-end="url(#p5l2b-arb)"/>
      <path d="M344 102 L392 102" marker-end="url(#p5l2b-arb)"/>
      <path d="M232 124 L184 124" marker-end="url(#p5l2b-arb)"/>
      <path d="M392 124 L344 124" marker-end="url(#p5l2b-arb)"/>
    </g>
    <g fill="none" stroke="#d64545" stroke-width="1.7">
      <path d="M504 102 L552 102" marker-end="url(#p5l2b-arr)"/>
      <path d="M664 102 L712 102" marker-end="url(#p5l2b-arr)"/>
      <path d="M552 124 L504 124" marker-end="url(#p5l2b-arr)"/>
      <path d="M712 124 L664 124" marker-end="url(#p5l2b-arr)"/>
      <path d="M525 108 L535 118"/><path d="M535 108 L525 118"/>
      <path d="M685 108 L695 118"/><path d="M695 108 L685 118"/>
    </g>
    <text x="450" y="154" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">len(items) == cap &#8594; there is no room for a fourth key</text>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M450 166 L450 194" marker-end="url(#p5l2b-ar)"/>
    </g>
    <text x="464" y="185" font-size="9.5" font-weight="700" fill="#e0930f">put(&#8220;D&#8221;, value) arrives &#8212; make room first</text>

    <rect x="46" y="200" width="392" height="88" rx="11" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-opacity="0.65" stroke-width="1.7"/>
    <text x="62" y="222" font-size="11.5" font-weight="700" fill="#d64545">&#9312; UNLINK the tail &#8594; C is evicted</text>
    <text x="62" y="242" font-size="9" fill="currentColor">lru = tail.prev</text>
    <text x="62" y="260" font-size="9" fill="currentColor">_unlink(lru)</text>
    <text x="62" y="278" font-size="9" fill="currentColor">del items[&#8220;C&#8221;]</text>
    <text x="184" y="242" font-size="9" fill="currentColor" opacity="0.7"># the LRU, found with no search</text>
    <text x="184" y="260" font-size="9" fill="currentColor" opacity="0.7"># exactly 2 pointer writes</text>
    <text x="184" y="278" font-size="9" fill="currentColor" opacity="0.7"># drop the map entry too</text>

    <rect x="462" y="200" width="392" height="88" rx="11" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.65" stroke-width="1.7"/>
    <text x="478" y="222" font-size="11.5" font-weight="700" fill="#0fa07f">&#9313; PUSH_FRONT the newcomer &#8594; D is MRU</text>
    <text x="478" y="242" font-size="9" fill="currentColor">n = Node(&#8220;D&#8221;, value)</text>
    <text x="478" y="260" font-size="9" fill="currentColor">items[&#8220;D&#8221;] = n</text>
    <text x="478" y="278" font-size="9" fill="currentColor">_push_front(n)</text>
    <text x="600" y="242" font-size="9" fill="currentColor" opacity="0.7"># a fresh node</text>
    <text x="600" y="260" font-size="9" fill="currentColor" opacity="0.7"># map entry added</text>
    <text x="600" y="278" font-size="9" fill="currentColor" opacity="0.7"># spliced in after HEAD</text>

    <g fill="none" stroke="currentColor" stroke-width="1.7">
      <path d="M450 292 L450 320" marker-end="url(#p5l2b-ar)"/>
    </g>
    <text x="464" y="311" font-size="9" fill="currentColor" opacity="0.8">a fixed number of pointer writes &#8212; nothing was scanned</text>

    <rect x="46" y="326" width="808" height="120" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.65" stroke-width="1.8"/>
    <text x="62" y="348" font-size="11.5" font-weight="700" fill="#3553ff">AFTER &#183; C is gone, D is the new MRU</text>
    <text x="290" y="362" text-anchor="middle" font-size="7" font-weight="700" fill="#0fa07f">inserted right after HEAD</text>
    <text x="690" y="362" text-anchor="middle" font-size="7" fill="currentColor" opacity="0.7">gap C left, closed</text>

    <rect x="78" y="370" width="104" height="52" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>
    <rect x="238" y="370" width="104" height="52" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.9"/>
    <rect x="398" y="370" width="104" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="558" y="370" width="104" height="52" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.7"/>
    <rect x="718" y="370" width="104" height="52" rx="10" fill="#7f7f7f" fill-opacity="0.12" stroke="#7f7f7f" stroke-width="1.7"/>

    <text x="130" y="392" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">HEAD</text>
    <text x="290" y="394" text-anchor="middle" font-size="15" font-weight="700" fill="#0fa07f">D</text>
    <text x="450" y="394" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">B</text>
    <text x="610" y="394" text-anchor="middle" font-size="15" font-weight="700" fill="currentColor">A</text>
    <text x="770" y="392" text-anchor="middle" font-size="12" font-weight="700" fill="currentColor">TAIL</text>

    <text x="130" y="412" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>
    <text x="290" y="412" text-anchor="middle" font-size="7.5" font-weight="700" fill="#0fa07f">new &#183; MRU</text>
    <text x="450" y="412" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">middle</text>
    <text x="610" y="412" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">LRU now</text>
    <text x="770" y="412" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.7">sentinel</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M184 386 L232 386" marker-end="url(#p5l2b-arg)"/>
      <path d="M344 386 L392 386" marker-end="url(#p5l2b-arg)"/>
      <path d="M232 408 L184 408" marker-end="url(#p5l2b-arg)"/>
      <path d="M392 408 L344 408" marker-end="url(#p5l2b-arg)"/>
    </g>
    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M504 386 L552 386" marker-end="url(#p5l2b-arb)"/>
      <path d="M664 386 L712 386" marker-end="url(#p5l2b-arb)"/>
      <path d="M552 408 L504 408" marker-end="url(#p5l2b-arb)"/>
      <path d="M712 408 L664 408" marker-end="url(#p5l2b-arb)"/>
    </g>
    <text x="450" y="438" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">len(items) == 3 again &#183; get(&#8220;C&#8221;) is now a miss &#183; A is the next victim</text>
  </g>
  <text x="450" y="468" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The cache never looks for a victim — the tail IS the victim, and the map turns its key back into an entry to delete.</text>
  <text x="450" y="486" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">This only works because the list is doubly linked: unlinking C needs C.prev, and only a doubly linked node knows it.</text>
</svg>
```

A doubly linked list is essential (not a singly linked one): to unlink a node in O(1)
you need its *previous* neighbor, and only a doubly linked node knows who that is.

### Sentinels: killing the edge cases

Linked-list code is famous for `if node is None` checks at the ends. We delete them all
with two **sentinel** nodes — a permanent dummy `head` and `tail` that never hold data
and never move. Every real node lives strictly between them, so it *always* has a
previous and a next neighbor. No boundary conditions, no `None` checks in the hot path.

## Build It

A complete, O(1) LRU cache in Python using a dict plus a hand-built doubly linked list
with sentinels. This is the interview-classic implementation — and it's exactly what
runs inside real caches. We use a module-level `MISS` sentinel so a genuine miss is never
confused with a stored value of `None`.

```python
# Build an LRU cache: O(1) get/put via a dict + doubly linked list.
# Ref: phases/05-caching/02-build-an-lru-cache/docs/en.md
# The dict gives O(1) lookup; the list keeps recency order so eviction is O(1).

MISS = object()  # unique sentinel: distinguishes "not cached" from a stored None

class Node:
    __slots__ = ("key", "value", "prev", "next")
    def __init__(self, key=None, value=None):
        self.key, self.value = key, value
        self.prev = self.next = None

class LRU:
    def __init__(self, capacity):
        self.cap = capacity
        self.items = {}                       # key -> Node
        self.head = Node()                    # sentinels: head.next = MRU,
        self.tail = Node()                    #            tail.prev = LRU
        self.head.next, self.tail.prev = self.tail, self.head  # empty: head <-> tail

    def _unlink(self, n):                     # remove n in O(1) — neighbors always exist
        n.prev.next = n.next
        n.next.prev = n.prev

    def _push_front(self, n):                 # insert right after head (most-recently-used)
        n.prev, n.next = self.head, self.head.next
        self.head.next.prev = n
        self.head.next = n

    def get(self, key):
        n = self.items.get(key)
        if n is None:
            return MISS                       # miss
        self._unlink(n)                       # touch:
        self._push_front(n)                   #   move to MRU end
        return n.value

    def put(self, key, value):
        n = self.items.get(key)
        if n is not None:                     # update existing + touch
            n.value = value
            self._unlink(n)
            self._push_front(n)
            return
        if len(self.items) == self.cap:       # full -> evict the LRU (tail.prev)
            lru = self.tail.prev
            self._unlink(lru)
            del self.items[lru.key]
        n = Node(key, value)
        self.items[key] = n
        self._push_front(n)

if __name__ == "__main__":
    c = LRU(2)                                # capacity 2
    c.put(1, 100)
    c.put(2, 200)
    print(c.get(1))                           # 100 — now 1 is MRU, 2 is LRU
    c.put(3, 300)                             # full -> evict 2 (least recently used)
    print(c.get(2) is MISS)                   # True — 2 was evicted
    print(c.get(3))                           # 300
```

Run it with `python main.py`. Trace the eviction: after `get(1)`, key `1` is the most
recently used, so when `put(3, ...)` needs room, key `2` is the tail — the correct
victim — and it's gone. Every step touched a constant number of pointers; nothing
scanned the list.

## Use It

Python's standard library gives you the exact structure you just built, gift-wrapped —
`collections.OrderedDict` is a dict backed by a doubly linked list in C, so `move_to_end`
and `popitem(last=False)` are the O(1) touch and O(1) evict from above:

```python
from collections import OrderedDict

class LRU:
    def __init__(self, capacity):
        self.cap = capacity
        self.data = OrderedDict()             # insertion/recency order, O(1) both ends

    def get(self, key):
        if key not in self.data:
            return None
        self.data.move_to_end(key)            # O(1) touch -> most-recently-used
        return self.data[key]

    def put(self, key, value):
        self.data[key] = value
        self.data.move_to_end(key)
        if len(self.data) > self.cap:
            self.data.popitem(last=False)     # evict the LRU end (oldest)
```

And for the most common case — memoizing an expensive pure function — you don't write a
class at all. `functools.lru_cache` *is* a hardened, C-level version of everything above:

```python
from functools import lru_cache

@lru_cache(maxsize=1024)                       # bounded LRU memoization, batteries included
def price_with_tax(sku: str) -> float:
    ...                                        # a slow lookup / computation
    return compute(sku)

price_with_tax("A-42")                         # computed once; repeats are cache hits
print(price_with_tax.cache_info())             # hits, misses, maxsize, currsize
```

Two things real caches add on top of this skeleton — and they matter more than the
skeleton itself:

**Concurrency.** Notice that even a `get` *mutates* recency (`move_to_end`). So reads are
writes: a plain LRU is **not** safe for concurrent use. `functools.lru_cache` guards each
call with a single internal lock — correct, but it means every call contends for one lock,
a scalability wall (and under the GIL a `get`-then-`move_to_end` still isn't atomic, so you
*need* that lock). The production fix is **sharding**: split the keyspace across N
independently locked segments (hash the key to pick a shard) so unrelated keys never block
each other. Libraries like `cachetools` and `cachebox` provide ready-made bounded caches
(`LRUCache`, `LFUCache`, `TTLCache`) built on this idea.

**Smarter eviction.** Pure LRU has one nasty failure mode — **scan pollution**. A single
sequential pass over cold data (an analytics job, a backfill, a crawler) touches every
cold key once, marking them all "recently used" and evicting your entire hot set. Your
hit ratio falls off a cliff for something that will never be read again. State-of-the-art
caches — **Caffeine** (Java), **Ristretto** (Go) — defend against this with
**W-TinyLFU**: a tiny, frequency-aware admission filter that refuses to admit a new item
unless it's likely to be used *more* than the victim it would evict. Recency (LRU) plus a
cheap frequency estimate (a Count-Min Sketch) beats either signal alone.

You'll meet LRU again in lesson 5 as one of Redis's `maxmemory-policy` options — where,
tellingly, Redis approximates LRU by **sampling a few random keys** rather than
maintaining an exact list, because the per-key pointer overhead you just built isn't
worth it at millions of keys.

## Key takeaways

- An **unbounded cache is a memory leak**; the moment you cap it, you need an **eviction
  policy** — that policy *is* the cache's design.
- Every policy is a cheap guess at the impossible optimum (**Bélády's** evict-furthest-in-
  future). **LRU** guesses using **recency**, leaning on temporal locality.
- Make all operations **O(1)** by combining a **hash map** (lookup) with a **doubly
  linked list** (recency order), the map pointing straight at the list nodes; **sentinel**
  head/tail nodes erase the edge cases.
- Even `Get` mutates the list, so a plain LRU isn't concurrency-safe — production caches
  **shard** behind many locks to avoid one global bottleneck.
- Pure LRU is vulnerable to **scan pollution**; frequency-aware policies (**LFU**,
  **TinyLFU / W-TinyLFU** in Caffeine and Ristretto) admit new items only when they'll
  outperform the victim.

Next: [Redis Fundamentals](../03-redis-fundamentals/) — move the cache out of your
process and onto a server the whole fleet can share.
