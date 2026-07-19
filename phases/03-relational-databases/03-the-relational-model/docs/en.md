# The Relational Model

> A table looks too simple to be a breakthrough. But behind that grid is a piece of mathematics that lets you ask *any* question of your data by describing the answer — never by explaining how to go and fetch it. That separation is the whole idea.

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [A Field Guide to Databases](../02-database-landscape/)
**Time:** ~60 minutes

## The Problem

We've said relational databases store data in "tables." Everyone has seen a table — it's
a spreadsheet, right? Rows and columns. If that were all there is to it, the relational
model wouldn't have won a Turing Award.

The depth is in the *rules*. A relational table isn't a loose grid you can do anything to;
it's a precise mathematical object with guarantees, and those guarantees are exactly what
let a database accept a question it has never seen before — "which customers in Berlin
ordered a red widget last March?" — and answer it correctly without you writing a single
line of loop-over-the-data code. This lesson unpacks what a table *really* is, the small
vocabulary that comes with it, and why "relational" is the reason SQL can be declarative.
We'll meet SQL here, but only lightly: SQL gets its own phase; today it's just the voice
the relational model speaks in.

## The Concept

### Relation, tuple, attribute, domain — the real names

The everyday words (table, row, column) each have a formal counterpart from Codd's 1970
paper. You'll see both used interchangeably for the rest of your career, so meet them once:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 300" width="100%" style="max-width:680px" role="img" aria-label="The author relation drawn as a table: a header row of attributes id, name, country, and three tuple rows." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l03a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="340.0" y="26" text-anchor="middle" font-size="14" font-weight="700">The "author" relation — a table</text>
  <g fill="none">
  <path d="M220 92 L 220 252" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M410 92 L 410 252" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M150 132 L 520 132" fill="none" stroke="currentColor" stroke-width="1.8"/>
  <path d="M150 172 L 520 172" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M150 212 L 520 212" fill="none" stroke="currentColor" stroke-width="1"/>
  <path d="M140 112.0 L 150 112.0" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#l03a-ah)"/>
  <path d="M530 152.0 L 520 152.0" fill="none" stroke="currentColor" stroke-width="1.4" marker-end="url(#l03a-ah)"/>
  </g>
  <g>
  <rect x="150" y="92" width="370" height="160" rx="10" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="154" y="96" width="362" height="34" rx="6" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="0" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="185.0" y="116.0" font-size="12" text-anchor="middle" font-weight="700" >id</text>
  <text x="315.0" y="116.0" font-size="12" text-anchor="middle" font-weight="700" >name</text>
  <text x="465.0" y="116.0" font-size="12" text-anchor="middle" font-weight="700" >country</text>
  <text x="185.0" y="156.0" font-size="11" text-anchor="middle" opacity="0.95" >1</text>
  <text x="315.0" y="156.0" font-size="11" text-anchor="middle" opacity="0.95" >Ada Lovelace</text>
  <text x="465.0" y="156.0" font-size="11" text-anchor="middle" opacity="0.95" >UK</text>
  <text x="185.0" y="196.0" font-size="11" text-anchor="middle" opacity="0.95" >2</text>
  <text x="315.0" y="196.0" font-size="11" text-anchor="middle" opacity="0.95" >Grace Hopper</text>
  <text x="465.0" y="196.0" font-size="11" text-anchor="middle" opacity="0.95" >US</text>
  <text x="185.0" y="236.0" font-size="11" text-anchor="middle" opacity="0.95" >3</text>
  <text x="315.0" y="236.0" font-size="11" text-anchor="middle" opacity="0.95" >Alan Turing</text>
  <text x="465.0" y="236.0" font-size="11" text-anchor="middle" opacity="0.95" >UK</text>
  <text x="136" y="109.0" font-size="10.5" text-anchor="end" opacity="0.9" >attributes</text>
  <text x="136" y="122.0" font-size="9.5" text-anchor="end" opacity="0.65" >(columns)</text>
  <text x="534" y="149.0" font-size="10.5" text-anchor="start" opacity="0.9" >tuple</text>
  <text x="534" y="162.0" font-size="9.5" text-anchor="start" opacity="0.65" >(row)</text>
  </g>
  <text x="340.0" y="288" text-anchor="middle" font-size="11" opacity="0.9">A relation (table) is a set of tuples (rows) over named attributes (columns).</text>
