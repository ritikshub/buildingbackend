# Keys & Relationships

> A key is how the database answers "*which* row?" — and a foreign key is how one table points at another so firmly that the database won't let the connection break. Keys are what turn a pile of tables into a model.

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [Tables, Columns & Data Types](../04-tables-columns-data-types/)
**Time:** ~60 minutes

## The Problem

You have an `author` table and a `book` table. Two questions decide whether they're a real
database or just two spreadsheets in a trench coat:

1. Given "the author Ada Lovelace," how does the database find her *one* row, unambiguously,
   even if two authors share a name?
2. How does a book *belong to* an author — such that the database itself guarantees a book
   can never reference an author who doesn't exist?

Both answers are **keys**. A key uniquely identifies a row; a **foreign key** makes one
table reference another and enforces that the reference is always valid. This is where the
relationships between tables — the connective tissue of every real schema — actually come
from. Get keys right and your data has a rigid, self-checking skeleton. Get them wrong and
you get duplicate rows, orphaned records, and the slow rot of data nobody can trust.

## The Concept

### The primary key: a row's identity

A **primary key (PK)** is one or more columns whose value **uniquely identifies each row**
in a table. It carries two guarantees the database enforces automatically: the value is
**unique** (no two rows share it) and **never NULL** (every row has one). It's the row's
name — the thing everything else uses to point at it.

```sql
CREATE TABLE author (
  id      BIGINT PRIMARY KEY,   -- unique + not null, enforced by the database
  name    TEXT,
  country TEXT
);
```

A table has **exactly one** primary key. Ask the database for "author 1" and there is
exactly one answer, forever.

### Candidate keys and composite keys

Often more than one column (or set of columns) *could* serve as the unique identifier —
each such option is a **candidate key**. An `author` table might have both `id` and
`email` as candidate keys (both unique). You pick one candidate to be the primary key; the
others can be enforced as `UNIQUE` (Lesson 6).

When it takes **several columns together** to be unique, that's a **composite key**. In a
table of enrollments, neither `student_id` nor `course_id` is unique alone (a student takes
many courses; a course has many students), but the *pair* is:

```sql
CREATE TABLE enrollment (
  student_id BIGINT,
  course_id  BIGINT,
  grade      TEXT,
  PRIMARY KEY (student_id, course_id)   -- unique together, not individually
);
```

### Natural vs. surrogate keys — a decision you'll make constantly

Where does the primary key *value* come from? Two schools:

- A **natural key** is data that already exists and is meant to be unique: an email, a
  Social Security number, an ISBN, a country code. It's meaningful.
- A **surrogate key** is a value invented purely to be the identity, carrying no business
  meaning: an auto-incrementing integer (`1, 2, 3, …`) or a `UUID`. It exists only to
  identify the row.

The trade-off, which comes up in nearly every table you design:

