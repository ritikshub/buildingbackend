# Integration Testing Against a Real Database

> Ten schema-and-query pairs, run against a real SQL engine and against PostgreSQL. **All ten returned different answers, and five of them raised no error in either engine** — the `SUM` over a money column is `10.305000000000001` here and exactly `10.31` there, `LIKE 'ADA%'` matches one row here and none there, and page 1 of your paginated list holds different rows. Then the isolation strategy that makes your suite **54× cheaper** turns out to do nothing at all for three tests in two hundred, and the suite stays green in file order **for ever** — shuffling finds it in **378 of 400 runs**. And of the six ways two transactions can interleave over one row, **four lose money**, while the two a normal test explores are exactly the two that pass.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Designing for Testability: Seams, Injection & the Untestable Function](../05-designing-for-testability/), [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/), [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/)
**Time:** ~80 minutes

## The Problem

The suite runs against SQLite. Somebody made that choice three years ago for an excellent reason: 1,412 tests finish in 38 seconds, on a laptop, on a plane, with no Docker daemon running. It has been green every day since. Production is PostgreSQL 16.

**Tuesday 09:12.** A `500` on `POST /orders`. The log line is one you have never seen from this service:

```text
psycopg.errors.InvalidTextRepresentation: invalid input syntax for type integer: "12 units"
```

A partner integration started sending `"12 units"` in a quantity field. There is a test for exactly this — `test_create_order_rejects_bad_quantity` — and it passes. It has always passed. It passes right now, on the same commit that is throwing 500s in production, because SQLite stored the string `'12 units'` in an `INTEGER` column without complaint, the row came back, and the assertion on the response body was satisfied.

**Tuesday 11:40.** Finance opens a ticket. The monthly revenue reconciliation is off, not by an amount anybody can see on a dashboard, but consistently: the ledger and the database disagree in the third decimal place, on about one row in three hundred. Nobody can reproduce it locally. Locally, the numbers match. Locally, `NUMERIC(10,2)` is a 64-bit float, and `10.005` stays `10.005`; in production it is an exact decimal and it became `10.01` the moment it was stored.

**Tuesday 14:07.** Support escalates a complaint that has been arriving for weeks and closing as user error. Customers type their email address in capitals on the login-help form and are told no account exists. There is a test. The test searches for `ADA@EXAMPLE.COM` and finds the row, because **SQLite's `LIKE` is case-insensitive for ASCII and PostgreSQL's is not.** The test asserts that the search works. In production, the search has never worked.

**Tuesday 16:30.** Somebody notices that the second page of the customer list has been repeating three names from page one since launch, and that the report generated at 09:00 lists them in a different order than the one on screen. `ORDER BY name` is not a total order across the two engines: SQLite sorts `Zoe` before `ada` because it compares bytes, and the production collation does not.

Three tickets, a fourth found by accident, three teams, four different-looking bugs, and one cause. Nobody wrote a bad test. Every one of these tests is well named, well structured, asserts on behaviour rather than on a mock, and was reviewed. They are all tests of a program that is not the one you deploy.

> **The test database is not the database, and a test that runs against a substitute is a test of a different program.**

**A note on this lesson's own code, because it would be dishonest not to make it first.** `code/integration_db.py` runs standalone with no Docker and no server, so the engine it drives is stdlib `sqlite3`. SQLite is standing in for PostgreSQL here, for teaching — which is *precisely* the substitution this lesson exists to argue against. That is a deliberate and slightly uncomfortable choice, and it is workable for one reason: everything the program measures about SQLite is measured by **executing it**, and the PostgreSQL column beside it is documented behaviour carrying its SQLSTATE code, never a guess. Section 1 is a live demonstration of exactly how far apart the two engines are, run on the substitute. The `Use It` half then shows the real setup — a PostgreSQL container, per suite, migrated forward — which is the thing you should actually build.

## The Concept

### What an integration test is actually for

A **unit test** ([Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/)) runs your code and asserts a fact about it, with everything outside the unit replaced. An **integration test** runs your code against the real thing on the other side of a boundary — here, a real SQL engine speaking a real wire protocol, with a real schema.

The common framing is that an integration test is a bigger, slower unit test: more setup, more code, more confidence. That framing is wrong in a way that matters, because it suggests the two are on a continuum and you can buy confidence by moving along it. They find **different bug classes**, and no quantity of one converts into the other.

A unit test can only check the rules your process knows about. An integration test checks the rules that live somewhere else: the constraint the schema declares, the type the column actually has, the ordering the collation actually produces, the isolation level the server actually runs, the migration that actually ran. Those rules are not in your source tree. You cannot unit-test them, because the object under test does not contain them.

That is also the sharpest test of whether a given test is worth its cost. Ask what would have to be true for it to fail. If the answer is "a bug in a function I can read", a unit test is cheaper and localises better. If the answer is "the database disagreed with what my code assumed about it", no amount of unit testing will ever produce it, and the only instrument that can is a connection to the real thing.

There is a second category, quieter and just as expensive: **wiring**. The query string that never gets executed because the branch above it returns early; the column name misspelled in a `SELECT` that only fails at runtime; the connection that is checked out and never returned ([Connection Pooling & N+1](../../03-relational-databases/14-connection-pooling-and-n-plus-1/)). Every one of these is invisible to a suite that never opens a socket, and every one is trivially visible to a suite that does.

Section 2 of the Build It puts a number on that. The same ten rules, declared once in a schema, checked against a hand-written in-memory fake and against a real engine: **the fake enforced 2 of 10; the engine enforced 10 of 10.** The fake is not badly written. It enforces the one constraint that was in the ticket its author was working on. The other eight are rules its author never had to think about, because the schema was thinking about them.

### The substitute-database fallacy, measured

So run the tests against a real engine — but which one? The tempting answer is "a real SQL database, just a faster one", and that is the substitute-database fallacy. Here is the whole argument, measured, ten schema-and-query pairs run live:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 638" width="100%" style="max-width:840px" role="img" aria-label="A ten-row table comparing what SQLite and PostgreSQL return for the same schema and the same query. Every one of the ten pairs returns a different result. Five of them PostgreSQL refuses with an error code — type affinity, VARCHAR length, divide by zero, foreign key enforcement and GROUP BY strictness — so the test suite is green and production raises a 500. The other five are answered by both engines with different answers and no error anywhere: a SUM over a NUMERIC money column is 10.305000000000001 in SQLite and exactly 10.31 in PostgreSQL, LIKE with an uppercase pattern matches one row in SQLite and none in PostgreSQL, page one of an ORDER BY holds different rows, the next id after a rolled-back INSERT is 2 in SQLite and 3 in PostgreSQL, and a re-read inside one transaction sees the old value in SQLite and the new one in PostgreSQL. A control row at the bottom shows multiple NULLs in a UNIQUE column, which behaves identically in both engines.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The same schema, the same SQL, two engines: 10 pairs, 10 different answers</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured — the sqlite3 column is executed live by code/integration_db.py; postgres is documented behaviour + SQLSTATE</text>
    <text x="32" y="80" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.7">THE QUERY</text>
    <text x="272" y="80" font-size="9.5" font-weight="700" fill="#e0930f">sqlite3 — THE SUBSTITUTE</text>
    <text x="574" y="80" font-size="9.5" font-weight="700" fill="#0fa07f">postgresql 17 — WHAT YOU DEPLOY</text>
    <path d="M20 86 L860 86" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <rect x="20" y="98" width="5" height="34" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <rect x="262" y="98" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="98" width="294" height="34" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.1"/>
    <text x="34" y="112" font-size="9.5" font-weight="700" fill="currentColor">type affinity</text>
    <text x="34" y="125" font-size="8" fill="currentColor" opacity="0.72">INSERT '12 units' INTO an INTEGER col</text>
    <text x="272" y="120" font-size="8.8" fill="currentColor">row stored, typeof='text', SUM=12.0</text>
    <text x="574" y="120" font-size="8.8" fill="currentColor">[22P02] rejected at INSERT</text>
    <rect x="20" y="140" width="5" height="34" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <rect x="262" y="140" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="140" width="294" height="34" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.1"/>
    <text x="34" y="154" font-size="9.5" font-weight="700" fill="currentColor">VARCHAR length</text>
    <text x="34" y="167" font-size="8" fill="currentColor" opacity="0.72">INSERT 30 chars INTO VARCHAR(10)</text>
    <text x="272" y="162" font-size="8.8" fill="currentColor">row stored, length(code) = 30</text>
    <text x="574" y="162" font-size="8.8" fill="currentColor">[22001] rejected at INSERT</text>
    <rect x="20" y="182" width="5" height="34" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <rect x="262" y="182" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="182" width="294" height="34" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="196" font-size="9.5" font-weight="700" fill="currentColor">NUMERIC is exact</text>
    <text x="34" y="209" font-size="8" fill="currentColor" opacity="0.72">SUM over a NUMERIC(10,2) money column</text>
    <text x="272" y="204" font-size="8.8" fill="currentColor">SUM = 10.305000000000001  (a float)</text>
    <text x="574" y="204" font-size="8.8" fill="currentColor">SUM = 10.31  (exact decimal)</text>
    <rect x="20" y="224" width="5" height="34" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <rect x="262" y="224" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="224" width="294" height="34" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.1"/>
    <text x="34" y="238" font-size="9.5" font-weight="700" fill="currentColor">divide by zero</text>
    <text x="34" y="251" font-size="8" fill="currentColor" opacity="0.72">SELECT revenue / units  WHERE units = 0</text>
    <text x="272" y="246" font-size="8.8" fill="currentColor">returns NULL, one row, no error</text>
    <text x="574" y="246" font-size="8.8" fill="currentColor">[22012] division by zero</text>
    <rect x="20" y="266" width="5" height="34" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <rect x="262" y="266" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="266" width="294" height="34" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="280" font-size="9.5" font-weight="700" fill="currentColor">LIKE case</text>
    <text x="34" y="293" font-size="8" fill="currentColor" opacity="0.72">WHERE email LIKE 'ADA%'</text>
    <text x="272" y="288" font-size="8.8" fill="currentColor">matches 1 row</text>
    <text x="574" y="288" font-size="8.8" fill="currentColor">matches 0 rows  (LIKE is case-sensitive)</text>
    <rect x="20" y="308" width="5" height="34" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <rect x="262" y="308" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="308" width="294" height="34" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.1"/>
    <text x="34" y="322" font-size="9.5" font-weight="700" fill="currentColor">FK enforcement</text>
    <text x="34" y="335" font-size="8" fill="currentColor" opacity="0.72">INSERT a child row with no parent</text>
    <text x="272" y="330" font-size="8.8" fill="currentColor">inserted — foreign_keys is OFF by default</text>
    <text x="574" y="330" font-size="8.8" fill="currentColor">[23503] foreign key violation</text>
    <rect x="20" y="350" width="5" height="34" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <rect x="262" y="350" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="350" width="294" height="34" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="364" font-size="9.5" font-weight="700" fill="currentColor">ORDER BY collation</text>
    <text x="34" y="377" font-size="8" fill="currentColor" opacity="0.72">ORDER BY name LIMIT 2  (mixed case)</text>
    <text x="272" y="372" font-size="8.8" fill="currentColor">page 1 = ['Bob', 'Zoe']</text>
    <text x="574" y="372" font-size="8.8" fill="currentColor">page 1 = ['ada', 'Bob']</text>
    <rect x="20" y="392" width="5" height="34" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <rect x="262" y="392" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="392" width="294" height="34" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.1"/>
    <text x="34" y="406" font-size="9.5" font-weight="700" fill="currentColor">GROUP BY strictness</text>
    <text x="34" y="419" font-size="8" fill="currentColor" opacity="0.72">SELECT cust, city ... GROUP BY cust</text>
    <text x="272" y="414" font-size="8.8" fill="currentColor">returns 'Berlin' — picks one arbitrarily</text>
    <text x="574" y="414" font-size="8.8" fill="currentColor">[42803] must appear in GROUP BY</text>
    <rect x="20" y="434" width="5" height="34" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <rect x="262" y="434" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="434" width="294" height="34" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="448" font-size="9.5" font-weight="700" fill="currentColor">sequence gaps</text>
    <text x="34" y="461" font-size="8" fill="currentColor" opacity="0.72">next id after a rolled-back INSERT</text>
    <text x="272" y="456" font-size="8.8" fill="currentColor">ids are [1, 2] — id 2 is reused</text>
    <text x="574" y="456" font-size="8.8" fill="currentColor">ids are [1, 3] — sequences never roll back</text>
    <rect x="20" y="476" width="5" height="34" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <rect x="262" y="476" width="294" height="34" rx="4" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="1.1"/>
    <rect x="564" y="476" width="294" height="34" rx="4" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="490" font-size="9.5" font-weight="700" fill="currentColor">read snapshot</text>
    <text x="34" y="503" font-size="8" fill="currentColor" opacity="0.72">re-read a row another txn just committed</text>
    <text x="272" y="498" font-size="8.8" fill="currentColor">same txn reads 100 then 100</text>
    <text x="574" y="498" font-size="8.8" fill="currentColor">same txn reads 100 then 555</text>
    <path d="M20 520 L860 520" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <rect x="262" y="530" width="294" height="30" rx="4" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.1"/>
    <rect x="564" y="530" width="294" height="30" rx="4" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="1.1"/>
    <text x="34" y="542" font-size="9.5" font-weight="700" fill="#0fa07f">THE CONTROL</text>
    <text x="34" y="555" font-size="8" fill="currentColor" opacity="0.72">three NULLs into a UNIQUE column</text>
    <text x="272" y="549" font-size="8.8" fill="currentColor">3 NULL rows accepted</text>
    <text x="574" y="549" font-size="8.8" fill="currentColor">3 NULL rows accepted — IDENTICAL</text>
    <rect x="20" y="574" width="404" height="26" rx="5" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.1"/>
    <rect x="436" y="574" width="424" height="26" rx="5" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.4"/>
    <rect x="30" y="581" width="5" height="12" rx="2" fill="#7f7f7f" fill-opacity="0.85"/>
    <text x="44" y="591" font-size="9.5" fill="currentColor">5 · postgres REFUSES — green suite, 500 in production</text>
    <rect x="446" y="581" width="5" height="12" rx="2" fill="#d64545" fill-opacity="0.85"/>
    <text x="460" y="591" font-size="9.5" font-weight="700" fill="#d64545">5 · BOTH ANSWER, DIFFERENTLY — no error is raised anywhere, ever</text>
    <text x="440" y="622" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Five of these never throw. The wrong number is the output: the money, the search, the page, the id.</text>
  </g>
