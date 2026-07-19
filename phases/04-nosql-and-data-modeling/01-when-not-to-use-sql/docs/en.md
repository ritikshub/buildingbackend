# When Not to Use SQL

> The relational database is the best default we have, and it will be the right answer more often than not. "NoSQL" is not a rebellion against it — it's a set of specialized tools for the specific shapes and scales where the relational model starts charging you more than it's worth. Knowing *when* to reach for one is a senior skill; reaching for one by reflex is a junior mistake.

**Type:** Learn
**Languages:** —
**Prerequisites:** [The Relational Model](../../03-relational-databases/03-the-relational-model/), [Schema Design & Normalization](../../03-relational-databases/07-schema-design-and-normalization/), [Indexes & the B-Tree](../../03-relational-databases/09-indexes-and-the-btree/)
**Time:** ~45 minutes

## The Problem

You spent all of Phase 3 learning why the relational database is so good: it stores data as
clean, normalized tables; it enforces correctness with constraints; it answers almost any
question you can phrase with joins and `WHERE`; and it wraps changes in ACID transactions so
a crash never leaves you half-written. For the overwhelming majority of applications, that is
the correct place to put your data, and the honest advice a senior engineer will give you is:
**start with Postgres, and stay there until something specific pushes you out.**

But "something specific" does happen. A social network needs to render a user's feed —
millions of times a second, each one assembled from data scattered across a fleet of machines.
A metrics pipeline ingests two million sensor readings per second, forever. A fraud team needs
"find every account within four hops of this stolen card." A product team ships a feature every
week and can't stop to write a schema migration for each one. In each of these, you can *make*
a relational database do the job — and then you spend the next year fighting it, because the
job is a shape the relational model was never built for.

This lesson is the map for that fork in the road. Not "SQL bad, NoSQL good" — that framing is
how people end up with five databases and a distributed-systems problem they didn't need. The
real question is narrower and more useful: **what does the relational model actually cost, on
which axes does that cost blow up, and which of those costs does each family of NoSQL store
buy back — in exchange for what?** Answer that, and the rest of this phase is just filling in
the specific tools.

## The Concept

### First, what "NoSQL" even means

The name is an accident. It was a Twitter hashtag for a 2009 meetup, and it has caused a decade
of confusion because it defines a huge, diverse family of databases by the *one thing they
aren't*. The more accurate reading, which the community adopted after the fact, is **"Not Only
SQL"** — these are stores that relax one or more of the relational database's defining
commitments in order to be dramatically better at something else.

To see what they're relaxing, name what a relational database (an **RDBMS** — Relational
Database Management System) commits to:

- **A fixed schema, enforced on write.** Every row in a table has the same columns, of the same
  declared types. The database rejects anything that doesn't fit.
- **Normalization.** Each fact lives in exactly one place; you reassemble related facts at read
  time with **joins**.
- **A rich, declarative query language.** You describe *what* you want (SQL) and the planner
  figures out *how* (Phase 3, Lesson 10).
- **ACID transactions.** A group of changes is atomic, consistent, isolated, and durable
  (Phase 3, Lesson 11).
- **Vertical scaling as the default.** One primary node owns the truth; you make it bigger to
  make it faster.

Each of those is a genuine gift — *and* each is a bet. When your data or your traffic breaks
the bet, the gift turns into a bill. NoSQL stores are what you get when you tear up one of the
bets on purpose.

### The five pressures that push you off relational

There isn't one reason to leave SQL. There are five distinct pressures, and it's worth being
able to name which one (if any) is actually acting on you — because the pressure determines the
tool. Cargo-culting "we need NoSQL to scale" when your real problem is schema flexibility gets
you the wrong database.

#### Pressure 1 — Rigid schema vs. data that won't hold still

A relational table is a contract signed in advance: these columns, these types, for every row.
That contract is a *feature* — it's how the database refuses to store nonsense. But it costs you
on two data shapes:

