# Data Modeling by Access Pattern

> Relational modeling lets you store data cleanly first and figure out the queries later — the planner adapts. Every NoSQL store takes that freedom away: no joins, look up by key, and the query you didn't design for is a full-table scan or simply impossible. So you invert the whole process — **list the queries first, then design the keys so each one is a single cheap lookup.** This is the meta-skill the whole phase was building toward, and single-table design is its sharpest edge.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Key-Value Stores](../02-key-value-stores/), [Document Databases](../03-document-databases/), [Wide-Column Stores](../04-wide-column-stores/), [Schema Design & Normalization](../../03-relational-databases/07-schema-design-and-normalization/)
**Time:** ~75 minutes

## The Problem

You've now met every NoSQL family — key-value, document, wide-column, time-series, graph — and each
one punished you for the same instinct: the relational reflex to normalize the data and join it back
together at read time. There are no joins. You fetch by key. If you want related data together, you
store it together.

That constraint sounds like a limitation until you realize it demands a completely different *design
process*, and getting that process wrong is the single most expensive mistake in NoSQL. Here's the
trap in miniature. You're building an e-commerce backend on DynamoDB, and you model it the way Phase 3
taught you — clean, normalized, one table per entity:

```text
customers(id, name, tier)
orders(id, customer_id, date, status, total)
order_items(id, order_id, sku, qty)
```

Then the access patterns arrive:

1. Get a customer's profile.
2. Get all of a customer's orders, newest first.
3. Get an order with its line items.
4. Get all orders in a given status.

In Postgres, all four are trivial — a `WHERE` and a couple of joins, and the planner figures out the
rest. On DynamoDB, **you cannot join `orders` to `order_items`.** To assemble "an order with its
items" you'd fetch the order by key, then make a *second* request for its items — the N+1 problem
(Phase 3, Lesson 14) baked into your data model. "All of a customer's orders" means querying the
`orders` table by `customer_id`, which isn't its key, so you're forced into a **Scan** — reading
*every order in the system* and throwing most away. The normalized design that was a virtue in
Phase 3 is a catastrophe here.

The fix isn't a better query. It's a different *order of operations*: **you write the list of access
patterns down first, and then you design the keys — and often a single table — so that every one of
those patterns is a direct key lookup.** This lesson is that discipline, and by the end you'll have
built the tool that expresses it best: **single-table design**, where customers, orders, and items
all live in one table, arranged so the joins you can't do are pre-assembled by the key layout.

## The Concept

### The inversion: query-first, not data-first

Sit the two philosophies side by side, because internalizing the flip is the whole lesson:

