# How Data Lives on Disk: Pages, Heaps & the Buffer Pool

> A database never reads "a row." It reads a **page** — a fixed-size block of bytes holding many rows — because that's the only unit the disk hands out efficiently. Understand the page and you understand why every index, transaction, and log in this phase works the way it does.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Schema Design & Normalization](../07-schema-design-and-normalization/)
**Time:** ~70 minutes

## The Problem

Everything so far has been the *logical* view: tables, rows, keys, constraints. But
underneath, a database is a program writing bytes to a file on a disk. And disks impose a
hard physical fact that shapes the entire design above them:

**You cannot efficiently read or write one row at a time.** Disks (and the operating
system on top of them) transfer data in fixed-size **blocks** — typically 4 KB or 8 KB.
Ask for a single 40-byte row and the hardware still reads the whole block it sits in. A
random read costs the same whether you use 40 bytes of the block or all 4096. So a database
that wants to be fast has to think in blocks, not rows: pack many rows into each block, read
a block once, and get many rows' worth of work out of it.

That block, as the database manages it, is called a **page**, and it's the atom of
everything below the logical model. This lesson builds a real one — a **slotted page**
inside a **heap file**, cached by a **buffer pool** — in ~130 lines of Python. Once you've
seen a row become `(page 2, slot 5)` and watched a page ride from disk into RAM and back,
indexes (Lesson 9), transactions (Lesson 11), and write-ahead logging (Lesson 13) stop
being magic — they're all just clever ways of moving these pages around.

## The Concept

### The page: the database's unit of everything

A **page** is a fixed-size chunk of bytes — Postgres uses **8 KB**, and the page is the
unit in which the database does *all* of its disk I/O, caching, and locking. A table isn't
stored as "a list of rows"; it's stored as a sequence of pages, each packed with as many
rows as fit. Reading a page is one disk operation that yields dozens or hundreds of rows.

Why a fixed size? Because it makes everything else simple: the byte offset of page `N` in
the file is just `N × PAGE_SIZE`, so the database can jump straight to any page with one
seek. And a fixed size means pages can be cached, swapped, and replaced uniformly (the
buffer pool below).

### Inside a page: the slotted layout

Rows are variable length (a name might be 4 characters or 40), which raises a puzzle: if you
just pack rows end to end and later one grows or is deleted, everything shifts and every
reference to a row breaks. The classic solution, used by Postgres and most databases, is the
**slotted page**:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 320" width="100%" style="max-width:720px" role="img" aria-label="A slotted database page: a header, a slot array growing right, free space in the middle, and rows growing left from the end. Each slot points to a row.">
  <defs>
    <marker id="ah1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="390" y="30" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One database page — fixed size (e.g. 8&#160;KB)</text>
  <g fill="none" stroke-linecap="round" stroke-linejoin="round">
    <rect x="22" y="52" width="736" height="196" rx="18" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2"/>
    <rect x="42" y="88" width="120" height="128" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="2"/>
    <rect x="186" y="100" width="48" height="40" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="2"/>
    <rect x="240" y="100" width="48" height="40" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="2"/>
    <rect x="294" y="100" width="48" height="40" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="2"/>
    <rect x="372" y="88" width="150" height="128" rx="10" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="7 6" opacity="0.5"/>
    <rect x="548" y="100" width="48" height="40" rx="7" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="2"/>
    <rect x="602" y="100" width="48" height="40" rx="7" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="2"/>
    <rect x="656" y="100" width="48" height="40" rx="7" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="2"/>
    <path d="M210 140 C 210 182, 680 182, 680 142" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#ah1)" opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="264" y="80" font-size="11.5" opacity="0.8">slots grow  →</text>
    <text x="626" y="80" font-size="11.5" opacity="0.8">←  rows grow</text>
    <text x="102" y="138" font-size="12" font-weight="700">HEADER</text>
    <text x="102" y="160" font-size="10.5" opacity="0.85">slot_count</text>
    <text x="102" y="178" font-size="10.5" opacity="0.85">free_ptr</text>
    <text x="210" y="125" font-size="11">slot0</text>
    <text x="264" y="125" font-size="11">slot1</text>
    <text x="318" y="125" font-size="11">slot2</text>
    <text x="447" y="146" font-size="12">free space</text>
    <text x="447" y="164" font-size="10" opacity="0.7">shrinks from both ends</text>
    <text x="572" y="125" font-size="11">row2</text>
    <text x="626" y="125" font-size="11">row1</text>
    <text x="680" y="125" font-size="11">row0</text>
    <text x="431" y="200" font-size="10.5" opacity="0.85">slot0 → (offset, length) → row0</text>
    <text x="390" y="286" font-size="11.5">A row's identity is (page number, slot number) — stable even when</text>
    <text x="390" y="304" font-size="11.5">the row is moved inside the page during compaction.</text>
  </g>
