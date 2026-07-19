# Indexes & the B-Tree

> A full scan reads every page to find one row. An index is a sorted map you keep on the side so you can jump almost straight to it — and the structure that makes it work on disk, the B-tree, keeps *any* row on a huge table just three or four page-reads away.

**Type:** Build
**Languages:** Python
**Prerequisites:** [How Data Lives on Disk](../08-storage-pages-and-heaps/)
**Time:** ~90 minutes

## The Problem

Last lesson's heap file has a painful property: to find "the user with email
`grace@navy.mil`," you scan pages until you hit her. On a ten-million-row table that's
millions of page reads for one answer — the O(n) scan from Lesson 1, now with a physical
price tag in disk I/O.

The obvious fix is "keep the data sorted so you can binary-search it." But you can't sort
the heap itself usefully: a table has *many* columns you'll search by (email, and id, and
last-name…) and the heap can only be in one order at a time; worse, keeping a sorted file
sorted means shifting mountains of rows on every insert. So instead we build a **separate,
sorted structure off to the side** — an **index** — that maps a key to the row's location,
and leaves the heap alone.

That raises the real engineering question: what structure? A sorted array binary-searches
in O(log n) but is murder to insert into. A binary search tree can rot into a linked list.
The answer, invented in 1970 and still under essentially every relational index today, is
the **B-tree** — a balanced tree shaped specifically for disk. This lesson builds a working
one and shows why it turns a million-row lookup into three page reads.

## The Concept

### What an index actually is

An **index** is a second data structure, stored separately from the table, that keeps some
key **in sorted order** alongside a pointer to where the full row lives — the `(page, slot)`
row id from Lesson 8. It's the book analogy made literal: the heap is the book's pages in
reading order; the index is the alphabetical index at the back, listing each term and the
page it's on. You don't read the whole book to find "B-tree"; you look it up and jump.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 288" width="100%" style="max-width:720px" role="img" aria-label="A sorted index on email lists three entries, each mapping an email to a page-and-slot row id; the grace entry's row id points into the heap file, jumping straight to page 3, slot 7." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l09a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="380.0" y="26" text-anchor="middle" font-size="14" font-weight="700">An index: a sorted map from key to row id</text>
  <g fill="none">
  <path d="M332 212.0 L 438 177.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09a-ah)"/>
  </g>
  <g>
  <rect x="28" y="58" width="322" height="196" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="46" y="100" width="286" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="46" y="146" width="286" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="46" y="192" width="286" height="40" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="438" y="140" width="300" height="74" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="189.0" y="84" font-size="12" text-anchor="middle" font-weight="700" >Index on email (sorted)</text>
  <text x="189.0" y="123.7" font-size="11" text-anchor="middle" >ada@...   → (page 5, slot 2)</text>
  <text x="189.0" y="169.7" font-size="11" text-anchor="middle" >alan@...  → (page 1, slot 0)</text>
  <text x="189.0" y="215.7" font-size="11" text-anchor="middle" >grace@... → (page 3, slot 7)</text>
  <text x="588.0" y="172.9" font-size="11.5" text-anchor="middle" font-weight="700" >Heap file</text>
  <text x="588.0" y="188.9" font-size="10" text-anchor="middle" opacity="0.85" >jump straight to page 3, slot 7</text>
  <text x="385.0" y="188.5" font-size="9.5" text-anchor="middle" opacity="0.75" >row id</text>
  </g>
  