| | **Relational (data-first)** | **NoSQL (query-first)** |
|---|---|---|
| Step 1 | Model the data: normalize into clean tables | List every access pattern you must serve |
| Step 2 | Add constraints and keys | Design keys so each pattern is one lookup |
| Reads | Any query; the planner joins and adapts | Only what you keyed for; no joins |
| New query later | Just write the `SELECT` | May need a new index, or a data migration |
| Optimizes for | Flexibility and correctness | Predictable `O(1)` reads at scale |

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 490" width="100%" style="max-width:880px" role="img" aria-label="The inversion, shown as two design pipelines that run in opposite directions through the same three stages: the queries, the keys, and the data. In the relational panel on the left the process starts at the bottom, at the data: step one is to model the data by normalizing it into clean customers, orders and order_items tables; step two is to add constraints and keys; and only at the top, step three, do you write whatever query you like, because the planner joins and adapts. The arrows therefore run upward, from data toward queries. In the NoSQL panel on the right the process starts at the top, at the queries: step one is to list every access pattern first, such as a customer's profile, their orders newest first, an order with its line items, and all orders in a given status; step two is to design the keys around that list, for example partition key CUSTOMER#c-1 and sort key ORDER#date#id, so that every pattern is a single-partition lookup; and only then, step three at the bottom, do you store the data in one table laid out the way the reads want it. The arrows therefore run downward, from queries toward data. The bottom bands give the honest bill. On the relational side a new query later is just a new SELECT with no schema change, optimizing for flexibility and correctness, at the cost that joins and ad-hoc queries do not scale across nodes. On the NoSQL side a query you did not design for becomes a full scan of every item, or is simply impossible, and adding a pattern later means a new secondary index or a data migration, in exchange for predictable constant-time reads at scale.">
  <defs>
    <marker id="p4l7a-arb" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p4l7a-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">The inversion &#8212; relational starts from the data, NoSQL starts from the queries</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="20" y="44" width="396" height="298" rx="12" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.7" stroke-width="1.8"/>
    <rect x="484" y="44" width="396" height="298" rx="12" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.7" stroke-width="1.8"/>

    <text x="218" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#3553ff">RELATIONAL &#183; data-first</text>
    <text x="682" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">NoSQL &#183; query-first</text>
    <text x="218" y="86" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">the planner adapts to whatever you ask</text>
    <text x="682" y="86" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.8">the keys ARE the questions you may ask</text>

    <text x="450" y="134" text-anchor="middle" font-size="8" font-weight="700" fill="currentColor" opacity="0.6">THE QUERIES</text>
    <text x="450" y="214" text-anchor="middle" font-size="8" font-weight="700" fill="currentColor" opacity="0.6">THE KEYS</text>
    <text x="450" y="294" text-anchor="middle" font-size="8" font-weight="700" fill="currentColor" opacity="0.6">THE DATA</text>

    <rect x="32" y="102" width="372" height="58" rx="9" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-width="1.5"/>
    <rect x="32" y="182" width="372" height="58" rx="9" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-width="1.5"/>
    <rect x="32" y="262" width="372" height="58" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2.1"/>

    <text x="44" y="282" font-size="10.5" font-weight="700" fill="#3553ff">STEP 1 &#183; MODEL THE DATA</text>
    <text x="392" y="282" text-anchor="end" font-size="7.5" font-weight="700" fill="#3553ff">START HERE</text>
    <text x="44" y="298" font-size="9" fill="currentColor">normalize into clean tables &#8212; a faithful model of the domain</text>
    <text x="44" y="312" font-size="8.5" fill="currentColor" opacity="0.75">customers &#183; orders &#183; order_items</text>

    <text x="44" y="202" font-size="10.5" font-weight="700" fill="#3553ff">STEP 2 &#183; ADD CONSTRAINTS AND KEYS</text>
    <text x="44" y="218" font-size="9" fill="currentColor">primary keys, foreign keys, a few indexes</text>
    <text x="44" y="232" font-size="8.5" fill="currentColor" opacity="0.75">the queries are still an afterthought at this point</text>

    <text x="44" y="122" font-size="10.5" font-weight="700" fill="#3553ff">STEP 3 &#183; THEN WRITE ANY QUERY YOU LIKE</text>
    <text x="44" y="138" font-size="9" fill="currentColor">the planner joins and adapts &#8212; nothing to redesign</text>
    <text x="44" y="152" font-size="8.5" fill="currentColor" opacity="0.75">all four access patterns: a WHERE and a couple of JOINs</text>

    <g fill="none" stroke="#3553ff" stroke-width="2">
      <path d="M218 262 L218 244" marker-end="url(#p4l7a-arb)"/>
      <path d="M218 182 L218 164" marker-end="url(#p4l7a-arb)"/>
    </g>
    <text x="218" y="336" text-anchor="middle" font-size="8.5" font-weight="700" fill="#3553ff">time runs &#8593; UPWARD &#183; data &#8594; keys &#8594; queries</text>

    <rect x="496" y="102" width="372" height="58" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2.1"/>
    <rect x="496" y="182" width="372" height="58" rx="9" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.5"/>
    <rect x="496" y="262" width="372" height="58" rx="9" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.5"/>

    <text x="508" y="122" font-size="10.5" font-weight="700" fill="#0fa07f">STEP 1 &#183; LIST EVERY ACCESS PATTERN</text>
    <text x="856" y="122" text-anchor="end" font-size="7.5" font-weight="700" fill="#0fa07f">START HERE</text>
    <text x="508" y="138" font-size="9" fill="currentColor">1. a customer&#8217;s profile  &#183;  2. their orders, newest first</text>
    <text x="508" y="152" font-size="8.5" fill="currentColor" opacity="0.75">3. an order with its line items  &#183;  4. all orders in a status</text>

    <text x="508" y="202" font-size="10.5" font-weight="700" fill="#0fa07f">STEP 2 &#183; DESIGN THE KEYS AROUND THAT LIST</text>
    <text x="508" y="218" font-size="9" fill="currentColor">PK = CUSTOMER#c-1  &#183;  SK = ORDER#&#60;date&#62;#&#60;id&#62;</text>
    <text x="508" y="232" font-size="8.5" fill="currentColor" opacity="0.75">so every pattern above is ONE single-partition lookup</text>

    <text x="508" y="282" font-size="10.5" font-weight="700" fill="#0fa07f">STEP 3 &#183; ONLY THEN STORE THE DATA</text>
    <text x="508" y="298" font-size="9" fill="currentColor">one table, items laid out the way the reads want them</text>
    <text x="508" y="312" font-size="8.5" fill="currentColor" opacity="0.75">the schema is a physical answer to a fixed set of questions</text>

    <g fill="none" stroke="#0fa07f" stroke-width="2">
      <path d="M682 160 L682 178" marker-end="url(#p4l7a-arg)"/>
      <path d="M682 240 L682 258" marker-end="url(#p4l7a-arg)"/>
    </g>
    <text x="682" y="336" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">time runs &#8595; DOWNWARD &#183; queries &#8594; keys &#8594; data</text>

    <rect x="20" y="356" width="396" height="76" rx="11" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.6" stroke-width="1.6"/>
    <text x="34" y="376" font-size="10.5" font-weight="700" fill="#3553ff">A NEW QUERY LATER</text>
    <text x="34" y="392" font-size="9" fill="currentColor">just write the SELECT &#183; no schema change at all</text>
    <text x="34" y="412" font-size="9.5" fill="currentColor">OPTIMIZES FOR: flexibility and correctness</text>
    <text x="34" y="426" font-size="8.5" fill="#e0930f">the bill: joins and ad-hoc scans stop scaling across nodes</text>

    <rect x="484" y="356" width="396" height="76" rx="11" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.6" stroke-width="1.6"/>
    <text x="498" y="376" font-size="10.5" font-weight="700" fill="#e0930f">A QUERY YOU DIDN&#8217;T DESIGN FOR</text>
    <text x="498" y="392" font-size="9" fill="#d64545">a full Scan &#8212; read every item &#8212; or simply impossible</text>
    <text x="498" y="412" font-size="9.5" fill="currentColor">OPTIMIZES FOR: predictable O(1) reads at scale</text>
    <text x="498" y="426" font-size="8.5" fill="#e0930f">the bill: a pattern added later = a new GSI, or a migration</text>
  </g>
  <text x="450" y="458" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">Relational lets you defer the queries; NoSQL makes you commit to them before you store a single item.</text>
  <text x="450" y="476" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">That is why you default to relational until the access patterns stabilize and scale genuinely forces you out.</text>