</svg>
```

The design: a small **header** at the front, then a **slot array** growing forward from it,
while the actual **row data** grows backward from the end of the page. Free space is the gap
in the middle. Each **slot** is a tiny fixed-size pointer — `(offset, length)` — that says
where its row lives inside the page. The row's real, stable identity is then just its **page
number + slot number**.

Why the indirection? Because now a row can be found through its slot, and if the row moves
*within* the page (say, after a compaction), only the slot's offset changes — the row's
external identity `(page, slot)` stays the same. That stable identity is precisely what an
index will store to point at a row (Lesson 9). Postgres calls this identity the **`ctid`**;
generically it's a **row id** or **tuple id**.

### The heap file: rows in no particular order

A table's pages are collected in a **heap file** — "heap" meaning *unordered*. When you
insert a row, the database drops it into any page with room (often the last one, appending),
and that's it. There's no sorting, no structure to maintain — which makes **inserts fast**
but means **finding a specific row requires scanning** every page until you hit it (the
O(n) full scan from Lesson 1). The heap is the default home for your rows; indexes are the
*separate*, sorted structures we add on top to avoid scanning it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 268" width="100%" style="max-width:680px" role="img" aria-label="A heap file for a table, holding three fixed-size pages of rows in no particular order.">
  <defs>
    <marker id="ah2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="380" y="28" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">A heap file — a table's rows across fixed-size pages</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M220 138 C 276 138, 276 80, 328 80" marker-end="url(#ah2)"/>
    <path d="M220 138 L 328 146" marker-end="url(#ah2)"/>
    <path d="M220 138 C 276 138, 276 212, 328 212" marker-end="url(#ah2)"/>
  </g>
  <g fill="none" stroke-linejoin="round">
    <rect x="40" y="104" width="180" height="66" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="2"/>
    <rect x="330" y="58" width="230" height="44" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="2"/>
    <rect x="330" y="124" width="230" height="44" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="2"/>
    <rect x="330" y="190" width="230" height="44" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="2"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="130" y="134" font-size="12" font-weight="700">HEAP FILE</text>
    <text x="130" y="153" font-size="10.5" opacity="0.85">table 'app_user'</text>
    <text x="445" y="85" font-size="11.5">Page 0  ·  rows 0–2</text>
    <text x="445" y="151" font-size="11.5">Page 1  ·  rows 3–5</text>
    <text x="445" y="217" font-size="11.5">Page 2  ·  rows 6–7 + free</text>
    <text x="380" y="258" font-size="11" opacity="0.9">Unordered: an insert drops into any page with room — fast to write, slow to find (scan page by page).</text>
  </g>
</svg>
```

### The buffer pool: pages living in RAM

