# Connection Pooling & the N+1 Problem

> Two quiet performance killers live at the seam between your app and the database: opening a fresh connection for every request, and firing one query per row in a loop. Both feel harmless in development and both fall over in production — and both have a one-paragraph fix.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Transactions & ACID](../11-transactions-and-acid/) · [How Queries Run](../10-query-planning-and-explain/)
**Time:** ~60 minutes

## The Problem

Your app works perfectly with one user on your laptop. In production, under real traffic, it
crawls — and the database's CPU is barely busy. The bottleneck isn't the database doing hard
work; it's *how your application talks to it*. Two anti-patterns dominate this seam:

1. **Opening a connection per request.** A database connection isn't free — establishing one
   is a multi-step handshake (Lesson 1's networking: TCP, often TLS, then authentication, then
   the database spinning up a backend process or thread for you). Do that on every request and
   you pay the setup cost thousands of times a second, and you slam into the database's hard
   cap on how many connections can exist at once.
2. **The N+1 query problem.** You fetch a list of 100 things with one query, then loop and run
   *another* query for each thing's related data — 1 + 100 = 101 round trips where 1 or 2 would
   do. Each trip is cheap; a hundred of them in a row is not.

Neither shows up with one user and a local database, which is exactly why they reach
production. This lesson builds a **connection pool** and demonstrates the **N+1 problem**
(and its fixes) so both become things you recognize on sight.

## The Concept

### Why a connection is expensive

When your app connects to Postgres, several things happen before you can run a single query:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1160 176" width="100%" style="max-width:760px" role="img" aria-label="The handshake pipeline to open a database connection: TCP, TLS, authentication, backend spawn, then ready." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l14a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="580.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Why a connection is expensive</text>
  <g fill="none">
  <path d="M159.5 96.0 L 191.5 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14a-ah)"/>
  <path d="M356.5 96.0 L 388.5 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14a-ah)"/>
  <path d="M532.5 96.0 L 564.5 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14a-ah)"/>
  <path d="M743.5 96.0 L 775.5 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14a-ah)"/>
  <path d="M968.5 96.0 L 1000.5 96.0" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14a-ah)"/>
  </g>
  <g>
  <rect x="29.5" y="68.0" width="130" height="56" rx="9" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="191.5" y="68.0" width="165" height="56" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="388.5" y="68.0" width="144" height="56" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="564.5" y="68.0" width="179" height="56" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="775.5" y="68.0" width="193" height="56" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="1000.5" y="68.0" width="130" height="56" rx="9" fill="#12a05a" fill-opacity="0.14" stroke="#12a05a" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="94.5" y="99.9" font-size="11.5" text-anchor="middle" >App</text>
  <text x="274.0" y="91.9" font-size="11.5" text-anchor="middle" font-weight="700" >TCP handshake</text>
  <text x="274.0" y="107.9" font-size="10" text-anchor="middle" opacity="0.85" >network round trips</text>
  <text x="460.5" y="91.9" font-size="11.5" text-anchor="middle" font-weight="700" >TLS handshake</text>
  <text x="460.5" y="107.9" font-size="10" text-anchor="middle" opacity="0.85" >encryption setup</text>
  <text x="654.0" y="91.9" font-size="11.5" text-anchor="middle" font-weight="700" >authenticate</text>
  <text x="654.0" y="107.9" font-size="10" text-anchor="middle" opacity="0.85" >password / cert check</text>
  <text x="872.0" y="91.9" font-size="11.5" text-anchor="middle" font-weight="700" >backend spawned</text>
  <text x="872.0" y="107.9" font-size="10" text-anchor="middle" opacity="0.85" >process/thread + memory</text>
  <text x="1065.5" y="99.9" font-size="11.5" text-anchor="middle" >Ready to query</text>
  </g>
  <text x="580.0" y="164" text-anchor="middle" font-size="11" opacity="0.9">Multiple network round trips + server-side setup — often milliseconds per connection.</text>
