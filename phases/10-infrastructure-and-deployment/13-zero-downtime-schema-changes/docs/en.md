# Zero-Downtime Schema & Contract Changes

> The rename took microseconds. The incompatibility lasted ninety seconds — and it produced two kinds of damage, not one. Measured here: the same column rename through a mixed fleet cost **202 failed requests, 125 wrong answers, and 90 permanently corrupted exported rows**; staged as expand/migrate/contract over five separately deployable steps, the identical 1,700 requests produced **0, 0 and 0**. Then the mechanism nobody teaches: a one-millisecond `ALTER` that was merely *waiting* for a lock stalled **42 innocent queries for 51.7 query-seconds**, and one setting cut that to 4 and 0.08.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Deployment Strategies](../11-deployment-strategies/), [Migrations & Schema Evolution](../../03-relational-databases/15-migrations-and-schema-evolution/), [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/)
**Time:** ~85 minutes

## The Problem

**15:40.** A migration runs as part of a normal deploy. It is one line — a type widening on `orders.total_cents`, reviewed by two people, tested in CI (Continuous Integration), applied to staging that morning without incident. In production it takes the lock and does not give it back for four minutes. Checkout returns 500s. The status page goes yellow. Somebody kills the migration at 15:44, the site recovers, and the incident review concludes that the table was "too big for an online change."

That conclusion is wrong, and the detail that makes it wrong is the one nobody noticed: **at 15:40 that table was not being written to.** Order volume at that hour is low. There was no write contention. What there *was* was a reporting query that had started at 15:38 and would run for six minutes — a plain `SELECT`, reading a table it had every right to read. The `ALTER` queued behind it. And then every subsequent query on `orders` queued behind the `ALTER`, including the ones that would have been perfectly happy to run alongside the report. The migration's own work took a few milliseconds. Its *waiting* took the site down.

**The second failure is quieter, and it is worse.** Two weeks later, a different deploy. New code reads `orders.shipping_address`; old code writes `orders.ship_to`. The rollout takes eleven minutes because one node is slow to pull the image. For those eleven minutes, roughly half the fleet writes a field the other half cannot see. Nothing throws. The error rate stays at 0.00%. Latency is flat. Every dashboard is green, every alert is silent, and the deploy is marked successful.

At 06:15 the next morning, the finance reconciliation job flags 90 orders whose shipping address is `NULL`. They were placed by real customers, charged to real cards, and written to the warehouse export with a blank address. The window that caused it closed thirteen hours earlier. There is nothing to roll back to; the bad rows are simply *there*, indistinguishable from good ones except by the field that is missing.

Two failures, one root cause. **A schema change is not an event that happens to a database. It is an event that happens to a running fleet.** Phase 3's [Migrations & Schema Evolution](../../03-relational-databases/15-migrations-and-schema-evolution/) built the runner that applies a migration and taught expand-contract as a pattern. This lesson is the other half: what a rolling deploy does to a schema change, and what a schema change does to a live fleet.

## The Concept

### Two versions of your code run at the same time, against one database

Lesson 11 established this as a property of a rolling rollout: for some interval, some instances are on the old version and some are on the new one. That was a fact about your deployment. Here it becomes a **constraint on every schema change you will ever make**:

> **During a rolling deploy, version N and version N+1 execute concurrently against a single shared database. Therefore every schema state must be compatible with the code version before it and the code version after it, for as long as both can exist.**

The last clause is the one that gets underestimated. How long can both exist? A healthy rollout of six instances is maybe ninety seconds. But:

- A **canary** deliberately holds the mixed state for an hour, or a day, because that is the entire point of a canary.
- A **stalled rollout** — one node that will not schedule, a failing readiness probe, a paused Argo CD sync — holds it indefinitely, and nobody notices because the old version is still serving fine.
- A **rollback** puts you back into the mixed state *after* you thought you had left it, and it does so at the worst possible moment, when you are already in an incident and reasoning badly.
- **Anything not in the rollout at all**: a cron job on a box that deploys weekly, a nightly export, a mobile client, a partner integration, an analytics worker that reads a replica.

So the honest answer is that the overlap window is **unbounded**. Design for that, and a stalled rollout is a non-event. Design for ninety seconds, and every one of the bullets above is an outage.

Here is that window as measured by the Build It — one `ALTER TABLE orders RENAME COLUMN ship_to TO shipping_address` against a six-instance fleet, which is exactly what the second incident above was:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 496" width="100%" style="max-width:840px" role="img" aria-label="A rolling deploy timeline in which a single ALTER TABLE RENAME has already run against the shared database. Through the first two stages the fleet is mixed, so old v1 code writing ship_to raises errors and reads it as None, while new v2 code works correctly. The measured damage is 164 errors, 102 bad reads and 69 bad exports in the first stage, 38, 23 and 21 in the second, and zero in the third once every instance is on v2, for a total of 202 errors, 125 bad reads and 90 permanently corrupted exported rows.">
  <defs>
    <marker id="l13-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One ALTER, one database, two versions of your code</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <rect x="176" y="40" width="464" height="344" rx="10" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-width="1.8" stroke-dasharray="7 4"/>
    <text x="408" y="58" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">THE OVERLAP WINDOW — both versions live, one schema</text>

    <g fill="currentColor" text-anchor="middle">
      <text x="290" y="80" font-size="11.5" font-weight="700">t+0s</text>
      <text x="522" y="80" font-size="11.5" font-weight="700">t+40s</text>
      <text x="754" y="80" font-size="11.5" font-weight="700">t+90s</text>
      <text x="290" y="94" font-size="9" opacity="0.8">3 of 6 on v2</text>
      <text x="522" y="94" font-size="9" opacity="0.8">5 of 6 on v2</text>
      <text x="754" y="94" font-size="9" opacity="0.8">6 of 6 on v2</text>
    </g>

    <g stroke-width="1.6">
      <rect x="233" y="104" width="14" height="16" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="253" y="104" width="14" height="16" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="273" y="104" width="14" height="16" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="293" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="313" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="333" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>

      <rect x="465" y="104" width="14" height="16" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f"/>
      <rect x="485" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="505" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="525" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="545" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="565" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>

      <rect x="697" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="717" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="737" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="757" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="777" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
      <rect x="797" y="104" width="14" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor" font-size="9" opacity="0.7">
      <text x="20" y="116">FLEET</text>
      <text x="20" y="152">v1 CODE</text>
      <text x="20" y="166" font-size="8.5">writes/reads</text>
      <text x="20" y="177" font-size="8.5">ship_to</text>
      <text x="20" y="228">v2 CODE</text>
      <text x="20" y="242" font-size="8.5">writes/reads</text>
      <text x="20" y="253" font-size="8.5">shipping_addr</text>
      <text x="20" y="304">SCHEMA</text>
      <text x="20" y="392">DAMAGE</text>
    </g>

    <g stroke-width="1.8">
      <rect x="184" y="132" width="212" height="64" rx="8" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="416" y="132" width="212" height="64" rx="8" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="648" y="132" width="212" height="64" rx="8" fill="#7f7f7f" fill-opacity="0.08" stroke="#7f7f7f"/>
      <rect x="184" y="208" width="178" height="52" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="416" y="208" width="178" height="52" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
      <rect x="648" y="208" width="178" height="52" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="196" y="150" font-size="9.5" font-weight="700" fill="#d64545">INSERT ... ship_to  -&gt;  500</text>
      <text x="196" y="164" font-size="8.5" opacity="0.9">no such column. The order is lost.</text>
      <text x="196" y="180" font-size="9.5" font-weight="700" fill="#d64545">SELECT *  -&gt;  row['ship_to'] = None</text>
      <text x="196" y="192" font-size="8.5" opacity="0.9">no exception, no log line, no alert</text>
      <text x="428" y="150" font-size="9.5" font-weight="700" fill="#d64545">INSERT ... ship_to  -&gt;  500</text>
      <text x="428" y="164" font-size="8.5" opacity="0.9">fewer v1 instances, same failure</text>
      <text x="428" y="180" font-size="9.5" font-weight="700" fill="#d64545">SELECT *  -&gt;  row['ship_to'] = None</text>
      <text x="428" y="192" font-size="8.5" opacity="0.9">the export job PERSISTS the None</text>
      <text x="754" y="160" font-size="9.5" text-anchor="middle" opacity="0.75">no v1 instances left</text>
      <text x="754" y="176" font-size="8.5" text-anchor="middle" opacity="0.75">the errors stop here</text>
      <text x="196" y="228" font-size="9.5" font-weight="700" fill="#0fa07f">INSERT shipping_address  OK</text>
      <text x="196" y="246" font-size="9.5" font-weight="700" fill="#0fa07f">SELECT shipping_address  OK</text>
      <text x="428" y="228" font-size="9.5" font-weight="700" fill="#0fa07f">INSERT shipping_address  OK</text>
      <text x="428" y="246" font-size="9.5" font-weight="700" fill="#0fa07f">SELECT shipping_address  OK</text>
      <text x="660" y="228" font-size="9.5" font-weight="700" fill="#0fa07f">INSERT shipping_address  OK</text>
      <text x="660" y="246" font-size="9.5" font-weight="700" fill="#0fa07f">SELECT shipping_address  OK</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="1.5">
      <path d="M380 196 L 380 282" marker-end="url(#l13-a1)" stroke="#d64545"/>
      <path d="M612 196 L 612 282" marker-end="url(#l13-a1)" stroke="#d64545"/>
    </g>
    <g fill="none" stroke="#0fa07f" stroke-width="1.5">
      <path d="M270 260 L 270 282" marker-end="url(#l13-a1)" stroke="#0fa07f"/>
      <path d="M502 260 L 502 282" marker-end="url(#l13-a1)" stroke="#0fa07f"/>
      <path d="M734 260 L 734 282" marker-end="url(#l13-a1)" stroke="#0fa07f"/>
    </g>

    <rect x="184" y="286" width="676" height="42" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="2"/>
    <g fill="currentColor">
      <text x="200" y="304" font-size="11" font-weight="700">ONE DATABASE:  orders(id, customer, total_cents, shipping_address)</text>
      <text x="200" y="320" font-size="9" opacity="0.9">ALTER TABLE orders RENAME COLUMN ship_to TO shipping_address; — ran in microseconds, at t+0</text>
    </g>

    <g fill="currentColor" font-size="9.5">
      <text x="184" y="348" font-size="9" opacity="0.7">5xx / bad reads / bad exports, per stage — 1,700 requests total</text>
      <text x="290" y="370" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">164 / 102 / 69</text>
      <text x="522" y="370" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">38 / 23 / 21</text>
      <text x="754" y="370" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">0 / 0 / 0</text>
    </g>

    <rect x="184" y="396" width="676" height="60" rx="9" fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="200" y="414" font-size="10.5" font-weight="700" fill="#d64545">THE LOUD HALF: 202 requests raised OperationalError — visible, paged, fixed by finishing the rollout.</text>
      <text x="200" y="432" font-size="10.5" font-weight="700" fill="#d64545">THE QUIET HALF: 90 exported rows persisted a NULL address. Nothing raised. Nothing alerted.</text>
      <text x="200" y="448" font-size="9" opacity="0.9">The window closed at t+90s and the 5xxs stopped. The 90 corrupt rows are still there the next morning.</text>
    </g>

    <text x="440" y="480" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The rename was instant. The incompatibility lasted 90 seconds — and would last forever if the rollout stalled.</text>
  </g>
