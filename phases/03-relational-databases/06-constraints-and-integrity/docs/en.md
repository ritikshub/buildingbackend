# Constraints & Data Integrity

> A constraint is a rule you declare once and the database enforces on every write, forever, no matter which app or which bug is doing the writing. It's how you make an invalid state not "unlikely" but *impossible*.

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [Keys & Relationships](../05-keys-and-relationships/)
**Time:** ~50 minutes

## The Problem

Where should the rule "an order total can't be negative" live? The tempting answer is "in
the application — I'll check it before saving." But *which* application? The web API checks
it. Does the mobile backend? The nightly batch importer? The admin script someone runs by
hand at 2 a.m.? The data migration? Every one of those is a separate door into your data,
and the rule is only as strong as the *weakest* door. One forgotten check, one bug, one
`UPDATE` run in a database console, and a negative total is now sitting in your table
forever — and every report, every calculation, every downstream system inherits the lie.

There is exactly one place that *every* write must pass through no matter its source: the
database itself. A **constraint** is a rule declared there, so the database **refuses**
any write that would violate it — from any client, on any code path, for all time. This
lesson is the constraint toolkit: the rules that turn "we try to keep the data valid" into
"the data *cannot be* invalid."

## The Concept

### The database is the last line of defense

Picture every write to your data as passing through a gauntlet of gates. Application
validation is a helpful early gate — it gives users nice error messages. But it's *in
front of* many possible doors, and it can be bypassed. The database's constraints are the
**final** gate that no write can skip:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 330" width="100%" style="max-width:720px" role="img" aria-label="Four client applications all write through the database, whose constraint gauntlet accepts valid rows and rejects invalid writes." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l06a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="400.0" y="26" text-anchor="middle" font-size="14" font-weight="700">The database: every write's final gate</text>
  <g fill="none">
  <path d="M203 80.0 L 300 112" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  <path d="M203 140.0 L 300 145" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  <path d="M203 200.0 L 300 178" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  <path d="M203 260.0 L 300 211" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  <path d="M562 157.0 L 618 116.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  <path d="M562 157.0 L 618 222.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06a-ah)"/>
  </g>
  <g>
  <rect x="25" y="58" width="178" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="25" y="118" width="178" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="25" y="178" width="178" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="25" y="238" width="178" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M300 91 a 131.0 9 0 0 1 262 0 v 132 a 131.0 9 0 0 1 -262 0 Z" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="2"/>
  <path d="M300 91 a 131.0 9 0 0 0 262 0" fill="none" stroke="#7c5cff" stroke-width="2"/>
  <rect x="618" y="92" width="165" height="48" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="618" y="196" width="172" height="52" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="114.0" y="83.9" font-size="11.5" text-anchor="middle" >Web API</text>
  <text x="114.0" y="143.9" font-size="11.5" text-anchor="middle" >Mobile backend</text>
  <text x="114.0" y="203.9" font-size="11.5" text-anchor="middle" >Batch importer</text>
  <text x="114.0" y="263.9" font-size="11.5" text-anchor="middle" >Manual SQL console</text>
  <text x="431.0" y="157.4" font-size="11.5" text-anchor="middle" font-weight="700" >Database — constraint gauntlet</text>
  <text x="431.0" y="173.4" font-size="10" text-anchor="middle" opacity="0.85" >NOT NULL · UNIQUE · CHECK · FK</text>
  <text x="700.5" y="119.9" font-size="11.5" text-anchor="middle" >Row stored ✓</text>
  <text x="704.0" y="225.9" font-size="11.5" text-anchor="middle" >Write rejected ✗</text>
  <text x="590.0" y="130.5" font-size="9.5" text-anchor="middle" opacity="0.75" >valid</text>
  <text x="590.0" y="183.5" font-size="9.5" text-anchor="middle" opacity="0.75" >invalid</text>
  </g>
  
