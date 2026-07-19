# Document Databases

> A key-value store hands back a sealed envelope; a relational database makes you cut every record into a dozen tables and sew them back together with joins. The document model sits between them: store the whole object as one self-describing JSON tree — the way your application already thinks about it — and let the database look *inside* it to answer queries. You trade the iron discipline of a schema for the freedom to let each record be its own shape.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Key-Value Stores](../02-key-value-stores/), [Schema Design & Normalization](../../03-relational-databases/07-schema-design-and-normalization/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/)
**Time:** ~75 minutes

## The Problem

An order arrives in your application as one object: a customer, a shipping address, a list of
line items, each with a product and a quantity. In your code it's a single nested structure —
a dict, an object, one thing. To store it in a relational database, you must **shred** it: the
order goes in `orders`, the address in `addresses` (or a pile of columns), each line item in
`order_items`, each pointing back with foreign keys. To read the order back, you **reassemble**
it with a three- or four-way join. Your application thinks in whole objects; your database
thinks in flat tables; and every read and write pays a tax translating between the two. That tax
has a name — the **object-relational impedance mismatch** — and ORMs exist entirely to hide it.

Now add the second problem from Lesson 1: the *shape* of your objects won't hold still. A book
product has an author and a page count; a laptop has RAM and a CPU; next week marketing adds a
"sustainability score." In a relational table, every one of those is an `ALTER TABLE` migration,
or a swamp of mostly-`NULL` columns, or a tangle of per-type side tables.

The **document database** answers both problems with one move: **store the object as it is.**
Keep the order as a single JSON document — nested line items and all — in a **collection** of
such documents. No shredding, no reassembly, no fixed schema. And unlike the key-value store's
opaque value, the document is **transparent**: the database can read its fields, so you can still
query "all orders over $100 shipped to Berlin." In this lesson you'll build a small document
database — insert, query by nested field, secondary index — and then meet MongoDB and, crucially,
Postgres `JSONB`, which gives you the document model *inside* a relational database.

## The Concept

### The model: a collection of self-describing documents

