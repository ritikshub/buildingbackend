---
name: checklist-event-design
description: A design-review checklist for an event-driven system - message classification, event naming and ownership, payload style, saga and compensation coverage, and the discoverability questions you must be able to answer without grepping
phase: 6
lesson: 11
---

# Checklist — Event-Driven Design Review

Run this against a design doc *before* the topics exist, and against the live system once a
quarter. Anything unchecked is either a deliberate, written-down decision or a defect.

Notation used throughout: `T1..Tn` are the forward steps of a business transaction, `Ci` is the
compensation for step `Ti`.

---

## Part 1 — Message classification (do this per message, not per service)

- [ ] Every message on every topic and queue is classified in writing as **event**, **command**,
      or **query**.
- [ ] Apply the naming test: **event** = past tense (`OrderPlaced`); **command** = imperative
      (`PlaceOrder`); **query** = interrogative (`GetOrder`). Names that fail the test are
      renamed or reclassified — not both left ambiguous.
- [ ] Apply the intent test to anything called an event:
      **could the producer have written this message without knowing the consumer exists?**
      If no, it is a command. Reclassify it.
- [ ] No message named as an event has exactly one plausible handler that the producer chose.
- [ ] Commands over a broker are **labelled as commands**. They are legitimate — durability,
      buffering, retries — but they break only *temporal* and *load* coupling. Do not record
      them as "decoupled".
- [ ] No queries are being served over the broker via a correlated reply queue. If a producer
      blocks on a reply, this is synchronous communication and must be costed as such
      (availability multiplies; the receiver must be up *now*).

| | Event | Command | Query |
|---|---|---|---|
| Intent | a fact that happened | an instruction | a request for data |
| Recipients | 0..N, unknown to sender | exactly 1, known | exactly 1, known |
| Rejectable? | no | yes | n/a |
| Dependency points | consumer -> contract | producer -> consumer | caller -> callee |

---

## Part 2 — Event design

- [ ] Named as a **business fact a domain expert would recognise**, past tense, in the domain's
      language. Not `OrdersRowUpdated`. Not `ProcessStep2Complete`.
- [ ] **Not a mirror of a database row.** A CDC-shaped event publishes your schema as an API and
      forces consumers to reverse-engineer intent from a diff. The event should carry *why*.
- [ ] **Ownership is unambiguous**: exactly one bounded context (the one where the fact becomes
      true) owns the event and approves changes to it. Write the owning team's name next to it.
- [ ] There is **no shared, unowned `events` package** that several teams commit to.
- [ ] **Versioned**, with a written compatibility policy (see lesson 12).
- [ ] **Immutable.** Corrections are new events (`OrderRepriced`, `ChargeReversed`), never edits.
- [ ] Carries the **aggregate id**, and that id is the **partition key** (lesson 7), so per-entity
      ordering holds while different entities process in parallel.
- [ ] Carries **trace context** (`traceparent`, lesson 2 / phase 10). In a choreographed system
      this is the only artifact describing the flow end to end.
- [ ] Granularity is **coarse and business-shaped**: one `OrderPlaced`, not five field-change
      events consumers must reassemble in order.
- [ ] **Not a god event**: no `change_type` discriminator with forty optional fields whose schema
      is the union of every consumer's wish list.

---

## Part 3 — Payload style is a deliberate choice

- [ ] The style is recorded per event stream, with the reason:

| Style | Choose when | Accept that |
|---|---|---|
| **Notification** (id only) | 1-2 consumers; payload too large or too sensitive to broadcast; "go look" semantics | consumers must call back, which reintroduces synchronous + spatial coupling at the producer |
| **State transfer** (self-contained) | the default for cross-service integration | events are larger, data is duplicated and goes stale, and the payload is now a contract |
| **Event sourcing** (log is the record) | history *is* the product: ledgers, audit, temporal queries | schema evolution is permanent, GDPR deletion needs crypto-shredding, projections and snapshots must be built and rebuilt |

- [ ] If **notification**: count the callbacks. `consumers x events/sec` extra load lands on the
      producer, and the producer's availability is now on every consumer's critical path.
- [ ] If **state transfer**: each field in the payload is a field somebody depends on. Confirm
      someone owns removing fields, not just adding them.
- [ ] If **event sourcing**: confirm it was chosen because history is the product, **not**
      because someone wanted decoupling. Styles 1 and 2 give decoupling for a fraction of the
      cost, and un-event-sourcing a system is a rewrite.

---

## Part 4 — Flow ownership

- [ ] For each multi-service business process, the choice of **choreography or orchestration** is
      written down with its justification.

| Signal | Favours choreography | Favours orchestration |
|---|---|---|
| Participants | 2-3 | 4 or more |
| Complexity | linear | branches, parallelism, timeouts |
| Compensation needed | no | **yes** |
| "Where is instance X?" asked | rarely | daily |
| Rate of change | rare | a step every few months |

