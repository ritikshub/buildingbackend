# Durability: Write-Ahead Logging

> How does `COMMIT` make a change survive a crash *one nanosecond later*, without slowly writing every modified page to its final home on disk first? By writing the *intent* to a sequential log and flushing that — a trick that is both faster and safer than touching the data itself. This is the engine under the "D" in ACID.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Transactions & ACID](../11-transactions-and-acid/) · [How Data Lives on Disk](../08-storage-pages-and-heaps/)
**Time:** ~90 minutes

## The Problem

Lesson 11 promised durability: once `COMMIT` returns, the change survives any crash. Lesson
8 showed why that's hard — a write first lands in the *volatile* buffer pool, and the data
pages on disk are updated later. So the naïve way to make a commit durable is: **on commit,
write every page this transaction modified to its final location on disk, right now.** It
works, but it's terrible on two counts:

- **It's slow.** A transaction might touch pages scattered all over the data file. Writing
  them means many **random** disk writes — the slowest thing a disk does (Lesson 1) — on the
  critical path of every commit.
- **It's not even safe.** Suppose a commit must update three pages and the power dies after
  writing two. Now the data file is *partially* updated — a **torn write** — and there's no
  record of what the third page should have been. The database is corrupt, and worse, it
  doesn't know it.

So the naïve approach makes commits both slow and fragile. The solution, used by essentially
every durable database — Postgres, MySQL/InnoDB, SQLite — is beautifully counterintuitive:
**don't write the data pages on commit at all. Write a small note describing the change to a
sequential log, flush *that*, and update the data pages lazily, later.** That's **write-ahead
logging (WAL)**, and this lesson builds one that survives a crash.

## The Concept

### The write-ahead rule

The entire idea is one rule:

> **Before a change is written to the data pages on disk, a record describing that change
> must first be written — and flushed — to the log.**

Log the intent *before* you do the deed. The log is a separate, **append-only** file. When a
transaction modifies data, the database first appends a **log record** — "transaction 42 set
`balance` to 80" — to the log. A transaction is **committed** the instant its **commit
record** is safely flushed (`fsync`'d) to the log. The actual data pages in the buffer pool
can be written to their final homes on disk **whenever** afterward — at leisure, in the
background. The log, not the data file, is the source of durable truth.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 470" width="100%" style="max-width:560px" role="img" aria-label="Write-ahead logging sequence: a transaction changes a row; step 1 append a change record to the WAL; step 2 fsync the WAL, which is the commit point; COMMIT returns success; step 3 the data pages are flushed to disk later in the background." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l13a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="320.0" y="26" text-anchor="middle" font-size="14" font-weight="700">The write-ahead rule</text>
  <g fill="none">
  <path d="M300.0 104 L 300.0 126" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13a-ah)"/>
  <path d="M300.0 178 L 300.0 200" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13a-ah)"/>
  <path d="M300.0 252 L 300.0 274" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13a-ah)"/>
  <path d="M300.0 326 L 300.0 348" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13a-ah)"/>
  </g>
  <g>
  <rect x="175.0" y="52" width="250" height="52" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="175.0" y="126" width="250" height="52" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="175.0" y="200" width="250" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="175.0" y="274" width="250" height="52" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  <rect x="175.0" y="348" width="250" height="52" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="300.0" y="81.9" font-size="11.5" text-anchor="middle" >Transaction changes a row</text>
  <text x="300.0" y="147.9" font-size="11.5" text-anchor="middle" font-weight="700" >1. Append change record</text>
  <text x="300.0" y="163.9" font-size="10" text-anchor="middle" opacity="0.85" >to the WAL (append-only)</text>
  <text x="300.0" y="221.9" font-size="11.5" text-anchor="middle" font-weight="700" >2. fsync the WAL</text>
  <text x="300.0" y="237.9" font-size="10" text-anchor="middle" opacity="0.85" >← the durable commit point</text>
  <text x="300.0" y="303.9" font-size="11.5" text-anchor="middle" >COMMIT returns success</text>
  <text x="300.0" y="369.9" font-size="11.5" text-anchor="middle" font-weight="700" >3. Data pages → disk LATER</text>
  <text x="300.0" y="385.9" font-size="10" text-anchor="middle" opacity="0.85" >(background, at leisure)</text>
  </g>
