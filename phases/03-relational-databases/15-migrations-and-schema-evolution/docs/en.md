# Migrations & Schema Evolution

> Your schema is not carved in stone — you'll add columns, tables, and constraints for as long as the product lives. A migration is how you make those changes **versioned, repeatable, and reviewable**, so the same change runs identically on your laptop, in CI, and on the production database serving live traffic.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Constraints & Data Integrity](../06-constraints-and-integrity/) · [Transactions & ACID](../11-transactions-and-acid/)
**Time:** ~60 minutes

## The Problem

You shipped v1 with a `users` table. Now v2 needs a `phone` column, a new `addresses`
table, and a `NOT NULL` constraint on `email`. How do those changes reach production?

The amateur answer — "log into the production database and run `ALTER TABLE` by hand" — is a
disaster in slow motion. It's unreviewed (a typo is now live), unrepeatable (staging and prod
drift apart, and the next environment you spin up is missing the change), unversioned (nobody
knows what state the schema is *in*), and un-rollback-able. And it ignores the hardest part:
production is a **live database**, often being read and written *by the old version of your
code at the same moment* the new version deploys. Change the schema carelessly and you break
requests in flight.

A **migration** solves all of this. It's a version-controlled script that transforms the
schema from one known state to the next, applied by a **runner** that tracks exactly which
migrations have run so every environment converges to the same schema. This lesson builds a
real migration runner and covers the pattern — **expand-contract** — that lets you change a
live schema without downtime.

## The Concept

### What a migration is

A **migration** is an ordered, versioned unit of schema change — typically a numbered script
with an **`up`** (apply the change) and often a **`down`** (revert it):

```sql
-- migration 003_add_phone.up
ALTER TABLE users ADD COLUMN phone VARCHAR(20);

-- migration 003_add_phone.down
ALTER TABLE users DROP COLUMN phone;
```

Migrations live in your repository next to the code, so a schema change is **code-reviewed,
tested in CI, and versioned** like any other change. The set of migrations, applied in order
from an empty database, *is* the definition of your schema — there's no separate "master
schema" that can drift.

### The migrations table: tracking what's been applied

The runner needs to know which migrations a given database has already run, so it applies each
one **exactly once** and in order. It keeps that state *in the database itself*, in a small
bookkeeping table (Rails calls it `schema_migrations`, others `_migrations` or `flyway_schema_history`):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 328" width="100%" style="max-width:700px" role="img" aria-label="A migration runner reads recorded versions from the database, applies pending migration files in order inside transactions, and records each version." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l15a-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="380.0" y="26" text-anchor="middle" font-size="14" font-weight="700">The migrations table</text>
  <g fill="none">
  <path d="M363.0 116 L 363.0 150" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15a-ah)"/>
  <path d="M598 178 L 458 178" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15a-ah)"/>
  <path d="M458 206 L 598 206" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15a-ah)"/>
  <path d="M458 234 L 598 234" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15a-ah)"/>
  </g>
  <g>
  <rect x="258" y="58" width="210" height="58" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="268" y="150" width="190" height="104" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  <path d="M598 157 a 60.0 9 0 0 1 120 0 v 90 a 60.0 9 0 0 1 -120 0 Z" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="2"/>
  <path d="M598 157 a 60.0 9 0 0 0 120 0" fill="none" stroke="#e0930f" stroke-width="2"/>
  </g>
  <g>
  <text x="363.0" y="82.9" font-size="11.5" text-anchor="middle" font-weight="700" >Migration files</text>
  <text x="363.0" y="98.9" font-size="10" text-anchor="middle" opacity="0.85" >001 · 002 · 003 · 004</text>
  <text x="363.0" y="205.9" font-size="11.5" text-anchor="middle" >Migration runner</text>
  <text x="658.0" y="210.4" font-size="11.5" text-anchor="middle" >Database</text>
  <text x="528.0" y="172.0" font-size="9.5" text-anchor="middle" opacity="0.75" >recorded versions?</text>
  <text x="528.0" y="200.0" font-size="9.5" text-anchor="middle" opacity="0.75" >apply pending (in txn)</text>
  <text x="528.0" y="228.0" font-size="9.5" text-anchor="middle" opacity="0.75" >record each version</text>
  </g>
  <text x="380.0" y="316" text-anchor="middle" font-size="11" opacity="0.9">Apply only the pending migrations, in order, each in its own transaction.</text>
