---
name: checklist-integration-testing-real-database
description: Auditing and building a database integration suite that tests the engine you actually deploy.
phase: 12
lesson: 06
---

# Checklist — Integration Testing Against a Real Database

For a backend service with a SQL database. Work top to bottom; each section is
independently useful. Reference numbers are measured in Phase 12 Lesson 06 —
recheck them against your own fixture size before quoting them at anyone.

---

## 0. Fill this in before you change anything

| Fact | Your value |
|---|---|
| Engine + **major version** in production | ______ |
| Engine + version the test suite talks to | ______ |
| If those differ — who decided, and when | ______ |
| Test isolation strategy (rollback / truncate / recreate / template / none) | ______ |
| Schema source in tests (migrations forward / dump / ORM `create_all`) | ______ |
| Fixture rows written per test | ______ |
| Integration suite wall time, cold and warm | ______ / ______ |
| Tests that open two connections on purpose | ______ |
| Is test order randomised? | ______ |

If rows 1 and 2 differ, everything below section 1 is secondary. Fix that first.

---

## 1. Are you testing the engine you deploy?

- [ ] Test engine and production engine are the **same product and same major version**
- [ ] The container image tag is pinned (`postgres:16.4-alpine`, never `:latest`)
- [ ] Nothing in `conftest.py` or CI silently swaps in SQLite / H2 / an in-memory driver
- [ ] `create_all()` / `sync_db()` is not used in place of migrations anywhere
- [ ] Extensions production relies on (`pg_trgm`, `citext`, `postgis`, …) are installed in the test image
- [ ] The test database's **collation and encoding** match production (`lc_collate`, `lc_ctype`, `ENCODING`) — this alone changes `ORDER BY` results and index usability

**If you are on a substitute today, these are the five that never raise an error**
(measured; each returned a different answer on both engines with nothing logged):

| Divergence | Substitute (SQLite) | PostgreSQL |
|---|---|---|
| `SUM` over `NUMERIC(10,2)` | `10.305000000000001` (float) | `10.31` (exact decimal) |
| `LIKE 'ADA%'` vs `'ada@…'` | matches 1 row | matches 0 rows |
| `ORDER BY name LIMIT 2` | `['Bob', 'Zoe']` | `['ada', 'Bob']` |
| next id after a rolled-back `INSERT` | `2` — reused | `3` — sequences never roll back |
| re-read in one txn after another commits | `100` then `100` | `100` then `555` |

Five more (`'12 units'` into `INTEGER`, 30 chars into `VARCHAR(10)`, divide by zero,
orphan FK row, bare column in `GROUP BY`) are **rejected by PostgreSQL** — green suite,
`500` in production. Grep your codebase for each pattern before you migrate the suite.

**Not a divergence:** multiple `NULL`s in a `UNIQUE` column behave identically. Do not
build an audit list — it will contain the wrong things.

---

## 2. Schema: migrate forward, never load a dump

- [ ] Test setup runs the **real migration tool** (`alembic upgrade head`, `migrate up`) once per session
- [ ] `schema.sql` / `structure.sql` is **not** the source of truth for test databases
- [ ] If a dump exists for speed, CI regenerates it from `head` and fails on any diff
- [ ] Migrations are squashed deliberately when slow — never bypassed
- [ ] A separate CI job runs migrations against a **restore that already contains rows**
- [ ] That job asserts each backfill's invariant (e.g. `SELECT count(*) FROM orders WHERE currency IS NULL` = 0)

> A schema dump can never exercise a data migration. Measured: after a partial backfill,
> the migrated database had **300 of 400 orders with `currency IS NULL`**; the dump-loaded
> database reported **0 of 0**. It was not passing the test — it had no rows to fail it.

A green schema diff does **not** close this. Only data does.

---

## 3. Isolation between tests

Default to **transaction rollback**. Measured over 200 tests, 240-row fixture:

| Strategy | stmts/test | row changes/test | commits | Cannot undo |
|---|---|---|---|---|
| recreate schema | 260.0 | 242.1 | 200 | — (nothing) |
| truncate + reseed | 251.0 | 481.9 | 200 | sequences without `RESTART IDENTITY`; schema changes |
| **transaction rollback** | **5.0** | **2.1** | **0** | **committed writes, sequences, anything outside the DB** |
| template copy | 3.0 | 2.1 | 0 | — (plus 40,960 bytes copied per test) |

- [ ] Each test runs inside a transaction that is rolled back, not committed
- [ ] The fixture seeds **once per session**, not per test
- [ ] Nothing in the test path calls `TRUNCATE` or `DROP` per test
- [ ] Tests asserting on a specific autoincrement id have been removed — sequences do not roll back on any engine
- [ ] Side effects outside the database (files, mail, cache, object storage) are isolated separately; rollback does not touch them

