---
name: checklist-resource-modeling
description: A design-review checklist for a REST resource model — catches verb-in-URL anti-patterns, over-nesting, and statelessness violations before they ship in a contract you can't change
phase: 02
lesson: 01
---

# Resource-Modeling Review Checklist

Run this before you freeze a new set of endpoints. Once a URL is public, every row
below is expensive to change — the point is to catch it at design time.

## URIs name things, methods do things

- [ ] Every path segment is a **noun**, not a verb. No `/createOrder`, `/getUser`,
      `/orders/7/delete`. The verb comes from the HTTP method.
- [ ] Collections are **plural and consistent**: `/orders`, `/orders/{order_id}`.
      Not a mix of `/order` and `/users`.
- [ ] Path parameters identify a resource; they are **not** used to smuggle an
      action (`/orders/7/cancel` is a deliberate controller sub-resource, not a
      random verb — see below).
- [ ] IDs in the path are opaque to the client. Don't leak an auto-increment integer
      if it exposes row counts you'd rather not publish.

## Nesting and relationships

- [ ] Nesting is **two levels at most** (`/orders/{id}/line-items`). Deeper than that
      (`/restaurants/1/menus/2/sections/3/items/4`) is fragile.
- [ ] A child is nested only when it **can't exist without its parent**.
- [ ] An entity with its own global ID, queried across parents, is **top-level with a
      filter** (`GET /orders?customer_id=42`), not buried (`/customers/42/orders`).

## Verbs, status codes, statelessness

- [ ] Each resource supports the **correct methods** with the correct success codes
      (POST → `201` + `Location`; DELETE → `204`; see lesson 02).
- [ ] **GET never mutates state.** No side effects behind a safe method.
- [ ] No request depends on **server-side session memory**. State the server needs
      arrives in the request (token, IDs) or lives in a shared store as a resource.
- [ ] Non-CRUD transitions (cancel, capture, merge) are modeled deliberately: a
      **controller sub-resource** `POST /orders/{id}/cancel`, a state `PATCH`, or an
      **action-as-resource** `POST /orders/{id}/cancellations` — not an invented verb.

## Sanity pass

- [ ] Could a new consumer guess the URL for "one order" after seeing "list orders"?
- [ ] Does the design sit at **Richardson level 2** (resources + verbs + status codes)?
- [ ] Which Fielding constraint does each questionable endpoint break, and what does
      that cost (caching? horizontal scaling? client coupling?)?