Disk is slow (Lesson 1's latency table: ~100 µs for an SSD read, versus ~100 ns for RAM —
a 1000× gap). So a database never works directly on disk. It keeps a big cache of pages in
memory called the **buffer pool** (Postgres: `shared_buffers`), and every read and write
goes through it:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 466" width="100%" style="max-width:560px" role="img" aria-label="The buffer pool decision flow: a query checks whether a page is in RAM; a hit uses it directly, a miss reads it from disk; then the page is modified in RAM, marked dirty, and flushed to disk later.">
  <defs>
    <marker id="ah3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="360" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">The buffer pool — a RAM cache of disk pages</text>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M360 86 L 360 98" marker-end="url(#ah3)"/>
    <path d="M478 152 L 506 152" marker-end="url(#ah3)"/>
    <path d="M360 206 L 360 236" marker-end="url(#ah3)"/>
    <path d="M360 288 L 360 330" marker-end="url(#ah3)"/>
    <path d="M601 178 L 601 356 L 472 356" marker-end="url(#ah3)"/>
    <path d="M360 380 L 360 410" marker-end="url(#ah3)"/>
    <path d="M360 100 L 478 152 L 360 204 L 242 152 Z" fill="#7f7f7f" fill-opacity="0.05" stroke-width="2"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="250" y="42" width="220" height="44" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="506" y="130" width="188" height="46" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="250" y="238" width="220" height="50" rx="9" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="250" y="330" width="220" height="50" rx="9" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
    <rect x="250" y="410" width="220" height="44" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor" text-anchor="middle">
    <text x="360" y="69" font-size="11">Query needs a row on page 2</text>
    <text x="360" y="149" font-size="10.5">Page 2 in the</text>
    <text x="360" y="164" font-size="10.5">buffer pool?</text>
    <text x="600" y="150" font-size="11" font-weight="700">HIT — in RAM</text>
    <text x="600" y="166" font-size="9.5" opacity="0.85">use it directly (fast)</text>
    <text x="360" y="260" font-size="11" font-weight="700">MISS</text>
    <text x="360" y="276" font-size="9.5" opacity="0.85">read page 2 from disk → pool</text>
    <text x="360" y="352" font-size="10.5">modify in RAM →</text>
    <text x="360" y="368" font-size="10.5">page marked 'dirty'</text>
    <text x="360" y="437" font-size="10.5" opacity="0.9">flushed to disk later (checkpoint)</text>
    <text x="493" y="144" font-size="9.5" opacity="0.75">yes</text>
    <text x="379" y="226" font-size="9.5" opacity="0.75" text-anchor="start">no</text>
  </g>
</svg>
```

This is exactly the caching discipline from Phase 5, applied inside the database: the
buffer pool is a cache of disk pages, with a **hit ratio** that governs performance, an
**eviction policy** (which page to drop when full — a clock/LRU variant), and **dirty
pages** (modified in memory, not yet written back). Two consequences worth holding onto:
a write first changes a page *in RAM*, so "the change is durable" is a separate, later step
(the page must reach disk) — which is the entire reason **write-ahead logging** exists
(Lesson 13). And the buffer pool is why a "warm" database is so much faster than a
cold-started one: its hot pages are already in RAM.

### Build It

We'll build the storage layer bottom-up: a **slotted page**, a **heap file** of pages, and
a **buffer pool** caching reads — with a small page size so a handful of rows spills across
several pages and we can watch it happen.

```python
import struct

PAGE_SIZE = 128  # tiny on purpose (real DBs use 4-8 KB) so a few rows fill a page

_HEADER = struct.Struct("<HH")   # (slot_count, free_end)  -- rows grow down from PAGE_SIZE
_SLOT = struct.Struct("<HH")     # (row_offset, row_length)
_H = _HEADER.size

def new_page():
    page = bytearray(PAGE_SIZE)
    _HEADER.pack_into(page, 0, 0, PAGE_SIZE)   # 0 slots, free region ends at PAGE_SIZE
    return page

def page_insert(page, row):
    """Place a row; return its slot index, or None if the page is full."""
    slot_count, free_end = _HEADER.unpack_from(page, 0)
    slots_end = _H + slot_count * _SLOT.size
    if free_end - slots_end < len(row) + _SLOT.size:      # need room for row + its slot
        return None
    offset = free_end - len(row)
    page[offset:free_end] = row                            # write row at the end
    _SLOT.pack_into(page, slots_end, offset, len(row))     # append its slot pointer
    _HEADER.pack_into(page, 0, slot_count + 1, offset)     # update header
    return slot_count
```

The rest — reading a row back through its slot, a `HeapFile` that maps `(page, slot)`
identities onto a real file, and a `BufferPool` that caches pages and counts hits and
misses — is in [`code/heap_file.py`](code/heap_file.py). Run it:

```bash
python heap_file.py
```

and it inserts rows, reports the `(page, slot)` id each one got, reads a row back *by its
id* (no scan), does a full scan of the heap, and prints buffer-pool hit/miss stats across
two passes so you can see caching at work. The whole point: a "row" on disk is an address,
a "table" is a pile of pages, and RAM is where the work actually happens.

### Use It

You never hand-manage pages in production — but every one of these ideas is visible in
Postgres, and knowing them makes its behavior legible:

- **Page size** is 8 KB; a huge value that won't fit on a page is stored out-of-line via a
  mechanism called **TOAST**.
- **`ctid`** is the physical row identity `(page, slot)` — you can literally
  `SELECT ctid, * FROM t` and see it. It changes when a row is updated (a new version is
  written elsewhere — that's Lesson 12's MVCC).
- **`shared_buffers`** is the buffer pool; sizing it is one of the first things you tune.
- `SELECT relpages, reltuples FROM pg_class WHERE relname = 't';` shows how many pages and
  rows the planner (Lesson 10) thinks a table has — the numbers it uses to cost a scan.

You didn't have to build any of it. But because you did build a small version, "the query
read 4000 pages from disk because the buffer pool was cold" is now a sentence you can
reason about instead of nod along to.

## Think about it

1. A row is 40 bytes and a page is 8 KB. Roughly how many rows share a page, and why does
   that make reading 200 sequential rows dramatically cheaper than 200 random ones?
2. Why does the slotted layout store a row's identity as `(page, slot)` rather than a raw
   byte offset? What can change without breaking references, and what would break if you
   used raw offsets?
3. A heap file makes inserts fast but lookups slow. Which earlier lesson's problem is that,
   and what structure (next lesson) fixes it without changing the heap?
4. A page is modified in the buffer pool but the power dies before it's written to disk.
   What have you lost, and which later lesson exists precisely to prevent that loss?

## Key takeaways

- Disks transfer fixed-size **blocks**, so a database reads and writes in **pages** (Postgres
  8 KB), packing many rows per page — the unit of all I/O, caching, and locking.
- A **slotted page** keeps a header + a forward-growing **slot array** of `(offset, length)`
  pointers + backward-growing row data, giving each row a stable identity of
  **`(page, slot)`** (Postgres `ctid`) even as rows move within the page.
- A **heap file** is the table's pages in **no order**: inserts are cheap (drop it anywhere
  with room), but finding a specific row means a **full scan** — the problem indexes solve.
- The **buffer pool** caches pages in RAM (Postgres `shared_buffers`); reads and writes go
  through it, with a hit ratio, eviction, and **dirty pages** — so a write is durable only
  once its page reaches disk, which is why write-ahead logging exists.

Next: [Indexes & the B-Tree](../09-indexes-and-the-btree/) — the sorted structure we build
*on top of* the heap so finding a row stops meaning scanning every page.
