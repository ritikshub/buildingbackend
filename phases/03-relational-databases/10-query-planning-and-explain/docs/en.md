# How Queries Run: The Planner & EXPLAIN

> You tell SQL *what* you want, never *how* to get it. Something has to decide the how — and that something, the query planner, can make the same query run in a millisecond or a minute. Learning to read its mind (via `EXPLAIN`) is the single highest-leverage database skill.

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [Indexes & the B-Tree](../09-indexes-and-the-btree/)
**Time:** ~75 minutes

## The Problem

SQL is **declarative** (Lesson 3): `SELECT * FROM orders WHERE user_id = 42` describes a
result, not a procedure. It says nothing about *how* to find those rows — scan the whole
table? use an index? which index? if there's a join, which table first? Every one of those
choices exists, and the difference between the best and worst is often **thousands of
times** in speed on the same data.

So who chooses? Not you, and not the storage engine — a dedicated component called the
**query planner** (or optimizer). It takes your declarative query and compiles it into a
concrete **execution plan**: a specific sequence of scans, index lookups, and joins. When a
query is mysteriously slow, the answer is almost never "the database is slow" — it's "the
planner chose a plan you didn't expect, for a reason you can see." This lesson is how the
planner thinks and how to read its decisions with `EXPLAIN`, the tool you'll reach for every
time a query misbehaves for the rest of your career. (We stay light on SQL syntax — the
point is the *machinery*, not the language.)

## The Concept

### The life of a query

Between your SQL text and the rows coming back, a query passes through four stages:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 150" width="100%" style="max-width:760px" role="img" aria-label="The life of a query: SQL text flows through parser, rewriter, planner/optimizer, and executor to produce rows." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l10a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g fill="none">
  <path d="M160.5 75.0 L 186.5 75.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10a-ah)"/>
  <path d="M337.5 75.0 L 363.5 75.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10a-ah)"/>
  <path d="M485.5 75.0 L 511.5 75.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10a-ah)"/>
  <path d="M669.5 75.0 L 695.5 75.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10a-ah)"/>
  <path d="M813.5 75.0 L 839.5 75.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10a-ah)"/>
  </g>
  <g>
  <rect x="42.5" y="40.0" width="118" height="70" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="186.5" y="40.0" width="151" height="70" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="363.5" y="40.0" width="122" height="70" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="511.5" y="40.0" width="158" height="70" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="695.5" y="40.0" width="118" height="70" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="839.5" y="40.0" width="118" height="70" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="101.5" y="78.9" font-size="11.5" text-anchor="middle" >SQL text</text>
  <text x="262.0" y="70.9" font-size="11.5" text-anchor="middle" font-weight="700" >Parser</text>
  <text x="262.0" y="86.9" font-size="10" text-anchor="middle" opacity="0.85" >text → parse tree</text>
  <text x="424.5" y="62.9" font-size="11.5" text-anchor="middle" font-weight="700" >Rewriter</text>
  <text x="424.5" y="78.9" font-size="10" text-anchor="middle" opacity="0.85" >expand views,</text>
  <text x="424.5" y="94.9" font-size="10" text-anchor="middle" opacity="0.85" >apply rules</text>
  <text x="590.5" y="70.9" font-size="11.5" text-anchor="middle" font-weight="700" >Planner/Optimizer</text>
  <text x="590.5" y="86.9" font-size="10" text-anchor="middle" opacity="0.85" >pick cheapest plan</text>
  <text x="754.5" y="70.9" font-size="11.5" text-anchor="middle" font-weight="700" >Executor</text>
  <text x="754.5" y="86.9" font-size="10" text-anchor="middle" opacity="0.85" >run the plan</text>
  <text x="898.5" y="78.9" font-size="11.5" text-anchor="middle" >Rows</text>
  </g>