</svg>
```

Look at the two rows of damage separately, because they behave completely differently.

The **202 errors** are loud. They page someone, they show up on a dashboard, and they *heal on their own* the moment the rollout finishes — which is why this failure mode gets systematically under-rated in retrospectives. "We had a ninety-second blip during the deploy" is a sentence people say and then move on from.

The **90 corrupted export rows** do not heal. They are the residue of a read path that every ORM (Object-Relational Mapper) in existence uses: `SELECT *`, then pull a key out of the resulting row object. When the column is gone, that key lookup does not raise — it returns `None`, or an empty string, or a zero, depending on your framework's helpfulness. The application then does something perfectly ordinary with that value, like writing it to another table. **A missing column is an exception on the write path and a silent default on the read path**, and the silent one is the one that produces artifacts you find in the morning.

### Expand, migrate, contract — as separate deploys

The pattern's name is **parallel change**, and the three-word version is **expand / migrate / contract**. Phase 3 introduced it as four stages. The deployment view adds the constraint that makes it actually work, and it is the one people skip:

> **Each step must be independently deployable and independently reversible. If two of them ship together, you do not have parallel change — you have the naive rename with extra steps.**

- **EXPAND.** Add the new shape *additively*, never touching the old one. New column nullable, no default constraint that requires a rewrite. Then deploy code that **dual-writes**: it writes both the old and new shape on every write, and still reads the old one. Now old code and new code both work, because the old shape is still authoritative and still maintained.
- **MIGRATE.** Backfill existing rows so the new shape is complete for historical data. Then deploy code that **reads the new shape** while still dual-writing. This is the step that must not be rushed: reading the new column before the backfill has finished means reading `NULL` for every row the backfill has not reached — silent corruption again, on a schedule you chose.
- **CONTRACT.** Once nothing reads *or* writes the old shape — verified, not assumed — deploy code that writes only the new shape, soak it, then drop the old column. This step destroys data and is the only one you cannot undo.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The same column rename staged as expand, migrate and contract across five separately deployable steps. Step zero is the baseline on v1. Step one expands by adding a nullable column and deploys dual-writing code. Step two backfills 574 legacy rows in seven bounded batches. Step three deploys readers of the new column. Step four removes the dual write. Step five contracts by dropping the old column. At every step the schema state is compatible with both the version before it and the version after it, and 1700 requests through the mixed fleet produced zero errors, zero bad reads and zero corrupted exported rows.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Expand / migrate / contract — five steps, each deployable on its own</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="currentColor" font-size="8.5" font-weight="700" opacity="0.65">
      <text x="62" y="64">STEP &amp; ACTION</text>
      <text x="264" y="64">FLEET</text>
      <text x="374" y="64">SCHEMA STATE</text>
      <text x="576" y="64">WRITES GO TO</text>
      <text x="722" y="64">READS COME FROM</text>
    </g>
    <path d="M20 70 L 858 70" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.4"/>

    <g stroke-width="2" fill="none">
      <rect x="20" y="78" width="30" height="40" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f"/>
      <rect x="20" y="126" width="30" height="88" rx="6" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
      <rect x="20" y="222" width="30" height="88" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
      <rect x="20" y="318" width="30" height="40" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
    </g>
    <g font-size="9.5" font-weight="700" text-anchor="middle">
      <text x="35" y="102" fill="#7f7f7f" transform="rotate(-90 35 102)">BASE</text>
      <text x="35" y="170" fill="#0fa07f" transform="rotate(-90 35 170)">EXPAND</text>
      <text x="35" y="266" fill="#e0930f" transform="rotate(-90 35 266)">MIGRATE</text>
      <text x="35" y="338" font-size="7.5" fill="#d64545" transform="rotate(-90 35 338)">CONTRACT</text>
    </g>

    <g stroke-width="1.6" fill="none">
      <rect x="58" y="78" width="798" height="40" rx="7" fill="#7f7f7f" fill-opacity="0.06" stroke="#7f7f7f" stroke-opacity="0.5"/>
      <rect x="58" y="126" width="798" height="40" rx="7" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.6"/>
      <rect x="58" y="174" width="798" height="40" rx="7" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f" stroke-opacity="0.6"/>
      <rect x="58" y="222" width="798" height="40" rx="7" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-opacity="0.6"/>
      <rect x="58" y="270" width="798" height="40" rx="7" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f" stroke-opacity="0.6"/>
      <rect x="58" y="318" width="798" height="40" rx="7" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-opacity="0.6"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.22">
      <path d="M258 82 L 258 354"/><path d="M368 82 L 368 354"/><path d="M570 82 L 570 354"/><path d="M716 82 L 716 354"/>
    </g>

    <g fill="currentColor">
      <text x="66" y="95" font-size="10" font-weight="700">0 · nothing yet</text>
      <text x="66" y="110" font-size="8.5" opacity="0.8">the state you start in</text>
      <text x="264" y="102" font-size="10">v1</text>
      <text x="374" y="102" font-size="9.5">orders(ship_to)</text>
      <text x="576" y="102" font-size="9.5">ship_to</text>
      <text x="722" y="102" font-size="9.5">ship_to</text>

      <text x="66" y="143" font-size="10" font-weight="700" fill="#0fa07f">1 · EXPAND — migration first</text>
      <text x="66" y="158" font-size="8.5" opacity="0.85">ADD COLUMN nullable, then deploy</text>
      <text x="264" y="150" font-size="10">v1 + v1d</text>
      <text x="374" y="145" font-size="9.5">ship_to</text>
      <text x="374" y="158" font-size="9.5" fill="#0fa07f">+ shipping_address (all NULL)</text>
      <text x="576" y="145" font-size="9.5">ship_to</text>
      <text x="576" y="158" font-size="9.5" fill="#0fa07f">+ shipping_address (v1d)</text>
      <text x="722" y="150" font-size="9.5">ship_to</text>

      <text x="66" y="191" font-size="10" font-weight="700" fill="#0fa07f">2 · BACKFILL — no deploy</text>
      <text x="66" y="206" font-size="8.5" opacity="0.85">574 rows, 7 bounded batches</text>
      <text x="264" y="198" font-size="10">v1d</text>
      <text x="374" y="192" font-size="9.5">both columns, both populated</text>
      <text x="374" y="205" font-size="8.5" opacity="0.8">new rows already dual-written</text>
      <text x="576" y="198" font-size="9.5">both</text>
      <text x="722" y="198" font-size="9.5">ship_to</text>

      <text x="66" y="239" font-size="10" font-weight="700" fill="#e0930f">3 · MIGRATE readers</text>
      <text x="66" y="254" font-size="8.5" opacity="0.85">deploy code that reads the new one</text>
      <text x="264" y="246" font-size="10">v1d + v2r</text>
      <text x="374" y="246" font-size="9.5">both columns, both populated</text>
      <text x="576" y="246" font-size="9.5">both</text>
      <text x="722" y="240" font-size="9.5">ship_to (v1d)</text>
      <text x="722" y="253" font-size="9.5" fill="#0fa07f">shipping_address (v2r)</text>

      <text x="66" y="287" font-size="10" font-weight="700" fill="#e0930f">4 · drop the dual write</text>
      <text x="66" y="302" font-size="8.5" opacity="0.85">separate deploy — soak here</text>
      <text x="264" y="294" font-size="10">v2r + v2</text>
      <text x="374" y="288" font-size="9.5">both columns</text>
      <text x="374" y="301" font-size="8.5" opacity="0.8">ship_to now stops changing</text>
      <text x="576" y="294" font-size="9.5">shipping_address</text>
      <text x="722" y="294" font-size="9.5">shipping_address</text>

      <text x="66" y="335" font-size="10" font-weight="700" fill="#d64545">5 · CONTRACT — deploy first</text>
      <text x="66" y="350" font-size="8.5" opacity="0.85">DROP COLUMN, only after the soak</text>
      <text x="264" y="342" font-size="10">v2</text>
      <text x="374" y="342" font-size="9.5">orders(shipping_address)</text>
      <text x="576" y="342" font-size="9.5">shipping_address</text>
      <text x="722" y="342" font-size="9.5">shipping_address</text>
    </g>

    <rect x="20" y="372" width="836" height="72" rx="9" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/>
    <g fill="currentColor">
      <text x="36" y="392" font-size="11" font-weight="700" fill="#0fa07f">Same rename. Same 1,700 requests through a fleet that is MIXED at every step: 0 errors, 0 bad reads, 0 corrupt rows.</text>
      <text x="36" y="411" font-size="9.5" opacity="0.95">Every row above is compatible with the row before it AND the row after it — that is what makes each step separately deployable,</text>
      <text x="36" y="425" font-size="9.5" opacity="0.95">and what makes a stalled rollout or a rollback a non-event. Expand runs BEFORE its code deploy; contract runs AFTER its code deploy.</text>
      <text x="36" y="439" font-size="9.5" opacity="0.95">Do all five in one deploy and you have written diagram 1 again.</text>
    </g>

    <text x="440" y="470" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Only step 5 destroys anything. It is the only step you cannot undo — which is why it goes last, alone, after a real soak.</text>
  </g>
</svg>
```

