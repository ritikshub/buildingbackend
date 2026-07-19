# Test Data & Fixtures: Factories, Builders & the Shared-State Trap

> Someone adds a third order to `user_id = 1` so they can test pagination. **52 of 240 unrelated tests go red** — 21.7% of the suite — and not one line of the code under test changed. Rebuild the same 240 tests on factories and the identical change breaks **0**. Then the quieter number: the `random.randint(1, 10**6)` you use for a "unique" test email gives you a 1-in-100 chance of a red build at **143 tests**, not at five thousand, and at 5,000 tests it collides **99.999634%** of the time. Both numbers come out of one 4,374-line seed file and one program you can run.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Integration Testing Against a Real Database](../06-integration-testing-real-database/), [Anatomy of a Unit Test](../03-anatomy-of-a-unit-test/)
**Time:** ~70 minutes

## The Problem

**09:12.** Priya picks up a two-line ticket: *orders list should paginate at 25 per page*. The endpoint already works; it just needs a test. She opens the integration suite, finds the fixture everyone uses, and needs a user with more than two orders.

`fixtures/seed.sql` is 4,374 lines long. It was generated three years ago by someone who has since left. It has no comments beyond the table names, and its first meaningful row is this one:

```sql
INSERT INTO users (id, email, username, role, status, country, city, credit_limit_cents, ...)
VALUES (1, 'admin@example.com', 'admin', 'admin', 'active', 'DE', 'Dresden', 250000, ...);
```

User 1 is an admin. User 1 is active. User 1 is in Germany, has a credit limit, has an address, and has exactly two orders. User 1 satisfies every precondition anyone has ever needed, which is precisely why **116 of the suite's 240 tests are bound to it.** Priya does not know that, because no test says so.

**09:31.** She adds one line to the seed — a third order for user 1 — and one test for page two.

**09:34.** The suite comes back. **52 failures.**

**09:35.** She reads the first one. `test_invoice_total_matches_orders` asserts that an invoice total equals the sum of a user's orders. It has nothing to do with pagination. It is red because the sum changed.

**09:41.** The tenth one is `test_first_order_gets_welcome_discount`, and it is *green*, which is somehow worse: it depends on user 1's oldest order, and her new order is the newest, so it survived by luck rather than by design. Nobody wrote that down either.

**10:20.** She has read 52 stack traces. Every one is a test that was passing for reasons its own author never stated. She reverts her line, writes the pagination test against a *different* user — user 47, who happens to have three orders — and moves on. The suite is green. Nothing has been fixed; one more test has just been welded to one more accidental row.

The failure here is not the seed file's size. 4,296 of those 4,353 rows are inert and cost nothing. The failure is that **a test's real precondition lives somewhere the test does not point at**, so the only way to know what a change will break is to make it and count the corpses.

> **A test should state, in its own body, exactly the data its assertion depends on — and nothing else.**

Everything below is an attempt to measure what that sentence is worth.

## The Concept

### The shared-fixture trap: every test requires everything

A **fixture** is the data a test needs in place before it can run. A **shared fixture** is one set of that data, loaded once, used by everybody — the `seed.sql`, the `conftest.py` that populates a database at session scope, the golden JSON everyone imports.

The trap is not that the data is shared. It is that **sharing makes the requirement invisible.** Every test declares two different things, and only one of them is written down:

- its **preconditions** — what the data must satisfy for the test to run at all ("a user with the admin role");
- its **dependencies** — what its assertion actually reads ("that user's role", "the sum of their orders").

With a factory, the preconditions are the first line of the test. With a shared seed, they are a `user_id = 1` and a promise. `Build It` generates both worlds from the *same* 240-test suite — same archetypes, same assertions, same seed — and changes one field in each:

```text
  one change to the fixture                       shared  factory
  user 1 role: admin -> member                        18        0
  add a 3rd order to user 1 (to test pagination)      52        0
  product 1 price: 550 -> 590 cents                   11        0
  DE VAT rate: 19.0 -> 20.0 (reference data)          33       33
```

The first three rows are the trap, priced. The fourth row is the honest limit, and it is worth more than the first three: **DE's VAT rate breaks 33 tests in both worlds**, because no factory has any business inventing a country's tax rate. Reference data is genuinely global, and a lesson that pretended otherwise would be selling something.

Notice also how the seed got to 4,374 lines. It was not written that way. When a test needed a precondition no existing row satisfied, someone appended a row — the program did this 15 times over 240 tests, because that is what happens. A seed file is not designed; it accretes, one unfindable row at a time.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 604" width="100%" style="max-width:840px" role="img" aria-label="Two worlds holding the same 240-test suite. On the left a shared seed.sql of 4,374 lines and 4,353 rows, drawn as a stack of grey rows with one red row — user 1 — receiving converging lines from ten test boxes, because 116 of the 240 tests bound to it. On the right a factory world where each test owns a private green data row and nothing crosses, with a single shared amber bar for the VAT reference rate read by 33 tests. A table underneath gives the measured blast radius of four one-field changes: 18, 52 and 11 failing tests in the shared world against 0 in the factory world, and 33 against 33 for the VAT rate, which is reference data and breaks both worlds equally.">
  <defs><marker id="p12-07-a1" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#0fa07f"/></marker></defs> <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same 240 tests. One field changes. Two very different mornings.</text>
  <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">measured, seed 1207 — the suite, the archetypes and the change are identical on both sides</text> <rect x="24" y="60" width="408" height="380" rx="11" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/> <text x="40" y="80" font-size="11.5" font-weight="700" fill="#7c5cff">SHARED SEED WORLD</text>
  <text x="40" y="96" font-size="8.5" fill="currentColor" opacity="0.7">fixtures/seed.sql — 4,374 lines, 4,353 rows, 553 KiB</text> <rect x="40" y="104" width="140" height="252" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.6"/> <rect x="48" y="112" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="128" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="144" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/>
  <rect x="48" y="160" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="192" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="208" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="224" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="240" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/>
  <rect x="48" y="256" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="272" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="288" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="304" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="320" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/>
  <rect x="48" y="336" width="124" height="6" rx="2" fill="#7f7f7f" fill-opacity="0.35"/> <rect x="48" y="176" width="124" height="10" rx="3" fill="#d64545" fill-opacity="0.55" stroke="#d64545" stroke-width="1.4"/> <text x="54" y="184" font-size="7.5" font-weight="700" fill="#d64545">user[1] — the god row</text> <path d="M248 120 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 144 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/>
  <path d="M248 168 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 192 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 216 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 240 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 264 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/>
  <path d="M248 288 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 312 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <path d="M248 336 L 182 181" fill="none" stroke="#d64545" stroke-width="1.1" stroke-opacity="0.5"/> <rect x="248" y="110" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/>
  <rect x="248" y="134" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="158" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="182" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="206" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/>
  <rect x="248" y="230" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="254" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="278" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="248" y="302" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/>
  <rect x="248" y="326" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <text x="336" y="124" font-size="8" text-anchor="middle" fill="#3553ff" font-weight="700">test_admin_can_delete_order</text> <text x="336" y="220" font-size="8" text-anchor="middle" fill="#3553ff">test_orders_page_two_empty</text> <text x="336" y="340" font-size="8" text-anchor="middle" fill="#3553ff">... 240 tests in total</text>
  <text x="40" y="378" font-size="9.5" fill="currentColor" opacity="0.9">116 of 240 tests (48.3%) bound to user 1.</text> <text x="40" y="392" font-size="9.5" fill="currentColor" opacity="0.9">The suite touched 53 distinct users.</text> <text x="40" y="410" font-size="9.5" fill="#d64545" font-weight="700">57 of 4,353 rows (1.31%) are load-bearing,</text> <text x="40" y="424" font-size="9.5" fill="#d64545" font-weight="700">and no test tells you which 57.</text>
  <rect x="448" y="60" width="408" height="380" rx="11" fill="#7f7f7f" fill-opacity="0.05" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.4"/> <text x="464" y="80" font-size="11.5" font-weight="700" fill="#0fa07f">FACTORY WORLD</text> <text x="464" y="96" font-size="8.5" fill="currentColor" opacity="0.7">55 lines of definitions — and 0 rows until a test asks</text> <rect x="466" y="110" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/>
  <path d="M546 120 L 566 120" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="110" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="134" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 144 L 566 144" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/>
  <rect x="570" y="134" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="158" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 168 L 566 168" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="158" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/>
  <rect x="466" y="182" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 192 L 566 192" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="182" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="206" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/>
  <path d="M546 216 L 566 216" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="206" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="230" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 240 L 566 240" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/>
  <rect x="570" y="230" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="254" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 264 L 566 264" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="254" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/>
  <rect x="466" y="278" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 288 L 566 288" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="278" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="302" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/>
  <path d="M546 312 L 566 312" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/> <rect x="570" y="302" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <rect x="466" y="326" width="80" height="20" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.3"/> <path d="M546 336 L 566 336" fill="none" stroke="#0fa07f" stroke-width="1.3" marker-end="url(#p12-07-a1)"/>
  <rect x="570" y="326" width="176" height="20" rx="5" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff" stroke-width="1.3"/> <text x="506" y="124" font-size="8" text-anchor="middle" fill="#0fa07f" font-weight="700">its own user</text> <text x="506" y="220" font-size="8" text-anchor="middle" fill="#0fa07f">its own user</text> <text x="658" y="124" font-size="8" text-anchor="middle" fill="#3553ff" font-weight="700">user(role='admin')</text>
  <text x="658" y="220" font-size="8" text-anchor="middle" fill="#3553ff">user(orders=2)</text> <text x="658" y="340" font-size="8" text-anchor="middle" fill="#3553ff">... 240 tests, 240 users</text> <rect x="466" y="360" width="356" height="26" rx="6" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="1.6"/> <text x="644" y="377" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">vat[DE].rate — the one cell still shared, by 33 tests</text>
  <text x="464" y="410" font-size="9.5" fill="#0fa07f" font-weight="700">266 cells read, exactly 1 of them shared.</text> <text x="464" y="424" font-size="9.5" fill="currentColor" opacity="0.9">That one is reference data. It is the honest floor.</text> <rect x="24" y="454" width="832" height="106" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-width="1.5"/> <text x="40" y="474" font-size="10" font-weight="700" fill="#3553ff">TESTS THAT FAIL AFTER ONE FIELD CHANGES</text>
  <text x="344" y="474" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">shared</text> <text x="432" y="474" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">factory</text> <text x="40" y="492" font-size="9.5" fill="currentColor">user 1 role: admin -> member</text> <text x="344" y="492" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">18</text>
  <text x="432" y="492" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0</text> <text x="40" y="509" font-size="9.5" fill="currentColor">add a 3rd order to user 1</text> <text x="344" y="509" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">52</text> <text x="432" y="509" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0</text> <text x="40" y="526" font-size="9.5" fill="currentColor">product 1 price: 550 -> 590</text>
  <text x="344" y="526" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">11</text> <text x="432" y="526" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0</text> <text x="40" y="543" font-size="9.5" fill="#e0930f">DE VAT rate: 19.0 -> 20.0</text> <text x="344" y="543" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">33</text> <text x="432" y="543" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">33</text>
  <text x="472" y="492" font-size="9.5" fill="currentColor" opacity="0.9">the worst one-field change costs 52 of 240 tests:</text> <text x="472" y="506" font-size="9.5" fill="currentColor" opacity="0.9">21.7% of the suite red, with nothing wrong in the</text> <text x="472" y="520" font-size="9.5" fill="currentColor" opacity="0.9">code under test.</text> <text x="472" y="538" font-size="9.5" fill="#e0930f" font-weight="700">the amber row is the honest limit: reference data</text>
  <text x="472" y="551" font-size="9.5" fill="#e0930f" font-weight="700">is shared by construction, in both worlds.</text> <text x="440" y="582" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A factory does not make data cheaper. It makes each test's real precondition visible,</text> <text x="440" y="598" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">which is what turns 52 mystery failures into 0.</text> </g>