</svg>
```

All ten diverge, and the split is the part worth internalising. **Five of them PostgreSQL simply refuses.** Your suite is green because SQLite accepted the row; production returns a `500` the first time that code path executes with real data. That is bad, and it is the *good* half — the failure is loud, it has a stack trace, and it arrives on the day you ship.

**The other five are answered by both engines, differently, with no error raised anywhere, ever.** There is no exception to catch, no log line, no alert. The wrong number is the output:

- **Money.** `NUMERIC(10,2)` in PostgreSQL is an arbitrary-precision exact decimal. In SQLite it is a hint with no enforcement (the "Datatypes In SQLite" documentation calls this **type affinity**: a column has a preference, not a type), so the value is stored as a 64-bit float. `SUM` over the same three rows measures **`10.305000000000001` against `10.31`**. That is the 11:40 ticket, and it does not go away by rounding at the edges, because the two engines rounded at different moments.
- **Search.** `LIKE 'ADA%'` matched **1 row** on SQLite and matches **0** on PostgreSQL, whose `LIKE` is case-sensitive (`ILIKE` is the case-insensitive one). Your test proves the search works. The 14:07 ticket says it never has.
- **Ordering.** `ORDER BY name LIMIT 2` returned **`['Bob', 'Zoe']`** on SQLite's `BINARY` collation, which sorts all uppercase before all lowercase, against **`['ada', 'Bob']`** under a typical `en_US.UTF-8`. Page 1 of your paginated list is a different set of rows in the two environments, and every cursor built on that ordering ([API Versioning](../../02-api-design/05-api-versioning/) covers why cursors leak into contracts) means something different.
- **Identity.** After a rolled-back `INSERT`, SQLite's next id was **2 — the id the rolled-back row had.** PostgreSQL gives **3**, because a sequence is deliberately non-transactional: it must hand out unique values to concurrent sessions without blocking, so it cannot roll back. Every test that asserts `assert order.id == 2` passes locally and fails the first time anything else touches that table.
- **Isolation.** Inside one transaction, after another connection committed a change, SQLite read **100 then 100** and PostgreSQL reads **100 then 555**. SQLite in WAL mode gives a read transaction a snapshot at its first read; PostgreSQL's default `READ COMMITTED` gives every *statement* a fresh snapshot ([Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/) is the mechanism). A test asserting "we are safe from non-repeatable reads" passes on the substitute by accident, and the code it was protecting is unprotected.

It is worth being clear that none of these are bugs in SQLite. Flexible typing is a documented design decision, made for an embedded database that must accept whatever an application hands it without a schema-migration ceremony; `LIKE` being ASCII-case-insensitive is the documented default; storing everything as one of five storage classes is what lets the whole engine fit in a few hundred kilobytes. Every divergence in that table is two teams making different, defensible choices for different products. **That is exactly why you cannot reason your way to safety here.** There is no bug to report and no fix to wait for. The two engines are not converging, and the only variable you control is which one your tests talk to.

Now the row at the bottom of the figure, which is the one that should change how you think about this. **The control is a `UNIQUE` constraint on a nullable column** — three `NULL`s inserted into a `UNIQUE` column. It is the divergence everyone names first. It does not diverge: both engines accepted all three, because SQL:2016 specifies that `NULL`s are distinct in a unique index and both implement it. **The differences that bite are never the ones already on your list**, which is exactly why enumerating them is not a strategy. You cannot maintain a list of the ways two engines differ. You can only stop having two engines.

### What only a real database can express

Take the argument one step further down. If the schema is where the rules live, a test double that stands in for the database is a second, private, unverified copy of those rules — the central problem of [Test Doubles](../04-test-doubles/), applied to the highest-value contract in your system.

The ten rules measured in section 2 are ordinary ones: `UNIQUE`, `NOT NULL`, two `CHECK` constraints, a `FOREIGN KEY`, a partial unique index, a `DEFAULT`, `ON DELETE CASCADE`, an upsert, and `INSERT ... RETURNING`. The fake caught the duplicate email and applied the default. It let through the null, the invalid enum value, the negative-price order, the order for a customer that does not exist, and the second concurrent "open" order that a partial unique index exists specifically to prevent. It orphaned a child row on delete. It could not do `RETURNING` at all.

A partial unique index — `CREATE UNIQUE INDEX ... ON orders(cid) WHERE status='open'` — is worth pausing on, because it is the shape of the rules you most want tested. It says "a customer may have many orders but at most one open one", it is enforced atomically by the engine against all concurrent writers, and reimplementing it correctly in application code is genuinely hard (it is a distributed-uniqueness problem the moment you have two app servers). It is exactly the rule you must not verify against a double, and exactly the rule a double will silently agree with.

### Isolation between tests: four strategies, and what each cannot undo

Every test wants a known database. Test 41 must not be able to see what test 40 wrote, or the suite's result depends on its order, and a suite whose result depends on its order is not measuring the code ([Determinism](../08-determinism-time-randomness-order/) is the general form of this problem).

There are four ways to get there, and there is a methodology point before the numbers. Wall-clock seconds are the obvious way to compare them and the wrong one: they change with your disk, your CPU, your container, and the phase of your page cache, so no number you publish is reproducible. What the clock is *measuring* is reproducible. `code/integration_db.py` counts the physical work instead — SQL statements issued, rows changed, and commits, where a commit on a real server is an `fsync` and is the single most expensive thing in the list:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 540" width="100%" style="max-width:840px" role="img" aria-label="Four ways to isolate one integration test from the next, measured over two hundred tests against a six-table, two-hundred-and-forty-row fixture. Recreating the schema costs 260 SQL statements and 242 row changes per test with 200 commits. Truncating and reseeding costs 251 statements and 482 row changes per test with 200 commits. Wrapping each test in a transaction and rolling it back costs 5 statements and 2.1 row changes per test with zero commits — roughly fifty times fewer statements and a hundred and fifteen to two hundred and thirty times fewer row changes. Copying a seeded template file costs 3 statements and 2.1 row changes but moves 40,960 bytes per test. A projection onto PostgreSQL using a one millisecond commit and a 0.05 millisecond statement puts recreate at 2.80 seconds, truncate at 2.71 seconds and rollback at 0.05 seconds. A footer lists what each strategy cannot undo.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Four ways to get a clean database, priced in physical work</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured over 200 tests · 6 tables, 3 indexes, 240 seed rows · counted in statements, not seconds, so the number reproduces</text>
    <text x="20" y="80" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">STRATEGY</text>
    <text x="250" y="80" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">SQL STATEMENTS / TEST</text>
    <text x="552" y="80" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">ROW CHANGES / TEST</text>
    <text x="858" y="80" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.65">COMMITS</text>
    <path d="M20 86 L858 86" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <text x="20" y="110" font-size="10.5" font-weight="700" fill="currentColor">recreate schema</text>
    <text x="20" y="123" font-size="8.2" fill="currentColor" opacity="0.72">drop, rebuild, reseed</text>
    <text x="20" y="136" font-size="8.2" fill="#e0930f" font-weight="700">isolates EVERYTHING</text>
    <rect x="250" y="102" width="200.0" height="16" rx="3" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/>
    <text x="457.0" y="114" font-size="10" font-weight="700" fill="currentColor">260.0</text>
    <rect x="552" y="102" width="85.4" height="16" rx="3" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/>
    <text x="644.4" y="114" font-size="10" font-weight="700" fill="currentColor">242.1</text>
    <text x="858" y="114" font-size="11" font-weight="700" text-anchor="end" fill="#d64545">200</text>
    <text x="20" y="170" font-size="10.5" font-weight="700" fill="currentColor">truncate + reseed</text>
    <text x="20" y="183" font-size="8.2" fill="currentColor" opacity="0.72">DELETE every table, reseed</text>
    <text x="20" y="196" font-size="8.2" fill="#e0930f" font-weight="700">isolates committed rows</text>
    <rect x="250" y="162" width="193.1" height="16" rx="3" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/>
    <text x="450.1" y="174" font-size="10" font-weight="700" fill="currentColor">251.0</text>
    <rect x="552" y="162" width="170.0" height="16" rx="3" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.4"/>
    <text x="729.0" y="174" font-size="10" font-weight="700" fill="currentColor">481.9</text>
    <text x="858" y="174" font-size="11" font-weight="700" text-anchor="end" fill="#d64545">200</text>
    <text x="20" y="230" font-size="10.5" font-weight="700" fill="currentColor">transaction rollback</text>
    <text x="20" y="243" font-size="8.2" fill="currentColor" opacity="0.72">BEGIN, run, ROLLBACK</text>
    <text x="20" y="256" font-size="8.2" fill="#0fa07f" font-weight="700">isolates uncommitted writes ONLY</text>
    <rect x="250" y="222" width="3.8" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.4"/>
    <text x="260.8" y="234" font-size="10" font-weight="700" fill="currentColor">5.0</text>
    <rect x="552" y="222" width="3.0" height="16" rx="3" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.4"/>
    <text x="562.0" y="234" font-size="10" font-weight="700" fill="currentColor">2.1</text>
    <text x="858" y="234" font-size="11" font-weight="700" text-anchor="end" fill="#0fa07f">0</text>
    <text x="20" y="290" font-size="10.5" font-weight="700" fill="currentColor">template copy</text>
    <text x="20" y="303" font-size="8.2" fill="currentColor" opacity="0.72">byte-copy a seeded file</text>
    <text x="20" y="316" font-size="8.2" fill="#7c5cff" font-weight="700">isolates everything, incl. schema</text>
    <rect x="250" y="282" width="3.0" height="16" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="1.4"/>
    <text x="260.0" y="294" font-size="10" font-weight="700" fill="currentColor">3.0</text>
    <rect x="552" y="282" width="3.0" height="16" rx="3" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="1.4"/>
    <text x="562.0" y="294" font-size="10" font-weight="700" fill="currentColor">2.1</text>
    <text x="858" y="294" font-size="11" font-weight="700" text-anchor="end" fill="#0fa07f">0</text>
    <path d="M256 242 L256 254 L264 254" fill="none" stroke="#0fa07f" stroke-width="1.3" stroke-dasharray="4 3"/>
    <text x="270" y="257" font-size="9.5" font-weight="700" fill="#0fa07f">50x fewer statements &#183; 230x fewer row changes &#183; 0 fsyncs</text>
    <path d="M20 344 L858 344" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <text x="20" y="364" font-size="10.5" font-weight="700" fill="currentColor">PROJECTED ONTO POSTGRESQL — SQL work only</text>
    <text x="20" y="378" font-size="8.5" fill="currentColor" opacity="0.75">assumed, NOT measured here: 1.0 ms per commit with fsync on, 0.05 ms per statement round trip. Substitute your own.</text>
    <text x="20" y="396" font-size="9.5" fill="currentColor">recreate schema</text>
    <rect x="200" y="387" width="300.0" height="11" rx="2" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.2"/>
    <text x="507.0" y="396" font-size="9.5" font-weight="700" fill="currentColor">2.80 s</text>
    <text x="20" y="416" font-size="9.5" fill="currentColor">truncate + reseed</text>
    <rect x="200" y="407" width="290.4" height="11" rx="2" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.2"/>
    <text x="497.4" y="416" font-size="9.5" font-weight="700" fill="currentColor">2.71 s</text>
    <text x="20" y="436" font-size="9.5" fill="currentColor">transaction rollback</text>
    <rect x="200" y="427" width="5.4" height="11" rx="2" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.2"/>
    <text x="212.4" y="436" font-size="9.5" font-weight="700" fill="currentColor">0.05 s</text>
    <text x="20" y="456" font-size="9.5" fill="currentColor">template copy</text>
    <rect x="200" y="447" width="3.2" height="11" rx="2" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="1.2"/>
    <text x="210.2" y="456" font-size="9.5" font-weight="700" fill="currentColor">0.03 s  + 40,960 bytes copied per test</text>
    <rect x="560" y="388" width="298" height="70" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.5"/>
    <text x="572" y="406" font-size="10.5" font-weight="700" fill="#0fa07f">54x cheaper than truncate</text>
    <text x="572" y="422" font-size="9" fill="currentColor" opacity="0.9">and the gap WIDENS with fixture size —</text>
    <text x="572" y="435" font-size="9" fill="currentColor" opacity="0.9">rollback&#8217;s cost does not depend on how</text>
    <text x="572" y="448" font-size="9" fill="currentColor" opacity="0.9">much seed data you have. The others do.</text>
    <rect x="20" y="470" width="838" height="34" rx="6" fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="1.4"/>
    <text x="32" y="486" font-size="9.5" font-weight="700" fill="#d64545">WHAT ROLLBACK CANNOT UNDO:</text>
    <text x="238" y="486" font-size="9.5" fill="currentColor">anything the code under test COMMITS itself &#183; sequence values &#183; files, mail, caches</text>
    <text x="32" y="499" font-size="9" fill="currentColor" opacity="0.85">TRUNCATE: sequence values unless RESTART IDENTITY &#183; schema changes.   TEMPLATE / RECREATE: nothing — and that is what they cost.</text>
    <text x="440" y="526" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">Rollback is the fastest strategy and the only one that can silently do nothing at all.</text>
  </g>
</svg>
```