</svg>
```

The algorithm is simple and idempotent: read the applied versions from the table, compute the
**pending** ones (defined but not yet applied), and run each pending migration in order — each
wrapped in a transaction (Lesson 11) so a failure leaves no half-applied change — recording
its version as it goes. Run the runner twice and the second run does nothing, because there's
nothing pending. That idempotency is what makes it safe to run on every deploy.

### The hard part: changing a *live* schema without downtime

Here's what separates a toy from production. During a deploy, there's a window where **old
code and new code run simultaneously** against the **same database**. So a migration must
never put the schema in a state that either version can't handle. The rule: **every migration
must be backward-compatible with the currently-running code.**

The pattern that makes this possible is **expand-contract** (also called parallel change).
Instead of changing a schema in one destructive step, you split it into safe stages across
*multiple* deploys:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 540 452" width="100%" style="max-width:520px" role="img" aria-label="Four safe stages: expand by adding a nullable column, backfill it in batches, deploy new code that uses it, then contract by dropping the old column." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  <defs><marker id="l15b-ah" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="270.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Expand → contract: changing a live schema safely</text>
  <g fill="none">
  <path d="M270.0 118 L 270.0 144" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15b-ah)"/>
  <path d="M270.0 210 L 270.0 236" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15b-ah)"/>
  <path d="M270.0 302 L 270.0 328" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l15b-ah)"/>
  </g>
  <g>
  <rect x="165.0" y="52" width="210" height="66" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="162.5" y="144" width="215" height="66" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="165.0" y="236" width="210" height="66" rx="9" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="165.0" y="328" width="210" height="66" rx="9" fill="#e0564f" fill-opacity="0.14" stroke="#e0564f" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="270.0" y="72.9" font-size="11.5" text-anchor="middle" font-weight="700" >1.  EXPAND</text>
  <text x="270.0" y="88.9" font-size="10" text-anchor="middle" opacity="0.85" >add new column (nullable)</text>
  <text x="270.0" y="104.9" font-size="10" text-anchor="middle" opacity="0.85" >old code still works</text>
  <text x="270.0" y="172.9" font-size="11.5" text-anchor="middle" font-weight="700" >2.  MIGRATE / BACKFILL</text>
  <text x="270.0" y="188.9" font-size="10" text-anchor="middle" opacity="0.85" >fill new column in batches</text>
  <text x="270.0" y="264.9" font-size="11.5" text-anchor="middle" font-weight="700" >3.  deploy NEW CODE</text>
  <text x="270.0" y="280.9" font-size="10" text-anchor="middle" opacity="0.85" >reads / writes new column</text>
  <text x="270.0" y="356.9" font-size="11.5" text-anchor="middle" font-weight="700" >4.  CONTRACT</text>
  <text x="270.0" y="372.9" font-size="10" text-anchor="middle" opacity="0.85" >drop the old column</text>
  </g>
  <text x="270.0" y="440" text-anchor="middle" font-size="11" opacity="0.9">Each step stays backward-compatible; the destructive drop comes last.</text>
</svg>
```

Renaming `name` to `full_name`, done safely, is four steps, not one: **expand** (add
`full_name`), **backfill** (copy `name` → `full_name` for existing rows), **switch** (deploy
code that uses `full_name`, writing both during the transition), **contract** (drop `name`
once nothing reads it). Do it in one `ALTER ... RENAME` under live traffic and every request
from the old code — still selecting `name` — breaks instantly.

### Operations that bite

Some schema changes are dangerous on a large, live table, and knowing which is a production
survival skill:

- **Adding a `NOT NULL` column with no default** — the database must fill every existing row,
  which on older systems rewrites and **locks** the whole table. Safe version: add it
  **nullable** (or with a default), backfill, then add the `NOT NULL` constraint separately.
- **Dropping or renaming a column in use** — breaks the old code still querying it. Use
  expand-contract.
- **Adding a constraint or index on a huge table** — can lock or scan the table for a long
  time. Production databases offer non-blocking variants (Postgres `CREATE INDEX CONCURRENTLY`,
  `ADD CONSTRAINT ... NOT VALID` then `VALIDATE`).