Notice what the fleet column says. It is **mixed at every single step** — `v1 + v1d`, `v1d + v2r`, `v2r + v2` — and it does not matter, because each pair of adjacent versions agrees about the schema in front of them. That is the entire trick. You are not avoiding the overlap window; you are making it harmless, five times in a row.

### The recipe table

Most schema changes reduce to eight operations. Here is what each one actually costs, and the safe staging for it. "Rewrite" means the database physically rewrites every row and holds an exclusive lock while it does.

| Change | Naive form | Cost | Safe staging |
|---|---|---|---|
| **Add a nullable column** | `ADD COLUMN x text` | Metadata-only. Cheap. | Ship it. Still take a `lock_timeout` — it needs `ACCESS EXCLUSIVE` for an instant. |
| **Add a `NOT NULL` column** | `ADD COLUMN x text NOT NULL DEFAULT 'a'` | On PostgreSQL ≥ 11 with a **non-volatile** default: metadata-only. With a volatile default (`gen_random_uuid()`, `now()` per row): full rewrite. On older engines: always a rewrite. | Add nullable → backfill in batches → `ADD CONSTRAINT ... NOT NULL NOT VALID` → `VALIDATE CONSTRAINT` (which takes only a `SHARE UPDATE EXCLUSIVE` lock and does not block reads or writes). |
| **Rename a column** | `RENAME COLUMN a TO b` | Free — and it is the most dangerous free operation there is. It is an atomic break for every deployed version that names the old column. | Never rename. Add `b`, dual-write, backfill, move readers, stop writing `a`, drop `a`. Five steps. |
| **Change a type** | `ALTER COLUMN x TYPE bigint` | Usually a full table rewrite plus every index on the column. Some widenings are metadata-only (`varchar(50)` → `varchar(100)`, `varchar` → `text`); most are not. | Add a new column of the new type, dual-write, backfill in batches, switch readers, drop the old. Identical to a rename. |
| **Drop a column** | `DROP COLUMN x` | Metadata-only in PostgreSQL (the data is only reclaimed by later rewrites) — so it is fast, and that is a trap. It is fast *and* irreversible. | Deploy code that stops referencing it → soak for at least one full deploy cycle → drop. Treat it as data deletion, because it is. |
| **Add an index** | `CREATE INDEX` | Takes a `SHARE` lock: **blocks all writes** for the whole build. Minutes to hours on a large table. | `CREATE INDEX CONCURRENTLY`. Two table scans, slower overall, no write blocking. Can fail and leave an **invalid** index that must be dropped and retried. |
| **Add a foreign key** | `ADD CONSTRAINT ... FOREIGN KEY` | Takes `SHARE ROW EXCLUSIVE` on *both* tables and scans the child to validate. | `ADD CONSTRAINT ... NOT VALID` (instant, enforced for new rows only), then `VALIDATE CONSTRAINT` in a separate transaction under a weaker lock. |
| **Split one table into two** | `CREATE TABLE`, copy, `DROP` columns | The multi-step change disguised as one. | Create the new table → dual-write to both → backfill → move readers → soak → stop writing the old → drop. The same five steps at table granularity. |