- [ ] **The flow is documented somewhere a human can read** — a diagram, a state machine, a
      README — and that document has an owner and a review date. "It's in the subscriptions"
      does not count.
- [ ] Under choreography: someone has drawn the **full reaction graph** and confirmed there are
      no cycles. `A -> B -> C -> A` is easy to create when nobody can see the whole picture.
- [ ] Under orchestration: the coordinator has **not** accreted business logic that belongs in
      the participants, and is not the component every team must edit to ship anything.
- [ ] The split is deliberate: choreography *between* bounded contexts, orchestration *within* a
      business transaction that must unwind as a unit.

---

## Part 5 — Sagas and compensation

For every business transaction spanning more than one service:

- [ ] It is written down as an explicit saga: **`T1..Tn` with a `Ci` for each compensatable step.**
- [ ] Every compensatable step has a **named, implemented, tested compensation**. Not a comment.
      Not a ticket.
- [ ] Each compensation is described as a **business action**, and the business has signed off:

      ```text
      T2  capture $89.98            C2  issue refund - new ledger record, 3-5 days,
                                        processor fee NOT returned (finance signed off)
      T3  reserve 2 units           C3  release reservation - stock may be taken by another order
      ```

- [ ] The **pivot step** is identified: the last irreversible action. Steps before it are
      *compensatable*; steps at or after it are *retriable until success*.
- [ ] **Non-compensatable steps are ordered last.** Charge before dispatch. Dispatch before the
      confirmation email. If an irreversible step sits early in the sequence, reorder it.
- [ ] Forward steps and compensations are both **idempotent** (lesson 6), keyed on
      `(saga_instance, step)`, and safe to run five times.
- [ ] Compensations run in **reverse order** (`Cj, Cj-1, ... C1`).
- [ ] **Intermediate states are first-class**: a semantic lock (`PAYMENT_PENDING`, `RESERVED`, an
      authorisation hold) marks in-flight records, and every other reader and writer of that
      record checks it. A saga is ACD, not ACID — there is no isolation.
- [ ] **Every semantic lock has a TTL and a sweeper.** A `RESERVED` row with no expiry is a stock
      leak the first time a saga dies mid-flight.
- [ ] Compensation failure is designed for:
      - [ ] retry budget measured in **hours or days**, not seconds
      - [ ] a **separate dead-letter queue** from normal traffic, with its own alert and owner
      - [ ] a defined **human escalation** after the budget expires
      - [ ] the worst case is "a customer is owed money, there is a record, it is assigned" —
            never silent data corruption
- [ ] The saga's own state is durable, and the coordinator writes intent **before** acting, so a
      crash between "sent the command" and "recorded that I sent it" recovers correctly.

---

## Part 6 — Discoverability (the questions that fail in production)

- [ ] **"Who consumes this event?"** is answerable without grepping — a registry, a schema
      catalogue, generated consumer-group listings, or broker subscription metadata.
- [ ] **"What happens when X is placed?"** is answerable from one artifact, not fourteen repos.
- [ ] **"Where is instance 4471 right now?"** is answerable by a query (orchestration) or a
      trace lookup (choreography), and someone has actually tried it this quarter.
- [ ] **"Who approves a change to this schema?"** has a name attached.
- [ ] A breaking change to an event cannot reach production without the consumers being known.
      If the last five incidents include "we renamed a field and five services broke", this
      control does not exist.

---

## Part 7 — Should this be event-driven at all?

Stop and reconsider if any of these is true:

- [ ] An invariant requires **immediate, isolated enforcement** ("two people must not book seat
      14C"). A saga's lack of isolation means the half-state *will* be observed. Keep the data in
      one place and use a real transaction.
- [ ] It is **simple CRUD with no interested third parties.** An event with zero subscribers is
      pure cost.
- [ ] The team is small enough that the **fixed overhead** — broker, schema governance,
      idempotency, tracing, saga state — exceeds the coupling being removed. A modular monolith
      with in-process events splits later along seams you have already drawn.
- [ ] **Consumers are not yet idempotent.** At-least-once delivery means duplicates; this is an
      entry fee, not an optimisation.
- [ ] **Requests are not yet traceable across services.** In a choreographed system, the first
      incident will be unresolvable.

---

## The one-line record

Put this next to every event in the design doc so the decisions survive the people who made them:

```text
<EventName>  v<N>  owner: <team / bounded context>
  classification: EVENT | COMMAND | QUERY   (intent test: <passes | fails because ...>)
  style:          notification | state transfer | event sourced   because <reason>
  partition key:  <aggregate id>            ordering guarantee: <per-key>
  consumers:      <list, or "registry link">
  part of saga:   <saga name, step Ti>  compensation Ci: <business action, signed off by <name>>
```
