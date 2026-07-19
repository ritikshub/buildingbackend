# Schema Design & Normalization

> Store every fact in exactly one place. That single discipline — normalization — is what stops your data from quietly contradicting itself, and it falls out of one question asked over and over: *what does this column actually depend on?*

**Type:** Learn
**Languages:** SQL
**Prerequisites:** [Constraints & Data Integrity](../06-constraints-and-integrity/)
**Time:** ~60 minutes

## The Problem

The naïve instinct, when you have orders to store, is one big table with everything on it:

| order_id | customer_name | customer_email | product | unit_price | qty |
|---|---|---|---|---|---|
| 1 | Ada Lovelace | ada@x.org | Widget | 9.99 | 2 |
| 2 | Ada Lovelace | ada@x.org | Gadget | 14.99 | 1 |
| 3 | Grace Hopper | grace@y.mil | Widget | 9.99 | 5 |

It looks convenient — everything about an order in one row. But it's a trap, and the trap
springs three ways:

- **Update anomaly.** Ada changes her email. It's stored on *every* order she's ever
  placed. Miss one row and your database now says Ada has two different emails — and which
  one is true? The data contradicts itself.
- **Insertion anomaly.** A new customer signs up but hasn't ordered yet. You *can't add
  them* — there's no order row to attach them to. To store a customer you're forced to
  invent a fake order.
- **Deletion anomaly.** Grace cancels her only order and you delete the row. You didn't
  mean to forget she exists — but you just did. The customer's data vanished with the order.

Every one of these is caused by the same root problem: **a fact is stored in more than one
place**, or **two unrelated facts are trapped in the same row**. Ada's email is a fact
about *Ada*, not about each order — yet it's copied onto every order. **Normalization** is
the systematic cure: decompose tables so that each fact lives in exactly one place. This
lesson is that process, and — just as important — when to stop.

## The Concept

### Functional dependencies: what determines what

The whole theory rests on one idea. A **functional dependency** `X → Y` ("X determines Y")
means: if you know X, you know exactly one Y. Knowing an `order_id` determines the order's
date. Knowing a `product_id` determines its name and price. Knowing a `customer_id`
determines that customer's email.

Normalization is just the discipline of arranging tables so that **every non-key column
depends on the primary key — the whole key, and nothing but the key.** When a column
depends on something *other* than its table's key, it's in the wrong table, and that
misplacement is exactly what causes the anomalies. Read that italicized sentence again;
the three normal forms below are just its three failure modes.

### First Normal Form (1NF): atomic values, no repeating groups

A table is in **1NF** when every cell holds a **single, atomic value** — no lists crammed
into a cell, no repeating columns like `product1, product2, product3`. This is really the
relational rule from Lesson 3 restated. The violation and its fix:

```sql
-- NOT 1NF: a list stuffed into one cell
-- order(id=1, products='Widget, Gadget, Gizmo')

-- 1NF: one row per value, in a related table
-- order_line(order_id=1, product='Widget')
-- order_line(order_id=1, product='Gadget')
-- order_line(order_id=1, product='Gizmo')
```

Why it matters: you can't index, constrain, join on, or aggregate a value buried in a
comma-separated string. 1NF makes every value first-class.

### Second Normal Form (2NF): no partial dependencies

2NF only bites when you have a **composite key** (a primary key made of several columns,
Lesson 5). A table is in **2NF** if it's in 1NF *and* every non-key column depends on the
**whole** key, not just part of it. Consider a line-items table keyed on
`(order_id, product_id)`:

| order_id | product_id | product_name | qty |
|---|---|---|---|
| 1 | 100 | Widget | 2 |
| 3 | 100 | Widget | 5 |

`product_name` depends only on `product_id` — *half* the key. So Widget's name is
duplicated across every order line containing it (a **partial dependency**), and renaming
the product means updating many rows. Fix: move `product_name` to a `product` table where
`product_id` is the whole key.

### Third Normal Form (3NF): no transitive dependencies

A table is in **3NF** if it's in 2NF *and* no non-key column depends on **another non-key
column** (a **transitive dependency**: key → A → B). Suppose an orders table stores:

| order_id | customer_id | customer_email |
|---|---|---|
| 1 | 7 | ada@x.org |
| 2 | 7 | ada@x.org |