A **document** is a tree of data — objects, arrays, numbers, strings, booleans — exactly what
JSON expresses (MongoDB stores it as **BSON**, a binary JSON with more types and faster
traversal). A **collection** is a bag of documents, the rough analog of a table. But the analogs
diverge in one decisive way:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 560" width="100%" style="max-width:880px" role="img" aria-label="The same order, modeled two ways. On the left, the relational model: the one order object is shredded across three tables — orders holding id, customer_id and total; addresses holding id, order_id and city, zip, country; and order_items holding id, order_id, sku and qty. The child rows point back at the parent with an order_id foreign key, so one application object becomes four rows across three tables. Reading it back means a SELECT that joins all three tables. The cost is a join on every read and several inserts on every write, but each fact is stored exactly once, so changing the shipping city touches one row. On the right, the document model: the same order is one JSON document containing _id, customer, a nested address object with city and zip, an items array of two sub-documents each with sku and qty, and total. The nested address object is the addresses table inlined; the items array is the order_items table inlined. Reading it back is a single fetch by _id — one seek, nothing to join and nothing to reassemble, and the whole write is atomic. The cost is duplication: embedded data that is shared across many parents, unbounded in size, or updated on its own goes stale in every copy. Both paths converge on the identical order object the application wanted, which is the point: same result, different cost to assemble it.">
  <defs>
    <marker id="p4l3a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p4l3a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One order, modeled two ways — same object out, very different cost to assemble it</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="424" height="354" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="460" y="42" width="424" height="354" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="228" y="66" text-anchor="middle" font-size="12.5" font-weight="700" fill="#3553ff">RELATIONAL — shredded across 3 tables</text>
    <text x="228" y="84" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the app's one object, cut up to fit flat tables</text>
    <text x="672" y="66" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">DOCUMENT — one order, one document</text>
    <text x="672" y="84" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the app's one object, stored exactly as it is</text>

    <g fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.6">
      <rect x="126" y="100" width="196" height="50" rx="8"/>
      <rect x="30" y="194" width="186" height="66" rx="8"/>
      <rect x="238" y="194" width="190" height="66" rx="8"/>
    </g>
    <text x="224" y="120" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">orders</text>
    <text x="224" y="137" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">id · customer_id · total</text>

    <g fill="none" stroke="#3553ff" stroke-width="1.5" stroke-opacity="0.8">
      <path d="M182 150 L128 194"/>
      <path d="M266 150 L330 194"/>
    </g>
    <text x="168" y="178" text-anchor="middle" font-size="8" fill="#3553ff">1:N</text>
    <text x="288" y="178" text-anchor="middle" font-size="8" fill="#3553ff">1:N</text>

    <text x="123" y="214" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">addresses</text>
    <text x="123" y="231" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">id · order_id (FK)</text>
    <text x="123" y="246" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">city · zip · country</text>

    <text x="333" y="214" text-anchor="middle" font-size="10.5" font-weight="700" fill="#3553ff">order_items</text>
    <text x="333" y="231" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">id · order_id (FK)</text>
    <text x="333" y="246" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">sku · qty · one row per item</text>

    <text x="228" y="280" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">one object → 4 rows across 3 tables, glued by foreign keys</text>

    <rect x="30" y="290" width="398" height="58" rx="9" fill="#3553ff" fill-opacity="0.1" stroke="#3553ff" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="229" y="309" text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">read it back = JOIN 3 TABLES</text>
    <text x="229" y="326" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">SELECT … FROM orders o JOIN addresses a</text>
    <text x="229" y="339" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">ON a.order_id=o.id JOIN order_items i ON i.order_id=o.id</text>

    <text x="228" y="368" text-anchor="middle" font-size="8.5" font-weight="700" fill="#e0930f">Cost: a join on every read, 4 inserts on every write —</text>
    <text x="228" y="383" text-anchor="middle" font-size="8.5" fill="#e0930f" opacity="0.9">but each fact is stored once: change the city in ONE row.</text>

    <rect x="474" y="98" width="242" height="172" rx="9" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-width="1.6"/>
    <g font-size="9.5" fill="currentColor">
      <text x="488" y="117">{</text>
      <text x="499" y="130">"_id": "order:501",</text>
      <text x="499" y="143">"customer": "Ada",</text>
      <text x="499" y="156"><tspan fill="#0fa07f" font-weight="700">"address"</tspan>: {</text>
      <text x="510" y="169">"city": "Berlin", "zip": "10115"</text>
      <text x="499" y="182">},</text>
      <text x="499" y="195"><tspan fill="#0fa07f" font-weight="700">"items"</tspan>: [</text>
      <text x="510" y="208">{ "sku": "A-1", "qty": 2 },</text>
      <text x="510" y="221">{ "sku": "B-9", "qty": 1 }</text>
      <text x="499" y="234">],</text>
      <text x="499" y="247">"total": 94.50</text>
      <text x="488" y="260">}</text>
    </g>

    <g fill="none" stroke="#0fa07f" stroke-width="1.4">
      <path d="M723 148 L723 186 M723 167 L729 167"/>
      <path d="M723 188 L723 238 M723 213 L729 213"/>
    </g>
    <text x="733" y="164" font-size="8.5" font-weight="700" fill="#0fa07f">nested object</text>
    <text x="733" y="176" font-size="8" fill="currentColor" opacity="0.8">= addresses, inlined</text>
    <text x="733" y="210" font-size="8.5" font-weight="700" fill="#0fa07f">array of sub-docs</text>
    <text x="733" y="222" font-size="8" fill="currentColor" opacity="0.8">= order_items, inlined</text>

    <text x="672" y="280" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">one object → 1 document: nothing to shred, nothing to rejoin</text>

    <rect x="472" y="290" width="398" height="58" rx="9" fill="#0fa07f" fill-opacity="0.1" stroke="#0fa07f" stroke-opacity="0.55" stroke-width="1.4"/>
    <text x="671" y="309" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">read it back = FETCH 1 DOCUMENT by _id</text>
    <text x="671" y="326" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.9">db.orders.find_one({"_id": "order:501"})</text>
    <text x="671" y="339" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">one seek — and one document = one atomic write</text>

    <text x="672" y="368" text-anchor="middle" font-size="8.5" font-weight="700" fill="#e0930f">Cost: embedding duplicates data — if the nested part is</text>
    <text x="672" y="383" text-anchor="middle" font-size="8.5" fill="#e0930f" opacity="0.9">shared, unbounded, or updated on its own, copies go stale.</text>
  </g>
  <g fill="none" stroke-width="1.7">
    <path d="M228 404 L228 430 L396 430 L396 438" stroke="#3553ff" marker-end="url(#p4l3a-arb)"/>
    <path d="M672 404 L672 430 L504 430 L504 438" stroke="#0fa07f" marker-end="url(#p4l3a-arg)"/>
  </g>
  <text x="302" y="419" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" font-weight="700" fill="#3553ff">read = JOIN 3 tables</text>
  <text x="598" y="419" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9" font-weight="700" fill="#0fa07f">read = fetch 1 document</text>
  <rect x="300" y="442" width="300" height="46" rx="10" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.6"/>
  <text x="450" y="463" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="11" font-weight="700" fill="currentColor">the SAME order object</text>
  <text x="450" y="478" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="8.5" fill="currentColor" opacity="0.8">the one thing your code actually wanted</text>
  <text x="450" y="512" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Both hand the application the identical order object — the difference is what you pay to assemble it.</text>
  <text x="450" y="530" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.9">Relational: each fact stored once, rebuilt with a join. Document: the whole aggregate in one place, duplication instead.</text>
  <text x="450" y="548" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">Hence the rule: embed what is read together, owned, and bounded — reference what is shared, unbounded, or updated on its own.</text>
