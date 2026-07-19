# Event-Driven Architecture: Commands, Choreography & Sagas

> You have queues, topics, a replayable log, idempotent consumers, dead-letter paths and an outbox. Every primitive works. And six months after the team started "doing events", nobody can answer *"what happens when an order is placed?"* without opening fourteen repositories, a customer has been charged for a parcel that will never ship, and one team's harmless field rename broke five services in production. The broker was never the hard part. This lesson is: which messages are facts and which are instructions, who owns a process that spans six services, and what you type instead of `ROLLBACK` when step three fails.

**Type:** Learn
**Languages:** —
**Prerequisites:** [The Dual-Write Problem: Transactional Outbox & CDC](../10-dual-write-outbox-and-cdc/)
**Time:** ~60 minutes

## The Problem

Ten lessons of machinery are behind you. Messages carry ids and trace context (Lesson 2), work is distributed through queues (Lesson 3) and broadcast through topics (Lesson 4), the log lets consumers replay (Lesson 5), consumers are idempotent (Lesson 6), partition keys hold per-order ordering (Lesson 7), failures land in a dead-letter queue (Lesson 8), lag is charted (Lesson 9), and the outbox has killed the dual-write bug (Lesson 10).

So the team goes event-driven. A year later, this is what they have built.

**Every event is a function call with a stamp on it.** The topic list reads `SendEmailRequested`, `UpdateInventoryCommand`, `ChargeCardV2`. Look at what `orders` publishes and you can name, precisely, which service is meant to handle each one — because the producer decided. The broker gave the team **temporal** and **load** decoupling, which are real and valuable. It gave them nothing at all on **spatial** coupling — the third row of Lesson 1's table — because the producer is still reaching across the boundary and telling a specific service what to do. The transport changed; the dependency graph did not. That system has a name: a **distributed monolith**, and it is strictly worse than the monolith it replaced, because it has all of the coupling plus a network, a serialization format, and eventual consistency.

**Nobody can describe the flow.** A new engineer asks what happens when an order is placed. The honest answer: `orders` publishes something, then between four and nine services react, and some of those reactions publish further things that other services react to. The only complete description of the process is the union of every subscription registration in fourteen repositories. No document, no diagram that has been true for more than a quarter, no single place in the code to point at. The process is an **emergent property** of scattered configuration. It was never designed; it accreted.

**A six-service business transaction has no atomicity, and nobody owns the gap.** `payments` captures $89.98 and commits. `inventory` tries to reserve two units and finds one — the warehouse count was stale. It logs an error, retries three times, and dead-letters the message, which is *correct behaviour* by every rule in Lesson 8. Meanwhile the card is debited, no stock is held, no parcel will ever be packed, and the order sits in a state no service believes it owns. `payments` did its job. `inventory` did its job. The broker did its job. There is money on the wrong side of the ledger and **no component is at fault**, which is exactly why nothing detects it. It surfaces as a support ticket nine days later.

**Events too thin to use, so everyone calls back.** Someone read that events should be small, so `OrderPlaced` carries `{"order_id": 4471}` and nothing else. Now `notifications` calls `orders` for the line items and `customers` for the email address; `shipping` calls `orders` for the address; `analytics` calls `orders` for the total. Five consumers, twelve synchronous callbacks, all aimed at the producer, all fired within milliseconds of the publish. The team has faithfully rebuilt the synchronous fan-in that Lesson 1 removed — with an extra broker hop in front, so the latency is *worse*, and with the producer now a hard runtime dependency of every consumer, so the availability arithmetic is back too. When `orders` has a bad afternoon, every consumer fails, and the postmortem says "but we're event-driven".

**A rename takes down five services.** The `orders` team ships a refactor: `total` becomes `total_cents`, because the units were ambiguous. It passes review, passes their tests, deploys. Forty minutes later five unrelated services are erroring and the `orders` team finds out from a Slack thread they were not in. They did not know who was listening, and **there was no way to find out**, because the whole appeal of pub/sub was that the producer does not have to know — which the team read as permission not to have a contract, rather than a requirement to have a very good one.

Each of these is a design failure, not an infrastructure failure, and not one is fixed by a better broker. This lesson is the set of ideas that prevent them: a rigorous distinction between events, commands and queries; three honest options for what an event carries; the choreography-versus-orchestration fork; and the saga — the only real answer to "how do I make six services agree when I cannot use a transaction".

## The Concept

### Event, command, query: three messages that look identical on the wire

Open a message on the network and you cannot tell these apart. All three are bytes in an envelope, going into a broker, coming out at a consumer. The difference is entirely one of **intent** — and it is the most consequential decision in the architecture, because it sets which direction your dependencies point.

An **event** is a statement of fact about something that already happened. `OrderPlaced`. Past tense, because it is in the past. The producer is not asking for anything, is not waiting for anything, and does not know or care who receives it. An event cannot be rejected: you can decline to *act* on the fact that an order was placed, but you cannot make it un-happen.

A **command** is an instruction to perform an action. `PlaceOrder`, `ChargeCard`, `ReserveStock`. Imperative, because it is an order given. Directed at exactly one recipient chosen by the sender, and it *can* be rejected — the recipient may validate it, refuse it, or fail it.