</svg>
```

### The coupling matrix: the cells nobody can ever change

"How coupled is our fixture?" is answerable. Take every assertion in the suite, resolve what cell of the seed it reads — a cell being one `(entity, id, field)` — and count.

```text
    #  cell in the shared seed           tests  % of suite   verdict
    1  user[1].orders.sum_total             28      11.7%   frozen — you cannot change it
    2  user[1].role                         18       7.5%   read all 10+ tests first
    3  user[1].credit_limit_cents           16       6.7%   read all 10+ tests first
    4  user[1].orders.count                 14       5.8%   read all 10+ tests first
    5  product[1].price                     11       4.6%   read all 10+ tests first
```

Seven of the top ten cells belong to one row. The top five carry **87 of 298 reads — 29.2% of everything the suite depends on.** This is a power law, and the head of a power law in a fixture file is a list of values that are now permanently frozen: not by policy, not by a comment, but by the arithmetic of who will be paged when they change.

The distribution is the argument:

```text
       distribution                        shared   factory
       distinct cells the suite reads          92       266
       total reads across the suite           298       298
       most tests reading one SEED cell        28         1
       seed cells read by 2+ tests             34         0
       seed cells read by 10+ tests             6         0
       reads of the one reference cell         33        33
```

Both worlds do the same **298 reads** — the suite asserts the same things either way. The shared world concentrates them onto 92 cells; the factory world spreads them across 266, of which **exactly one is shared by more than one test**, and that one is the VAT rate. That is not a rounding difference. It is the difference between a suite where any change requires a survey and a suite where a change to a test's data affects that test.

The related number is the one people reach for first and it is a red herring: only **57 of 4,353 seeded rows (1.31%) are load-bearing**. The other 4,296 are ballast. Deleting the ballast would feel productive and would change nothing, because ballast is free. The cost is entirely in the head of the distribution.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="A ranked bar chart of the ten cells of the shared seed that the 240-test suite reads most. The top cell, user one's order total, is read by 28 tests or 11.7 percent of the suite; then user one's role at 18, credit limit at 16, order count at 14, product one's price at 11, user one's country at 11, order list at 10, user two's status at 10, first order id at 9 and address one's city at 8. Seven of the ten belong to a single row, user 1. A panel underneath records that 57 of 4,353 seeded rows are load-bearing, that 34 seed cells are read by two or more tests in the shared world against 0 in the factory world, and that the top five cells carry 29.2 percent of every read.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The columns nobody can ever change again</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">how many of the 240 tests read each cell of the shared seed — seven of the top ten are one row</text>
  <text x="290" y="66" font-size="9" text-anchor="end" fill="currentColor" opacity="0.6" font-weight="700">CELL (entity, id, field)</text> <text x="300" y="66" font-size="9" fill="currentColor" opacity="0.6" font-weight="700">TESTS READING IT</text> <path d="M300 88 L 300 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="300" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">0</text>
  <path d="M375 88 L 375 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="375" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">5</text> <path d="M450 88 L 450 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="450" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">10</text>
  <path d="M525 88 L 525 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="525" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">15</text> <path d="M600 88 L 600 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="600" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">20</text>
  <path d="M675 88 L 675 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="675" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">25</text> <path d="M750 88 L 750 342" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="750" y="82" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.55">30</text> <text x="290" y="106" font-size="10" text-anchor="end" fill="currentColor">user[1].orders.sum_total</text>
  <rect x="300" y="94" width="420" height="17" rx="3" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.3"/> <text x="728" y="106" font-size="10" font-weight="700" fill="#d64545">28</text> <text x="754" y="106" font-size="9" fill="currentColor" opacity="0.6">11.7% of the suite</text> <text x="290" y="131" font-size="10" text-anchor="end" fill="currentColor">user[1].role</text>
  <rect x="300" y="119" width="270" height="17" rx="3" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.3"/> <text x="578" y="131" font-size="10" font-weight="700" fill="#d64545">18</text> <text x="604" y="131" font-size="9" fill="currentColor" opacity="0.6">7.5% of the suite</text> <text x="290" y="156" font-size="10" text-anchor="end" fill="currentColor">user[1].credit_limit_cents</text>
  <rect x="300" y="144" width="240" height="17" rx="3" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.3"/> <text x="548" y="156" font-size="10" font-weight="700" fill="#d64545">16</text> <text x="574" y="156" font-size="9" fill="currentColor" opacity="0.6">6.7% of the suite</text> <text x="290" y="181" font-size="10" text-anchor="end" fill="currentColor">user[1].orders.count</text>
  <rect x="300" y="169" width="210" height="17" rx="3" fill="#d64545" fill-opacity="0.45" stroke="#d64545" stroke-width="1.3"/> <text x="518" y="181" font-size="10" font-weight="700" fill="#d64545">14</text> <text x="544" y="181" font-size="9" fill="currentColor" opacity="0.6">5.8% of the suite</text> <text x="290" y="206" font-size="10" text-anchor="end" fill="currentColor">product[1].price</text>
  <rect x="300" y="194" width="165" height="17" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/> <text x="473" y="206" font-size="10" font-weight="700" fill="#e0930f">11</text> <text x="499" y="206" font-size="9" fill="currentColor" opacity="0.6">4.6% of the suite</text> <text x="290" y="231" font-size="10" text-anchor="end" fill="currentColor">user[1].country</text>
  <rect x="300" y="219" width="165" height="17" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/> <text x="473" y="231" font-size="10" font-weight="700" fill="#e0930f">11</text> <text x="499" y="231" font-size="9" fill="currentColor" opacity="0.6">4.6% of the suite</text> <text x="290" y="256" font-size="10" text-anchor="end" fill="currentColor">user[1].orders.list</text>
  <rect x="300" y="244" width="150" height="17" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/> <text x="458" y="256" font-size="10" font-weight="700" fill="#e0930f">10</text> <text x="484" y="256" font-size="9" fill="currentColor" opacity="0.6">4.2% of the suite</text> <text x="290" y="281" font-size="10" text-anchor="end" fill="currentColor">user[2].status</text>
  <rect x="300" y="269" width="150" height="17" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.3"/> <text x="458" y="281" font-size="10" font-weight="700" fill="#e0930f">10</text> <text x="484" y="281" font-size="9" fill="currentColor" opacity="0.6">4.2% of the suite</text> <text x="290" y="306" font-size="10" text-anchor="end" fill="currentColor">user[1].orders.first_id</text>
  <rect x="300" y="294" width="135" height="17" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f" stroke-width="1.3"/> <text x="443" y="306" font-size="10" font-weight="700" fill="#7f7f7f">9</text> <text x="469" y="306" font-size="9" fill="currentColor" opacity="0.6">3.8% of the suite</text> <text x="290" y="331" font-size="10" text-anchor="end" fill="currentColor">address[1].city</text>
  <rect x="300" y="319" width="120" height="17" rx="3" fill="#7f7f7f" fill-opacity="0.30" stroke="#7f7f7f" stroke-width="1.3"/> <text x="428" y="331" font-size="10" font-weight="700" fill="#7f7f7f">8</text> <text x="454" y="331" font-size="9" fill="currentColor" opacity="0.6">3.3% of the suite</text> <rect x="24" y="356" width="832" height="76" rx="10" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff" stroke-width="1.5"/>
  <text x="40" y="375" font-size="10.5" font-weight="700" fill="#7c5cff">the same suite, measured in both worlds</text> <text x="500" y="375" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">shared seed</text> <text x="600" y="375" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">factories</text> <text x="40" y="393" font-size="9.5" fill="currentColor" opacity="0.9">distinct cells the suite reads</text>
  <text x="500" y="393" font-size="9.5" font-weight="700" text-anchor="end" fill="currentColor">92</text> <text x="600" y="393" font-size="9.5" font-weight="700" text-anchor="end" fill="currentColor">266</text> <text x="40" y="409" font-size="9.5" fill="currentColor" opacity="0.9">seed cells read by 2 or more tests</text> <text x="500" y="409" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">34</text> <text x="600" y="409" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0</text>
  <text x="40" y="425" font-size="9.5" fill="currentColor" opacity="0.9">most tests reading one seed cell</text> <text x="500" y="425" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">28</text> <text x="600" y="425" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">1</text> <text x="640" y="393" font-size="9" fill="currentColor" opacity="0.75">top 5 cells = 29.2% of all reads</text>
  <text x="640" y="409" font-size="9" fill="currentColor" opacity="0.75">57 of 4,353 rows load-bearing</text> <text x="640" y="425" font-size="9" fill="currentColor" opacity="0.75">the other 4,296 are ballast</text> <text x="440" y="454" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Ballast is free. The head of this distribution is not: 28 tests are pinned to one number that no test mentions.</text> </g>
</svg>
```