</svg>
```

### Why this is faster *and* safer

The same design fixes both of the naïve approach's problems at once:

- **Faster**, because the log is written **sequentially**. Instead of scattering random
  writes across the data file, a commit appends a few small records to the end of one file
  and issues **one `fsync`**. Sequential writes are dramatically faster than random ones, and
  many databases batch concurrent commits into a single `fsync` (**group commit**) for even
  more throughput. The expensive random data-page writes move *off* the commit path.
- **Safer**, because the log makes recovery deterministic. The commit record is a single
  small write that is either fully in the log or not — there's no "torn commit." And every
  change is described in the log before it touches the data file, so after a crash the
  database can always reconstruct the correct state (next section). A half-written data page
  is no longer fatal, because the log knows what it *should* contain.

### Crash recovery: redo and undo

After a crash, the data file may be missing recently-committed changes (they were only in the
log and hadn't been flushed to their pages yet) and may contain changes from transactions
that never committed. Recovery uses the log to fix both, in the spirit of the classic
**ARIES** algorithm (Mohan et al., 1992):

- **REDO** — replay the log forward, re-applying the changes of every transaction that has a
  **commit record**. This restores committed changes that hadn't yet reached the data pages.
  *This is what makes commits durable:* the change was in the log, so it survives.
- **UNDO** — roll back any changes from transactions that were in progress but have **no
  commit record** (they were interrupted by the crash). *This is what makes atomicity
  crash-safe* (Lesson 11): a half-done transaction leaves no trace.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 510" width="100%" style="max-width:700px" role="img" aria-label="Crash recovery flow: on crash and restart, scan the WAL; for each transaction, is there a commit record? If yes, REDO its changes for durability so committed work survives. If no, UNDO or discard its changes for atomicity so partial work vanishes. Both paths lead to a consistent state restored." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l13b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="360.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Crash recovery — REDO the committed, UNDO the rest</text>
  <g fill="none">
  <path d="M360.0 90 L 360.0 118" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13b-ah)"/>
  <path d="M360.0 162 L 360 188.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l13b-ah)"/>
  <path d="M225.0 240 L185.0 240 L185.0 332" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l13b-ah)"/>
  <path d="M495.0 240 L535.0 240 L535.0 332" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l13b-ah)"/>
  <path d="M185.0 392 L185.0 428 L360 428 L360 452" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l13b-ah)"/>
  <path d="M535.0 392 L535.0 428 L360 428 L360 452" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l13b-ah)"/>
  </g>
  <g>
  <rect x="288.0" y="46" width="144" height="44" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="300.0" y="118" width="120" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M360 188.0 L495.0 240 L360 292.0 L225.0 240 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="70" y="332" width="230" height="60" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="420" y="332" width="230" height="60" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="256.0" y="452" width="208" height="44" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="360.0" y="71.9" font-size="11.5" text-anchor="middle" >Crash! — restart</text>
  <text x="360.0" y="143.9" font-size="11.5" text-anchor="middle" >Scan the WAL</text>
  <text x="360" y="236.1" font-size="10.5" text-anchor="middle" >For each transaction —</text>
  <text x="360" y="251.1" font-size="10" text-anchor="middle" opacity="0.85" >commit record?</text>
  <text x="185.0" y="357.6" font-size="10.5" text-anchor="middle" font-weight="700" >REDO its changes</text>
  <text x="185.0" y="373.6" font-size="10" text-anchor="middle" opacity="0.85" >durability: work survives</text>
  <text x="535.0" y="357.6" font-size="10.5" text-anchor="middle" font-weight="700" >UNDO / discard changes</text>
  <text x="535.0" y="373.6" font-size="10" text-anchor="middle" opacity="0.85" >atomicity: work vanishes</text>
  <text x="205.0" y="234" font-size="9.5" text-anchor="middle" opacity="0.8" >yes</text>
  <text x="515.0" y="234" font-size="9.5" text-anchor="middle" opacity="0.8" >no</text>
  <text x="360.0" y="477.9" font-size="11.5" text-anchor="middle" >Consistent state restored</text>
  </g>
</svg>
```

When the dust settles, the database is in exactly the state where every committed transaction
is applied and every uncommitted one is gone — precisely the atomicity and durability ACID
promised.