</svg>
```

In the relational world, the schema is a faithful model of the *domain*, and queries are an
afterthought the planner handles. In the NoSQL world, **the schema is a physical answer to a fixed set
of questions.** You are not modeling the data; you are modeling the *reads*. This is the same law you
met in Lesson 4 ("model queries, not data") for Cassandra — here it becomes the general discipline for
every NoSQL store, and the reason you *default to relational until your access patterns are stable and
your scale forces you out* (Lesson 1): query-first modeling trades away exactly the flexibility a young,
changing product needs most.

### The vocabulary of keys: partition key + sort key

Nearly every scalable NoSQL store gives you a two-part key, and the two parts do two different jobs
(you saw this exact split in wide-column stores, Lesson 4):

- The **partition key** (DynamoDB's *hash key*, Cassandra's *partition key*) decides **which node**
  an item lives on, by hashing (Lesson 2's consistent hashing). All items sharing a partition key live
  together, and you must supply it on every efficient read — it's how the cluster finds your data.
- The **sort key** (DynamoDB's *range key*, Cassandra's *clustering key*) decides the **order of items
  within a partition**, and lets you slice a *range*: "items whose sort key begins with `ORDER#`,"
  "items between two timestamps," newest-first or oldest-first.

The move that unlocks everything is to **encode meaning into the keys** — not `id = 42`, but
`PK = CUSTOMER#c-1`, `SK = ORDER#2024-06-11#o-620`. The prefix (`CUSTOMER#`, `ORDER#`) namespaces the
entity; the structured sort key encodes hierarchy and order you can then range-query.

### Single-table design and the item collection

Here's the practice that makes experienced relational engineers wince and then convert:
**put multiple entity types in one table**, co-located by partition key, so a parent and its children
come back together in a single query. That group of items sharing a partition key is an **item
collection** — and it is the join you can't do, precomputed by how you laid out the keys.

Model the e-commerce example as one table:

