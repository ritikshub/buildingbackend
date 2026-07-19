# Capstone: A Mini Relational Engine on a B-Tree

> You've built the pieces — a page store, a B-tree index, a transaction manager, a write-ahead log. A database *is* those pieces, composed. In this capstone we assemble them into one small engine that stores rows, finds them by key, scans them in order, and survives a crash. No frameworks, ~200 lines, and nothing left as magic.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Indexes & the B-Tree](../09-indexes-and-the-btree/) · [Transactions & ACID](../11-transactions-and-acid/) · [Write-Ahead Logging](../13-write-ahead-logging/)
**Time:** ~120 minutes

## The Problem

Across this phase you built a database's organs in isolation: rows in **pages** and a **heap
file** (Lesson 8), a **B-tree** to find them fast (Lesson 9), a **transaction manager** for
all-or-nothing changes (Lesson 11), and a **write-ahead log** for crash-proof durability
(Lesson 13). Each worked on its own bench.

A real database is not those things separately — it's what happens when you **wire them
together** so a single `put` flows through all of them: logged for durability, applied to an
index for fast retrieval, inside a transaction for atomicity. Seeing that composition is the
point of a capstone. It's the difference between knowing the parts and understanding the
machine. So we'll build **MiniDB**: a small but genuinely working storage engine with an
ordered index, transactions, and crash recovery — then crash it and watch it come back
intact. When you finish, "a database" will be a thing you have built, not a black box you
call.

## The Concept

### The architecture of a database engine

Databases are built in **layers**, each depending on the one below. Our MiniDB implements a
vertical slice through the same stack a real engine uses:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 486" width="100%" style="max-width:680px" role="img" aria-label="API layer calls the transaction manager, which fans out to a B-tree index over an in-memory row store and a write-ahead log on a durable disk log." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l16a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="360.0" y="26" text-anchor="middle" font-size="14" font-weight="700">MiniDB — the architecture of a database engine</text>
  <g fill="none">
  <path d="M360.0 100 L 360.0 132" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16a-ah)"/>
  <path d="M360 202 L360 232 L184 232 L184 258" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l16a-ah)"/>
  <path d="M360 202 L360 232 L540 232 L540 258" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l16a-ah)"/>
  <path d="M184.0 316 L 184.0 366" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16a-ah)"/>
  <path d="M540.0 316 L 540 366" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16a-ah)"/>
  </g>
  <g>
  <rect x="288.0" y="48" width="144" height="52" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="256.0" y="132" width="208" height="70" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="91.0" y="258" width="186" height="58" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="450.5" y="258" width="179" height="58" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="101.5" y="366" width="165" height="58" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M486 375 a 54.0 9 0 0 1 108 0 v 78 a 54.0 9 0 0 1 -108 0 Z" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="2"/>
  <path d="M486 375 a 54.0 9 0 0 0 108 0" fill="none" stroke="#e0930f" stroke-width="2"/>
  </g>
  <g>
  <text x="360.0" y="69.9" font-size="11.5" text-anchor="middle" font-weight="700" >API layer</text>
  <text x="360.0" y="85.9" font-size="10" text-anchor="middle" opacity="0.85" >put / get / scan</text>
  <text x="360.0" y="154.9" font-size="11.5" text-anchor="middle" font-weight="700" >Transaction manager</text>
  <text x="360.0" y="170.9" font-size="10" text-anchor="middle" opacity="0.85" >begin / commit / rollback</text>
  <text x="360.0" y="186.9" font-size="10" text-anchor="middle" opacity="0.85" >atomicity</text>
  <text x="184.0" y="282.9" font-size="11.5" text-anchor="middle" font-weight="700" >B-tree index</text>
  <text x="184.0" y="298.9" font-size="10" text-anchor="middle" opacity="0.85" >key → row · range scan</text>
  <text x="540.0" y="282.9" font-size="11.5" text-anchor="middle" font-weight="700" >Write-ahead log</text>
  <text x="540.0" y="298.9" font-size="10" text-anchor="middle" opacity="0.85" >durability &amp; recovery</text>
  <text x="184.0" y="390.9" font-size="11.5" text-anchor="middle" font-weight="700" >In-memory row store</text>
  <text x="184.0" y="406.9" font-size="10" text-anchor="middle" opacity="0.85" >the 'data pages'</text>
  <text x="540.0" y="414.4" font-size="11.5" text-anchor="middle" font-weight="700" >Durable log</text>
  <text x="540.0" y="430.4" font-size="10" text-anchor="middle" opacity="0.85" >on disk</text>
  </g>
  <text x="360.0" y="474" text-anchor="middle" font-size="11" opacity="0.9">Layers, each depending on the one below — the essential spine of a database.</text>
