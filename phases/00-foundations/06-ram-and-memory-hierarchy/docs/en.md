# RAM & the Memory Hierarchy

> Registers hold a handful of numbers. Your program needs millions. RAM is where they live — fast, forgetful, and surprisingly expensive. And it's just one rung on a ladder that explains most performance mysteries.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The CPU](../05-the-cpu/)
**Time:** ~50 minutes

## The Problem

The CPU has only a handful of registers, but a running program juggles millions of
values. Where do they all live while the program runs? Why does that memory vanish when
the power drops — and why does 32 GB of RAM cost more than a 1 TB disk that holds thirty
times as much? The answers reveal the **memory hierarchy**, the single idea behind most
backend performance work.

## The Concept

### What RAM is

**RAM** — Random Access Memory — is the computer's **working memory**: it holds the
instructions and data of whatever is *currently running*. "Random access" means you can
read *any* location equally quickly (unlike a tape you'd have to scan through). When the
CPU needs a value that isn't in a register, it fetches it from RAM.

### What RAM is made of, and why it forgets

The common type, **DRAM**, stores each bit as a tiny electrical **charge in a capacitor**,
guarded by one **transistor** (lesson 3). Two consequences fall straight out of that:

- The charge **leaks away**, so DRAM must be constantly **refreshed** (recharged many times a
  second) to hold its values — that's the "dynamic" in DRAM.
- When the **power is cut**, the charges vanish and everything is lost. That's why RAM is
  **volatile** (lesson 9's "save your work" in hardware terms).

### Why RAM costs more per gigabyte than disk

RAM buys **speed** at the expense of **capacity and persistence**: it needs constant power,
constant refreshing, and fast precise circuitry, all of which cost money and space. Disks —
**SSD** (solid-state drive) and **HDD** (hard disk drive) — store bits far more densely and
keep them without power, but they're much slower.
So you get a trade: a little fast expensive memory (RAM) and a lot of slow cheap storage
(disk) — never both at once.

### The memory hierarchy: a speed-vs-size pyramid

That trade repeats at every level, forming a pyramid. Each step down is bigger and cheaper
per byte, but dramatically slower:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 426" width="100%" style="max-width:880px" role="img" aria-label="The memory hierarchy drawn to scale on a logarithmic latency axis, where every column to the right is ten times slower than the one before it. Five rungs are drawn as horizontal bars growing from a shared origin at one nanosecond. Registers, about 1 nanosecond, are only a stub at the origin; they hold hundreds of bytes and cost the most per byte. CPU cache, about 1 to 10 nanoseconds, is one decade long; it holds kilobytes to megabytes at a very high cost per byte. RAM, about 100 nanoseconds, is two decades long; it holds gigabytes at a high cost per byte. SSD, about 100 microseconds, is five decades long; it holds terabytes at a low cost per byte. Hard disk or network, about 10 milliseconds or more, is seven decades long and runs the full width of the chart; it is huge and the cheapest per byte. The gaps between rungs are annotated: up to ten times from registers to cache, ten times from cache to RAM, one thousand times from RAM to SSD, which is the difference between a book on your desk and driving to a library, and another one hundred times from SSD to disk. A second axis along the bottom relabels the very same decades at human scale, as if one nanosecond took one second: 1 second, 10 seconds, 1.7 minutes, 17 minutes, 2.8 hours, 1.2 days, 12 days, and 3.8 months. A rail down the left edge states the inverse trade: going up the ladder is faster, smaller and costlier per byte, and going down it is slower, bigger and cheaper per byte.">
  <defs>
    <marker id="p0l06a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p0l06a-arm" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Not five equal boxes — the five rungs span seven orders of magnitude</text>
  <text x="450" y="44" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.85">Drawn to scale on a log axis: each column to the right is 10× slower than the one before it.</text>

  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g stroke="currentColor" stroke-width="1" fill="none" stroke-dasharray="2 6">
      <path d="M272 84 L272 318" stroke-opacity="0.32"/>
      <path d="M356 84 L356 318" stroke-opacity="0.32"/>
      <path d="M440 84 L440 318" stroke-opacity="0.32"/>
      <path d="M524 84 L524 318" stroke-opacity="0.12"/>
      <path d="M608 84 L608 318" stroke-opacity="0.12"/>
      <path d="M692 84 L692 318" stroke-opacity="0.32"/>
      <path d="M776 84 L776 318" stroke-opacity="0.12"/>
      <path d="M860 84 L860 318" stroke-opacity="0.32"/>
    </g>

    <g stroke="currentColor" stroke-opacity="0.5" stroke-width="1.2" fill="none">
      <path d="M272 84 L860 84"/>
      <path d="M272 84 L272 79"/><path d="M356 84 L356 79"/><path d="M440 84 L440 79"/><path d="M524 84 L524 79"/>
      <path d="M608 84 L608 79"/><path d="M692 84 L692 79"/><path d="M776 84 L776 79"/><path d="M860 84 L860 79"/>
      <path d="M272 318 L860 318"/>
      <path d="M272 318 L272 323"/><path d="M356 318 L356 323"/><path d="M440 318 L440 323"/><path d="M524 318 L524 323"/>
      <path d="M608 318 L608 323"/><path d="M692 318 L692 323"/><path d="M776 318 L776 323"/><path d="M860 318 L860 323"/>
    </g>

    <g text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">
      <text x="272" y="76">1 ns</text><text x="356" y="76">10 ns</text><text x="440" y="76">100 ns</text><text x="524" y="76">1 µs</text>
      <text x="608" y="76">10 µs</text><text x="692" y="76">100 µs</text><text x="776" y="76">1 ms</text><text x="860" y="76">10 ms</text>
    </g>
    <text x="252" y="76" text-anchor="end" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.8">real latency →</text>

    <g text-anchor="middle" font-size="8" fill="currentColor" opacity="0.85">
      <text x="272" y="334">1 s</text><text x="356" y="334">10 s</text><text x="440" y="334">1.7 min</text><text x="524" y="334">17 min</text>
      <text x="608" y="334">2.8 hours</text><text x="692" y="334">1.2 days</text><text x="776" y="334">12 days</text><text x="860" y="334">3.8 months</text>
    </g>
    <text x="252" y="334" text-anchor="end" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.8">if 1 ns took 1 second →</text>

    <g fill="none" stroke-width="1.6">
      <path d="M36 198 L36 90" stroke="#0fa07f" stroke-opacity="0.75" marker-end="url(#p0l06a-arg)"/>
      <path d="M36 214 L36 318" stroke="#e0930f" stroke-opacity="0.75" marker-end="url(#p0l06a-arm)"/>
    </g>
    <text x="24" y="144" transform="rotate(-90 24 144)" text-anchor="middle" font-size="7" font-weight="700" fill="#0fa07f">faster · smaller · costlier</text>
    <text x="24" y="266" transform="rotate(-90 24 266)" text-anchor="middle" font-size="7" font-weight="700" fill="#e0930f">slower · bigger · cheaper</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="272" y="100" width="10" height="18" rx="3" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="272" y="144" width="84" height="18" rx="3" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
      <rect x="272" y="188" width="168" height="18" rx="3" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
      <rect x="272" y="232" width="420" height="18" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="272" y="276" width="588" height="18" rx="3" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1">
      <circle cx="52" cy="109" r="8.5"/><circle cx="52" cy="153" r="8.5"/><circle cx="52" cy="197" r="8.5"/>
      <circle cx="52" cy="241" r="8.5"/><circle cx="52" cy="285" r="8.5"/>
    </g>
    <g text-anchor="middle" font-size="8.5" font-weight="700" fill="currentColor" opacity="0.65">
      <text x="52" y="112">1</text><text x="52" y="156">2</text><text x="52" y="200">3</text><text x="52" y="244">4</text><text x="52" y="288">5</text>
    </g>

    <g font-size="10" font-weight="700">
      <text x="66" y="113" fill="#0fa07f">Registers</text>
      <text x="66" y="157" fill="#0fa07f">CPU cache</text>
      <text x="66" y="201" fill="#7c5cff">RAM</text>
      <text x="66" y="245" fill="#e0930f">SSD</text>
      <text x="66" y="289" fill="#e0930f">Hard disk / network</text>
    </g>
    <g text-anchor="end" font-size="9.5" font-weight="700" fill="currentColor">
      <text x="252" y="113">~1 ns</text>
      <text x="252" y="157">~1–10 ns</text>
      <text x="252" y="201">~100 ns</text>
      <text x="252" y="245">~100 µs</text>
      <text x="252" y="289">~10 ms+</text>
    </g>

    <g font-size="7.5" fill="currentColor" opacity="0.75">
      <text x="66" y="130">hundreds of bytes</text>
      <text x="66" y="174">KB–MB</text>
      <text x="66" y="218">GBs</text>
      <text x="66" y="262">TBs</text>
      <text x="66" y="306">huge</text>
    </g>
    <g font-size="7.5" fill="currentColor" opacity="0.35">
      <text x="148" y="130">·</text><text x="148" y="174">·</text><text x="148" y="218">·</text><text x="148" y="262">·</text><text x="148" y="306">·</text>
    </g>
    <g font-size="7.5" font-weight="700" fill="currentColor" opacity="0.85">
      <text x="157" y="130">highest cost/byte</text>
      <text x="157" y="174">very high cost/byte</text>
      <text x="157" y="218">high cost/byte</text>
      <text x="157" y="262">low cost/byte</text>
      <text x="157" y="306">lowest cost/byte</text>
    </g>

    <g font-size="7.5" fill="currentColor" opacity="0.62">
      <text x="292" y="113">a stub, because 1 ns is where this scale starts</text>
      <text x="366" y="157">on the CPU chip itself — holds the hot, recently-used data</text>
      <text x="450" y="201">Random Access Memory — DRAM leaks charge, so it refreshes; power off wipes it clean</text>
      <text x="282" y="245">solid-state drive — persistent, no power needed</text>
      <text x="282" y="289">a spinning platter or a hop across the network — the huge, cheap, slow bottom</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.2">
      <path d="M272 133 L356 133"/><path d="M272 129 L272 137"/><path d="M356 129 L356 137"/>
      <path d="M356 177 L440 177"/><path d="M356 173 L356 181"/><path d="M440 173 L440 181"/>
      <path d="M440 221 L692 221"/><path d="M440 217 L440 225"/><path d="M692 217 L692 225"/>
      <path d="M692 265 L860 265"/><path d="M692 261 L692 269"/><path d="M860 261 L860 269"/>
    </g>
    <g text-anchor="middle" font-size="8" font-weight="700" fill="currentColor" opacity="0.85">
      <text x="314" y="128">up to ×10</text>
      <text x="398" y="172">×10</text>
      <text x="566" y="216">×1000 — a book on your desk vs. driving to the library</text>
      <text x="776" y="260">×100 — and another hundredfold</text>
    </g>
  </g>

  <text x="450" y="360" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Every rung ends on a decade line — read straight down to see what that wait feels like at human scale.</text>
  <text x="450" y="378" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Faster is always smaller and costlier per byte: a little fast expensive RAM and a lot of slow cheap disk, never both at once.</text>
  <text x="450" y="398" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.8">Locality — programs reuse what they just used, and data near it — is why caching works: keep hot data high on the ladder.</text>
  <text x="450" y="414" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">That is the whole idea behind backend caching: Redis in front of a database, indexes, in-memory data.</text>
</svg>
```

| Level | Rough speed | Size | Cost per byte |
|---|---|---|---|
| Registers | ~1 ns | hundreds of bytes | highest |
| CPU cache | ~1–10 ns | KB–MB | very high |
| RAM | ~100 ns | GBs | high |
| SSD | ~100 µs | TBs | low |
| Hard disk / network | ~10 ms+ | huge | lowest |

Each rung is roughly **10× to 1000× slower** than the one above. The gap between RAM and
disk alone is like the difference between grabbing a book off your desk versus driving to a
library.

### Locality: why caching works at all

Programs aren't random: they tend to reuse data they *just* used (**temporal locality**)
and data *near* what they just used (**spatial locality**). Caches exploit this — keep the
hot, recently-used data on the fast upper rungs, and most reads never pay the slow price.
**This is the entire idea behind backend caching** (Redis in front of a database, indexes,
in-memory data): move the data your users hit most as high up the pyramid as you can.

## Build It

The hierarchy is really just "a small fast box in front of a big slow store." You can
model exactly that in Python. [`code/cache_demo.py`](../code/cache_demo.py) puts a tiny
cache in front of a slow store and runs a realistic workload (a few hot keys, accessed
repeatedly):

```python
class SlowStore:
    def __init__(self, data): self.data, self.slow_reads = data, 0
    def get(self, k):
        self.slow_reads += 1            # a slow trip down the hierarchy
        return self.data[k]

class Cache:
    def __init__(self, store, size):
        self.store, self.size, self.box = store, size, {}
        self.hits = self.misses = 0
    def get(self, k):
        if k in self.box:               # cache HIT — fast
            self.hits += 1
            return self.box[k]
        self.misses += 1                # cache MISS — go to the slow store
        if len(self.box) >= self.size:
            self.box.pop(next(iter(self.box)))   # evict the oldest
        self.box[k] = self.store.get(k)
        return self.box[k]
```

Because the workload has locality, a tiny cache turns thousands of slow reads into a
handful — the whole payoff of the hierarchy, in ~20 lines.

**Think about it:**

1. Why does DRAM lose its contents when the power goes off? (Hint: what stores each bit?)
2. Order these fastest-to-slowest: RAM, a CPU register, an SSD, a CPU cache.
3. Your API is slow because it reads the same few database rows on every request. Which
   idea from this lesson fixes it, and how?

## Key takeaways

- **RAM** is fast, volatile **working memory** holding the running program; the CPU reads
  from it when a value isn't in a register.
- **DRAM** stores each bit as a leaky **charge in a capacitor** — so it needs constant
  **refresh** and loses everything on **power off** (volatile).
- **RAM costs more per byte than disk** because it buys speed at the expense of capacity
  and persistence — the universal trade of the **memory hierarchy** (registers → cache →
  RAM → SSD → disk), each rung ~10–1000× slower but bigger/cheaper.
- **Locality** makes **caching** work: keep hot data high on the pyramid. This is the core
  idea behind backend caching, indexes, and in-memory stores.

Next: [The GPU](../07-the-gpu/) — a very different chip built to do thousands of small things
at once.