```text
 PK                SK                       entity        attributes
 CUSTOMER#c-1      #PROFILE                 customer      name=Ada, tier=gold
 CUSTOMER#c-1      ORDER#2024-05-02#o-500   order_ref     status=PAID
 CUSTOMER#c-1      ORDER#2024-06-11#o-620   order_ref     status=SHIPPED
 ORDER#o-620       #META                    order         status=SHIPPED
 ORDER#o-620       ITEM#01                  order_item    sku=LAPTOP-9
 ORDER#o-620       ITEM#02                  order_item    sku=MOUSE-3
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 592" width="100%" style="max-width:880px" role="img" aria-label="Single-table design and the item collection. The two parts of the key do two different jobs: the partition key, PK, is hashed to pick which node an item is stored on, so every item sharing a partition key sits together and you must supply it on every fast read; the sort key, SK, orders the items inside one partition and lets you take a range slice, such as sort keys beginning with ORDER# read in reverse for newest first. Below that, one table holds three different entity types. The first item collection is everything under PK equals CUSTOMER#c-1: a customer item with sort key #PROFILE holding name Ada and tier gold, and two order_ref items with sort keys ORDER#2024-05-02#o-500 status PAID and ORDER#2024-06-11#o-620 status SHIPPED. The second item collection is everything under PK equals ORDER#o-620: an order item with sort key #META status SHIPPED, and two order_item rows with sort keys ITEM#01 sku LAPTOP-9 and ITEM#02 sku MOUSE-3. A dashed link marks that the same order o-620 appears in both partitions, duplicated on write so that each read stays a single lookup. On the right, one Query on PK equals CUSTOMER#c-1 returns the whole collection, profile and both orders together in sort-key order, and adding SK begins_with ORDER# with reverse returns just the orders newest first, examining three items instead of the twelve in the table. A second Query on PK equals ORDER#o-620 returns the #META header plus ITEM#01 and ITEM#02, which is the join you cannot do, precomputed. At the bottom, the relational equivalent needs three tables, customers, orders and order_items, wired by two joins that the planner reassembles on every read, whereas the single table needs one table, zero joins and one request because the key layout already did the work. The closing warning is that there are no joins to fall back on, so a pattern the keys do not serve is a full scan, or a secondary index you add on purpose.">
  <defs>
    <marker id="p4l7b-arg" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="450" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">One table, three entity types &#8212; the item collection IS the join, precomputed by the keys</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="20" y="42" width="428" height="56" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.6"/>
    <text x="34" y="61" font-size="11" font-weight="700" fill="#7c5cff">PARTITION KEY &#183; PK &#8212; WHERE the item lives</text>
    <text x="34" y="78" font-size="9" fill="currentColor">hashed &#8594; picks which NODE the item is stored on</text>
    <text x="34" y="92" font-size="8.5" fill="currentColor" opacity="0.8">items sharing a PK sit together &#183; required on every fast read</text>

    <rect x="452" y="42" width="428" height="56" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="1.6"/>
    <text x="466" y="61" font-size="11" font-weight="700" fill="#e0930f">SORT KEY &#183; SK &#8212; the ORDER inside a partition</text>
    <text x="466" y="78" font-size="9" fill="currentColor">range slice: SK begins_with &#8220;ORDER#&#8221; &#183; reversed = newest first</text>
    <text x="466" y="92" font-size="8.5" fill="currentColor" opacity="0.8">so &#8220;their orders since March&#8221; is a slice, never a scan</text>

    <text x="44" y="118" font-size="9" font-weight="700" fill="#7c5cff" opacity="0.9">PK</text>
    <text x="170" y="118" font-size="9" font-weight="700" fill="#e0930f" opacity="0.9">SK</text>
    <text x="330" y="118" font-size="9" font-weight="700" fill="currentColor" opacity="0.6">entity</text>
    <text x="418" y="118" font-size="9" font-weight="700" fill="currentColor" opacity="0.6">attributes</text>

    <rect x="20" y="128" width="576" height="104" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.8" stroke-width="1.7"/>
    <text x="44" y="146" font-size="9.5" font-weight="700" fill="#7c5cff">ITEM COLLECTION &#183; everything under PK = CUSTOMER#c-1</text>

    <text x="44" y="172" font-size="9" fill="#7c5cff">CUSTOMER#c-1</text>
    <text x="170" y="172" font-size="9" fill="#e0930f">#PROFILE</text>
    <text x="330" y="172" font-size="9" fill="currentColor" opacity="0.65">customer</text>
    <text x="418" y="172" font-size="9" fill="currentColor">name=Ada, tier=gold</text>

    <text x="44" y="196" font-size="9" fill="#7c5cff">CUSTOMER#c-1</text>
    <text x="170" y="196" font-size="9" fill="#e0930f">ORDER#2024-05-02#o-500</text>
    <text x="330" y="196" font-size="9" fill="currentColor" opacity="0.65">order_ref</text>
    <text x="418" y="196" font-size="9" fill="currentColor">status=PAID</text>

    <text x="44" y="220" font-size="9" fill="#7c5cff">CUSTOMER#c-1</text>
    <text x="170" y="220" font-size="9" fill="#e0930f">ORDER#2024-06-11#o-620</text>
    <text x="330" y="220" font-size="9" fill="currentColor" opacity="0.65">order_ref</text>
    <text x="418" y="220" font-size="9" fill="currentColor">status=SHIPPED</text>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.5" stroke-dasharray="3 4">
      <path d="M528 216 L566 216 L566 308 L528 308"/>
    </g>
    <circle cx="528" cy="216" r="2.6" fill="#7f7f7f"/>
    <circle cx="528" cy="308" r="2.6" fill="#7f7f7f"/>
    <text x="44" y="254" font-size="8.5" fill="currentColor" opacity="0.85">the SAME order o-620 lives in BOTH partitions &#8212; duplicated on write so each read is one lookup</text>

    <rect x="20" y="268" width="576" height="104" rx="10" fill="#7c5cff" fill-opacity="0.06" stroke="#7c5cff" stroke-opacity="0.8" stroke-width="1.7"/>
    <text x="44" y="286" font-size="9.5" font-weight="700" fill="#7c5cff">ITEM COLLECTION &#183; everything under PK = ORDER#o-620</text>

    <text x="44" y="312" font-size="9" fill="#7c5cff">ORDER#o-620</text>
    <text x="170" y="312" font-size="9" fill="#e0930f">#META</text>
    <text x="330" y="312" font-size="9" fill="currentColor" opacity="0.65">order</text>
    <text x="418" y="312" font-size="9" fill="currentColor">status=SHIPPED</text>

    <text x="44" y="336" font-size="9" fill="#7c5cff">ORDER#o-620</text>
    <text x="170" y="336" font-size="9" fill="#e0930f">ITEM#01</text>
    <text x="330" y="336" font-size="9" fill="currentColor" opacity="0.65">order_item</text>
    <text x="418" y="336" font-size="9" fill="currentColor">sku=LAPTOP-9</text>

    <text x="44" y="360" font-size="9" fill="#7c5cff">ORDER#o-620</text>
    <text x="170" y="360" font-size="9" fill="#e0930f">ITEM#02</text>
    <text x="330" y="360" font-size="9" fill="currentColor" opacity="0.65">order_item</text>
    <text x="418" y="360" font-size="9" fill="currentColor">sku=MOUSE-3</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.7">
      <path d="M614 180 L600 180" marker-end="url(#p4l7b-arg)"/>
      <path d="M614 320 L600 320" marker-end="url(#p4l7b-arg)"/>
    </g>

    <rect x="616" y="128" width="264" height="104" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7"/>
    <text x="628" y="148" font-size="9" font-weight="700" fill="#0fa07f">ONE Query &#8594; the whole collection</text>
    <text x="628" y="166" font-size="8" fill="currentColor">Query(PK = &#8220;CUSTOMER#c-1&#8221;)</text>
    <text x="628" y="179" font-size="7.5" fill="currentColor" opacity="0.8">&#8594; profile + both orders, in sort-key order</text>
    <text x="628" y="197" font-size="8" fill="currentColor">&#8230; SK begins_with &#8220;ORDER#&#8221;, reverse</text>
    <text x="628" y="210" font-size="7.5" fill="currentColor" opacity="0.8">&#8594; just the orders, newest first</text>
    <text x="628" y="226" font-size="7.5" font-weight="700" fill="#0fa07f">1 request &#183; 3 items examined, not 12</text>

    <rect x="616" y="268" width="264" height="104" rx="10" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f" stroke-width="1.7"/>
    <text x="628" y="288" font-size="9" font-weight="700" fill="#0fa07f">ONE Query = THE JOIN</text>
    <text x="628" y="306" font-size="8" fill="currentColor">Query(PK = &#8220;ORDER#o-620&#8221;)</text>
    <text x="628" y="319" font-size="7.5" fill="currentColor" opacity="0.8">&#8594; #META header + ITEM#01 + ITEM#02</text>
    <text x="628" y="337" font-size="7.5" fill="currentColor">the order WITH its line items in a single</text>
    <text x="628" y="350" font-size="7.5" fill="currentColor">read &#8212; the join you cannot do, precomputed</text>
    <text x="628" y="366" font-size="7.5" font-weight="700" fill="#0fa07f">1 request &#183; 3 items examined</text>

    <rect x="20" y="394" width="428" height="112" rx="11" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.7" stroke-width="1.7"/>
    <text x="34" y="416" font-size="11" font-weight="700" fill="#3553ff">RELATIONAL &#8212; the join happens at READ time</text>
    <rect x="36" y="432" width="112" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.5"/>
    <rect x="166" y="432" width="92" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.5"/>
    <rect x="276" y="432" width="118" height="32" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.5"/>
    <text x="92" y="452" text-anchor="middle" font-size="9" fill="currentColor">customers</text>
    <text x="212" y="452" text-anchor="middle" font-size="9" fill="currentColor">orders</text>
    <text x="335" y="452" text-anchor="middle" font-size="9" fill="currentColor">order_items</text>
    <g fill="none" stroke="#7f7f7f" stroke-width="1.5">
      <path d="M148 448 L166 448"/>
      <path d="M258 448 L276 448"/>
    </g>
    <text x="157" y="426" text-anchor="middle" font-size="6.5" font-weight="700" fill="#7f7f7f">JOIN</text>
    <text x="267" y="426" text-anchor="middle" font-size="6.5" font-weight="700" fill="#7f7f7f">JOIN</text>
    <text x="34" y="480" font-size="9" fill="currentColor">SELECT &#8230; FROM customers JOIN orders JOIN order_items</text>
    <text x="34" y="496" font-size="8.5" fill="currentColor" opacity="0.75">3 tables &#183; 2 joins &#183; the planner reassembles on every read</text>

    <rect x="452" y="394" width="428" height="112" rx="11" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.7" stroke-width="1.7"/>
    <text x="466" y="416" font-size="11" font-weight="700" fill="#0fa07f">SINGLE TABLE &#8212; the join was done at WRITE time</text>
    <rect x="560" y="432" width="212" height="32" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.5"/>
    <text x="666" y="452" text-anchor="middle" font-size="9" fill="currentColor">one table &#183; (PK, SK)</text>
    <text x="466" y="480" font-size="9" fill="currentColor">Query(PK = &#8220;CUSTOMER#c-1&#8221;)</text>
    <text x="466" y="496" font-size="8.5" fill="currentColor" opacity="0.75">1 table &#183; 0 joins &#183; 1 request &#183; the keys did the work already</text>
  </g>
  <text x="450" y="530" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="9.5" fill="#d64545">There are no joins to fall back on: a pattern the keys don&#8217;t serve is a full Scan &#8212; or a GSI you add on purpose.</text>
  <text x="450" y="556" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">The partition key says WHERE an item lives; the sort key says in WHAT ORDER &#8212; together they pre-assemble the join.</text>
  <text x="450" y="574" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.75">The price is denormalization: order o-620 is written twice. Storage is cheap; a cross-partition scan is not.</text>
</svg>
```

