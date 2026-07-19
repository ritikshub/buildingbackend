# Polyglot Persistence

> The end of this phase is not "pick the one right database." It's the senior realization that a real system uses *several* — a relational core for money, a cache for speed, a search index for text, maybe a graph for recommendations — each placed exactly where its pressure is felt. The hard part was never choosing them. It's keeping them from lying to each other. Polyglot persistence is powerful, and it is a tax; this lesson is how to pay the least tax for the most benefit.

**Type:** Learn
**Languages:** —
**Prerequisites:** [When Not to Use SQL](../01-when-not-to-use-sql/), [Document Databases](../03-document-databases/), [Data Modeling by Access Pattern](../07-data-modeling-by-access-pattern/), [Durability: Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/)
**Time:** ~50 minutes

## The Problem

Go back to the e-commerce system you walked in Lesson 1, but now you've finished the phase and you
know every tool. Trace the data one more time, and each part genuinely points at a different store:

- **Orders, payments, inventory** — money; needs ACID transactions and strong consistency → relational.
- **Sessions and the cart** — one key, blindingly fast, disposable → key-value (Redis).
- **The product catalog** — heterogeneous, schema shifts weekly → document (or Postgres `JSONB`).
- **Product search** — full-text "wireless headphones under $50" → a search engine (Elasticsearch).
- **"Customers who bought this…"** — deep co-purchase traversal → graph.
- **Site metrics and clickstream** — timestamped firehose → time-series.
- **Product images** — large blobs → object storage (S3).

The naïve reading of Phase 4 is "use the best database for each job," and if you follow it literally
you arrive at seven data stores. Each is *individually* optimal. Together they are a different kind of
problem entirely — and it is not the problem you spent this phase solving.

Because now you must **run** seven systems: back them up, monitor them, patch them, secure them, staff
the on-call for them. Your data is **duplicated** across them: a product's name and price live in the
relational database *and* the search index *and* the cache. And the moment you have the same fact in
two places, you face the question that decides whether this architecture is a triumph or a debugging
nightmare: **when a customer edits a product and you write it to Postgres but the update to
Elasticsearch fails, your two systems now disagree — and nothing will ever fix it on its own.**

That is the real subject of this final lesson. Not "which database" — you can answer that now. It's
**how multiple databases coexist without lying to each other**, and how a senior engineer decides how
many is too many. This deliberate mix of stores is called **polyglot persistence**, and it's the
destination the whole phase has been climbing toward.

## The Concept

### What polyglot persistence is

**Polyglot persistence** is using multiple, different data-storage technologies within a single system,
each chosen to fit the shape and access pattern of one slice of the data. The term is a deliberate echo
of "polyglot programming" (using several languages in one system); it was popularized by Martin Fowler
and Pramod Sadalage in *NoSQL Distilled* (2012). The idea is not "collect databases" — it's "stop
forcing one database to be good at everything, and place each part of your data where it thrives."

The mapping from Lesson 1's five pressures to the store that relieves each is the phase in one table —
and it's exactly the e-commerce breakdown above:

| Slice of data | Pressure (Lesson 1) | Store | Phase 4 lesson |
|---|---|---|---|
| Orders, payments | none — needs ACID | Relational (Postgres) | — (Phase 3) |
| Sessions, cart | speed, simple key | Key-value (Redis) | 2 |
| Product catalog | schema flexibility | Document / `JSONB` | 3 |
| Activity feed, messaging | write throughput | Wide-column (Cassandra) | 4 |
| Metrics, clickstream | timestamped firehose | Time-series | 5 |
| Recommendations | deep traversal | Graph | 6 |

### The first rule: one source of truth per fact

Before any syncing machinery, the decision that makes polyglot persistence *tractable* is this:
**designate exactly one store as the system of record for each piece of data, and treat every other
copy as a derived, rebuildable projection of it.**

