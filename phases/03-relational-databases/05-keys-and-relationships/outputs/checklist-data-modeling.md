---
name: checklist-data-modeling
description: A pre-flight checklist for turning a domain into relational tables — entities, keys, and the three relationship shapes — before you write a single CREATE TABLE
phase: 03
lesson: 05
---

# Data-Modeling Checklist

Run this before committing a schema. It turns a vague domain ("users have orders")
into tables, keys, and relationships that the database can enforce for you.

## 1. Find the entities

- [ ] List every **noun** the system tracks (user, order, product, invoice…). Each
      distinct kind of thing is usually one table.
- [ ] For each entity, is it really *one* thing, or two crammed together? (A "customer"
      row holding both account and shipping-address fields may be two entities.)

## 2. Give every table an identity (primary key)

- [ ] Every table has exactly **one** primary key.
- [ ] Default to a **surrogate key** — auto-increment `BIGINT` or `UUID` — that carries no
      business meaning and never changes.
- [ ] Only use a **natural key** as the PK when identity genuinely never changes (or for a
      junction table's composite key).
- [ ] Size integer keys for the *lifetime* max, with headroom (`BIGINT`, not `INTEGER`, if
      billions of rows are plausible).

## 3. Enforce the other unique facts (candidate keys)

- [ ] Any column that must be unique but isn't the PK (email, username, slug) gets its own
      `UNIQUE` constraint — don't rely on application code to check.

## 4. Classify every relationship, then model it

For each pair of related entities, decide the shape and apply the rule:

- [ ] **One-to-many (1:N)** → foreign key on the **many** side, `REFERENCES` the one side.
- [ ] **One-to-one (1:1)** → foreign key **+ `UNIQUE`**; or fold into one table if the
      extra columns aren't optional/large/separately-accessed.
- [ ] **Many-to-many (M:N)** → a **junction table** with a foreign key to each side
      (often a composite PK). Put facts *about the pairing* (quantity, role, joined_at)
      here.

## 5. Make every reference enforced

- [ ] Every foreign key actually declares `REFERENCES` (so the database enforces
      referential integrity — no orphans).
- [ ] Decide the `ON DELETE` / `ON UPDATE` behavior for each FK (Lesson 6): `RESTRICT`,
      `CASCADE`, or `SET NULL` — don't leave it to the default by accident.

## 6. Sanity-check with an ER diagram

- [ ] Draw it (mermaid `erDiagram`). Every connecting line should be a real foreign key.
- [ ] Walk each of the top 5 queries the app will run. Can you answer each by following
      keys? If a query needs data that isn't reachable, a relationship is missing.

## Red flags

- A column holding a comma-separated list of IDs → you need a junction table.
- The same fact duplicated across many rows → a relationship (and normalization,
  Lesson 7) is missing.
- A foreign-key column with no `REFERENCES` → integrity is now *your* job, and you will
  eventually get it wrong.
- A "natural" primary key you can imagine ever changing → switch to a surrogate now.