### Checkpoints: so recovery isn't infinite

If recovery had to replay the log from the very beginning of time, it would take longer and
longer as the log grew. So the database periodically performs a **checkpoint**: it flushes
all dirty buffer-pool pages to the data file and records, in the log, "everything up to here
is safely in the data file." Recovery then only needs to replay the log **from the last
checkpoint forward**, not from the dawn of the database. Checkpoints also let the database
**recycle** old log segments that are no longer needed for recovery, so the log doesn't grow
without bound.

### Build It

We'll build a WAL-backed key-value store and then *crash* it. The store appends every change
to a log file, marks a transaction committed only when its commit record is `fsync`'d, and
recovers by replaying the log — redoing committed transactions and dropping uncommitted ones.
Recovery is the whole point, and it's tiny:

```python
def recover(wal_path):
    """Rebuild state from the log: apply only the writes of committed transactions."""
    records = [json.loads(line) for line in open(wal_path)]
    committed = {r["t"] for r in records if r["op"] == "commit"}   # who committed?
    data = {}
    for r in records:
        if r["op"] == "set" and r["t"] in committed:  # REDO committed writes...
            data[r["k"]] = r["v"]                      # ...UNDO uncommitted by omission
    return data
```

The full store — appending `set` and `commit` records, `fsync` at the commit point, a
simulated crash that logs a transaction's writes but dies before its commit record, and a
restart that recovers from the log — is in [`code/wal.py`](code/wal.py). Run it:

```bash
python wal.py
```

It commits some transfers, prints the raw append-only log so you can see the intent recorded
before the deed, then simulates a crash mid-transaction and **restarts** — showing that
committed changes survive (redo) while the interrupted transaction leaves no trace (undo).
That's durability and crash-safe atomicity, built from one append-only file.

### Use It

You never write WAL records by hand — but the WAL is the most important file in a production
database, and its existence explains a lot:

- **Postgres** stores WAL segments under `pg_wal/`; `fsync` and `wal_level` settings tune the
  durability/performance trade; a `CHECKPOINT` command forces the flush described above.
- **Crash recovery is automatic**: start Postgres after a crash and it replays WAL from the
  last checkpoint before accepting connections — the redo/undo you just built.
- **Replication is the WAL, streamed.** A replica stays in sync by receiving and replaying
  the primary's WAL records — the same log that provides durability also provides
  replication and point-in-time recovery.
- The classic durability knob, **`fsync = off`**, makes commits faster by *not* flushing the
  log — and turns a crash into data loss. Now you know exactly what it's trading away.

Because you built the redo/undo loop, "the database recovered by replaying the write-ahead
log" is a sentence you can see the machinery behind.

## Think about it

1. Why is appending a record to a sequential log and calling `fsync` once dramatically faster
   than writing several modified data pages to their scattered final locations on commit?
2. A commit writes its log record and `fsync`s it, then the power dies *before* any data page
   is updated. Is the transaction durable? Walk what recovery does.
3. A transaction logs two `set` records, then the process is killed before the commit record.
   What does recovery do with those two writes, and which ACID property is that?
4. Without checkpoints, what happens to crash-recovery time as a long-running database's log
   grows — and how does a checkpoint bound it?

## Key takeaways

- Writing modified **data pages** to disk on every commit is slow (random writes) and unsafe
  (torn writes corrupt the file). **Write-ahead logging** avoids both.
- The **write-ahead rule**: append a record describing a change to a sequential, append-only
  **log**, and flush it, *before* the data pages change. A transaction is **committed** when
  its **commit record** is `fsync`'d — the durable commit point. Data pages flush lazily,
  later.
- It's **faster** (one sequential `fsync`, off the random-write path; group commit) and
  **safer** (deterministic recovery, no torn commit).
- **Crash recovery** replays the log: **REDO** committed transactions (durability) and
  **UNDO** uncommitted ones (crash-safe atomicity) — restoring exactly the ACID state.
- **Checkpoints** flush dirty pages and mark a safe point so recovery replays only from
  there, bounding recovery time and letting old log segments be recycled. In production the
  WAL also powers **replication** and point-in-time recovery.

Next: [Connection Pooling & the N+1 Problem](../14-connection-pooling-and-n-plus-1/) — from
the storage engine back up to how your application talks to the database efficiently.
