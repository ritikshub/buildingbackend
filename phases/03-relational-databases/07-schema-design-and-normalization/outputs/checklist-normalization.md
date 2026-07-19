---
name: checklist-normalization
description: A step-by-step checklist to normalize a table to 3NF, spot the three anomalies, and decide whether a denormalization is justified
phase: 03
lesson: 07
---

# Normalization Checklist

Point this at any table (existing or proposed) to drive it to 3NF and catch the
redundancy that causes anomalies. Work top to bottom.

## Smell test: is this table already sick?

- [ ] Is any fact (a customer's email, a product's name) repeated across multiple rows?
      → redundancy → anomalies are coming.
- [ ] Can you *not* add an entity because it has no parent row yet? → insertion anomaly.
- [ ] Would deleting one row silently erase an unrelated fact? → deletion anomaly.
- [ ] Does updating one real-world fact require touching many rows? → update anomaly.

## 1NF — atomic values

- [ ] Every cell holds a single value (no comma-separated lists, no JSON blob standing in
      for what should be rows).
- [ ] No repeating columns (`item1`, `item2`, `item3`) — those become rows in a child
      table.

## 2NF — no partial dependencies (only matters with a composite key)

- [ ] Identify the primary key. If it's a single column, 2NF is automatic — skip ahead.
- [ ] For a composite key, check each non-key column: does it depend on the **whole** key,
      or just part of it?
- [ ] Any column depending on only part of the key → move it to a table where that part is
      the whole key.

## 3NF — no transitive dependencies

- [ ] For each non-key column, ask: does it depend on the primary key, or on **another
      non-key column**?
- [ ] Any column depending on a non-key column (key → A → B) → move it to a table keyed by
      A, and keep A as a foreign key here.
- [ ] Recite the mnemonic against every non-key column: does it depend on *the key, the
      whole key, and nothing but the key*?

## Wire it back together

- [ ] Each new table has its own primary key (Lesson 5).
- [ ] Foreign keys link the decomposed tables, with `REFERENCES` so integrity is enforced
      (Lesson 6).
- [ ] The top queries you need can still be answered by joining the normalized tables.

## Should you denormalize? (only after the above)

Only reintroduce duplication if ALL of these are true:

- [ ] You have a **measured** read-performance problem on a hot path (not a guess).
- [ ] You already tried an **index** (Lesson 9) and it wasn't enough.
- [ ] You can name **who keeps the duplicate in sync** (app code, trigger, or scheduled
      job) and accept the extra write complexity.
- [ ] The duplication is intentional and documented — not the accidental wide-table trap.

If any box is unchecked, stay normalized.