</svg>
```

This is **defense in depth**, not either/or: keep validating in the app for good UX, *and*
enforce the true invariants in the database so they hold even when the app is wrong. When
the two disagree, the database wins — because it's the one that can't be bypassed.

### NOT NULL — this value is required

The simplest constraint: forbid the absence of a value. Recall from Lesson 4 that any
column can hold NULL ("no value") unless told otherwise, and that NULL drags in
three-valued-logic surprises. `NOT NULL` says "every row must have a real value here":

```sql
CREATE TABLE app_user (
  id    BIGINT PRIMARY KEY,
  email TEXT NOT NULL          -- a user with no email cannot be stored
);
```

Use it on every column that is genuinely mandatory. It's the cheapest correctness win in
the whole schema, and it makes downstream code simpler by removing a whole class of
"but what if it's null?" branches.

### UNIQUE — no duplicates

`UNIQUE` guarantees no two rows share a value in that column (or set of columns) — it's how
you enforce candidate keys that aren't the primary key (Lesson 5):

```sql
ALTER TABLE app_user ADD CONSTRAINT uq_user_email UNIQUE (email);
```

Now the database itself prevents two accounts with the same email — even if two signup
requests race at the same millisecond, one succeeds and the other is rejected. That's a
guarantee application code *cannot* make on its own, because between its "is this email
taken?" check and its insert, another request can sneak in. Only the database, holding the
write, can enforce uniqueness atomically. (A `UNIQUE` across multiple columns enforces the
*combination* is unique, like `(student_id, course_id)`.)

### PRIMARY KEY — unique and not null, together

A primary key (Lesson 5) is really just `UNIQUE` + `NOT NULL` bundled and blessed as the
row's identity. Everything you know about those two constraints applies; the PK is the
canonical one the whole schema references.

### CHECK — any rule you can write as a condition

`CHECK` enforces an arbitrary boolean condition on each row — this is where domain rules
live:

```sql
CREATE TABLE order_line (
  id        BIGINT PRIMARY KEY,
  quantity  INT     NOT NULL CHECK (quantity > 0),
  price     NUMERIC(12,2) NOT NULL CHECK (price >= 0),
  status    TEXT    NOT NULL CHECK (status IN ('pending','shipped','delivered'))
);
```

Now a quantity of zero, a negative price, or a status of `'banana'` is *impossible* to
store — the database rejects the write with a clear error. `CHECK` turns business rules
("quantity must be positive," "status is one of these three") into invariants the data can
never violate. The `status IN (...)` pattern is a lightweight enum; some databases also
offer a dedicated `ENUM` type for the same job.

### DEFAULT — fill in a value when none is given

`DEFAULT` isn't a prohibition like the others; it *supplies* a value when an insert omits
the column, which keeps mandatory columns populated without every caller remembering to set
them:

```sql
CREATE TABLE app_user (
  id         BIGINT PRIMARY KEY,
  is_active  BOOLEAN     NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()   -- stamped automatically
);
```

`DEFAULT` pairs beautifully with `NOT NULL`: the column is required, but callers who don't
care get a sensible value for free.

### FOREIGN KEY and referential actions

Foreign keys (Lesson 5) enforce that a reference points at a real row. But they also need
to answer: **what happens to the children when the parent is deleted or its key changes?**
That's the `ON DELETE` / `ON UPDATE` clause, and choosing it deliberately matters:

| Action | On deleting a referenced parent… |
|---|---|
| `RESTRICT` / `NO ACTION` | **Refuse** the delete while children exist (the safe default) |
| `CASCADE` | **Delete the children too** (delete an order → its line items vanish) |
| `SET NULL` | Set the child's foreign key to NULL (orphan it deliberately; column must allow NULL) |
| `SET DEFAULT` | Set the child's foreign key to its DEFAULT value |

```sql
CREATE TABLE order_line (
  order_id BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  -- deleting an order removes its lines automatically; no orphans left behind
  product_id BIGINT REFERENCES product(id) ON DELETE RESTRICT
  -- but you can't delete a product that still appears on any order line
);
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 820 340" width="100%" style="max-width:720px" role="img" aria-label="Deleting an order reaches a decision on whether child order-line rows reference it, branching into RESTRICT, CASCADE, and SET NULL outcomes." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l06b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="410.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Foreign-key referential actions on DELETE</text>
  <g fill="none">
  <path d="M410.0 80 L 410.0 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06b-ah)"/>
  <path d="M410.0 180.0 L 410.0 212" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M124.0 212 L 701.0 212" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M124.0 212 L 124.0 246" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06b-ah)"/>
  <path d="M415.0 212 L 415.0 246" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06b-ah)"/>
  <path d="M701.0 212 L 701.0 246" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l06b-ah)"/>
  </g>
  <g>
  <rect x="338.0" y="34" width="144" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M410 96.0 L528.0 138 L410 180.0 L292.0 138 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="38" y="246" width="172" height="54" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="300" y="246" width="230" height="54" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="612" y="246" width="178" height="54" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="410.0" y="60.9" font-size="11.5" text-anchor="middle" >DELETE order #42</text>
  <text x="410" y="134.1" font-size="10.5" text-anchor="middle" >order_line rows</text>
  <text x="410" y="149.1" font-size="10" text-anchor="middle" opacity="0.85" >reference it?</text>
  <text x="124.0" y="276.9" font-size="11.5" text-anchor="middle" >✗ delete refused</text>
  <text x="415.0" y="276.9" font-size="11.5" text-anchor="middle" >✓ delete order + its lines</text>
  <text x="701.0" y="268.9" font-size="11.5" text-anchor="middle" font-weight="700" >✓ delete order,</text>
  <text x="701.0" y="284.9" font-size="10" text-anchor="middle" opacity="0.85" >null children's FK</text>
  <text x="136.0" y="228" font-size="9.5" text-anchor="start" opacity="0.8" >ON DELETE RESTRICT</text>
  <text x="427.0" y="228" font-size="9.5" text-anchor="start" opacity="0.8" >ON DELETE CASCADE</text>
  <text x="689.0" y="228" font-size="9.5" text-anchor="end" opacity="0.8" >ON DELETE SET NULL</text>
  </g>
  
