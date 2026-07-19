---
name: checklist-migration-safety
description: A pre-merge safety checklist for a database migration that will run against a live production database during a rolling deploy
phase: 03
lesson: 15
---

# Migration Safety Checklist

Run this before merging any migration that will hit a live, in-use database. The guiding
question: *while old and new code run at the same time, does every step stay safe?*

## Is it a proper migration at all?

- [ ] It's a versioned file in the repo (not a hand-run `ALTER`), reviewed in a PR.
- [ ] It runs inside a transaction, so a failure leaves nothing half-applied.
- [ ] It's immutable once merged — if it's already run anywhere, you write a NEW migration
      instead of editing this one.
- [ ] Running the migrator twice is a no-op (idempotent).

## Backward compatibility (old code is still running!)

- [ ] The change is compatible with the **currently deployed** code, not just the new code.
- [ ] No column/table the running code still reads or writes is dropped or renamed in this
      step.
- [ ] If renaming/removing, it's split into expand-contract stages across releases:
      **expand** (add) → **backfill** → **switch code** → **contract** (drop), each shipped
      separately.

## Locking & big-table hazards

- [ ] Adding a column? It's **nullable or has a default** — not `NOT NULL` with no default
      on a large table (that can rewrite/lock it). Add the constraint in a later step after
      backfilling.
- [ ] Creating an index on a large table? Use the **non-blocking** variant
      (`CREATE INDEX CONCURRENTLY` in Postgres) so it doesn't lock writes.
- [ ] Adding a constraint on a large table? Add it `NOT VALID`, then `VALIDATE` separately,
      to avoid a long blocking scan.

## Data backfills

- [ ] Backfills are **separated** from the schema change (own migration or own step).
- [ ] Large backfills are **batched** (a few thousand rows per loop, committing between),
      not one giant `UPDATE` that holds locks and bloats the WAL.
- [ ] The backfill is safe to re-run / resume if interrupted.

## Reversibility & recovery

- [ ] There's a `down` (or a documented forward-fix plan) for structural changes.
- [ ] Destructive steps (drops, deletes) are scheduled **as late and separate as possible**,
      so there's time to catch a mistake while the old data still exists.
- [ ] You accept that data-destructive steps can't be undone by `down` — the plan is
      **roll forward**, not back.

## Before it ships

- [ ] Tested against a copy with production-like data volume (not just an empty dev DB).
- [ ] You know roughly how long it takes and whether it locks anything, on the real table
      size.
- [ ] The deploy order (migration before/with/after the code) is decided and correct.

## Red flags — stop and restage

- `ALTER TABLE ... RENAME` or `DROP COLUMN` on a table the live code still uses.
- `ADD COLUMN ... NOT NULL` with no default on a big table.
- A single `UPDATE`/`DELETE` touching millions of rows.
- Editing a migration that has already run in any environment.