Two entries deserve emphasis. **Rename is free and catastrophic** — the cheapest operation in the table is the one that breaks the most code, which is exactly why it is the default mistake. And **drop is fast and unrecoverable** — speed is not safety, and the two get conflated constantly because the only feedback the database gives you is how long the statement took.

### Locks, precisely — and the queue nobody knows about

In PostgreSQL, most `ALTER TABLE` forms take an **`ACCESS EXCLUSIVE`** lock, which is the strongest table-level lock there is. It conflicts with *every* other lock mode, including `ACCESS SHARE`, which is what a plain `SELECT` takes (PostgreSQL 16 manual, §13.3 "Explicit Locking"). So while a DDL (Data Definition Language) statement holds that lock, nothing can read the table.

That is the part people know, and on its own it is not very frightening: `ADD COLUMN` holds `ACCESS EXCLUSIVE` for microseconds. Here is the part that is frightening.

> **A lock request is granted only if it conflicts with nothing currently HELD *and* nothing already WAITING ahead of it in the queue.**

Read it again with the incident from The Problem in mind. A six-minute reporting `SELECT` holds `ACCESS SHARE`. Your one-millisecond `ALTER` asks for `ACCESS EXCLUSIVE`, conflicts, and joins the queue. Now the next ordinary `SELECT` arrives. It needs `ACCESS SHARE`, which does not conflict with the report's `ACCESS SHARE` at all — it could run immediately, all day, no problem. But it *does* conflict with the queued `ALTER`, and the `ALTER` is ahead of it. So it waits. And so does the next one, and the next.

**Your table is now unreadable, and the statement causing it is holding no locks whatsoever. It is merely waiting.** This is the single most important mechanism in this lesson, because it explains the class of incident where a migration that "should have been instant" took a service down, and the post-mortem blames table size.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 508" width="100%" style="max-width:840px" role="img" aria-label="Two runs of the same ALTER TABLE against a table already held by a three second analytics SELECT. On the left, a bare ALTER waits 2501 milliseconds for one millisecond of work, and because PostgreSQL grants a lock only if it conflicts with nothing held and nothing already waiting ahead of it, 42 ordinary SELECTs queue behind the waiting DDL, the worst waiting 2461 milliseconds, for 51.7 query-seconds of stalled traffic. On the right, the same ALTER with lock_timeout set to 50 milliseconds gives up four times and succeeds on the fifth attempt at t equals 4.27 seconds; only 4 SELECTs are blocked, the worst for 36 milliseconds, totalling 0.08 query-seconds.">
  <defs>
    <marker id="l13-a3" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="24" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The lock queue: a DDL that is WAITING blocks everything behind it</text>
  <text x="440" y="42" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="10" fill="currentColor" opacity="0.85">A lock is granted only if it conflicts with nothing HELD and nothing already WAITING ahead of it.</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="54" width="416" height="290" rx="12" fill="#d64545" fill-opacity="0.08" stroke="#d64545"/>
      <rect x="448" y="54" width="416" height="290" rx="12" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>
    <text x="224" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">RUN A — bare ALTER TABLE, no lock_timeout</text>
    <text x="656" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">RUN B — SET lock_timeout = '50ms', then retry</text>

    <g fill="currentColor" font-size="8.5" opacity="0.7">
      <text x="28" y="102">ANALYTICS</text><text x="28" y="113">SELECT, 3.0s</text>
      <text x="28" y="150">ALTER TABLE</text><text x="28" y="161">1 ms of work</text>
      <text x="28" y="204">ORDINARY</text><text x="28" y="215">SELECTs, 5 ms</text>
      <text x="460" y="102">ANALYTICS</text><text x="460" y="113">SELECT, 3.0s</text>
      <text x="460" y="150">ALTER TABLE</text><text x="460" y="161">1 ms of work</text>
      <text x="460" y="204">ORDINARY</text><text x="460" y="215">SELECTs, 5 ms</text>
    </g>

    <g stroke-width="1.6">
      <rect x="118" y="92" width="204" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.22" stroke="#7f7f7f"/>
      <rect x="550" y="92" width="204" height="20" rx="4" fill="#7f7f7f" fill-opacity="0.22" stroke="#7f7f7f"/>
    </g>
    <g fill="currentColor" font-size="9" text-anchor="middle">
      <text x="220" y="106">ACCESS SHARE held, t=0 to 3.000</text>
      <text x="652" y="106">ACCESS SHARE held, t=0 to 3.000</text>
    </g>

    <rect x="152" y="138" width="170" height="20" rx="4" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="1.6" stroke-dasharray="6 3"/>
    <rect x="322" y="138" width="5" height="20" rx="1.5" fill="#d64545" stroke="#d64545" stroke-width="1.4"/>
    <g fill="currentColor">
      <text x="237" y="152" font-size="9" text-anchor="middle">WAITING for ACCESS EXCLUSIVE</text>
      <text x="134" y="176" font-size="9" fill="#d64545" font-weight="700">2,501 ms of waiting. Its own work: 1 ms.</text>
    </g>

    <g stroke-width="1.6">
      <rect x="584" y="138" width="5" height="20" rx="1.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="604" y="138" width="5" height="20" rx="1.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="643" y="138" width="5" height="20" rx="1.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="713" y="138" width="5" height="20" rx="1.5" fill="#e0930f" fill-opacity="0.55" stroke="#e0930f"/>
      <rect x="838" y="138" width="6" height="20" rx="1.5" fill="#0fa07f" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" font-size="9">
      <text x="584" y="132" fill="#e0930f" font-weight="700">4 attempts aborted, 50 ms each</text>
      <text x="844" y="132" fill="#0fa07f" font-weight="700" text-anchor="end">attempt 5 wins</text>
      <text x="560" y="176" font-size="9" fill="#0fa07f" font-weight="700">bounded waits + jittered backoff — it runs at t=4.266</text>
    </g>

    <g stroke-width="1.6">
      <rect x="118" y="186" width="34" height="22" rx="4" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
      <rect x="155" y="186" width="167" height="22" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
      <rect x="325" y="186" width="98" height="22" rx="4" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
      <rect x="550" y="186" width="304" height="22" rx="4" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle">
      <text x="135" y="201" font-size="7.5">8 ok</text>
      <text x="238" y="201" font-size="9.5" font-weight="700" fill="#d64545">42 STALLED</text>
      <text x="374" y="201" font-size="8" >queue drains</text>
      <text x="702" y="201" font-size="9.5" fill="#0fa07f" font-weight="700">only 4 ever wait, never longer than 36 ms</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.6">
      <path d="M118 226 L 424 226" marker-end="url(#l13-a3)"/>
      <path d="M550 226 L 856 226" marker-end="url(#l13-a3)"/>
      <path d="M118 222 L 118 230"/><path d="M186 222 L 186 230"/><path d="M254 222 L 254 230"/><path d="M322 222 L 322 230"/><path d="M390 222 L 390 230"/>
      <path d="M550 222 L 550 230"/><path d="M618 222 L 618 230"/><path d="M686 222 L 686 230"/><path d="M754 222 L 754 230"/><path d="M822 222 L 822 230"/>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.75" text-anchor="middle">
      <text x="118" y="242">0s</text><text x="186" y="242">1s</text><text x="254" y="242">2s</text><text x="322" y="242">3s</text><text x="390" y="242">4s</text>
      <text x="550" y="242">0s</text><text x="618" y="242">1s</text><text x="686" y="242">2s</text><text x="754" y="242">3s</text><text x="822" y="242">4s</text>
    </g>

    <g fill="currentColor">
      <text x="30" y="272" font-size="10.5" font-weight="700" fill="#d64545">innocent queries blocked: 42</text>
      <text x="30" y="292" font-size="9.5" opacity="0.9">worst wait 2,461 ms · 51.7 query-seconds stalled</text>
      <text x="30" y="308" font-size="9.5" opacity="0.9">None of the 42 conflicted with the analytics query.</text>
      <text x="30" y="324" font-size="9.5" opacity="0.9">They conflicted with an ALTER that held nothing.</text>
      <text x="462" y="272" font-size="10.5" font-weight="700" fill="#0fa07f">innocent queries blocked: 4  — 10x fewer</text>
      <text x="462" y="292" font-size="9.5" opacity="0.9">worst wait 36 ms · 0.08 query-seconds stalled</text>
      <text x="462" y="308" font-size="9.5" opacity="0.9">The DDL landed 1.27 s later than in run A.</text>
      <text x="462" y="324" font-size="9.5" opacity="0.9">Each abort drains the queue and lets traffic past.</text>
    </g>

    <rect x="16" y="360" width="848" height="98" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
    <text x="32" y="380" font-size="11" font-weight="700" fill="currentColor">Why the 42 queue at all — the rule almost nobody knows</text>
    <g fill="currentColor" font-size="9.5">
      <text x="32" y="400">ACCESS SHARE (every SELECT) does not conflict with ACCESS SHARE. Those 42 queries could have run beside the analytics</text>
      <text x="32" y="416">query all day. They conflict with the ALTER — and the ALTER is not holding anything. It is WAITING. A request is granted</text>
      <text x="32" y="432">only if it conflicts with nothing held AND nothing queued ahead of it: one blocked DDL turns a slow query into a table outage.</text>
      <text x="32" y="450" font-weight="700" fill="#0fa07f">lock_timeout bounds how long your DDL may be that obstacle. It is the highest-value line in a migration.</text>
    </g>

    <text x="440" y="488" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The trade is elapsed time for blast radius: 1.27 s later, and 0.08 query-seconds of stalled traffic instead of 51.7.</text>
  </g>
