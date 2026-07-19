# Wide-Column Stores

> When you need to absorb a million writes a second, forever, across a hundred cheap machines, no single-primary database can help you — the bottleneck is physics, not tuning. Wide-column stores answer with two ideas: spread every row across the cluster by a partition key so there is no single primary, and replace the B-tree's in-place updates with an append-only engine (the LSM-tree) that turns every write into a cheap sequential append. The price is joins, ad-hoc queries, and strong consistency by default. You design the tables around your queries, not the other way round.

**Type:** Learn
**Languages:** —
**Prerequisites:** [When Not to Use SQL](../01-when-not-to-use-sql/), [Key-Value Stores](../02-key-value-stores/), [How Data Lives on Disk: Pages, Heaps & the Buffer Pool](../../03-relational-databases/08-storage-pages-and-heaps/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/)
**Time:** ~45 minutes

## The Problem

You're building the backend for a messaging app. Every message sent — billions a day — must be
written durably and be readable, in order, from a user's conversation. Reach for the tools you
know and each one hits a wall:

- A **relational** database funnels every write through one primary (Phase 3's WAL and MVCC
  assume it). One machine, however large, cannot ingest a billion writes a day plus maintain a
  B-tree index on every insert. You could shard it, but then a conversation's messages scatter
  across shards and reassembling them fights the design.
- A **key-value** store scales writes beautifully, but you can only fetch by exact key — you can't
  ask for "the last 50 messages in this conversation, newest first."
- A **document** store gives you queryable values, but at this write volume the single-primary and
  index-maintenance costs bite the same way relational does.

You need three things at once that no store so far gives together: **enormous write throughput**,
**horizontal scale across many machines**, and **ordered range reads within a group** (a
conversation, a user's timeline, a sensor's readings). The **wide-column store** — born from
Google's **Bigtable** (2006) and Amazon's **Dynamo** (2007) papers, and embodied today in
**Apache Cassandra**, **HBase**, and **ScyllaDB** — is the database shaped for exactly this.
Understanding it means understanding two things deeply: its unusual data model, and the
write-optimized storage engine (the **LSM-tree**) that makes the throughput possible.

## The Concept

### First, clear up the name — it is *not* a columnar analytics store

This is the single most common confusion in all of NoSQL, so kill it up front. "Wide-column" and
"columnar" sound identical and mean opposite things:

- A **columnar / column-oriented analytics store** (Parquet, Redshift, ClickHouse, BigQuery)
  stores each *column* contiguously on disk so an analytics query can scan one column across
  millions of rows fast. It's built for `SELECT AVG(price) FROM sales` over a whole table — **OLAP**,
  analytics.
- A **wide-column store** (Cassandra, HBase) is a *row* store that partitions rows across a cluster
  and lets each row have a different, sparse set of columns. It's built for high-volume operational
  reads and writes by key — **OLTP**-ish, at scale.