</svg>
```

That's multiple network round trips plus server-side setup — often **milliseconds**, which is
an eternity next to a query that might take microseconds. And it's not just latency: every
open connection consumes memory and a process/thread on the database, so databases enforce a
**hard maximum** (Postgres defaults to ~100). Open connections carelessly and you either
exhaust that limit — new requests get "too many connections" errors — or you spend more time
handshaking than querying.

### The connection pool

The fix is the same idea as any pool (you'll see it again in the concurrency phase): **open a
fixed set of connections once, keep them alive, and hand them out.** A request **borrows** a
connection from the pool, uses it, and **returns** it for the next request to reuse. The
expensive handshake happens a handful of times at startup, not once per request.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 700 356" width="100%" style="max-width:680px" role="img" aria-label="Requests borrow live connections from a pool of five; a request blocks if all are busy; connections return when done." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l14b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="350.0" y="26" text-anchor="middle" font-size="14" font-weight="700">The connection pool</text>
  <g fill="none">
  <path d="M198 101.0 L 428 118" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14b-ah)"/>
  <path d="M198 169.0 L 428 158" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14b-ah)"/>
  <path d="M214 248.0 L 428 214" fill="none" stroke="currentColor" stroke-width="1.6" stroke-dasharray="5 5" marker-end="url(#l14b-ah)"/>
  <path d="M428 250 Q 314.2 241.9 216 300" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l14b-ah)"/>
  </g>
  <g>
  <rect x="48" y="78" width="150" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="48" y="146" width="150" height="46" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="38" y="220" width="176" height="56" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="428" y="74" width="224" height="196" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="450" y="150" width="30" height="66" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="488" y="150" width="30" height="66" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="526" y="150" width="30" height="66" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="564" y="150" width="30" height="66" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="602" y="150" width="30" height="66" rx="5" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="123.0" y="104.9" font-size="11.5" text-anchor="middle" >Request 1</text>
  <text x="123.0" y="172.9" font-size="11.5" text-anchor="middle" >Request 2</text>
  <text x="126.0" y="243.9" font-size="11.5" text-anchor="middle" font-weight="700" >Request 3</text>
  <text x="126.0" y="259.9" font-size="10" text-anchor="middle" opacity="0.85" >waits if all busy</text>
  <text x="540" y="102" font-size="12" text-anchor="middle" font-weight="700" >Connection Pool</text>
  <text x="540" y="120" font-size="9.5" text-anchor="middle" opacity="0.8" >5 live, reused connections</text>
  <text x="465" y="240" font-size="9" text-anchor="middle" opacity="0.75" >c1</text>
  <text x="503" y="240" font-size="9" text-anchor="middle" opacity="0.75" >c2</text>
  <text x="541" y="240" font-size="9" text-anchor="middle" opacity="0.75" >c3</text>
  <text x="579" y="240" font-size="9" text-anchor="middle" opacity="0.75" >c4</text>
  <text x="617" y="240" font-size="9" text-anchor="middle" opacity="0.75" >c5</text>
  <text x="313.0" y="103.5" font-size="9.5" text-anchor="middle" opacity="0.75" >borrow</text>
  <text x="313.0" y="157.5" font-size="9.5" text-anchor="middle" opacity="0.75" >borrow</text>
  <text x="321.0" y="225.0" font-size="9.5" text-anchor="middle" opacity="0.75" >blocks</text>
  <text x="384" y="308" font-size="9.5" text-anchor="middle" opacity="0.75" >returns when done → reused</text>
  </g>
  <text x="350.0" y="344" text-anchor="middle" font-size="11" opacity="0.9">A request borrows a connection, uses it, then returns it for the next to reuse.</text>
</svg>
```

The critical knob is **pool size**, and it's a genuine trade-off (a frequent production
bottleneck):

- **Too small** and requests queue up waiting for a free connection — you've throttled your
  own throughput.
- **Too large** and you overwhelm the database with more concurrent work than its CPUs and
  memory can handle; past a point, *more* connections make everything *slower*. The database's
  connection cap is a ceiling you must stay under across *all* your app instances combined.

A pool that's exhausted makes a borrower **wait** (up to a checkout timeout, then error) — so
sizing it to your real concurrency, and keeping transactions short (Lesson 11) so connections
return quickly, is the whole game. Other typical knobs: a max idle time (close connections
that sit unused), a max lifetime (recycle old ones), and a min/max size range.

### The N+1 query problem

The second killer is subtler because each query looks fine. You want authors and their books:

```python
authors = db.query("SELECT * FROM author")            # 1 query
for a in authors:                                      # N authors...
    a.books = db.query(                                # ...one query EACH = N queries
        "SELECT * FROM book WHERE author_id = ?", a.id)
```

For 100 authors that's **101 queries**. The database handles each instantly, but every query
is a full round trip through the pool and over the network. At even 1 ms per round trip, 101
queries is ~100 ms of pure waiting — and it scales with your data, so the page that was snappy
with 10 authors is unusable with 1,000. It's called **N+1** because it's the 1 query for the
list plus N queries for the details.

