# Tables, Columns & Data Types

> A column's type is a promise the database enforces on every value that will ever live there. Choose it well and the database catches your bugs, packs your data tightly, and sorts it correctly. Choose "just make it text" and you inherit all three problems forever.

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [The Relational Model](../03-the-relational-model/)
**Time:** ~55 minutes

## The Problem

You're defining a table for users. Easy — `id`, `name`, `email`, `age`, `created`,
`balance`. But *what kind* of value is each one? If you shrug and make everything text,
the database will let you store `"forty-two"` in the age column, `"last tuesday"` as a
timestamp, and `"10.0"` and `"10.00"` and `"$10"` as three different balances that no
longer sort or add up. Every consuming program now has to parse, validate, and re-check
what should have been guaranteed once.

A column's **data type** is that guarantee. It's a contract the database enforces on
*every* value the column will ever hold: what's allowed in, how much space it takes, how
it sorts and compares, and which operations make sense on it. Getting types right is the
most basic act of schema design — and it quietly prevents a whole category of bugs before
they're written. This lesson is the type system, the one genuinely tricky corner of it
(NULL), and how to choose.

## The Concept

### Anatomy of a column

A table is a set of columns; each column is a **name + a type + optional constraints**
(constraints are Lesson 6). The type is the part that decides what a value *is*.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 180" width="100%" style="max-width:640px" role="img" aria-label="Anatomy of a column definition: a name, a type, and optional constraints, grouped under a column definition." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <g fill="none">
  <path d="M215.0 105.0 L 245.0 105.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M395.0 105.0 L 425.0 105.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  </g>
  <g>
  <rect x="45" y="34" width="550" height="112" rx="12" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="65.0" y="76" width="150" height="58" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="245.0" y="76" width="150" height="58" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="425.0" y="76" width="150" height="58" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="63" y="58" font-size="12" text-anchor="start" font-weight="700" >A column definition</text>
  <text x="140.0" y="100.9" font-size="11.5" text-anchor="middle" font-weight="700" >name</text>
  <text x="140.0" y="116.9" font-size="10" text-anchor="middle" opacity="0.85" >'balance'</text>
  <text x="320.0" y="100.9" font-size="11.5" text-anchor="middle" font-weight="700" >type</text>
  <text x="320.0" y="116.9" font-size="10" text-anchor="middle" opacity="0.85" >NUMERIC(12,2)</text>
  <text x="500.0" y="100.9" font-size="11.5" text-anchor="middle" font-weight="700" >constraints</text>
  <text x="500.0" y="116.9" font-size="10" text-anchor="middle" opacity="0.85" >NOT NULL, ≥ 0</text>
  </g>
  <text x="320.0" y="168" text-anchor="middle" font-size="11" opacity="0.9">A column = a name + a type + optional constraints.</text>