</svg>
```

The mitigation is two settings and a loop. **`lock_timeout`** bounds how long a statement will wait *to acquire* a lock before aborting — as distinct from `statement_timeout`, which bounds how long it runs once it has one. Set it low (50 ms to a few seconds), catch the failure, back off with jitter, and try again. Every abort instantly drains the queue that had formed behind you. In the measured run, five attempts at 50 ms cost the table **0.08 query-seconds of stalled traffic instead of 51.7**, and the migration landed 1.27 seconds later than it otherwise would have. That is the entire trade, and it is not close.

### Cheap, or a rewrite?

The distinction that decides whether a migration is a non-event or an outage is whether the engine can change *metadata only* or must physically rewrite every row.

- **`ADD COLUMN` with a non-volatile default is metadata-only** on PostgreSQL 11 and later. The default is recorded in the catalog and materialised lazily as rows are updated. Before 11, the same statement rewrote the entire table — which is why "add a column with a default" is remembered as dangerous by anyone who operated PostgreSQL 10, and is fine today. Know your version; the answer changed underneath the folklore.
- **A volatile default rewrites.** `DEFAULT gen_random_uuid()` or `DEFAULT clock_timestamp()` must produce a different value per row, so there is nothing to record in the catalog and every row must be touched.
- **A type change generally rewrites**, and rebuilds every index on that column. `int` → `bigint` on a large table is a rewrite. A `varchar` length *increase* and `varchar` → `text` are metadata-only, because the stored representation is unchanged.
- **`CREATE INDEX` blocks writes; `CREATE INDEX CONCURRENTLY` does not.** The concurrent build takes a weaker lock and does two passes over the table, so it is slower in wall time and it can *fail* — leaving behind an index marked `INVALID` that is not used by the planner and must be dropped before you retry. Check for it; a forgotten invalid index is a query plan regression waiting for the next deploy to be blamed for it.
- **`DROP COLUMN` is metadata-only** in PostgreSQL. The bytes stay in the pages until a later rewrite reclaims them, which is why the statement returns instantly — and why its speed tells you nothing about its safety.

### Backfills: bounded batches, never one transaction

A backfill is not DDL, it is DML (Data Manipulation Language) — an `UPDATE` over a lot of rows — and it fails in a completely different way. One `UPDATE` touching ten million rows:

- Holds row locks on everything it has touched, for the whole duration. Any concurrent write to those rows blocks.
- Holds a **transaction snapshot** open for the whole duration. Under MVCC (Multi-Version Concurrency Control, built in Phase 3's [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/)), an `UPDATE` writes a new version of each row and leaves the old one behind. A long-running transaction pins the oldest snapshot the system must preserve, so **vacuum cannot reclaim any dead row version anywhere in the database** while it runs. The table bloats, the indexes bloat, and the bloat outlives the migration.
- Writes the entire change to the write-ahead log ([Durability: Write-Ahead Logging](../../03-relational-databases/13-write-ahead-logging/)) as one unit, which floods replication and can push replicas into lag measured in minutes.
- Cannot be interrupted without losing all of it. Kill it at 90% and you have done nothing.

Batching fixes all four. Take a bounded window of rows by primary key, commit, pause briefly, repeat — **keyset pagination, not `OFFSET`**, because `OFFSET n` re-scans the n rows it is skipping and turns a linear backfill into a quadratic one. The measured cost of batching is that it is *slower overall*, and that is exactly the trade you want: in the Build It, one million rows took **2.43 s in a single transaction and 4.28 s in 50 batches (+76%)**, while the longest single lock hold fell from **2,427 ms to 114 ms — 21× shorter**. A concurrent reader completed **1 query during the single transaction and 165 during the batched run**, on identical traffic against the same table.

### Contracts are not only databases

Everything above generalises. **Any consumer you do not deploy atomically with the producer needs a compatibility window** — and you deploy nothing atomically with anything.

- **API responses.** Adding a field is safe if consumers ignore unknown fields; removing or renaming one is a rename. Making a previously optional request field required is a breaking change even though nothing in your schema "shrank". [API Versioning Strategies](../../02-api-design/05-api-versioning/) covers the versioning mechanics — URI versions, media-type negotiation, sunset headers — and they are the *how*; the *when* is the same rule as above.
- **Message and event schemas.** Worse than APIs, because messages are durable: a consumer may read an event written by a producer version that was retired months ago, and a replay from the beginning of the log will feed it every version you ever emitted. [Schema Evolution & Event Contracts](../../06-messaging-and-pub-sub/12-schema-evolution-and-event-contracts/) covers backward, forward and full compatibility and the registry that enforces them.
- **Caches and serialized blobs.** A `pickle`, a protobuf in Redis, a JSON column — every one is a schema with two versions of your code reading it.

The unifying statement is worth putting on a wall:

> **Deploy boundaries are compatibility boundaries. Anything that crosses one — a column, a JSON field, an event payload, a cache value — needs a window during which both shapes are valid.**

### Migration ordering vs deploy ordering

The two orderings are not the same, and getting them backwards is a common, avoidable outage:

- **Expand runs *before* the code deploy.** The new column must exist before any instance tries to write it. A migration that adds a column is safe to run against 100% old code, because old code does not know it exists.
- **Contract runs *after* the code deploy has fully rolled out and soaked.** The column must stop being referenced before it is removed — and "fully rolled out" includes the cron boxes, the batch workers and the one instance the autoscaler forgot.

Which gives a decision rule you can apply to any migration in review:

> **If a migration must run before its deploy and is not backward compatible with the currently running code, it is a migration that requires downtime. There is no clever ordering that fixes it — only splitting it into steps that are each backward compatible, or taking the outage deliberately.**

Say that plainly when it comes up. A planned two-minute maintenance window, announced, at 04:00, with the fleet drained, is a *far* better outcome than an unplanned one at 15:40 — and the option only exists if someone recognised the incompatibility in review rather than in production.

## Build It

[`code/zero_downtime_migrations.py`](code/zero_downtime_migrations.py) is five numbered arguments. Standard library only, seeded with `random.Random(7)`, ~11 seconds. SQLite is the stand-in engine for sections 1, 2, 3 and 5 — it gives a real table, real DDL and a real concurrent reader thread. **Section 4 is different, and this matters: it does not observe SQLite's locking, because SQLite's locking model is not PostgreSQL's. It implements PostgreSQL's lock-queue rule directly, in Python, and says so in its own output.** The real commands are in `Use It`.

**The fleet.** Four code versions differing only in which column they write and which key they read:

```python
V1  = Version("v1",  ("ship_to",),                     "ship_to",          "old code: ship_to only")
V1D = Version("v1d", ("ship_to", "shipping_address"),  "ship_to",          "dual-write, reads OLD")
V2R = Version("v2r", ("ship_to", "shipping_address"),  "shipping_address", "dual-write, reads NEW")
V2  = Version("v2",  ("shipping_address",),            "shipping_address", "new code: shipping_address only")
```

**The read path is the point of the whole exercise.** It is `SELECT *` followed by a dictionary lookup — which is what every ORM does — and that is precisely why a missing column produces `None` rather than an error:

```python
def read_order(conn, v, oid):
    """SELECT * then row[key] — the ORM read path. A dropped or renamed column
    is not an error here; it is a KeyError the framework turns into None."""
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (oid,)).fetchone()
    if row is None:
        return None, False
    d = {k: row[k] for k in row.keys()}
    return d.get(v.reads), True