</svg>
```

Two documents in the same collection **need not have the same fields**. This is the
schema-flexibility win, and it rests on a shift in *when* the schema is checked:

- **Schema-on-write** (relational): the schema is declared up front and the database rejects any
  row that doesn't fit. Correctness is enforced at write time; the data on disk is guaranteed
  uniform.
- **Schema-on-read** (document): there's no enforced schema; any document shape is accepted, and
  *the application* makes sense of the fields when it reads them. Flexibility at write time;
  the burden of "what shape is this?" moves to read time.

That is a real trade, not a free lunch. Schema-on-read means the database will happily store a
typo'd field name or a missing required value — the discipline the relational schema enforced for
you is now yours to keep in application code (which is why document databases grew optional
**schema validation** you can switch on). You gain agility; you owe vigilance.

### The transparent value: querying inside the document

This is the line between a document store and a key-value store, and it's the whole reason the
category exists. In Lesson 2 the value was opaque — you could only fetch it by key. A document
database can **reach into the document** and match on any field, including nested ones and array
elements:

```text
find( type = "book" AND price < 50 )                 → filter on top-level fields
find( address.city = "Berlin" )                      → reach a nested field by path
find( items.sku = "SKU-42" )                         → match an element inside an array
```

Because the fields are visible, the database can also build **secondary indexes** on them —
including nested paths — so those queries don't scan the whole collection. This is the exact
B-tree/hash-index idea from Phase 3, Lesson 9, now applied to schemaless documents: an index maps
a field's value to the set of documents that have it, turning an `O(n)` scan into an `O(1)` (hash)
or `O(log n)` (tree) lookup. You'll build one below and watch it drop a 10,000-document scan to a
single lookup.

### The central design decision: embed or reference?

Here is where document modeling stops being "just dump your objects" and becomes a craft. Real
data has relationships — an order has a customer, a customer has orders, a post has comments. You
have two ways to represent a relationship, and choosing correctly *is* document data modeling:

**Embed** — nest the related data *inside* the parent document:

```json
{ "_id": "order:501", "customer": "Ada",
  "items": [ {"sku": "A-1", "qty": 2}, {"sku": "B-9", "qty": 1} ] }