The shape of the result is stark. **Recreating the schema costs 260 statements and 242 row changes per test; truncate-and-reseed costs 251 statements and 482 row changes** (it pays twice — once to delete every row, once to write it back). **Transaction rollback costs 5 statements, 2.1 row changes, and zero commits across the entire 200-test run.** That is roughly **50× fewer statements and 230× fewer row changes**, and the reason is structural rather than clever: *rollback never re-seeds anything.* Truncate and recreate write all 240 fixture rows 200 times over — **96,379 row changes against 420.**

The last column matters as much as the first. **Rollback performed zero commits.** The other two performed 200 each, and every one of those is a durable write the server must flush before it can answer. Projected onto PostgreSQL at 1 ms per commit and 0.05 ms per statement — constants the program prints and does not measure, so substitute your own — the suite's SQL time is **2.71 s for truncate against 0.05 s for rollback, 54× cheaper.** And that gap grows: rollback's cost does not depend on how large your fixture is, and every other strategy's does. A team with a 4,000-row seed sees the same 5 statements per test.

The fourth strategy is the **template database**: seed one database, then copy it per test. It does almost no SQL — 3 statements — and moves **40,960 bytes** per test instead. That trade is the right one above some fixture size, because the cost scales with the database rather than with the number of rows your loader inserts one at a time. PostgreSQL gives you this directly with `CREATE DATABASE testdb_7 TEMPLATE testdb_master`, which is a file copy inside the server.

Now the part that decides which one you can actually use — **what each strategy cannot undo:**

- **Rollback** cannot undo anything the code under test committed itself (the next section), and it cannot undo a sequence value, because PostgreSQL sequences never roll back. It cannot undo anything outside the database at all: a file written, an email queued, a cache key set.
- **Truncate** does not reset sequences unless you write `TRUNCATE ... RESTART IDENTITY`, and it cannot undo a schema change, so a test that runs a migration poisons everything after it.
- **Template and recreate** undo everything, including the schema. That is what they cost.

### The transaction-rollback trick, and the exact case where it lies

The rollback strategy is three lines. Before each test, `BEGIN`. Run the test. Afterwards, `ROLLBACK`. Nothing the test wrote was ever committed, so nothing survives, and the database is byte-identical to where it started without a single row being rewritten. It is the correct default and the numbers above are why.