```

The export job then **persists** whatever that read returned, which is how a transient window becomes permanent damage.

**The backfill** is keyset pagination with a commit per batch. Note that it never uses `OFFSET`, and that the loop condition is driven by the data rather than by a row count:

```python
def do_backfill() -> None:
    # Keyset pagination, not OFFSET: find the next unbackfilled id, take a
    # bounded window from there, commit, repeat. Never one big UPDATE.
    lo, batches, rows = 0, 0, 0
    while True:
        nxt = conn.execute(
            "SELECT min(id) FROM orders WHERE shipping_address IS NULL"
            " AND id > ?", (lo,)).fetchone()[0]
        if nxt is None:
            break
        cur = conn.execute(
            "UPDATE orders SET shipping_address = ship_to"
            " WHERE shipping_address IS NULL AND id >= ? AND id < ?",
            (nxt, nxt + 100))
        conn.commit()
        rows += cur.rowcount
        batches += 1
        lo = nxt + 99
```

**The lock manager** is the modelled part. Twelve lines, and the second `and` clause is the whole lesson:

```python
def grant_pass(self) -> None:
    ahead: List[str] = []
    keep: List[Req] = []
    for r in self.wait:
        ok = (not any(conflicts(r.mode, m) for _, m, _ in self.held)
              and not any(conflicts(r.mode, m) for m in ahead))   # <-- the cascade
        if ok:
            self.held.append((self.now + r.dur, r.mode, r.name))
            ...
        else:
            ahead.append(r.mode)
            keep.append(r)
    self.wait = keep
```

Delete `and not any(conflicts(r.mode, m) for m in ahead)` and the 42 blocked queries become 0 — every `SELECT` would sail past the waiting `ALTER`. That single clause is the difference between a slow migration and an outage, and it is why "the `ALTER` itself is instant" is not a safety argument.

Run it:

```bash
docker compose exec -T app python \
  phases/10-infrastructure-and-deployment/13-zero-downtime-schema-changes/code/zero_downtime_migrations.py
```

```console
== 1 · THE OVERLAP WINDOW: ONE RENAME, TWO VERSIONS, ONE DATABASE ==
  fleet: 6 instances behind one load balancer, one shared database
  the migration is the whole change, run at deploy time:
    ALTER TABLE orders RENAME COLUMN ship_to TO shipping_address;
  that DDL took a few microseconds. Now the rollout begins.

  rollout stage                  reqs      5xx  bad reads bad exports
  3 of 6 on v2 (t+0s)             700      164        102         69
  5 of 6 on v2 (t+40s)            500       38         23         21
  6 of 6 on v2 (t+90s)            500        0          0          0
  TOTAL                          1700      202        125         90

  the loud half : 202 requests raised OperationalError: table orders has no column named ship_to
                  every one of those was a lost order and a 500.
  the quiet half: 90 of 363 exported rows have a NULL address
                  90 exported rows disagree with what was actually stored.
                  No exception. No log line. No alert. The read path is
                  SELECT * then row['ship_to'] — after the rename that key
                  is simply absent, so the ORM hands the app None.

== 2 · THE SAME RENAME AS EXPAND / MIGRATE / CONTRACT ==
  five separately deployable steps. The fleet stays MIXED throughout.
  step action                         fleet                    reqs   5xx bad-rd bad-exp
  0    (nothing yet)                  v1                        200     0      0       0
  1    EXPAND: ADD COLUMN (nullable)  v1+v1d                    300     0      0       0
  2    BACKFILL in batches of 100     v1d                       300     0      0       0
  3    MIGRATE: deploy new readers    v1d+v2r                   300     0      0       0
  4    drop the dual write            v2+v2r                    300     0      0       0
  5    CONTRACT: DROP COLUMN ship_to  v2                        300     0      0       0
       TOTAL                                                   1700     0      0       0

  backfill: 574 legacy rows in 7 batches of 100
  final schema: orders(shipping_address)
  persisted corruption across all 371 exported rows: 0

== 3 · THE BACKFILL: ONE TRANSACTION VS BOUNDED BATCHES ==
  1000000 rows to backfill, one secondary index to maintain.
  A reader thread runs a small indexed SELECT every 2 ms throughout
  and records how long each one actually took.

  run                    total   txns   max lock   reads   read p50   read p99   read max  >100ms
  one transaction        2.43s      1     2427ms       1   2426.3ms   2426.3ms     2426ms       1
  batches of 20000       4.28s     50      114ms     165      0.1ms    109.4ms      114ms       3

  both backfilled 1000000 rows.
  total wall time: 2.43s -> 4.28s (+76%) — the batched run is slower.
  longest single lock hold: 2427 ms -> 114 ms (21x shorter).
  worst concurrent read:    2426 ms -> 114 ms; reads over 100 ms: 1 -> 3.

== 4 · THE LOCK QUEUE CASCADE (PostgreSQL semantics, MODELLED) ==
  Not observed from SQLite — SQLite has a different locking model.

  --- run A: a bare ALTER TABLE, no lock_timeout ---
  t= 0.500  ALTER TABLE        ACCESS EXCLUSIVE REQUESTED
  t= 3.000  analytics SELECT   ACCESS SHARE     RELEASED
  t= 3.000  ALTER TABLE        ACCESS EXCLUSIVE GRANTED after  2500 ms wait
  t= 3.001  ALTER TABLE        ACCESS EXCLUSIVE RELEASED
  t= 3.001  SELECT #9          ACCESS SHARE     GRANTED after  2461 ms wait
  ...
  ALTER TABLE finally ran at t=3.001 — it waited 2501 ms for 1 ms of work.
  innocent SELECTs blocked behind the WAITING DDL: 42
     worst wait 2461 ms; 51.7 query-seconds of stalled traffic in total.

  --- run B: SET lock_timeout = '50ms', retry with jittered backoff ---
  the DDL gave up 4 times and succeeded on attempt 5 at t=4.266.
  innocent SELECTs blocked: 4 (was 42) — a 10x reduction.
     worst wait 36 ms (was 2461 ms); 0.08 query-seconds stalled (was 51.7).

== 5 · ROLLBACK COMPATIBILITY: WHICH STEPS CAN YOU UNDO? ==
       schema state                   v1        v1d       v2r       v2
  S0   before expand                  OK        FAIL      FAIL      FAIL
  S1   after EXPAND, not backfilled   OK        OK        SILENT    SILENT
  S2   after BACKFILL                 OK        OK        OK        OK
  S3   after CONTRACT                 FAIL      FAIL      FAIL      OK

  reachable rollback set, per step:
    before expand          -> v1                       (1 of 4 versions)
    after EXPAND           -> v1, v1d                  (2 of 4 versions)
    after BACKFILL         -> v1, v1d, v2r, v2         (4 of 4 versions)
    after CONTRACT         -> v2                       (1 of 4 versions)

  (total wall time 10.7 s)