Now read the access patterns straight off the key design:

- **A customer's profile** → get `PK = CUSTOMER#c-1`, `SK = #PROFILE`. One item.
- **A customer's orders, newest first** → query `PK = CUSTOMER#c-1`, `SK begins_with ORDER#`, reversed.
  The structured sort key (`ORDER#<date>#<id>`) means "newest first" is just descending sort order.
- **A customer plus all their orders in one shot** → query `PK = CUSTOMER#c-1` with no sort-key filter.
  The whole item collection — profile and orders together — in a single request. *That's the join.*
- **An order with its line items** → query `PK = ORDER#o-620`. The `#META` header and every `ITEM#`
  row come back together, sorted.

Every one is a single-partition lookup. Notice the deliberate **denormalization**: the order is stored
*twice* — once as a reference in the customer's partition (to list a customer's orders) and once as its
own partition head with its items (to fetch the order with its items). Duplicating on write to make
each read a single lookup is not a hack — it's the design, the same bargain document (Lesson 3) and
wide-column (Lesson 4) stores make. Storage is cheap; a cross-partition scan is not.

### Secondary indexes: adding an access pattern you didn't key for

Access pattern 4 — "all orders in a given status" — can't be served by the base table's keys, because
`status` is neither the partition key nor the sort key. This is what a **Global Secondary Index (GSI)**
is for: a **second copy of the items, keyed by a different attribute**, that the store maintains for
you on every write.

