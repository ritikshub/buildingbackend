# Isolation, Concurrency & MVCC

> Run one transaction and everything is simple. Run a thousand at once and they start reading each other's half-finished work, overwriting each other, and seeing the database change underfoot. Isolation is the dial that controls how much of that chaos leaks through — and it's a dial, not a switch, because the top setting isn't free.

**Type:** Learn
**Languages:** —
**Prerequisites:** [Transactions & ACID](../11-transactions-and-acid/)
**Time:** ~60 minutes

## The Problem

The "I" in ACID (Lesson 11) promised that concurrent transactions "don't step on each
other." That was a comforting simplification. The truth is that perfect isolation — every
transaction behaving *exactly* as if it were the only one running — is expensive, because it
forces transactions to wait for each other. So real databases offer a **spectrum** of
isolation, and they let you choose where to sit on it, trading correctness against
concurrency.

To choose well you have to know what breaks at each setting. When two transactions overlap
in time and touch the same data, specific, named things can go wrong — a transaction reading
data that was never really committed, or getting two different answers to the same question
seconds apart. These are the **read phenomena**, and the **isolation levels** are defined
precisely by which of them they permit. This lesson is those phenomena, the four levels, and
the clever mechanism — **MVCC** — that lets modern databases give strong isolation without
grinding to a halt.

## The Concept

### The read phenomena: what concurrency breaks

The SQL standard defines the anomalies that can occur when transactions interleave. Three
are core:

**Dirty read** — a transaction reads another transaction's **uncommitted** change, which may
then be rolled back. You made a decision based on data that never really existed.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 356" width="100%" style="max-width:680px" role="img" aria-label="Sequence diagram of a dirty read: T1 updates balance to 0 without committing; T2 reads balance and sees 0; T1 rolls back so balance was never 0; T2 acted on data that never existed." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l12a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="340.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Dirty read — T2 reads T1's uncommitted change</text>
  <g fill="none">
  <path d="M100 92 L 100 336" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5"/>
  <path d="M340 92 L 340 300" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5"/>
  <path d="M570 98 L 570 336" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5"/>
  <path d="M100 132 L 570 132" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l12a-ah)"/>
  <path d="M340 190 L 570 190" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l12a-ah)"/>
  <path d="M100 248 L 570 248" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l12a-ah)"/>
  </g>
  <g>
  <rect x="65" y="52" width="70" height="40" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="305" y="52" width="70" height="40" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M530 59 a 40.0 9 0 0 1 80 0 v 30 a 40.0 9 0 0 1 -80 0 Z" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="2"/>
  <path d="M530 59 a 40.0 9 0 0 0 80 0" fill="none" stroke="#e0930f" stroke-width="2"/>
  <rect x="210" y="288" width="260" height="44" rx="7" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="100.0" y="67.9" font-size="11.5" text-anchor="middle" font-weight="700" >T1</text>
  <text x="100.0" y="83.9" font-size="10" text-anchor="middle" opacity="0.85" >txn</text>
  <text x="340.0" y="67.9" font-size="11.5" text-anchor="middle" font-weight="700" >T2</text>
  <text x="340.0" y="83.9" font-size="10" text-anchor="middle" opacity="0.85" >txn</text>
  <text x="570.0" y="82.4" font-size="11.5" text-anchor="middle" >DB</text>
  <text x="335.0" y="123" font-size="10" text-anchor="middle" opacity="0.8" >UPDATE balance = 0  (not committed)</text>
  <text x="455.0" y="181" font-size="10" text-anchor="middle" opacity="0.8" >READ balance → 0  (dirty! sees uncommitted)</text>
  <text x="335.0" y="239" font-size="10" text-anchor="middle" opacity="0.8" >ROLLBACK  (balance was never 0)</text>
  <text x="340.0" y="313.6" font-size="10.5" text-anchor="middle" >T2 acted on data that never existed</text>
  </g>