It also has one failure mode, it is not rare, and it is invisible:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 574" width="100%" style="max-width:840px" role="img" aria-label="Two step charts of transaction nesting depth through one test. On the left, the naive harness: BEGIN takes depth to one, the code under test INSERTs, then the repository calls COMMIT which takes depth back to zero in the middle of the test and makes the write durable; the repository reopens a transaction and the harness ROLLBACK at the end undoes an empty one. Three rows survive the rollback, the suite is green in file order, and shuffling 400 times caught it in 378 runs, 94.5 percent. On the right, the fix: the harness opens BEGIN and a SAVEPOINT, the repository&#8217;s commit becomes a savepoint RELEASE followed by a new SAVEPOINT, so the depth never returns to zero until the harness ROLLBACK at the end, which undoes everything. Zero rows survive and all 400 shuffled runs are green, with no change to the production code.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The rollback lie: what happens when the code under test commits</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">transaction nesting depth through one test &#183; the naive harness returns to depth 0 in the MIDDLE of the test, and that is the whole bug</text>
    <rect x="14" y="56" width="418" height="336" rx="10" fill="#d64545" fill-opacity="0.06" stroke="#d64545" stroke-width="1.7"/>
    <rect x="448" y="56" width="418" height="336" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.7"/>
    <text x="223" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#d64545">NAIVE &#8212; the repository calls commit()</text>
    <text x="657" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">FIXED &#8212; commit() becomes a SAVEPOINT release</text>
    <path d="M36 240 L416 240" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <path d="M466 240 L846 240" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <text x="32" y="243" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">0</text>
    <text x="462" y="243" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">0</text>
    <path d="M36 205 L416 205" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <path d="M466 205 L846 205" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <text x="32" y="208" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">1</text>
    <text x="462" y="208" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">1</text>
    <path d="M36 170 L416 170" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <path d="M466 170 L846 170" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/>
    <text x="32" y="173" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">2</text>
    <text x="462" y="173" text-anchor="end" font-size="7.5" fill="currentColor" opacity="0.6">2</text>
    <text x="26" y="152" font-size="8" font-weight="700" fill="currentColor" opacity="0.7">depth</text>
    <rect x="220" y="236" width="80" height="8" fill="#d64545" fill-opacity="0.35" stroke="none"/>
    <text x="260" y="230" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">NO TXN OPEN</text>
    <path d="M36 240 L60 240 L60 205 L220 205 L220 240 L300 240 L300 205 L380 205 L380 240 L416 240" fill="none" stroke="#d64545" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M466 240 L486 240 L486 205 L522 205 L522 170 L626 170 L626 205 L678 205 L678 170 L730 170 L730 205 L790 205 L790 240 L846 240" fill="none" stroke="#0fa07f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M60 240 L60 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="60" cy="258" r="7.5" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="60" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">1</text>
    <path d="M140 240 L140 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="140" cy="258" r="7.5" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="140" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">2</text>
    <path d="M220 240 L220 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="220" cy="258" r="7.5" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="220" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">3</text>
    <path d="M300 240 L300 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="300" cy="258" r="7.5" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="300" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">4</text>
    <path d="M380 240 L380 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="380" cy="258" r="7.5" fill="none" stroke="#d64545" stroke-width="1.3"/>
    <text x="380" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">5</text>
    <path d="M486 240 L486 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="486" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="486" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">1</text>
    <path d="M522 240 L522 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="522" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="522" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">2</text>
    <path d="M574 240 L574 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="574" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="574" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">3</text>
    <path d="M626 240 L626 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="626" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="626" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">4</text>
    <path d="M678 240 L678 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="678" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="678" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">5</text>
    <path d="M730 240 L730 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="730" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="730" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">6</text>
    <path d="M790 240 L790 248" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.55"/>
    <circle cx="790" cy="258" r="7.5" fill="none" stroke="#0fa07f" stroke-width="1.3"/>
    <text x="790" y="261.5" text-anchor="middle" font-size="8.5" font-weight="700" fill="#0fa07f">7</text>
    <circle cx="140" cy="205" r="4.5" fill="#3553ff" stroke="none"/>
    <text x="140" y="196" text-anchor="middle" font-size="8" font-weight="700" fill="#3553ff">INSERT</text>
    <circle cx="574" cy="170" r="4.5" fill="#3553ff" stroke="none"/>
    <text x="574" y="161" text-anchor="middle" font-size="8" font-weight="700" fill="#3553ff">INSERT</text>
    <text x="222" y="196" text-anchor="middle" font-size="8" font-weight="700" fill="#d64545">COMMIT</text>
    <text x="28" y="292" font-size="8.3" fill="currentColor">1 &#183; BEGIN &#8212; the harness opens the test transaction</text>
    <text x="28" y="305" font-size="8.3" fill="currentColor">2 &#183; INSERT INTO products &#8212; the code under test writes</text>
    <text x="28" y="318" font-size="8.3" fill="currentColor">3 &#183; COMMIT &#8212; THE HARNESS&#8217;S TRANSACTION IS GONE. On disk.</text>
    <text x="28" y="331" font-size="8.3" fill="currentColor">4 &#183; BEGIN &#8212; the repository reopens one for its caller</text>
    <text x="28" y="344" font-size="8.3" fill="currentColor">5 &#183; ROLLBACK &#8212; the harness undoes an EMPTY transaction</text>
    <text x="462" y="292" font-size="8.3" fill="currentColor">1 &#183; BEGIN &#8212; the harness opens the test transaction</text>
    <text x="462" y="305" font-size="8.3" fill="currentColor">2 &#183; SAVEPOINT svc &#8212; and a nested one for the code</text>
    <text x="462" y="318" font-size="8.3" fill="currentColor">3 &#183; INSERT INTO products &#8212; the same production line</text>
    <text x="462" y="331" font-size="8.3" fill="currentColor">4 &#183; RELEASE svc &#8212; the repository&#8217;s &#8220;commit&#8221;</text>
    <text x="462" y="344" font-size="8.3" fill="currentColor">5 &#183; SAVEPOINT svc &#8212; reopened, still inside the harness</text>
    <text x="462" y="357" font-size="8.3" fill="currentColor">6 &#183; ROLLBACK TO svc &#183; RELEASE svc</text>
    <text x="462" y="370" font-size="8.3" fill="currentColor">7 &#183; ROLLBACK &#8212; the outer txn is still there. All gone.</text>
    <rect x="14" y="404" width="418" height="82" rx="9" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.6"/>
    <rect x="448" y="404" width="418" height="82" rx="9" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="28" y="424" font-size="10.5" font-weight="700" fill="#d64545">3 rows survived the rollback, 0 failures</text>
    <text x="28" y="441" font-size="9.3" fill="currentColor" opacity="0.92">file order is green 100% of the time, for ever</text>
    <text x="28" y="456" font-size="9.3" fill="currentColor" opacity="0.92">shuffled 400x:  22 green (5.50%)  &#183;  378 caught (94.50%)</text>
    <text x="28" y="471" font-size="9.3" fill="currentColor" opacity="0.92">P(three shuffled runs ALL miss it) = 0.02%</text>
    <text x="462" y="424" font-size="10.5" font-weight="700" fill="#0fa07f">0 rows survived, 0 failures</text>
    <text x="462" y="441" font-size="9.3" fill="currentColor" opacity="0.92">shuffled 400x:  400/400 green (100.00%)</text>
    <text x="462" y="456" font-size="9.3" fill="currentColor" opacity="0.92">same suite, same tests, same three repositories</text>
    <text x="462" y="471" font-size="9.3" fill="currentColor" opacity="0.92">that still call commit(). The seam moved, not the code.</text>
    <text x="440" y="512" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A ROLLBACK can only undo a transaction that is still open. COMMIT closed it, so the rollback undid nothing.</text>
    <text x="440" y="532" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The suite never noticed, because the tests that would have noticed happened to run first.</text>
  </g>
