# A Field Guide to Databases: Types & Trade-offs

> "Database" is not one thing. It's a family of tools shaped by different questions — and the reason the relational one became the default is worth understanding *before* you commit to it.

**Type:** Learn
**Languages:** —
**Prerequisites:** [Why Databases Exist](../01-why-databases-exist/)
**Time:** ~50 minutes

## The Problem

The last lesson argued that you need *a database*. But walk into any system-design
conversation and you'll hear a dozen names — Postgres, Redis, MongoDB, Cassandra, Neo4j,
Elasticsearch, DynamoDB — thrown around as if they're interchangeable. They are not. Each
was built around a different **data model** (the shape it stores data in) and a different
set of trade-offs, and picking the wrong one means fighting your database for the life of
the project.

This phase is about **relational** databases specifically. But "relational" only means
something in contrast to the alternatives. So this lesson maps the whole family: what each
type is good at, what it gives up to get there, and — the payoff — *why the relational
model is the right default for most backends, and how to recognize the cases where it
isn't.* You'll leave able to answer the interview-and-real-life question "why did you pick
Postgres here?" with something better than "it's what I know."

## The Concept

### The one thing they all share, and the one thing that divides them

Every database from this lesson gives you the four guarantees of the last one — durable,
queryable, concurrent, consistent — to *some* degree. What separates them is two choices:

1. **The data model** — the shape data takes. Tables? Key→value pairs? Nested documents?
   A graph of nodes and edges? The model decides which questions are cheap and which are
   painful.
2. **The consistency model** — how strict the guarantees are, especially across many
   machines. **Strong** consistency (every reader sees the latest write, always) versus
   **eventual** consistency (readers may briefly see stale data, in exchange for staying
   fast and available when machines fail). We'll go deep on this in the distributed-systems
   phase; here it's enough to know it's a dial, and different databases set it differently.

Almost every "which database?" argument is really an argument about these two axes.

### The family tree

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 775 428" width="100%" style="max-width:720px" role="img" aria-label="A tree: Databases split into Relational (SQL), NoSQL, and Specialized. NoSQL contains Key-Value, Document, Wide-Column, and Graph. Specialized contains Time-Series and Search. Each type lists example engines." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l02a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="387.5" y="26" text-anchor="middle" font-size="14" font-weight="700">The database family tree</text>
  <g fill="none">
  <path d="M130 226 L150 226 L150 70 L170 70" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M130 226 L150 226 L150 200 L170 200" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M130 226 L150 226 L150 356 L170 356" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 200 L340 200 L340 122 L360 122" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 200 L340 200 L340 174 L360 174" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 200 L340 200 L340 226 L360 226" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 200 L340 200 L340 278 L360 278" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 356 L340 356 L340 330 L360 330" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 356 L340 356 L340 382 L360 382" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02a-ah)"/>
  <path d="M310 70 L 552.0 70.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 122 L 581.0 122.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 174 L 571.5 174.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 226 L 542.0 226.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 278 L 584.5 278.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 330 L 561.5 330.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M490 382 L 548.5 382.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  </g>
  <g>
  <rect x="20" y="202" width="110" height="48" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="170" y="48" width="140" height="44" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="170" y="178" width="140" height="44" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="170" y="334" width="140" height="44" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="101" width="130" height="42" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="153" width="130" height="42" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="205" width="130" height="42" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="257" width="130" height="42" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="309" width="130" height="42" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="360" y="361" width="130" height="42" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="552.0" y="50" width="192" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="581.0" y="102" width="134" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="571.5" y="154" width="153" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="542.0" y="206" width="212" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="584.5" y="258" width="127" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="561.5" y="310" width="173" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="548.5" y="362" width="199" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="75.0" y="229.9" font-size="11.5" text-anchor="middle" >Databases</text>
  <text x="240.0" y="73.9" font-size="11.5" text-anchor="middle" >Relational (SQL)</text>
  <text x="240.0" y="203.9" font-size="11.5" text-anchor="middle" >NoSQL</text>
  <text x="240.0" y="359.9" font-size="11.5" text-anchor="middle" >Specialized</text>
  <text x="425.0" y="125.9" font-size="11.5" text-anchor="middle" >Key-Value</text>
  <text x="425.0" y="177.9" font-size="11.5" text-anchor="middle" >Document</text>
  <text x="425.0" y="229.9" font-size="11.5" text-anchor="middle" >Wide-Column</text>
  <text x="425.0" y="281.9" font-size="11.5" text-anchor="middle" >Graph</text>
  <text x="425.0" y="333.9" font-size="11.5" text-anchor="middle" >Time-Series</text>
  <text x="425.0" y="385.9" font-size="11.5" text-anchor="middle" >Search</text>
  <text x="648.0" y="73.6" font-size="10.5" text-anchor="middle" >Postgres · MySQL · SQLite</text>
  <text x="648.0" y="125.6" font-size="10.5" text-anchor="middle" >Redis · DynamoDB</text>
  <text x="648.0" y="177.6" font-size="10.5" text-anchor="middle" >MongoDB · Couchbase</text>
  <text x="648.0" y="229.6" font-size="10.5" text-anchor="middle" >Cassandra · HBase · Bigtable</text>
  <text x="648.0" y="281.6" font-size="10.5" text-anchor="middle" >Neo4j · Neptune</text>
  <text x="648.0" y="333.6" font-size="10.5" text-anchor="middle" >InfluxDB · TimescaleDB</text>
  <text x="648.0" y="385.6" font-size="10.5" text-anchor="middle" >Elasticsearch · OpenSearch</text>
  </g>
  