</svg>
```

**Non-repeatable read** — a transaction reads a row, and when it reads the **same row**
again, the value has changed because another transaction committed an update in between. The
same question gives two different answers within one transaction.

**Phantom read** — a transaction runs a query (say, "all orders over $100"), and when it
runs the **same query** again, new rows have appeared or vanished because another transaction
committed an insert or delete. Not a changed row — a changed *set* of rows.

Two more worth naming: a **lost update** (two transactions read a value, both modify it, and
one overwrites the other's change), and **write skew** (two transactions each read an
overlapping set, make disjoint writes that are each fine alone but together violate an
invariant — the subtle one that only the strongest level prevents).

### The four isolation levels

The SQL-92 standard defines four levels, each permitting fewer phenomena as you climb — and
demanding more of the database (more waiting, or more aborts) to deliver:

| Isolation level | Dirty read | Non-repeatable read | Phantom read |
|---|---|---|---|
| **Read Uncommitted** | possible | possible | possible |
| **Read Committed** | prevented | possible | possible |
| **Repeatable Read** | prevented | prevented | possible* |
| **Serializable** | prevented | prevented | prevented |

- **Read Uncommitted** — the weakest; allows even dirty reads. Rarely useful; some databases
  (like Postgres) don't even implement it as distinct from the next level up.
- **Read Committed** — you only ever see **committed** data, but each *statement* gets a
  fresh view, so values and result sets can change between statements in your transaction.
  This is the **default in Postgres and Oracle**, and it's the right default for most
  applications.
- **Repeatable Read** — every read in the transaction sees the **same snapshot** taken at the
  start, so a row you read twice reads the same both times. (*The standard still permits
  phantoms here; Postgres's implementation actually prevents them too, via snapshots — a
  common point of confusion.*)
- **Serializable** — the strongest: the result is guaranteed to be *as if* the transactions
  ran one after another in some serial order. No anomaly of any kind, including write skew.
  The cost is that the database may have to **abort** a transaction that would violate
  serializability, and your application must **retry** it.

The governing trade-off: **higher isolation buys correctness with concurrency.** The top of
the ladder eliminates every anomaly but makes transactions wait on or abort each other; the
bottom lets more run simultaneously but exposes you to the phenomena. You climb only as high
as your correctness needs demand.

### How isolation is enforced: locking vs. MVCC

There are two broad strategies for delivering isolation, and the difference defines how a
database *feels* under load.

**Locking (pessimistic).** Before touching data, a transaction acquires a **lock** — a
*shared* lock to read, an *exclusive* lock to write — and holds it until commit (a protocol
called **two-phase locking**, 2PL). Locks prevent conflicts by making transactions **wait**:
a writer blocks readers, readers block writers. Correct, but concurrency suffers, and it
introduces **deadlocks** (two transactions each waiting on a lock the other holds — the
database detects this and aborts one).

**MVCC — Multi-Version Concurrency Control (optimistic-ish).** Instead of locking readers
out, the database keeps **multiple versions** of each row. When a transaction updates a row,
it doesn't overwrite it — it writes a **new version**, leaving the old one in place. Each
version is stamped with the transaction that created it, and each transaction reads from a
**snapshot** that shows it only the versions that were committed as of its start. The famous
consequence:

> **Readers never block writers, and writers never block readers.**

A long analytics query reading millions of rows sees a stable, consistent snapshot and never
blocks the transactions busily updating those same rows — they're just creating new versions
alongside the ones the query is reading. This is why MVCC is used by **Postgres, MySQL's
InnoDB, and Oracle**: it delivers strong isolation with far more concurrency than pure
locking.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 320" width="100%" style="max-width:700px" role="img" aria-label="MVCC versions of row balance: v1=100 by txn 10, superseded by v2=70 by txn 25, superseded by v3=80 by txn 42. A snapshot from txn 15 sees v1; a snapshot from txn 30 sees v2." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l12b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="350.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Row 'balance' — MVCC keeps every version over time</text>
  <g fill="none">
  <path d="M210 118.0 L 275 118.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l12b-ah)"/>
  <path d="M425 118.0 L 490 118.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l12b-ah)"/>
  <path d="M135.0 236 L 135.0 145" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#l12b-ah)"/>
  <path d="M350.0 236 L 350.0 145" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#l12b-ah)"/>
  </g>
  <g>
  <rect x="60" y="91" width="150" height="54" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="275" y="91" width="150" height="54" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="490" y="91" width="150" height="54" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="53.0" y="236" width="164" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="268.0" y="236" width="164" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="135.0" y="113.9" font-size="11.5" text-anchor="middle" font-weight="700" >v1 = 100</text>
  <text x="135.0" y="129.9" font-size="10" text-anchor="middle" opacity="0.85" >txn 10 (created)</text>
  <text x="350.0" y="113.9" font-size="11.5" text-anchor="middle" font-weight="700" >v2 = 70</text>
  <text x="350.0" y="129.9" font-size="10" text-anchor="middle" opacity="0.85" >txn 25 (updated)</text>
  <text x="565.0" y="113.9" font-size="11.5" text-anchor="middle" font-weight="700" >v3 = 80</text>
  <text x="565.0" y="129.9" font-size="10" text-anchor="middle" opacity="0.85" >txn 42 (updated)</text>
  <text x="565.0" y="74" font-size="9" text-anchor="middle" opacity="0.7" >current</text>
  <text x="135.0" y="254.6" font-size="10.5" text-anchor="middle" font-weight="700" >Snapshot @ txn 15</text>
  <text x="135.0" y="270.6" font-size="10" text-anchor="middle" opacity="0.85" >sees v1</text>
  <text x="350.0" y="254.6" font-size="10.5" text-anchor="middle" font-weight="700" >Snapshot @ txn 30</text>
  <text x="350.0" y="270.6" font-size="10" text-anchor="middle" opacity="0.85" >sees v2</text>
  </g>
  <text x="350.0" y="308" text-anchor="middle" font-size="11" opacity="0.9">Each snapshot sees the newest version committed before that transaction started.</text>
</svg>
```