They are unrelated. This lesson is about the second. (If you hear "column store" in an *analytics*
context, that's the first, and it belongs to a data-warehouse discussion, not this one.)

### The data model: a partitioned, sorted map of maps

Forget tables-of-rows for a moment. The wide-column model is best understood as a **map of maps**,
addressed by a compound key. Every piece of data is located by:

```text
   (partition key)              →   which NODE owns the data   (distribution)
      (clustering key)          →   the SORT ORDER within that partition   (range reads)
         (column name)          →   value
```

That two-level key is the entire design, and each level does one job:

- The **partition key** decides *which machine* the data lives on. It's hashed onto the same kind
  of ring you built in Lesson 2 (consistent hashing) — so writes and reads for different partition
  keys land on different nodes, and the cluster shares the load. All data for one partition key
  lives together on one node (and its replicas).
- The **clustering key** decides the *sort order of rows within a partition*. Because the rows of a
  partition are stored physically sorted by this key, you can do a fast **ordered range read** —
  "the last 50 messages," "readings between 9am and 10am" — reading a contiguous run off disk.

Here's a messaging table modeled the Cassandra way — partition by conversation, cluster by time:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 556" width="100%" style="max-width:880px" role="img" aria-label="How a compound key splits into two jobs in a wide-column store. The primary key is written as PRIMARY KEY, open bracket conv_id close bracket, then sent_at DESC. The first part, conv_id, is the partition key: it is hashed onto the consistent-hashing ring and decides which node in the cluster owns the data, which is what gives horizontal scale. The second part, sent_at DESC, is the clustering key: rows inside a partition are stored physically sorted by it, which is what gives fast ordered range reads. Below, a cluster holds two nodes. Node A owns the whole partition conv:42, containing two rows sorted newest first: sent_at 10:03 from Ada body hi, then sent_at 10:02 from Bob body yo; those rows sit next to each other on disk. Node B owns partition conv:88, containing sent_at 09:15 from Cy; reads for conv:88 never touch Node A. The consequence is a sharp split in cost: a query inside one partition, such as the last fifty messages in conv:42, is one node and one contiguous sequential read and is cheap, while a query that spans partitions, such as every message Ada ever sent, must ask every node and merge the results, and is expensive.">
  <defs>
    <marker id="p4l4a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p4l4a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One compound key, two different jobs — which node, and in what order</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="450" y="58" text-anchor="middle" font-size="13" fill="currentColor">PRIMARY KEY ( <tspan fill="#3553ff" font-weight="700">(conv_id)</tspan>, <tspan fill="#0fa07f" font-weight="700">sent_at DESC</tspan> )</text>
    <g fill="none" stroke-width="1.5">
      <path d="M442 64 L442 70 L255 70 L255 73" stroke="#3553ff" marker-end="url(#p4l4a-arb)"/>
      <path d="M540 64 L540 70 L645 70 L645 73" stroke="#0fa07f" marker-end="url(#p4l4a-arg)"/>
    </g>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="90" y="76" width="330" height="80" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
      <rect x="480" y="76" width="330" height="80" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="255" y="98" font-size="11" font-weight="700" fill="#3553ff">1 · PARTITION KEY</text>
      <text x="255" y="118" font-size="9.5">hash(conv_id) → a position on the ring</text>
      <text x="255" y="134" font-size="9.5">decides WHICH NODE owns every row</text>
      <text x="255" y="150" font-size="8.5" opacity="0.75">this is what gives horizontal scale</text>

      <text x="645" y="98" font-size="11" font-weight="700" fill="#0fa07f">2 · CLUSTERING KEY</text>
      <text x="645" y="118" font-size="9.5">rows are stored physically SORTED by it</text>
      <text x="645" y="134" font-size="9.5">decides the ORDER inside one partition</text>
      <text x="645" y="150" font-size="8.5" opacity="0.75">this is what gives ordered range reads</text>
    </g>
    <g fill="none" stroke-width="1.5">
      <path d="M150 158 L150 174" stroke="#3553ff" marker-end="url(#p4l4a-arb)"/>
      <path d="M750 158 L750 174" stroke="#0fa07f" marker-end="url(#p4l4a-arg)"/>
    </g>

    <rect x="20" y="178" width="860" height="232" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4" fill-rule="evenodd"/>
    <text x="450" y="200" text-anchor="middle" font-size="11" font-weight="700" fill="currentColor">Cluster — one partition lives entirely on one node (plus its replicas)</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="40" y="214" width="470" height="182" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="530" y="214" width="330" height="182" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
      <rect x="56" y="252" width="438" height="134" rx="8" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.85"/>
      <rect x="546" y="252" width="298" height="134" rx="8" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-opacity="0.85"/>
    </g>
    <g fill="none" stroke="none">
      <rect x="70" y="298" width="410" height="24" rx="6" fill="#0fa07f" fill-opacity="0.13"/>
      <rect x="70" y="326" width="410" height="24" rx="6" fill="#0fa07f" fill-opacity="0.07"/>
      <rect x="560" y="298" width="270" height="24" rx="6" fill="#0fa07f" fill-opacity="0.13"/>
    </g>

    <text x="56" y="240" font-size="11.5" font-weight="700" fill="#7c5cff">Node A</text>
    <text x="130" y="240" font-size="8.5" fill="currentColor" opacity="0.75">hash(conv:42) landed here</text>
    <text x="70" y="272" font-size="10.5" font-weight="700" fill="#0fa07f">partition conv:42</text>
    <text x="70" y="288" font-size="8.5" fill="currentColor" opacity="0.8">all of it on ONE node — rows sorted by sent_at DESC</text>
    <text x="80" y="314" font-size="9.5" fill="currentColor">sent_at=10:03 · from=Ada · body='hi'</text>
    <text x="470" y="314" font-size="8" text-anchor="end" fill="currentColor" opacity="0.8">newest</text>
    <text x="80" y="342" font-size="9.5" fill="currentColor">sent_at=10:02 · from=Bob · body='yo'</text>
    <text x="470" y="342" font-size="8" text-anchor="end" fill="currentColor" opacity="0.8">older</text>
    <text x="70" y="366" font-size="8.5" fill="#0fa07f">the rows of one partition are contiguous on disk —</text>
    <text x="70" y="380" font-size="8.5" fill="#0fa07f">"the last 50 messages" = ONE cheap sequential read</text>

    <text x="546" y="240" font-size="11.5" font-weight="700" fill="#7c5cff">Node B</text>
    <text x="620" y="240" font-size="8.5" fill="currentColor" opacity="0.75">hash(conv:88) landed here</text>
    <text x="560" y="272" font-size="10.5" font-weight="700" fill="#0fa07f">partition conv:88</text>
    <text x="560" y="288" font-size="8.5" fill="currentColor" opacity="0.8">a different hash → a different node</text>
    <text x="570" y="314" font-size="9.5" fill="currentColor">sent_at=09:15 · from=Cy · body='…'</text>
    <text x="560" y="356" font-size="8.5" fill="currentColor" opacity="0.85">reads for conv:88 never touch Node A</text>
    <text x="560" y="370" font-size="8.5" fill="currentColor" opacity="0.85">— different partition, different owner</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.8">
      <rect x="20" y="426" width="420" height="58" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="460" y="426" width="420" height="58" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle">
      <text x="230" y="448" font-size="10.5" font-weight="700" fill="#0fa07f">CHEAP — inside one partition</text>
      <text x="230" y="466" font-size="9" fill="currentColor">"last 50 messages in conv:42" → one node, one read</text>
      <text x="670" y="448" font-size="10.5" font-weight="700" fill="#e0930f">EXPENSIVE — across partitions</text>
      <text x="670" y="466" font-size="9" fill="currentColor">"every message Ada sent" → ask EVERY node, then merge</text>
    </g>
  </g>
  <text x="450" y="508" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Get the partition key right and your query is one sequential read; get it wrong and it is a full-cluster scan.</text>
  <text x="450" y="526" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">That is why you model the query first: filter by the partition key, order by the clustering key — one table per access pattern.</text>
  <text x="450" y="544" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">There are no joins across partitions — they may be on different machines, so related data is stored together, or stored twice.</text>
</svg>
```

Two more properties fall out of this model and matter enormously:

- **Sparse and wide.** Each row (partition) can have a different, huge set of columns — Bigtable's
  original design allowed *millions* of columns per row, most absent. A missing column costs
  nothing (there's no `NULL` slot reserved, unlike a relational row). This is the "wide" in
  wide-column: rows are wide and ragged, not uniform.
- **No joins, ever.** There is no way to join partition to partition — they may be on different
  machines. If you need related data together, you **store it together** (denormalize) or you
  store it *twice*, once per query. Which leads to the defining discipline…

### Query-first modeling: one table per access pattern

In the relational world you model the *data* (normalize into clean tables) and then query it
however you like; the planner figures out the joins. In the wide-column world that's inverted, and
it's the hardest mental shift for a SQL veteran: **you model the queries.**

The rule is blunt: **the partition key must contain what you filter by, and the clustering key must
match how you want it ordered — for each query you intend to run.** If you have two access patterns
("messages by conversation, newest first" and "messages by user across all conversations"), you
build **two tables**, writing each message into both. Duplicating data on write to make each read a
single-partition lookup is not a hack here — it is the intended design. Storage is cheap; a
cross-partition scatter-read is not.

This is why Lesson 7 ("Data Modeling by Access Pattern") exists as its own lesson: in these stores,
listing your access patterns *before* designing tables isn't good practice, it's mandatory — get
the partition key wrong and the query you need is impossible without a full-cluster scan.

### The engine that makes it fast: the LSM-tree

Now the deep part — *why* wide-column stores can absorb writes a relational database can't. The
answer is the storage engine. Recall Phase 3: a B-tree stores rows in pages and **updates them in
place**, which means a write is a random disk seek plus index maintenance. Great for reads,
expensive for a write firehose.

Wide-column stores use the opposite structure — the **Log-Structured Merge-tree (LSM-tree)**
(O'Neil et al., 1996). It's the Bitcask log from Lesson 2 with one addition — *keep the data
sorted* — and it's built on a simple bet: **never do a random write; only ever append, and sort
lazily.** The write path:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 616" width="100%" style="max-width:880px" role="img" aria-label="The LSM-tree write path, in four numbered steps. An incoming write of a key and value forks immediately into two things that both happen on every write, in parallel. Step one, on the left: the write is appended to the commit log, one sequential append to a file on disk — this is Phase 3's write-ahead log reused here, so an acknowledged write survives a crash. Step two, on the right: the write is inserted into the memtable, a sorted structure held in RAM such as a skip list, with no disk seek in the hot path, which is why writes are so cheap. Both are done before the write is acknowledged. Step three: when the memtable fills up, the whole thing is flushed at once to a new SSTable — a Sorted String Table, an immutable file that is never edited. On disk these SSTables pile up: SSTable 1, SSTable 2, SSTable 3, each sorted and immutable. Step four: compaction runs in the background, merge-sorting the sorted runs into fewer, larger files in linear sequential time, discarding superseded values and tombstones. The payoff is that writes never seek; the price is that a read may have to check the memtable plus several SSTables, which Bloom filters and compaction keep cheap.">
  <defs>
    <marker id="p4l4b-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p4l4b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="p4l4b-arp" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The LSM-tree write path — never seek, only append, and sort lazily</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="340" y="44" width="220" height="44" rx="10" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="40" y="136" width="380" height="90" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
      <rect x="480" y="136" width="380" height="90" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
      <rect x="180" y="274" width="380" height="76" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>

    <g text-anchor="middle" fill="currentColor">
      <text x="450" y="64" font-size="12" font-weight="700" fill="#3553ff">write(key, value)</text>
      <text x="450" y="80" font-size="8.5" opacity="0.75">one message, arriving</text>

      <text x="450" y="114" font-size="8.5" font-weight="700" opacity="0.85">BOTH of these happen on every write — in parallel</text>

      <text x="230" y="160" font-size="11.5" font-weight="700" fill="#7c5cff">1 · append to the COMMIT LOG</text>
      <text x="230" y="180" font-size="9.5">one sequential append to a file on disk</text>
      <text x="230" y="196" font-size="9.5">Phase 3's write-ahead log, reused here</text>
      <text x="230" y="214" font-size="8.5" opacity="0.75">survives a crash — an acked write is never lost</text>

      <text x="670" y="160" font-size="11.5" font-weight="700" fill="#0fa07f">2 · insert into the MEMTABLE</text>
      <text x="670" y="180" font-size="9.5">a sorted structure in RAM (skip list)</text>
      <text x="670" y="196" font-size="9.5">no disk seek in the hot path</text>
      <text x="670" y="214" font-size="8.5" opacity="0.75">memory speed — this is why writes are cheap</text>

      <text x="450" y="244" font-size="9" opacity="0.9">both are done before the write is acknowledged</text>

      <text x="370" y="298" font-size="11.5" font-weight="700" fill="#7c5cff">3 · FLUSH to a new SSTable</text>
      <text x="370" y="318" font-size="9.5">the whole memtable written out at once</text>
      <text x="370" y="334" font-size="9.5">an SSTable: sorted, IMMUTABLE, never edited</text>
    </g>

    <g fill="none" stroke="#3553ff" stroke-width="1.8">
      <path d="M380 90 L240 130" marker-end="url(#p4l4b-arb)"/>
      <path d="M520 90 L670 130" marker-end="url(#p4l4b-arb)"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M670 228 L670 266 L370 266 L370 270" marker-end="url(#p4l4b-arg)"/>
    </g>
    <text x="684" y="252" font-size="8.5" fill="currentColor" opacity="0.8">when the memtable fills up</text>

    <rect x="40" y="368" width="820" height="176" rx="12" fill="#7c5cff" fill-opacity="0.04" stroke="#7c5cff" stroke-opacity="0.55" stroke-width="1.5"/>
    <g fill="none" stroke="#7c5cff" stroke-width="1.8">
      <path d="M370 352 L375 398" marker-end="url(#p4l4b-arp)"/>
    </g>
    <text x="60" y="390" font-size="10.5" font-weight="700" fill="#7c5cff">On disk</text>
    <text x="115" y="390" font-size="8.5" fill="currentColor" opacity="0.75">— immutable files</text>
    <text x="392" y="390" font-size="8" fill="currentColor" opacity="0.75">each flush adds one more file</text>

    <g fill="none" stroke-linejoin="round" stroke-width="1.6">
      <rect x="270" y="402" width="220" height="34" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="270" y="444" width="220" height="34" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="270" y="486" width="220" height="34" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="520" y="414" width="320" height="94" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
    </g>
    <g text-anchor="middle" fill="currentColor">
      <text x="380" y="423" font-size="9">SSTable 1 · sorted, immutable</text>
      <text x="380" y="465" font-size="9">SSTable 2 · sorted, immutable</text>
      <text x="380" y="507" font-size="9">SSTable 3 · sorted, immutable</text>

      <text x="680" y="438" font-size="11.5" font-weight="700" fill="#7c5cff">4 · COMPACTION — in the background</text>
      <text x="680" y="458" font-size="9">merge-sorts the sorted runs into</text>
      <text x="680" y="474" font-size="9">fewer, larger files — O(n), sequential</text>
      <text x="680" y="492" font-size="8.5" opacity="0.8">discarding superseded values + tombstones</text>

      <text x="450" y="532" font-size="8.5" opacity="0.8">you never edit an SSTable — you only add new ones and merge old ones away</text>
    </g>
    <g fill="none" stroke="#7c5cff" stroke-width="1.6">
      <path d="M496 419 L514 442" marker-end="url(#p4l4b-arp)"/>
      <path d="M496 461 L514 461" marker-end="url(#p4l4b-arp)"/>
      <path d="M496 503 L514 480" marker-end="url(#p4l4b-arp)"/>
    </g>
  </g>
  <text x="450" y="568" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Writes never seek: one sequential append plus one memory insert — that is the entire throughput story.</text>
  <text x="450" y="586" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The price is paid on reads: a key may sit in the memtable or in any SSTable, so a read may check several places.</text>
  <text x="450" y="604" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="currentColor" opacity="0.72">Bloom filters skip the SSTables that cannot hold the key, and compaction keeps their number small — the B-tree's mirror image.</text>
</svg>
```

Step by step:

1. **Commit log (write-ahead log).** The write is first appended to a durable log on disk — a
   sequential append, fast — so a crash can't lose an acknowledged write (exactly Phase 3,
   Lesson 13's WAL, reused here).
2. **Memtable.** The write also goes into an in-memory sorted structure (a balanced tree / skip
   list). Writes are now *memory-speed* — no disk seek in the hot path. This is why writes are so
   cheap.
3. **Flush to an SSTable.** When the memtable fills, it's written out, all at once, as a **Sorted
   String Table (SSTable)** — an immutable file of key→value pairs in sorted order. Because it's
   written sequentially and never modified, this is disk-friendly and lock-free.
4. **Compaction.** Over time you accumulate many SSTables. A background job **merge-sorts** them
   into fewer, larger ones (a merge of sorted runs — `O(n)`, sequential), discarding superseded
   values and expired data. Same idea as Lesson 2's compaction, now keeping sort order.

The genius and the cost, side by side:

- **Writes are cheap and sequential** — an append to the log plus a memory insert. No in-place
  update, no random seek, no read-before-write. This is the whole reason for the throughput.
- **Reads are more expensive than a B-tree** — a key might be in the memtable *or* any of several
  SSTables, so a read may have to check several places. Two optimizations rescue it: each SSTable
  has a **Bloom filter** (a tiny probabilistic structure that answers "this key is *definitely not*
  here" instantly, skipping SSTables that can't contain the key) and a sparse index; and compaction
  keeps the number of SSTables small. This is the fundamental **read-vs-write trade**: B-trees
  optimize reads and pay on writes; LSM-trees optimize writes and pay (a little, cleverly) on reads.
- **Deletes are tombstones** — like Lesson 2, a delete is a marker written forward, and the value
  is really removed only at compaction. (This causes a classic operational trap; see below.)

| | **B-tree** (relational, Phase 3) | **LSM-tree** (wide-column) |
|---|---|---|
| Write | Update in place — random I/O | Append to log + memtable — sequential I/O |
| Read | Fast — one tree descent | Slower — check memtable + N SSTables (+ Bloom filters) |
| Optimized for | Read-heavy, mixed workloads | **Write-heavy** ingest |
| Space | Compact | Amplified until compaction |

That single engine choice is most of why a Cassandra cluster ingests writes at a rate that would
melt a single Postgres primary.

### Tunable consistency: dialing CAP per query

Wide-column stores are distributed and **replicated** — each partition is copied to **N** nodes
(the **replication factor**) so the data survives a machine dying. That raises Lesson 1's CAP
question: when replicas might disagree, does a read see the latest write? Cassandra's answer is
elegant: **you tune it, per operation.** You choose how many replicas must acknowledge a write
(**W**) and how many must respond to a read (**R**):

- If **R + W > N**, the read set and write set are guaranteed to **overlap** on at least one
  replica that has the latest value — you get **strong consistency** for that operation.
- If **R + W ≤ N**, you might read a replica that hasn't caught up — **eventual consistency**, but
  faster and more available.

For example, with `N = 3`: `W = QUORUM (2)` and `R = QUORUM (2)` gives `2 + 2 > 3` → strong. Or
`W = 1, R = 1` → fast, highly available, possibly stale. **The same table can serve both**, chosen
by the query — strong consistency for a password change, eventual for a "seen" marker. This is
CAP made into a dial (with **PACELC** as the fuller framing: even without a partition, you trade
latency vs. consistency — a distributed-systems trade-off).

### The operational failure modes (what bites you in production)

Because the model is so different, its failure modes are specific — and a senior engineer picks
the partition key *to avoid them*:

- **Hot partitions.** If your partition key is low-cardinality or skewed (partition by `country`,
  and 60% of traffic is one country), all that load hammers the few nodes owning those partitions
  while the rest idle. The fix is a high-cardinality, evenly-distributed partition key (often a
  composite one).
- **Unbounded / large partitions.** A partition that grows forever (partition a sensor table by
  `sensor_id` alone, and one sensor runs for years) becomes a giant, slow partition on one node.
  The fix is **bucketing**: add a time bucket to the partition key (`sensor_id + day`) so each
  partition is bounded.
- **Tombstone build-up.** Because deletes are tombstones removed only at compaction, a workload
  that deletes a lot (or uses TTLs heavily) accumulates tombstones that a range read must scan
  *past* — a query reading "live" rows can grind through thousands of dead ones. This is a
  notorious Cassandra gotcha; you design to avoid delete-heavy patterns.

## Think about it

1. A colleague says "we store our sales data in a column store for fast analytics" and another
   says "we use Cassandra, a wide-column store." Are they talking about the same kind of database?
   Explain the difference in one sentence each.
2. You must serve two queries: "messages in a conversation, newest first" and "all messages a user
   sent, newest first." Why does the wide-column model push you to *two tables*, and what is the
   partition key of each?
3. Explain in one sentence why an LSM-tree can absorb writes faster than a B-tree — and name the
   one thing the LSM-tree makes *harder* in exchange, plus the structure that rescues it.
4. With replication factor `N = 3`, you set `W = 2` and `R = 2`. Is a read guaranteed to see the
   latest write? Show the arithmetic. What if you set `W = 1, R = 1`?
5. You partition a metrics table by `sensor_id` alone and, a year later, reads are slow and one
   node is hot. Name the two failure modes at play and the single change to the partition key that
   fixes both.

## Key takeaways

- A **wide-column store** (Cassandra, HBase; from the Bigtable & Dynamo papers) is a *row* store
  that **partitions rows across a cluster** and lets each row hold a different, sparse set of
  columns. It is **not** a columnar analytics store (Parquet/Redshift) — same words, opposite
  purpose.
- Data is addressed by a compound key: the **partition key** picks the *node* (via consistent
  hashing → horizontal scale), the **clustering key** sets the *sort order within a partition* (→
  fast ordered range reads). There are **no joins**.
- You **model queries, not data**: the partition key must hold what you filter by and the
  clustering key must match your ordering — **per access pattern**, so you build **one table per
  query** and write data into each. Duplicating on write is the intended design, not a hack
  (Lesson 7).
- Throughput comes from the **LSM-tree**: append to a commit log + insert into an in-memory
  **memtable**, flush to immutable sorted **SSTables**, **compact** in the background. Writes are
  cheap sequential appends; reads check several SSTables but are rescued by **Bloom filters**. This
  is the **write-optimized** mirror of the B-tree.
- Consistency is **tunable per operation** via replication factor **N** and quorum sizes **R**/
  **W**: `R + W > N` guarantees strong consistency; below it, eventual but faster. Watch the
  signature failure modes — **hot partitions**, **unbounded partitions**, and **tombstone
  build-up** — all avoided by choosing the partition key well.

Next: [Time-Series Databases](../05-time-series-databases/) — take the append-only, write-optimized
idea and specialize it for the one data shape that's exploding everywhere: timestamped points, by
the billion.