- The **system of record** (the *primary*, the *source of truth*) owns the fact. For a product's core
  data, that's usually the relational database — the one with transactions and constraints.
- Every **derived store** — the search index, the cache, the recommendation graph — holds a *copy*
  shaped for a specific read, and must be **rebuildable from the source of truth**. If the search index
  is corrupted or lost, you re-derive it from Postgres and lose nothing permanent.

The failure that sinks polyglot systems is having **two stores both believe they own the same fact**,
so when they disagree there is no authority to break the tie. Avoid it by construction: one owner, and
the rest are downstream views. This is the same "one fact in one place" instinct as normalization
(Phase 3, Lesson 7) — lifted from columns-within-a-database up to databases-within-a-system.

Two common shapes realize this:

- **Primary + derived projections.** One relational system of record, plus read-optimized copies (a
  search index, a cache, a graph) fed *from* it. The subject of the rest of this lesson.
- **Per-service ownership (microservices).** Each service owns its own database, chosen for its needs,
  and no other service reaches into it — they ask via its API. The "source of truth per fact" rule
  becomes "one owning service per fact" (a service-boundary question).

### The central hazard: the dual-write problem

Here is the specific, unavoidable danger, and it deserves its own name because it is *the* reason
polyglot persistence is hard. The instant your application writes the same logical change to **two
stores** — the database *and* the search index, the database *and* the cache, the database *and* a
message broker — you are performing a **dual write**, and **there is no transaction that spans both.**
Either write can fail after the other succeeds:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 592" width="100%" style="max-width:880px" role="img" aria-label="The dual-write problem. An application handles one logical change — a product's price going from fifty dollars to forty — and must write it to two different systems. Write one updates Postgres and commits successfully. Write two indexes the same change into Elasticsearch and fails, because of a network blip or a crash. Both writes are drawn inside a dashed red boundary labelled as the transaction that does not exist: there is no shared commit and no shared rollback across two separate systems, so Postgres cannot be undone just because Elasticsearch failed. Downstream, the source of truth says forty dollars while the search index still says fifty, and a red not-equals badge sits between them. Nothing in the system holds a record that the second write was ever owed, so there is no retry and no reconciliation: the disagreement is silent and permanent.">
  <defs>
    <marker id="p4l8a-ab" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="p4l8a-ad" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">The dual write: two systems, two writes, and no transaction around them</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="270" y="44" width="340" height="48" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.7"/>
    <text x="440" y="66" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">APPLICATION</text>
    <text x="440" y="84" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">one logical change: product price $50 → $40</text>

    <rect x="80" y="104" width="720" height="152" rx="12" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="8 6"/>

    <g fill="none" stroke="#7f7f7f" stroke-width="1.6">
      <path d="M440 92 L440 128"/>
      <path d="M265 128 L615 128"/>
    </g>
    <path d="M265 128 L265 156" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p4l8a-ab)"/>
    <path d="M615 128 L615 156" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p4l8a-ad)"/>

    <rect x="125" y="160" width="280" height="64" rx="9" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.8"/>
    <text x="265" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">1 · WRITE to Postgres</text>
    <text x="265" y="200" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">UPDATE products SET price = 40</text>
    <text x="265" y="216" text-anchor="middle" font-size="9.5" font-weight="700" fill="#3553ff">✓ COMMITS successfully</text>

    <rect x="475" y="160" width="280" height="64" rx="9" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-width="1.8"/>
    <text x="615" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">2 · WRITE to Elasticsearch</text>
    <text x="615" y="200" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">index products: price = 40</text>
    <text x="615" y="216" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">✗ FAILS — network blip / crash</text>

    <text x="440" y="242" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">✗ THIS BOUNDARY DOES NOT EXIST — no shared commit, no shared rollback</text>

    <path d="M265 256 L265 288" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p4l8a-ab)"/>
    <text x="278" y="277" font-size="9" fill="#3553ff">durable</text>
    <path d="M615 256 L615 288" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 5" marker-end="url(#p4l8a-ad)"/>
    <text x="628" y="277" font-size="9" fill="#d64545">never arrives</text>

    <path d="M170 300 L170 348 A95 13 0 0 0 360 348 L360 300" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/>
    <ellipse cx="265" cy="300" rx="95" ry="13" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.8"/>
    <text x="265" y="326" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Postgres</text>
    <text x="265" y="343" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">the system of record</text>

    <path d="M520 300 L520 348 A95 13 0 0 0 710 348 L710 300" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
    <ellipse cx="615" cy="300" rx="95" ry="13" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="615" y="326" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">Elasticsearch</text>
    <text x="615" y="343" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">unchanged since last sync</text>

    <path d="M265 364 L265 390" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#p4l8a-ab)"/>
    <path d="M615 364 L615 390" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#p4l8a-ad)"/>

    <rect x="135" y="394" width="260" height="52" rx="9" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.7"/>
    <text x="265" y="417" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">source of truth: $40</text>
    <text x="265" y="435" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">what the customer is charged</text>

    <rect x="485" y="394" width="260" height="52" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.7"/>
    <text x="615" y="417" text-anchor="middle" font-size="11" font-weight="700" fill="#d64545">search index: $50</text>
    <text x="615" y="435" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">what the customer sees</text>

    <circle cx="440" cy="420" r="28" fill="#d64545" fill-opacity="0.14" stroke="#d64545" stroke-width="2"/>
    <text x="440" y="429" text-anchor="middle" font-size="24" font-weight="700" fill="#d64545">≠</text>

    <rect x="90" y="470" width="700" height="58" rx="10" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-opacity="0.75" stroke-width="1.7"/>
    <text x="440" y="492" text-anchor="middle" font-size="11.5" font-weight="700" fill="#d64545">They disagree — and NOTHING will ever reconcile them</text>
    <text x="440" y="511" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">no retry queue, no record that the second write was ever owed — the failure is silent and permanent</text>

    <text x="440" y="552" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Ordering cannot save you: the gap between the first commit and the second is exactly where the failure lives.</text>
    <text x="440" y="572" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">Every real fix works the same way — by removing the second synchronous write. The next diagram does exactly that.</text>
  </g>
</svg>
```

Postgres commits `$40`; the call to Elasticsearch times out; the process crashes before it can retry.
Now the source of truth says `$40` and search says `$50`, **forever**, until something notices. You
cannot fix this by "just wrapping both in a transaction" — they're different systems with no shared
commit. You cannot fix it reliably by "write to the DB, then update search" — the gap between the two
is exactly where the failure lives. Recognizing that this gap is unclosable by ordering alone is the
whole insight; the solutions below all work by *removing the second synchronous write*.

### Keeping stores in sync without a distributed transaction

Three techniques, used together, turn the dual write into something reliable.

**The Outbox Pattern.** Instead of writing to the database *and then* to the other store, write the
data change **and a record of the event to publish** in the **same database transaction**, into an
`outbox` table. That write is atomic — both rows commit or neither does, no dual write. A separate
**relay** process then reads unpublished rows from the outbox and pushes them to the search index,
cache, or message broker, marking each done. If the relay crashes, it retries from the outbox on
restart; nothing is lost, because the intent to publish was committed atomically with the data.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 648" width="100%" style="max-width:880px" role="img" aria-label="The transactional outbox pattern, drawn as the same picture as the dual-write diagram so the fix reads as a transformation of it. The same application handles the same price change, but now both writes go into one database. Inside a solid green boundary — one database transaction — sit two rows: the business write, UPDATE products SET price equals forty, and the event write, INSERT INTO outbox recording price_changed. Both rows commit or neither does, so there is no dual write at all. The transaction commits to Postgres, which now holds the product row and the outbox row together. A separate outbox relay polls the unpublished outbox rows and publishes them, with retries, to the derived stores: the search index and the cache. If a downstream store is down, the outbox row simply stays unpublished and the relay retries until it lands, so the failure is temporary and self-healing rather than silent and permanent. The price is eventual consistency: the derived stores lag the database by the relay's propagation delay, so exact prices must still be read from Postgres.">
  <defs>
    <marker id="p4l8b-ag" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14" font-weight="700" fill="currentColor">The outbox: the same two writes, but ONE of them is now just a row</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <rect x="270" y="44" width="340" height="48" rx="10" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.7"/>
    <text x="440" y="66" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">APPLICATION</text>
    <text x="440" y="84" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the same change: product price $50 → $40</text>

    <rect x="80" y="104" width="720" height="152" rx="12" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="2.4"/>
    <text x="96" y="126" font-size="10" font-weight="700" fill="#0fa07f">BEGIN</text>
    <text x="784" y="248" text-anchor="end" font-size="10" font-weight="700" fill="#0fa07f">COMMIT</text>

    <path d="M440 92 L440 128" fill="none" stroke="#7f7f7f" stroke-width="1.6"/>
    <path d="M265 128 L615 128" fill="none" stroke="#0fa07f" stroke-width="1.6"/>
    <path d="M265 128 L265 156" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p4l8b-ag)"/>
    <path d="M615 128 L615 156" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p4l8b-ag)"/>

    <rect x="125" y="160" width="280" height="64" rx="9" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.8"/>
    <text x="265" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">1 · the business write</text>
    <text x="265" y="200" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">UPDATE products SET price = 40</text>
    <text x="265" y="216" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">the fact itself</text>

    <rect x="475" y="160" width="280" height="64" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="615" y="182" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">2 · the event write</text>
    <text x="615" y="200" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">INSERT INTO outbox (price_changed)</text>
    <text x="615" y="216" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">the intent to publish: a row, not a network call</text>

    <text x="440" y="242" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">✓ ONE DATABASE TRANSACTION — both rows commit, or neither does</text>

    <path d="M440 256 L440 272 L265 272 L265 288" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#p4l8b-ag)"/>
    <text x="452" y="269" font-size="9.5" font-weight="700" fill="#0fa07f">both rows land together — or not at all</text>

    <path d="M170 300 L170 348 A95 13 0 0 0 360 348 L360 300" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/>
    <ellipse cx="265" cy="300" rx="95" ry="13" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.8"/>
    <text x="265" y="322" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">Postgres</text>
    <text x="265" y="338" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">products row + outbox row,</text>
    <text x="265" y="351" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">in the same commit</text>

    <path d="M362 330 L468 330" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#p4l8b-ag)"/>
    <text x="416" y="322" text-anchor="middle" font-size="8.5" fill="#0fa07f">reads the outbox</text>

    <rect x="475" y="298" width="280" height="64" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="1.8"/>
    <text x="615" y="320" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">OUTBOX RELAY</text>
    <text x="615" y="337" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">polls unpublished outbox rows</text>
    <text x="615" y="352" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">marks each done only after it publishes</text>

    <g fill="none" stroke="#0fa07f" stroke-width="1.8">
      <path d="M615 362 L615 384"/>
      <path d="M520 384 L740 384"/>
      <path d="M520 384 L520 406" marker-end="url(#p4l8b-ag)"/>
      <path d="M740 384 L740 406" marker-end="url(#p4l8b-ag)"/>
    </g>
    <text x="512" y="381" text-anchor="end" font-size="9" font-weight="700" fill="#0fa07f">publish · RETRIES</text>

    <path d="M432 420 L432 458 A88 12 0 0 0 608 458 L608 420" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
    <ellipse cx="520" cy="420" rx="88" ry="12" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="520" y="443" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">search index</text>
    <text x="520" y="458" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">derived · rebuildable</text>

    <path d="M652 420 L652 458 A88 12 0 0 0 828 458 L828 420" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.8"/>
    <ellipse cx="740" cy="420" rx="88" ry="12" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.8"/>
    <text x="740" y="443" text-anchor="middle" font-size="10.5" font-weight="700" fill="#7c5cff">cache</text>
    <text x="740" y="458" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">derived · rebuildable</text>

    <rect x="60" y="396" width="340" height="82" rx="10" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.6"/>
    <text x="230" y="418" text-anchor="middle" font-size="10" font-weight="700" fill="#e0930f">NOT instant — eventually consistent</text>
    <text x="230" y="436" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">the derived stores lag Postgres by the</text>
    <text x="230" y="451" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">relay's propagation delay (ms → seconds)</text>
    <text x="230" y="468" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">read exact prices from the source of truth</text>

    <rect x="90" y="500" width="700" height="58" rx="10" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.8" stroke-width="1.7"/>
    <text x="440" y="522" text-anchor="middle" font-size="11.5" font-weight="700" fill="#0fa07f">If a downstream store is down, the outbox row just stays unpublished</text>
    <text x="440" y="541" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.8">the relay retries until it lands — the failure is temporary and self-healing, never silent and permanent</text>

    <text x="440" y="582" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">The dual write is gone: the app writes to ONE system, atomically. Everything else is fed from that single commit.</text>
    <text x="440" y="602" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">The failure mode moved from permanent silent divergence to temporary lag — the price you pay is eventual consistency.</text>
    <text x="440" y="622" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.72">(Delivery is at-least-once, so every consumer must be idempotent: applying the same event twice must equal applying it once.)</text>
  </g>
</svg>
```

**Change Data Capture (CDC).** The elegant generalization — and a beautiful callback to Phase 3. Every
relational database already writes a **write-ahead log (WAL)**: an ordered, durable record of every
committed change (Phase 3, Lesson 13 — the log you *built*). **CDC tails that log** (tools like
Debezium) and streams every insert, update, and delete out to whatever needs it. You don't change your
application code at all; the derived stores subscribe to the database's own change stream. The WAL you
made for crash recovery becomes the **integration backbone** of the whole system — the source of truth
narrating its every change, and the projections following along.

**Idempotent, eventually-consistent consumers.** Both outbox relays and CDC streams deliver
**at-least-once** — a crash mid-publish means an event may be delivered twice (Phase 6; glossary:
*Exactly-Once Delivery* is mostly a myth). So every consumer that updates a derived store must be
**idempotent**: applying the same event twice must equal applying it once (dedupe on an event id, or
make the update a set-to-this-value rather than an increment — the idempotency discipline from Phase 2,
Lesson 7 and Lesson 2 of this phase). And you must accept **eventual consistency between stores**: the
search index lags the database by the propagation delay. Design the UX for it — read the price from the
source of truth on the product page where it must be exact, and tolerate a second of staleness in
search results where it doesn't matter. (This is Lesson 1's BASE trade, now *between* your stores rather
than within one.)