### Object mothers, builders and factories

Three patterns solve "get me a user", and the differences show up only at scale.

An **object mother** is a named, fully-formed specimen: `admin_user()`, `suspended_user()`, `admin_user_on_pro_with_mfa()`. Its name is its precondition set. That is its whole appeal — and its whole problem, because a suite needs one mother per *distinct* precondition set, and real tests combine preconditions freely ("an admin, on the team plan, with MFA on, who has two orders").

Count them as the suite grows:

```text
   tests written   mothers required   tests per mother
              30                 25                1.2
              60                 45                1.3
             120                 87                1.4
             240                145                1.7
         ceiling              32768                  —   (2^15 independent preconditions)
```

At 240 tests the suite demands **145 distinct mothers** — 1.7 tests each. The curve is flattening, but it is flattening toward a ceiling of 2¹⁵ = 32,768, not toward a constant. Object mothers do not scale with the number of *tests*; they scale with the number of *combinations*, and combinations are exponential in the number of things a test can care about.

A **builder** is a fluent chain: `UserBuilder().admin().on_plan('pro').build()`. A **factory** is defaults plus overrides: `make_user(role='admin', plan='pro')`. Both need exactly one definition regardless of how many combinations exist:

```text
  pattern           definition   call lines   edits to add           a new
                         lines in the suite     one column  scenario costs
  object mother          1,063          240            145    a new method
  builder                   55          773              1         nothing
  factory                   55          240              1         nothing
```

**145 mothers at 7.3 lines each is 1,063 lines of fixture code against 55 for the factory — 19×.** And the maintenance column is the one that decides it: adding a single required column to `users` costs **145 edits with mothers and 1 with a factory**, and 145 is not a constant. It is the mother count, and the mother count only goes up.

The builder's cost is real but different: **773 call lines against the factory's 240**, because every precondition is its own method call. What you buy for those extra lines is that each precondition has a *name* you can grep for — `suspended()` rather than `status='suspended'`. That matters when the domain has states with rules attached, and it does not matter for a plain field. Use a builder for lifecycle states, a factory for everything else, and let the mothers go.

### Defaults, overrides, and the relevance principle

A factory that requires every field is a mother with extra steps. A factory that hides every field is a shared seed with extra steps. The design problem is which fields to make visible, and the relevance principle answers it: **the fields the assertion depends on, and no others.**

That is measurable in two directions. How much of what the test shows you matters, and how much of what matters did it never show you?

```text
  style             data rows to  values stated  of the deps,   tests with an
                  read ELSEWHERE    in the body        stated    unstated dep
  shared seed                5.2            0.0         0.0%             240
  object mother             25.3            1.0         0.0%             240
  factory                    0.0            2.2        74.5%              61
```

The shared-seed row is the lesson. Its assertion depends on **1.24 things per test**, states **zero** of them, and the reader's only route to the precondition is **5.2 rows scattered somewhere inside 4,374 lines** — with nothing to say which 5.2.

The object-mother row is the one worth sitting with, because most teams believe mothers fix this. They do not. `admin_user()` is a *name*, not data. The 22 fields it sets live one hop away in 25.3 lines of definition, the test body still states nothing, and **240 of 240 tests still assert on a value they never mention.** A name is a promise that the data is right; the relevance principle wants the data.

The factory states **74.5% of what its assertions read, at 2.2 values per test** — which is *more* values than the assertion reads (1.24), and that is correct. A test states its preconditions as well as its dependencies; the preconditions are what make it runnable.

And then the residual, which is the honest part: **61 of 240 factory tests (25.4%) still assert on something they never stated.** A default, or reference data. Defaults are shared state with better manners — invisible, global, and load-bearing exactly like `user_id = 1`, just easier to change. The fix is not fewer defaults. It is to restate, in the test, every value the assertion names, *even when the default already has it right*:

```python
# The default role is already 'member'. State it anyway.
user = make_user(role="member")
assert not can_delete_any_order(user)
```