</svg>
```

Let's walk each branch — what it stores, its superpower, and its cost.

### Relational — data as tables you query by logic

Data lives in **tables** (rows and columns) with declared types, and rows in different
tables link through **keys**. You query with **SQL** by *describing the result you want*,
and the database figures out how to get it. Its superpowers: **ad-hoc queries** (ask a
question nobody planned for, including joining several tables), **strong integrity**
(constraints reject bad data), and **ACID transactions** (all-or-nothing, crash-safe
changes). Its historical weakness was scaling writes across many machines — one big
server was the model. Examples: **PostgreSQL, MySQL, SQLite**. This is the rest of the
phase.

### Key-Value — a giant dictionary on disk

The simplest model: a **key** maps to a **value** (an opaque blob), and you can `get`,
`put`, and `delete` by key — that's essentially it. Because the access pattern is so
restricted, key-value stores are *blisteringly* fast and scale horizontally with ease.
The cost: you can only find data **by its key**. Want "all users in Berlin"? A pure
key-value store can't answer that without scanning everything — it has no idea what's
*inside* the value. Examples: **Redis** (in-memory, the caching phase used it),
**DynamoDB**. Perfect for sessions, caches, feature flags, rate-limit counters.

### Document — nested JSON you store whole

A **document** database stores self-contained records, usually **JSON**-like, with nested
fields and arrays — you keep an order and its line items together in one document instead
of spread across tables. Its superpower is a **flexible schema** (documents in the same
collection can have different fields) and that a whole object loads in one read. The cost:
weaker cross-document integrity and joins, and the flexibility becomes *your* problem to
police — nothing stops two documents from disagreeing about the same fact. Examples:
**MongoDB, Couchbase**. Good for content, catalogs, and evolving shapes.

### Wide-Column — tables built for enormous scale

Superficially table-like, but designed so rows can have millions of columns and data is
partitioned across many machines from day one. You design the schema *around the exact
queries you'll run* and give up flexible ad-hoc querying and joins in return for
near-linear write scaling and high availability. Examples: **Cassandra, HBase, Google
Bigtable**. Reach for it at genuinely huge write volumes (telemetry, feeds) where a single
relational server can't keep up.

### Graph — data where the *connections* are the point

Stores **nodes** (entities) and **edges** (relationships) as first-class things, so
"friends of my friends who like jazz" is a cheap walk across edges instead of a pile of
expensive joins. Superpower: deeply connected data and many-hop traversals. Cost: a
niche model that's overkill unless relationships are the *main event*. Examples: **Neo4j,
Amazon Neptune**. Good for social graphs, fraud rings, recommendation networks.

### Specialized — time-series and search

Two purpose-built branches worth knowing:

- **Time-series** databases (**InfluxDB, TimescaleDB**) optimize for append-only,
  timestamped data — metrics, sensor readings — with fast time-range queries and automatic
  roll-up/expiry. The observability phase leans on these.
- **Search** engines (**Elasticsearch, OpenSearch**) build an *inverted index* over text
  so "find every document mentioning these words, ranked by relevance" is instant. They
  complement a primary database rather than replace it.

### A quick comparison

| Type | Stores data as | Find data by | Superpower | Gives up |
|---|---|---|---|---|
| Relational | Tables (rows × columns) | Any column, joins | Ad-hoc queries, integrity, ACID | Easy multi-machine write scaling |
| Key-Value | key → blob | The key only | Raw speed, simple scaling | Querying by anything but the key |
| Document | Nested JSON docs | Fields in the doc | Flexible schema, whole-object reads | Cross-doc integrity & joins |
| Wide-Column | Partitioned wide rows | Pre-designed keys | Massive write scale, availability | Ad-hoc queries, joins |
| Graph | Nodes + edges | Traversals | Many-hop relationships | Being a general-purpose default |
| Time-Series | Timestamped points | Time ranges | Time queries, retention | General-purpose use |
| Search | Inverted text index | Words, relevance | Full-text ranking | Being a source of truth |

### Why "NoSQL" happened — and why relational didn't lose

The non-relational branches are collectively nicknamed **NoSQL** ("Not Only SQL"). They
surged in the late 2000s when web companies hit data volumes a single relational server
couldn't hold, and were willing to trade strict consistency and flexible queries for
horizontal scale and availability. That trade is real and sometimes necessary. But two
things happened: relational databases learned to scale much further than anyone expected,
and teams rediscovered — often painfully — that giving up **integrity, transactions, and
ad-hoc queries** costs *developer* time on every feature thereafter. The pendulum settled
where it started for most workloads: relational by default, NoSQL where a specific
pressure demands it.

### How to actually choose

Don't start from the database — start from your **data and its access patterns**, then
let the shape point at a model:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 730 516" width="100%" style="max-width:680px" role="img" aria-label="A decision flowchart. Start from what your data looks like. If it has rich relationships and ad-hoc queries, choose Relational (Postgres). Otherwise pick by access pattern: single-key -&gt; Key-Value, whole objects -&gt; Document, massive writes -&gt; Wide-Column, many-hop -&gt; Graph, timestamped -&gt; Time-Series, full-text -&gt; Search." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l02b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="365.0" y="26" text-anchor="middle" font-size="14" font-weight="700">How to choose a database</text>
  <g fill="none">
  <path d="M175 90 L 175 120" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l02b-ah)"/>
  <path d="M291.0 168.0 L 525 168" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l02b-ah)"/>
  <path d="M175.0 216.0 L 175 306" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 232 L525 232" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 280 L525 280" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 328 L525 328" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 376 L525 376" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 424 L525 424" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  <path d="M286.0 352.0 L306 352.0 L306 472 L525 472" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round" marker-end="url(#l02b-ah)"/>
  </g>
  <g>
  <rect x="53.5" y="44" width="243" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <path d="M175 120.0 L291.0 168 L175 216.0 L59.0 168 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="148" width="180" height="40" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M175 306.0 L286.0 352 L175 398.0 L64.0 352 Z" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="212" width="180" height="40" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="260" width="180" height="40" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="308" width="180" height="40" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="356" width="180" height="40" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="404" width="180" height="40" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="525" y="452" width="180" height="40" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="175.0" y="70.9" font-size="11.5" text-anchor="middle" >What does your data look like?</text>
  <text x="175" y="164.1" font-size="10.5" text-anchor="middle" >Rich relationships &amp;</text>
  <text x="175" y="179.1" font-size="10" text-anchor="middle" opacity="0.85" >ad-hoc queries?</text>
  <text x="615.0" y="171.9" font-size="11.5" text-anchor="middle" >Relational (Postgres)</text>
  <text x="408" y="159" font-size="9.5" text-anchor="middle" opacity="0.8" >Yes - most apps</text>
  <text x="186" y="258" font-size="10" text-anchor="start" opacity="0.8" >No</text>
  <text x="175" y="348.1" font-size="10.5" text-anchor="middle" >What's the</text>
  <text x="175" y="363.1" font-size="10" text-anchor="middle" opacity="0.85" >access pattern?</text>
  <text x="615.0" y="235.9" font-size="11.5" text-anchor="middle" >Key-Value</text>
  <text x="415.5" y="224" font-size="9.5" text-anchor="middle" opacity="0.8" >get/put by a single key</text>
  <text x="615.0" y="283.9" font-size="11.5" text-anchor="middle" >Document</text>
  <text x="415.5" y="272" font-size="9.5" text-anchor="middle" opacity="0.8" >whole self-contained objects</text>
  <text x="615.0" y="331.9" font-size="11.5" text-anchor="middle" >Wide-Column</text>
  <text x="415.5" y="320" font-size="9.5" text-anchor="middle" opacity="0.8" >massive write volume, known queries</text>
  <text x="615.0" y="379.9" font-size="11.5" text-anchor="middle" >Graph</text>
  <text x="415.5" y="368" font-size="9.5" text-anchor="middle" opacity="0.8" >many-hop connections</text>
  <text x="615.0" y="427.9" font-size="11.5" text-anchor="middle" >Time-Series</text>
  <text x="415.5" y="416" font-size="9.5" text-anchor="middle" opacity="0.8" >timestamped metrics</text>
  <text x="615.0" y="475.9" font-size="11.5" text-anchor="middle" >Search</text>
  <text x="415.5" y="464" font-size="9.5" text-anchor="middle" opacity="0.8" >full-text search</text>
  </g>
  
</svg>
```