### The cost ledger: why "best tool for each job" is a trap

Now the senior counterweight, because everything above makes adding a store sound routine, and it
isn't. Every new store you add carries a permanent bill:

- **Operations:** one more system to run, back up, monitor, patch, secure, capacity-plan, and page
  someone for at 3 a.m.
- **A new failure mode:** it can be down, slow, or out of sync while everything else is fine.
- **Duplicated data + a sync mechanism:** an outbox/CDC pipeline that is itself code to write, test,
  and operate.
- **A consistency window:** the lag between source and projection, which your product must tolerate.
- **Cognitive load:** every engineer must now understand another data model, query language, and set of
  failure behaviors. Cross-store questions become app-side joins.

So the rule that closes the phase is the mirror image of "use the best tool for each job":

> **Minimize the number of stores. Add one only when a *named* pressure genuinely demands it and your
> current store truly cannot relieve it.**

And remember Lesson 1's "the line has moved": Postgres has absorbed most of what used to require a
second store — `JSONB` (documents), partitioning and TimescaleDB (time-series), full-text search and
`pgvector` (search/embeddings), `LISTEN`/`NOTIFY` (pub/sub), recursive CTEs and Apache AGE (graph). For
a huge fraction of "we need a second database" moments, the honest answer is a Postgres feature you
didn't know existed — which relieves the pressure with **zero** new operational cost. **Every store you
*don't* add is a distributed-systems problem you don't have.** Boring, in persistence, is a feature.