Here `order_id → customer_id → customer_email`. `customer_email` doesn't really depend on
the *order*; it depends on the *customer*, who is a non-key column here. That's why Ada's
email is duplicated across her orders — the update anomaly from the top of the lesson. Fix:
`customer_email` belongs in a `customer` table keyed by `customer_id`; the order keeps only
`customer_id` as a foreign key.

The classic mnemonic (Bill Kent, 1983) captures 2NF and 3NF together: **every non-key fact
must depend on "the key, the whole key, and nothing but the key."** Whole key = 2NF;
nothing but the key = 3NF.

### BCNF and beyond, briefly

**Boyce-Codd Normal Form (BCNF)** is a slightly stricter 3NF: *every* determinant (anything
that determines another column) must be a candidate key. It matters in edge cases with
overlapping candidate keys; for the vast majority of schemas, **3NF is the practical
target** and usually gives you BCNF for free. Higher forms (4NF, 5NF) address multi-valued
and join dependencies and rarely come up day to day. Aim for 3NF and you've eliminated the
anomalies that actually bite.

### The normalized result

Applying this to the wide orders table decomposes it into four clean tables, each fact in
one home:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 720 452" width="100%" style="max-width:720px" role="img" aria-label="An entity relationship diagram of CUSTOMER, ORDERS, PRODUCT and ORDER_LINE with their primary, foreign and unique keys and the relationships between them." font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
  
  <text x="360.0" y="26" text-anchor="middle" font-size="14" font-weight="700">Normalized schema — each fact in exactly one home</text>
  <g fill="none">
  <path d="M48 92 L 246 92" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M474 92 L 672 92" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M48 330 L 246 330" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M474 330 L 672 330" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M256 116.0 L 464 116.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M256 354.0 L 464 354.0" fill="none" stroke="currentColor" stroke-width="1.6"/>
  <path d="M573.0 170 L 573.0 300" fill="none" stroke="currentColor" stroke-width="1.6"/>
  </g>
  <g>
  <rect x="38" y="62" width="218" height="108" rx="10" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2" stroke-linejoin="round"/>
  <rect x="464" y="62" width="218" height="108" rx="10" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="38" y="300" width="218" height="108" rx="10" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f" stroke-width="2" stroke-linejoin="round"/>
  <rect x="464" y="300" width="218" height="108" rx="10" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2" stroke-linejoin="round"/>
  </g>
  <g>
  <text x="147.0" y="82" font-size="12.5" text-anchor="middle" font-weight="700" >CUSTOMER</text>
  <text x="54" y="109" font-size="10" text-anchor="start" opacity="0.9" >id : bigint</text>
  <text x="240" y="109" font-size="9.5" text-anchor="end" font-weight="700" >PK</text>
  <text x="54" y="131" font-size="10" text-anchor="start" opacity="0.9" >email : text</text>
  <text x="240" y="131" font-size="9.5" text-anchor="end" font-weight="700" >UK</text>
  <text x="54" y="153" font-size="10" text-anchor="start" opacity="0.9" >name : text</text>
  <text x="573.0" y="82" font-size="12.5" text-anchor="middle" font-weight="700" >ORDERS</text>
  <text x="480" y="109" font-size="10" text-anchor="start" opacity="0.9" >id : bigint</text>
  <text x="666" y="109" font-size="9.5" text-anchor="end" font-weight="700" >PK</text>
  <text x="480" y="131" font-size="10" text-anchor="start" opacity="0.9" >customer_id : bigint</text>
  <text x="666" y="131" font-size="9.5" text-anchor="end" font-weight="700" >FK</text>
  <text x="480" y="153" font-size="10" text-anchor="start" opacity="0.9" >placed_at : timestamptz</text>
  <text x="147.0" y="320" font-size="12.5" text-anchor="middle" font-weight="700" >PRODUCT</text>
  <text x="54" y="347" font-size="10" text-anchor="start" opacity="0.9" >id : bigint</text>
  <text x="240" y="347" font-size="9.5" text-anchor="end" font-weight="700" >PK</text>
  <text x="54" y="369" font-size="10" text-anchor="start" opacity="0.9" >name : text</text>
  <text x="54" y="391" font-size="10" text-anchor="start" opacity="0.9" >unit_price : numeric</text>
  <text x="573.0" y="320" font-size="12.5" text-anchor="middle" font-weight="700" >ORDER_LINE</text>
  <text x="480" y="347" font-size="10" text-anchor="start" opacity="0.9" >order_id : bigint</text>
  <text x="666" y="347" font-size="9.5" text-anchor="end" font-weight="700" >FK</text>
  <text x="480" y="369" font-size="10" text-anchor="start" opacity="0.9" >product_id : bigint</text>
  <text x="666" y="369" font-size="9.5" text-anchor="end" font-weight="700" >FK</text>
  <text x="480" y="391" font-size="10" text-anchor="start" opacity="0.9" >qty : int</text>
  <text x="360.0" y="108.0" font-size="10" text-anchor="middle" opacity="0.9" >places</text>
  <text x="270" y="108.0" font-size="11" text-anchor="middle" font-weight="700" opacity="0.9" >1</text>
  <text x="450" y="108.0" font-size="13" text-anchor="middle" font-weight="700" opacity="0.9" >∞</text>
  <text x="360.0" y="346.0" font-size="10" text-anchor="middle" opacity="0.9" >appears in</text>
  <text x="270" y="346.0" font-size="11" text-anchor="middle" font-weight="700" opacity="0.9" >1</text>
  <text x="450" y="346.0" font-size="13" text-anchor="middle" font-weight="700" opacity="0.9" >∞</text>
  <text x="587.0" y="238.0" font-size="10" text-anchor="start" opacity="0.9" >contains</text>
  <text x="586.0" y="186" font-size="11" text-anchor="middle" font-weight="700" opacity="0.9" >1</text>
  <text x="586.0" y="290" font-size="13" text-anchor="middle" font-weight="700" opacity="0.9" >∞</text>
  </g>
  