</svg>
```

- The **parser** turns text into a tree and checks syntax (`SELCT` → error here).
- The **rewriter** expands views and applies rules — a normalization step.
- The **planner/optimizer** is the brain: it generates candidate plans and picks the one it
  estimates is cheapest.
- The **executor** runs that plan, pulling rows through it.

The interesting stage — the one that decides your query's fate — is the planner.

### The planner's job: choose among plans

For any non-trivial query there are *many* correct ways to compute the answer, and they
have wildly different costs. The planner enumerates plausible plans and assigns each an
estimated **cost**, then picks the minimum. Its choices come from two menus.

**Access methods** — how to get rows out of one table:

- **Sequential scan** (`Seq Scan`) — read every page of the heap, top to bottom. Great when
  you need most of the table (sequential disk reads are fast); terrible for finding one row
  in a million.
- **Index scan** (`Index Scan`) — walk a B-tree (Lesson 9) to the matching keys, then fetch
  those rows from the heap. Great for finding a few rows; a loser when "a few" is actually
  half the table, because each heap fetch is a *random* read.
- **Index-only scan** — when the index already contains every column the query needs, skip
  the heap entirely. The fastest of all.

**Join algorithms** — how to combine two tables:

- **Nested loop** — for each row of A, look up matches in B (ideally via B's index). Best
  when one side is small.
- **Hash join** — build a hash table of the smaller side, probe it with the larger. Best
  for joining two big unsorted tables on equality.
- **Merge join** — sort both sides by the join key, then walk them in lockstep. Best when
  inputs are already sorted (e.g. by an index).

The whole plan is a **tree** of these operators: leaves scan tables, higher nodes join and
filter, the root produces the final rows.

### Cost estimation: the planner is guessing (from statistics)

Here's the part that surprises people: **the planner never looks at your data to decide.**
That would be as slow as running the query. Instead it *estimates*, using **statistics** the
database keeps about each table — how many rows it has, how many distinct values each column
has, a histogram of the value distribution, how many pages it occupies. These are gathered by
`ANALYZE` (run automatically in the background) and stored for the planner to consult.

From those stats the planner estimates **selectivity** — what fraction of rows a condition
will match — and that estimate drives everything:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 360" width="100%" style="max-width:620px" role="img" aria-label="Cost estimation: a condition WHERE user_id equals 42 leads to a decision on the estimated number of matching rows; few rows (high selectivity) choose an index scan, many rows (low selectivity) choose a sequential scan." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l10b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g fill="none">
  <path d="M340.0 80 L 340.0 102.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l10b-ah)"/>
  <path d="M224.0 150.0 L175.0 150.0 L175.0 256" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l10b-ah)"/>
  <path d="M456.0 150.0 L505.0 150.0 L505.0 256" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l10b-ah)"/>
  </g>
  <g>
  <rect x="261.0" y="36" width="158" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M340 102.0 L456.0 150 L340 198.0 L224.0 150 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="89.0" y="256" width="172" height="54" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="419.0" y="256" width="172" height="54" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="340.0" y="61.9" font-size="11.5" text-anchor="middle" >WHERE user_id = 42</text>
  <text x="340" y="146.1" font-size="10.5" text-anchor="middle" >Estimated</text>
  <text x="340" y="161.1" font-size="10" text-anchor="middle" opacity="0.85" >matching rows?</text>
  <text x="175.0" y="278.9" font-size="11.5" text-anchor="middle" font-weight="700" >Index Scan</text>
  <text x="175.0" y="294.9" font-size="10" text-anchor="middle" opacity="0.85" >jump to the few rows</text>
  <text x="505.0" y="270.9" font-size="11.5" text-anchor="middle" font-weight="700" >Seq Scan</text>
  <text x="505.0" y="286.9" font-size="10" text-anchor="middle" opacity="0.85" >index's random reads</text>
  <text x="505.0" y="302.9" font-size="10" text-anchor="middle" opacity="0.85" >would cost more</text>
  <text x="175.0" y="138.0" font-size="9.5" text-anchor="middle" opacity="0.8" >few (high selectivity)</text>
  <text x="505.0" y="138.0" font-size="9.5" text-anchor="middle" opacity="0.8" >many (low selectivity)</text>
  </g>
</svg>
```

This is *why* an index sometimes goes unused (Lesson 9): if the planner estimates a
condition matches 40% of the table, thousands of random index-driven heap fetches cost more
than one sequential sweep, so it correctly chooses the scan. And it's why **stale statistics
cause slow queries** — if the stats say a table has 1,000 rows but it really has 10 million,
every estimate is wrong and the planner picks a plan that made sense for the table it
*thought* it had.