</svg>
```

- A **relation** is a table — a named set of rows sharing the same columns.
- A **tuple** is a row — one record, one author.
- An **attribute** is a column — a named field like `name`, with a fixed meaning.
- A **domain** is the set of values an attribute is *allowed* to take — its type and
  permitted range. The domain of `country` might be "any 2-letter ISO code"; the domain of
  `id` might be "positive integers." A value that isn't in the domain simply isn't allowed.

That's the entire core vocabulary. A **relational schema** (Lesson 7) is just a collection
of relations and their attributes' domains.

### The rules that make it more than a spreadsheet

A relation obeys constraints a spreadsheet doesn't, and each one buys something:

- **A relation is a *set* of tuples** — so there are **no duplicate rows** (a set can't
  contain the same element twice) and **no inherent order** (a set isn't ordered). You
  never rely on "the third row"; you identify a row by its *values*, via a key. This is why
  the database is free to store and return rows in whatever order is fastest.
- **Every value is atomic** — one value per cell, not a list crammed into it. `authors =
  {Ada, Grace}` in a single cell is not allowed; that's what a second table and a key are
  for. (This is the seed of *first normal form*, Lesson 7.)
- **Columns are identified by name, not position**, and every value in a column comes from
  the same domain. `country` is always a country, in every row.
- **All rows have the same columns.** A relation has a fixed shape; you don't get a row
  with an extra field bolted on. (Contrast the document model of Lesson 2, which *does*.)

These rules are restrictive on purpose. Restrictions are what make the data *predictable*,
and predictable data is what a query engine can reason about mechanically.

### "Relational" means *relations*, not *relationships*

The single most common misunderstanding: people assume "relational" refers to the
relationships *between* tables (author → books). It doesn't. The name comes from
**relation**, the mathematical term for a single table. The model is "relational" because
it's built out of relations. (Relationships between tables are wonderful, and we build them
with keys in Lesson 5 — but they're not where the name comes from.) Getting this straight
now saves a lot of muddled thinking later.

### The payoff: relational algebra

Here's why the rigor matters. Because relations are well-defined mathematical sets, you can
define **operations** that take relations in and give relations out — a closed algebra,
much like arithmetic on numbers. Codd defined a handful of primitive operations; you don't
need to memorize the symbols, just feel what they do:

| Operation | Symbol | What it does | Plain English |
|---|---|---|---|
| Select | σ | Keep rows matching a condition | "authors where country = 'UK'" |
| Project | π | Keep only certain columns | "just the names" |
| Join | ⋈ | Combine two relations on matching values | "each book next to its author" |
| Union | ∪ | All rows from both | "UK authors and US authors" |
| Difference | − | Rows in one but not the other | "authors with no books" |

The magic property: **every operation returns another relation.** So you can feed the
output of one into the next and build up any query as a chain — select, then project, then
join — the way you chain arithmetic. "UK authors' names" is `π_name( σ_country='UK'(author)
)`. A whole query is just an expression in this algebra.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 180" width="100%" style="max-width:700px" role="img" aria-label="A relational algebra pipeline: the author relation, then select country equals UK giving UK authors, then project name giving their names." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l03b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="350.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Relational algebra — chaining operations</text>
  <g fill="none">
  <path d="M165.0 95.0 L 285.0 95.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l03b-ah)"/>
  <path d="M415.0 95.0 L 535.0 95.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l03b-ah)"/>
  </g>
  <g>
  <rect x="35.0" y="71.0" width="130" height="48" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="285.0" y="71.0" width="130" height="48" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="535.0" y="71.0" width="130" height="48" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="100.0" y="90.9" font-size="11.5" text-anchor="middle" font-weight="700" >author</text>
  <text x="100.0" y="106.9" font-size="10" text-anchor="middle" opacity="0.85" >(relation)</text>
  <text x="350.0" y="90.9" font-size="11.5" text-anchor="middle" font-weight="700" >UK authors</text>
  <text x="350.0" y="106.9" font-size="10" text-anchor="middle" opacity="0.85" >(relation)</text>
  <text x="600.0" y="90.9" font-size="11.5" text-anchor="middle" font-weight="700" >their names</text>
  <text x="600.0" y="106.9" font-size="10" text-anchor="middle" opacity="0.85" >(relation)</text>
  <text x="225.0" y="89.0" font-size="9.5" text-anchor="middle" opacity="0.75" >σ  country='UK'</text>
  <text x="475.0" y="89.0" font-size="9.5" text-anchor="middle" opacity="0.75" >π  name</text>
  </g>
  <text x="350.0" y="168" text-anchor="middle" font-size="11" opacity="0.9">π name ( σ country='UK' ( author ) )  —  every operation takes a relation and returns a relation.</text>
</svg>
```

This is the deep reason SQL can be **declarative**. You write the *expression* — the
result you want — and the database is free to evaluate it however it likes: it can reorder
the operations, use an index, or pick a join strategy, as long as the answer matches the
algebra. That freedom is the query planner of Lesson 10, and it only exists because the
model is math.