</svg>
```

The right choice is a modeling decision: line items are *part of* an order, so `CASCADE`
(they die with it) is right; but a product is referenced by orders as history, so
`RESTRICT` (don't let it be deleted out from under real orders) protects the record.

### Declarative integrity: declare once, enforced forever

The theme tying all of these together: you **declare the invariant once**, in the schema,
and the database enforces it on **every** write from then on — no procedural code, no
remembering, no per-caller discipline. This is the same declarative spirit as SQL itself
(Lesson 3): you state *what must be true*, and the system guarantees it. Constraints are
also self-documenting — reading the schema tells the next engineer exactly what the data
means and what's impossible — and they're a genuine performance asset, because the planner
(Lesson 10) can trust a `UNIQUE` or `NOT NULL` guarantee when choosing how to run a query.

A robust schema puts it all together:

```sql
CREATE TABLE orders (
  id         BIGINT PRIMARY KEY,
  user_id    BIGINT NOT NULL REFERENCES app_user(id) ON DELETE RESTRICT,
  total      NUMERIC(12,2) NOT NULL CHECK (total >= 0),
  status     TEXT NOT NULL DEFAULT 'pending'
               CHECK (status IN ('pending','paid','shipped','cancelled')),
  placed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Every rule that matters — an order belongs to a real user, has a non-negative total, a
valid status, and a timestamp — is now guaranteed by the database, not hoped for by the
application.

## Think about it

1. Your app checks "is this email already registered?" then inserts the new user. Under
   concurrent signups this still creates duplicates sometimes. Why — and which single
   constraint closes the hole for good?
2. You model `order → order_line` and `order_line → product`. Argue for `ON DELETE
   CASCADE` on one of those foreign keys and `ON DELETE RESTRICT` on the other. What real
   damage does each choice prevent?
3. "We validate everything in the application, so database constraints are redundant."
   Give two concrete ways invalid data still gets in without database constraints.
4. Write a `CHECK` constraint for a table where `discount_price` must be present only when
   `on_sale` is true, and must be less than `price`. (Sketch the condition.)

## Key takeaways

- The database is the **one chokepoint every write passes through**, so it's the only
  place an invariant can be truly guaranteed. Constraints there make invalid states
  **impossible**, not merely unlikely.
- Use **defense in depth**: validate in the app for UX, enforce in the database for truth;
  when they disagree, the database — which can't be bypassed — wins.
- The toolkit: **`NOT NULL`** (required), **`UNIQUE`** (no duplicates, atomically — the
  only safe way under concurrency), **`CHECK`** (any boolean domain rule), **`DEFAULT`**
  (auto-fill), and **`FOREIGN KEY`** with **`ON DELETE`/`ON UPDATE`** actions
  (`RESTRICT` / `CASCADE` / `SET NULL`).
- Constraints are **declarative**: declare the rule once, the database enforces it on every
  write forever — and they double as documentation and a hint the query planner can trust.

Next: [Schema Design & Normalization](../07-schema-design-and-normalization/) — with keys
and constraints in hand, how to arrange columns across tables so each fact lives in exactly
one place.
