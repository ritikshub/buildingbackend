---
name: checklist-graph-fit
description: A checklist for deciding whether a problem is genuinely graph-shaped, modeling nodes and edges, and knowing when a relational join or a recursive CTE is the cheaper right answer instead of a dedicated graph database
phase: 04
lesson: 06
---

# Graph Database Fit & Modeling Checklist

The graph model is seductive — everything is connected, so everything *looks* like a graph. Run
this before you add a graph database, because the common mistake is reaching for one when a join
(or a recursive CTE) in the database you already run would do.

## Step 0 — Is this genuinely a graph problem?

- [ ] Your core queries are **traversals**: "friends of friends," "within N hops," "shortest path,"
      "any path," "which nodes reach X."
- [ ] The traversals are **deep or variable-length** — **3+ hops, or an unknown number of hops** —
      where a relational self-join's `dᵏ` blow-up actually bites.
- [ ] The **relationships themselves** are the valuable data (their type, direction, weight,
      history), not just a link between two rows.

If your relationships are **shallow and fixed** (one or two hops, known in advance) — "a user has
posts," "an order has line items" — **stop**: a foreign key is already a one-hop edge and a join is
the right tool. Adding a graph database buys you only a second system to run.

## Step 1 — Try the cheaper relational option first

- [ ] For **bounded** traversal, a Postgres **recursive CTE** (`WITH RECURSIVE`) can walk a fixed
      number of hops without a new database.
- [ ] The **Apache AGE** extension adds a real property graph and Cypher **inside Postgres**;
      **pgRouting** does pathfinding on graph data in Postgres.
- [ ] Reach for a **dedicated** graph database (Neo4j, Neptune, TigerGraph) only when the traversals
      are **deep, hot, and central** to the product — recommendations, fraud rings, knowledge graphs.

## Step 2 — Model the graph (nodes, edges, properties)

- [ ] **Nodes** = the entities you traverse *between* (User, Account, Product, Merchant). Give each a
      **label** (its type) and **properties**.
- [ ] **Edges** = the relationships, and they are **typed and directed** (`FOLLOWS`, `USED_AT`,
      `DEPENDS_ON`). Put data that belongs to the *relationship* (weight, since, amount) **on the
      edge**, not on the nodes.
- [ ] Decide direction deliberately — `A FOLLOWS B` is not `B FOLLOWS A`. Store an undirected
      relationship as two directed edges if traversal must go both ways.
- [ ] Keep **entities as nodes, not properties** if you'll ever traverse to them (a `city` you filter
      by can be a property; a `city` you traverse a supply chain through should be a node).

## Step 3 — Design the traversals and guard the failure modes

- [ ] Write each query as a traversal: start node, edge types to follow, max depth, what to return.
- [ ] **Bound your depth.** An unbounded `[:REL*]` on a dense graph can walk the whole thing — cap
      the hop count (`*1..4`) unless you truly need "any path."
- [ ] **Watch for supernodes** — a node with an enormous degree (a celebrity, a hub, a popular tag).
      It's the graph's version of a hot partition: traversals *through* it fan out into millions of
      edges. Filter, sample, or cap fan-out around them.

## Step 4 — Plan to run it alongside, not instead of, your relational store

- [ ] Keep the **transactional source of truth** (orders, payments, anything needing ACID) in the
      relational database.
- [ ] Put only the **relationship-heavy, deep-traversal slice** in the graph.
- [ ] Decide how the graph stays in sync with the source of truth (this is the polyglot-persistence
      problem — Lesson 8: dual writes, outbox, or CDC).

## Traps to avoid

- [ ] **Cargo-culting the graph** for one-hop relationships a join handles.
- [ ] **Unbounded traversals** that walk the entire graph.
- [ ] **Supernodes** blowing up fan-out.
- [ ] Treating the graph database as the **system of record** for data that needs strong
      transactional guarantees.

## Decision shortcut

> Deep or variable-length traversal (3+ / unknown hops), relationships-as-data → graph database.
> One or two fixed hops → a foreign key + join, or a recursive CTE in Postgres.
> Model entities as nodes, relationship data on edges, bound the depth, avoid supernodes,
> and run it alongside the relational source of truth (Lesson 8).