</svg>
```

Compared to Postgres we're deliberately leaving things out — no SQL parser (we call methods
directly), no on-disk paging of the index (it lives in memory, rebuilt from the log on
startup), no MVCC or concurrent transactions (Lesson 12), no query planner (Lesson 10). What
we keep is the **essential spine**: **durability via WAL, atomicity via transactions, and
fast ordered access via a B-tree.** That spine is what makes it a database rather than a dict.

### How a write flows through the layers

Trace a single committed `put` and you can see every lesson doing its job in sequence:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1050 180" width="100%" style="max-width:760px" role="img" aria-label="A put buffers in the transaction, then commit appends put and commit records to the WAL and fsyncs, then applies to the B-tree index, becoming visible to get and scan." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l16b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="525.0" y="26" text-anchor="middle" font-size="14" font-weight="700">How a committed write flows through the layers</text>
  <g fill="none">
  <path d="M162.5 98.0 L 192.5 98.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16b-ah)"/>
  <path d="M343.5 98.0 L 373.5 98.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16b-ah)"/>
  <path d="M503.5 98.0 L 533.5 98.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16b-ah)"/>
  <path d="M705.5 98.0 L 735.5 98.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16b-ah)"/>
  <path d="M871.5 98.0 L 901.5 98.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l16b-ah)"/>
  </g>
  <g>
  <rect x="18.5" y="65.0" width="144" height="66" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="192.5" y="65.0" width="151" height="66" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="373.5" y="65.0" width="130" height="66" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="533.5" y="65.0" width="172" height="66" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="735.5" y="65.0" width="136" height="66" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="901.5" y="65.0" width="130" height="66" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="90.5" y="101.9" font-size="11.5" text-anchor="middle" >txn.put(id, row)</text>
  <text x="268.0" y="93.9" font-size="11.5" text-anchor="middle" font-weight="700" >buffered in txn</text>
  <text x="268.0" y="109.9" font-size="10" text-anchor="middle" opacity="0.85" >(not yet visible)</text>
  <text x="438.5" y="101.9" font-size="11.5" text-anchor="middle" >commit</text>
  <text x="619.5" y="85.9" font-size="11.5" text-anchor="middle" font-weight="700" >1. WAL append</text>
  <text x="619.5" y="101.9" font-size="10" text-anchor="middle" opacity="0.85" >put + commit, fsync</text>
  <text x="619.5" y="117.9" font-size="10" text-anchor="middle" opacity="0.85" >durable commit point</text>
  <text x="803.5" y="85.9" font-size="11.5" text-anchor="middle" font-weight="700" >2. apply to</text>
  <text x="803.5" y="101.9" font-size="10" text-anchor="middle" opacity="0.85" >B-tree index</text>
  <text x="803.5" y="117.9" font-size="10" text-anchor="middle" opacity="0.85" >findable by key</text>
  <text x="966.5" y="93.9" font-size="11.5" text-anchor="middle" font-weight="700" >visible to</text>
  <text x="966.5" y="109.9" font-size="10" text-anchor="middle" opacity="0.85" >get() &amp; scan()</text>
  </g>
  <text x="525.0" y="168" text-anchor="middle" font-size="11" opacity="0.9">The write-ahead rule: log first (durable, atomic commit point), then apply to the index (findable).</text>
</svg>
```

The ordering is the whole game and it's exactly the write-ahead rule: **log first, then
apply.** If the process dies after step 1 but before step 2, recovery replays the log and
redoes the apply — the commit is durable. If it dies *before* step 1's commit record, the
transaction had no durable commit point, so recovery drops it — the change atomically vanishes.
Durability and atomicity fall out of the layering, not from any extra machinery.

### Reads and recovery