- **Rapidly-evolving data**, where the fields change weekly and every change is an `ALTER TABLE`
  migration (Phase 3, Lesson 15) coordinated across a running system.
- **Heterogeneous data**, where "a product" legitimately has different attributes depending on
  what it is — a book has an author and page count, a laptop has RAM and a CPU — and forcing
  them into one wide table gives you a swamp of mostly-`NULL` columns, or a tangle of
  type-specific side tables.

The **document** model (Lesson 3) relaxes *schema-on-write* into *schema-on-read*: store each
record as a self-describing JSON document, and let its shape vary.

#### Pressure 2 — Joins that get too expensive

Normalization's bargain is: store each fact once, pay to rejoin at read time. A join over
indexed columns is cheap *on one machine*. The bargain breaks in two ways. First, **deep
relationship traversal** — "friends of friends of friends of friends" — is one self-join per
hop, and the intermediate result sets multiply until the query melts (Lesson 6 shows the exact
blow-up). Second, and more fundamentally, **a join needs both sides in one place.** The moment
your data is spread across many machines (Pressure 5), a join may have to drag rows across the
network between nodes, and the neat `O(log n)` index lookup becomes a distributed shuffle.

The **document** and **wide-column** models sidestep this by *denormalizing* — storing related
data pre-joined, together — so the common read is one lookup, no join. The **graph** model
(Lesson 6) attacks it from the other side, making a relationship a direct pointer so a hop is
`O(1)` no matter how big the graph.

#### Pressure 3 — Write throughput a single primary can't absorb

A classic RDBMS funnels every write through **one primary node** (Phase 3's WAL and MVCC assume
it). You can add read replicas to scale *reads*, but writes still bottleneck on that one machine's
CPU, disk, and the B-tree index maintenance every insert triggers. When you need to absorb
hundreds of thousands to millions of writes per second — an activity feed, a clickstream, IoT
telemetry — no single machine is big enough.

The **wide-column** model (Lesson 4) is built for exactly this: writes are distributed across
every node in the cluster by a partition key, and its **LSM-tree** storage engine turns a write
into a cheap append instead of an in-place B-tree update. **Time-series** stores (Lesson 5)
specialize the same idea for timestamped data.

#### Pressure 4 — Scaling *out* instead of *up*

Pressures 2 and 3 share a root cause worth isolating: a relational database prefers to **scale
vertically** (a bigger machine) because its best features — joins, foreign keys, cross-row
transactions — assume all the data is reachable from one place. Eventually you hit the biggest
machine money can buy, or its price becomes absurd. The alternative is to **scale horizontally**:
spread the data across many cheap machines (**sharding**) and add more when
you need more.

You *can* shard Postgres, but you give up the very things you were paying it for: a query can no
longer freely join across shards, and a transaction can no longer freely span them. NoSQL stores
that were **designed** to be distributed from day one (Dynamo-lineage: Cassandra, DynamoDB,
Riak) treat horizontal scale as the default, not a bolt-on — at the price of the guarantees in
Pressure 5.

#### Pressure 5 — The consistency you can afford at scale (CAP)

Here is the one that isn't about performance — it's about physics. The moment your data lives on
more than one machine, the network between them *can and will* fail. The **CAP theorem** (Eric
Brewer, 2000; proved by Gilbert & Lynch, 2002) says that when a network **P**artition happens,
a distributed store must choose: stay **C**onsistent (refuse reads/writes that can't see the
latest data, i.e. become unavailable) or stay **A**vailable (answer anyway, risking stale data).
You cannot have both *during a partition*. (Full treatment belongs to distributed systems — here we only
need its consequence.)