### Physical vs. logical: data independence

Codd's other gift was **data independence**: the *logical* view (tables and columns you
query) is completely separate from the *physical* reality (bytes, files, indexes, B-trees
on disk). You ask for "UK authors" and never say *how* to find them. The database can
change how it stores the data — add an index, reorganize files, upgrade the storage
engine — and your queries keep working unchanged. In the pointer-navigating databases
before 1970, the query *was* the physical path, so any storage change broke every program.
Separating the two is what made databases something you could build a durable application
on top of.

### Meet SQL — briefly

**SQL (Structured Query Language)** is the language that speaks relational algebra in words.
It became an ANSI standard in 1986 and an ISO standard in 1987, so the same core language
works across Postgres, MySQL, SQLite, and the rest. Its defining trait is that it's
**declarative** — *what*, not *how*:

```sql
-- "Give me the names of authors from the UK." You describe the result;
-- you never write a loop or say which index to use.
SELECT name
FROM author
WHERE country = 'UK';
```

That's `π_name( σ_country='UK'(author) )` from above, in SQL's clothing: `SELECT` is
project, `FROM` names the relation, `WHERE` is select. SQL splits into two halves you'll
hear named constantly:

- **DDL — Data Definition Language**: statements that define *shape* — `CREATE TABLE`,
  `ALTER TABLE`, `DROP TABLE`. This is how you declare a schema.
- **DML — Data Manipulation Language**: statements that work with *data* — `SELECT`,
  `INSERT`, `UPDATE`, `DELETE`.

And that's genuinely all the SQL you need for this phase. We'll write small snippets to
make ideas concrete, but the syntax, joins, subqueries, window functions, and the rest are
a **separate phase**. Here, SQL is a way to *point at* relational concepts, not the subject
itself. Don't worry about mastering it yet.

### A worked schema

Two relations and the relationship between them (which we'll formalize in Lesson 5):

```sql
-- DDL: define the shape of two relations
CREATE TABLE author (
  id      INTEGER,      -- domain: positive integers
  name    TEXT,         -- domain: text
  country TEXT          -- domain: 2-letter code
);

CREATE TABLE book (
  id        INTEGER,
  title     TEXT,
  author_id INTEGER     -- points at author.id — the seed of a relationship
);
```

The `author` relation:

| id | name | country |
|---|---|---|
| 1 | Ada Lovelace | UK |
| 2 | Grace Hopper | US |
| 3 | Alan Turing | UK |

The `book` relation, whose `author_id` points back at `author.id`:

| id | title | author_id |
|---|---|---|
| 1 | Notes on the Engine | 1 |
| 2 | The Compiler | 2 |
| 3 | On Computable Numbers | 3 |

Two simple relations. A join on `book.author_id = author.id` puts each book beside its
author — no pointers, no navigation, just matching values. Everything else in this phase
is about making this fast (indexes), safe (constraints, transactions), and durable (the
storage engine) — but the model underneath stays this small.

## Think about it

1. A relation is a *set* of tuples. What two everyday spreadsheet habits does that
   forbid — and why is each restriction actually useful to the database?
2. Someone says "relational databases are called that because tables relate to each
   other." Correct them precisely: where does the name actually come from?
3. Relational algebra is "closed" — every operation returns a relation. Why does that
   property matter for building up a complex query? (Think about chaining.)
4. Your team switches the storage engine and adds three indexes, but no application query
   changes. Which principle of the relational model made that possible?

## Key takeaways

- The relational model's core vocabulary: a **relation** (table) is a set of **tuples**
  (rows) over named **attributes** (columns), each drawn from a **domain** (its allowed
  values).
- A relation is a **set** — no duplicate rows, no inherent order, every value **atomic** —
  and those restrictions are exactly what make the data mechanically queryable.
- **"Relational" means relations (tables)**, not relationships between tables — a
  persistent and worth-fixing misconception.
- **Relational algebra** (select, project, join, …) is closed: operations take relations
  and return relations, so any query is an expression you can chain — which is why SQL can
  be **declarative** (describe the result, let the planner choose how).
- **Data independence** separates the logical tables you query from the physical bytes on
  disk, so storage can change without breaking queries.
- **SQL** is the standardized declarative language (DDL defines shape, DML works with
  data) — introduced here only as far as we need it; it gets its own phase.

Next: [Tables, Columns & Data Types](../04-tables-columns-data-types/) — we zoom into a
single relation and get precise about columns, the type system, and the strange, important
non-value called NULL.