### EXPLAIN: reading the plan

`EXPLAIN` shows the plan the planner chose, without running it. `EXPLAIN ANALYZE` actually
runs the query and shows **estimated vs. actual** side by side — the more useful form for
debugging. A tiny example, before any index:

```sql
EXPLAIN SELECT * FROM orders WHERE user_id = 42;
```

```text
Seq Scan on orders  (cost=0.00..18334.00 rows=93 width=52)
  Filter: (user_id = 42)
```

Read it as: a sequential scan over the whole `orders` heap, expecting to keep 93 rows.
`cost=0.00..18334.00` is (startup cost .. total cost) in the planner's arbitrary units;
`rows=93` is its estimate. Now add the index from Lesson 9 and re-check:

```sql
CREATE INDEX idx_orders_user ON orders (user_id);
EXPLAIN SELECT * FROM orders WHERE user_id = 42;
```

```text
Index Scan using idx_orders_user on orders  (cost=0.42..25.30 rows=93 width=52)
  Index Cond: (user_id = 42)
```

The plan flipped from `Seq Scan` to `Index Scan`, and the estimated cost fell from ~18,334
to ~25 — a ~700× drop, because it now jumps to 93 rows via the B-tree instead of reading
every page. That flip, visible in the plan, is the entire value of the index made concrete.

### How to actually use this

`EXPLAIN` is a debugging skill, and it has a short, reliable playbook:

1. **Run `EXPLAIN ANALYZE`** on the slow query.
2. **Find the expensive node** — the one with the biggest actual time or row count. Plans
   are trees; the problem is usually one operator deep in it.
3. **Look for a `Seq Scan` on a big table** where you expected an index — either the index
   is missing, or the planner chose not to use it (often correct, sometimes a clue).
4. **Compare estimated vs. actual rows.** A large gap (est. 10, actual 100,000) means the
   statistics are wrong — run `ANALYZE`, and the planner may pick a better plan immediately.
5. **Then act**: add an index (Lesson 9), refresh statistics, or reshape the query. Re-run
   `EXPLAIN` to confirm the plan changed.

The mental shift: you never command the database *how* to run a query. You **shape its
choices** — by providing indexes, keeping statistics fresh, and writing queries it can
optimize — and you **read its plan** to understand what it decided and why. That's the whole
relationship between you and the planner.

## Think about it

1. Your query filters on an indexed column, but `EXPLAIN` shows a `Seq Scan` anyway. Give
   two distinct, *legitimate* reasons the planner might correctly refuse the index.
2. `EXPLAIN ANALYZE` shows a node with `rows=5` estimated but `actual rows=200000`. What's
   almost certainly wrong, and what one command might fix it — without touching the query?
3. You're joining a 10-row table to a 10-million-row table on a key the big table has
   indexed. Which join algorithm fits, and why would a hash join be wasteful here?
4. Why does the planner estimate cost from statistics instead of just looking at the data to
   get the true answer? What would the alternative cost you?

## Key takeaways

- SQL says *what*; the **query planner** decides *how*, compiling your declarative query into
  a concrete **execution plan** — and the best vs. worst plan can differ by orders of
  magnitude.
- A query flows **parse → rewrite → plan → execute**; the planner chooses **access methods**
  (Seq Scan / Index Scan / Index-Only) and **join algorithms** (nested loop / hash / merge),
  assembling them into a plan tree.
- The planner **estimates cost from statistics** (row counts, distinct values, histograms
  from `ANALYZE`), driven by **selectivity** — which is why a low-selectivity filter
  correctly skips an index, and why **stale stats cause bad plans**.
- **`EXPLAIN`** shows the chosen plan; **`EXPLAIN ANALYZE`** adds actual vs. estimated. The
  playbook: find the expensive node, spot unexpected `Seq Scan`s, and watch for large
  estimate-vs-actual gaps (bad statistics).
- You don't tell the database *how* — you **shape its choices** (indexes, fresh stats, query
  form) and **read its plan** to see what it did.

Next: [Transactions & ACID](../11-transactions-and-acid/) — from reading data fast to
changing it safely: grouping writes so they're all-or-nothing and survive a crash.