</svg>
```

Read the left chart as transaction nesting depth over the life of one test. The harness opens a transaction (depth 1). The code under test inserts a row. Then the repository calls `commit()` — because in production, that repository method owns its transaction, and that is correct design, not a bug. **The depth drops to 0 in the middle of the test**, and at that instant the row is durable. The repository opens a fresh transaction for its caller, and the harness's `ROLLBACK` at the end faithfully undoes that fresh, empty transaction. The row stays.

The measured result over a 200-test suite with three such tests: **3 rows survived the rollback, and 0 tests failed.** The suite is green. It will be green tomorrow and next year, because the three committing tests are at the end of the file and the three tests that assert an empty catalogue are at positions 40, 90 and 140 — they run before the pollution exists. File order is one permutation out of 200!, and it happens to be a safe one.

Shuffle the order, which is what `pytest-randomly` does on every run, and the picture inverts: **378 of 400 shuffled runs caught it — 94.50%.** The probability that three consecutive shuffled runs all miss it is **0.02%**. This is the exact shape of an order-dependent bug and the reason it deserves its own vocabulary: it is not *rare*, it is *conditional*, and the condition is a permutation you never try. One line of configuration converts a bug that hides for ever into one that surfaces on the first run.

The fix is on the right, and it is not "stop calling `commit()`". You cannot ask production code to stop managing its own transactions; that is the code being correct. Instead, **move the seam** ([Designing for Testability](../05-designing-for-testability/) is the general technique). Hand the code under test a connection whose `commit()` is a `SAVEPOINT` release: the repository still publishes to its caller, the nesting depth drops from 2 to 1 rather than from 1 to 0, and the harness's outer transaction is still open at the end to roll everything back. Measured: **0 rows survived and 400 of 400 shuffled runs green** — with the three repositories still calling `commit()`, and not one line of production code changed.

There is a second lie in the same family, and it is worth naming because the fix above does not cover it: rollback cannot isolate a **sequence**. PostgreSQL's `nextval()` is deliberately outside transaction control, so a rolled-back test still consumed the id. Any assertion of the form `assert response.json()["id"] == 1` is order-dependent under *every* isolation strategy on a real server. Assert that the id is an integer, or that it round-trips, never that it is a particular number.

### Concurrency in an integration test: producing a lost update on purpose

Most suites contain zero tests that run two connections at once, which means the entire class of concurrency bug is untested by construction. The usual objection is that concurrency tests are flaky. They are flaky when written with threads and `sleep()`. They are perfectly deterministic when you drive both connections yourself, one step at a time, from a single thread — which is also the only way to hit a specific interleaving on purpose.

One row, a balance of 100. `T1` adds 10, `T2` adds 5, both as read-modify-write, which is what every ORM produces from `account.balance += 10`. The correct answer is 115. There are exactly six legal interleavings, and `code/integration_db.py` replays all six against the real engine:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 528" width="100%" style="max-width:840px" role="img" aria-label="All six ways two read-modify-write transactions can interleave over one row holding a balance of 100, where transaction one adds ten and transaction two adds five, so the correct answer is always 115. The two serial schedules, where each transaction reads and writes before the other starts, both give 115 and pass, and they are the only two a normal test runs. The four interleaved schedules, where both reads happen before either write, give 105, 110, 105 and 110 &#8212; every one silently loses one of the two updates. Adding a version column so the UPDATE carries WHERE version equals the value that was read makes all six schedules end at 115: the four interleaved ones each detect one conflict through a zero row count and retry. At scale, eight workers doing twenty-five increments each end at 25 out of 200 without the version column and exactly 200 with it.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Six ways two transactions can interleave. Four of them lose money.</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">one row, balance 100 &#183; T1 adds 10, T2 adds 5 &#183; the right answer is 115, always &#183; every schedule replayed against the real engine</text>
    <text x="22" y="86" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">SCHEDULE</text>
    <text x="250" y="86" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">TIME &#8594;</text>
    <text x="660" y="86" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">NAIVE</text>
    <text x="762" y="86" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">+ VERSION COL</text>
    <path d="M20 92 L858 92" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <rect x="20" y="96" width="838" height="40" rx="6" fill="#0fa07f" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="112" font-size="10" font-weight="700" fill="currentColor">R1 W1 R2 W2</text>
    <text x="30" y="126" font-size="7.6" font-weight="700" fill="#e0930f">serial &#183; the only two a test runs</text>
    <rect x="250" y="99" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="281" y="109" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="281" y="120" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="99" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="375" y="109" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="375" y="120" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <rect x="438" y="99" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="469" y="109" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="469" y="120" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="532" y="99" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="563" y="109" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="563" y="120" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <text x="660" y="112" font-size="10.5" font-weight="700" fill="#0fa07f">115  ok</text>
    <text x="762" y="112" font-size="10.5" font-weight="700" fill="#0fa07f">115  ok</text>
    <rect x="20" y="148" width="838" height="40" rx="6" fill="#0fa07f" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="164" font-size="10" font-weight="700" fill="currentColor">R2 W2 R1 W1</text>
    <text x="30" y="178" font-size="7.6" font-weight="700" fill="#e0930f">serial &#183; the only two a test runs</text>
    <rect x="250" y="151" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="281" y="161" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="281" y="172" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="151" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="375" y="161" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="375" y="172" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <rect x="438" y="151" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="469" y="161" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="469" y="172" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="532" y="151" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="563" y="161" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="563" y="172" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <text x="660" y="164" font-size="10.5" font-weight="700" fill="#0fa07f">115  ok</text>
    <text x="762" y="164" font-size="10.5" font-weight="700" fill="#0fa07f">115  ok</text>
    <rect x="20" y="200" width="838" height="40" rx="6" fill="#d64545" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="216" font-size="10" font-weight="700" fill="currentColor">R1 R2 W1 W2</text>
    <text x="30" y="230" font-size="7.6" font-weight="700" fill="#7f7f7f">interleaved &#183; never tested</text>
    <rect x="250" y="203" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="281" y="213" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="281" y="224" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="203" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="375" y="213" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="375" y="224" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="438" y="203" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="469" y="213" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="469" y="224" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <rect x="532" y="203" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="563" y="213" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="563" y="224" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <text x="660" y="216" font-size="10.5" font-weight="700" fill="#d64545">105  LOST 10</text>
    <text x="762" y="216" font-size="10.5" font-weight="700" fill="#0fa07f">115  caught</text>
    <rect x="20" y="252" width="838" height="40" rx="6" fill="#d64545" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="268" font-size="10" font-weight="700" fill="currentColor">R1 R2 W2 W1</text>
    <text x="30" y="282" font-size="7.6" font-weight="700" fill="#7f7f7f">interleaved &#183; never tested</text>
    <rect x="250" y="255" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="281" y="265" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="281" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="255" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="375" y="265" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="375" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="438" y="255" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="469" y="265" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="469" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <rect x="532" y="255" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="563" y="265" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="563" y="276" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <text x="660" y="268" font-size="10.5" font-weight="700" fill="#d64545">110  LOST 5</text>
    <text x="762" y="268" font-size="10.5" font-weight="700" fill="#0fa07f">115  caught</text>
    <rect x="20" y="304" width="838" height="40" rx="6" fill="#d64545" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="320" font-size="10" font-weight="700" fill="currentColor">R2 R1 W1 W2</text>
    <text x="30" y="334" font-size="7.6" font-weight="700" fill="#7f7f7f">interleaved &#183; never tested</text>
    <rect x="250" y="307" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="281" y="317" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="281" y="328" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="307" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="375" y="317" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="375" y="328" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="438" y="307" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="469" y="317" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="469" y="328" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <rect x="532" y="307" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="563" y="317" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="563" y="328" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <text x="660" y="320" font-size="10.5" font-weight="700" fill="#d64545">105  LOST 10</text>
    <text x="762" y="320" font-size="10.5" font-weight="700" fill="#0fa07f">115  caught</text>
    <rect x="20" y="356" width="838" height="40" rx="6" fill="#d64545" fill-opacity="0.07" stroke="none"/>
    <text x="30" y="372" font-size="10" font-weight="700" fill="currentColor">R2 R1 W2 W1</text>
    <text x="30" y="386" font-size="7.6" font-weight="700" fill="#7f7f7f">interleaved &#183; never tested</text>
    <rect x="250" y="359" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="281" y="369" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 read</text>
    <text x="281" y="380" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="344" y="359" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="375" y="369" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 read</text>
    <text x="375" y="380" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">sees 100</text>
    <rect x="438" y="359" width="62" height="24" rx="4" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff" stroke-width="1.3"/>
    <text x="469" y="369" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">T2 write</text>
    <text x="469" y="380" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+5</text>
    <rect x="532" y="359" width="62" height="24" rx="4" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.3"/>
    <text x="563" y="369" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">T1 write</text>
    <text x="563" y="380" text-anchor="middle" font-size="7.5" fill="currentColor" opacity="0.8">+10</text>
    <text x="660" y="372" font-size="10.5" font-weight="700" fill="#d64545">110  LOST 5</text>
    <text x="762" y="372" font-size="10.5" font-weight="700" fill="#0fa07f">115  caught</text>
    <path d="M20 428 L858 428" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <rect x="20" y="438" width="410" height="56" rx="8" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.6"/>
    <rect x="448" y="438" width="410" height="56" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="34" y="457" font-size="10.5" font-weight="700" fill="#d64545">AT SCALE &#8212; 8 workers, 25 increments each</text>
    <text x="34" y="474" font-size="9.5" fill="currentColor" opacity="0.92">naive read-modify-write:  final 25 / 200 &#8212; 175 lost</text>
    <text x="34" y="488" font-size="9.5" fill="currentColor" opacity="0.92">run the same code serially: 200, and a green test</text>
    <text x="462" y="457" font-size="10.5" font-weight="700" fill="#0fa07f">WITH A VERSION COLUMN</text>
    <text x="462" y="474" font-size="9.5" fill="currentColor" opacity="0.92">final 200 / 200, 0 lost, 175 retries</text>
    <text x="462" y="488" font-size="9.5" fill="currentColor" opacity="0.92">UPDATE ... WHERE ver = ? &#8594; rowcount 0 means &#8220;retry&#8221;</text>
    <text x="440" y="518" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">The test that runs one transaction and then the next explores exactly the two schedules that cannot fail.</text>
  </g>
</svg>
```

**Four of the six lose an update.** When both transactions read before either writes, both compute from 100, and whichever writes second overwrites the other — final balance 105 or 110, no error, no warning, money gone. This is the **lost update** anomaly, and it is why [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/) exists; PostgreSQL's default `READ COMMITTED` does not prevent it, and neither does `REPEATABLE READ` for this shape without an explicit lock.

Now the finding that should change how you write these tests. **The two schedules that pass are the two serial ones — and those are exactly the two a normal test explores.** A test that arranges `T1`, runs it, then arranges `T2` and runs it, is by construction exploring `R1 W1 R2 W2`. It is green. It is *always* green. It has proved nothing whatsoever about the four schedules where the money disappears, and the reader of that test file will reasonably believe concurrency is covered.

Scale it up and the same mechanism gets loud: 8 workers doing 25 increments each, interleaved round-robin, ended at **25 out of an expected 200 — 175 increments lost.** Run the identical code serially and it ends at 200 with a green test.

The fix is a **version column** (optimistic concurrency control): read the row and its version, then write `UPDATE ... SET bal=?, ver=ver+1 WHERE id=? AND ver=?`. If somebody moved the row underneath you, the `WHERE` matches nothing and **`rowcount` comes back 0** — that is the conflict, detected exactly, with no lock held and nothing guessed. Retry from the new value. Measured: **all six schedules end at 115**, each of the four interleaved ones detecting exactly one conflict, and the 8-worker run ends at **exactly 200 with 175 retries.** The retries are the collisions, priced honestly rather than hidden. ([Race Conditions & Atomicity](../../08-concurrency-and-performance/08-race-conditions-and-atomicity/) covers the same trade in application memory.)

### Migrations in tests: run them forward, or load a dump?

There are two ways to put a schema into a test database. Run the migrations in order, the way production did. Or load `schema.sql`, a dump somebody generated once and checked in, because it is faster and because running 300 migrations per suite is absurd.