A single-node relational database sidesteps CAP by not being distributed — but that's also why
it can't scale out. Distributed NoSQL stores make the trade explicit, and many let you *tune* it
per operation. That trade is usually described by swapping ACID for its deliberate opposite:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 526" width="100%" style="max-width:880px" role="img" aria-label="ACID versus BASE, shown as two side-by-side panels — the two bets a database can make about consistency. On the left, in blue, ACID: the relational bet, made by a database where one machine owns the truth. Its four letters are spelled out. A is for Atomic: all of the change lands, or none of it does. C is for Consistent: the database never ends up breaking its own rules. I is for Isolated: concurrent transactions cannot see each other's half-finished work. D is for Durable: once it says committed, a crash cannot undo it. Its promise is strong consistency — every read sees the last write, always. On the right, in green, BASE: the distributed bet, made by a store spread over many machines with no single owner. Its letters are spelled out too. B and A are for Basically Available: answer every request you can, even while some nodes or links are unreachable. S is for Soft state: a replica's value can change on its own as updates propagate, with no new write involved. E is for Eventually consistent: if writes stop, every replica converges to the same value, and until then they may disagree. The explicit axis of comparison, drawn as a matching amber band across the middle of both panels with a dashed partition line between them, is what each does when the network partitions. ACID keeps C and drops A: it refuses to answer rather than answer with stale data, so availability drops. BASE keeps A and drops C: it answers from any reachable replica, fresh or not, so it stays up. Each pays a cost. ACID is hard to scale out, because joins and cross-row transactions want all the data in one place. BASE reads can be stale, so the application must be written to tolerate it. The trade, stated plainly: ACID buys correctness by giving up availability during a partition, and BASE buys availability by giving up freshness.">
  <defs>
    <marker id="p4l1a-ara" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="450" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="15" font-weight="700" fill="currentColor">Two bets a database can make — and a network partition is where they part ways</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="414" height="362" rx="12" fill="#3553ff" fill-opacity="0.06" stroke="#3553ff" stroke-opacity="0.8"/>
    <rect x="470" y="42" width="414" height="362" rx="12" fill="#0fa07f" fill-opacity="0.06" stroke="#0fa07f" stroke-opacity="0.8"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="223" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#3553ff">ACID — the relational bet</text>
    <text x="223" y="86" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">one machine owns the truth</text>
    <text x="677" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">BASE — the distributed bet</text>
    <text x="677" y="86" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.75">many machines, no single owner</text>

    <g fill="none" stroke-width="1.2">
      <rect x="28" y="96" width="390" height="146" rx="9" fill="#3553ff" fill-opacity="0.05" stroke="#3553ff" stroke-opacity="0.35"/>
      <rect x="482" y="96" width="390" height="146" rx="9" fill="#0fa07f" fill-opacity="0.05" stroke="#0fa07f" stroke-opacity="0.35"/>
    </g>

    <text x="42" y="118"><tspan font-size="15" font-weight="700" fill="#3553ff">A</tspan><tspan font-size="11" font-weight="700" fill="currentColor">tomic</tspan></text>
    <text x="42" y="131" font-size="8.5" fill="currentColor" opacity="0.75">all of the change lands, or none of it does</text>
    <text x="42" y="152"><tspan font-size="15" font-weight="700" fill="#3553ff">C</tspan><tspan font-size="11" font-weight="700" fill="currentColor">onsistent</tspan></text>
    <text x="42" y="165" font-size="8.5" fill="currentColor" opacity="0.75">the database never ends up breaking its own rules</text>
    <text x="42" y="186"><tspan font-size="15" font-weight="700" fill="#3553ff">I</tspan><tspan font-size="11" font-weight="700" fill="currentColor">solated</tspan></text>
    <text x="42" y="199" font-size="8.5" fill="currentColor" opacity="0.75">concurrent transactions can't see each other's half-work</text>
    <text x="42" y="220"><tspan font-size="15" font-weight="700" fill="#3553ff">D</tspan><tspan font-size="11" font-weight="700" fill="currentColor">urable</tspan></text>
    <text x="42" y="233" font-size="8.5" fill="currentColor" opacity="0.75">once it says committed, a crash cannot undo it</text>

    <text x="496" y="118"><tspan font-size="15" font-weight="700" fill="#0fa07f">B</tspan><tspan font-size="11" font-weight="700" fill="currentColor">asically </tspan><tspan font-size="15" font-weight="700" fill="#0fa07f">A</tspan><tspan font-size="11" font-weight="700" fill="currentColor">vailable</tspan></text>
    <text x="496" y="131" font-size="8.5" fill="currentColor" opacity="0.75">answer every request you can, even while some</text>
    <text x="496" y="143" font-size="8.5" fill="currentColor" opacity="0.75">nodes or links are unreachable</text>
    <text x="496" y="162"><tspan font-size="15" font-weight="700" fill="#0fa07f">S</tspan><tspan font-size="11" font-weight="700" fill="currentColor">oft state</tspan></text>
    <text x="496" y="175" font-size="8.5" fill="currentColor" opacity="0.75">a replica's value can change on its own as</text>
    <text x="496" y="187" font-size="8.5" fill="currentColor" opacity="0.75">updates propagate — no new write involved</text>
    <text x="496" y="206"><tspan font-size="15" font-weight="700" fill="#0fa07f">E</tspan><tspan font-size="11" font-weight="700" fill="currentColor">ventually consistent</tspan></text>
    <text x="496" y="219" font-size="8.5" fill="currentColor" opacity="0.75">if writes stop, every replica converges to the</text>
    <text x="496" y="231" font-size="8.5" fill="currentColor" opacity="0.75">same value; until then they may disagree</text>

    <g fill="none" stroke="currentColor" stroke-opacity="0.18" stroke-width="1.2">
      <path d="M32 252 H414"/>
      <path d="M486 252 H868"/>
    </g>

    <text x="223" y="266" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">The promise: strong consistency</text>
    <text x="223" y="281" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">every read sees the last write, always</text>
    <text x="677" y="266" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">The promise: eventual consistency</text>
    <text x="677" y="281" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">if writes stop, every replica converges</text>

    <g fill="#e0930f" fill-opacity="0.08" stroke="#e0930f" stroke-opacity="0.7" stroke-width="1.5">
      <rect x="28" y="294" width="390" height="64" rx="9"/>
      <rect x="482" y="294" width="390" height="64" rx="9"/>
    </g>
    <text x="223" y="312" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">WHEN THE NETWORK PARTITIONS (CAP)</text>
    <text x="223" y="330" text-anchor="middle" font-size="9.5" fill="currentColor">keeps C, drops A: refuses to answer</text>
    <text x="223" y="346" text-anchor="middle" font-size="9.5" fill="currentColor">rather than answer with stale data</text>
    <text x="677" y="312" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">WHEN THE NETWORK PARTITIONS (CAP)</text>
    <text x="677" y="330" text-anchor="middle" font-size="9.5" fill="currentColor">keeps A, drops C: answers from any</text>
    <text x="677" y="346" text-anchor="middle" font-size="9.5" fill="currentColor">reachable replica, fresh or not</text>

    <path d="M450 52 V394" fill="none" stroke="#e0930f" stroke-opacity="0.3" stroke-width="1.5" stroke-dasharray="4 5"/>
    <g fill="none" stroke="#e0930f" stroke-width="1.5">
      <path d="M449 326 L434 326" marker-end="url(#p4l1a-ara)"/>
      <path d="M451 326 L466 326" marker-end="url(#p4l1a-ara)"/>
    </g>

    <text x="223" y="378" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Cost: hard to scale out — joins and cross-row</text>
    <text x="223" y="392" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">transactions want all the data in one place.</text>
    <text x="677" y="378" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">Cost: reads can be stale — the application</text>
    <text x="677" y="392" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.85">must be written to tolerate it.</text>

    <rect x="16" y="418" width="868" height="56" rx="11" fill="#7f7f7f" fill-opacity="0.07" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.5"/>
    <text x="450" y="440" text-anchor="middle" font-size="10" fill="currentColor"><tspan font-weight="700" fill="#3553ff">ACID</tspan> buys correctness by giving up availability. <tspan font-weight="700" fill="#0fa07f">BASE</tspan> buys availability by giving up freshness.</text>
    <text x="450" y="458" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">Neither is "better" — you choose per dataset, not per company: strong for money, eventual for a feed.</text>
  </g>
  <text x="450" y="496" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">A single-node relational database dodges the choice by not being distributed — which is exactly why it can't scale out.</text>
  <text x="450" y="514" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10.5" fill="currentColor" opacity="0.9">"Eventually" promises convergence, not a deadline — and many stores let you tune the dial per operation.</text>