```

**Reference** — store the related data as separate documents and keep an id pointer, like a
relational foreign key:

```json
{ "_id": "order:501", "customer_id": "cust:7", "item_ids": ["item:1", "item:2"] }
```

The trade is fundamental and worth internalizing:

| | **Embed** | **Reference** |
|---|---|---|
| Read the whole thing | **One fetch**, no join — fast | Multiple fetches / app-side join |
| Data duplication | Yes (embedded copy) | No (single source) |
| Update the related data | Must update every copy | Update once |
| Growth | Document can bloat if the array is unbounded | Parent stays small |
| Atomicity | **One document = one atomic write** | Spans documents (harder) |

The guidance that falls out of that table:

- **Embed when** the related data is *read together* with its parent, *owned by* it, and
  *bounded* in size: line items in an order, an address on a user, a handful of comments. The
  document is the natural **aggregate** — the unit you load and save as a whole. (This is
  Domain-Driven Design's "aggregate" made physical.)
- **Reference when** the related data is *shared* across many parents (a product referenced by
  thousands of orders — you don't want thousands of copies), *unbounded* (a celebrity's millions
  of followers can't live in one document), or *queried independently*.

Notice what embedding does: it **denormalizes on purpose.** In Phase 3 you learned normalization —
store each fact once — as a virtue. The document model deliberately breaks it to make the common
read a single fetch. And so the ghost that normalization banished comes back: the **update
anomaly.** If you embed a product's name into every order and the name changes, you now have a
thousand stale copies. The document world's answer isn't "never denormalize" — it's "denormalize
data that *doesn't change* (a snapshot of the price *at time of order* is often exactly what you
want anyway), and reference data that does." Choosing per-relationship is the skill.

### Atomicity: the document is the transaction boundary

One more property matters enormously. In most document databases, **a write to a single document
is atomic** — it lands completely or not at all, even if it updates ten nested fields. But a write
spanning *multiple* documents historically was not (MongoDB added multi-document ACID transactions
in 2018, but they're heavier and used sparingly). This is the deep reason the aggregate boundary
matters: **draw your document boundaries around the data that must change together.** If an order
and its line items must always be consistent, embedding them in one document makes every update
atomic for free. Split them across documents and you've handed yourself a distributed-consistency
problem. The document boundary isn't just a storage choice — it's your unit of atomicity.

## Build It

Let's build a document database that can do the thing a key-value store can't: **look inside the
value.** It stores JSON documents in named collections, matches queries on top-level *and nested*
fields with operators (`$gt`, `$lt`, `$in`), and builds a secondary index to make equality lookups
`O(1)`. Standard library only — `json` is all we need, because a document *is* JSON.

The heart is two small functions. First, walking a dotted path into a nested document — this is
what makes `address.city` work:

```python
_MISSING = object()   # a path that doesn't exist ≠ a stored null

def resolve_path(doc, path):
    cur = doc
    for part in path.split("."):          # "specs.ram_gb" -> ["specs", "ram_gb"]
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return _MISSING               # missing field never matches (doesn't crash/match null)
    return cur
```

Second, deciding whether a document matches a query. A query is a dict of `field → condition`,
where a condition is either a value (equality) or an operator dict like `{"$gt": 16}`. All
conditions must hold (implicit AND):

```python
def matches(doc, query):
    for path, condition in query.items():
        actual = resolve_path(doc, path)
        if isinstance(condition, dict) and any(k.startswith("$") for k in condition):
            for op, operand in condition.items():
                if op == "$eq" and not (actual is not _MISSING and actual == operand): return False
                if op == "$gt" and not (actual is not _MISSING and actual >  operand): return False
                if op == "$lt" and not (actual is not _MISSING and actual <  operand): return False
                if op == "$in" and not (actual is not _MISSING and actual in operand): return False
        else:
            if actual is _MISSING or actual != condition:
                return False
    return True
```

A collection stores documents by `_id` and can build a secondary index — a map from a field's
value to the set of document ids that have it. `find` uses the index when it can, and falls back
to a full scan when it can't (exactly what a real query planner does):

```python
class Collection:
    def __init__(self):
        self.docs = {}                    # _id -> document
        self.indexes = {}                 # field -> { value -> set(_id) }
        self.scans_last_find = 0          # instrumentation: how many docs we examined

    def create_index(self, field):        # value -> set of ids, for O(1) equality lookups
        idx = {}
        for _id, doc in self.docs.items():
            val = resolve_path(doc, field)
            if val is not _MISSING:
                idx.setdefault(val, set()).add(_id)
        self.indexes[field] = idx

    def find(self, query, projection=None):
        self.scans_last_find = 0
        candidates = None                 # try to use an index for one equality field
        for field, cond in query.items():
            if field in self.indexes and not isinstance(cond, dict):
                candidates = self.indexes[field].get(cond, set())
                break
        source = (self.docs[i] for i in candidates) if candidates is not None else self.docs.values()
        results = []
        for doc in source:
            self.scans_last_find += 1
            if matches(doc, query):
                results.append(doc)
        return results
```

Running `python docdb.py` stores a book, a laptop, and more — documents with *different fields* in
one collection — then queries them:

```console
$ python docdb.py
== Query by a top-level field ==
  {'_id': 'p:1', 'title': 'SICP', 'author': 'Abelson'}
  {'_id': 'p:3', 'title': 'SQL for Smarties', 'author': 'Celko'}

== Query a NESTED field with dot notation ==
  {'_id': 'p:2', 'title': 'ThinkPad X1', 'specs': {'ram_gb': 32, 'cpu': 'i7'}}

== Index: turn an O(n) scan into an O(1) lookup ==
  without index: examined 10003 docs
  with index:    examined 1 docs