</svg>
```

Now Ada's email lives in **one** row of `customer`. Change it once, everywhere is correct.
A customer can exist with zero orders (no insertion anomaly). Deleting an order can't erase
a customer (no deletion anomaly). Each anomaly is gone because each fact has exactly one
home — and the foreign keys and constraints from Lessons 5–6 hold the pieces together.

### When to denormalize — on purpose, with eyes open

Normalization optimizes for *correctness* by removing duplication. But it has a cost:
answering "show me each order with its customer name and product names" now requires
**joining** four tables back together, and joins take work. Sometimes, for a
read-heavy hot path, you deliberately reintroduce controlled duplication — this is
**denormalization**:

- Storing a `customer_name` snapshot on the order (also captures history: the name *at the
  time of the order*).
- Keeping a cached `order_total` column instead of summing line items on every read.
- Materializing a pre-joined view for a dashboard.

The rules for doing it sanely: **normalize first, denormalize only when a measured read
problem demands it**, and when you do, **own the duplication** — you now have two copies of
a fact and must keep them in sync (with application code, triggers, or a scheduled job),
knowingly trading write complexity for read speed. Denormalizing *by accident* (the wide
table you started with) gives you all the anomalies and none of the deliberate benefit.
Denormalizing *on purpose*, after normalizing, is a legitimate performance tool.

## Think about it

1. In the wide orders table, walk each of the three anomalies (update, insertion,
   deletion) with a concrete action and say what goes wrong. Which normal form fixes each?
2. A table `enrollment(student_id, course_id, course_title, grade)` has primary key
   `(student_id, course_id)`. Which column violates 2NF, and where should it go?
3. Explain `order_id → customer_id → customer_email` as a transitive dependency, and why
   it causes Ada's email to appear on every one of her orders.
4. Your dashboard join across five normalized tables is too slow. Before denormalizing,
   what should you try first (hint: Lesson 9)? If you do denormalize `order_total`, what new
   responsibility have you taken on?

## Key takeaways

- Cramming everything into one wide table causes **update, insertion, and deletion
  anomalies** — all rooted in a fact being stored in more than one place.
- A **functional dependency** `X → Y` means X determines Y; normalization arranges tables
  so every non-key column depends on **the key, the whole key, and nothing but the key.**
- **1NF**: atomic values, no repeating groups. **2NF**: no partial dependency on part of a
  composite key. **3NF**: no transitive dependency (non-key → non-key). **3NF is the
  practical target**; BCNF is a stricter edge-case refinement.
- A normalized schema gives each fact **exactly one home**, so a change in one place is
  correct everywhere and the anomalies disappear.
- **Denormalize deliberately, never accidentally**: normalize first, reintroduce controlled
  duplication only for a measured read problem, and then own the job of keeping the copies
  in sync.

Next: [How Data Lives on Disk: Pages, Heaps & the Buffer Pool](../08-storage-pages-and-heaps/)
— we drop below the logical model to see how rows are actually stored, the foundation every
index and transaction is built on.