### Bringing the phase home: the decision framework

Everything from Lesson 1 to here collapses into one repeatable decision:

1. **Start with the relational database as the system of record.** It's the right default for the vast
   majority of data, and it's where the transactional core (money) must live.
2. **Name the specific pressure** pushing on a slice of data — schema, joins/traversal, write
   throughput, scale-out, or consistency (Lesson 1's five). If you can't name one, there is no pressure;
   stay put.
3. **Check whether your relational database already relieves it** — `JSONB`, partitioning, FTS,
   `pgvector`, recursive CTE. If it does, use that: no new system.
4. **Only if it genuinely can't, and the scale justifies the operational cost,** add the specialized
   store — and make it a **derived, rebuildable projection** of the source of truth where possible.
5. **Sync it with the outbox pattern or CDC, and make the consumers idempotent.** Accept the eventual
   consistency between stores and design the UX around it.

That is polyglot persistence done well: not five databases by reflex, and not one database tortured
into five jobs, but **a relational core plus a specialized store exactly where a named pressure demands
one — each kept honest by a source of truth and a reliable change stream.**

## Think about it

1. Your service writes an order to Postgres and then publishes an "order placed" event to Kafka so the
   search index and email service can react. The Kafka publish fails after the Postgres commit. Name
   the problem, name the pattern that fixes it, and explain in one sentence *why* that pattern works
   when "write DB, then publish" doesn't.
2. In a Postgres + Elasticsearch setup where products are edited in Postgres and searched in
   Elasticsearch, which store is the source of truth — and what must be true of the search index for
   the architecture to be safe?
3. Change Data Capture uses which structure from Phase 3 as its backbone, and why is it elegant that
   the same structure you built for crash recovery becomes the system's integration backbone?
4. Give one concrete case where adding a *second* datastore is the right senior decision, and one where
   it's cargo-culting — and state the question that distinguishes them.
5. An outbox relay delivers at-least-once, so a consumer may see the same "price changed to $40" event
   twice. Why is that fine if the consumer is idempotent, and what would go wrong if the event were
   "increase price by $5" instead?

## Key takeaways

- **Polyglot persistence** is using several storage technologies in one system, each matched to a
  slice of data's shape and pressure (Lesson 1's map). It's the phase's destination — and a real,
  permanent operational tax, not a free win.
- **Designate one source of truth per fact;** treat every other store as a **derived, rebuildable
  projection**. The failure that sinks these systems is two stores both claiming to own the same fact
  with no authority to break a tie.
- The central hazard is the **dual-write problem**: writing the same change to two stores has **no
  transaction spanning both**, so a failure between them causes permanent disagreement — and ordering
  the writes cannot fix it.
- Sync stores **without** a distributed transaction: the **outbox pattern** (write data + event in one
  atomic DB transaction, relay publishes) and **CDC** (tail the **WAL** from Phase 3 and stream every
  change), with **idempotent consumers** and accepted **eventual consistency between stores**.
- **Minimize stores.** Add one only for a *named* pressure your current store genuinely can't relieve,
  at a scale that justifies the cost — and remember Postgres has absorbed `JSONB`, partitioning, FTS,
  `pgvector`, and graph traversal. Every store you don't add is a distributed-systems problem you don't
  have.

Next: [Why & Where to Cache](../../05-caching/01-why-and-where-to-cache/) — you've just seen the cache
appear as one of the derived stores in a polyglot system; Phase 5 goes deep on it, starting with the
one question that governs every cache: what to keep, where, and for how long.
