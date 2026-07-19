# Transactions & ACID

> Move $30 from Alice to Bob and the world must never see the money debited-but-not-credited — not for a microsecond, not even if the power fails between the two writes. A transaction is the guarantee that a group of changes happens all the way, or not at all.

**Type:** Build
**Languages:** Python
**Prerequisites:** [How Data Lives on Disk](../08-storage-pages-and-heaps/)
**Time:** ~75 minutes

## The Problem

A bank transfer is two operations: subtract $30 from Alice, add $30 to Bob. Run them as
two independent writes and consider what a crash — or a bug, or a concurrent reader — can do
in the gap between them:

1. Debit Alice ($100 → $70). **← crash here**
2. Credit Bob ($50 → $80). *never happens*

Now $30 has evaporated. The database is in a state that should be *impossible*: money left
one account and arrived nowhere. No individual write was wrong; the problem is that the two
writes needed to be **one indivisible thing**, and nothing made them one.

This is the problem transactions solve. A **transaction** groups a set of operations so the
database treats them as a single, atomic unit: **all of them commit, or none of them do.**
The industry named the four guarantees a transaction provides with the acronym **ACID**, and
they are the reason you can trust a database with money, inventory, and anything else where
"half done" is a catastrophe. This lesson explains all four and builds a small transaction
manager that delivers atomicity, consistency, and durability so you can see them work.

## The Concept

### What a transaction is

A transaction is a unit of work bracketed by a beginning and an ending decision:

```sql
BEGIN;                                    -- start the transaction
UPDATE account SET balance = balance - 30 WHERE name = 'Alice';
UPDATE account SET balance = balance + 30 WHERE name = 'Bob';
COMMIT;                                   -- make all of it permanent, atomically
--   ...or ROLLBACK to throw all of it away as if it never happened
```

Everything between `BEGIN` and `COMMIT` is provisional. **`COMMIT`** is the single atomic
instant where the whole group becomes real and permanent. **`ROLLBACK`** discards the whole
group as though it never started. There is no in-between visible to anyone: the transfer is
either fully done or fully absent.

### ACID: the four guarantees