The second is a fourth environment that nobody migrates:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 546" width="100%" style="max-width:840px" role="img" aria-label="A migration timeline of five steps, with a marker showing that the checked-in schema.sql dump was regenerated after migration 004. Underneath, the seven columns of the orders table are listed with whether each exists in the migrated database and in the database loaded from the dump. Five columns match. legacy_total is missing from the migrated database because migration 005 dropped it, but is still present in the dump. discount_cents is present in the migrated database because 005 added it, and missing from the dump. The dump therefore drifts in both directions at once. Two measured results follow: a query selecting discount_cents returns 400 on the migrated database and raises no such column on the dump. And migration 004 backfilled currency only for paid orders, so the migrated database has 300 of 400 orders with a NULL currency while the dump database has 0 of 0 &#8212; it has no rows at all, so it cannot fail the test.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Migrate forward, or load a dump? They drift in both directions at once.</text>
    <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">measured &#8212; the same five migrations applied in order, versus a schema.sql regenerated after 004</text>
    <defs><marker id="p12-06-arw" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker></defs>
    <path d="M60 112 L95 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55"/>
    <path d="M125 112 L263 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55"/>
    <path d="M293 112 L431 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55"/>
    <path d="M461 112 L599 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55"/>
    <path d="M629 112 L767 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55"/>
    <path d="M797 112 L836 112" fill="none" stroke="currentColor" stroke-width="1.5" opacity="0.55" marker-end="url(#p12-06-arw)"/>
    <circle cx="110" cy="112" r="14" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="110" y="116" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">001</text>
    <text x="110" y="142" text-anchor="middle" font-size="7.6" fill="currentColor" opacity="0.8">initial</text>
    <circle cx="278" cy="112" r="14" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="278" y="116" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">002</text>
    <text x="278" y="142" text-anchor="middle" font-size="7.6" fill="currentColor" opacity="0.8">order index</text>
    <circle cx="446" cy="112" r="14" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="446" y="116" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">003</text>
    <text x="446" y="142" text-anchor="middle" font-size="7.6" fill="currentColor" opacity="0.8">status</text>
    <circle cx="614" cy="112" r="14" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f" stroke-width="1.7"/>
    <text x="614" y="116" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">004</text>
    <text x="614" y="142" text-anchor="middle" font-size="7.6" fill="currentColor" opacity="0.8">currency + backfill</text>
    <circle cx="782" cy="112" r="14" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff" stroke-width="1.7"/>
    <text x="782" y="116" text-anchor="middle" font-size="9" font-weight="700" fill="#7c5cff">005</text>
    <text x="782" y="142" text-anchor="middle" font-size="7.6" fill="currentColor" opacity="0.8">discount, drop legacy</text>
    <path d="M614 96 L614 74" fill="none" stroke="#e0930f" stroke-width="1.4" stroke-dasharray="4 3"/>
    <text x="614" y="68" text-anchor="middle" font-size="9.5" font-weight="700" fill="#e0930f">schema.sql regenerated HERE</text>
    <text x="836" y="98" text-anchor="end" font-size="8.5" fill="currentColor" opacity="0.75">production keeps moving</text>
    <path d="M20 160 L858 160" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <text x="60" y="178" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">orders COLUMN</text>
    <text x="330" y="178" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">MIGRATED FORWARD</text>
    <text x="480" y="178" text-anchor="middle" font-size="9" font-weight="700" fill="#e0930f">FROM schema.sql</text>
    <text x="580" y="178" font-size="9" font-weight="700" fill="currentColor" opacity="0.65">WHAT HAPPENED</text>
    <text x="60" y="201" font-size="10" font-weight="400" fill="currentColor">id</text>
    <text x="330" y="201" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="201" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="60" y="225" font-size="10" font-weight="400" fill="currentColor">cid</text>
    <text x="330" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="225" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="60" y="249" font-size="10" font-weight="400" fill="currentColor">cents</text>
    <text x="330" y="249" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="249" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <rect x="50" y="258" width="808" height="22" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.2"/>
    <text x="60" y="273" font-size="10" font-weight="700" fill="currentColor">legacy_total</text>
    <text x="330" y="273" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">MISSING</text>
    <text x="480" y="273" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="580" y="273" font-size="8.6" font-weight="700" fill="#d64545">005 DROPPED it &#8212; the dump still has it</text>
    <text x="60" y="297" font-size="10" font-weight="400" fill="currentColor">status</text>
    <text x="330" y="297" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="297" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="60" y="321" font-size="10" font-weight="400" fill="currentColor">currency</text>
    <text x="330" y="321" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="321" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <rect x="50" y="330" width="808" height="22" rx="4" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="1.2"/>
    <text x="60" y="345" font-size="10" font-weight="700" fill="currentColor">discount_cents</text>
    <text x="330" y="345" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">present</text>
    <text x="480" y="345" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">MISSING</text>
    <text x="580" y="345" font-size="8.6" font-weight="700" fill="#d64545">005 ADDED it &#8212; the dump never saw it</text>
    <path d="M20 376 L858 376" fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4"/>
    <rect x="20" y="388" width="410" height="98" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.3"/>
    <rect x="448" y="388" width="410" height="98" rx="8" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="1.6"/>
    <text x="34" y="406" font-size="9.2" font-weight="700" fill="currentColor">SELECT count(*) FROM orders WHERE discount_cents = 0</text>
    <text x="34" y="426" font-size="9.5" fill="#0fa07f" font-weight="700">migrated    400</text>
    <text x="34" y="443" font-size="9.2" fill="#d64545" font-weight="700">from dump   no such column: discount_cents</text>
    <text x="34" y="465" font-size="8.6" fill="currentColor" opacity="0.85">A schema diff finds this one. It is the easy half,</text>
    <text x="34" y="477" font-size="8.6" fill="currentColor" opacity="0.85">and it fails loudly the first time the query runs.</text>
    <text x="462" y="406" font-size="9.5" font-weight="700" fill="#d64545">THE HALF NO SCHEMA DIFF CAN FIND</text>
    <text x="462" y="424" font-size="8.8" fill="currentColor" opacity="0.9">004 backfilled currency for status=&#8217;paid&#8217; rows only.</text>
    <text x="462" y="443" font-size="9.2" fill="#0fa07f" font-weight="700">migrated    300 of 400 orders have currency IS NULL</text>
    <text x="462" y="460" font-size="9.2" fill="#d64545" font-weight="700">from dump   0 of 0 &#8212; there are no rows at all</text>
    <text x="462" y="478" font-size="8.6" font-weight="700" fill="currentColor">The dump is not passing this test. It cannot fail it.</text>
    <text x="440" y="510" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">A schema dump can never exercise a data migration, because a data migration is a function of data.</text>
    <text x="440" y="530" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Every backfill you ship is untested unless the test database was migrated forward over rows that existed first.</text>
  </g>
</svg>
```

The measured drift goes **both ways at once.** The dump lacks `discount_cents`, which migration 005 added after the dump was regenerated. And it still carries `legacy_total`, which migration 005 dropped. Nobody was careless. A dump is a photograph of one machine at one instant, and the migrations kept moving. Note that it is not wrong about everything — five of seven columns match, the index matches — which is exactly why nobody audits it.

The column drift is the easy half. It fails loudly: `SELECT count(*) FROM orders WHERE discount_cents = 0` returns **400** against the migrated database and `no such column` against the dump. You find that on the first run and fix it. A schema diff in CI would catch it too ([Migrations & Schema Evolution](../../03-relational-databases/15-migrations-and-schema-evolution/), and [Zero-Downtime Schema Changes](../../10-infrastructure-and-deployment/13-zero-downtime-schema-changes/) for the production version).

The other half no schema comparison can find. Migration 004 added `currency` and backfilled it — for `status='paid'` rows only, which is the backfill everybody writes, because it is the rows you were thinking about. On the forward-migrated database, **300 of 400 orders still have `currency IS NULL`**, and any code that assumes the column is populated is a `NoneType` waiting to happen. On the dump-loaded database the same query reports **0 of 0**.

Look carefully at what that means. The dump database is **not passing the test. It has no rows to fail it.** A schema dump can never exercise a data migration, because a data migration is a function of data the dump does not contain. Every backfill you have ever shipped is untested unless your test database was migrated forward over rows that existed before the migration ran.

The practical rule that falls out: **run the real migrations in your test setup, once per suite, over a database that already has rows in it.** If they are too slow to run per suite, that is a signal to squash them, not to bypass them — and squashing is a deliberate, reviewed operation that keeps the migration path authoritative.

### Making it fast without making it a lie

The remaining costs are ordinary engineering, and the ordering matters more than any individual trick.

Rollback isolation is first because it is the largest single win — **95,959 row changes and 200 commits removed** from the 200-test run. Everything else is smaller.

Second: start **one container per suite**, not per test. A PostgreSQL container takes seconds to become ready and milliseconds to answer; paying that per test is the most common way a testcontainers setup becomes intolerable. The split is session-scoped container, function-scoped data.

Third: **one database per parallel worker.** This is the one people get wrong by trying to solve it with threads. Sharing one database between four workers is a data problem, not a scheduling problem: measured here, **4 of 4 workers were refused with `database is locked`** while another held a write transaction, against **0 of 4** when each worker had its own database file. And note what PostgreSQL would do differently — it would not error, it would *block*, which is worse in a suite, because the failure arrives minutes later as a timeout attributed to whichever test happened to be holding the lock. `pytest-xdist` gives each worker an id; use it in the database name.

Fourth: turn off durability. A test database that is destroyed after every run does not need to survive a power cut, so `fsync=off`, `full_page_writes=off`, `synchronous_commit=off` and a `tmpfs` data directory are all free. This is the one place where "unsafe" is genuinely the right answer, and it is worth being precise about why: the setting is unsafe because a crash can corrupt the database, and the cost of that here is one `docker compose up`.

Note what is *not* on this list. Reducing the number of integration tests is not a speed optimisation, it is a coverage decision wearing one as a disguise, and it should be argued on those terms with the cost matrix from [The Shape of a Test Suite](../02-the-shape-of-a-test-suite/) rather than smuggled in during a slow-CI week. The four steps above between them removed the great majority of the work in this lesson's measurements without removing a single assertion — do all four before anyone proposes deleting a test.

### When SQLite is genuinely the right answer

Being fair to the substitute, because "always use the real thing" is a rule with real exceptions.

**If you deploy SQLite, test on SQLite.** It is an excellent production database for single-writer workloads, and everything in section 1 then reads in the opposite direction.

**`STRICT` tables fix the largest single divergence.** Declaring `CREATE TABLE t(...) STRICT` (SQLite 3.37+) makes the engine enforce column types and reject `'12 units'` in an `INTEGER` column. It closes the type-affinity gap. It does not touch collation, `LIKE` case sensitivity, `NUMERIC` exactness, sequence behaviour, `GROUP BY` strictness, or the isolation model.

**An in-memory fake is the right tool when you are testing something else.** If the assertion is about pricing logic and the repository is scaffolding, a fake keeps the test fast and the failure localised. The discipline that makes this safe is the one from [Test Doubles](../04-test-doubles/): write **one contract test suite and run it against both the fake and the real engine.** The fake is then verified rather than assumed, and the moment it drifts, the shared suite goes red against the real thing. That is the only version of "use a fast substitute" that is not a bet.

And say the general form plainly, because it is the transferable idea: **a substitute is safe exactly when something independently verifies that it still matches.** Absent that, a substitute is a second implementation of somebody else's contract, maintained by you, verified by nobody — and the ten rows in section 1 are what that costs.

## Build It

[`code/integration_db.py`](code/integration_db.py) is one file, standard library only, seeded with `random.Random(11)`, and runs in about six seconds. It creates a temporary directory, drives real `sqlite3` connections inside it, and writes nothing anywhere else.

The first design decision is in the connection wrapper, and it is the one that makes the whole lesson reproducible:

```python
class Counted:
    """A sqlite3 connection that counts statements, row changes and commits."""

    def __init__(self, path: str) -> None:
        self.path = path
        # isolation_level=None turns OFF the sqlite3 module's implicit BEGIN, so
        # every transaction below is one that was typed on purpose.
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.stmts = 0
        self.commits = 0
        self.conn.set_trace_callback(self._trace)

    def _trace(self, sql: str) -> None:
        self.stmts += 1
        if sql.strip().upper().startswith(("COMMIT", "END")):
            self.commits += 1
```

Two things are load-bearing. `isolation_level=None` disables Python's `sqlite3` module's habit of opening transactions for you behind your back — a lesson about transaction boundaries cannot be written on a driver that invents them. And `set_trace_callback` gives an exact integer count of statements, which is what section 3 reports instead of seconds.

Each divergence is a function that *runs*, returning the string the engine actually produced, paired with PostgreSQL's documented answer and its SQLSTATE code. Nothing in the table is asserted; the left column is evidence:

```python
def _d_sequence(c: Counted) -> str:
    c.x("CREATE TABLE d9(id INTEGER PRIMARY KEY, v TEXT)")
    c.x("INSERT INTO d9(v) VALUES('first')")
    c.x("BEGIN")
    c.x("INSERT INTO d9(v) VALUES('rolled back')")
    c.x("ROLLBACK")
    c.x("INSERT INTO d9(v) VALUES('second')")
    return f"ids are {[r[0] for r in c.x('SELECT id FROM d9')]} — id 2 reused"