| | Natural key | Surrogate key |
|---|---|---|
| Meaningful? | Yes (it's real data) | No (just an identity) |
| Stable? | **No** — emails change, "unique" IDs get reissued | **Yes** — never needs to change |
| Leaks info? | Yes (a natural key in a URL exposes real data) | No |
| Guaranteed unique & present? | Only if the real world cooperates | Yes, by construction |

The hard-won default: **use a surrogate key** (an auto-increment `BIGINT` or a `UUID`) as
the primary key, and enforce natural keys like `email` with a separate `UNIQUE` constraint.
Why? Because natural keys change — a company renames, a person's "permanent" ID gets
reissued, a country splits — and when a primary key changes, every foreign key pointing at
it has to change too, a migration from hell. A surrogate key is meaningless *on purpose*,
so it never needs to change. (Integers are compact and sort well; UUIDs are unique without
a central counter, handy across distributed systems and when you don't want IDs to be
guessable — at the cost of size and random ordering. Lesson 9 revisits that.)

### The foreign key: a reference the database enforces

A **foreign key (FK)** is a column in one table that **references the primary key of
another** (or the same) table. It's how a book *belongs to* an author:

```sql
CREATE TABLE book (
  id        BIGINT PRIMARY KEY,
  title     TEXT,
  author_id BIGINT REFERENCES author(id)   -- FK: must match an existing author.id
);
```

The magic word is **enforced**. With that `REFERENCES` in place, the database guarantees
**referential integrity**: every `author_id` in `book` must point at a row that actually
exists in `author`. Try to insert a book for author 999 when there's no author 999, and
the database *rejects the write*. Try to delete an author who still has books, and it
refuses (unless you tell it what to do with the children — Lesson 6's `ON DELETE`
actions). A book can never become an **orphan** pointing at a ghost. The connection can't
silently break, because the database won't allow the state where it's broken.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 340" width="100%" style="max-width:680px" role="img" aria-label="Foreign key enforcement. A valid reference from book.author_id=2 to author.id=2 which exists. An invalid reference from book.author_id=999 to a missing author.id=999, which the database rejects as a referential integrity violation." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l05a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="340.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Foreign key enforcement — referential integrity</text>
  <g fill="none">
  <path d="M255 78.0 L 400 78.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l05a-ah)"/>
  <path d="M263 176.0 L 395 176.0" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#l05a-ah)"/>
  <path d="M470.0 200 L 469.5 252" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#l05a-ah)"/>
  </g>
  <g>
  <rect x="95" y="54" width="160" height="48" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="400" y="54" width="140" height="48" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  <rect x="87" y="152" width="176" height="48" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="395" y="152" width="150" height="48" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-dasharray="7 6" stroke-linejoin="round"/>
  <rect x="344" y="252" width="251" height="52" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="175.0" y="81.9" font-size="11.5" text-anchor="middle" >book.author_id = 2</text>
  <text x="470.0" y="73.9" font-size="11.5" text-anchor="middle" font-weight="700" >author.id = 2</text>
  <text x="470.0" y="89.9" font-size="10" text-anchor="middle" opacity="0.85" >✓ exists</text>
  <text x="327.5" y="72.0" font-size="9.5" text-anchor="middle" opacity="0.75" >REFERENCES</text>
  <text x="175.0" y="179.9" font-size="11.5" text-anchor="middle" >book.author_id = 999</text>
  <text x="470.0" y="171.9" font-size="11.5" text-anchor="middle" font-weight="700" >author.id = 999</text>
  <text x="470.0" y="187.9" font-size="10" text-anchor="middle" opacity="0.85" >✗ missing</text>
  <text x="329.0" y="170.0" font-size="9.5" text-anchor="middle" opacity="0.75" >REFERENCES</text>
  <text x="469.5" y="273.9" font-size="11.5" text-anchor="middle" font-weight="700" >✗ database REJECTS the write</text>
  <text x="469.5" y="289.9" font-size="10" text-anchor="middle" opacity="0.85" >referential integrity violation</text>
  <text x="482.0" y="229.0" font-size="9.5" text-anchor="start" opacity="0.75" >database REJECTS the write</text>
  </g>
  <text x="340.0" y="328" text-anchor="middle" font-size="11" opacity="0.9">A foreign key makes the broken state unwritable: the database enforces the reference.</text>
</svg>
```

### The three shapes of a relationship

Almost every relationship between two entities is one of three shapes, and each has a
standard way to model it with keys.

**One-to-many (1:N)** — the most common. One author has many books; each book has one
author. Model it by putting the foreign key **on the "many" side**: `book.author_id`. One
`author.id`, referenced by many `book` rows. (That's the example above.)

**One-to-one (1:1)** — one row in A pairs with at most one row in B. A user has one profile.
Model it like 1:N but make the foreign key **`UNIQUE`**, so the "many" side can hold at
most one:

```sql
CREATE TABLE user_profile (
  user_id BIGINT UNIQUE REFERENCES app_user(id),   -- UNIQUE ⇒ one profile per user
  bio     TEXT
);
```

(1:1 is often better folded into one table; use a separate table when the extra columns are
optional, rarely read, or access-controlled separately.)

**Many-to-many (M:N)** — the one that needs a third table. A student takes many courses; a
course has many students. You **cannot** put a foreign key on either side — a single column
can only hold one value. Instead you create a **junction table** (also called a join,
bridge, or associative table) whose rows are the *pairings*, with a foreign key to each
side:

```sql
CREATE TABLE enrollment (
  student_id BIGINT REFERENCES student(id),
  course_id  BIGINT REFERENCES course(id),
  PRIMARY KEY (student_id, course_id)   -- each pairing once (a composite key!)
);
```

Every M:N relationship becomes two 1:N relationships pointing *into* a junction table. And
the junction table is a great home for facts *about the pairing* itself — `enrolled_at`, a
`grade`, a `role` — data that belongs to neither entity alone.

### Reading a schema: the ER diagram

An **entity-relationship (ER) diagram** shows the tables (entities) and how keys connect
them, with **cardinality** — the "one" and "many" ends — marked on each line. Here's a
small e-commerce model tying the shapes together:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 410" width="100%" style="max-width:720px" role="img" aria-label="Entity relationship diagram with four entities APP_USER, ORDERS, PRODUCT and ORDER_ITEM and their primary and foreign keys, connected by places, contains and appears-in relationships." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <text x="380.0" y="26" text-anchor="middle" font-size="14" font-weight="700">ER diagram — a small e-commerce schema</text>
  <g fill="none">
  <path d="M80 85 L 270 85" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M490 85 L 680 85" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M80 291 L 270 291" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M490 291 L 680 291" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M175.0 154 L 175.0 260" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M585.0 154 L 585.0 260" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M280 310.0 L 480 310.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  </g>
  <g>
  <rect x="70" y="54" width="210" height="100" rx="10" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="480" y="54" width="210" height="100" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="70" y="260" width="210" height="100" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="480" y="260" width="210" height="100" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="175.0" y="76" font-size="12.5" text-anchor="middle" font-weight="700" opacity="0.8" >APP_USER</text>
  <text x="84" y="106" font-size="10" text-anchor="start" opacity="0.95" >id</text>
  <text x="162" y="106" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="266" y="106" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >PK</text>
  <text x="84" y="126" font-size="10" text-anchor="start" opacity="0.95" >email</text>
  <text x="162" y="126" font-size="9.5" text-anchor="start" opacity="0.65" >text</text>
  <text x="266" y="126" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >UK</text>
  <text x="585.0" y="76" font-size="12.5" text-anchor="middle" font-weight="700" opacity="0.8" >PRODUCT</text>
  <text x="494" y="106" font-size="10" text-anchor="start" opacity="0.95" >id</text>
  <text x="572" y="106" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="676" y="106" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >PK</text>
  <text x="494" y="126" font-size="10" text-anchor="start" opacity="0.95" >name</text>
  <text x="572" y="126" font-size="9.5" text-anchor="start" opacity="0.65" >text</text>
  <text x="494" y="146" font-size="10" text-anchor="start" opacity="0.95" >price</text>
  <text x="572" y="146" font-size="9.5" text-anchor="start" opacity="0.65" >numeric</text>
  <text x="175.0" y="282" font-size="12.5" text-anchor="middle" font-weight="700" opacity="0.8" >ORDERS</text>
  <text x="84" y="312" font-size="10" text-anchor="start" opacity="0.95" >id</text>
  <text x="162" y="312" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="266" y="312" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >PK</text>
  <text x="84" y="332" font-size="10" text-anchor="start" opacity="0.95" >user_id</text>
  <text x="162" y="332" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="266" y="332" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >FK</text>
  <text x="84" y="352" font-size="10" text-anchor="start" opacity="0.95" >placed_at</text>
  <text x="162" y="352" font-size="9.5" text-anchor="start" opacity="0.65" >timestamptz</text>
  <text x="585.0" y="282" font-size="12.5" text-anchor="middle" font-weight="700" opacity="0.8" >ORDER_ITEM</text>
  <text x="494" y="312" font-size="10" text-anchor="start" opacity="0.95" >order_id</text>
  <text x="572" y="312" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="676" y="312" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >FK</text>
  <text x="494" y="332" font-size="10" text-anchor="start" opacity="0.95" >product_id</text>
  <text x="572" y="332" font-size="9.5" text-anchor="start" opacity="0.65" >bigint</text>
  <text x="676" y="332" font-size="9.5" text-anchor="end" font-weight="700" opacity="0.95" >FK</text>
  <text x="494" y="352" font-size="10" text-anchor="start" opacity="0.95" >quantity</text>
  <text x="572" y="352" font-size="9.5" text-anchor="start" opacity="0.65" >int</text>
  <text x="185.0" y="172" font-size="10" text-anchor="start" font-weight="700" opacity="0.8" >1</text>
  <text x="185.0" y="210.0" font-size="10" text-anchor="start" opacity="0.9" >places</text>
  <text x="185.0" y="248" font-size="12" text-anchor="start" font-weight="700" opacity="0.8" >∞</text>
  <text x="595.0" y="172" font-size="10" text-anchor="start" font-weight="700" opacity="0.8" >1</text>
  <text x="595.0" y="210.0" font-size="10" text-anchor="start" opacity="0.9" >appears in</text>
  <text x="595.0" y="248" font-size="12" text-anchor="start" font-weight="700" opacity="0.8" >∞</text>
  <text x="380.0" y="301.0" font-size="10" text-anchor="middle" opacity="0.9" >contains</text>
  <text x="292" y="301.0" font-size="10" text-anchor="start" font-weight="700" opacity="0.8" >1</text>
  <text x="468" y="301.0" font-size="12" text-anchor="end" font-weight="700" opacity="0.8" >∞</text>
  </g>
  <text x="380.0" y="398" text-anchor="middle" font-size="11" opacity="0.9">||  one  ·  o{  many.   ORDER_ITEM is the junction table resolving M:N between ORDERS and PRODUCT.</text>
</svg>
```

Read the crow's-foot notation: `||--o{` means "one to zero-or-many." A user **places** many
orders (1:N). An order **contains** many order items (1:N). A product **appears in** many
order items (1:N). And `ORDER_ITEM` is the **junction table** that resolves the M:N between
orders and products — one order has many products, one product is in many orders — while
also carrying `quantity`, a fact about the pairing. `PK` = primary key, `FK` = foreign key,
`UK` = unique key. This diagram *is* the schema, and every line is a foreign key doing its
job.

## Think about it

1. Your `user` table uses `email` as its primary key. A user changes their email. What
   now has to happen to every table that references them, and how would a surrogate key
   have avoided it?
2. You need to model "a playlist contains many songs, and a song appears on many
   playlists." Why can't a foreign key on either table express this, and what exactly do
   you build instead? Where would `position_in_playlist` live?
3. A foreign key gives you referential integrity. Give a concrete bad state it makes
   *impossible*, and say what would exist in your data without it.
4. When is a natural key actually the right primary key? (Hint: think about a junction
   table, or an entity whose identity genuinely never changes.)

## Key takeaways

- A **primary key** uniquely identifies each row (**unique + not NULL**, one per table);
  a **candidate key** is any column set that could serve; a **composite key** spans
  multiple columns that are unique only together.
- Prefer a **surrogate key** (auto-increment `BIGINT` or `UUID`) as the primary key and
  enforce natural keys like `email` with `UNIQUE` — because natural keys change, and a
  changing primary key is a migration nightmare.
- A **foreign key** references another table's primary key and makes the database enforce
  **referential integrity**: no orphan rows, no references to things that don't exist —
  the invalid state simply can't be written.
- Model relationships with keys: **1:N** puts the FK on the many side; **1:1** adds
  `UNIQUE`; **M:N** needs a **junction table** of the pairings (two FKs, often a composite
  PK), which also holds facts about the pairing.
- An **ER diagram** visualizes entities, their keys, and cardinality — every connecting
  line is a foreign key.

Next: [Constraints & Data Integrity](../06-constraints-and-integrity/) — foreign keys are
one kind of rule the database enforces; now the full toolkit for making invalid data
impossible.