A **read** (`get`, `scan`) just walks the B-tree — `get` searches for a key in a handful of
node hops (Lesson 9's shallow tree), `scan` walks the tree in order to return a sorted range,
which is exactly what an ordered index is for. No log involved; reads see whatever the index
holds.

**Recovery** on startup is the mirror of the write path: read the whole WAL, find which
transactions have a commit record, and rebuild the B-tree by applying every committed `put`
in order (last write wins). Uncommitted transactions are simply never applied. The index is a
*derived* structure — the log is the source of truth — so a crash can never leave the index
and the durable state disagreeing: we just rebuild the index from the log.

### Build It

MiniDB composes three components you've already built the ideas for:

1. A **B-tree** (from Lesson 9, extended with `set`/upsert and an in-order `range`) as the
   primary index: key → row, kept sorted for fast lookup and range scans.
2. A **WAL** (from Lesson 13): every committed write is logged and `fsync`'d before it's
   applied; recovery replays it.
3. A **transaction manager** (from Lesson 11): writes buffer until commit, then hit the log
   and the index atomically; rollback throws the buffer away.

The heart is `commit`, where the layers meet — log-and-fsync, *then* apply to the index:

```python
def commit(self):
    for key, row in self.writes:                     # 1. WAL: log the intent...
        self.db._log({"t": self.tid, "op": "put", "k": key, "v": row})
    self.db._log({"t": self.tid, "op": "commit"})
    self.db._sync()                                  #    ...fsync = durable commit point
    for key, row in self.writes:                     # 2. index: now make it findable
        self.db.index.set(key, row)
```

The full engine — the B-tree, the WAL with recovery, `begin`/`put`/`commit`/`rollback`, and
`get`/`scan` — is in [`code/minidb.py`](code/minidb.py). Run it:

```bash
python minidb.py
```

It inserts rows in a transaction and commits, reads one back **by key**, does an ordered
**range scan**, shows a **rollback** leaving no trace, updates a row (upsert through the same
key), then **simulates a crash** — logging a transaction's writes with no commit — and
**restarts**, rebuilding the index from the WAL so committed rows survive (in order) and the
uncommitted one is gone. Every ACID property you studied, in one running program.

### Use It

MiniDB is a teaching engine, so the "Use It" here is *seeing your engine's DNA in a real one*.
Everything you built maps directly onto production databases:

- **SQLite** is astonishingly close to MiniDB's shape — a single file, a B-tree per table, a
  WAL mode for durability — just vastly more complete (a full SQL parser, real on-disk paging,
  types, constraints). Reading the SQLite architecture docs after this lesson is a revelation:
  you'll recognize the pieces.
- **Postgres** adds everything we skipped — the query planner (Lesson 10), MVCC and concurrent
  transactions (Lesson 12), on-disk pages and a buffer pool (Lesson 8), rich types and
  constraints (Lessons 4–6) — but the spine is identical: a B-tree access method over pages,
  transactions, and a write-ahead log.
- The gaps you feel in MiniDB *are* the rest of a database course: concurrency control,
  buffer management, the SQL layer, replication (which, recall from Lesson 13, is just the WAL
  streamed to a replica). You now have the map.

You will almost certainly never ship a database engine. But having built one, you'll debug,
tune, and reason about the ones you *do* ship from the inside out — which is exactly the point
of building things from scratch.

## Think about it

1. Trace a committed `put` through MiniDB's layers and name the lesson each step comes from.
   At which exact instant does the write become durable, and at which does it become
   *findable*?
2. The process crashes after a commit record is `fsync`'d but before the B-tree is updated.
   Walk what recovery does and why the row is still there afterward. Which two ACID properties
   did the layering deliver for free?
3. MiniDB rebuilds its whole index from the WAL on startup. What real-database feature (from
   Lesson 13) would you add so recovery doesn't have to replay the *entire* log every time?
4. Name three things Postgres has that MiniDB doesn't, and for each, say which earlier lesson
   in this phase covers it.

## Key takeaways

- A database engine is built in **layers** — API → transactions → access method (B-tree) +
  WAL → storage — and MiniDB is a working vertical slice through that stack.
- A committed write flows **buffer → WAL (log + fsync) → index apply**: logging first makes the
  commit **durable and atomic** (the commit point), then applying to the **B-tree** makes it
  **findable** and **ordered** — durability and atomicity emerge from the layering itself.
- **Reads** walk the B-tree (`get` = search, `scan` = ordered range); **recovery** rebuilds
  the index by replaying committed writes from the WAL, so the derived index can never
  disagree with the durable truth.
- The pieces you built are the real spine of **SQLite and Postgres**; the parts MiniDB omits —
  a SQL planner, MVCC/concurrency, on-disk paging, replication — are precisely the rest of the
  database curriculum, and you now have the map to all of it.

This is the end of Phase 3. You started with a program's data vanishing on exit and ended
having built the machine that keeps it — durable, queryable, concurrent, and consistent. Next
comes [Phase 4 — NoSQL and Data Modeling](../../04-nosql-and-data-modeling/), where you'll see
what the relational model gives up, and what you gain, when the data's shape calls for
something else.