</svg>
```

Crucially, the index is *redundant* — every answer it gives could be found by scanning the
heap. It exists purely to make lookups fast, which is why it's a pure performance/space
trade (more on the cost below).

### Why binary search wants a tree, and why the tree must be a B-tree

Sorted data can be binary-searched: check the middle, halve the search space, repeat —
O(log n). Ten million rows is ~23 halvings. Beautiful, until you insert: putting a new key
in the middle of a sorted array shifts everything after it. And a plain binary search tree
solves inserts but can degenerate — insert keys in sorted order and it becomes a linked
list, O(n) again.

The **B-tree** (Bayer & McCreight, 1972, *"Organization and Maintenance of Large Ordered
Indexes"*) fixes both by being **balanced** and **high-fanout**. Two ideas:

1. **Each node holds many keys, not one** — a whole page's worth (dozens to hundreds). A
   node *is* a page (Lesson 8), so one disk read loads many keys and many branch choices at
   once.
2. **The tree stays balanced automatically.** When a node fills up, it **splits** in two and
   pushes its middle key up to the parent. Every leaf is always at the same depth, so the
   tree never degenerates — its worst case is its average case.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 380" width="100%" style="max-width:720px" role="img" aria-label="A B-tree with a root holding keys 30 and 60, three child nodes holding key ranges, and three leaves pointing at the heap rows in each range." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l09b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="410.0" y="26" text-anchor="middle" font-size="14" font-weight="700">A B-tree — many keys per node, every leaf at the same depth</text>
  <g fill="none">
  <path d="M410.0 94 L 150.0 152" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  <path d="M410.0 94 L 410.0 152" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  <path d="M410.0 94 L 672.0 152" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  <path d="M150.0 202 L 150.0 272" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  <path d="M410.0 202 L 410.0 272" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  <path d="M672.0 202 L 672.0 272" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l09b-ah)"/>
  </g>
  <g>
  <rect x="340.0" y="44" width="140" height="50" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="85.0" y="152" width="130" height="50" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="345.0" y="152" width="130" height="50" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="600.0" y="152" width="144" height="50" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="75.0" y="272" width="150" height="50" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="335.0" y="272" width="150" height="50" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="597.0" y="272" width="150" height="50" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="410.0" y="72.9" font-size="11.5" text-anchor="middle" >[ 30 · 60 ]</text>
  <text x="150.0" y="180.9" font-size="11.5" text-anchor="middle" >[ 10 · 20 ]</text>
  <text x="410.0" y="180.9" font-size="11.5" text-anchor="middle" >[ 40 · 50 ]</text>
  <text x="672.0" y="180.9" font-size="11.5" text-anchor="middle" >[ 70 · 80 · 90 ]</text>
  <text x="150.0" y="300.9" font-size="11.5" text-anchor="middle" >heap rows &lt; 30</text>
  <text x="410.0" y="300.9" font-size="11.5" text-anchor="middle" >heap rows 30–60</text>
  <text x="672.0" y="300.9" font-size="11.5" text-anchor="middle" >heap rows &gt; 60</text>
  </g>
  <text x="410.0" y="368" text-anchor="middle" font-size="11" opacity="0.9">To find a key: start at the root and follow the child whose range contains it.</text>
</svg>
```

To find a key you start at the root, pick the child whose range contains it, and descend —
at each node a quick search among its keys tells you which pointer to follow.

### The magic of fanout: why the tree is so short

Here's the payoff, and it's worth internalizing because it's *why databases scale*. The
number of levels you descend equals the number of page reads to find any row, and fanout
makes that number tiny. If each node holds **100 keys** (so ~101 children — modest for an
8 KB page):

| Levels | Keys the tree can hold |
|---|---|
| 1 | ~100 |
| 2 | ~10,000 |
| 3 | ~1,000,000 |
| 4 | ~100,000,000 |

**Three levels index a million rows; four index a hundred million.** So *any* row in a
100-million-row table is at most **four page reads** away — and the top levels are almost
always cached in the buffer pool, so it's often just one real disk read. That's the whole
game: high fanout makes the tree so shallow that "search a hundred million things" costs
about the same as "search a hundred." The height grows as `log_fanout(n)`, which barely
moves as `n` explodes.

### B-tree vs. B+-tree (what your database actually uses)

Real databases use a variant, the **B+-tree**, with two refinements: **all row pointers
live in the leaves** (internal nodes hold only keys, as signposts), and **the leaves are
linked in a chain**. The linked leaves make **range scans** cheap — "all orders from March"
descends to the first match, then walks the leaf chain in sorted order without revisiting
the tree. When someone says "B-tree index" in a database context, they almost always mean a
B+-tree. Our build below is a classic B-tree for clarity; the leaf-chaining is the one thing
to add in your head.

### Clustered vs. secondary indexes

Two ways an index relates to the table's rows:

- A **secondary (non-clustered) index** is a separate structure whose leaves hold the *row
  id* pointing back into the heap. The heap stays in its own order; you can have many
  secondary indexes on one table (one per column you search by). This is how **Postgres**
  works — the heap plus independent B-tree indexes.
- A **clustered index** stores the *actual rows* in the leaves, in key order — the table
  *is* the B-tree, sorted by that key. Lookups by the clustering key need no second hop to a
  heap, but there can be only **one** (the rows can only be in one physical order). This is
  how **MySQL/InnoDB** stores every table, ordered by its primary key.

### The cost: why not index every column?

Indexes are not free speed — they're a trade, and over-indexing is a real mistake:

- **Writes get slower.** Every `INSERT`/`UPDATE`/`DELETE` must update *every* index on the
  table, each an extra structure to keep sorted and balanced. Ten indexes means a write does
  eleven structures' worth of work.