**ACID** (a term coined by Härder and Reuter in 1983 to name properties reliable systems
already had) stands for **Atomicity, Consistency, Isolation, Durability.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 258" width="100%" style="max-width:680px" role="img" aria-label="A transaction provides four guarantees: Atomicity (all-or-nothing), Consistency (never violates the rules), Isolation (concurrent transactions don't interfere), and Durability (once committed, survives a crash)." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l11a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g fill="none">
  <path d="M340.0 80 L 340.0 118" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M96.0 118 L 577.0 118" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M96.0 118 L 96.0 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11a-ah)"/>
  <path d="M252.0 118 L 252.0 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11a-ah)"/>
  <path d="M411.0 118 L 411.0 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11a-ah)"/>
  <path d="M577.0 118 L 577.0 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11a-ah)"/>
  </g>
  <g>
  <rect x="279.0" y="34" width="122" height="46" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="31.0" y="150" width="130" height="66" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  <rect x="187.0" y="150" width="130" height="66" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="343.0" y="150" width="136" height="66" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="505.0" y="150" width="144" height="66" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="340.0" y="60.9" font-size="11.5" text-anchor="middle" >A transaction</text>
  <text x="96.0" y="178.9" font-size="11.5" text-anchor="middle" font-weight="700" >Atomicity</text>
  <text x="96.0" y="194.9" font-size="10" text-anchor="middle" opacity="0.85" >all-or-nothing</text>
  <text x="252.0" y="170.9" font-size="11.5" text-anchor="middle" font-weight="700" >Consistency</text>
  <text x="252.0" y="186.9" font-size="10" text-anchor="middle" opacity="0.85" >never violates</text>
  <text x="252.0" y="202.9" font-size="10" text-anchor="middle" opacity="0.85" >the rules</text>
  <text x="411.0" y="170.9" font-size="11.5" text-anchor="middle" font-weight="700" >Isolation</text>
  <text x="411.0" y="186.9" font-size="10" text-anchor="middle" opacity="0.85" >concurrent txns</text>
  <text x="411.0" y="202.9" font-size="10" text-anchor="middle" opacity="0.85" >don't interfere</text>
  <text x="577.0" y="170.9" font-size="11.5" text-anchor="middle" font-weight="700" >Durability</text>
  <text x="577.0" y="186.9" font-size="10" text-anchor="middle" opacity="0.85" >once committed,</text>
  <text x="577.0" y="202.9" font-size="10" text-anchor="middle" opacity="0.85" >survives a crash</text>
  </g>
</svg>
```

**Atomicity — all or nothing.** The transaction is indivisible. If any part fails, or you
call `ROLLBACK`, or the machine crashes mid-way, the database guarantees that **none** of
the transaction's changes remain — it's as if `BEGIN` never happened. This is what saves the
transfer: crash after debiting Alice but before crediting Bob, and recovery *undoes* the
debit. The money is never lost because the halfway state is never allowed to persist.

**Consistency — the rules always hold.** A transaction moves the database from one **valid**
state to another valid state, where "valid" means every constraint (Lesson 6) is satisfied.
If a transaction would leave the data violating a rule — a negative balance, a foreign key
pointing at nothing, a broken `CHECK` — the database refuses to commit it and rolls it back.
(Note: this "C" is about *your declared rules*; the database enforces them, but you define
what "valid" means.)

**Isolation — concurrent transactions don't step on each other.** When many transactions run
at once, isolation makes each one behave *as if* it ran alone — a concurrent transaction
shouldn't see another's half-finished work. *How* isolated, and the surprising ways this can
be relaxed for speed, is a big enough topic to be its own lesson (Lesson 12) — for now, hold
"each transaction sees a consistent snapshot, not others' in-progress mess."

**Durability — committed means committed.** Once `COMMIT` returns success, the change
**survives anything** — power loss one nanosecond later, an OS crash, a pulled plug. The
data is safely on disk (or recoverable from a log). Recall from Lesson 8 that a write first
lands in the *volatile* buffer pool; durability is the guarantee that a committed change has
been made permanent despite that. *How* a database achieves durability efficiently — without
flushing the whole database on every commit — is the **write-ahead log** of Lesson 13.

### The commit point: the atomic instant

The linchpin of atomicity and durability is a single moment: the **commit point**. Before
it, the transaction's changes are provisional — held somewhere they can be undone, invisible
to others, and lost harmlessly on a crash. After it, they are permanent and can always be
recovered. The database's whole job is to make crossing that line **atomic**: the commit
either fully happens (and is durable) or hasn't happened at all. There is no torn commit.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 780 336" width="100%" style="max-width:720px" role="img" aria-label="The commit point: from BEGIN, changes are held provisionally (undoable, invisible, a crash is a no-op) up to the COMMIT point; if crossed the changes become permanent and durable, but a crash before it means nothing happened (rolled back)." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l11b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g fill="none">
  <path d="M130.0 151.0 L 147.5 161.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11b-ah)"/>
  <path d="M362.5 161.0 L 400.0 128.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11b-ah)"/>
  <path d="M550.0 128.0 L 597.5 152.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11b-ah)"/>
  <path d="M475.0 176.0 L 475.0 252" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l11b-ah)"/>
  </g>
  <g>
  <rect x="10.0" y="128" width="120" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="147.5" y="128" width="215" height="66" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
  <path d="M475 80.0 L550.0 128 L475 176.0 L400.0 128 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="597.5" y="128" width="165" height="48" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="403.0" y="252" width="144" height="54" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="70.0" y="154.9" font-size="11.5" text-anchor="middle" >BEGIN</text>
  <text x="255.0" y="148.9" font-size="11.5" text-anchor="middle" font-weight="700" >changes held provisionally</text>
  <text x="255.0" y="164.9" font-size="10" text-anchor="middle" opacity="0.85" >(undoable, invisible,</text>
  <text x="255.0" y="180.9" font-size="10" text-anchor="middle" opacity="0.85" >crash = no-op)</text>
  <text x="475" y="124.1" font-size="10.5" text-anchor="middle" >COMMIT</text>
  <text x="475" y="139.1" font-size="10" text-anchor="middle" opacity="0.85" >point</text>
  <text x="680.0" y="155.9" font-size="11.5" text-anchor="middle" >permanent + durable</text>
  <text x="475.0" y="274.9" font-size="11.5" text-anchor="middle" font-weight="700" >nothing happened</text>
  <text x="475.0" y="290.9" font-size="10" text-anchor="middle" opacity="0.85" >(rolled back)</text>
  <text x="573.75" y="110" font-size="9.5" text-anchor="middle" opacity="0.8" >crossed</text>
  <text x="483.0" y="217.0" font-size="9.5" text-anchor="start" opacity="0.8" >crash before</text>
  </g>
</svg>
```

How is that atomic single-instant achieved when a commit touches many pages? By writing an
intention to a log *first* — but that's Lesson 13. Here we build the model: hold changes
aside, apply them together, and only then make them the new truth.

### Build It

We'll build a transaction manager over a small key-value store that delivers three of the
four properties concretely — **atomicity** (all-or-nothing via a held-aside write set),
**consistency** (an invariant checked before commit), and **durability** (committed state
flushed to a file, so it survives "reopening" the database). The core is that a transaction
buffers its writes and the store swaps them in **atomically** only if the invariant holds:

```python
def commit(self, txn):
    # Build the would-be new state WITHOUT mutating the live data yet.
    new_state = {**self._data, **txn.writes}
    self._invariant(new_state)      # consistency: raises if a rule is violated
    self._data = new_state          # atomicity: one swap - all writes or none
    self._flush()                   # durability: committed state hits disk
```

The full manager — `begin`, `read`/`write` against a per-transaction write set, `commit`,
`rollback`, and a reload-from-disk to prove durability — is in
[`code/transactions.py`](code/transactions.py). Run it:

```bash
python transactions.py
```

It runs a **successful transfer** (commit → balances change, total conserved), an
**overdraft transfer** that would break the "no negative balance" invariant (commit refused
→ atomic rollback, Alice *not* debited), and a **simulated crash** mid-transaction (writes
buffered but never committed → reopening the database shows the uncommitted change never
persisted). Three runs, three ACID properties you can watch hold.

### Use It

In a real database you get all four properties by just wrapping your work in a transaction —
and the biggest practical mistake is *forgetting to*:

```sql
BEGIN;
UPDATE account SET balance = balance - 30 WHERE name = 'Alice';
UPDATE account SET balance = balance + 30 WHERE name = 'Bob';
COMMIT;   -- both, atomically and durably; a crash here rolls the whole thing back
```

In application code, use your driver's transaction block so a commit or rollback always
happens (Python: `with connection.transaction():`; most ORMs have an equivalent). Key
production instincts: **keep transactions short** (they hold resources and, per Lesson 12,
locks); **never leave one open** across a network call or user think-time; and **let the
database enforce consistency** with constraints rather than hoping application code checks
every rule. A transaction is the unit of trust — reach for it any time two writes must
succeed or fail together.

## Think about it

1. Walk the transfer crashing *between* the debit and the credit. Which ACID property
   detects and repairs this, and what exactly does recovery do to Alice's balance?
2. Distinguish Atomicity from Durability. Give one failure each is responsible for that the
   other is not.
3. A transaction tries to set a balance to −50, which a `CHECK (balance >= 0)` constraint
   forbids. Which ACID property is engaged, and what happens to the transaction's *other*,
   valid write in the same transaction?
4. Why must committed data survive a crash one nanosecond after `COMMIT` returns — but a
   change made one nanosecond *before* commit may safely vanish? What line separates them?

## Key takeaways

- A **transaction** groups operations into one atomic unit bracketed by `BEGIN` and
  `COMMIT`/`ROLLBACK`: **all commit or none do**, with no visible in-between.
- **ACID**: **Atomicity** (all-or-nothing, crash mid-way undoes everything), **Consistency**
  (commits only if all your constraints still hold), **Isolation** (concurrent transactions
  don't see each other's half-done work — Lesson 12), **Durability** (once committed, it
  survives any crash — Lesson 13).
- The **commit point** is the atomic instant: before it, changes are provisional (undoable,
  invisible, harmless to lose); after it, permanent and recoverable. The database guarantees
  crossing that line is atomic.
- In practice: **wrap multi-write operations in a transaction**, keep transactions **short**,
  never hold one open across user/network waits, and enforce consistency with database
  constraints.

Next: [Isolation, Concurrency & MVCC](../12-isolation-levels-and-mvcc/) — the "I" in ACID up
close: what goes wrong when transactions run at once, and how databases keep them apart.