```

The rollback lie needs the code under test to be genuinely reasonable, so `ProductRepo` is written the way a repository is written — it owns its transaction — and the *only* difference between the broken and fixed runs is what `commit()` is wired to:

```python
    def create(self, sku: str) -> None:
        self.conn.execute("INSERT INTO products(sku) VALUES(?)", (sku,))
        if self.honest:
            # The test handed us a connection whose commit() is a savepoint
            # release, so "commit" means "publish to my caller" and the outer
            # transaction survives.
            self.conn.execute("RELEASE SAVEPOINT svc")
            self.conn.execute("SAVEPOINT svc")
        else:
            self.conn.execute("COMMIT")     # ends the TEST's transaction too
            self.conn.execute("BEGIN")
```

The concurrency section takes a schedule as a string and drives two connections through it. This is the whole technique for deterministic concurrency testing, and it is smaller than people expect — no threads, no sleeps, no retries-until-it-happens:

```python
    for op in schedule.split():
        who = int(op[1])
        conn = conns[who]
        if op[0] == "R":
            read[who] = conn.execute("SELECT bal, ver FROM acct WHERE id=1").fetchone()
            continue
        bal, ver = read[who]
        cur = conn.execute("UPDATE acct SET bal=?, ver=ver+1 WHERE id=1 AND ver=?",
                           (bal + DELTA[who], ver))
        if cur.rowcount == 0:                    # somebody moved it under us
            conflicts += 1
```

`cur.rowcount == 0` is the entire conflict-detection mechanism. The row is not where you left it, so your update matched nothing, so you know — exactly, not probabilistically — that you must re-read and retry.

Two smaller choices are worth calling out because they are what make the output trustworthy. The program prints no wall-clock value anywhere, so two runs on the same machine `diff` to nothing; the only line that varies between machines is the SQLite version in the header. And every database file lives inside a single `tempfile.TemporaryDirectory()`, which means the program can be run from anywhere, leaves nothing behind, and cannot accidentally read a database a previous run created — the same isolation property the lesson is about, applied to the lesson.

Section 6 models the migration-versus-dump problem rather than asserting it: five real migrations are applied in order to one database, with four hundred rows inserted *before* migration 004 runs so that its backfill has something to miss, while a second database is built from the schema statements a dump taken after 004 would have contained. Both are then queried. The drift is not configured; it falls out of the two construction paths.

Run it:

```bash
python3 phases/12-testing-and-quality/06-integration-testing-real-database/code/integration_db.py
```

```console
INTEGRATION TESTING AGAINST A REAL DATABASE — Phase 12, Lesson 06
seed=11. The database under test is stdlib sqlite3 3.53.1, in a temp dir.
READ SECTION 1 BEFORE YOU TRUST THAT SENTENCE.
== 1 · THE SUBSTITUTE-DATABASE FALLACY: THE DIVERGENCE TABLE ==
  TYPE AFFINITY  ·  INSERT '12 units' INTO an INTEGER column
     sqlite3     row stored, typeof='text', SUM(qty)=12.0
     postgres    [22P02] ERROR: invalid input syntax for type integer: "12 units"

  VARCHAR LENGTH  ·  INSERT 30 chars INTO VARCHAR(10)
     sqlite3     row stored, length(code)=30
     postgres    [22001] ERROR: value too long for type character varying(10)

  NUMERIC IS EXACT  ·  SUM over a NUMERIC(10,2) money column
     sqlite3     typeof='real', SUM=10.305000000000001
     postgres    typeof='numeric', SUM=10.31 (exact decimal, 10.005 -> 10.01)

  ...(five more divergences; the program prints all ten)...

  SEQUENCE GAPS  ·  id of the next row after a rolled-back INSERT
     sqlite3     ids are [1, 2] — id 2 reused
     postgres    ids are [1, 3] — the sequence is non-transactional

  READ SNAPSHOT  ·  re-read a row another txn committed
     sqlite3     same txn reads 100 then 100 — unchanged
     postgres    same txn reads 100 then 555 — READ COMMITTED re-reads
  --------------------------------------------------------------------------
  10 schema/query pairs; all 10 answered differently.
     5 PostgreSQL refuses outright. Your suite is green and
       production throws a 500 the first time that path runs.
     5 BOTH engines answer, with different answers. No error is
       raised anywhere, ever — the wrong number IS the output. Those
       five are money (SUM differs in the 3rd decimal), search (a LIKE
       that matches here and not there), ordering (page 1 holds
       different rows), identity (the next id) and isolation.

  THE CONTROL — three NULLs into a UNIQUE column:
     sqlite3     3 NULL rows accepted
     postgres    3 NULL rows accepted (NULLS DISTINCT is the default)
  Identical. This is the divergence everybody names first and it is not
  one: both follow SQL:2016 and treat NULLs as distinct in a UNIQUE
  index. The differences that bite are never the ones you worry about.
== 2 · WHAT ONLY A REAL DATABASE ENFORCES ==
  Ten rules this schema states. The fake re-implements the ones its
  author thought of; the engine enforces the ones it was told.

  ...(ten declared rules: six refusals, then four values)...

  fake repository .......  2/10 rules
  real SQL engine ....... 10/10 rules
  The fake is not lazy. Every rule it missed is one its author never had
  to think about, because the schema was thinking about it for them. That
  is the bug class integration tests exist for — not 'more code per test',
  but the rules that live outside your process.
== 3 · TEST ISOLATION: FOUR STRATEGIES OVER 200 TESTS ==
  Fixture: 6 tables, 3 indexes, 240 seed rows. 200 tests.
  Cost is counted in STATEMENTS, ROW CHANGES and COMMITS — the physical
  work. Seconds are not printed: they differ on every machine and would
  make this program non-reproducible. These integers do not.

     strategy               stmts/test   row changes/test   commits   bytes copied/test
     recreate schema          260.0              242.1       200                0
     truncate + reseed        251.0              481.9       200                0
     transaction rollback       5.0                2.1         0                0
     template copy              3.0                2.1         0           40,960

     recreate schema       isolates everything
     truncate + reseed     isolates committed rows
     transaction rollback  isolates uncommitted writes only
     template copy         isolates everything, incl. schema
  --------------------------------------------------------------------------
  recreate schema         52.0x the statements and  115.3x the row changes of rollback
  truncate + reseed       50.2x the statements and  229.5x the row changes of rollback
  transaction rollback  5 statements per test, 0 commits all run, 0 bytes copied

  Rollback is 54x cheaper than truncate and 56x cheaper than recreate under
  these constants, and the gap widens with fixture size: rollback's cost
  does not depend on how big your seed data is, and the others' do.
== 4 · THE ROLLBACK LIE ==
  A 200-test suite, every test wrapped in BEGIN ... ROLLBACK.
  3 exercise a repository whose create() calls commit(), because in
  production that method owns its transaction and nobody wrote it wrong.
  3 assert the catalogue is empty, at positions 40, 90, 140.

  IN FILE ORDER (committing tests last, as they were written):
     failures 0      rows that survived the rollback 3
     Green. Shipped. The rollback did nothing at all for those 3 tests:
     COMMIT ended the transaction the harness opened, so the ROLLBACK
     that followed had no transaction left to undo.

  SHUFFLED 400 TIMES (what pytest-randomly does every run):
     runs that went green .........   22/400 ( 5.50%)
     runs that caught it ..........  378/400 (94.50%)
     mean failing tests when caught 2.41      worst run 3
     P(three shuffled runs ALL miss it) 0.02%
     Not rare — CONDITIONAL. In file order it is green 100% of the time,
     for ever, because file order is one permutation and it happens to
     be a safe one. Shuffling finds it on the first run 94.5% of
     the time, for one line of configuration.

  THE FIX — give the code under test a connection whose commit() is a
  SAVEPOINT release, so the outer transaction is still there to undo:
     file order:  failures 0   rows survived 0
     shuffled:    400/400 runs green (100.00%)
  Same suite, same tests, same three repositories still calling commit().
  Nothing about the production code changed. The seam moved.
== 5 · A LOST UPDATE, DETERMINISTICALLY ==
  One row, balance 100. T1 adds 10, T2 adds 5, both read-modify-write in
  the way every ORM writes it. The correct answer is 115, always.
  Two connections driven step by step from one thread — no threads, no
  sleeps, no luck. Every legal interleaving, replayed for real:

     schedule            naive           version column              kind
     R1 W1 R2 W2       115 ok          115 ok                      serial
     R2 W2 R1 W1       115 ok          115 ok                      serial
     R1 R2 W1 W2       105 LOST 10     115 ok, 1 conflict caught   interleaved
     R1 R2 W2 W1       110 LOST 5      115 ok, 1 conflict caught   interleaved
     R2 R1 W1 W2       105 LOST 10     115 ok, 1 conflict caught   interleaved
     R2 R1 W2 W1       110 LOST 5      115 ok, 1 conflict caught   interleaved
  4 of 6 interleavings lose an update. 2 of 6 are serial, and the serial
  two are exactly the two a normal test explores — because a normal test
  runs one transaction, then the next. The test passes. It has proved
  nothing about the 4 schedules that lose money. With a version
  column, 6/6 end at 115: the UPDATE that finds rowcount 0 knows it
  was overwritten and retries. Nothing is guessed and nothing sleeps.
== 6 · MIGRATE FORWARD vs LOAD A DUMP ==
  Two ways to get a schema into a test database. They do not converge.

     migrated forward   5 migrations applied: 001, 002, 003, 004, 005
     loaded from dump   schema.sql, regenerated at 004

  ...(the column drift, in both directions)...

  AND THE BUG NEITHER SCHEMA COMPARISON FINDS. Migration 004 backfilled
  currency for status='paid' rows only. Everything else is still NULL:
     migrated forward   300 of 400 orders have currency IS NULL
     loaded from dump   0 of 0 orders have currency IS NULL
  The dump database is not passing this test. It has no rows to fail it.
  A schema dump can never exercise a data migration, because a data
  migration is a function of data the dump does not contain. Every
  backfill you ship is untested unless the test database was migrated
  forward over rows that existed before the migration ran.
  THE ORDER TO DO IT IN, by what each step removes:
     1. transaction rollback per test   95,959 row changes and 200 commits
     2. one container started per SUITE, not per test
     3. one database per worker         4/4 lock errors
     4. fsync off, tmpfs storage        the disk — safe ONLY because
        losing the entire test database costs you nothing