- **Space.** Each index is a whole extra copy of its key column plus pointers.
- **The planner might ignore it anyway.** An index on a low-selectivity column (a `boolean`
  that's `true` for half the rows) is often *slower* than a scan, so the planner (Lesson 10)
  skips it — and you paid the write cost for nothing.

The discipline: index the columns you actually **filter, join, and sort by**, favor
**high-selectivity** columns (many distinct values, like email), use **composite indexes**
for multi-column queries (respecting the *leftmost-prefix* rule — an index on `(a, b)` helps
queries on `a` or `a, b` but not `b` alone), and *measure* before adding more.

### Build It

We'll build a real, self-balancing B-tree — nodes that hold many keys, splitting as they
fill — and watch its height stay tiny as the key count explodes. The heart is the split:

```python
def _split_child(self, parent, i):
    """Node parent.children[i] is full: split it and lift its median into parent."""
    t = self.t                       # minimum degree; a node holds t-1 .. 2t-1 entries
    full = parent.children[i]
    right = BTreeNode(leaf=full.leaf)
    median = full.entries[t - 1]     # this key moves UP to the parent
    right.entries = full.entries[t:] # top half -> new right node
    full.entries = full.entries[:t - 1]  # bottom half stays
    if not full.leaf:                # internal nodes split their children too
        right.children = full.children[t:]
        full.children = full.children[:t]
    parent.entries.insert(i, median)
    parent.children.insert(i + 1, right)
```

The full tree — `insert` (splitting the root when it fills, growing the tree *upward* so it
stays balanced), `search` (which reports how many nodes it visited), an in-order range scan,
and a height report — is in [`code/btree.py`](code/btree.py). Run it:

```bash
python btree.py
```

It inserts 100,000 keys, prints the tree's **height** (spoiler: single digits), searches a
key while counting **nodes visited** versus the ~50,000 a linear scan would average, shows a
**range scan** returning keys already in sorted order, and prints a height-vs-size table so
you can watch `log_fanout(n)` in action.

### Use It

In Postgres you never touch a node — you just create the index and the planner uses it:

```sql
CREATE INDEX idx_user_email ON app_user (email);        -- a B+-tree index
CREATE INDEX idx_order_user_date ON orders (user_id, placed_at);  -- composite
```

Then `EXPLAIN` (Lesson 10) shows the planner switching from `Seq Scan` to `Index Scan`, and
`SELECT * FROM pg_indexes WHERE tablename = 'app_user';` lists what exists. B-tree is the
default and right choice for equality and range queries; Postgres also offers specialized
types (GIN for full-text/JSON, GiST for geometry, BRIN for huge append-only tables) for
when a B-tree isn't the right shape — but B-tree is where 95% of indexing lives.

## Think about it

1. A node holds 200 keys. How many levels (page reads) to index a **billion** rows, roughly?
   Why is the top of the tree effectively free to traverse?
2. Why can a table have many secondary indexes but only one clustered index? What does the
   clustered index's leaf hold that a secondary's doesn't?
3. You add indexes to nine columns "to be safe." Name two concrete costs you just took on,
   and one reason the database might not even use some of them.
4. You have an index on `(country, city)`. Which of these does it help, and why:
   `WHERE country = 'DE'`, `WHERE country = 'DE' AND city = 'Berlin'`, `WHERE city =
   'Berlin'`?

## Key takeaways

- An **index** is a separate, sorted structure mapping a key to a row's location, so lookups
  jump instead of scanning — redundant data kept purely to trade space and write cost for
  read speed.
- The **B-tree** (and its **B+-tree** variant) is balanced and **high-fanout**: each node is
  a page holding many keys, and full nodes **split**, keeping every leaf at the same depth.
- **Fanout makes the tree shallow** — with ~100 keys/node, three levels index a million rows
  and four index a hundred million, so any row is a handful of page reads away; height grows
  as `log_fanout(n)`.
- **Secondary** indexes (Postgres) point back into the heap and you can have many;
  a **clustered** index (InnoDB primary key) stores the rows themselves in key order, and
  there's only one.
- Indexes **cost writes and space**, and the planner may skip low-selectivity ones — so
  index the columns you filter/join/sort by, prefer high selectivity, mind the composite
  **leftmost-prefix** rule, and measure.

Next: [How Queries Run: The Planner & EXPLAIN](../10-query-planning-and-explain/) — how the
database *decides* whether to use one of these indexes or just scan the heap.