```

**Section 1 is the failure, and the two halves of it fail differently.** 202 of 1,700 requests raised `OperationalError: table orders has no column named ship_to` — visible, alertable, and self-healing once the rollout completes. Then the number to remember: **90 exported rows persisted a `NULL` address**, out of 363 rows the export job wrote. A quarter of the nightly export is wrong. Nothing raised, nothing logged, and the window that produced it closed at t+90s, long before anybody could correlate the two. Note the stage-by-stage decay — 164 errors, then 38, then 0 — which is the shape that makes this so easy to dismiss: the graph is already recovering by the time anyone opens it.

**Section 2 is the same rename, done properly, and the headline is that nothing happened.** Identical 1,700 requests, identical mixed fleet at every step, and **0 errors, 0 bad reads, 0 corrupt rows across all 371 exported rows.** The backfill moved **574 legacy rows in 7 batches of 100**. The final schema is exactly the one section 1 arrived at. Same destination, five deploys instead of one, and zero damage instead of 202 errors, 125 wrong answers and 90 permanent artifacts.

**Section 3 quantifies the batching trade, and the honest reading is that batching is worse on the metric people optimise.** One million rows: the single transaction finished in **2.43 s**, the 50-batch version in **4.28 s — 76% slower**. If wall-clock migration time is your metric, batching loses. Now look at the metric that matters to everyone *else* using the database. The longest single lock hold went from **2,427 ms to 114 ms, 21× shorter**. A reader thread issuing one small indexed `SELECT` every 2 ms completed **exactly 1 query during the 2.43-second single transaction** — it was blocked for essentially the entire run, its one query taking 2,426 ms — versus **165 queries in the batched run, p50 0.1 ms, p99 109.4 ms.** Same traffic, same table, same total work. You paid **1.85 seconds** of your own wall time to take **2,426 ms off the worst thing that happened to anybody else.**

**Section 4 is the modelled one.** The scenario is minimal: an analytics `SELECT` holds `ACCESS SHARE` for 3 seconds; at t=0.5 an `ALTER TABLE` whose own work takes **1 millisecond** requests `ACCESS EXCLUSIVE`; ordinary `SELECT`s arrive every 60 ms. Run A: the `ALTER` waits **2,501 ms**, and **42 ordinary queries that had no conflict with the analytics query at all** stall behind it — worst wait **2,461 ms**, **51.7 query-seconds** of stalled traffic in aggregate. Run B changes nothing but adding `lock_timeout = '50ms'` and a jittered retry: the DDL is aborted **4 times**, wins on attempt 5 at t=4.266, and blocks **4 queries for at most 36 ms — 0.08 query-seconds total.** The migration landed 1.27 seconds later. That is the whole price.

**Section 5 is the setup for the next lesson.** Every code version is run against every schema state, and the interesting cell is not `FAIL` — it is `SILENT`. In state S1 (expanded but *not yet backfilled*), `v2r` and `v2` do not crash; they return the wrong answer, which is section 1's silent corruption arriving by a different route. And read the rollback sets: after `EXPAND` you can roll back to **2 of 4 versions**; after `BACKFILL` to **all 4** — the safest moment in the entire sequence, and the right place to pause. After `CONTRACT`, **1 of 4**, and the three you lost do not degrade, they raise on every request. **The `DROP` is the moment you give up your ability to roll back.**

## Use It

Everything above is standard PostgreSQL. The safe recipes, in real DDL:

```sql
-- SAFE: nullable add. Metadata-only.
ALTER TABLE orders ADD COLUMN shipping_address text;

-- SAFE on PostgreSQL >= 11: non-volatile default, recorded in the catalog.
ALTER TABLE orders ADD COLUMN currency text NOT NULL DEFAULT 'USD';

-- DANGEROUS: volatile default forces a full table rewrite under ACCESS EXCLUSIVE.
ALTER TABLE orders ADD COLUMN uid uuid NOT NULL DEFAULT gen_random_uuid();

-- NOT NULL in three safe steps instead of one rewriting step:
ALTER TABLE orders ADD COLUMN region text;                       -- 1. nullable
--    ... backfill in batches (below) ...
ALTER TABLE orders ADD CONSTRAINT orders_region_nn               -- 2. instant
      CHECK (region IS NOT NULL) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT orders_region_nn;         -- 3. SHARE UPDATE
                                                                 --    EXCLUSIVE: reads
                                                                 --    and writes continue

-- Foreign keys, same shape:
ALTER TABLE orders ADD CONSTRAINT orders_customer_fk
      FOREIGN KEY (customer_id) REFERENCES customers(id) NOT VALID;
ALTER TABLE orders VALIDATE CONSTRAINT orders_customer_fk;
```

Indexes are the other everyday case. `CREATE INDEX` takes a `SHARE` lock and blocks every write to the table for the entire build; `CONCURRENTLY` does not, at the cost of two passes and the possibility of failure:

```sql
CREATE INDEX CONCURRENTLY ix_orders_shipping ON orders (shipping_address);

-- It can fail (a deadlock, a cancelled session, a unique violation) and leave
-- an INVALID index behind: not used by the planner, still maintained on write.
SELECT c.relname
  FROM pg_class c JOIN pg_index i ON i.indexrelid = c.oid
 WHERE i.indisvalid = false;

DROP INDEX CONCURRENTLY ix_orders_shipping;   -- then retry the build
```

`CREATE INDEX CONCURRENTLY` cannot run inside a transaction block, which means most migration frameworks need to be told to disable their automatic transaction wrapper for that one revision.

**The bounded wait.** This is the pattern to put in every migration you write, and it is the one thing from this lesson worth adopting today:

```sql
SET lock_timeout = '2s';        -- how long we wait FOR a lock before aborting
SET statement_timeout = '30s';  -- how long we run once we HAVE it
ALTER TABLE orders ADD COLUMN shipping_address text;
```

With a retry loop around it, in the migration's own language:

```python
import random, time
import psycopg  # Use It half only — the Build It above is stdlib

def ddl_with_bounded_wait(conn, sql, attempts=10, lock_timeout="2s"):
    """Never let a DDL statement become the head of a lock queue for long."""
    for attempt in range(1, attempts + 1):
        try:
            with conn.transaction():
                conn.execute(f"SET LOCAL lock_timeout = '{lock_timeout}'")
                conn.execute(sql)
            return
        except psycopg.errors.LockNotAvailable:
            if attempt == attempts:
                raise
            backoff = min(2 ** attempt, 60) * (0.5 + random.random())
            time.sleep(backoff)          # jitter: many migrations may be retrying
```

**Finding the blocker during an incident.** When a table has gone quiet and you suspect a lock queue, this is the query. The blocked statement is rarely the culprit — look for the oldest entry, which is usually an idle-in-transaction session or a long analytics query:

```sql
SELECT a.pid,
       a.state,
       now() - a.xact_start        AS txn_age,
       now() - a.query_start       AS query_age,
       a.wait_event_type,
       l.mode,
       l.granted,
       left(a.query, 80)           AS query
  FROM pg_stat_activity a
  JOIN pg_locks l ON l.pid = a.pid
 WHERE l.relation = 'orders'::regclass
 ORDER BY a.xact_start;

-- who is blocking whom, directly:
SELECT pid, pg_blocking_pids(pid), left(query, 60)
  FROM pg_stat_activity
 WHERE cardinality(pg_blocking_pids(pid)) > 0;

SELECT pg_cancel_backend(12345);      -- cancel the query (polite)
SELECT pg_terminate_backend(12345);   -- kill the session (last resort)
```

Cancel the *blocker*, not your migration, if the blocker is a report someone can re-run. Cancel your migration if the blocker is a transaction holding real user work.

**Batched backfills** in a migration framework. The shape is identical in every language — bounded window by primary key, commit per batch, sleep between:

```sql
-- one batch; loop this in the migration script, not in SQL
UPDATE orders
   SET shipping_address = ship_to
 WHERE id > :last_id
   AND id <= :last_id + 5000
   AND shipping_address IS NULL;