A **query** is a request for data. `GetOrder`. One known recipient, and the sender is by definition waiting for the answer — which makes it synchronous communication whatever carries it (Lesson 1's costume test).

|  | **Event** | **Command** | **Query** |
|---|---|---|---|
| **Intent** | a fact that happened | an instruction to do something | a request for data |
| **Naming** | past tense — `OrderPlaced` | imperative — `PlaceOrder` | interrogative — `GetOrder` |
| **Recipients** | 0..N, **unknown to the sender** | exactly 1, known | exactly 1, known |
| **Can it be rejected?** | No — it already happened | Yes | n/a |
| **Coupling direction** | consumer → producer's contract | producer → consumer | caller → callee |
| **Sender waits?** | No | Sometimes (reply, or fire-and-forget) | Always |
| **Failure means** | the *consumer* has a problem | the *action* did not happen | the caller is blocked |

The row that matters is **coupling direction**. Everything else is naming convention; this one is architecture.

### The dependency inversion is the entire payoff

When `orders` sends a command, it must know that `payments` exists, know its address, know its request schema, and know what a rejection means. `orders` **depends on** `payments`, and adding a fourth thing that happens on every order means editing `orders`.

When `orders` publishes an event, it declares a fact and stops. It has no consumer list. Each consumer independently decides to depend on the **`OrderPlaced` contract** — not on the service's internals or its API, on the published shape of a fact. The arrow now points *from* each consumer *to* a contract the producer happens to own. That is a dependency inversion in the same sense as the object-oriented one: both sides depend on an abstraction, and the concrete side no longer names the other.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 636" width="100%" style="max-width:840px" role="img" aria-label="The same order flow drawn as commands and as events. With commands the orders service names payments, inventory and notifications, so the dependency arrow points from producer to consumers and adding a side effect requires redeploying orders. With events the orders service publishes an OrderPlaced fact to a topic and names nobody, so the dependency arrow reverses and points from each consumer to the event contract, and a fourth consumer can be added with zero changes to orders.">
  <defs>
    <marker id="l11-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
    <marker id="l11-a1o" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/>
    </marker>
    <marker id="l11-a1g" markerWidth="9" markerHeight="9" refX="5.5" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One flow, two intents — and the dependency arrow reverses</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="280" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="336" width="848" height="282" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
    <rect x="44" y="124" width="130" height="140" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="212" y="134" width="126" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="212" y="180" width="126" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="212" y="226" width="126" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
    <rect x="402" y="128" width="156" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="402" y="174" width="156" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="402" y="220" width="156" height="40" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M174 148 L 206 148" marker-end="url(#l11-a1)"/>
    <path d="M338 148 L 396 148" marker-end="url(#l11-a1)"/>
    <path d="M174 194 L 206 194" marker-end="url(#l11-a1)"/>
    <path d="M338 194 L 396 194" marker-end="url(#l11-a1)"/>
    <path d="M174 240 L 206 240" marker-end="url(#l11-a1)"/>
    <path d="M338 240 L 396 240" marker-end="url(#l11-a1)"/>
  </g>
  <path d="M109 286 L 466 286" fill="none" stroke="#e0930f" stroke-width="3" marker-end="url(#l11-a1o)"/>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="452" width="126" height="64" rx="10" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="206" y="414" width="178" height="140" rx="11" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="452" y="400" width="150" height="36" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="452" y="442" width="150" height="36" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="452" y="484" width="150" height="36" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="452" y="526" width="150" height="36" rx="9" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-dasharray="6 4"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M166 484 L 200 484" marker-end="url(#l11-a1)"/>
    <path d="M384 484 L 446 418" marker-end="url(#l11-a1)"/>
    <path d="M384 484 L 446 460" marker-end="url(#l11-a1)"/>
    <path d="M384 484 L 446 502" marker-end="url(#l11-a1)"/>
    <path d="M384 484 L 446 544" marker-end="url(#l11-a1)"/>
  </g>
  <path d="M527 586 L 300 586" fill="none" stroke="#0fa07f" stroke-width="3" marker-end="url(#l11-a1g)"/>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="12.5" font-weight="700" fill="#e0930f">COMMAND STYLE — the producer names the consumer</text>
    <text x="36" y="88" font-size="9.5" opacity="0.85">imperative verbs · exactly one intended handler each · rejection is possible</text>
    <text x="109" y="182" font-size="11" font-weight="700" text-anchor="middle">orders</text>
    <text x="109" y="202" font-size="8.5" text-anchor="middle" opacity="0.85">holds 3 addresses</text>
    <text x="109" y="218" font-size="8.5" text-anchor="middle" opacity="0.85">imports 3 clients</text>
    <text x="109" y="236" font-size="8.5" text-anchor="middle" opacity="0.85">names 3 services</text>
    <text x="275" y="152" font-size="10" font-weight="700" text-anchor="middle">ChargeCard</text>
    <text x="275" y="198" font-size="10" font-weight="700" text-anchor="middle">ReserveStock</text>
    <text x="275" y="244" font-size="10" font-weight="700" text-anchor="middle">SendEmail</text>
    <text x="480" y="153" font-size="10.5" font-weight="700" text-anchor="middle">payments</text>
    <text x="480" y="199" font-size="10.5" font-weight="700" text-anchor="middle">inventory</text>
    <text x="480" y="245" font-size="10.5" font-weight="700" text-anchor="middle">notifications</text>
    <text x="288" y="306" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">DEPENDENCY: orders → payments, inventory, notifications</text>
    <text x="584" y="142" font-size="9.5" opacity="0.9">orders holds an address for each</text>
    <text x="584" y="160" font-size="9.5" opacity="0.9">consumer, imports their clients,</text>
    <text x="584" y="178" font-size="9.5" opacity="0.9">and lists them by name in code.</text>
    <text x="584" y="204" font-size="10" font-weight="700">Add a 4th side effect:</text>
    <text x="584" y="222" font-size="9.5" opacity="0.9">edit + test + redeploy orders.</text>
    <text x="584" y="252" font-size="9.5" opacity="0.9">Broker gained: temporal + load</text>
    <text x="584" y="270" font-size="9.5" opacity="0.9">decoupling. Spatial: UNCHANGED.</text>

    <text x="36" y="364" font-size="12.5" font-weight="700" fill="#0fa07f">EVENT STYLE — the producer names a fact, and nobody else</text>
    <text x="36" y="382" font-size="9.5" opacity="0.85">past-tense fact · 0..N consumers, unknown to the sender · cannot be rejected</text>
    <text x="103" y="480" font-size="11" font-weight="700" text-anchor="middle">orders</text>
    <text x="103" y="500" font-size="8.5" text-anchor="middle" opacity="0.85">names nobody</text>
    <text x="295" y="440" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">topic: orders.v1</text>
    <text x="295" y="462" font-size="11" font-weight="700" text-anchor="middle">OrderPlaced</text>
    <text x="295" y="484" font-size="8.5" text-anchor="middle" opacity="0.9">{ order_id, customer_id,</text>
    <text x="295" y="500" font-size="8.5" text-anchor="middle" opacity="0.9">  total_cents, currency,</text>
    <text x="295" y="516" font-size="8.5" text-anchor="middle" opacity="0.9">  items[], placed_at }</text>
    <text x="295" y="538" font-size="8.5" text-anchor="middle" opacity="0.75">a versioned CONTRACT</text>
    <text x="527" y="423" font-size="10.5" font-weight="700" text-anchor="middle">payments</text>
    <text x="527" y="465" font-size="10.5" font-weight="700" text-anchor="middle">inventory</text>
    <text x="527" y="507" font-size="10.5" font-weight="700" text-anchor="middle">notifications</text>
    <text x="527" y="545" font-size="10" font-weight="700" text-anchor="middle" fill="#7c5cff">fraud</text>
    <text x="527" y="558" font-size="8" text-anchor="middle" opacity="0.85">subscribed Tuesday</text>
    <text x="413" y="606" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">DEPENDENCY: each consumer → the OrderPlaced contract</text>
    <text x="622" y="424" font-size="9.5" opacity="0.9">orders publishes a fact and</text>
    <text x="622" y="442" font-size="9.5" opacity="0.9">names nobody. Consumers depend</text>
    <text x="622" y="460" font-size="9.5" opacity="0.9">on the CONTRACT, not on the</text>
    <text x="622" y="478" font-size="9.5" opacity="0.9">producer's code or its uptime.</text>
    <text x="622" y="504" font-size="10" font-weight="700">Add a 4th side effect:</text>
    <text x="622" y="522" font-size="9.5" opacity="0.9">one new subscriber.</text>
    <text x="622" y="540" font-size="9.5" opacity="0.9">Zero changes to orders.</text>
    <text x="622" y="566" font-size="9.5" font-weight="700" fill="#0fa07f">Spatial coupling: gone.</text>
  </g>
</svg>
```

**Commands sent over a broker are completely legitimate.** A command in a queue buys durability, buffering (Lesson 9) and free retry-with-backoff (Lesson 8), and many good systems do exactly this. What it does **not** buy you is decoupling:

| Coupling (Lesson 1) | Synchronous call | **Command** over a broker | **Event** on a topic |
|---|---|---|---|
| **Temporal** — both up at once? | coupled | decoupled | decoupled |
| **Load** — rates must match? | coupled | decoupled | decoupled |
| **Spatial** — sender knows receiver? | coupled | **still coupled** | decoupled |

Mislabelling a command as an event is the most common design error in event-driven systems, and it is the mechanism behind the distributed monolith. Someone renames `SendEmail` to `SendEmailRequested`, publishes it to a topic instead of a queue, ticks "event-driven" on the migration doc — and ships the exact dependency graph they started with, plus a broker to operate.

The boundary cases are where the skill lives:

| Message | Presented as | Actually is | Why |
|---|---|---|---|
| `OrderPlaced` | event | **event** | past-tense fact; 0..N consumers; irreversible |
| `SendWelcomeEmail` on a topic | event | **command** | imperative; one intended handler; the producer decided *what should happen*, not *what happened* |
| `OrderCancellationRequested` | command | **event** | it is a fact about what the *customer did*. Whether it is honoured is the consumer's decision |
| `InventoryLevelChanged` | event | a **bad** event | mirrors a database column, not a business fact — Lesson 10's warning, and it forces consumers to reverse-engineer intent |
| `PaymentCaptureRequested` from a saga orchestrator | event | **command** in event clothing | the orchestrator has exactly one payments service in mind and is waiting on the result |
| `GetCustomerAddress` over a queue | "async" | **query** | request-reply in disguise; temporal coupling fully intact (Lesson 1) |

The tell is always the same: **read the name and ask whether the producer could have written it without knowing the consumer exists.** If not, it is a command.

### The three event styles: what does the event carry?

You have decided a message is an event. The next decision is what goes inside it, and there are three coherent answers — a widely used taxonomy of event styles, each right somewhere.

**1. Event notification.** The event carries an identifier and essentially nothing else.

```json
{ "type": "OrderPlaced", "order_id": 4471, "occurred_at": "2026-07-18T09:14:02Z" }
```

Tiny, cheap, and almost impossible to break: one field means nearly no schema to evolve, and the producer stays free to reshape its internals.

The cost is the fourth symptom from The Problem. A consumer that needs the line items, the email address or the total must **call back**, reintroducing synchronous, spatial and temporal coupling pointed the wrong way — from every consumer at the producer, all firing at once. Availability multiplies again, and the producer must be sized for its own traffic *plus* a callback per subscriber per event. Use notification when consumers need only the identity ("something changed, go look"), when the payload is too large or too sensitive to broadcast, or when there are one or two consumers and the callback is cheap.

**2. Event-carried state transfer.** The event carries everything a reasonable consumer needs.

```json
{
  "type": "OrderPlaced", "version": 3, "order_id": 4471,
  "customer": { "id": 881, "email": "r@example.com", "tier": "gold" },
  "items": [ { "sku": "KB-01", "qty": 2, "unit_cents": 4499 } ],
  "total_cents": 8998, "currency": "USD",
  "ship_to": { "line1": "...", "postcode": "..." },
  "occurred_at": "2026-07-18T09:14:02Z"
}
```

Now `notifications` can send the email, and `shipping` can dispatch, with the producer switched off. **This is the property you actually wanted when you said "decoupled":** consumer autonomy, not merely a broker in the middle. It is also what makes the availability arithmetic hold, because the consumer no longer depends on the producer being up at consumption time.

Say the costs out loud. Events get bigger, costing broker throughput and storage. Data is duplicated — the customer's email now lives in five services' local stores, a deliberate denormalization. Copies go **stale**: the consumer holds the address *as it was when the order was placed*, which for shipping is arguably more correct than the current value and for a marketing preference is arguably wrong. And the payload is now a **contract** — every field you include is a field somebody depends on. That is Lesson 12, and it is the price of this style.

**3. Event sourcing.** The event log *is* the system of record. There is no `orders` table that holds the truth and emits events on the side; the sequence of events **is** the truth, and current state is a **fold** (a left reduction) over the events for one aggregate.

```text
OrderPlaced      { order_id: 4471, items: [KB-01 x2], total_cents: 8998 }
PaymentCaptured  { order_id: 4471, amount_cents: 8998, psp_ref: "ch_9f2" }
ItemRemoved      { order_id: 4471, sku: "KB-01", qty: 1 }
OrderRepriced    { order_id: 4471, total_cents: 4499 }
RefundIssued     { order_id: 4471, amount_cents: 4499 }

state = reduce(apply, events_for(4471), Order.empty())
```

The benefits are not marketing. A **perfect audit trail** by construction — not a log *about* the changes, the changes themselves — which is why the pattern is common in finance. **Temporal queries**: what did this order look like at 14:02 on Tuesday? Replay to that offset. **Rebuild any projection** — read model, search index, report — by folding the log with different code, so a bug in a read model is fixed by deploying and re-folding rather than by writing a migration. And **Lesson 10's dual-write problem dissolves entirely**, because there is only ever one write: appending the event. There is no state to keep in sync with the log, because the log *is* the state. (Phase 3's write-ahead log, promoted from an implementation detail to the public model of the system.)

The costs, stated honestly, because this is the pattern most often adopted for the wrong reasons:

- **Schema evolution is forever.** A conventional service migrates its table and moves on. An event-sourced service must fold events written three years ago, in the shape they had three years ago, for as long as it retains them — so every reader carries upcasting logic for every historical version. Lesson 12 is not optional here; it is load-bearing.
- **Deletion is genuinely hard.** GDPR (General Data Protection Regulation) Article 17 gives a data subject the right to erasure, and your log is append-only and immutable by design — the two properties you bought it for. The standard mitigation is **crypto-shredding**: encrypt personal fields with a per-subject key and destroy the key. It works, and it is a constraint you must accept on day one rather than discover on day 900.
- **Projections must be built, monitored and rebuilt.** Every query the product needs is a separate materialized read model with its own lag, bugs and rebuild time. This is where **CQRS** (Command Query Responsibility Segregation — separating the write model from one or more read models) shows up, because event sourcing all but forces it.
- **Snapshots are mandatory at scale.** Folding 400,000 events to answer one lookup is not viable, so you persist the folded state at offset *N* and replay from there — more machinery, more invalidation logic, another thing to get wrong.
- **The learning curve is steep**, and it is a one-way door: un-event-sourcing a system is a rewrite.

Use event sourcing when the **history is the product** — ledgers, trading, audit-critical workflows, anything where "how did we get here" is a routine business question. Do not use it because you want decoupling; styles 1 and 2 give you that for a fraction of the cost. **You do not need event sourcing to do event-driven architecture**, and treating the two as synonyms is a common and expensive mistake.

| Style | Event size | Consumer autonomy | Coupling to payload | Best when |
|---|---|---|---|---|
| **Notification** | tiny | low — must call back | minimal | 1–2 consumers; large or sensitive payloads; "go look" semantics |
| **State transfer** | medium–large | **high** — works with the producer down | **high** — the payload is a contract | the default for cross-service integration |
| **Event sourcing** | n/a (the log is the state) | high | very high, and permanent | history *is* the product: ledgers, audit, temporal queries |

Most healthy systems use style 2 for integration, style 1 for a few high-volume or privacy-sensitive streams, and style 3 only in the one or two bounded contexts that genuinely need it.

### Choreography vs orchestration: who holds the map?

Five things must happen when an order is placed. There are exactly two ways to arrange them, and this is the central architectural fork of the lesson.

**Choreography.** Each service subscribes to the events it cares about and reacts. `payments` hears `OrderPlaced` and captures. `inventory` hears `PaymentCaptured` and reserves. `shipping` hears `StockReserved` and dispatches. Nobody is in charge; the process is the emergent sum of the reactions, like dancers who each know only their own cue.

**Orchestration.** A coordinator — a workflow service, a saga orchestrator, a state machine — owns the process. It sends `CapturePayment`, waits for the reply, sends `ReserveStock`, waits, and so on, recording where it has got to. The process exists as an artifact you can read, test and query.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 596" width="100%" style="max-width:840px" role="img" aria-label="Choreography and orchestration compared for the same five-step order process. Under choreography five services chain reactions through events, the flow knowledge lives nowhere and debugging starts with a distributed trace. Under orchestration a saga coordinator issues commands and receives replies, the flow lives in one state machine with one row per order, and debugging starts with a database query, at the cost of a component that knows every participant.">
  <defs>
    <marker id="l11-a2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
    <marker id="l11-a2d" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same five steps, same broker — the difference is who holds the map</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="418" height="512" rx="13" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    <rect x="446" y="42" width="418" height="512" rx="13" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
    <rect x="44" y="92" width="170" height="34" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="44" y="152" width="170" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="44" y="212" width="170" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="44" y="272" width="170" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="44" y="332" width="170" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="466" y="110" width="130" height="240" rx="11" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="680" y="104" width="164" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="680" y="156" width="164" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="680" y="208" width="164" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="680" y="260" width="164" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="680" y="312" width="164" height="34" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M129 126 L 129 148" marker-end="url(#l11-a2)"/>
    <path d="M129 186 L 129 208" marker-end="url(#l11-a2)"/>
    <path d="M129 246 L 129 268" marker-end="url(#l11-a2)"/>
    <path d="M129 306 L 129 328" marker-end="url(#l11-a2)"/>
    <path d="M596 115 L 674 115" marker-end="url(#l11-a2)"/>
    <path d="M596 167 L 674 167" marker-end="url(#l11-a2)"/>
    <path d="M596 219 L 674 219" marker-end="url(#l11-a2)"/>
    <path d="M596 271 L 674 271" marker-end="url(#l11-a2)"/>
    <path d="M596 323 L 674 323" marker-end="url(#l11-a2)"/>
  </g>
  <g fill="none" stroke="#7c5cff" stroke-width="1.4" stroke-dasharray="5 4">
    <path d="M674 129 L 600 129" marker-end="url(#l11-a2d)"/>
    <path d="M674 181 L 600 181" marker-end="url(#l11-a2d)"/>
    <path d="M674 233 L 600 233" marker-end="url(#l11-a2d)"/>
    <path d="M674 285 L 600 285" marker-end="url(#l11-a2d)"/>
    <path d="M674 337 L 600 337" marker-end="url(#l11-a2d)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="12.5" font-weight="700" fill="#3553ff">CHOREOGRAPHY — five subscriptions, no map</text>
    <text x="129" y="114" font-size="10.5" font-weight="700" text-anchor="middle">orders</text>
    <text x="129" y="174" font-size="10.5" font-weight="700" text-anchor="middle">payments</text>
    <text x="129" y="234" font-size="10.5" font-weight="700" text-anchor="middle">inventory</text>
    <text x="129" y="294" font-size="10.5" font-weight="700" text-anchor="middle">shipping</text>
    <text x="129" y="354" font-size="10.5" font-weight="700" text-anchor="middle">notifications</text>
    <text x="226" y="142" font-size="9.5" opacity="0.9">OrderPlaced</text>
    <text x="226" y="202" font-size="9.5" opacity="0.9">PaymentCaptured</text>
    <text x="226" y="262" font-size="9.5" opacity="0.9">StockReserved</text>
    <text x="226" y="322" font-size="9.5" opacity="0.9">ShipmentDispatched</text>
    <text x="36" y="396" font-size="10.5" font-weight="700">FLOW KNOWLEDGE LIVES:</text>
    <text x="36" y="414" font-size="9.5" opacity="0.9">nowhere. It is the union of five</text>
    <text x="36" y="430" font-size="9.5" opacity="0.9">subscription lists in five repos.</text>
    <text x="36" y="456" font-size="10.5" font-weight="700">DEBUGGING STARTS:</text>
    <text x="36" y="474" font-size="9.5" opacity="0.9">a trace_id in a tracing tool —</text>
    <text x="36" y="490" font-size="9.5" opacity="0.9">if every hop propagated it.</text>
    <text x="36" y="516" font-size="10.5" font-weight="700" fill="#e0930f">THE COST:</text>
    <text x="36" y="534" font-size="9.5" opacity="0.9">no artifact describes the process,</text>
    <text x="36" y="548" font-size="9.5" opacity="0.9">and reaction cycles are easy to add.</text>

    <text x="466" y="70" font-size="12.5" font-weight="700" fill="#7c5cff">ORCHESTRATION — one map, one owner</text>
    <text x="531" y="140" font-size="11" font-weight="700" text-anchor="middle">OrderSaga</text>
    <text x="531" y="158" font-size="8.5" text-anchor="middle" opacity="0.85">a state machine</text>
    <text x="531" y="198" font-size="9.5" text-anchor="middle" font-weight="700">order 4471</text>
    <text x="531" y="218" font-size="9" text-anchor="middle" opacity="0.9">step 3 of 5</text>
    <text x="531" y="236" font-size="9" text-anchor="middle" opacity="0.9">RESERVING_STOCK</text>
    <text x="531" y="256" font-size="8.5" text-anchor="middle" opacity="0.85">started 1.2 s ago</text>
    <text x="531" y="276" font-size="8.5" text-anchor="middle" opacity="0.85">timeout at 30 s</text>
    <text x="531" y="300" font-size="8.5" text-anchor="middle" opacity="0.85">compensations:</text>
    <text x="531" y="316" font-size="8.5" text-anchor="middle" opacity="0.85">C2, C1 registered</text>
    <text x="762" y="126" font-size="10" font-weight="700" text-anchor="middle">1 · orders</text>
    <text x="762" y="178" font-size="10" font-weight="700" text-anchor="middle">2 · payments</text>
    <text x="762" y="230" font-size="10" font-weight="700" text-anchor="middle">3 · inventory</text>
    <text x="762" y="282" font-size="10" font-weight="700" text-anchor="middle">4 · shipping</text>
    <text x="762" y="334" font-size="10" font-weight="700" text-anchor="middle">5 · notifications</text>
    <text x="466" y="372" font-size="9" opacity="0.85">solid → command  ·  dashed ⇠ reply / event</text>
    <text x="466" y="396" font-size="10.5" font-weight="700">FLOW KNOWLEDGE LIVES:</text>
    <text x="466" y="414" font-size="9.5" opacity="0.9">one state machine, one repo,</text>
    <text x="466" y="430" font-size="9.5" opacity="0.9">one row per order.</text>
    <text x="466" y="456" font-size="10.5" font-weight="700">DEBUGGING STARTS:</text>
    <text x="466" y="474" font-size="9.5" opacity="0.9">SELECT * FROM saga_instance</text>
    <text x="466" y="490" font-size="9.5" opacity="0.9">WHERE order_id = 4471;</text>
    <text x="466" y="516" font-size="10.5" font-weight="700" fill="#e0930f">THE COST:</text>
    <text x="466" y="534" font-size="9.5" opacity="0.9">a component that knows everyone —</text>
    <text x="466" y="548" font-size="9.5" opacity="0.9">a coupling hotspot and a bottleneck.</text>

    <text x="440" y="580" font-size="10" text-anchor="middle" opacity="0.95">Neither is "correct". Choreography optimises for autonomy; orchestration optimises for legibility.</text>
  </g>
</svg>
```

The debate is unusually tribal, which signals that both sides are describing real experience. Resist it and use the properties of the process in front of you:

| Signal | Favours **choreography** | Favours **orchestration** |
|---|---|---|
| **Number of participants** | 2–3 | 4 or more |
| **Process complexity** | linear, no branches | branches, parallel steps, timeouts, conditional retries |
| **Compensation required?** | no — steps are independent | **yes** — a failure must unwind earlier work |
| **"Where is order 4471?"** | rarely asked | asked daily, by support and by the business |
| **Auditability / regulatory** | not required | required |
| **Rate of change** | the process rarely changes | a step is added or reordered every few months |
| **Team boundaries** | spans several teams / bounded contexts | lives inside one team's domain |
| **Failure mode you fear** | one consumer being down | the process silently stalling half-done |

Two failure modes deserve names. Under choreography it is the **accidental cycle**: `inventory` publishes `StockAdjusted`, `pricing` reacts with `PriceChanged`, `catalog` reacts with `ProductUpdated`, and something in `inventory` reacts to *that*. Each subscription was reasonable in isolation and nobody could see the loop, because no artifact shows the graph. It surfaces as a slow-motion message storm at 3 a.m. Reasoning about it needs the causal-ordering framework from Lamport's *Time, Clocks, and the Ordering of Events in a Distributed System* (CACM 21(7), 1978) — the happened-before relation is what a distributed trace approximates when it draws you the chain.

Under orchestration it is the **god orchestrator**: the coordinator accretes business logic that belongs in the participants, ends up knowing every service's schema, and becomes the thing every team must change to ship anything. That is a distributed monolith with a different topology.

The pragmatic answer, and the one for your design doc: **choreography between bounded contexts, orchestration within a business transaction that needs atomicity.** Ordering, payment and fulfilment form one transaction that must unwind as a unit — orchestrate it. Analytics, recommendations, marketing and the data warehouse just want to know an order happened — let them choreograph off `OrderPlaced` and never tell the orchestrator they exist. Real systems are hybrids.

### Sagas: what you type instead of ROLLBACK

Lesson 10 closed the door on distributed transactions. **2PC** (two-phase commit) makes every participant hold locks while waiting for a coordinator that may crash; it does not survive partitions, it does not work across services you do not own, and it converts independent failures into correlated ones. So: five services, one business transaction, and no `BEGIN`.

The answer is the **saga**, introduced by Hector Garcia-Molina and Kenneth Salem in *Sagas* (Proceedings of the 1987 ACM SIGMOD International Conference on Management of Data). Their original problem was not microservices but **long-lived transactions** inside one database, which hold locks so long they destroy concurrency. The proposal generalises perfectly:

> A saga is a sequence of transactions `T1, T2, ... Tn` that can be interleaved with other transactions. Each `Ti` has a **compensating transaction** `Ci` that semantically undoes it. The system guarantees that either all of `T1 ... Tn` complete, **or** the sequence `T1 ... Tj, Cj ... C1` executes — the work is done, or it is semantically undone.

Note what was traded away in 1987 and is still traded away today: **isolation**. A saga commits each step locally and immediately, releasing its locks, so other transactions *can and will observe the intermediate states*. That was the point — concurrency in exchange for isolation — and it is exactly the trade you make when you split a business transaction across services.

### Compensation is not rollback

This is the point engineers most often miss, and it is worth stating bluntly.

A database rollback is a **physical** operation. The write-ahead log holds the before-image (Phase 3), nothing outside the transaction ever saw the change, and undoing it restores a state indistinguishable from the change never having happened.

A compensation is a **semantic, forward-moving business action**. The original step already committed and the world already saw it. You cannot un-send an email, un-ship a package, un-charge a card, or un-tell a warehouse worker to pick an item. What you can do:

| Step `Ti` | Compensation `Ci` — what actually happens |
|---|---|
| capture $89.98 | **issue a refund**: a new ledger entry, settling in 3–5 days, possibly minus a non-refundable processor fee |
| reserve 2 units | **release the reservation** — and someone else may take them before you finish |
| book a courier slot | **cancel the booking**, if it is before the cut-off; after cut-off, accept the fee |
| dispatch a parcel | **there is no compensation.** Issue a return label and hope |
| send a confirmation email | **send a second email** apologising. The first one is in their inbox forever |
| award 500 loyalty points | **deduct 500 points** — unless they were already spent, in which case, a business decision |

Every right-hand cell is a **business decision encoded in code**, not a technical undo. Who eats the processor fee? Do we offer a backorder instead of a refund? Do we let the balance go negative when points were already spent? None of those has an engineering answer, and if an engineer picks one silently, the business discovers the choice via a customer complaint. **Design compensations with the people who own the money.** That one practice separates a saga that works from one that generates support tickets.

Two structural consequences follow:

- **Compensations must be idempotent and retryable**, exactly like forward steps (Lessons 6 and 8). "Refund order 4471" must be safe to execute five times, because at-least-once delivery means it will be. Key the refund on the saga instance and step, not on a fresh identifier.
- **Compensations run in reverse order.** `Cj, Cj-1, ... C1`. Releasing stock before refunding the payment is usually fine; cancelling the order record before either is not, because you have destroyed the context the compensations needed.

### The order saga, step by step

The running example as a real saga: five local transactions, three compensations, one pivot.

```text
T1  orders        create order, status = PLACED       C1  cancel order + notify the customer
T2  payments      capture 8998 cents                  C2  issue a refund of 8998 cents
T3  inventory     reserve 2 x KB-01                   C3  release the reservation
=========== compensatable above · PIVOT · retriable below ===========================
T4  shipping      hand the parcel to the courier      --  nothing undoes this
T5  notifications send the confirmation email         --  retry until it sends
```

The **pivot step** is the boundary between two different worlds. Steps before it are **compensatable**: they can be semantically undone, so a failure means unwind. Steps at or after it are **retriable**: they cannot be undone, so a failure means *keep trying until it succeeds*, escalating to a human if it never does. The pivot is the last point at which abandoning the saga is still an option.

That produces the most useful design rule in the pattern: **order your steps so that everything irreversible happens as late as possible.** Charge the card before dispatching the parcel, because a refund is easy and a recall is not. Reserve stock before you dispatch. Send the email last, because it is a permanent record in someone else's inbox and you get one shot at it. When you sketch a saga, mark the pivot first; the ordering of everything else falls out of it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 660" width="100%" style="max-width:840px" role="img" aria-label="A five-step order saga. On the happy path five local transactions commit in sequence and the order becomes placed, paid, reserved, shipped and confirmed, with shipping marked as the pivot beyond which the saga can only move forward. When step three fails because stock is unavailable, the saga aborts and runs compensations in reverse: a refund is issued and the order is cancelled. A timeline shows the customer's card debited for the whole window, demonstrating that a saga has no isolation.">
  <defs>
    <marker id="l11-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
    <marker id="l11-a3p" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The saga — five commits forward, and the cascade that unwinds them</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="186" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
    <rect x="16" y="242" width="848" height="376" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="24" y="92" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="194" y="92" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="364" y="92" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="534" y="92" width="146" height="52" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="704" y="92" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M170 118 L 190 118" marker-end="url(#l11-a3)"/>
    <path d="M340 118 L 360 118" marker-end="url(#l11-a3)"/>
    <path d="M510 118 L 530 118" marker-end="url(#l11-a3)"/>
    <path d="M680 118 L 700 118" marker-end="url(#l11-a3)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="296" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="194" y="296" width="146" height="52" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="364" y="296" width="146" height="52" rx="9" fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-width="2.6"/>
    <rect x="24" y="410" width="146" height="52" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
    <rect x="194" y="410" width="146" height="52" rx="9" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M170 322 L 190 322" marker-end="url(#l11-a3)"/>
    <path d="M340 322 L 360 322" marker-end="url(#l11-a3)"/>
  </g>
  <g fill="none" stroke="#7c5cff" stroke-width="2.2">
    <path d="M437 348 L 437 388 L 267 388 L 267 404" marker-end="url(#l11-a3p)"/>
    <path d="M194 436 L 176 436" marker-end="url(#l11-a3p)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="12.5" font-weight="700" fill="#0fa07f">HAPPY PATH — five local transactions, five commits, zero global locks</text>
    <text x="97" y="114" font-size="10.5" font-weight="700" text-anchor="middle">T1 · orders</text>
    <text x="97" y="132" font-size="9" text-anchor="middle" opacity="0.9">create order</text>
    <text x="267" y="114" font-size="10.5" font-weight="700" text-anchor="middle">T2 · payments</text>
    <text x="267" y="132" font-size="9" text-anchor="middle" opacity="0.9">capture 8998</text>
    <text x="437" y="114" font-size="10.5" font-weight="700" text-anchor="middle">T3 · inventory</text>
    <text x="437" y="132" font-size="9" text-anchor="middle" opacity="0.9">reserve 2 x KB-01</text>
    <text x="607" y="114" font-size="10.5" font-weight="700" text-anchor="middle">T4 · shipping</text>
    <text x="607" y="132" font-size="9" text-anchor="middle" opacity="0.9">hand to courier</text>
    <text x="777" y="114" font-size="10.5" font-weight="700" text-anchor="middle">T5 · notify</text>
    <text x="777" y="132" font-size="9" text-anchor="middle" opacity="0.9">confirmation email</text>
    <text x="97" y="166" font-size="9" text-anchor="middle" opacity="0.85">PLACED</text>
    <text x="267" y="166" font-size="9" text-anchor="middle" opacity="0.85">PAID</text>
    <text x="437" y="166" font-size="9" text-anchor="middle" opacity="0.85">RESERVED</text>
    <text x="607" y="166" font-size="9" text-anchor="middle" opacity="0.85">SHIPPED</text>
    <text x="777" y="166" font-size="9" text-anchor="middle" opacity="0.85">CONFIRMED</text>
    <text x="607" y="184" font-size="9" text-anchor="middle" font-weight="700" fill="#7c5cff">PIVOT — forward only past here</text>
    <text x="440" y="212" font-size="10" text-anchor="middle" opacity="0.95">Each box commits locally and releases its locks. Between any two boxes the system is legally, observably half-done.</text>

    <text x="36" y="270" font-size="12.5" font-weight="700" fill="#e0930f">FAILURE AT T3 — the compensating cascade, and what the customer sees</text>
    <text x="97" y="318" font-size="10.5" font-weight="700" text-anchor="middle">T1 · orders</text>
    <text x="97" y="336" font-size="9" text-anchor="middle" opacity="0.9">committed</text>
    <text x="267" y="318" font-size="10.5" font-weight="700" text-anchor="middle">T2 · payments</text>
    <text x="267" y="336" font-size="9" text-anchor="middle" opacity="0.9">committed · card debited</text>
    <text x="437" y="316" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">T3 · inventory</text>
    <text x="437" y="333" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">OUT OF STOCK</text>
    <text x="437" y="346" font-size="8" text-anchor="middle" opacity="0.85">not a bug — a valid outcome</text>
    <text x="437" y="378" font-size="9" text-anchor="middle" font-weight="700" fill="#7c5cff">SAGA ABORTS → compensate in reverse</text>
    <text x="267" y="432" font-size="10.5" font-weight="700" text-anchor="middle">C2 · payments</text>
    <text x="267" y="450" font-size="9" text-anchor="middle" opacity="0.9">issue refund 8998</text>
    <text x="97" y="432" font-size="10.5" font-weight="700" text-anchor="middle">C1 · orders</text>
    <text x="97" y="450" font-size="9" text-anchor="middle" opacity="0.9">cancel + notify</text>
    <text x="36" y="486" font-size="9.5" opacity="0.95">C2 does not delete the charge. It writes a NEW refund record; the ledger keeps both, forever.</text>

    <text x="540" y="300" font-size="10.5" font-weight="700">WHAT THE OUTSIDE WORLD SEES (illustrative)</text>
    <text x="540" y="324" font-size="9.5" opacity="0.9">t+0      order PLACED</text>
    <text x="540" y="342" font-size="9.5" opacity="0.9">t+180ms  order PAID          ← card debited</text>
    <text x="540" y="360" font-size="9.5" opacity="0.9">t+240ms  reservation FAILED</text>
    <text x="540" y="378" font-size="9.5" opacity="0.9">t+250ms  order REFUNDING     ← still debited</text>
    <text x="540" y="396" font-size="9.5" opacity="0.9">t+400ms  order CANCELLED</text>
    <text x="540" y="414" font-size="9.5" opacity="0.9">t+3-5d   funds back on the card</text>
    <text x="540" y="442" font-size="9.5" opacity="0.95">Every one of those states is queryable by</text>
    <text x="540" y="458" font-size="9.5" opacity="0.95">support, by a report, and by another saga.</text>
    <text x="540" y="482" font-size="10" font-weight="700" fill="#e0930f">A saga is ACD, not ACID.</text>
    <text x="540" y="500" font-size="9.5" opacity="0.95">Atomic, Consistent, Durable — with NO</text>
    <text x="540" y="516" font-size="9.5" opacity="0.95">Isolation. Another transaction will read a</text>
    <text x="540" y="532" font-size="9.5" opacity="0.95">half-completed saga. Plan for it.</text>

    <text x="36" y="524" font-size="10.5" font-weight="700">COMPENSATION ≠ ROLLBACK</text>
    <text x="36" y="546" font-size="9.5" opacity="0.9">capture → refund (new record, 3-5 days, fee kept)</text>
    <text x="36" y="564" font-size="9.5" opacity="0.9">reserve → release (someone else may take it)</text>
    <text x="36" y="582" font-size="9.5" opacity="0.9">dispatch → nothing. Return label and an apology.</text>
    <text x="36" y="600" font-size="9.5" opacity="0.9">email → a second email. There is no unsend.</text>

    <text x="440" y="642" font-size="10" text-anchor="middle" opacity="0.95">Every arrow in the lower half is code you must write, test and page someone about. Most teams ship the upper half only.</text>
  </g>
</svg>
```

**The happy path** is five local commits across five services, published through the outbox of Lesson 10, with no global lock held at any moment and every step safe to retry because Lesson 6's idempotency keys are on every message.

**Now walk the failure.** T1 and T2 commit; the card is genuinely debited. T3 finds one unit where it expected two. This is **not an exception** — it is a legitimate business outcome, and modelling it as an error is how teams end up dead-lettering it instead of handling it. `inventory` publishes `StockReservationFailed` (a fact) and the saga aborts. The cascade runs `C2` — `payments` issues a refund, a *new* transaction creating a *new* ledger record, not a deletion of the capture — then `C1`, which sets the order to `CANCELLED` and notifies the customer that the money is on its way back, possibly with a backorder offer, because that is what the business decided this compensation means.

Compare that to The Problem's third symptom: the identical scenario with no saga, discovered nine days later by a human. The saga did not prevent the failure. **It made the failure somebody's job.**

### The two shapes a saga comes in

A saga is a pattern, not a topology, so it can be built either way.

In a **choreographed saga** each participant subscribes to the previous step's event and knows which compensation to run when it sees a failure event: `payments` subscribes to `OrderPlaced` and to `StockReservationFailed`, the first triggering T2 and the second C2. No coordinator exists. That is simple for three participants; by six, working out which compensations fire in which order means reading six repositories, and inserting a step means changing at least two.

In an **orchestrated saga** a coordinator holds a state machine with a persisted instance per order, sends commands, receives replies, and on failure runs the registered compensations in reverse. The saga state row *is* the answer to "where is order 4471" — which is what workflow engines exist to give you. Its own durability matters enormously: if it crashes between "sent `ReserveStock`" and "recorded that I sent it", it must still recover correctly, so it writes intent before acting — Phase 3's write-ahead log again, usually with its own outbox (Lesson 10).

Choose by the same table as above, with one thumb on the scale: **once compensation is in the picture, orchestration gets much more attractive**, because compensation is precisely the logic that needs a global view of what has already happened.

### Semantic locks, and the missing I

A saga gives you Atomicity (eventually — all steps or all compensations), Consistency and Durability, but not **Isolation** — the I of ACID, the four properties named by Härder and Reuter in *Principles of Transaction-Oriented Database Recovery* (ACM Computing Surveys 15(4), 1983). Concurrent readers and other sagas *will* observe half-finished states, as the diagram's timeline shows.

The main countermeasure is a **semantic lock**: an explicit, application-level marker announcing that a record is mid-saga, so other actors can decide what to do about it.

```text
order.status  = PAYMENT_PENDING   -- not a real state of the business, a saga state
stock.status  = RESERVED          -- distinct from SOLD; reservations expire
account.hold  = 8998              -- an authorisation hold, not a capture
```

The value is that the intermediate state becomes **first-class and legible** rather than a lie. A second saga touching the same order sees `PAYMENT_PENDING` and can choose to refuse, queue behind it, or proceed anyway. A report can exclude it. Support can explain it. The alternative — an order silently between states while the row still reads `PLACED` — is where the nasty bugs live.

Three cheaper countermeasures are worth knowing by name. **Commutative updates**: `balance += 50` and `balance -= 50` commute, `balance = 950` does not, and commutative steps compensate trivially. **Version checks**: before compensating, verify the state still looks like what you committed — if someone else changed it, that is an escalation, not an overwrite. **Pessimistic ordering**: reorder so the dangerous intermediate state is short-lived and harmless, which is exactly what an authorisation hold before a capture buys you.

And **semantic locks must expire.** A `RESERVED` row with no time-to-live is a stock leak, because some saga will die between T3 and its compensation and nobody will ever release those units. Every lock needs a timeout and a sweeper — the same reasoning as Lesson 3's visibility timeout and Lesson 8's retry budget, applied to business state.

### When the compensation itself fails

The question that separates people who have read about sagas from people who have run one.

`C2` — issue the refund — fails. The payment processor is down. Now what?

**A compensation must not be allowed to fail permanently.** The forward path has an easy out: if T3 fails, abort and unwind. The compensation path has nothing behind it. So:

1. **Retry aggressively and for a long time**, with exponential backoff and jitter (Lesson 8). Compensation retry budgets are measured in hours or days, not the seconds you allow a forward step. The failure is almost always transient.
2. **Never dead-letter a compensation into the same DLQ as normal traffic.** A dead-lettered forward message is an inconvenience; a dead-lettered compensation is money in the wrong place. It needs its own queue, its own alert and an owner.
3. **After the retry budget, page a human.** Genuinely — this is one of the few places where "escalate to a person" is correct design rather than a failure of imagination, because the residual cases are closed cards, frozen accounts and processors requiring a manual reversal, none of which code can resolve.
4. **Design compensations so their worst case is a ticket, not corruption.** If `C2` never succeeds, the end state should be "a customer is owed $89.98, there is a record saying so, and it is assigned to someone". That is recoverable. "The order says `CANCELLED` and the payment record was deleted" is not.

The uncomfortable corollary, worth accepting early: **a compensation that can fail permanently means your saga can end inconsistent, and no amount of retrying changes that.** The goal is not to eliminate the possibility but to make it rare, detectable and assigned.

### Designing events that age well

Events outlive the code that produced them, the team that designed them, and often the service itself. Design accordingly.

**Name them as business facts, past tense, in the domain's language.** `OrderPlaced`, `PaymentCaptured`, `ShipmentDispatched`, `SubscriptionCancelled` — not `OrderTableRowInserted`, not `ProcessOrderStep2Complete`. If a domain expert would not recognise the name, it is the wrong name. That is not aesthetics: it is the difference between an event that survives a refactor and a leaked implementation detail with a timestamp.

**Make them meaningful to the business, not a mirror of a database row.** Lesson 10's warning, restated where it matters most. CDC (Change Data Capture) gives you `orders_row_updated {status: "SHIPPED"}` for free, and it is nearly useless as an integration event: it publishes your schema as an API, forces every consumer to reverse-engineer intent from a diff, and makes any table refactor a breaking change for services you have never heard of. A `PriceChanged` event carries *why* — a promotion, a cost change, a manual override. A row diff never can.

**Own them.** Every event belongs to exactly one bounded context: the one where the fact becomes true. `PaymentCaptured` is owned by `payments`, full stop. A shared events library that five teams commit to with no owner is the *shared mutable schema* anti-pattern, and it produces the fifth symptom from The Problem.

**Version them, and treat compatibility as a contract.** The schema is a public API with an unknown number of consumers — Lesson 12 in its entirety, and the reason it follows this lesson.

**Keep them immutable.** You never edit an event. If the fact was wrong, publish a correcting event — `OrderRepriced`, `ChargeReversed` — which is how double-entry bookkeeping has handled this for five hundred years.

**Include the aggregate id, and use it as the partition key.** The `order_id` in the envelope becomes Lesson 7's partition key, which is what gives per-order ordering while different orders process in parallel. Get it wrong and `OrderCancelled` overtakes `OrderPlaced`.

**Include trace context.** In a choreographed system the `traceparent` in the envelope (Lesson 2, Phase 9) is not observability polish — it is the *only* artifact that describes the process end to end.

**Prefer coarse business events over chatty field-level ones.** One `OrderPlaced` beats `OrderCreated` + `OrderItemAdded` × 3 + `OrderTotalCalculated`. Fine-grained change events force every consumer to reassemble a business fact from fragments, in order, with no guarantee they agree on the result.

**But avoid the god event** — one `OrderUpdated` carrying every field anyone ever needed, with a `change_type` discriminator and forty optional fields. Nobody can evolve it, everybody parses it defensively, and its schema is the union of every consumer's requirements: the shared mutable schema again, wearing a payload.

### Anti-patterns, named so you can spot them in review

- **The distributed monolith** — services split across a network but still deployed in lockstep. *Tell:* releasing A requires releasing B and C the same day.
- **Events as RPC** (Remote Procedure Call) — imperative names, one intended consumer, sometimes a reply queue. *Tell:* the name contains an imperative verb, or you can name the one service that must handle it.
- **The chatty event storm** — an event per field change instead of per business fact. *Tell:* consumers buffer and correlate several events before they can act.
- **The god event** — one event carrying everything for everyone. *Tell:* a `change_type` discriminator and mostly optional fields.
- **The shared mutable event schema with no owner** — a central `events` package every team edits. *Tell:* nobody can answer "who approves a change to `OrderPlaced`?"
- **Events used for queries** — publishing a request and consuming a correlated reply because "we're event-driven now". *Tell:* the producer blocks; Lesson 1's costume test fails.
- **Eventual consistency leaking into a UI that promised immediacy** — the user clicks *Place Order*, the page says "Order confirmed", the read model has not caught up, and their order history is empty. *Tell:* a bug report saying "it worked but the page was blank" that nobody can reproduce. The fix is product work as much as engineering: say "processing", render optimistic state from the command you just sent, or read-your-own-writes from the write model for that one user.

### When NOT to use event-driven architecture

Symmetry, because the failure mode of this lesson is applying it everywhere.

- **Strong, immediate consistency requirements.** "Two people must not book seat 14C" is an invariant enforced at a single point inside one transaction. A saga's *lack of isolation* means someone will observe the half-state — which for a seat booking is a double-sold seat. For invariants that are not negotiable, keep the data in one place and use a real transaction.
- **Simple CRUD with no interested third parties.** (CRUD = Create, Read, Update, Delete.) If nothing reacts to a change, there is no fan-out to gain, and an event with zero subscribers is pure cost.
- **Small teams.** The overhead is real and roughly fixed: a broker to run, schemas to govern, idempotency everywhere, distributed tracing, saga state to inspect, and a mental model every new hire must acquire. Below a certain size that exceeds the coupling it removes. A modular monolith with in-process events and one database is an excellent architecture, and it splits later along seams you have already drawn.
- **When you cannot yet make consumers idempotent.** Lesson 6's entry fee. At-least-once delivery means duplicates; if processing a message twice charges a card twice, events will damage your data faster than synchronous calls ever failed you.
- **When you cannot yet trace a request across services.** In a choreographed system with no propagated trace context, the first production incident is unresolvable. Build that first (Phase 9).

### Bounded contexts, Conway's Law, and finding the events

One last frame, because it explains why event-driven architecture spreads through organisations rather than through codebases.

A **bounded context** (from Domain-Driven Design) is a boundary within which a set of terms has one consistent meaning. "Order" means something different in sales, in fulfilment and in finance, and building one shared `Order` object for all three is how you get a model nobody can change. Events are how bounded contexts integrate: each publishes facts in its own language, and each consumer translates into its own.

Melvin Conway observed in *How Do Committees Invent?* (Datamation, April 1968) that organisations which design systems are constrained to produce designs copying their own communication structures. The usual reading is fatalistic; the useful one is that if two teams must coordinate a deploy to ship a change, they will build a system whose components must be deployed together. So **the architecture that lets teams ship independently is the one where they integrate through published facts rather than calls into each other's services.** Events buy deploy independence at the organisational level — which is why the spatial-coupling row of Lesson 1's table is the one that changes how companies build software.

And how do you *find* the events in a domain? **Event storming**: put everyone with domain knowledge in a room, write every business fact anyone can think of on a sticky note in the past tense, arrange them on a wall in time order, then add the commands that cause them, the actors who issue those commands, and the policies ("whenever X, then Y") that connect them. A few hours, no software, and it reliably produces two things a design document cannot — a shared vocabulary, and the discovery that two teams have been using the same word for different things. Start there, not at the broker's config file.

## Think about it

1. Classify each as **event**, **command** or **query**, say what you would rename it, and state which of Lesson 1's three couplings the current design actually breaks: (a) `InvoiceOverdue`, published nightly by a scheduler; (b) `RecalculateCreditScore`, published to a topic one service subscribes to; (c) `CustomerAddressChanged`, carrying only `{customer_id}`; (d) `FraudCheckRequested`, published by an orchestrator that waits for `FraudCheckCompleted`.

2. A subscription-billing process does five things on renewal day: charge the card, extend the entitlement, issue an invoice PDF, update the revenue ledger, email the customer. It gains a step roughly every quarter, finance asks weekly "why did customer 8812 not renew?", and a failed charge must not leave an extended entitlement. Choose choreography or orchestration, justify it against at least four rows of the decision table, then name the one part you would deliberately build the *other* way.

3. Step 4 of your saga hands a physical parcel to a courier, and it is not the last step. Where does the pivot go, what happens if step 5 fails, and what is the compensation for step 4 if the failure is detected forty minutes after dispatch? State which of your answers are engineering decisions and which are business decisions someone else must sign off.

4. A team reports: "we're event-driven, but every deploy of `catalog` breaks `search` and `pricing`, and `catalog` must be redeployed whenever anyone adds a feature to `recommendations`." Name the specific anti-patterns, prescribe a fix for each, and say which of the three event styles you would move them to and why that symptom is the evidence.

5. Two systems are proposed for event sourcing: (a) a trading ledger where regulators ask why any position had any value on any past date, and corrections must never destroy the original record; (b) a product catalogue where editors change descriptions and images, and the only query is "show me the current product". Decide yes or no for each, and name the *specific* cost that decides it.

6. Your saga sets `order.status = PAYMENT_PENDING` as a semantic lock during T2, and a support tool lets agents cancel orders without checking that field. Describe the concrete bug, connect it to the missing **I** in ACID, then give one fix in the support tool and one in the saga design — and say which you would ship first.

## Key takeaways

- **Event, command and query are indistinguishable on the wire and completely different in architecture.** An event is a past-tense fact with 0..N recipients unknown to the sender, and cannot be rejected. A command is an imperative instruction to one known recipient, and can be. A query is a request for data, and is synchronous communication whatever transport carries it.
- **The payoff of events is the reversed dependency arrow.** With commands the producer depends on its consumers; with events each consumer depends on a published contract the producer owns. Commands over a broker are legitimate — durability, buffering, retries — but they break only **temporal** and **load** coupling, never **spatial**. Mislabelling a command as an event is what produces a **distributed monolith**.
- **Three event styles, three different bills.** *Notification* (an id only) is cheap and evolvable but forces callbacks, rebuilding the synchronous fan-in with worse latency. *Event-carried state transfer* buys real consumer autonomy — the consumer works while the producer is down — at the cost of size, duplication, staleness, and a payload that is now a contract. *Event sourcing* makes the log the system of record and dissolves the dual-write problem, but costs permanent schema-evolution debt, hard GDPR deletion, projections to rebuild, and snapshots. **You do not need event sourcing to do event-driven architecture.**
- **Choreography vs orchestration is a choice about where the flow lives.** Choreography maximises autonomy and leaves no artifact describing the process — debugging starts with a distributed trace, and accidental reaction cycles are easy to create. Orchestration makes the process explicit, inspectable and testable, at the cost of a component that knows everyone. Choose by participant count, branching, need for compensation, auditability and rate of change. The pragmatic hybrid: **choreography between bounded contexts, orchestration within a business transaction that needs atomicity.**
- **A saga (Garcia-Molina & Salem, SIGMOD 1987) is a sequence of local transactions `T1..Tn`, each with a compensating transaction `Ci`**, guaranteeing either `T1..Tn` completes or `T1..Tj, Cj..C1` runs. It is what replaces the distributed transaction that Lesson 10 ruled out, and it trades **isolation** for concurrency — exactly the trade the 1987 paper made.
- **Compensation is not rollback.** The step already committed and the world already saw it. You issue a refund, release a reservation, send an apology email — new forward actions with business consequences, not physical undos. Each is a business decision encoded in code, so design them with the people who own the money. Compensations must be idempotent, run in reverse order, retry for hours before escalating, and never share a dead-letter queue with normal traffic.
- **A saga is ACD, not ACID — there is no isolation**, so other transactions will observe half-completed sagas. Make the intermediate state first-class with a **semantic lock** (`PAYMENT_PENDING`, `RESERVED`, an authorisation hold) that expires, and put your **pivot** — the last irreversible step — as late in the sequence as possible: steps before it are compensatable, steps after it are retriable-until-success.
- **Design events as business facts, not database rows.** Past tense, domain language, owned by one bounded context, versioned (Lesson 12), immutable — corrections are new events — carrying the aggregate id as partition key (Lesson 7) and trace context (Lesson 2). Prefer one coarse business event over a storm of field-level changes, but avoid the god event whose schema is the union of every consumer's wish list.
- **Do not use event-driven architecture** where an invariant needs immediate, isolated enforcement ("two people must not book seat 14C"), for simple CRUD with no interested third parties, in teams small enough that the fixed operational overhead exceeds the coupling removed, or before consumers are idempotent and requests are traceable across services. Those last two are entry fees, not optimisations.

Next: [Schema Evolution & Event Contracts](../12-schema-evolution-and-event-contracts/) — you have just made the event payload a public API with an unknown number of consumers, so the next question is unavoidable: how do you change it without a synchronised deploy, and what exactly does "compatible" mean?