```

Look at the last two lines — that's the whole value of an index, made visible. Finding one
document by `sku` in a 10,000-document collection examined all 10,003 without an index and exactly
**1** with one. The book and the laptop coexisting in one collection with different fields is the
schema-flexibility win. And every query reached *inside* the documents — the thing the key-value
store of Lesson 2 fundamentally cannot do.

## Use It

**MongoDB** is the document database most people mean by the term. Its query language is your
`find`, grown up — the same `field → condition` shape, with a large operator vocabulary and an
**aggregation pipeline** for grouping and transforming. Your Build-It maps to it almost line for
line:

```python
# MongoDB via pymongo. The query documents are exactly the shape you just built.
from pymongo import MongoClient
db = MongoClient("mongodb://localhost:27017").shop
db.products.insert_one({"type": "laptop", "title": "ThinkPad X1",
                        "specs": {"ram_gb": 32, "cpu": "i7"}, "price": 1600})

db.products.find({"type": "book", "price": {"$lt": 50}})   # your matches(), as a query
db.products.find({"specs.ram_gb": {"$gt": 16}})            # your resolve_path(), as dot notation
db.products.create_index("sku")                            # your create_index()
```

But here is the lesson that separates a mid-level engineer from a senior one, and it circles back
to Lesson 1: **you may not need a separate document database at all.** Postgres has a `JSONB`
column type — binary JSON, *indexable*, queryable — that gives you the document model **inside a
relational database**, with full ACID transactions and the option to join it to normal tables:

```sql
-- A relational table with a schemaless JSONB column: document flexibility, relational guarantees.
CREATE TABLE products (id bigserial PRIMARY KEY, doc jsonb);
INSERT INTO products (doc) VALUES
  ('{"type":"laptop","title":"ThinkPad X1","specs":{"ram_gb":32}}');

SELECT doc->>'title' FROM products WHERE doc->>'type' = 'book' AND (doc->>'price')::int < 50;
SELECT doc FROM products WHERE doc->'specs'->>'ram_gb' > '16';   -- reach a nested field
CREATE INDEX ON products USING gin (doc);                        -- index the whole document
```

This is the single most important practical takeaway of the lesson. For a great many "we need a
document database" situations, the honest answer is: **use a `JSONB` column in the Postgres you're
already running.** You get schema flexibility *and* transactions *and* the ability to keep your
transactional data relational and your flexible data document-shaped in the same database — no
second system to operate (Lesson 8). Reach for a dedicated MongoDB when the document workload is
large enough, or the horizontal-scale and operational-tooling needs are specialized enough, to
justify a whole new store — not by reflex.

Whichever you use, the modeling discipline is identical, and it's the part people get wrong:

- **Draw document boundaries around aggregates** — the data that's read together and must change
  together. That boundary is also your atomicity boundary.
- **Embed the bounded and owned; reference the shared and unbounded.** An order's line items:
  embed. A product referenced by every order: reference (or embed a *snapshot* of just the fields
  you need at order time, like name and price — often the correct choice).
- **Watch unbounded arrays.** An `items: [...]` that grows without limit turns one document into a
  slow, ever-growing object. If it can grow forever (a user's activity log), reference it out.
- **Index the fields you query**, exactly as in the relational world — and pay the same write cost
  for each index (Phase 3, Lesson 9).

## Key takeaways

- A **document database** stores each record as one self-describing **JSON/BSON document** in a
  **collection**, matching your application's object model — no shredding into tables, no join to
  reassemble (the **impedance mismatch** disappears).
- Unlike a key-value store's opaque value, a document is **transparent**: the database queries
  *inside* it — top-level fields, **nested paths**, array elements — and builds **secondary
  indexes** on those fields to avoid full scans.
- It's **schema-on-read**, not schema-on-write: documents in one collection can have different
  shapes (flexibility), but the correctness the relational schema enforced is now the
  application's job (vigilance) — hence optional schema validation.
- The core modeling decision is **embed vs. reference**. Embed data that's read-together, owned,
  and bounded (deliberate **denormalization** → one fast, atomic fetch); reference data that's
  shared, unbounded, or queried on its own. The **document boundary is your unit of atomicity** —
  draw it around what must change together.
- You often **don't need a separate document database**: Postgres **`JSONB`** gives you queryable,
  indexable documents *with* ACID transactions inside a database you already run. Reach for a
  dedicated MongoDB when scale or specialized needs genuinely justify a second system.

Next: [Wide-Column Stores](../04-wide-column-stores/) — when even a document store can't absorb
the write volume, we distribute writes across a whole cluster and meet the LSM-tree, the
write-optimized cousin of the B-tree.