That line is redundant today and load-bearing the day somebody changes the default. It is the cheapest insurance in this lesson.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="Three cards showing the same test written three ways. With a shared seed the body states 0 values, its assertion depends on 1.24 things, and 5.2 rows must be found somewhere inside a 4,374-line file. With an object mother the body still states 0 values, because a name is not data, and 22 fields sit one hop away in 25.3 lines of mother definition. With a factory the body states 2.2 values, 74.5 percent of everything the assertion reads, and 0 rows live elsewhere. A strip underneath records that 240 of 240 tests have an unstated dependency in the first two styles and 61 of 240 in the third.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">A test should state exactly what its assertion depends on — and nothing else</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">the same test, three fixture styles, averaged over the same 240-test suite</text>
  <rect x="24" y="62" width="264" height="272" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="1.7"/> <text x="38" y="82" font-size="11" font-weight="700" fill="#d64545">SHARED SEED</text> <rect x="36" y="92" width="240" height="68" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/> <text x="43" y="108" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">def test_admin_can_delete_order():</text>
  <text x="43" y="121" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;r = client.delete('/orders/1',</text> <text x="43" y="134" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;as_user=1)</text>
  <text x="43" y="147" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;assert r.status_code == 204</text> <text x="38" y="182" font-size="8.5" fill="currentColor" opacity="0.85">values stated in the body</text> <text x="274" y="182" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">0</text> <text x="38" y="199" font-size="8.5" fill="currentColor" opacity="0.85">things the assertion reads</text>
  <text x="274" y="199" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">1.24</text> <text x="38" y="216" font-size="8.5" fill="currentColor" opacity="0.85">rows you must find elsewhere</text> <text x="274" y="216" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">5.2</text> <text x="38" y="233" font-size="8.5" fill="currentColor" opacity="0.85">in a file of</text> <text x="274" y="233" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">4,374 lines</text>
  <text x="38" y="306" font-size="8.5" font-weight="700" fill="#d64545">Nothing here says user 1 is an admin.</text> <text x="38" y="320" font-size="8.5" fill="currentColor" opacity="0.8">You cannot know without opening seed.sql.</text> <rect x="302" y="62" width="264" height="272" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="1.7"/> <text x="316" y="82" font-size="11" font-weight="700" fill="#e0930f">OBJECT MOTHER</text>
  <rect x="314" y="92" width="240" height="81" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/> <text x="321" y="108" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">def test_admin_can_delete_order():</text> <text x="321" y="121" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;user = admin_user()</text>
  <text x="321" y="134" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;r = client.delete('/orders/1',</text> <text x="321" y="147" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;as_user=user)</text>
  <text x="321" y="160" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;assert r.status_code == 204</text> <text x="316" y="195" font-size="8.5" fill="currentColor" opacity="0.85">values stated in the body</text> <text x="552" y="195" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">0</text> <text x="316" y="212" font-size="8.5" fill="currentColor" opacity="0.85">things the assertion reads</text>
  <text x="552" y="212" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">1.24</text> <text x="316" y="229" font-size="8.5" fill="currentColor" opacity="0.85">fields the mother sets</text> <text x="552" y="229" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">22</text> <text x="316" y="246" font-size="8.5" fill="currentColor" opacity="0.85">lines one hop away</text> <text x="552" y="246" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">25.3</text>
  <text x="316" y="306" font-size="8.5" font-weight="700" fill="#e0930f">The name carries the precondition.</text> <text x="316" y="320" font-size="8.5" fill="currentColor" opacity="0.8">The values are still somewhere else.</text> <rect x="580" y="62" width="264" height="272" rx="10" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f" stroke-width="1.7"/> <text x="594" y="82" font-size="11" font-weight="700" fill="#0fa07f">FACTORY</text>
  <rect x="592" y="92" width="240" height="94" rx="6" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/> <text x="599" y="108" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">def test_admin_can_delete_order():</text> <text x="599" y="121" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;user = make_user(role='admin',</text>
  <text x="599" y="134" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;status='active')</text> <text x="599" y="147" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;r = client.delete('/orders/1',</text>
  <text x="599" y="160" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;&#160;as_user=user)</text> <text x="599" y="173" font-size="7.6" fill="currentColor" opacity="0.92" xml:space="preserve">&#160;&#160;&#160;&#160;assert r.status_code == 204</text> <text x="594" y="208" font-size="8.5" fill="currentColor" opacity="0.85">values stated in the body</text>
  <text x="830" y="208" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">2.2</text> <text x="594" y="225" font-size="8.5" fill="currentColor" opacity="0.85">things the assertion reads</text> <text x="830" y="225" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">1.24</text> <text x="594" y="242" font-size="8.5" fill="currentColor" opacity="0.85">of those deps, stated</text> <text x="830" y="242" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">74.5%</text>
  <text x="594" y="259" font-size="8.5" fill="currentColor" opacity="0.85">rows to read elsewhere</text> <text x="830" y="259" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0.0</text> <text x="594" y="306" font-size="8.5" font-weight="700" fill="#0fa07f">The precondition is the test's first line.</text> <text x="594" y="320" font-size="8.5" fill="currentColor" opacity="0.8">Delete the seed and nothing breaks.</text>
  <rect x="24" y="348" width="832" height="34" rx="8" fill="#3553ff" fill-opacity="0.08" stroke="#3553ff" stroke-width="1.5"/> <text x="40" y="369" font-size="10" font-weight="700" fill="#3553ff">TESTS WHOSE ASSERTION READS A VALUE THE TEST NEVER STATED</text> <text x="590" y="369" font-size="11" font-weight="700" text-anchor="end" fill="#d64545">240 / 240</text> <text x="712" y="369" font-size="11" font-weight="700" text-anchor="end" fill="#e0930f">240 / 240</text>
  <text x="842" y="369" font-size="11" font-weight="700" text-anchor="end" fill="#0fa07f">61 / 240</text> <text x="440" y="404" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Even the factory leaves 61 tests asserting on a default they never named. Defaults are shared state with better manners.</text> </g>
</svg>
```

### Referential integrity for free, and the cycle it creates

The feature that makes factories usable on a relational schema is the **SubFactory**: when a child needs a parent, the factory makes one. Ask for an order item and you get an order, a user, an address, a product, a catalogue — a valid graph, with no `NOT NULL` violations and no boilerplate.

It is not free. Walk the foreign keys of a small schema and count:

```text
      account=2  catalogue=1  order=1  order_item=1  product=1  shipping_address=1  user=2
      TOTAL 9 rows for 1 requested row
```

Nine rows for one, and look at `user=2`. The order created a user, and the order's shipping address created *another* one. The test now holds two users and an address belonging to neither order — a graph that satisfies every constraint and models nothing real. Assertions written against it can pass for reasons that do not exist in production.

The fan-out compounds when a test wants a collection. One order with ten line items:

```text
    each item builds its own parents :   90 rows, 10 orders, 20 users
    parents created once and passed  :   16 rows, 1 order,   1 user
    ratio 5.6x
```

**90 rows against 16 — 5.6×** — and the expensive version is also *wrong*: it builds ten orders of one item each, not one order of ten. The rule is boring and absolute: **create the parent once and pass it in.** `OrderItemFactory(order=order)` is not an optimisation, it is the difference between testing what you meant and testing something adjacent to it.

Then the cycle. Real schemas have mutual foreign keys — `users.default_address_id → addresses.id` and `addresses.user_id → users.id`. Two SubFactories pointing at each other have **no base case**: the program's recursion reached depth 50 and wrote 50 rows before an artificial limit stopped it, and in `factory_boy` this surfaces as a `RecursionError` from a line that looks like a declaration. The fix is to stop trying to do it in one statement: create with the nullable side `NULL`, then fill it in with a post-generation hook. Rows written: 2. Always 2.

At suite scale the SubFactory bill is **240 tests × 9 rows = 2,160 rows written for 240 rows asked for**, which is what makes the next two sections necessary.

### Uniqueness: a random "unique" field is a birthday problem

This line is in a great many test suites:

```python
email = f"user{random.randint(1, 10**6)}@test.com"
```

A million slots for a few thousand tests feels like plenty. It is a **birthday problem** (Feller, *An Introduction to Probability Theory and Its Applications*, Vol. 1, 3rd ed., 1968, sec. II.3), and the quantity that matters is not tests-versus-slots but *pairs* of tests versus slots. With `n` draws from `m` slots there are `n(n-1)/2` pairs, so the collision probability climbs with the **square** of the suite size:

```text
P(at least one collision) = 1 - prod(1 - i/m) for i in 0..n-1
```

`Build It` computes that exactly and simulates it, and they agree everywhere:

```text
   suite size    analytic   simulated   trials  expected dup pairs
          100    0.4938%     0.5150%   20,000               0.005
          500   11.7301%    11.5250%    4,000               0.125
        1,000   39.3267%    41.6000%    2,000               0.499
        5,000   99.9996%   100.0000%      400              12.498
```

At 5,000 tests, `P(collision) = 99.999634%`. That is not a flaky suite. **That is a broken suite that happens to pass 0.000366% of the time**, with 12.5 expected duplicate pairs every run.

The number to actually remember is smaller and much worse: solve for the suite size at which a build has a **1% chance of going red for this reason alone**, and it arrives at **143 tests.** Not five thousand. One hundred and forty-three. Every suite in this curriculum is past it.

The options are not close:

```text
  strategy for a unique field                  distinct values  P(collide) @5,000
  randint(1, 10**6)                                  1,000,000         99.999634%
  randint(1, 10**12)                         1,000,000,000,000          1.250e-05
  random 8-hex suffix (16**8)                    4,294,967,296          2.906e-03
  uuid4 — 122 random bits (RFC 9562)                 5.317e+36          2.351e-30
  factory Sequence / itertools.count                 unbounded  0 by construction
```

An 8-hex suffix — which looks thoroughly random — still collides at **2.906e-03** per run. UUID4 (122 random bits, per RFC 9562 sec. 5.4) is fine at 2.351e-30. A sequence is better still, and not because it is "more random": it is a **different kind of guarantee**. Uniqueness proved rather than probable, for the price of one integer of state per factory. This is exactly what `factory_boy`'s `Sequence` is, and it is why factories do not have this bug.

One warning that belongs to the next lesson: seeding fixes reproducibility, not collisions. A seeded RNG collides in the same place every run, which is *better* — a deterministic failure is debuggable — but the collision is still there.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 570" width="100%" style="max-width:840px" role="img" aria-label="A bar chart of the probability that a suite drawing random six-digit ids collides at least once, at suite sizes 100, 250, 500, 1000, 2000 and 5000. Each size shows a solid blue bar for the exact birthday-problem value and a dashed green outline for the simulated value, and the two agree everywhere: 0.4938 against 0.5150 percent at 100 tests, 3.0648 against 2.9250 at 250, 11.7301 against 11.5250 at 500, 39.3267 against 41.6000 at 1,000, 86.4710 against 84.7000 at 2,000, and 99.9996 against 100.0000 at 5,000. A red band marks that the one-percent-per-run threshold arrives at just 143 tests. A table underneath compares five strategies for a unique field and their collision probability across a 5,000-test suite.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">randint(1, 10**6) for a "unique" email is a measurable flake rate</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">P(at least one collision) — exact (Feller 1968, sec. II.3) against simulation, seed 1207</text>
  <rect x="110" y="100" width="104" height="16" rx="4" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.3"/> <text x="162" y="112" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">analytic</text> <rect x="222" y="100" width="104" height="16" rx="4" fill="none" stroke="#0fa07f" stroke-width="1.6" stroke-dasharray="4 2.5"/> <text x="274" y="112" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">simulated</text>
  <path d="M96 322 L 826 322" fill="none" stroke="currentColor" stroke-width="1" opacity="0.45"/><text x="88" y="325" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">0%</text> <path d="M96 264 L 826 264" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="88" y="268" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">25%</text>
  <path d="M96 207 L 826 207" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="88" y="210" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">50%</text> <path d="M96 150 L 826 150" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="88" y="152" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">75%</text>
  <path d="M96 92 L 826 92" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="88" y="95" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.6">100%</text> <rect x="113" y="321" width="42" height="1" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/> <rect x="159" y="321" width="42" height="1" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/>
  <text x="134" y="315" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">0.4938%</text> <text x="180" y="304" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">0.5150%</text> <text x="157" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">100</text> <rect x="234" y="315" width="42" height="7" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/>
  <rect x="280" y="315" width="42" height="7" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/> <text x="256" y="309" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">3.0648%</text> <text x="302" y="298" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">2.9250%</text> <text x="278" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">250</text>
  <rect x="356" y="295" width="42" height="27" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/> <rect x="402" y="295" width="42" height="27" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/> <text x="377" y="289" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">11.7301%</text> <text x="423" y="278" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">11.5250%</text>
  <text x="400" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">500</text> <rect x="478" y="232" width="42" height="90" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/> <rect x="524" y="226" width="42" height="96" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/> <text x="499" y="226" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">39.3267%</text>
  <text x="545" y="215" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">41.6000%</text> <text x="522" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">1,000</text> <rect x="600" y="123" width="42" height="199" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/> <rect x="646" y="127" width="42" height="195" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/>
  <text x="621" y="117" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">86.4710%</text> <text x="667" y="106" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">84.7000%</text> <text x="644" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">2,000</text> <rect x="721" y="92" width="42" height="230" rx="3" fill="#3553ff" fill-opacity="0.35" stroke="#3553ff" stroke-width="1.4"/>
  <rect x="767" y="92" width="42" height="230" rx="3" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="4 2.5"/> <text x="742" y="74" font-size="8.5" font-weight="700" text-anchor="middle" fill="#3553ff">99.9996%</text> <text x="788" y="86" font-size="8.5" font-weight="700" text-anchor="middle" fill="#0fa07f">100.0000%</text> <text x="765" y="340" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">5,000</text>
  <text x="440" y="358" font-size="9.5" text-anchor="middle" font-weight="700" fill="currentColor" opacity="0.65">TESTS IN THE SUITE</text> <rect x="24" y="368" width="832" height="30" rx="7" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="1.6"/> <text x="440" y="388" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">a 1% chance of a red build per run — for this reason alone — arrives at 143 tests. Not 5,000. 143.</text>
  <rect x="24" y="406" width="832" height="124" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.5"/> <text x="40" y="424" font-size="9" font-weight="700" fill="#7c5cff">STRATEGY FOR A UNIQUE FIELD</text> <text x="600" y="424" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">distinct values</text> <text x="842" y="424" font-size="9" font-weight="700" text-anchor="end" fill="currentColor" opacity="0.7">P(collide) across 5,000 tests</text>
  <text x="40" y="448" font-size="9.5" fill="currentColor" opacity="0.9">randint(1, 10**6)</text><text x="600" y="448" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.75">1,000,000</text><text x="842" y="448" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">99.999634%</text>
  <text x="40" y="465" font-size="9.5" fill="currentColor" opacity="0.9">randint(1, 10**12)</text><text x="600" y="465" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.75">1,000,000,000,000</text><text x="842" y="465" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">1.250e-05</text>
  <text x="40" y="482" font-size="9.5" fill="currentColor" opacity="0.9">random 8-hex suffix (16**8)</text><text x="600" y="482" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.75">4,294,967,296</text><text x="842" y="482" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">2.906e-03</text>
  <text x="40" y="499" font-size="9.5" fill="currentColor" opacity="0.9">uuid4 — 122 random bits (RFC 9562)</text><text x="600" y="499" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.75">5.317e+36</text><text x="842" y="499" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">2.351e-30</text>
  <text x="40" y="516" font-size="9.5" fill="currentColor" opacity="0.9">factory Sequence / itertools.count</text><text x="600" y="516" font-size="9.5" text-anchor="end" fill="currentColor" opacity="0.75">unbounded</text><text x="842" y="516" font-size="9.5" font-weight="700" text-anchor="end" fill="#0fa07f">0 by construction</text>
  <text x="440" y="554" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">A sequence is not less random. It is a different guarantee: uniqueness proved, for one integer of state.</text> </g>
</svg>
```

### Volume: when the fixture is the suite's run time

Some tests genuinely need bulk: pagination over ten thousand rows, an aggregation, an index that only matters at scale. Build that corpus per test and the fixture becomes the suite. `Build It` runs 300 tests needing a 1,000-row corpus against real `sqlite3`, isolating each test with `BEGIN`/`ROLLBACK` — the technique from [Integration Testing Against a Real Database](../06-integration-testing-real-database/) — and counts work rather than milliseconds, because rows and statements are reproducible and wall-clock time is not:

```text
  strategy                              rows written  statements  corpus builds
  per-test, row by row                       300,000     300,900            300
  per-test, one batch (COPY-shaped)          300,000       1,200            300
  session corpus + per-test writers           70,000         510             70
```

Read the first two rows together, because they are the trap that looks like a fix. **The batch writes exactly the same 300,000 rows.** It does it in 1,200 statements instead of 300,900 — a **251× cut in round trips and 0× in rows.** Batching (`executemany`, `COPY`, a multi-row `INSERT`) removes per-statement overhead, and per-statement overhead is real, but rows are a floor you cannot batch away.

Only sharing removes rows, and sharing under-delivers in a way worth knowing in advance. A session-scoped corpus *looks* like a 300× win: build 1,000 rows once instead of 300,000. It returns **4.3×**. The reason is in the last column: **69 of the 300 tests (23.0%) write to the corpus** and therefore cannot share it — they build their own. That fraction was counted from the suite's own archetypes, not assumed.

The gap between 300× and 4.3× is the whole design problem in one line: **you cannot share a corpus with a test that changes it.** Which gives the actual policy — split the suite by whether a test writes:

- **Read-only bulk** → one session-scoped corpus, built once, never mutated. Enforce it: give readers a connection that cannot write, or assert row counts are unchanged in a session-scoped teardown.
- **Writes** → per-test data inside a transaction that rolls back, at whatever volume that test genuinely needs, which is usually five rows and not ten thousand.
- **The middle case** — a test that needs bulk *and* writes — is where the volume goes. There are usually a handful. Batch those and stop optimising.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 434" width="100%" style="max-width:840px" role="img" aria-label="Three ways to give 300 tests a 1,000-row corpus, measured against real sqlite3. Inserting row by row writes 300,000 rows in 300,900 statements across 300 corpus builds. One batched insert per test writes exactly the same 300,000 rows in only 1,200 statements. A session-scoped corpus shared by readers writes 70,000 rows in 510 statements across 70 builds. A panel underneath explains that the shared corpus looks like a 300x saving but delivers 4.3x, because 69 of the 300 tests write to the corpus and must build their own.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Batching cuts round trips. Only sharing cuts rows — and only for readers.</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">300 tests x a 1,000-row corpus, real sqlite3, each test isolated by BEGIN/ROLLBACK</text>
  <text x="268" y="70" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65">ROWS WRITTEN (linear)</text> <text x="586" y="70" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65">STATEMENTS EXECUTED (log)</text> <path d="M586 96 L 586 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="586" y="90" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.55">10^2</text>
  <path d="M643 96 L 643 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="643" y="90" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.55">10^3</text> <path d="M700 96 L 700 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="700" y="90" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.55">10^4</text>
  <path d="M757 96 L 757 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="757" y="90" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.55">10^5</text> <path d="M814 96 L 814 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.14"/><text x="814" y="90" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.55">10^6</text> <path d="M268 96 L 268 284" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
  <text x="24" y="121" font-size="10" font-weight="700" fill="currentColor">per-test, row by row</text> <text x="24" y="135" font-size="8.5" fill="currentColor" opacity="0.65">300 corpus builds</text> <rect x="268" y="108" width="250" height="26" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.5"/> <text x="526" y="126" font-size="10" font-weight="700" fill="#d64545">300,000</text>
  <rect x="586" y="108" width="198" height="26" rx="4" fill="#d64545" fill-opacity="0.30" stroke="#d64545" stroke-width="1.5"/> <text x="792" y="126" font-size="10" font-weight="700" fill="#d64545">300,900</text> <text x="24" y="177" font-size="10" font-weight="700" fill="currentColor">per-test, one batch (COPY-shaped)</text> <text x="24" y="191" font-size="8.5" fill="currentColor" opacity="0.65">300 corpus builds</text>
  <rect x="268" y="164" width="250" height="26" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.5"/> <text x="526" y="182" font-size="10" font-weight="700" fill="#e0930f">300,000</text> <rect x="586" y="164" width="62" height="26" rx="4" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f" stroke-width="1.5"/> <text x="656" y="182" font-size="10" font-weight="700" fill="#e0930f">1,200</text>
  <text x="24" y="233" font-size="10" font-weight="700" fill="currentColor">session corpus + per-test writers</text> <text x="24" y="247" font-size="8.5" fill="currentColor" opacity="0.65">70 corpus builds</text> <rect x="268" y="220" width="58" height="26" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.5"/> <text x="334" y="238" font-size="10" font-weight="700" fill="#0fa07f">70,000</text>
  <rect x="586" y="220" width="40" height="26" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.5"/> <text x="634" y="238" font-size="10" font-weight="700" fill="#0fa07f">510</text> <rect x="24" y="296" width="832" height="86" rx="10" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-width="1.5"/> <text x="40" y="316" font-size="10.5" font-weight="700" fill="#3553ff">the two numbers that matter, and they disagree</text>
  <text x="40" y="336" font-size="9.5" fill="currentColor" opacity="0.9">batching the same work: 300,900 -&gt; 1,200 statements, a <tspan font-weight="700" fill="#e0930f">251x</tspan> cut in round trips and <tspan font-weight="700" fill="#e0930f">0x</tspan> in rows written</text>
  <text x="40" y="354" font-size="9.5" fill="currentColor" opacity="0.9">sharing one corpus: looks like a <tspan font-weight="700" fill="#0fa07f">300x</tspan> win (300,000 rows -&gt; 1,000) and returns <tspan font-weight="700" fill="#d64545">4.3x</tspan> (300,000 -&gt; 70,000)</text> <text x="40" y="372" font-size="9.5" fill="#d64545" font-weight="700">because 69 of the 300 tests (23.0%) write to the corpus and have to build their own.</text>
  <text x="440" y="410" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Rows are the floor you cannot batch away. The gap between 300x and 4.3x is one rule:</text> <text x="440" y="426" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">you cannot share a corpus with a test that changes it.</text> </g>
</svg>
```

### Production data is not test data

The tempting shortcut: restore last night's production dump into staging. Real distributions, real edge cases, real volume, no generation code. Then someone says "we anonymised it", and two things are quietly untrue.

**A consistent hash is not anonymisation.** Replacing `email` with `sha256(email)` preserves joins, which is why people do it — and a hash of a value from an *enumerable* domain is a lock whose key is the domain. Corporate addresses follow a published format. `Build It` gives the attacker no knowledge of who is in the dump; they enumerate the whole name space, 200 first names × 300 surnames, and hash it:

```text
  whole name space: 200 x 300 = 60,000 candidates hashed.
  rows re-identified: 20,000 of 20,000 (100.0%)
```

**Sixty thousand SHA-256 calls recovers every row.** The hash column survived. Nothing behind it did. A consistent hash is an equality check over a domain the attacker can enumerate, and salting it per-dataset breaks exactly the joins you kept it for.

**The columns you did not mask re-identify people by themselves.** This is Sweeney's k-anonymity result (*k-Anonymity: A Model for Protecting Privacy*, IJUFKS 10(5), 2002): a row is re-identified when its **quasi-identifier** — the combination of ordinary-looking columns — is unique in the data, because any public list carrying the same columns then names it. Measured on the same dump:

```text
  quasi-identifier joined on                    cells  k=1 rows    share
  (city, birth_year, gender)                    2,998        31    0.2%
  (postcode, birth_year, gender)               16,961    14,250   71.2%
  (postcode, birth_year, birth_day, gender)    19,991    19,982   99.9%
```

The third row is a date of birth, which every "anonymised" dump keeps because the tests need realistic ages. It leaves **99.9% of the dump uniquely identifiable from three facts a stranger can look up.** Generalising the quasi-identifier is the genuine fix and the first row is its price — city instead of postcode, year instead of date, and the unique share falls to **0.2%**. Note what that costs: exactly the realism you took the production dump to get.

Then the fix everyone tries next, which is worse than either attack. Shuffle a column within itself, so no row is a real person:

```text
  marginal distribution preserved exactly               True
  rows whose city still matches their address            971  4.86%
  rows whose country still matches their city          2,650  13.25%
  tests asserting a cross-table invariant                 43  17.9% of the suite
```

The marginal distribution is preserved *exactly* — every city appears the same number of times, every dashboard looks right. And **4.86% of rows still live in the city their own address says they live in**, 13.25% in a country consistent with their city, and **43 of the 240 tests (17.9%) assert a cross-column or cross-table invariant** and now fail for no reason connected to the code.

Shuffling preserves every marginal and destroys every joint distribution. Your histograms are perfect and your joins are fiction, which is the worst available combination: the data looks real enough that nobody checks it, and no invariant in it holds. See [Injection & the OWASP Top 10](../../07-auth-and-security/11-injection-and-owasp-top-10/) for the adjacent point that a test environment holding real PII is a production data store with none of the controls.

The conclusion is not "anonymise harder". It is that **the properties you want from production data — real distributions, real edge cases — are properties you can generate**, and generated data has no one to re-identify.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 546" width="100%" style="max-width:840px" role="img" aria-label="Two measured attacks on an anonymised 20,000-row production dump, and one failed fix. First, a dictionary attack: because the address format is public, enumerating the 200 by 300 name space costs 60,000 sha256 computations and re-identifies 20,000 of 20,000 rows, 100 percent. Second, a join on the unmasked quasi-identifier: city with birth year and gender leaves 0.2 percent of rows unique, postcode with birth year and gender leaves 71.2 percent, and postcode with a full date of birth and gender leaves 99.9 percent. Third, the fix that fails: shuffling the city column preserves the marginal distribution exactly but leaves only 4.86 percent of rows matching their own address and 13.25 percent matching their own country, breaking 43 of the 240 tests that assert a cross-table invariant.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace"> <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">"We anonymised it" — two attacks and one failed fix, all measured</text> <text x="440" y="44" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">a 20,000-row production dump: email replaced by sha256(email), every other column kept</text>
  <rect x="24" y="60" width="832" height="102" rx="10" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-width="1.6"/> <text x="40" y="80" font-size="10.5" font-weight="700" fill="#d64545">ATTACK 1 — the consistent hash is a dictionary away from plaintext</text> <rect x="40" y="92" width="180" height="46" rx="7" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.4"/>
  <text x="130" y="110" font-size="9" text-anchor="middle" fill="currentColor">200 first x 300 last names</text> <text x="130" y="126" font-size="10.5" font-weight="700" text-anchor="middle" fill="currentColor">60,000 candidates</text> <path d="M226 115 L 262 115" fill="none" stroke="#d64545" stroke-width="1.6" marker-end="url(#p12-07-a6)"/> <rect x="268" y="92" width="176" height="46" rx="7" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="1.4"/>
  <text x="356" y="110" font-size="9" text-anchor="middle" fill="#7c5cff">sha256(first.last@domain)</text> <text x="356" y="126" font-size="9" text-anchor="middle" fill="currentColor" opacity="0.8">the format is public</text> <path d="M450 115 L 486 115" fill="none" stroke="#d64545" stroke-width="1.6" marker-end="url(#p12-07-a6)"/> <rect x="492" y="92" width="180" height="46" rx="7" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.6"/>
  <text x="582" y="110" font-size="9" text-anchor="middle" fill="#d64545">matched against the dump</text> <text x="582" y="126" font-size="11" font-weight="700" text-anchor="middle" fill="#d64545">20,000 of 20,000</text> <text x="692" y="107" font-size="14" font-weight="700" fill="#d64545">100.0%</text> <text x="692" y="124" font-size="8.5" fill="currentColor" opacity="0.8">re-identified, for</text> <text x="692" y="135" font-size="8.5" fill="currentColor" opacity="0.8">60,000 hash calls</text>
  <text x="40" y="154" font-size="9" fill="currentColor" opacity="0.85">a consistent hash is not encryption. It is an equality check over a domain the attacker can enumerate.</text> <rect x="24" y="174" width="832" height="152" rx="10" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f" stroke-width="1.6"/> <text x="40" y="194" font-size="10.5" font-weight="700" fill="#e0930f">ATTACK 2 — a join on the columns you did NOT mask (Sweeney, k-Anonymity, IJUFKS 10(5), 2002)</text>
  <text x="40" y="210" font-size="9" fill="currentColor" opacity="0.8">rows whose quasi-identifier is unique in the dump — those are named by any public list carrying the same columns</text> <text x="374" y="236" font-size="9.5" text-anchor="end" fill="currentColor">(city, birth_year, gender)</text> <rect x="384" y="222" width="1" height="20" rx="3" fill="#0fa07f" fill-opacity="0.35" stroke="#0fa07f" stroke-width="1.4"/> <text x="393" y="237" font-size="10" font-weight="700" fill="#0fa07f">0.2%</text>
  <text x="842" y="237" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">31 of 20,000</text> <text x="374" y="270" font-size="9.5" text-anchor="end" fill="currentColor">(postcode, birth_year, gender)</text> <rect x="384" y="256" width="214" height="20" rx="3" fill="#e0930f" fill-opacity="0.35" stroke="#e0930f" stroke-width="1.4"/> <text x="606" y="271" font-size="10" font-weight="700" fill="#e0930f">71.2%</text>
  <text x="842" y="271" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">14,250 of 20,000</text> <text x="374" y="304" font-size="9.5" text-anchor="end" fill="currentColor">(postcode, birth_year, birth_day, gender)</text> <rect x="384" y="290" width="300" height="20" rx="3" fill="#d64545" fill-opacity="0.35" stroke="#d64545" stroke-width="1.4"/> <text x="692" y="305" font-size="10" font-weight="700" fill="#d64545">99.9%</text>
  <text x="842" y="305" font-size="9" text-anchor="end" fill="currentColor" opacity="0.7">19,982 of 20,000</text> <rect x="24" y="338" width="832" height="122" rx="10" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff" stroke-width="1.6"/> <text x="40" y="358" font-size="10.5" font-weight="700" fill="#7c5cff">THE "FIX" — shuffle the city column so no row is a real person</text> <text x="40" y="380" font-size="9.5" fill="currentColor" opacity="0.9">marginal distribution preserved exactly</text>
  <text x="620" y="380" font-size="10" font-weight="700" text-anchor="end" fill="#0fa07f">True</text> <text x="40" y="400" font-size="9.5" fill="currentColor" opacity="0.9">rows whose city still matches their own address</text> <text x="620" y="400" font-size="10" font-weight="700" text-anchor="end" fill="#d64545">971 / 20,000 = 4.86%</text> <text x="40" y="420" font-size="9.5" fill="currentColor" opacity="0.9">rows whose country still matches their own city</text>
  <text x="620" y="420" font-size="10" font-weight="700" text-anchor="end" fill="#d64545">2,650 / 20,000 = 13.25%</text> <text x="40" y="440" font-size="9.5" fill="currentColor" opacity="0.9">tests in this lesson's suite asserting a cross-table invariant</text> <text x="620" y="440" font-size="10" font-weight="700" text-anchor="end" fill="#d64545">43 of 240 — all now red</text> <text x="648" y="392" font-size="9" fill="currentColor" opacity="0.8">every histogram is perfect.</text>
  <text x="648" y="406" font-size="9" fill="currentColor" opacity="0.8">every join is fiction.</text> <text x="648" y="424" font-size="9" font-weight="700" fill="#7c5cff">shuffling preserves marginals</text> <text x="648" y="437" font-size="9" font-weight="700" fill="#7c5cff">and destroys joint structure.</text>
  <text x="440" y="486" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Generalising the quasi-identifier is the real fix, and the first bar is its price: 99.9% unique falls to 0.2% —</text> <text x="440" y="502" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">bought with exactly the realism you took the production dump to get.</text>
  <text x="440" y="526" font-size="11" text-anchor="middle" font-weight="700" fill="#0fa07f">Generate the data instead. A factory has no PII to leak.</text> </g> <defs><marker id="p12-07-a6" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="#d64545"/></marker></defs>
</svg>
```

### Golden files: when the fixture is the assertion

A **golden file** (or approval test) inverts the usual arrangement: instead of writing an assertion, you record the output and assert it has not changed. For anything with a big structured output — a rendered invoice, an API response, a query plan — it is the cheapest thorough assertion available.

It is also the only fixture whose *review* is the test. A golden file is only as good as the diff a human reads, so the format decides whether the test exists:

```text
  golden file format                            files  diff lines  diff chars  chars/file
  json.dumps(obj)  — one line, no spaces           60         120      40,726         679
  json.dumps(obj, indent=2, sort_keys=True)        60          60       1,260          21
```

Same 60 files, same benign change (one added `currency` field), **32× the characters to read**. The pretty-printed diff is 60 identical one-line additions at 21 characters each, which a reviewer can genuinely approve. The one-line format is 679 characters of changed JSON per file, which a reviewer approves faster, having read none of it. Store goldens pretty-printed with sorted keys, always.

Then the failure mode that kills them. Put one unstable field in the golden — a `generated_at` timestamp — and introduce one real regression, VAT charged at 20% instead of 19% on a single response:

```text
  goldens that changed this run                    60 of 60
  goldens with a real behaviour change              1 of 60
  diff lines the reviewer must read               122
  diff lines that mean anything                     4
  signal ratio                                   3.3%
```

**A 3.3% signal ratio.** The reviewer is handed 60 changed files, 59 of which changed because time passed. Nobody reviews that; they run the accept-all command, and the one genuine regression is approved along with the noise. The golden file did its job — it *detected* the change — and the review discarded the signal.

So: goldens need determinism more than any other fixture, because their assertion is "nothing changed" and every unstable byte is a false positive. Scrub or inject every volatile field, keep goldens small and per-behaviour rather than one giant snapshot, and treat a golden update in a pull request as a change to expected behaviour requiring the same scrutiny as a change to an assertion. [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/) is the next lesson because this is where it starts to hurt.

## Build It

[`code/test_data.py`](code/test_data.py) is nine numbered experiments in the standard library, seeded with `random.Random(1207)`, finishing in about five seconds. Every number it prints is a count rather than a duration, so two runs produce byte-identical **stdout** — the one value that cannot be reproducible, the elapsed time, goes to stderr, which is what lets you `diff` two runs at all. The parts that carry the ideas:

**Both worlds are generated from one suite.** The comparison is only honest if nothing differs except how each test gets its data, so a test is an archetype plus its incidental preconditions, and the two worlds differ only in the binding function:

```python
def bind_shared(suite, world, rng):
    """How a test finds data in a shared seed: grep the file and take the
    first row that works. Four times in five that is the lowest id."""
    ...
    uid = matches[0] if rng.random() < 0.80 else rng.choice(matches[:5])

def bind_factory(suite):
    """How a test finds data with factories: it builds exactly what it needs,
    with ids from a sequence, so no two tests can collide."""
    return [Test(..., 10_001 + i, ...) for i, (arch, needs) in enumerate(suite)]
```

The 80% is the whole mechanism of the trap. Nobody *chooses* to couple 116 tests to user 1; they grep the seed, take the first row that satisfies their precondition, and the first row is almost always the lowest id — which is the god fixture, because the god fixture is the one that satisfies everything.

**A failure is a read-set intersection.** With both worlds carrying explicit read sets, blast radius stops being a guess:

```python
def failures(tests, changed, invalidated):
    n = 0
    for t in tests:
        broke = bool(t.reads & changed)
        if not broke and invalidated:
            # The change also destroyed a precondition this test declared.
            broke = t.user_id == 1 and any(nd in t.needs for nd in invalidated)
        n += broke
    return n
```

The second clause matters: changing user 1's role from `admin` to `member` breaks tests that *read* the role and also tests that merely *required* an admin. Both are red; only the first kind is obvious in a stack trace.

**The seed grows itself.** When no existing row satisfies a test's preconditions, the program appends one — 15 times over 240 tests. This is not decoration; it is how a fixture file becomes 4,374 lines, and it means the seed's size is an output of the experiment rather than a number chosen to sound impressive.

**The collision probability is computed exactly and then checked by simulation.** Computing `1 - prod(1 - i/m)` naively underflows; doing it in log space does not:

```python
def birthday_p(n: int, m: int) -> float:
    """P(at least one collision) drawing n values uniformly from m, exactly."""
    if n > m:
        return 1.0
    return -math.expm1(sum(math.log1p(-i / m) for i in range(n)))
```

`math.log1p` and `math.expm1` are the paired functions for exactly this: they keep precision when the argument is near zero, which every term here is. The simulation exists so the closed form is checked rather than trusted, and once they agree at six sizes the closed form can be used where simulating would be pointless.

**The volume experiment runs against real sqlite3 and counts work, not time.** Wall-clock numbers are not reproducible, so the program reports `conn.total_changes` and its own statement count — both exact, both what the wall clock is proportional to:

```python
conn.execute("BEGIN")
conn.executemany(INSERT, rows)         # the COPY-shaped batch
conn.execute(PROBE)
conn.execute("ROLLBACK")
```

**One reproducibility bug the program had to fix in itself.** The coupling matrix is built by iterating `frozenset`s of tuples, so `Counter.most_common()` breaks ties in an order that follows `PYTHONHASHSEED` — a ranking that changes between runs on identical data. That is lesson 08's subject arriving early, in this program:

```python
def ranked(counter: Counter) -> list:
    """most_common() with an explicit tie-break. ... Sorting by (-count, key)
    makes the ranking a property of the data."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))
```

Run it:

```bash
docker compose exec -T app python \
  phases/12-testing-and-quality/07-test-data-and-fixtures/code/test_data.py
```

```console
TEST DATA & FIXTURES — measured
Phase 12 · Lesson 07 · seed=1207 · stdlib only

== 1 · THE SHARED-FIXTURE TRAP: BLAST RADIUS OF ONE FIELD ==
  shared seed : 4,374 lines, 4,353 rows, 553 KiB — of which 15 users were
                appended by this suite, because no existing row fit
  factory code: 55 lines of definitions, measured from this file; 0 rows until asked
  suite       : 240 tests, 14 archetypes, identical in both worlds
  binding     : shared -> 116 tests (48.3%) on user 1, 53 distinct users; factory -> 240, 0 shared

  one change to the fixture                       shared  factory
  user 1 role: admin -> member                        18        0
  add a 3rd order to user 1 (to test pagination)      52        0
  product 1 price: 550 -> 590 cents                   11        0
  DE VAT rate: 19.0 -> 20.0 (reference data)          33       33

  worst single-field change: 52 of 240 tests (21.7%) in the shared world, 0 in
  the factory world, and the code under test did not move. Now read
  [+4]

== 2 · THE COUPLING MATRIX: WHICH CELLS ARE NOW FROZEN ==
  a cell is one (entity, id, field). Every cell in seed.sql that the 240
  tests' assertions depend on, ranked:

    #  cell in the shared seed           tests  % of suite   verdict
    1  user[1].orders.sum_total             28      11.7%   frozen — you cannot change it
    2  user[1].role                         18       7.5%   read all 10+ tests first
    3  user[1].credit_limit_cents           16       6.7%   read all 10+ tests first
    4  user[1].orders.count                 14       5.8%   read all 10+ tests first
    5  product[1].price                     11       4.6%   read all 10+ tests first
  [+5]

       distribution                        shared   factory
       distinct cells the suite reads          92       266
       total reads across the suite           298       298
       most tests reading one SEED cell        28         1
       seed cells read by 2+ tests             34         0
       seed cells read by 10+ tests             6         0
       reads of the one reference cell         33        33

  the top 5 seed cells carry 87/298 = 29.2% of every read. 57 of
  4,353 seeded rows (1.31%) are load-bearing; the other 4,296 exist to
  make the file look like a database. The ballast is free. The head
  is not: user[1].orders.sum_total is read by 28 tests (11.7%) and no test says so.
  [+4]

== 3 · OBJECT MOTHERS vs BUILDERS vs FACTORIES ==
  [+7]
   tests written   mothers required   tests per mother
              30                 25                1.2
              60                 45                1.3
             120                 87                1.4
             240                145                1.7
         ceiling              32768                  —   (2^15 independent preconditions)

  pattern           definition   call lines   edits to add           a new
                         lines in the suite     one column  scenario costs
  object mother          1,063          240            145    a new method
  builder                   55          773              1         nothing
  factory                   55          240              1         nothing
  [+6]

== 4 · THE RELEVANCE PRINCIPLE, MEASURED ==
  [+4]
  style             data rows to  values stated  of the deps,   tests with an
                  read ELSEWHERE    in the body        stated    unstated dep
  shared seed                5.2            0.0         0.0%             240
  object mother             25.3            1.0         0.0%             240
  factory                    0.0            2.2        74.5%              61
  [+14]

== 5 · REFERENTIAL INTEGRITY FOR FREE, AND WHAT IT COSTS ==
  [+2]
      account=2  catalogue=1  order=1  order_item=1  product=1  shipping_address=1  user=2
      TOTAL 9 rows for 1 requested row — and note user=2, account=2:
  [+1]

  now the test wants ONE order with 10 line items.
    each item builds its own parents :   90 rows, 10 orders, 20 users
    parents created once and passed  :   16 rows, 1 order,   1 user
    ratio 5.6x — and the first version tests 10 orders of one item
    each, which is not what the author meant.
  [+11]

== 6 · UNIQUENESS: A RANDOM 'UNIQUE' FIELD IS A FLAKE RATE ==
  [+3]
   suite size    analytic   simulated   trials  expected dup pairs
          100    0.4938%     0.5150%   20,000               0.005
          250    3.0648%     2.9250%    8,000               0.031
          500   11.7301%    11.5250%    4,000               0.125
        1,000   39.3267%    41.6000%    2,000               0.499
        2,000   86.4710%    84.7000%    1,000               1.999
        5,000   99.9996%   100.0000%      400              12.498

  analytic and simulated agree at every size, so the closed form
  can be trusted where simulating is pointless. At 5,000 tests, P(collision)
  = 99.999634%: not a flaky suite, a broken one that passes 0.000366% of the time,
  with 12.5 expected duplicate pairs per run. And the threshold nobody
  thinks they are near — a 1% chance of a red build per run, for
  this reason alone — arrives at 143 tests. Not 5,000. 143.

  strategy for a unique field                  distinct values  P(collide) @5,000
  randint(1, 10**6)                                  1,000,000         99.999634%
  randint(1, 10**12)                         1,000,000,000,000          1.250e-05
  random 8-hex suffix (16**8)                    4,294,967,296          2.906e-03
  uuid4 — 122 random bits (RFC 9562)                 5.317e+36          2.351e-30
  factory Sequence / itertools.count                 unbounded  0 by construction
  [+6]

== 7 · VOLUME: 300 TESTS THAT EACH NEED A 1,000-ROW CORPUS ==
  [+3]

  strategy                              rows written  statements  corpus builds
  per-test, row by row                       300,000     300,900            300
  per-test, one batch (COPY-shaped)          300,000       1,200            300
  session corpus + per-test writers           70,000         510             70

  strategy                                rows   stmts   isolation
  per-test, row by row                    1.0x      1x   every test gets a pristine corpus
  per-test, one batch (COPY-shaped)       1.0x    251x   every test gets a pristine corpus
  session corpus + per-test writers       4.3x    590x   readers share it; writers build their own
  [+8]

== 8 · ANONYMISATION: TWO WAYS IT DOES NOT WORK ==
  [+7]
  rows re-identified: 20,000 of 20,000 (100.0%). The hash column survived;
  [+7]
  quasi-identifier joined on                    cells  k=1 rows    share
  (city, birth_year, gender)                    2,998        31    0.2%
  (postcode, birth_year, gender)               16,961    14,250   71.2%
  (postcode, birth_year, birth_day, gender)    19,991    19,982   99.9%
  [+7]
  THE 'FIX' — shuffle the city column so no row is a real person.
  marginal distribution preserved exactly               True
  rows whose city still matches their address            971  4.86%
  rows whose country still matches their city          2,650  13.25%
  tests asserting a cross-table invariant                 43  17.9% of the suite
  [+6]

== 9 · GOLDEN FILES: THE FORMAT IS THE REVIEW ==
  60 golden files, one API response each. One benign change: a `currency`
  field is added to every response.

  golden file format                            files  diff lines  diff chars  chars/file
  json.dumps(obj)  — one line, no spaces           60         120      40,726         679
  json.dumps(obj, indent=2, sort_keys=True)        60          60       1,260          21
  [+5]

  now put ONE unstable field in the golden (`generated_at`) and one
  REAL regression (VAT at 20% not 19% on a single response):

  goldens that changed this run                    60 of 60
  goldens with a real behaviour change              1 of 60
  diff lines the reviewer must read               122
  diff lines that mean anything                     4
  signal ratio                                   3.3%
  [+6]

  (elapsed on stderr; stdout is identical run to run)
```

**Section 1** is the headline and nothing is stipulated: same 240 tests, same archetypes, same seed, one field changed. **52 of 240 (21.7%) against 0.** **Section 2** explains why — the reads concentrate, 28 tests onto one cell. **Section 4** is the principle stated as a measurement, and its most useful row is the middle one: object mothers do not solve this. **Section 6** is the number to take to your own suite today. **Section 7** is the one that contradicted the obvious expectation — a session-scoped corpus is a 4.3× win, not a 300× one. **Section 8** is why you should stop asking for a production dump.

## Use It

**`factory_boy` is the default and the API is small.** Four declarations cover almost everything:

```python
import factory
from factory.alchemy import SQLAlchemyModelFactory

class UserFactory(SQLAlchemyModelFactory):
    class Meta:
        model = User
        sqlalchemy_session_persistence = "flush"   # not "commit" — see below

    # Sequence: uniqueness proved, not probable. This is section 6's fix.
    email = factory.Sequence(lambda n: f"user-{n}@test.invalid")
    username = factory.Sequence(lambda n: f"user-{n}")
    role = "member"                                 # a default you can override
    status = "active"
    country = "DE"

    # LazyAttribute: derived from OTHER fields, so overrides stay consistent.
    city = factory.LazyAttribute(lambda o: CAPITALS[o.country])

class OrderFactory(SQLAlchemyModelFactory):
    class Meta:
        model = Order
    user = factory.SubFactory(UserFactory)          # referential integrity
    total_cents = 1_000
```

`Sequence` is the whole of section 6 in one word. `LazyAttribute` is what stops `make_user(country="FR")` from leaving a German city behind — derive dependent fields rather than defaulting them. `SubFactory` is section 5, including its costs.

`sqlalchemy_session_persistence` deserves the callout: set it to `"flush"`, not `"commit"`. A factory that commits defeats the transaction-rollback isolation from Lesson 6 and leaks rows into the next test — the order-dependent failure that Lesson 9 will spend its budget hunting.

**The three flags that bite.** `build()` makes an unsaved object, `create()` persists it — and `SubFactory` under `build()` still *creates* the parent unless you use `factory.build(dict, FACTORY_CLASS=...)` or `SubFactory(..., strategy=factory.BUILD_STRATEGY)`. Use `create_batch(10, order=order)` rather than a loop of `OrderItemFactory()`, or you get section 5's 90 rows and ten orders. And `post_generation` is how you break a cycle:

```python
class UserFactory(SQLAlchemyModelFactory):
    @factory.post_generation
    def default_address(obj, create, extracted, **kwargs):
        if not create:
            return
        obj.default_address = extracted or AddressFactory(user=obj)
```

**`Faker` needs a fixed seed, and unseeded `Faker` is a flake source in its own right.** `factory.Faker("email")` draws from a global generator; without seeding, two tests can draw the same value and a `UNIQUE` constraint fails one run in N. Seed it once, in `conftest.py`:

```python
from faker import Faker
Faker.seed(1207)                 # deterministic values every run
```

Better still: use `Faker` for fields nobody asserts on (names, addresses, text) and a `Sequence` for anything with a uniqueness constraint. Seeding makes a collision reproducible; only a sequence makes it impossible.

**Fixture scope, and the rule for choosing one.** `pytest` offers `function`, `class`, `module`, `package` and `session`. The rule is a single question: **does any test mutate it?**

| Scope | Use for | Rule |
|---|---|---|
| `function` (default) | anything a test writes to | the default for a reason — stay here unless you measured a problem |
| `module` / `class` | expensive read-only setup shared by one file | only if every test in the file treats it as read-only |
| `session` | containers, connection pools, immutable reference data, the read-only bulk corpus | must be genuinely immutable, and enforce it |

Section 7 is the arithmetic behind the table: 69 of 300 tests wrote, so a session-scoped corpus returned 4.3× rather than 300×. Do not fight that number by making writers share; the failure mode is order-dependent tests, which cost far more than the CI seconds. And note that `pytest-xdist` (`-n auto`) gives each worker its **own** session fixture — a session-scoped container becomes one container *per worker*, which is either fine or a resource explosion depending on what it is.

**`pytest-factoryboy`** registers factories as fixtures (`user_factory`, and a `user` instance) and lets you override fields per test with `@pytest.mark.parametrize("user__role", ["admin"])`. It is genuinely useful for parametrised tests and it also makes the relevance principle harder to see, because the override moves from the body into a decorator. Use it for parametrised sweeps; use plain factory calls in the body for everything else.

**Golden files: `syrupy`.** `assert response == snapshot` with `--snapshot-update` to accept, snapshots stored next to the test. Two settings do the work: a JSON/AmberSnapshot extension that pretty-prints with sorted keys (section 9's 32×), and a matcher that scrubs volatile fields before comparison:

```python
from syrupy.matchers import path_type

def test_order_response(client, snapshot):
    body = client.get("/orders/1").json()
    assert body == snapshot(matcher=path_type({
        ".*generated_at": (str,),      # present and a string; value ignored
        ".*id": (int,),
    }, regex=True))
```

Without that matcher you get section 9's 3.3% signal ratio and an accept-all habit. `pytest-approvaltests` is the alternative if you want an external diff tool in the loop.

**Never take the production dump.** If you are overruled, the floor is: generalise every quasi-identifier before it leaves production (city not postcode, birth *year* not birth date — that is 99.9% unique down to 0.2%), never a bare consistent hash on an enumerable domain, and treat the result as production data under production controls, because it still is. The better answer is a generator seeded from *aggregate* statistics — real distributions, no real people.

**What to actually pick.** For a backend service: `factory_boy` with `Sequence` for every unique field and `SubFactory` for parents; `Faker.seed()` pinned in `conftest.py`; `function` scope by default and `session` scope only for containers and genuinely immutable reference data; parents created once and passed in; `syrupy` with a scrubbing matcher for the two or three endpoints whose output is big enough to be worth a golden. Then write the fixture policy down, because the trap in this lesson is not built by a decision — it is built by 240 small ones.

## Think about it

1. Section 1 measured a 52-test blast radius in the shared world and 0 in the factory world — except for the VAT rate, which broke 33 tests in both. Your service has a currency table, a feature-flag defaults table, and a tenant-settings table. Which of those belong in the reference-data floor and which are the god fixture wearing a costume? What test would tell you the difference?
2. The coupling matrix shows 28 tests reading `user[1].orders.sum_total` and 57 of 4,353 rows load-bearing. You are given one week to migrate the suite off the shared seed. Using only those two numbers, what order do you convert tests in, and how do you know you are finished?
3. Section 6 puts the 1%-per-run collision threshold at 143 tests. Your suite has 900 tests and uses `randint(1, 10**6)` for emails — but you have never seen this failure. Give two mechanisms by which the collision could be occurring and being absorbed, and say what you would grep for to confirm each.
4. The session-scoped corpus returned 4.3× against a theoretical 300× because 23.0% of tests wrote to it. At what write-fraction does a shared corpus stop being worth the isolation risk at all? Derive it from the numbers in section 7 rather than guessing, and state the assumption your derivation makes.
5. Section 9 measured a 3.3% signal ratio when one volatile field is present in 60 goldens. Your team's policy is "review every snapshot diff". Compute what that policy actually costs per pull request at 122 diff lines, and propose a change to the *fixture* rather than to the policy that would make the policy honest.

## Key takeaways

- **A shared fixture makes every test's real precondition invisible, and the price is measurable.** The same 240-test suite, the same one-field change: **52 of 240 tests (21.7%) red in the shared-seed world and 0 in the factory world.** Nothing about the code under test changed in either case.
- **Coupling concentrates into a head you can name.** **28 tests read one cell** (`user[1].orders.sum_total`), the top five cells carry **29.2% of all 298 reads**, and **34 seed cells are read by two or more tests against 0 in the factory world.** Only **57 of 4,353 rows (1.31%) are load-bearing** — the ballast is free, the head is not.
- **Object mothers do not fix this; they move it one hop.** A mother's name is its precondition set, so the suite needed **145 distinct mothers for 240 tests** (ceiling 2¹⁵), costing **1,063 lines against a factory's 55 — 19×** — and one new required column costs **145 edits versus 1.** In both the seed and the mother world, **240 of 240 tests assert on a value the test body never states.**
- **A factory states 74.5% of what its assertions read, and the 25.4% residual is the lesson's honest edge.** **61 of 240 tests** still depend on a default or on reference data they never mention. Restate the value in the test even when the default already has it right.
- **SubFactories buy referential integrity and charge in rows.** One requested `order_item` writes **9 rows** — including **two users**, because the order and its shipping address each made one — and ten line items cost **90 rows against 16 (5.6×)** while testing the wrong thing. Mutual foreign keys have no base case at all: depth 50 and 50 rows before an artificial limit stopped it.
- **`randint(1, 10**6)` for a unique field is a birthday problem, and the threshold is far lower than anyone guesses.** A **1% chance of a red build per run arrives at 143 tests**; at 5,000 tests the collision probability is **99.999634%** with 12.5 expected duplicate pairs. Analytic and simulated agreed at all six suite sizes. A `Sequence` costs one integer and makes it 0 by construction.
- **Batching cuts round trips; only sharing cuts rows, and sharing under-delivers.** The COPY-shaped batch wrote the **same 300,000 rows** in **1,200 statements instead of 300,900 (251×)**. The session-scoped corpus looked like a 300× win and returned **4.3×**, because **69 of 300 tests (23.0%) write and must build their own.**
- **"We anonymised it" fails two ways, both cheap to exploit.** **60,000 SHA-256 calls re-identified 20,000 of 20,000 rows (100.0%)** because the address format is public; and **99.9% of the dump is unique on (postcode, birth date, gender)** — 0.2% if you generalise to (city, birth year, gender), which costs exactly the realism you wanted. Shuffling a column preserves the marginal *exactly* and leaves **4.86% of rows matching their own address**, breaking **43 of 240 tests**.
- **A golden file's format is its test.** The same benign change costs **32× more characters to read** in one-line JSON than pretty-printed with sorted keys. One volatile field drops the review's **signal ratio to 3.3%** — 60 of 60 goldens changed, 1 real — which is how a genuine regression gets approved by an accept-all.

Next: [Determinism: Time, Randomness, IDs & Order](../08-determinism-time-randomness-order/) — removing the hidden inputs a test never set, starting with the clock that changes 1,440 times a day.