</svg>
```

When you write a `CREATE TABLE`, you're really declaring, column by column, the domain
(Lesson 3) each attribute draws from:

```sql
CREATE TABLE app_user (
  id         BIGINT,          -- a whole number, room for billions
  email      VARCHAR(255),    -- text, at most 255 chars
  age        SMALLINT,        -- a small whole number
  balance    NUMERIC(12, 2),  -- exact decimal: 12 digits, 2 after the point
  is_active  BOOLEAN,         -- true / false
  created_at TIMESTAMPTZ      -- a moment in time, timezone-aware
);
```

Exact type *names* vary a little between databases (Postgres, MySQL, SQLite each have
quirks), but the **families** are universal. Learn the families and you can read any
schema.

### The type families

**Whole numbers (integers).** Come in sizes, and size = the range they hold and the bytes
they cost:

| Type | Bytes | Roughly holds | Use for |
|---|---|---|---|
| `SMALLINT` | 2 | ±32 thousand | ages, counts, small enums |
| `INTEGER` | 4 | ±2.1 billion | most counters, IDs in small systems |
| `BIGINT` | 8 | ±9.2 quintillion | IDs at scale, money-in-cents |

Pick the **smallest type that comfortably fits the largest value you'll ever have**, with
headroom. A user's age is a `SMALLINT`; a primary key for a table that might hit billions
of rows is a `BIGINT` (a 4-byte `INTEGER` key caps at ~2.1 billion — a real production
outage waiting to happen).

**Exact decimals vs. approximate floats — the money trap.** There are two ways to store
fractional numbers, and confusing them corrupts financial data:

- `NUMERIC` / `DECIMAL(precision, scale)` stores the value **exactly**, digit by digit.
  `NUMERIC(12,2)` means 12 total digits, 2 after the decimal point. `0.10 + 0.20` is
  exactly `0.30`.
- `REAL` / `DOUBLE PRECISION` (floating point) stores an **approximation** in binary. In
  float, `0.1 + 0.2` famously equals `0.30000000000000004`. Fine for physics and
  measurements; **catastrophic for money**, where a fraction of a cent that won't reconcile
  is a bug an auditor will find.

The rule is absolute: **store money as `NUMERIC`/`DECIMAL`** (or as an integer count of
the smallest unit, e.g. cents in a `BIGINT`). Never in a float.

**Text.** Three flavors:

- `CHAR(n)` — fixed length, padded with spaces. Rarely what you want.
- `VARCHAR(n)` — variable length up to a cap `n`.
- `TEXT` — variable length, effectively unbounded.

In Postgres these perform almost identically; the length cap on `VARCHAR` is really a
*constraint*, not a performance feature. Use `VARCHAR(n)` when there's a real business
limit (an ISO country code is 2 chars), `TEXT` otherwise.

**Boolean.** `BOOLEAN` — `true` / `false` (and, per NULL below, possibly *unknown*).
Prefer it over a `0/1` integer or a `'Y'/'N'` string; it says what it means.

**Dates and times** — the family that causes the most bugs:

- `DATE` — a calendar day, no time.
- `TIME` — a time of day, no date.
- `TIMESTAMP` — date + time, but **no timezone** — a source of endless confusion.
- `TIMESTAMPTZ` (timestamp with time zone) — a specific instant, stored normalized to
  **UTC**. This is almost always the right choice: store the true moment in UTC, convert
  to the user's timezone only when displaying.

Storing a timestamp as `TEXT` (`"2026-07-17 14:30"`) throws away every guarantee — no
validation, no correct sorting across formats, no date arithmetic. Use the real type.

**Other essentials:**

- `UUID` — a 128-bit globally unique identifier, for IDs that must be unique without a
  central counter (Lesson 5 weighs these against integers).
- `BYTEA` / `BLOB` — raw binary bytes (small images, hashes). Large files usually belong
  in object storage with just a URL in the database.
- `JSON` / `JSONB` — a whole semi-structured document *inside* a column, for the genuinely
  variable-shaped corner of an otherwise relational schema. Powerful, but reach for it
  sparingly: data you'll query and constrain wants real columns, not a JSON blob.
- `ENUM` — a column restricted to a fixed set of labels (`'pending' | 'shipped' |
  'delivered'`).

### Why the type actually earns its keep

Choosing a real type over "just text" buys you four things at once:

1. **Correctness** — the database *rejects* `age = 'banana'` or an impossible date. Bad
   data can't get in.
2. **Space** — a `SMALLINT` age is 2 bytes; `"forty-two"` as text is more, and a
   `BIGINT` packs tighter and compares faster than a numeric string.
3. **Correct operations** — dates subtract to give durations, numbers add, booleans
   filter. Text does none of these meaningfully.
4. **Correct sorting** — as numbers, `9 < 10`. As text, `"10" < "9"` (string comparison is
   character by character). Store numbers as numbers or your ordering lies.

### NULL: the value that isn't a value

Every column can, unless you forbid it, hold **NULL** — a special marker meaning "**no
value here**": unknown, missing, or not applicable. NULL is *not* zero, *not* an empty
string, *not* false. A user with `age = NULL` isn't zero years old; their age is simply
unknown.

NULL forces the database into **three-valued logic**. Ordinary logic has TRUE and FALSE;
add "unknown" and every comparison against NULL returns **UNKNOWN**, which behaves like a
third truth value:

| Expression | Result |
|---|---|
| `5 = 5` | TRUE |
| `5 = NULL` | **UNKNOWN** |
| `NULL = NULL` | **UNKNOWN** — not TRUE! |
| `NULL <> 5` | **UNKNOWN** |

This trips up everyone at least once, because rows are only returned when a `WHERE`
condition is **TRUE** — UNKNOWN is filtered out just like FALSE:

```sql
-- Does NOT return users whose age is NULL — 'age <> 30' is UNKNOWN for them,
-- and UNKNOWN rows are excluded, not included.
SELECT * FROM app_user WHERE age <> 30;