Practical rules of thumb:

- **Default to relational** unless you have a concrete reason not to. It's the most
  flexible, the safest for correctness, and the least likely to trap you when requirements
  change — which they always do.
- **Choose by the questions you'll ask, not the data you'll store.** If you'll query the
  data many different ways, you want the model that supports ad-hoc queries: relational.
- **Add, don't replace.** Real systems are often **polyglot** — Postgres as the source of
  truth, Redis for caching/sessions, Elasticsearch for search — each doing what it's best
  at. Reaching for a second store is normal; ripping out the first rarely is.
- **Scale is a reason, not the reason.** "We might need web-scale" is not, by itself, a
  reason to abandon relational on day one. Most systems never reach the scale where a
  well-run Postgres stops being enough.

## Think about it

1. You're building a URL shortener: `short-code → long-URL`, looked up only by the code,
   billions of reads. Which model fits, and what are you giving up that you don't need?
2. A social network wants "people you may know" (friends-of-friends, up to 4 hops). Why
   would this be painful in a relational database and natural in a graph one?
3. Your team says "let's use MongoDB so we don't need a fixed schema." What does that
   flexibility *cost* you later, and who becomes responsible for the integrity the database
   used to enforce?
4. Name a real product you use and guess its polyglot stack: which store is the source of
   truth, and what would you bolt on for caching and for search?

## Key takeaways

- Databases differ along two axes: the **data model** (tables, key-value, document,
  wide-column, graph, …) and the **consistency model** (strong vs. eventual).
- **Relational** trades easy multi-machine write scaling for **ad-hoc queries, strong
  integrity, and ACID transactions** — the bundle most applications need.
- The **NoSQL** family each drops some of that bundle to buy a specific superpower: raw
  key speed, schema flexibility, write scale, relationship traversal, time queries, or
  full-text search.
- **Choose by access pattern, not by hype.** Start from the questions you'll ask; if
  they're many and varied, relational wins.
- Real systems are usually **polyglot** — relational source of truth plus specialized
  stores alongside it — so "add a store" beats "replace the store."

Next: [The Relational Model](../03-the-relational-model/) — now we commit to tables, and
meet the elegant 1970 idea (and the language, SQL) that this whole phase is built on.