- **A giant backfill in one statement** — one `UPDATE` touching millions of rows holds locks
  and bloats the WAL. **Batch it**: update a few thousand rows at a time in a loop.

### Rollbacks are not a time machine

A `down` migration can revert a *structural* change (drop the column you added). But a
migration that **destroyed data** — dropped a column, deleted rows — can't truly be undone; the
data is gone. So the production instinct is **roll forward, not back**: for a bad migration,
write a *new* migration that fixes the problem, rather than relying on `down` to restore lost
data. Keep destructive steps (the "contract") as late and as separate as possible, so you have
time to catch a mistake while the old data still exists.

### Build It

We'll build a migration runner over SQLite: a `schema_migrations` table, a list of ordered
migrations, and a runner that applies only the pending ones — idempotently. The core is the
pending-and-apply loop:

```python
def migrate(conn, migrations):
    ensure_migrations_table(conn)
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    pending = [m for m in sorted(migrations) if m.version not in done]
    for m in pending:
        m.apply(conn)                                   # the up: DDL and/or backfill
        conn.execute("INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                     (m.version, m.name))
        conn.commit()                                   # each migration is atomic
    return [m.version for m in pending]
```

The full runner — plus migrations that create tables, and an **expand + batched backfill**
migration that adds a `status` column and fills it in for existing rows a batch at a time — is
in [`code/migrate.py`](code/migrate.py). Run it:

```bash
python migrate.py
```

It applies migrations 1–3 to a fresh database, runs the runner **again** to show it's
idempotent (0 pending), then adds migration 4 and shows only *that* one applies — and prints
the `schema_migrations` ledger so you can see exactly what ran.

### Use It

You'll use a migration tool, not hand-roll one — but they all work exactly like what you built:

- **Tools**: Flyway and Liquibase (JVM), Alembic (SQLAlchemy), Django migrations, Rails
  Active Record migrations, `golang-migrate`, Prisma Migrate. Each keeps a versions table and
  applies pending migrations in order.
- **Workflow**: write a migration → review it in a PR → CI applies it to a test database → the
  deploy pipeline applies it to production before (or as) the new code rolls out.
- **The golden rules**: migrations are **immutable once merged** (never edit a migration that's
  run somewhere — write a new one); keep them **backward-compatible** with the running code
  (expand-contract); and **separate schema changes from data backfills** so each is small and
  reversible.

Because you built the runner, "the deploy ran three pending migrations" and "we're doing an
expand-contract rename over two releases" are plans you can reason about, not incantations.

## Think about it

1. Why is running `ALTER TABLE` by hand on production worse than a migration file, on at least
   three distinct axes (repeatability, review, environment drift)?
2. You need to rename `users.name` to `users.full_name` with zero downtime while old code is
   still live. Write the four expand-contract steps in order, and say what breaks if you do it
   in one `RENAME`.
3. A migration adds a `NOT NULL` column with no default to a 50-million-row table and
   production locks up. What happened, and how would you stage the same change safely?
4. A migration accidentally dropped a column that still held needed data. Why can't the `down`
   migration save you, and what's the right recovery posture?

## Key takeaways

- A **migration** is a versioned, ordered, code-reviewed script (`up`/`down`) that evolves the
  schema; the set of migrations *is* the schema definition, so environments never drift.
- A **migration runner** records applied versions in a **migrations table** and applies only
  the **pending** ones, in order, each in a transaction — **idempotently**, so it's safe to run
  on every deploy.
- Changing a **live** schema demands **backward compatibility**: old and new code run at once,
  so use **expand-contract** (add new → backfill → switch code → drop old) instead of one
  destructive step.
- Beware operations that **lock or rewrite** big tables (`NOT NULL` with no default, dropping
  in-use columns, non-concurrent index/constraint builds, giant single-statement backfills) —
  stage them and **batch** backfills.
- **Roll forward, not back**: data-destructive migrations can't be truly undone, so keep
  destructive steps late and separate, and fix bad migrations with new ones.

Next: [Capstone: A Mini Relational Engine on a B-Tree](../16-mini-relational-engine/) — we
assemble pages, a B-tree, transactions, and a WAL into one small working database engine.