A GSI is the same "duplicate on write to serve a read" trade as single-table design — except the store
automates the duplication. You declare "index these items by `status`," and now `status = SHIPPED`
becomes a direct lookup into the index instead of a scan of the base table. The catch is that you
choose *which* items land in the index (by which items carry the index's key attributes), and you pay
extra write cost and storage to keep the copy current — exactly the index trade-off from Phase 3,
Lesson 9, now explicit and by-hand.

### The costs — and why you still default to relational

Query-first modeling buys `O(1)` reads at massive scale, but be honest about the bill:

- **You must know your queries up front.** For a mature, high-scale system with well-understood
  access patterns, that's fine. For a young product whose features change weekly, it's a straitjacket
  — which is why Lesson 1's rule holds: *default to relational until the access patterns stabilize and
  the scale genuinely forces you out.* A relational database's ad-hoc query flexibility is worth more
  than `O(1)` while you're still discovering what to build.
- **A new access pattern later is a migration, not a `CREATE INDEX` you run on a whim.** GSIs soften
  this, but adding one to a huge table backfills every item, and re-keying the base table can mean
  rewriting the dataset.
- **Overloaded, encoded keys are cryptic.** `PK = CUSTOMER#c-1`, `SK = ORDER#2024-06-11#o-620` trades
  the self-documenting clarity of `customers`/`orders` tables for raw lookup speed. That's a real
  readability cost your team pays forever.

## Build It

Let's build a single-table design engine: a table addressed by a composite `(PK, SK)` key, range
queries by sort-key prefix, and a hand-built GSI — then serve all five access patterns and *count the
items each one examines* to prove they're targeted lookups, not scans. Standard library only; the
store is a couple of nested dictionaries.

The table stores items as `partition → {sort_key → item}`, and a `query` reads just one partition,
optionally sliced to the sort keys that begin with a prefix:

```python
class Table:
    def put(self, item):
        self.items.setdefault(item["PK"], {})[item["SK"]] = dict(item)
        for gsi in self.gsis.values():
            gsi.index(item)                       # keep every index current on write

    def query(self, pk, begins_with=None, reverse=False):
        partition = self.items.get(pk, {})        # touches ONE partition, never the table
        keys = sorted(partition)
        if begins_with is not None:
            keys = [k for k in keys if k.startswith(begins_with)]
        if reverse:
            keys.reverse()
        self.reads_last = len(keys)               # instrumentation: items examined
        return [partition[k] for k in keys]

    def scan(self):                               # the anti-pattern, for contrast
        all_items = [it for part in self.items.values() for it in part.values()]
        self.reads_last = len(all_items)
        return all_items
```

The GSI is a second copy of the items keyed by a chosen attribute, rebuilt on every `put`. Only items
that *have* the index's key attributes get indexed — which is how you control an index's membership:

```python
class GSI:
    def index(self, item):
        if self.pk_attr in item and self.sk_attr in item:      # membership is opt-in
            bucket = self.data.setdefault(item[self.pk_attr], {})
            bucket[(item[self.sk_attr], item["PK"], item["SK"])] = dict(item)

    def query(self, gsi_pk, reverse=False):
        bucket = self.data.get(gsi_pk, {})
        keys = sorted(bucket, reverse=reverse)                 # ordered by the GSI sort key
        return [bucket[k] for k in keys], len(keys)
```

The e-commerce model writes each order *twice* — a reference in the customer's partition and a `#META`
head with its items in the order's own partition — and puts the GSI keys (`gsi1pk`/`gsi1sk`) only on
the canonical `#META` item so each order is indexed exactly once:

```python
    def place_order(cust, oid, date, status, items):
        t.put({"PK": f"CUSTOMER#{cust}", "SK": f"ORDER#{date}#{oid}", "entity": "order_ref",
               "order_id": oid, "status": status, "order_date": date})
        t.put({"PK": f"ORDER#{oid}", "SK": "#META", "entity": "order",
               "order_id": oid, "status": status, "order_date": date,
               "gsi1pk": status, "gsi1sk": f"{date}#{oid}"})     # only this item joins the GSI
        for i, (sku, qty) in enumerate(items, 1):
            t.put({"PK": f"ORDER#{oid}", "SK": f"ITEM#{i:02d}", "entity": "order_item",
                   "sku": sku, "qty": qty})
```

Running `python single_table.py` loads the one table and serves every access pattern, printing how
many items each examined:

```console
$ python single_table.py
== One table, 12 items, three entity types co-located by key ==
    CUSTOMER#c-1     | #PROFILE                   | customer
    CUSTOMER#c-1     | ORDER#2024-05-02#o-500     | order_ref
    CUSTOMER#c-1     | ORDER#2024-06-11#o-620     | order_ref
    ORDER#o-620      | #META                      | order
    ORDER#o-620      | ITEM#01                    | order_item
    ORDER#o-620      | ITEM#02                    | order_item
    ...

== Access pattern 2: a customer's orders, newest first ==
   o-620  2024-06-11  SHIPPED
   o-500  2024-05-02  PAID
   examined 2 items (only Ada's partition, not the table)

== Access pattern 4: an order with its line items (one partition) ==
   #META    order o-620 (SHIPPED)
   ITEM#01  LAPTOP-9
   ITEM#02  MOUSE-3
   examined 3 items

== Access pattern 5: orders by status -- needs a GSI (a non-key attribute) ==
   SHIPPED orders: ['o-700', 'o-620']   examined 2 items via the GSI
   (without the GSI, the same answer needs a full scan: 12 items examined)
```

Read the examined-counts — they're the whole point. "A customer's orders" examined **2** items (only
Ada's partition), not the 12 in the table. "An order with its items" examined **3** — the header and
two line items, the join you can't do, pre-assembled in one partition. And "orders by status" examined
**2** items through the GSI versus **12** for the full scan it replaces — on a real table of a hundred
million orders, that's the difference between a millisecond and a meltdown. Every access pattern became
a direct key lookup *because you designed the keys around the queries*, not the other way round.

## Use It

**DynamoDB** is where single-table design was born and is the canonical home of this discipline. Your
Build-It is its data model in miniature — `PK`/`SK`, `begins_with`, `Query` vs `Scan`, and GSIs:

```python
# DynamoDB via boto3. Query reads one partition; Scan reads the whole table (avoid it).
table.query(KeyConditionExpression=Key("PK").eq("CUSTOMER#c-1")
            & Key("SK").begins_with("ORDER#"), ScanIndexForward=False)   # orders, newest first
table.query(KeyConditionExpression=Key("PK").eq("ORDER#o-620"))          # order + its items
table.query(IndexName="orders_by_status",
            KeyConditionExpression=Key("gsi1pk").eq("SHIPPED"))          # your GSI query
```

The same query-first law shows up differently across the stores you've learned, and seeing the
contrast cements it:

- **Cassandra / wide-column (Lesson 4)** takes it to the other extreme: instead of overloading one
  table, you build **one table per access pattern** and write each row into all of them. Same
  discipline (model the queries, duplicate on write), different expression — many single-purpose
  tables instead of one overloaded table.
- **DynamoDB** favors **one overloaded table** with item collections and GSIs — fewer tables, encoded
  keys.
- **MongoDB / document (Lesson 3)** expresses it as the **embed-vs-reference** decision: you draw the
  document boundary around the data an access pattern reads together (the aggregate). Same instinct,
  document-shaped.

All three are the same idea: **there are no joins, so design the storage around the reads.**

Three hard-won lessons that separate people who model NoSQL well from people who end up scanning in
production:

- **Write the access-pattern list before the schema — literally.** A numbered list of every read
  ("get a customer's orders, newest first"), each naming what you filter by and how you sort. That
  list *is* the design input. Skipping it is how you discover, in production, a query you can't serve.
- **Model the queries you have, but keep the keys generic.** Use overloaded, prefixed keys
  (`PK`/`SK`, `gsi1pk`/`gsi1sk`) so you can add new entity types and access patterns to the same table
  without re-keying — a little forethought that buys real flexibility inside a rigid model.
- **A `Scan` in production is a design smell.** It means an access pattern you never modeled a key
  for. When you reach for one, stop: either add a GSI, or you've hit the limit of query-first modeling
  and the honest answer is that this workload wanted the ad-hoc flexibility of a relational database
  (Lesson 1) all along.

## Key takeaways

- NoSQL modeling **inverts** the relational process: because there are **no joins** and you fetch **by
  key**, you **list the access patterns first**, then design the keys so each one is a **single cheap
  lookup**. You model the *reads*, not the domain — the general form of Lesson 4's "model queries, not
  data."
- Scalable stores give a two-part key: the **partition key** picks the node and groups items; the
  **sort key** orders them within a partition and enables range slices. **Encode meaning into the
  keys** (`CUSTOMER#c-1`, `ORDER#<date>#<id>`) so hierarchy and order become queryable.
- **Single-table design** co-locates multiple entity types by partition key so a parent and its
  children return together as an **item collection** — the join you can't do, precomputed by key
  layout. Duplicating data on write (an order stored under both the customer and the order) is the
  intended design.
- A **Global Secondary Index (GSI)** is a store-maintained second copy keyed by a different attribute,
  adding an access pattern the base keys don't serve — the same duplicate-on-write trade, automated,
  paid for in write cost and storage.
- The discipline is powerful but **rigid**: you must know your queries up front, and adding one later
  is a migration, not a casual `CREATE INDEX`. So **default to relational** until access patterns
  stabilize and scale forces you out — and treat a **production `Scan` as a design smell**, the sign of
  a pattern you forgot to model.

Next: [Polyglot Persistence](../08-polyglot-persistence/) — you now know every NoSQL family and how to
model for each. The final lesson zooms out to the real architecture: a system that uses *several* of
these stores at once, why that's powerful, and the hard problem — keeping them from lying to each other
— that decides whether it's worth it.