The insidious part: ORMs (object-relational mappers) *cause N+1 by default*. Accessing
`author.books` inside a loop looks like touching a property, but each access secretly fires a
query. The N+1 is hidden behind innocent-looking code, which is why it survives review and
surfaces only under production data volumes.

### Killing N+1

Two standard fixes, both collapsing N+1 queries into one or two:

**A single JOIN** — ask the database to do the combining, in one query and one round trip:

```sql
SELECT author.name, book.title
FROM author
JOIN book ON book.author_id = author.id;   -- 1 query, all authors + all their books
```

**A batched `IN` query** — fetch the list, collect the ids, then fetch *all* related rows at
once (2 queries total, regardless of N):

```sql
SELECT * FROM author;                                   -- query 1: the list
SELECT * FROM book WHERE author_id IN (1, 2, 3, ...);   -- query 2: all books, batched
```

In an ORM, this is **eager loading** (Django's `select_related`/`prefetch_related`,
SQLAlchemy's `joinedload`/`selectinload`, Rails' `includes`) — you tell it up front "I'll need
the books," and it fetches them in one join or one batched query instead of N lazy ones. The
fix is always the same shape: **replace N round trips with a constant number.**

### Build It

We'll build a bounded, thread-safe **connection pool** and watch it cap and reuse connections,
then run an **N+1 vs. JOIN vs. batched** comparison and count the queries each one costs. The
pool's core is a semaphore that caps live connections and an idle list that enables reuse:

```python
@contextmanager
def acquire(self):
    self._sem.acquire()                    # block if all connections are checked out
    try:
        with self._lock:
            conn = self._idle.pop() if self._idle else self._open()  # reuse or open
        yield conn
    finally:
        with self._lock:
            self._idle.append(conn)        # return it for the next borrower
        self._sem.release()
```

The full pool, plus a real SQLite N+1 demo that counts queries, is in
[`code/pooling.py`](code/pooling.py). Run it:

```bash
python pooling.py
```

It fires 40 concurrent tasks through a 5-connection pool and shows only **5** connections were
ever opened (vs. 40 without a pool), then runs the author/book query three ways and prints the
query counts: **N+1 = 1+N**, **JOIN = 1**, **batched = 2** — the anti-pattern and its two fixes,
measured.

### Use It

In production you rarely write a pool by hand — you configure a battle-tested one — but every
knob maps to what you built:

- **App-side pools**: SQLAlchemy's `QueuePool`, Go's `database/sql` pool (`SetMaxOpenConns`),
  HikariCP (JVM), `node-postgres`'s `Pool`. Set the **max size** below the database's cap,
  divided across all app instances.
- **Server-side poolers**: **PgBouncer** sits in front of Postgres and multiplexes thousands
  of client connections onto a small set of real ones — essential when you have many app
  instances.
- **Find N+1**: turn on query logging in dev, or use an ORM debug toolbar, and watch for the
  same query repeating with different ids. That repetition *is* the N+1.
- **Fix N+1**: reach for eager loading / a join before optimizing anything else — it's often
  the single biggest win on a slow endpoint.

## Think about it

1. Your database allows 100 connections. You run 10 app instances, each with a pool max of 20.
   What goes wrong, and what's the arithmetic you should have done?
2. A page renders a list of 50 orders, each showing the customer's name. In the logs you see 51
   queries. Name the anti-pattern and write the one JOIN (or the two batched queries) that fixes
   it.
3. Why does making a connection pool *larger* eventually make the whole system *slower* rather
   than faster? What resource are you actually contending for?
4. An ORM makes `order.customer.name` fire a query every time it's accessed in a loop. Why is
   this so easy to miss in code review, and what one call turns 51 queries into 1 or 2?

## Key takeaways

- A database **connection is expensive** to open (TCP + TLS + auth + a server-side
  process/thread), and databases **cap** how many can exist — so opening one per request is
  slow and exhausts the limit.
- A **connection pool** opens a fixed set once and lends them out; **pool size** is a
  trade-off — too small throttles throughput, too large overwhelms the database — and must stay
  under the DB's cap across all app instances combined.
- The **N+1 problem** is 1 query for a list plus N queries for each item's details (101 round
  trips for 100 items); ORMs cause it by default through innocent-looking lazy property access.
- **Fix N+1** by replacing N round trips with a constant number: a single **JOIN**, or a
  **batched `IN`** query (2 total) — in ORMs, **eager loading**.

Next: [Migrations & Schema Evolution](../15-migrations-and-schema-evolution/) — how to change
a live database's schema safely, without downtime or data loss.