-- The ONLY correct way to test for NULL is IS NULL / IS NOT NULL:
SELECT * FROM app_user WHERE age IS NULL;
```

Two consequences to bank now: **test NULL with `IS NULL`, never `= NULL`** (the latter is
always UNKNOWN, so it matches nothing), and **aggregates skip NULLs** — `AVG(age)` ignores
unknown ages rather than treating them as zero, which is usually what you want but
occasionally a nasty surprise. If a column should never be absent, forbid NULL with a
`NOT NULL` constraint (Lesson 6) — the cleanest way to avoid the whole tangle.

### Choosing types: a worked before/after

The lazy schema — everything stringly-typed:

```sql
-- DON'T: every guarantee thrown away
CREATE TABLE order_bad (
  id       TEXT,   -- sorts as text: '10' < '9'
  total    TEXT,   -- '$10.00' — can't sum, can't compare
  created  TEXT,   -- 'last tuesday' — no validation, no date math
  shipped  TEXT    -- 'yes' / 'y' / 'true' / '1' — pick one? nobody did
);
```

The same table with the type system doing its job:

```sql
-- DO: the database now enforces meaning
CREATE TABLE order_good (
  id         BIGINT,          -- sorts numerically, packs tightly
  total      NUMERIC(12, 2),  -- exact money, sums correctly
  created_at TIMESTAMPTZ,     -- a real instant in UTC, supports date math
  shipped    BOOLEAN          -- unambiguous true/false
);
```

The second table can't be fed nonsense, sorts and sums correctly, and needs zero
defensive parsing in application code. That's the type system paying rent.

## Think about it

1. Why must a bank never store account balances as `DOUBLE PRECISION`? Give the concrete
   arithmetic that goes wrong, and the two correct alternatives.
2. `SELECT * FROM app_user WHERE age <> 30` returns 90 rows, but you know 5 users have a
   NULL age. Are those 5 in the result? Explain using three-valued logic, and fix the query
   to include them.
3. You store IDs as `TEXT` and sort them: `1, 10, 100, 2, 20`. Why this order, and what one
   change fixes it?
4. When is `JSONB` a *good* choice inside a relational table, and what do you give up
   versus modeling those fields as real columns?

## Key takeaways

- A column's **data type** is an enforced contract: it decides what's allowed in, how much
  space it takes, how it compares and sorts, and which operations are valid.
- Know the **families**: sized integers, **exact `NUMERIC`/`DECIMAL` vs approximate float**
  (money is *always* exact), text (`VARCHAR`/`TEXT`), boolean, the date/time family
  (prefer **`TIMESTAMPTZ` in UTC**), plus UUID, binary, JSON, and enum.
- Real types buy **correctness, compact storage, correct operations, and correct sorting**
  — "just make it text" forfeits all four.
- **NULL means "no value"** (unknown/absent), not zero or empty, and it triggers
  **three-valued logic**: comparisons with NULL are UNKNOWN, so test with **`IS NULL`**,
  never `= NULL`, and remember aggregates skip NULLs.
- Pick the **smallest correct type with headroom**; forbid NULL where a value is mandatory
  to sidestep the three-valued-logic traps entirely.

Next: [Keys & Relationships](../05-keys-and-relationships/) — how a single row is uniquely
identified, and how keys turn separate tables into a connected model.