Each transaction, looking at its snapshot, sees the row *as of the moment it started*. This
is **snapshot isolation**, and it's how Repeatable Read is implemented in practice.

### The cost of MVCC: dead versions and vacuum

Keeping old versions isn't free. Every update leaves an old row version behind, and deletes
just mark a version as gone — so the table accumulates **dead versions** that are no longer
visible to any transaction. (This is the deeper reason a row's `ctid` from Lesson 8 changes
on update: an update writes a new physical version elsewhere.) Left unchecked, these dead
versions **bloat** the table and its indexes. So MVCC databases run a background cleanup —
Postgres calls it **`VACUUM`** — that reclaims space from versions no transaction can see
anymore. Understanding this demystifies two common production sights: tables that grow even
under steady state, and the `autovacuum` process working to keep them in check.

### Choosing a level in practice

- **Default to Read Committed.** It prevents dirty reads and is a sensible baseline for the
  vast majority of application queries.
- **Reach for Repeatable Read / Snapshot** when a transaction reads the same data multiple
  times and needs a stable view — reports, multi-step calculations, anything that must not
  see the data shift underfoot.
- **Use Serializable** for correctness-critical invariants that span multiple rows (financial
  postings, inventory that must never oversell, the write-skew cases) — and be ready to
  **catch serialization failures and retry** the transaction.
- **Guard against lost updates** with `SELECT ... FOR UPDATE` (take an explicit lock on the
  rows you'll modify) or optimistic concurrency (a version column checked on write) — a
  read-modify-write under Read Committed is otherwise a classic bug.

The instinct to build: isolation level is a **deliberate choice per transaction**, matched to
what that transaction must guarantee — not a global setting you pick once and forget.

## Think about it

1. Two operators both open the "edit product price" screen (reading $10), each change it,
   and each save. Under Read Committed with a naive read-modify-write, what anomaly occurs,
   and what one clause or technique prevents it?
2. A 30-second analytics query runs while thousands of updates hit the same rows. Under MVCC,
   why does the query neither block the updates nor block *on* them — and what does the query
   actually see?
3. Your database is Serializable and the app occasionally gets "could not serialize access"
   errors. Is this a bug? What must the application be built to do?
4. Explain, using MVCC versions, why a heavily-updated Postgres table can grow on disk even
   when the row *count* is stable — and what process reclaims the space.

## Key takeaways

- Concurrent transactions can suffer named **read phenomena**: **dirty reads** (seeing
  uncommitted data), **non-repeatable reads** (a row changes between reads), and **phantom
  reads** (a query's result set changes) — plus lost updates and write skew.
- The four **isolation levels** — Read Uncommitted, **Read Committed** (the common default),
  Repeatable Read, **Serializable** — each permit fewer phenomena, trading **concurrency for
  correctness** as you climb.
- Isolation is enforced by **locking** (transactions wait on each other; risks deadlocks) or
  **MVCC**, which keeps **multiple row versions** so **readers don't block writers and
  writers don't block readers**, each transaction reading a consistent **snapshot**.
- MVCC's cost is **dead versions** that bloat tables and indexes, reclaimed by background
  cleanup (Postgres **`VACUUM`**) — and it's why a row's physical identity changes on update.
- Choose the level **per transaction**: Read Committed by default, higher when a transaction
  needs a stable view or a multi-row invariant, and **retry** on serialization failures.

Next: [Durability: Write-Ahead Logging](../13-write-ahead-logging/) — the "D" in ACID up
close: how a database makes a committed change survive a crash without flushing everything to
disk on every commit.