</svg>
```

**BASE** — Basically Available, Soft state, Eventually consistent — is the acronym coined
(half in jest) to name the opposite bet. It says: prioritize staying up, accept that different
replicas may briefly disagree, and guarantee only that *if writes stop, all replicas eventually
converge* to the same value (**eventual consistency**). For a bank ledger, that's unacceptable.
For a "likes" counter or a social feed, a few seconds of staleness is invisible and the
availability is worth everything. **Choosing which of your data is which is the whole game.**

### The map: which pressure buys which store

Stack the five pressures against the families you'll build in this phase, and the phase stops
being a list of trendy databases and becomes a decision table:

| Family | Relaxes / adds | Wins when the pressure is… | Lesson |
|---|---|---|---|
| **Key-Value** | Drops query-by-value; data is an opaque blob keyed by one id | Raw speed & scale for simple lookups (sessions, cache, flags) | 2 |
| **Document** | Drops fixed schema; adds queryable nested JSON | Schema flexibility + read-together aggregates (Pressures 1, 2) | 3 |
| **Wide-Column** | Drops joins; distributes writes by partition key over an LSM engine | Massive write throughput + horizontal scale (Pressures 3, 4, 5) | 4 |
| **Time-Series** | Specializes for append-only timestamped points + compression | Metrics, sensors, events at firehose volume (Pressure 3) | 5 |
| **Graph** | Makes relationships first-class via index-free adjacency | Deep relationship traversal (Pressure 2, the traversal half) | 6 |

Read across a row and you can see the shape of the trade every time: **you give up a general
capability to get a specialized one.** A key-value store can't answer "find all users in Berlin"
— but it will hand you a user by id faster and at more scale than anything else. That is the
entire philosophy of NoSQL in one sentence: **constrain the model to buy performance, scale, or
flexibility on the one axis you actually need.**

### The senior-level caveat: the line has moved

If this lesson had been written in 2012, it would have ended here with "so pick a NoSQL store."
It's not 2012, and a senior engineer holds two more facts that a junior one usually doesn't:

**Relational databases absorbed most of NoSQL's features.** Postgres today has `JSONB` — a
binary, *indexable* JSON column type — which gives you the document model *inside* a relational
database, transactions and all (you'll use it in Lesson 3's "Use It"). It has declarative table
**partitioning** for time-series-shaped data, `LISTEN/NOTIFY` for pub/sub, full-text search,
`PostGIS` for geospatial, the **TimescaleDB** and **pgvector** extensions. For a huge number of
"we need NoSQL" moments, the honest answer is now "you need a Postgres feature you didn't know
existed." Reaching for a second database has a real, permanent cost — another system to run,
back up, monitor, and keep in sync (Lesson 8) — and that cost is often higher than the problem.

**NoSQL databases absorbed most of SQL's features.** The trade is no longer as stark as the
table above suggests. MongoDB added multi-document ACID transactions in 2018 and a rich
aggregation language. Cassandra has secondary indexes. DynamoDB has transactions and secondary
indexes. Many "NoSQL" stores now speak a SQL dialect. The categories are converging, and the
2010s war between them reads today as a false binary.

So the real decision rule is not "SQL or NoSQL." It's: **default to your relational database;
identify the *specific* pressure pushing you off it; check whether your relational database has
grown a feature that relieves that pressure; and only if it genuinely hasn't — and the volume
truly justifies a whole new system to operate — reach for the specialized store that targets
exactly that pressure.** The rest of Phase 4 teaches those stores so that when the moment comes,
you'll recognize it and choose deliberately, not by hype.

### A worked judgment call

Make it concrete. You're building an e-commerce backend. Walk the data:

- **Orders, payments, inventory** — money is involved; you need atomic multi-row transactions and
  strong consistency. *No pressure pushes you off relational. Stay on Postgres.* This is the
  default, and for the part of the system that matters most, it's also the answer.
- **The product catalog** — every category has different attributes; the marketing team adds
  fields weekly. *Pressure 1 (schema).* Candidate for a document store — **or** a Postgres
  `JSONB` column, which is very likely the right call unless the catalog is enormous.
- **User sessions and the cart** — looked up by one key, need to be blindingly fast, don't need
  to outlive much. *Pressure 3, in a small way.* A key-value store (Redis) is the classic fit.
- **The "customers who viewed this also viewed…" engine** — deep relationship traversal over a
  huge graph of co-views. *Pressure 2 (traversal).* A graph database earns its keep here.
- **Site metrics and clickstream** — billions of append-only timestamped events, queried by
  time range. *Pressure 3 (write firehose).* A time-series store, or Postgres partitioning /
  TimescaleDB.

Notice the shape of the answer: **not one database, and not five databases by default — a
relational core, plus a specialized store only where a named pressure genuinely demands one.**
That deliberate mix is **polyglot persistence**, and it's the destination of this whole phase
(Lesson 8). Everything between here and there is learning each tool well enough to know when its
pressure is the one you're actually feeling.

## Think about it

1. A teammate says "our app is slow, we should switch to NoSQL." Which of the five pressures
   would you ask about first to find out whether that's even the right diagnosis — and what's a
   likely relational fix (from Phase 3) they may have skipped?
2. You're storing bank account balances and transfers between accounts. Which single property of
   ACID makes eventual consistency (BASE) unacceptable here, and why?
3. Your product catalog has 200 product types with wildly different attributes. Name the
   pressure. Now give *two* different solutions — one that stays on Postgres and one that leaves
   it — and one reason you'd pick each.
4. The CAP theorem forces a choice only *during a network partition.* Why does a single-node
   Postgres instance get to ignore CAP entirely — and what does it give up in exchange for that
   freedom?
5. "NoSQL scales better than SQL." Rewrite this sentence into something precise and true, using
   the words *horizontal*, *partition key*, and *joins*.

## Key takeaways

- **"NoSQL" means "Not Only SQL"** — a family of stores that each relax one relational commitment
  (fixed schema, joins, single-primary, strong consistency) to be far better at one specific
  thing. It is not a replacement for relational databases; it's a set of specialized tools.
- There are **five distinct pressures** that push you off relational: rigid **schema**,
  expensive **joins/traversal**, **write throughput** a single primary can't take, the need to
  **scale out** not up, and the **consistency-vs-availability** trade of CAP. Name the pressure
  before you name the tool.
- Distributed stores trade **ACID** for **BASE** (Basically Available, Soft state, Eventually
  consistent) because the **CAP theorem** forbids both strong consistency and availability during
  a network partition. Match the guarantee to the data: strong for money, eventual for a feed.
- Each NoSQL family maps to a pressure: **key-value** → speed/scale for simple lookups;
  **document** → schema flexibility; **wide-column** → write throughput at horizontal scale;
  **time-series** → timestamped firehoses; **graph** → deep traversal.
- The line has moved: **relational databases absorbed** `JSONB`, partitioning, and search, while
  **NoSQL absorbed** transactions and secondary indexes. Default to your relational database,
  check if it already solves the pressure, and only then reach for a specialized store — knowing
  each new store is a permanent operational cost (Lesson 8).

Next: [Key-Value Stores](../02-key-value-stores/) — the simplest NoSQL model of all, where we
throw away every query except "give me the value for this key," and discover how much speed and
scale that one constraint buys back.