```

The sections that should change how you build things are 1, 4 and 5. **Section 1** is the scale of the substitution problem: ten for ten, with five silent. **Section 4** is the one that will be true of your suite today if you use rollback isolation and any repository in your codebase commits — green in file order for ever, caught by 94.50% of shuffles. **Section 5** is the argument for writing one deliberately interleaved test: four of six schedules lose money and your suite explores neither of them.

## Use It

**Start the real engine, once per suite.** `testcontainers-python` is the shortest path, and the fixture layering is the part that matters — a session-scoped container, function-scoped data:

```python
# conftest.py
import pytest
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer

@pytest.fixture(scope="session")
def pg_url():
    # Pin the image to the MAJOR VERSION YOU DEPLOY. "postgres:latest" is how
    # you find out about a breaking change from your test suite.
    with PostgresContainer("postgres:16.4-alpine") as pg:
        yield pg.get_connection_url()

@pytest.fixture(scope="session")
def engine(pg_url):
    eng = create_engine(pg_url, pool_pre_ping=True)
    run_migrations(eng)          # the REAL migrations, forward, once
    seed_reference_data(eng)     # countries, currencies — things migrations own
    yield eng
    eng.dispose()

@pytest.fixture()
def db(engine):
    """Function-scoped: a transaction that is never committed."""
    conn = engine.connect()
    txn = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    session.close()
    txn.rollback()               # everything the test did, gone
    conn.close()
```

`join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0) is the fix from section 4, and it is a single keyword argument. It makes the session's `commit()` a `RELEASE SAVEPOINT` inside the outer transaction the fixture owns, so code under test that legitimately commits no longer escapes your rollback. On SQLAlchemy 1.4 the equivalent is the `after_transaction_end` event that restarts a nested transaction; it is fiddlier and does the same thing. **If you use rollback isolation and have not set this, assume you have section 4's bug.** The cheapest way to find out is to turn on shuffling and read the first red build.

Two container flags are worth the trouble, because they turn the biggest remaining cost off:

```python
PostgresContainer("postgres:16.4-alpine").with_command(
    "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off "
    "-c max_connections=200"
).with_tmpfs({"/var/lib/postgresql/data": "rw,size=512m"})
```

That is the projection in section 3 made real: the 200 commits stop touching a disk. It is safe here and nowhere else, because the entire database is disposable.

**Run migrations, do not load a dump.** With Alembic, in the session fixture:

```python
from alembic import command
from alembic.config import Config

def run_migrations(engine):
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(cfg, "head")
```

Add a CI job that runs `alembic upgrade head` against a database **restored from a production-shaped backup with rows in it**, then asserts the invariants your backfills were supposed to establish. That is the only test that exercises a data migration, and section 6 is why: on a schema-only database the assertion passes because there is nothing to check.

**One database per worker.** With `pytest-xdist`, `PYTEST_XDIST_WORKER` is `gw0`, `gw1`, … Use it, and use PostgreSQL's template feature so each one is a file copy rather than a migration run:

```python
@pytest.fixture(scope="session")
def worker_db(pg_url, worker_id):
    name = f"test_{worker_id}"          # test_gw0, test_gw1, ...
    with connect(pg_url, dbname="postgres", autocommit=True) as c:
        c.execute(f'DROP DATABASE IF EXISTS "{name}"')
        # TEMPLATE copies the seeded master at file speed. It requires that no
        # other session is connected to the template — the classic 55006 error.
        c.execute(f'CREATE DATABASE "{name}" TEMPLATE test_master')
    yield url_for(name)
```

`CREATE DATABASE ... TEMPLATE` fails with `55006 object_in_use` if anything is connected to the template, which in practice means your session fixture must close its own connection to the master before workers start. Budget an hour for that the first time.

`pytest-postgresql` is the lighter alternative: it starts a real `postgres` from your `PATH` rather than a container, which is faster to boot and requires PostgreSQL installed on every machine and in CI. It offers the same fixture shapes, including `postgresql_proc` (session) and `postgresql` (function). Choose it when you control the runners and want no Docker dependency; choose testcontainers when you want the *exact* image you deploy and CI parity.

In CI, Docker Compose service containers do the same job with less Python:

```yaml
# .github/workflows/test.yml
services:
  postgres:
    image: postgres:16.4-alpine
    env: { POSTGRES_PASSWORD: test, POSTGRES_DB: test }
    # Without this the first test connects before the server is ready and you
    # get a flake that only happens on cold runners.
    options: >-
      --health-cmd "pg_isready -U postgres" --health-interval 5s
      --health-timeout 5s --health-retries 10
    ports: ["5432:5432"]
```

The health check is not optional. A service container that is *running* is not a database that is *accepting connections*, and the gap between the two is where a whole genre of CI flake lives ([CI/CD Pipelines](../../10-infrastructure-and-deployment/10-ci-cd-pipelines/), [Health Checks & Probes](../../09-logging-monitoring-and-observability/08-health-checks-and-probes/)).

**What to actually pick, in this order.** One: a container of the exact image you deploy, session-scoped. Two: real migrations run forward in that fixture, plus a separate CI job that migrates a data-bearing restore. Three: transaction-rollback isolation with `join_transaction_mode="create_savepoint"`. Four: `fsync=off` and `tmpfs`. Five: `pytest-xdist` with one template-cloned database per worker. Six: `pytest-randomly` turned on permanently, because it is what turns section 4's bug from invisible into a first-run failure. Then, and only then, write one test that drives two connections through an interleaving on purpose — it will be the only test you have that could ever fail for the right reason.

## Think about it

1. Section 1 measured `SUM` over a `NUMERIC(10,2)` column as `10.305000000000001` on SQLite and `10.31` on PostgreSQL. Your team's fix is to round every money value to two decimals in the application before writing and after reading. Trace what that does and does not fix for each of the ten divergences, and say which of them it makes *harder* to detect.
2. The control row showed that multiple `NULL`s in a `UNIQUE` column behave identically in both engines — the one divergence everybody expects, and it is not one. Given that, what is wrong with the strategy "keep a documented list of the differences between our test database and production and check new queries against it"? What would you have to be able to do for that strategy to work?
3. Section 4's suite was green in file order and caught by 94.50% of shuffles. Suppose your team turns on `pytest-randomly` and the next morning there are eleven failures across four unrelated files. Rank the possible explanations, and say precisely what you would run first to separate "we just found eleven real bugs" from "shuffling broke something".
4. The version-column fix took the 8-worker run from 25/200 to exactly 200/200, at the cost of 175 retries — one retry for almost every increment. At what contention level does this stop being the right answer, what would you measure to know you had reached it, and what would you replace it with?
5. Section 6 showed the dump-loaded database reporting `0 of 0` rows with a NULL currency while the migrated one reported `300 of 400`. Your CI already runs a schema diff between the dump and `alembic upgrade head`, and it is green. Explain why it is green, and design the smallest additional check that would have caught the backfill bug — including what data it needs and where that data comes from.

## Key takeaways

- **A test database that is not your production engine tests a different program.** Ten schema-and-query pairs, run live: **all ten returned different answers.** Five PostgreSQL refuses outright — green suite, `500` in production. The other **five are answered by both engines with different answers and no error anywhere**, and they are the ones that matter: money (`SUM` `10.305000000000001` vs `10.31`), search (`LIKE 'ADA%'` matching 1 row vs 0), ordering (page 1 = `['Bob','Zoe']` vs `['ada','Bob']`), identity (next id 2 vs 3) and isolation (a re-read seeing 100 vs 555).
- **The divergences that bite are never the ones on your list.** The control — three `NULL`s in a `UNIQUE` column — is the difference everyone names first, and it is identical in both engines under SQL:2016. You cannot maintain a list of the ways two engines differ; you can only stop having two engines.
- **The schema is where the rules live, and a double cannot hold them.** The same ten declared rules: a hand-written in-memory fake enforced **2 of 10**, the real engine **10 of 10**. The eight it missed — `NOT NULL`, two `CHECK`s, the foreign key, a partial unique index, `ON DELETE CASCADE`, upsert, `RETURNING` — are rules its author never had to think about because the schema was thinking about them.
- **Transaction rollback is the isolation strategy to default to, and the margin is structural.** Measured over 200 tests: **5 statements and 2.1 row changes per test with 0 commits**, against 251 and 482 with 200 commits for truncate-and-reseed — **50× fewer statements, 230× fewer row changes, 96,379 row changes reduced to 420.** It re-seeds nothing, so unlike every other strategy its cost does not grow with your fixture.
- **Rollback is also the only strategy that can silently do nothing at all.** Three tests in two hundred whose repository called `commit()` left **3 rows behind with 0 failures reported**, and the suite stays green in file order for ever. Shuffling caught it in **378 of 400 runs (94.50%)**; the chance three shuffled runs all miss it is **0.02%**. The fix is one keyword — make `commit()` a savepoint release — and it took the suite to **0 rows leaked and 400/400 green** without changing a line of production code.
- **A serial test proves nothing about concurrency, and that is provable rather than rhetorical.** Of the six legal interleavings of two read-modify-write transactions over one row, **four lose an update (105, 110, 105, 110 against a correct 115)** — and the two that pass are exactly the two a normal test explores. At 8 workers the naive version ended at **25 of 200**. A version column with `WHERE ver = ?` and a `rowcount == 0` check took all six schedules to 115 and the 8-worker run to **exactly 200, with 175 retries**.
- **A schema dump can never exercise a data migration.** The dump drifted **both ways at once** — missing `discount_cents`, still carrying `legacy_total`. But the column drift is the loud half; migration 004's partial backfill left **300 of 400 orders with `currency IS NULL`** on the migrated database, while the dump-loaded one reported **0 of 0**. It is not passing that test — it has no rows to fail it.
- **Parallelism in an integration suite is a data problem, not a thread problem.** Four workers sharing one database were refused **4 of 4** times while another held a write transaction; one database each gave **0 of 4**. PostgreSQL makes this worse rather than better by blocking instead of erroring, so the failure arrives later and lands on the wrong test.
- **A substitute is safe exactly when something independently verifies that it still matches.** `STRICT` tables close SQLite's type-affinity gap and touch none of the other nine divergences. If you want a fast in-memory fake, the price is one contract test suite run against both it and the real engine — otherwise a substitute is a second implementation of someone else's contract, maintained by you and verified by nobody.

Next: [Test Data & Fixtures: Factories, Builders & the Shared-State Trap](../07-test-data-and-fixtures/) — you now have a real database per test and no idea what should be in it; the 4,300-line shared seed is the next thing that will make nineteen unrelated tests fail at once.