```

**Alembic** (SQLAlchemy) and **Django migrations** both express expand/contract as *separate revisions* — the whole point being that they are deployed at different times, not merged for tidiness:

```python
# alembic/versions/0007_expand_add_shipping_address.py   — deploy N, runs BEFORE code
def upgrade():
    op.add_column("orders", sa.Column("shipping_address", sa.Text(), nullable=True))

def downgrade():
    op.drop_column("orders", "shipping_address")

# alembic/versions/0008_backfill_shipping_address.py     — deploy N, data only
def upgrade():
    conn, last = op.get_bind(), 0
    while True:
        res = conn.execute(sa.text(
            "UPDATE orders SET shipping_address = ship_to "
            "WHERE id > :lo AND id <= :lo + 5000 AND shipping_address IS NULL"
        ), {"lo": last})
        last += 5000
        if res.rowcount == 0 and last > max_id(conn):
            break

# alembic/versions/0011_contract_drop_ship_to.py         — deploy N+2, runs AFTER code
def upgrade():
    op.drop_column("orders", "ship_to")   # irreversible: downgrade cannot restore data
```

```python
# Django: the concurrent index needs its own atomic=False migration
class Migration(migrations.Migration):
    atomic = False                                    # CONCURRENTLY forbids a txn
    operations = [migrations.AddIndexConcurrently(
        model_name="order",
        index=models.Index(fields=["shipping_address"], name="ix_orders_shipping"),
    )]
```

**When the change genuinely requires a rewrite**, online schema-change tools do expand/contract for you at the storage layer. `gh-ost` and `pt-online-schema-change` (both MySQL) build a **shadow table** with the new schema, copy rows into it in bounded chunks, capture concurrent changes — `pt-online-schema-change` with triggers, `gh-ost` by tailing the binary log, which avoids adding trigger overhead to your live writes — and finish with an atomic rename. PostgreSQL's equivalent is `pg_repack`. They all pay the same price: double the disk, a long copy, and a brief lock at cutover. They change the *cost* of a rewrite; they do not remove the need for the application-level compatibility window, because your code still has to work against both shapes while the tool runs.

**Deploy order, as a table you can hand to a reviewer:**

| Change | Migration runs | Code deploy | Gap between them |
|---|---|---|---|
| Add a column, add an index | **Before** the deploy | Uses it after | Minutes is fine |
| Backfill | **Between** deploys, after dual-write ships | — | As long as it takes |
| Switch readers to the new shape | — | **After** the backfill completes | Verify completion, don't assume |
| Stop writing the old shape | — | Its own deploy | Soak: at least one full deploy cycle |
| Drop a column / table / constraint | **After** the deploy has soaked | Already shipped | Days, not minutes |

Rules that survive contact with an incident:

- **Never run a bare DDL statement at peak.** Always `SET lock_timeout`, always with a retry loop. The measured cost of not doing it was 42 blocked queries and 51.7 query-seconds from a statement whose own work took 1 ms.
- **Expand and contract go in separate deploys, with a real soak between them.** Not the same pull request, not the same release. If your process cannot express "these two migrations are deployed a week apart", fix the process before the next rename.
- **Backfill in bounded batches with a pause, and use keyset pagination.** Batching cost 76% more wall time and cut the worst lock hold by 21×. `OFFSET` on a large table turns a linear job into a quadratic one.
- **Dual-write for the entire window, and verify before you switch readers.** Run a reconciliation query that counts rows where the two shapes disagree, and require zero before deploying the readers. If you cannot write that query, you do not know the backfill finished.
- **Treat every `DROP` as forfeiting your ability to roll back.** Measured in section 5: before the drop, 4 of 4 code versions work against the schema; after it, 1 of 4, and the other three raise on every request. Add the old column back and the *data* is still gone.
- **Take the same discipline to every contract you publish.** API fields, event payloads, cached blobs. Ask one question in review: which consumer do I deploy atomically with this producer? The answer is always "none".
- **When there is no compatible staging, say so and schedule the window.** A deliberate two-minute outage at 04:00 beats an accidental four-minute one at 15:40, and the difference is entirely whether somebody named it in review.

## Think about it

1. Your rollout is configured `maxSurge: 1, maxUnavailable: 0` over 40 instances, and one instance is stuck `Pending` because the cluster is out of capacity. The migration for this release was an `ADD COLUMN`, so you are confident it is safe. Which of expand/migrate/contract are you now safe to proceed with, and which one becomes indefinitely blocked? What monitoring would tell you that you are sitting in an overlap window rather than a completed rollout?
2. Section 5 shows `v2r` reading correctly at state S2 but returning `SILENT` at S1 — no error, wrong answer. You cannot pause a rollout mid-flight to wait for a backfill. Design the check that gates the reader deploy on backfill completeness, and say what it must count. What does your answer imply about rows created *during* the backfill, and does the dual-write make that easier or harder?
3. The batched backfill took 76% longer in wall time and reduced the worst lock hold by 21×. Construct a case where you should take the single transaction instead, and state precisely what has to be true about the table, the traffic and the time of day. Then say what you would monitor to know your assumption was wrong while it was still running.
4. Your migration uses `lock_timeout = '2s'` with ten jittered retries and fails all ten because a reporting job holds a lock for an hour every night. Give three different fixes, one at the migration layer, one at the database layer, and one at the reporting job's layer, and rank them by which team has to be in the room.
5. You are asked to change `orders.total_cents` from `integer` to `bigint` on a table with 400 million rows and 6 indexes, on a database whose disk is 70% full. Walk the plan, including what you do about replicas and about the export job that nobody in your team owns. At which step is rollback still free, and what is the last moment you can change your mind?

## Key takeaways

- **A rolling deploy runs two versions of your code against one database, and the window is unbounded.** A naive `RENAME COLUMN` across a 6-instance rollout produced **202 errors, 125 bad reads and 90 corrupted exported rows out of 1,700 requests**; the same rename as five separately deployable expand/migrate/contract steps produced **0, 0 and 0** with the fleet mixed at every step. A canary, a stalled node or a rollback stretches that window from ninety seconds to indefinitely.
- **The silent half is the expensive half.** The 202 errors healed on their own when the rollout finished. The **90 exported rows with a `NULL` address — a quarter of the 363 rows the export job wrote —** are permanent, because `SELECT *` plus a dictionary lookup returns `None` for a missing column instead of raising. Alert on reconciliation mismatches, not just on 5xx.
- **A DDL statement that is merely *waiting* blocks the whole table.** A lock is granted only if it conflicts with nothing held **and nothing already queued ahead of it**, so a 1 ms `ALTER` stuck behind a 3-second analytics query stalled **42 innocent `SELECT`s for 51.7 query-seconds, worst wait 2,461 ms**. `SET lock_timeout` plus a jittered retry cut that to **4 queries and 0.08 query-seconds**, at a cost of 1.27 seconds of migration latency.
- **Batch every backfill; the extra wall time is the product you are buying.** One million rows took **2.43 s in one transaction vs 4.28 s in 50 batches (+76%)**, but the longest lock hold fell **2,427 ms → 114 ms (21×)** and a concurrent reader completed **165 queries instead of 1** on identical traffic. A single-transaction backfill also pins an MVCC snapshot, so vacuum stops reclaiming dead rows database-wide while it runs.
- **Migration order and deploy order are different.** Expand runs *before* its code deploy, contract *after* its code deploy has fully soaked. A migration that must run before its deploy and is not backward compatible with the running code is a migration that requires downtime — name it in review and schedule the window.
- **`DROP` is the step that forfeits rollback.** Measured across every code version against every schema state: **4 of 4 versions work after the backfill, 1 of 4 after the contract**, and the other three raise on every request rather than degrading. Everything before the drop is reversible; that one is not, which is why it ships alone, last, after a real soak.

Next: [Rollback, Backups & Disaster Recovery](../14-rollback-backups-and-disaster-recovery/) — this lesson showed which schema states you can still roll back to; that one covers what to do when the answer is none of them.