---

## 4. The rollback lie — check this today

If you use rollback isolation and **any** repository or service method calls `commit()`,
you probably have this bug and your suite is green.

- [ ] Sessions are created with `join_transaction_mode="create_savepoint"` (SQLAlchemy 2.0)
- [ ] …or the 1.4 equivalent: an `after_transaction_end` listener that restarts the nested transaction
- [ ] Verified by hand: a test that calls a committing repository leaves **0 rows** behind

```python
# The check. Run it once. It takes two minutes and it is decisive.
def test_rollback_is_not_a_lie(db):
    ProductRepo(db).create("probe-sku")   # a method that calls commit()
    # ...then, in a SECOND test that runs after it:
def test_catalogue_starts_empty(db):
    assert db.execute(text("SELECT count(*) FROM products")).scalar() == 0
```

Measured on a 200-test suite with 3 committing tests: **3 rows survived the rollback,
0 failures reported.** In file order the suite is green **100% of the time, for ever**.
Shuffled 400 times, **378 runs (94.50%) caught it**; the chance three shuffled runs all
miss it is **0.02%**. After the savepoint fix: **0 rows leaked, 400/400 green**, with the
repositories still calling `commit()`.

- [ ] `pytest-randomly` (or `-p no:randomly` removed) is **on** in CI, permanently
- [ ] The first red build after enabling it was read, not re-run

---

## 5. Concurrency — at least one test, on purpose

Most suites have zero. Of the six legal interleavings of two read-modify-write
transactions over one row, **four lose an update** (measured: 105, 110, 105, 110 against
a correct 115) — and the two that pass are exactly the two a serial test explores.

- [ ] At least one test drives **two connections step by step from one thread** (no threads, no `sleep`)
- [ ] It asserts the interleaved schedule, not just the serial one
- [ ] Rows contended by concurrent writers carry a **version column**, and the write is
      `UPDATE … SET v = ?, ver = ver + 1 WHERE id = ? AND ver = ?`
- [ ] `rowcount == 0` is treated as a conflict and retried — never ignored
- [ ] Retry counts are observable, so contention shows up as a metric rather than as latency

Measured with the version column: all six schedules end at 115; an 8-worker run went from
**25 of 200 to exactly 200 of 200, with 175 retries.**

---

## 6. Speed — in this order, and only in this order

- [ ] **1.** Transaction rollback per test (removed **95,959 row changes and 200 commits** from a 200-test run)
- [ ] **2.** One container per **session**, not per test; function-scoped data
- [ ] **3.** One database per parallel worker, cloned via `CREATE DATABASE … TEMPLATE`
- [ ] **4.** `fsync=off`, `full_page_writes=off`, `synchronous_commit=off`, data dir on `tmpfs`

```python
PostgresContainer("postgres:16.4-alpine").with_command(
    "postgres -c fsync=off -c full_page_writes=off -c synchronous_commit=off"
).with_tmpfs({"/var/lib/postgresql/data": "rw,size=512m"})
```

- [ ] Workers do **not** share one database. Measured: 4 of 4 workers refused with
      `database is locked`; 0 of 4 with a database each. PostgreSQL *blocks* instead of
      erroring, so the failure lands minutes later on the wrong test.
- [ ] `CREATE DATABASE … TEMPLATE` failures (`55006 object_in_use`) are handled — the
      session fixture must disconnect from the template before workers clone it
- [ ] CI service containers have a **health check** (`pg_isready`); "running" is not "accepting connections"

Deleting integration tests is **not** on this list. Do all four first.

---

## 7. If you must keep a fast substitute

- [ ] It is justified in writing, with the divergence table from §1 attached
- [ ] SQLite tables are declared `STRICT` (closes type affinity only — not collation,
      `LIKE`, `NUMERIC`, sequences, `GROUP BY` strictness or the isolation model)
- [ ] **One shared contract test suite runs against both the substitute and the real engine**
- [ ] That suite runs against the real engine on every merge, not nightly
- [ ] Money, ordering, search and identity assertions run **only** against the real engine

> A substitute is safe exactly when something independently verifies that it still
> matches. Without that, it is a second implementation of someone else's contract,
> maintained by you and verified by nobody.

---

## 8. Sign-off

- [ ] Same engine, same major version, pinned image
- [ ] Migrations run forward; a data-bearing migration job exists in CI
- [ ] Rollback isolation, with savepoint-joined sessions verified by hand
- [ ] Test order randomised in CI
- [ ] At least one deliberate two-connection test
- [ ] One database per worker; container per session; durability off
- [ ] No test asserts a specific sequence value
