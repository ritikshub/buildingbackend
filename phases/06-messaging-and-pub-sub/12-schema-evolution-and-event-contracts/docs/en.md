# Schema Evolution & Event Contracts

> A REST endpoint's breaking change hurts until the last client upgrades. An event's breaking change hurts forever, because the log still holds every message you ever wrote and one of them was written under a schema nobody remembers. This lesson is about the contract you signed with your own past — how to keep it, how to tell which changes break it, and how to read a message written ninety days and three schema versions ago.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Event-Driven Architecture: Commands, Choreography & Sagas](../11-event-driven-architecture/)
**Time:** ~70 minutes

## The Problem

Your `OrderPlaced` event has been in production for a year. Six services consume it. Then three things happen, in this order, each worse than the last.

**Failure one: Tuesday, 14:02.** A developer adds a `currency` field to `OrderPlaced` — required, because an order without a currency is meaningless and the reviewer agreed. The producer deploys. Within ninety seconds, four of the six consumers are throwing validation errors on **every single message**, because their JSON Schema validator has `additionalProperties: false` and a message carrying a field it has never heard of is, by that rule, invalid.

Nobody did anything unreasonable. The producer team shipped a field their product needed. The consumer teams turned on strict validation because a linter told them to. But nobody could deploy in the right order, because there *is* no right order across six teams with six release trains — and the outage was total from the first message.

**Failure two: the one nobody notices for three days.** Chastened, the team makes a smaller change. They rename `total` to `total_amount` for clarity. No consumer crashes. Not one. Every consumer reads a field that is now absent, gets back the language's default — `0` in Go, `0` from `dict.get(key, 0)` in Python, `undefined → NaN → 0` after a coercion in JavaScript — and carries on. The analytics warehouse dutifully records **every order as being worth nothing**.

Three days later a finance analyst asks why revenue fell off a cliff. There were no exceptions. No error logs. No alerts, because you alert on error *rates*, and the error rate was zero. In the measured run at the end of this lesson, 5,000 real orders worth **EUR 1,257,034.30** are read by the renamed consumer and total **EUR 0.00**, with zero exceptions raised and zero log lines written. A loud outage costs you an afternoon. A quiet one costs you the last three days of every number your company makes decisions with — plus however long it takes to re-derive them, if you still can.

**Failure three: the one unique to this phase.** A bug is found in the pricing consumer. The fix is easy; the recovery is not. You need to **replay** the last ninety days from the log — exactly the capability [The Log: Offsets, Retention & Replay](../05-the-log-offsets-and-replay/) existed to give you. You rewind the consumer group to offset zero, and it dies on the first record, because that record was written two schema versions ago and the current code cannot parse it. In the measured run, a consumer that understands only the newest schema processes **0 of 9,000** records in a 90-day log.

The replay — the whole reason you chose a log instead of a queue — is impossible. Not degraded. Impossible.

Put failures one and two side by side, because the instinct they provoke — "so validate strictly, then" — is exactly half right and the other half is why this lesson has a Build section.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 424" width="100%" style="max-width:840px" role="img" aria-label="The same 5,000 records missing the same field, read two ways. A tolerant but naive reader defaults the missing field to zero and reports EUR 0.00 against a true value of EUR 1,257,034.30, raising no exceptions, writing no log lines and firing no alerts. A strict validator halts loudly at record 1 of 5,000, naming the missing field.">
  <defs>
    <marker id="l12-b-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One missing field, two readers, two very different bills</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="18" y="140" width="176" height="118" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="268" y="52" width="594" height="150" rx="13" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
    <rect x="268" y="222" width="594" height="140" rx="13" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M194 180 L 230 180 L 230 118 L 262 118" marker-end="url(#l12-b-arrow)"/>
    <path d="M194 200 L 230 200 L 230 288 L 262 288" marker-end="url(#l12-b-arrow)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="106" y="166" font-size="10.5" font-weight="700" text-anchor="middle">5,000 records</text>
    <text x="106" y="184" font-size="9" text-anchor="middle" opacity="0.9">written under v1</text>
    <text x="106" y="200" font-size="9" text-anchor="middle" opacity="0.9">field: total_cents</text>
    <text x="106" y="222" font-size="9.5" font-weight="700" text-anchor="middle" fill="#3553ff">TRUE VALUE</text>
    <text x="106" y="240" font-size="10" font-weight="700" text-anchor="middle">EUR 1,257,034.30</text>
    <text x="288" y="78" font-size="12" font-weight="700" fill="#e0930f">TOLERANT BUT NAIVE — rec.get("total_amount", 0)</text>
    <text x="288" y="100" font-size="9.5" opacity="0.9">the field is gone, so the language hands back its zero value</text>
    <text x="288" y="120" font-size="10.5" font-weight="700">reported total   EUR 0.00</text>
    <text x="288" y="144" font-size="9.5" opacity="0.9">exceptions raised 0   log lines written 0   alerts fired 0</text>
    <text x="288" y="162" font-size="9.5" opacity="0.9">records skipped 0   error rate 0%   dashboards all green</text>
    <text x="288" y="188" font-size="10.5" font-weight="700" fill="#e0930f">THREE DAYS OF SILENTLY WRONG NUMBERS — and no signal to find it by</text>
    <text x="288" y="248" font-size="12" font-weight="700" fill="#0fa07f">STRICT — assert "total_amount" in rec</text>
    <text x="288" y="270" font-size="9.5" opacity="0.9">the field is gone, so the very first record fails the assertion</text>
    <text x="288" y="292" font-size="10.5" font-weight="700">HALTED at record 1 of 5,000</text>
    <text x="288" y="312" font-size="9.5" opacity="0.9">"missing required field 'total_amount'"</text>
    <text x="288" y="336" font-size="10.5" font-weight="700" fill="#0fa07f">ONE PAGE, ONE ROLLBACK, ZERO CORRUPTED ROWS</text>
    <text x="440" y="392" font-size="10" text-anchor="middle" opacity="0.95">Neither reader is right on its own. Assert on the fields you actually consume; ignore everything else.</text>
    <text x="440" y="410" font-size="9.5" text-anchor="middle" opacity="0.78">Strictness applied to the WHOLE message is what caused failure one. Strictness applied to YOUR slice is what catches failure two.</text>
  </g>
</svg>
```

That third failure is the one that reframes everything. In a request/response API (Phase 2, Lesson 05), a breaking change is painful *until every client upgrades*, and then it is over; old requests are not retained anywhere, and time heals it. In an event-driven system, **old events live forever in the log**. Every schema you ever published is still out there in bytes you still own. A schema is therefore a contract with the **past** as well as the future, and the past does not upgrade. This is strictly harder than REST versioning, and it deserves to be treated as its own discipline rather than as "versioning, but for messages".

## The Concept

### An event schema is a public API with an unbounded lifetime and an unknown consumer set

Two properties make an event schema harder than an HTTP API, and both come directly from things you already built.

**You cannot enumerate your consumers.** That was the *point* of [Pub/Sub: Topics & Fan-Out](../04-pub-sub-topics-and-fan-out/) — the producer writes to a topic and never names a subscriber, which is what lets a new team start consuming `OrderPlaced` without anyone editing the orders service. The price of that decoupling is arriving now: you cannot call a meeting of everyone affected by your change, because you do not have the list. A REST API has an access log with client identities in it. A topic has subscribers who may have joined last week and may be in another business unit.

**Your data has no expiry.** In a request/response system, the oldest request in flight is a few seconds old. In a retained log, the oldest record is as old as your retention window — 7 days, 90 days, or, for an event-sourced system where the log *is* the database, the age of the company.

Put together: you must make a change that is safe for consumers you cannot list, applied to data you cannot rewrite. Coordination is unavailable, so **compatibility rules replace coordination.** That is the whole idea. A compatibility rule is a constraint you accept on your changes in exchange for never having to synchronise a deploy.

### The compatibility modes, defined exactly

These four terms are misused constantly, including in vendor documentation, so pin them down with the two roles that actually matter. The **writer** is the code that serialised a record. The **reader** is the code deserialising it. Compatibility is always a question about a *pair*.

- **Backward compatible** — **new code can read old data.** The new schema is the reader; an older schema was the writer. This is what lets you deploy the *consumer* first, and it is the property required to **replay history**, because in a replay the reader is always new and the data is always old.
- **Forward compatible** — **old code can read new data.** An older schema is the reader; the new schema is the writer. This is what lets you deploy the *producer* first, and it is what you need when you cannot upgrade every consumer before the producer ships — which, per the previous section, is most of the time.
- **Full compatible** — both. Any deploy order works.
- **None** — no check. The registry accepts anything.

The mnemonic that survives an interview: **backward looks backward in time at old data; forward looks forward in time at new data.** The direction names the *data*, not the code.

Now the part that most teams get wrong. Each of those has a **transitive** variant. A plain `BACKWARD` check compares your candidate against **only the immediately preceding version**. `BACKWARD_TRANSITIVE` compares it against **every version ever registered**.

That distinction sounds pedantic and is not. Non-transitive checks compose badly: v2 is compatible with v1, v3 is compatible with v2, and v3 is *not* compatible with v1. Compatibility is not transitive by nature, which is exactly why the transitive mode has to be asked for explicitly. And "compatible with v1" is precisely what a replay from the start of the log needs. The measured matrix later in this lesson contains two changes that a non-transitive check accepts and a transitive check rejects — a tag reuse and a re-used field name — and both of them corrupt data silently rather than failing loudly.

**A non-transitive check on a retained log gives you a false sense of safety**: it certifies that your new consumer can read the most recent messages, which was never the question. The question was whether it can read the oldest message still in retention.

| Mode | Reader | Writer | Checked against | Deploy order it permits |
|---|---|---|---|---|
| `BACKWARD` | new | previous version | latest only | **consumers first**, then producers |
| `BACKWARD_TRANSITIVE` | new | *all* previous versions | all | consumers first, **and replay works** |
| `FORWARD` | previous version | new | latest only | **producers first**, then consumers |
| `FORWARD_TRANSITIVE` | *all* previous versions | new | all | producers first, **including stale consumers** |
| `FULL` | both | both | latest only | either order |
| `FULL_TRANSITIVE` | both | both | all | **either order, and replay works** |

**The practical default for events on a retained log is `FULL_TRANSITIVE`.** It is the strictest mode, it rejects changes you will want to make, and that is the trade: you give up the ability to make certain changes in exchange for never having to coordinate a deploy and never losing the ability to read your own history. If your log is a durable archive — and if you chose a log over a queue, it is — anything weaker is a promise you cannot keep.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="Backward compatibility means new code reads old data and permits deploying consumers first, which is also what replay requires. Forward compatibility means old code reads new data and permits deploying producers first. Transitive variants check against every registered version rather than only the immediately previous one, which is what catches a reused field tag between version one and version four.">
  <defs>
    <marker id="l12-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
    <marker id="l12-arrowg" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/>
    </marker>
    <marker id="l12-arrowb" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The direction names the DATA, not the code</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="848" height="150" rx="13" fill="#0fa07f" fill-opacity="0.07" stroke="#0fa07f"/>
    <rect x="16" y="204" width="848" height="150" rx="13" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff"/>
    <rect x="16" y="364" width="848" height="90" rx="13" fill="#e0930f" fill-opacity="0.08" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="60" y="112" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="188" y="112" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="316" y="112" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="444" y="112" width="92" height="46" rx="9" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/>
    <rect x="60" y="272" width="92" height="46" rx="9" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/>
    <rect x="188" y="272" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="316" y="272" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="444" y="272" width="92" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
  </g>
  <g fill="none" stroke="#0fa07f" stroke-width="2">
    <path d="M482 108 L 482 92 L 106 92 L 106 108" marker-end="url(#l12-arrowg)"/>
    <path d="M482 108 L 482 92 L 234 92 L 234 108" marker-end="url(#l12-arrowg)"/>
    <path d="M482 108 L 482 92 L 362 92 L 362 108" marker-end="url(#l12-arrowg)"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="2">
    <path d="M106 268 L 106 252 L 234 252 L 234 268" marker-end="url(#l12-arrowb)"/>
    <path d="M106 268 L 106 252 L 362 252 L 362 268" marker-end="url(#l12-arrowb)"/>
    <path d="M106 268 L 106 252 L 490 252 L 490 268" marker-end="url(#l12-arrowb)"/>
  </g>
  <g fill="none" stroke="#e0930f" stroke-width="2" stroke-dasharray="6 4">
    <path d="M700 404 L 760 404" marker-end="url(#l12-arrow)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="12.5" font-weight="700" fill="#0fa07f">BACKWARD — new code reads OLD data</text>
    <text x="36" y="88" font-size="9.5" opacity="0.85">the reader is the new schema; the writers are everything already in the log</text>
    <text x="106" y="140" font-size="10.5" font-weight="700" text-anchor="middle">v1 data</text>
    <text x="234" y="140" font-size="10.5" font-weight="700" text-anchor="middle">v2 data</text>
    <text x="362" y="140" font-size="10.5" font-weight="700" text-anchor="middle">v3 data</text>
    <text x="490" y="132" font-size="10.5" font-weight="700" text-anchor="middle" fill="#0fa07f">v4 READER</text>
    <text x="490" y="148" font-size="8.5" text-anchor="middle" opacity="0.85">new consumer</text>
    <text x="576" y="112" font-size="10.5" font-weight="700">upgrade CONSUMERS first</text>
    <text x="576" y="130" font-size="9.5" opacity="0.9">solid arrows = the transitive check</text>
    <text x="576" y="147" font-size="9.5" opacity="0.9">plain BACKWARD only checks v3 -&gt; v4</text>
    <text x="576" y="170" font-size="10" font-weight="700" fill="#0fa07f">REQUIRED FOR REPLAY</text>
    <text x="36" y="230" font-size="12.5" font-weight="700" fill="#3553ff">FORWARD — old code reads NEW data</text>
    <text x="36" y="248" font-size="9.5" opacity="0.85">the writer is the new schema; the readers are every consumer not yet upgraded</text>
    <text x="106" y="292" font-size="10.5" font-weight="700" text-anchor="middle" fill="#3553ff">v4 WRITER</text>
    <text x="106" y="308" font-size="8.5" text-anchor="middle" opacity="0.85">new producer</text>
    <text x="234" y="300" font-size="10.5" font-weight="700" text-anchor="middle">v2 reader</text>
    <text x="362" y="300" font-size="10.5" font-weight="700" text-anchor="middle">v3 reader</text>
    <text x="490" y="300" font-size="10.5" font-weight="700" text-anchor="middle">v1 reader</text>
    <text x="576" y="272" font-size="10.5" font-weight="700">upgrade PRODUCERS first</text>
    <text x="576" y="290" font-size="9.5" opacity="0.9">the v1 reader is the one nobody</text>
    <text x="576" y="307" font-size="9.5" opacity="0.9">remembers is still running</text>
    <text x="576" y="330" font-size="10" font-weight="700" fill="#3553ff">FULL = BOTH ROWS AT ONCE</text>
    <text x="36" y="390" font-size="12" font-weight="700" fill="#e0930f">WHY TRANSITIVE IS NOT PEDANTRY</text>
    <text x="36" y="410" font-size="9.5" opacity="0.9">v2 retires field tag 7 without reserving it. v4 reuses tag 7 for warehouse_id.</text>
    <text x="36" y="428" font-size="9.5" opacity="0.9">v3 -&gt; v4 is clean, so BACKWARD and FORWARD both say ACCEPT. v1 -&gt; v4 aliases</text>
    <text x="36" y="446" font-size="9.5" opacity="0.9">gift_message onto warehouse_id — silently. Only the _TRANSITIVE modes catch it.</text>
    <text x="790" y="399" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">row 11</text>
    <text x="790" y="416" font-size="9" text-anchor="middle" opacity="0.9">measured</text>
    <text x="790" y="432" font-size="9" text-anchor="middle" opacity="0.9">in Build It</text>
  </g>
</svg>
```

### Safe and unsafe changes — the table you use in review

This is the reference. Every row is measured in the Build It section against all six modes.

| Change | Verdict | Why |
|---|---|---|
| **Add an optional field with a default** | **SAFE** | New readers fill the default when reading old data; old readers ignore an unknown field. The only genuinely free change. |
| **Add a required field (no default)** | breaks **backward** | A new reader demands a field that no historical record contains and has nothing to fall back on. (It also breaks **forward** if any consumer validates strictly — that is failure one.) |
| **Remove an optional field** | **safe-ish** | Structurally fine both ways. But a consumer that *depends* on that field now silently gets its default. "Optional in the schema" is not "unused in production." |
| **Remove a required field** | breaks **forward** | Every old reader still demands it and it is no longer emitted. The mirror image of adding one. |
| **Rename a field** | breaks **both** | A rename is a **delete plus an add**, so it takes both failures at once — and because the delete half produces a *missing field* rather than an error, it is the failure-two silent corruption. There is no such thing as a rename on the wire. |
| **Widen a type** (int32 → int64) | **backward only** | Avro's promotion rules let a value written as `int` be read as `long`, but not the reverse. Consumers must be upgraded first. |
| **Narrow a type** (int64 → int32) | **forward only** | The mirror: old readers can widen your new narrow values, but new readers cannot read historical values that no longer fit. Practically: don't. |
| **Change units or meaning, same name and type** | **UNDETECTABLE — the worst change there is** | Cents to euros. Seconds to milliseconds. UTC to local. **No schema checker on earth detects this**, because structurally nothing changed. Every mode returns ACCEPT and your numbers are wrong by a factor of 100. The fix is never to redefine a field: add `total_eur` and leave `total_cents` alone forever. |
| **Add an enum value** | breaks **forward** | Genuinely underappreciated. Old readers with an exhaustive `match`/`switch` and no default arm throw on the first message carrying the new symbol — and in a partitioned consumer that is head-of-line blocking, not one bad record. |
| **Change cardinality** (single → repeated) | breaks **both** | `string` and `array<string>` are different wire shapes with no promotion in either direction. |
| **Reorder field declarations** | **SAFE** | Identity is the field's name and tag, never its position. Any reader that depends on order is broken already. |
| **Reuse a retired field number** (Protobuf) | **SILENT CORRUPTION** | Tags, not names, are the wire identity in Protobuf: the encoded bytes carry `7`, not `gift_message`. Reuse tag 7 and every historical record's `gift_message` decodes as your new `warehouse_id` with no error. This is why Protobuf has `reserved` — declaring `reserved 7;` makes even a non-transitive checker sufficient. |

Two of those rows deserve emphasis because they are the ones that hurt.

**The rename is dangerous because it is not atomic on the wire.** You think of it as one operation; the serialisation format sees a field disappear and an unrelated field appear. And of the two halves, the disappearance is the dangerous one, because a missing field is not an error in most readers — it is a default.

**The units change is dangerous because it is invisible.** Every other row in this table can be caught by a machine. That one cannot, by anyone, ever. It is the only change on the list where the control has to be a human in a review, which is exactly why the checklist in `outputs/` puts it in bold.

### Defaults are the mechanism that makes evolution work at all

Strip away the vocabulary and every compatibility rule reduces to one question: **when a field is absent from the bytes, what value does the reader use?** If the answer is "a defined default", the schema can evolve. If the answer is "an error" or "whatever the language does", it cannot.

This is why the **Apache Avro specification** requires a `default` on a field if you want readers using a newer schema to read older data — schema resolution states that if the reader's record has a field with no counterpart in the writer's record, the reader uses that field's default, and it is an error if none is specified. Avro made the requirement explicit and mandatory, and that single design decision is most of why Avro is the format of choice for long-lived event logs.

**Protocol Buffers takes the opposite route to the same place**: every scalar field has an implicit zero value (`0`, `""`, `false`, empty list), so a field absent from the wire is never an error. Evolution is safe by construction.

And that convenience is a trap, which is where failure two comes from. If absent means zero, then **absent is indistinguishable from legitimately zero**. Did this order really have a `discount_cents` of 0, or did the producer not send the field? Did `total` really become 0, or did someone rename it? Your code cannot tell, and neither can your dashboard. Proto3 acknowledged this by re-introducing explicit presence: marking a field `optional` in proto3 generates a `has_field()` accessor so you can distinguish "unset" from "set to zero". Use it for anything where zero is a meaningful value — money, counts, scores, temperatures.

The general rule: **a default must be a value that is correct for records that predate the field.** `currency` defaulting to `"EUR"` is right if and only if everything before the multi-currency launch really was in euros. A default is a historical claim, and writing one down is the moment to check whether it is true.

### The tolerant reader

Postel's principle — be conservative in what you send, liberal in what you accept — applied to messages. A **tolerant reader**:

1. **Ignores unknown fields.** Silently. Not a warning, not a metric, not an error.
2. **Never fails on extra data.** A message with more in it than you expected is a message from the future, and the future is allowed to have more fields.
3. **Validates only what it actually uses.** A shipping consumer that needs `order_id` and `address` should not care that `payment_method` changed type. Validate your slice, not the whole document.
4. **Never assumes field order**, and never assumes the field set is closed.
5. **Has a default arm on every match.** Unknown enum symbol means "not mine, skip or park it", never "crash".

Failure one in The Problem is caused entirely by violating rule 1. A validator configured with `additionalProperties: false` — the JSON Schema keyword that rejects any property not explicitly declared — turns *every* additive change, including the safest change on the table, into an outage. In the measured run, switching from a tolerant reader to a strict one flips **6 of the 17** `BACKWARD`/`FORWARD` accepts into rejects. Strict validation on inbound events converts your compatibility policy into a fiction.

There is a real counter-argument: strictness catches typos and malformed producers early, and "just ignore it" can hide a genuine integration bug for months. The resolution is *where* you are strict. Be strict on the fields you consume — assert `order_id` is present and is a string, reject the message to the dead-letter queue from [Retries, Backoff & Dead-Letter Queues](../08-retries-backoff-and-dead-letter-queues/) if it isn't. Be permissive about everything else. Strict about your slice, tolerant about the rest.

### Schema registries: writer's schema versus reader's schema

The mechanism that makes all of this operational is a **schema registry**: a service holding schemas under a **subject** (usually one per topic), each subject holding an ordered list of **versions**, with a globally unique **schema id** per registered schema, and a **compatibility mode** enforced on every registration.

The message on the wire then carries **the schema id, not the schema**. In the measured run, the three registered versions of `OrderPlaced` are 513–514 bytes of schema text each, and the average payload is 133 bytes. Embed the schema in every message and you ship 666 bytes per event — **399% overhead**, four times the actual data. Ship a magic byte plus a 4-byte id and you ship 138 bytes: **3.8% overhead**, and the wire is **4.8× smaller** across the corpus. At 5,000 events/second, the difference is **212 GB/day of pure schema text**.

But the size win is the lesser benefit. The important one: because the id is on every record and the registry never deletes a schema, **the writer's schema is always retrievable for any record, forever**. That is what makes old data readable, and it is the single mechanism that closes failure three.

That gives you Avro's model of deserialisation, which is the cleanest formulation of what evolution actually *is*:

```text
writer's schema   the schema the record was serialised with   (fetched by id from the registry)
reader's schema   the schema your code was compiled against   (the only one you know)
resolution        a mechanical rule set that maps one onto the other, field by field
```

The reader never parses bytes "generically". It parses them **against the writer's schema** and projects the result **onto its own schema**: fields present in both are matched by name and type-promoted if needed; fields only the writer has are skipped; fields only the reader has are filled from the reader's defaults. Compatibility, then, is not a vague property — it is the precise question *"does resolution succeed for this (reader, writer) pair?"*, and that is the function you will implement in thirty lines.

The last piece is a control: **the compatibility check runs in CI, before the schema is registered, and fails the build.** A registry that accepts an incompatible schema has already lost — the incompatible producer will deploy and write records nobody can read. The gate has to be upstream of the deploy, not a runtime error afterwards.

### Versioning strategies, and when each is right

Four approaches, in increasing order of weight.

**1. A `schema_version` in the envelope, plus a tolerant reader.** The envelope from [Anatomy of a Message](../02-anatomy-of-a-message/) carries the version; consumers branch on it where they must and tolerate everything else. Simplest, most common, and adequate for a queue with short retention. It degrades badly as versions accumulate, because every consumer grows a version-dispatch tree that nobody dares delete.

**2. Upcasting — the technique most worth learning.** Keep a chain of small, pure functions `v1→v2`, `v2→v3`, `v3→v4`, each doing exactly one migration. On read, look at the record's version and apply the hops needed to lift it to the current version. **Consumer business logic then only ever knows the newest shape.**

```python
def up_1_to_2(r):            # v1 predates multi-currency
    out = {k: v for k, v in r.items() if k != "gift_message"}
    out["currency"] = "EUR"  # ...so EUR is the historically correct default
    return out

def up_3_to_4(r):            # the rename, made survivable
    out = dict(r)
    out["total_amount"] = out.pop("total_cents")
    return out
```

Everything good about this comes from the functions being *pure and individually testable*. Each hop is a few lines with a unit test; the chain is composition; and a `v1` record and a `v4` record are literally the same object by the time your handler sees them. This is the technique that makes long-retention logs and **event sourcing** tractable — in an event-sourced system the log is the source of truth and can never be rewritten, so upcasters are the only migration tool that exists.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="A ninety day log holding three schema generations: 2,400 version one records, 2,800 version two records and 3,800 version three records. A chain of three upcaster functions lifts every record to version four at read time, so a consumer that understands only version four processes all 9,000 records, where without upcasters it processes none of them.">
  <defs>
    <marker id="l12-c-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One consumer, ninety days, three schema generations</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="64" width="212" height="58" rx="9" fill="#e0930f" fill-opacity="0.15" stroke="#e0930f"/>
    <rect x="248" y="64" width="240" height="58" rx="9" fill="#7c5cff" fill-opacity="0.15" stroke="#7c5cff"/>
    <rect x="494" y="64" width="336" height="58" rx="9" fill="#3553ff" fill-opacity="0.15" stroke="#3553ff"/>
    <rect x="192" y="196" width="150" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="366" y="196" width="150" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="540" y="196" width="150" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="252" y="298" width="376" height="64" rx="11" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5">
    <path d="M136 128 L 136 219 L 186 219" marker-end="url(#l12-c-arrow)"/>
    <path d="M368 128 L 368 176 L 441 176 L 441 190" marker-end="url(#l12-c-arrow)"/>
    <path d="M662 128 L 662 176 L 615 176 L 615 190" marker-end="url(#l12-c-arrow)"/>
    <path d="M342 219 L 360 219" marker-end="url(#l12-c-arrow)"/>
    <path d="M516 219 L 534 219" marker-end="url(#l12-c-arrow)"/>
    <path d="M690 219 L 716 219 L 716 268 L 440 268 L 440 292" marker-end="url(#l12-c-arrow)"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="136" y="86" font-size="11" font-weight="700" text-anchor="middle">v1 · days 1-24</text>
    <text x="136" y="103" font-size="10" text-anchor="middle">2,400 records</text>
    <text x="136" y="117" font-size="8.5" text-anchor="middle" opacity="0.8">total_cents, gift_message</text>
    <text x="368" y="86" font-size="11" font-weight="700" text-anchor="middle">v2 · days 25-52</text>
    <text x="368" y="103" font-size="10" text-anchor="middle">2,800 records</text>
    <text x="368" y="117" font-size="8.5" text-anchor="middle" opacity="0.8">+ currency</text>
    <text x="662" y="86" font-size="11" font-weight="700" text-anchor="middle">v3 · days 53-90</text>
    <text x="662" y="103" font-size="10" text-anchor="middle">3,800 records</text>
    <text x="662" y="117" font-size="8.5" text-anchor="middle" opacity="0.8">+ channel</text>
    <text x="440" y="152" font-size="9.5" text-anchor="middle" opacity="0.85">the retained log — 9,000 records the producer wrote under three different contracts</text>
    <text x="267" y="215" font-size="9.5" font-weight="700" text-anchor="middle">up_1_to_2</text>
    <text x="267" y="231" font-size="8" text-anchor="middle" opacity="0.85">currency = "EUR"</text>
    <text x="441" y="215" font-size="9.5" font-weight="700" text-anchor="middle">up_2_to_3</text>
    <text x="441" y="231" font-size="8" text-anchor="middle" opacity="0.85">channel = "web"</text>
    <text x="615" y="215" font-size="9.5" font-weight="700" text-anchor="middle">up_3_to_4</text>
    <text x="615" y="231" font-size="8" text-anchor="middle" opacity="0.85">total_cents -&gt; total_amount</text>
    <text x="440" y="262" font-size="9" text-anchor="middle" opacity="0.8">pure functions, one migration each, applied at READ time — a v1 record pays 3 hops, a v3 record pays 1</text>
    <text x="440" y="322" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">THE CONSUMER — knows v4 and nothing else</text>
    <text x="440" y="340" font-size="9.5" text-anchor="middle" opacity="0.9">no version branch, no legacy field names, no if-statements about history</text>
    <text x="440" y="356" font-size="10" text-anchor="middle" font-weight="700">9,000 of 9,000 processed · sum EUR 2,263,290.88 · exact match</text>
    <text x="440" y="390" font-size="10.5" text-anchor="middle" font-weight="700" fill="#e0930f">Remove the three upcasters and the same consumer processes 0 of 9,000.</text>
    <text x="440" y="410" font-size="9.5" text-anchor="middle" opacity="0.8">Expand-contract never completes on a retained log, so these functions are production code forever — not migration scaffolding.</text>
  </g>
</svg>
```

The measured run replays 9,000 records across three schema generations and processes **100%** of them with a consumer that understands only v4, producing an aggregate that matches the expected value exactly.

**3. A new topic per major version, with dual publishing.** `orders.placed.v1` and `orders.placed.v2` are separate topics; the producer writes both during the migration; consumers move over one at a time; the old topic is eventually retired. Heavyweight — double the storage, double the write path, and a genuine risk of the two topics diverging — but it is sometimes the only safe option for a truly breaking change, and unlike the others it has a clean end state.

**4. Expand-contract (parallel change).** The migration sequence that makes a breaking change out of a series of non-breaking ones:

```text
1. EXPAND    add total_amount alongside total_cents. Both optional, both defaulted.
2. DUAL-WRITE  the producer writes both fields, with identical values.
3. MIGRATE   consumers switch to total_amount, one team at a time, on their own schedule.
4. VERIFY    confirm nobody reads total_cents — consumer-group observability, not a survey.
5. CONTRACT  stop writing total_cents. Later, remove it from the schema. Never reuse its tag.
```

Now the crucial caveat, and it is the thing that separates events from database columns. When you contract a column, the old column is gone and the migration is over. When you contract an *event field*, **every record already in the log still has the old shape**. You cannot rewrite history, so step 5 completes only for *future* records. Any replay still meets `total_cents`.

Which means: **on a retained log, upcasters are permanent.** The `v3→v4` upcaster is not migration scaffolding to be deleted after the rollout — it is production code for as long as the log holds a v3 record, which for an event-sourced system is forever. Budget for it. Test it. Put it behind an interface. Do not let a well-meaning cleanup PR delete it in eighteen months.

### Consumer-driven contracts and the historical corpus

Two testing practices convert all of this from policy into something CI can enforce.

**Keep a corpus of real historical messages** — a few hundred actual records sampled across your retention window, *including the oldest one still retained*, checked into the repo as a fixture. Every candidate schema and every consumer change runs against it. This is the only test that catches the class of bug where the schema check passes and the consumer still breaks, because the schema was never the whole contract: the consumer also depends on values, ranges, and enum symbols that the schema permits but never actually contained. Refresh the corpus on a schedule so it tracks the retention window.

**Consumer-driven contract testing** inverts the dependency. Each consumer publishes a machine-readable statement of what it depends on — "I read `order_id`, `total_amount` and `status`; I handle the symbols `placed`, `paid`, `shipped`". The producer's CI runs every published consumer contract against the candidate schema. **The producer's build fails before the deploy, rather than the consumer's pager firing after it.** It also solves a political problem: the producer team gets an automated, specific, un-ignorable signal instead of a Slack message from a team they've never met.

### Ownership, deprecation, and "who is listening?"

The remaining failures are organisational, and they are the ones that actually bite in a large company.

**Every event schema has exactly one owning team**, named in the schema itself (Avro and Protobuf both carry doc/option metadata; use it) and in the registry. Shared ownership means no ownership, and an event with no owner accumulates fields nobody can explain and cannot be deprecated by anyone.

**A schema change is a reviewed change**, in a pull request, in the same repository as the schema, with the compatibility check as a required status. Classify the change against the table above in the PR description. That single sentence — "this is an additive change with a default, `FULL_TRANSITIVE` clean" — is what makes review possible for someone who is not deep in your domain.

**Deprecation needs a real timeline, not an announcement.** Mark the field deprecated in the schema with a doc comment stating the removal date. Communicate it. Then *verify* — and this is the step people skip — that nobody reads it, before removing it.

**Which brings back the "who is listening?" problem from [Event-Driven Architecture](../11-event-driven-architecture/).** The registry tells you who *produces* (subjects and their owners); it does not tell you who consumes. The answer is a pair of tools you already have: a **registry plus consumer-group observability**. Every broker exposes its consumer groups, their offsets, and their lag — the same metrics you used for backpressure in [Backpressure, Lag & Flow Control](../09-backpressure-lag-and-flow-control/). Consumer groups on a topic *are* the subscriber list. Combine that with consumer-published contracts and you can answer "who reads `gift_message`?" with data instead of a survey, which is the difference between a deprecation that completes and one that stalls for two years.

## Build It

`code/schema_registry.py` implements the whole apparatus: a schema model with field tags, types, defaults and declared semantics; writer/reader resolution; the six compatibility modes; a registry that gates registration; upcasters; and the Confluent-style wire envelope. Standard library only, seeded, deterministic.

The heart of it is one function. Every compatibility mode is this function called with the arguments in a particular order:

```python
def can_read(reader: Schema, writer: Schema, strict: bool = False) -> list[str]:
    """Can code holding `reader` decode a record written with `writer`?"""
    problems: list[str] = []

    for tag in sorted(set(reader.by_tag) & set(writer.by_tag)):
        rf, wf = reader.by_tag[tag], writer.by_tag[tag]
        if rf.name != wf.name:                       # Protobuf's tag-reuse hazard
            problems.append(
                f"tag {tag} carries '{wf.name}' on the wire but means '{rf.name}' to the reader")

    for name in reader.order:
        rf, wf = reader.fields[name], writer.fields.get(name)
        if wf is None:                               # absent from the bytes...
            if not rf.has_default:                   # ...and nothing to fall back on
                problems.append(
                    f"reader needs '{name}', the writer never emits it, and it has no default")
            continue
        if not readable_as(wf.type, rf.type):        # Avro's promotion rules
            problems.append(
                f"'{name}' is {wf.type} on the wire, {rf.type} in the reader: no legal promotion")
            continue
        if wf.type.startswith("enum:"):
            unknown = [s for s in writer.enums[wf.type[5:]] if s not in reader.enums[rf.type[5:]]]
            if unknown and not rf.has_default:
                problems.append(
                    f"'{name}' may carry enum symbol {unknown[0]!r}, unknown to the reader")

    if strict:                                       # the anti-pattern, modelled
        for name in writer.order:
            if name not in reader.fields:
                problems.append(f"strict validator rejects unknown field '{name}'")

    return problems
```

The modes are then a three-line table — which direction to check, and whether to check against one version or all of them:

```python
_SPEC = {                       # (checks backward?, checks forward?, transitive?)
    "BACKWARD":   (True, False, False),   "BACKWARD_T": (True, False, True),
    "FORWARD":    (False, True, False),   "FORWARD_T":  (False, True, True),
    "FULL":       (True, True, False),    "FULL_T":     (True, True, True),
}

def check_mode(mode, candidate, history, strict=False):
    backward, forward, transitive = _SPEC[mode]
    targets = list(enumerate(history, 1)) if transitive else [(len(history), history[-1])]
    problems = []
    for version, old in targets:
        if backward:                      # new code reads old data
            problems += [f"v{version}: {p}" for p in can_read(candidate, old, strict)]
        if forward:                       # old code reads new data
            problems += [f"v{version}: {p}" for p in can_read(old, candidate, strict)]
    return problems
```

Type promotion follows Avro's resolution rules exactly, and note that the relation is **one-directional** — which is the entire reason widening and narrowing land in different modes:

```python
PROMOTIONS = {
    "int32":  {"int32", "int64", "float", "double"},
    "int64":  {"int64", "float", "double"},
    "float":  {"float", "double"},
    "double": {"double"},
    "string": {"string", "bytes"},
    "bytes":  {"bytes", "string"},
    "bool":   {"bool"},
}
```

One function in the file deliberately sits *outside* the compatibility system, because the change it detects is outside what any real checker can see:

```python
def semantic_drift(a: Schema, b: Schema) -> list[str]:
    """Fields whose NAME and TYPE are identical but whose MEANING changed.

    No structural checker sees this. Not Avro, not Protobuf, not JSON Schema.
    It is detected here only because this model records semantics explicitly -
    a luxury real wire formats do not give you.
    """
```

The subject under test is `orders.OrderPlaced` with three registered versions: v1 has seven fields including `gift_message` at tag 7 and `promo_code` at tag 8; v2 adds `currency` and retires `gift_message` **without reserving tag 7**; v3 retires `promo_code` and adds `channel`. That "without reserving" is the deliberate, extremely common mistake that the transitive modes are about to catch.

Run it:

```console
$ python schema_registry.py
== 1. THE REGISTRY: subjects, versions, and one id per schema ==
  registered v1  schema_id=1   fields=7  514 B of schema text
  registered v2  schema_id=2   fields=7  513 B of schema text
  registered v3  schema_id=3   fields=7  513 B of schema text
  compatibility mode enforced on every register(): FULL_T
  register(v4 = rename total_cents -> total_amount) REJECTED
    reason: v1: reader needs 'total_amount', the writer never emits it, and it has no default
  the rename never reaches the log. That is the entire point of the gate.

== 2. COMPATIBILITY MATRIX: 13 proposed changes x 6 modes ==
  subject 'orders.OrderPlaced'   history v1..v3   ACC = accept, REJ = reject
  _T = transitive: checked against EVERY registered version, not just the latest
    #  proposed change                       BACKWARD BACKWARD_T    FORWARD  FORWARD_T       FULL     FULL_T
    1  add optional field, with default           ACC        ACC        ACC        ACC        ACC        ACC
       -> compatible with every registered version
    2  add required field, no default             REJ        REJ        ACC        ACC        REJ        REJ
       -> v3: reader needs 'warehouse_code', the writer never emits it, and it has no default
    3  remove optional field (has default)        ACC        ACC        ACC        ACC        ACC        ACC
       -> compatible with every registered version
    4  remove required field                      ACC        ACC        REJ        REJ        REJ        REJ
       -> v3: reader needs 'customer_id', the writer never emits it, and it has no default
    5  rename required field (drop + add)         REJ        REJ        REJ        REJ        REJ        REJ
       -> v3: reader needs 'total_amount', the writer never emits it, and it has no default
    6  widen int32 -> int64 (item_count)          ACC        ACC        REJ        REJ        REJ        REJ
       -> v3: 'item_count' is int64 on the wire, int32 in the reader: no legal promotion
    7  narrow int64 -> int32 (total_cents)        REJ        REJ        ACC        ACC        REJ        REJ
       -> v3: 'total_cents' is int64 on the wire, int32 in the reader: no legal promotion
    8  change UNITS, same name and type           ACC        ACC        ACC        ACC        ACC        ACC
       -> UNDETECTABLE: 'total_cents': 'integer minor units (cents)' -> 'decimal major units (euros)'
          no mode rejects it; no structural checker ever could
    9  add enum symbol 'refunded'                 ACC        ACC        REJ        REJ        REJ        REJ
       -> v3: 'status' may carry enum symbol 'refunded', unknown to the reader
   10  reorder field declarations                 ACC        ACC        ACC        ACC        ACC        ACC
       -> compatible with every registered version
   11  reuse retired tag 7 for a new field        ACC        REJ        ACC        REJ        ACC        REJ
       -> v1: tag 7 carries 'gift_message' on the wire but means 'warehouse_id' to the reader
   12  re-add retired NAME with a new type        ACC        REJ        ACC        REJ        ACC        REJ
       -> v1: 'promo_code' is string on the wire, int64 in the reader: no legal promotion
   13  change cardinality: string -> array        REJ        REJ        REJ        REJ        REJ        REJ
       -> v3: 'currency' is string on the wire, array<string> in the reader: no legal promotion
  swap the tolerant reader for a strict one and 6 of those 17 BACKWARD/FORWARD accepts become rejects
  row 11 under non-transitive BACKWARD is ACC -- unless v2 said 'reserved 7':
    tag 7 was reserved by v2 and may never return

== 3. SILENT CORRUPTION: the rename that raised nothing ==
  producer wrote 5,000 OrderPlaced events under v1 (field 'total_cents')
  ground truth            sum(total_cents)  =  125,703,430 cents  EUR 1,257,034.30
  v3 analytics consumer   sum(total_amount) =            0 cents  EUR 0.00
  exceptions raised 0   log lines written 0   alerts fired 0   records skipped 0
  same data, strict validator: HALTED at record 1 of 5,000 - "missing required field 'total_amount'"
  the loud failure costs one page. The quiet one costs EUR 1,257,034.30 of wrong numbers.

== 4. UPCASTERS: replaying 90 days across three schema generations ==
  log: 9,000 events over 90 days   producer deployed v2 on day 25, v3 on day 53
    v1:  2,400 events (26.7%)   days  1-24
    v2:  2,800 events (31.1%)   days 25-52
    v3:  3,800 events (42.2%)   days 53-90
  v4 consumer, NO upcasters:  processed 0 of 9,000 (0.0%)   failed 9,000   <- the replay is impossible
  v4 consumer, WITH upcasters: processed 9,000 of 9,000 (100.0%)   failed 0
    upcast hops applied: v1->v4 x2,400 (3 hops each), v2->v4 x2,800 (2), v3->v4 x3,800 (1)
    aggregate sum(total_amount) = 226,329,088 cents  EUR 2,263,290.88
    expected                    = 226,329,088 cents  EUR 2,263,290.88   match: True

== 5. THE ENVELOPE: a 5-byte schema id vs the whole schema ==
  corpus 9,000 events   payload alone  1,199,535 B   (133 B/event)
  schema embedded in every message   5,989,935 B   (666 B/event)   overhead 399%
  magic byte + 4-byte schema id      1,244,535 B   (138 B/event)   overhead 3.8%
  saved 4,745,400 B on this corpus: the wire is 4.8x smaller
  ...and the writer's schema is still recoverable for every record: by_id[1] -> v1, by_id[3] -> v3
  at 5,000 events/s that difference is 212 GB/day of pure schema text

== 6. THE ENUM HAZARD: exhaustive matching meets a new symbol ==
  producer added one enum symbol; 329 of 4,000 events (8.2%) now carry it
  exhaustive consumer: HALTED at offset 3 - unhandled status 'refunded'
    processed 3 of 4,000 (0.1%), partition blocked, 3,997 events stuck behind it
  tolerant consumer:   processed 4,000 of 4,000 (100.0%), 0 halts
    await_payment           1,192
    ignore_unknown_status     329
    notify_customer         1,232
    pick_and_pack           1,247
  adding an enum value is BACKWARD compatible and FORWARD INCOMPATIBLE.
  row 9 of the table said so. This is what the table was measuring.

== 7. SUMMARY: FULL_TRANSITIVE verdict, and the safe path anyway ==
  change                               FULL_T  deploy order safe migration path
  add optional field, with default        ACC  either     ship it - the only free change on this list
  add required field, no default          REJ  prod-first give it a default; require it in a later version
  remove optional field (has default)     ACC  either     deprecate: announce, watch usage, then drop
  remove required field                   REJ  cons-first add a default in v+1, remove the field in v+2
  rename required field (drop + add)      REJ  NEITHER    dual-write both names, migrate, upcast forever
  widen int32 -> int64 (item_count)       REJ  cons-first consumers first: upgrade every reader, then widen
  narrow int64 -> int32 (total_cents)     REJ  prod-first do not narrow - add a new field instead
  change UNITS, same name and type        ACC  either     NEVER redefine. add total_eur, keep total_cents
  add enum symbol 'refunded'              REJ  cons-first ship tolerant readers first, then emit the symbol
  reorder field declarations              ACC  either     ship it - tag and name are identity, order is not
  reuse retired tag 7 for a new field     REJ  NEITHER    never reuse a tag. reserve 7, take the next one
  re-add retired NAME with a new type     REJ  NEITHER    pick a new name: promo_code_id, not promo_code
  change cardinality: string -> array     REJ  NEITHER    add currencies[]; upcast old value to a 1-item list
  default for a retained, replayable log: FULL_TRANSITIVE. Anything weaker is a promise you cannot keep.
```

**The matrix is the lesson.** Read it as a set of symmetries, because the symmetries are how you remember it without memorising it.

**Adding and removing are mirror images.** Row 2 (add a required field) is `REJ` under backward and `ACC` under forward. Row 4 (remove a required field) is exactly reversed. Adding a field breaks the *new* reader looking at *old* data; removing one breaks the *old* reader looking at *new* data. Same for **row 6 and row 7**: widening is backward-only, narrowing is forward-only, because Avro's promotion relation runs in one direction. Whenever you cannot remember which is which, reconstruct it from "the direction names the data".

**Row 5 takes both failures**, because a rename is a delete plus an add and each half breaks a different direction. There is no mode under which a rename is acceptable. That is the machine telling you, in advance, exactly what The Problem's failure two cost.

**Rows 11 and 12 are the transitive argument, measured.** Both are `ACC` under `BACKWARD`, `FORWARD` and `FULL`, and `REJ` under all three transitive variants. Row 11 reuses tag 7, which v2 retired; v3 has no tag 7, so a check against v3 alone finds nothing wrong, while a check against v1 finds that the wire tag `7` carries `gift_message` bytes that the new reader will interpret as `warehouse_id`. Row 12 is the same shape with names instead of tags: `promo_code` was a `string` in v1 and v2, and re-adding it as `int64` collides with every record older than v3. **Three of six modes certify these as safe.** That is what a non-transitive check buys you.

Then the counter-measure, on the line beneath: with `reserved 7` declared in v2, the plain `BACKWARD` registry rejects the reuse outright — `tag 7 was reserved by v2 and may never return`. Reserving retired tags is what makes a cheap, non-transitive check sufficient for the tag-reuse class of bug. It costs one line in a `.proto` file.

**Row 8 is the row that cannot be enforced.** Changing `total_cents` from integer cents to decimal euros — same name, same type, same tag — is `ACCEPT` in all six modes, because there is nothing structural to reject. The only reason the program prints anything at all is that this model records a `semantics` string, which no real wire format gives you. Every number downstream is now wrong by a factor of 100 and every automated control you own is green. **The most dangerous change in the table is the one the table cannot reject.**

**Strict readers dismantle the policy.** Six of the seventeen backward/forward accepts flip to reject when the reader refuses unknown fields — including row 1, the change everyone agrees is safe. Failure one, reproduced from first principles: it was never the `currency` field that broke those consumers, it was `additionalProperties: false`.

**Section 3 is the argument for enforcement, in money.** The same 5,000 records, the same missing field, two readers. The tolerant-but-naive one returns `EUR 0.00` against a ground truth of `EUR 1,257,034.30` while raising zero exceptions, writing zero log lines and firing zero alerts — there is no signal anywhere for a monitoring system to catch. The strict one halts at record 1 of 5,000 with a precise message naming the missing field. The strict reader is *wrong* as an inbound policy and *right* as a self-check, and the distinction is what to be strict about: assert on the fields you consume, tolerate the rest.

**Section 4 is failure three, solved.** The 90-day log holds three schema generations in realistic proportions — 2,400 v1 records from days 1–24, 2,800 v2 records from days 25–52, 3,800 v3 records from days 53–90. A consumer that understands only v4 processes **0 of 9,000** on its own. With three tiny upcasters registered, the same consumer, unchanged, processes **9,000 of 9,000** and the aggregate `226,329,088` cents matches the expected value exactly. Note what the consumer never learns: it has no version branch, no `if version == 1`, no legacy field names. Three functions of four lines each made ninety days of history readable by code that only knows today's shape.

**Section 5 prices the envelope.** 133 bytes of payload carrying 513 bytes of schema is not a rounding error, it is 399% overhead — the contract costing four times the data. The id-based envelope adds 5 bytes for 3.8%, and the schema is *still* recoverable for every record. The 212 GB/day figure at 5,000 events/second is the version of this argument that gets budget approval.

**Section 6 shows why "just add an enum value" is not a small change.** With 8.2% of messages carrying the new `refunded` symbol, the exhaustive consumer halts at **offset 3** — the fourth message it ever sees — having processed 0.1% of the stream, with 3,997 events stuck behind it. That last number is the real damage: this is not one poison-pill record going to the dead-letter queue, it is a blocked partition, because the consumer will crash-loop on the same offset forever. The tolerant consumer processes 100% and routes 329 unknown-status events to a review bucket where a human can see them. One extra `else` branch is the difference between an incident and a metric.

## Use It

You will not write a registry; you will configure one. Every fragment below maps to something you just built.

**Confluent Schema Registry** is the reference implementation of section 1. Schemas live under a **subject** (by default `<topic>-value`), and compatibility is a per-subject setting:

```bash
# the six modes you implemented, by their real names
curl -X PUT http://registry:8081/config/orders.placed-value \
  -H 'Content-Type: application/vnd.schemaregistry.v1+json' \
  -d '{"compatibility": "FULL_TRANSITIVE"}'

# the CI gate: dry-run a candidate against the registered history. Non-zero exit fails the build.
curl -X POST http://registry:8081/compatibility/subjects/orders.placed-value/versions/latest \
  -d @order-placed.avsc
```

`BACKWARD`, `FORWARD`, `FULL` and their `_TRANSITIVE` forms are exactly the six columns of the matrix, with `BACKWARD` as the product default — worth knowing, because the default is *not* the right choice for a long-retention topic. And the wire format is the envelope from section 5, byte for byte:

```text
byte 0        magic byte, always 0x00
bytes 1-4     schema id, 4-byte big-endian   <- fetch the WRITER's schema from the registry
bytes 5..n    the payload
```

**Apache Avro** is the format built for this problem. Schema resolution is a first-class part of its specification, and the `.avsc` schema declares the defaults that resolution depends on:

```json
{"type": "record", "name": "OrderPlaced", "namespace": "com.shop.orders",
 "fields": [
   {"name": "order_id",    "type": "string"},
   {"name": "total_cents", "type": "long", "doc": "integer minor units, EUR. NEVER redefine."},
   {"name": "currency",    "type": "string", "default": "EUR"},
   {"name": "status",      "type": {"type": "enum", "name": "OrderStatus",
                                    "symbols": ["placed", "paid", "shipped"],
                                    "default": "placed"}}
 ]}
```

The `"default"` on `currency` is what makes a new reader able to read pre-multi-currency records; the `"default"` on the enum is the tolerant-reader escape hatch that turns an unknown future symbol into a known value instead of an exception. **Both are the fix for a row in the matrix**, written declaratively.

**Protocol Buffers** makes the field number the identity, which is why its rules are about numbers rather than names:

```text
message OrderPlaced {
  reserved 7, 8;                        // gift_message, promo_code -- never reuse these
  reserved "gift_message", "promo_code";
  string order_id     = 1;
  int64  total_cents  = 3;              // minor units. Widening int32->int64 is safe; do not narrow.
  optional string channel = 9;          // proto3 'optional' = explicit presence, so "" != unset
}
```

`reserved` is the counter-measure from row 11, and it costs one line. Note also that proto3 **preserves unknown fields on round-trip** — a field the reader does not know is retained in the message and re-emitted on serialisation, which makes a Protobuf reader tolerant by construction and stops a middleware hop from silently stripping data it did not understand.

**JSON Schema** is where the strict-reader failure originates:

```json
{"$schema": "https://json-schema.org/draft/2020-12/schema",
 "type": "object",
 "required": ["order_id", "total_cents"],
 "additionalProperties": true,
 "properties": {"order_id": {"type": "string"}, "total_cents": {"type": "integer"}}}
```

`"additionalProperties": true` — the default, and keep it that way for inbound events. Setting it to `false` is the single line that produced failure one. Be strict via `required` on the fields you actually consume; be open about the rest.

**CloudEvents** gives you the envelope-level hook that ties back to [Anatomy of a Message](../02-anatomy-of-a-message/): `datacontenttype` names the serialisation, and **`dataschema` is a URI identifying the schema of `data`** — the standardised place to put your registry pointer:

```json
{"specversion": "1.0", "type": "com.shop.order.placed", "source": "/orders",
 "id": "9f2b...", "datacontenttype": "application/avro",
 "dataschema": "https://registry:8081/schemas/ids/3",
 "data": {"order_id": "o_00123", "total_cents": 4999, "currency": "EUR"}}
```

**And the control that makes any of it real: fail the build.** For Protobuf, `buf breaking --against '.git#branch=main'` classifies a diff against a chosen rule set (`WIRE`, `WIRE_JSON`, `FILE`) and exits non-zero. For Avro or JSON Schema, the registry's `/compatibility` endpoint does the same job. Wire it into the pull request as a required status check, on the producer's repository, before merge. A compatibility policy that is documented but not enforced is a policy that holds until the first busy sprint.

## Think about it

1. Your `OrderPlaced` topic has 7-day retention and your `AccountOpened` topic is event-sourced with infinite retention. Argue for a *different* compatibility mode on each, and say precisely which capability you are giving up on the first one.
2. A teammate proposes changing `duration` from seconds to milliseconds "because everything else is in milliseconds, and the field name doesn't say seconds anyway". Every automated check passes. Describe what you will see in production, when, and how you would find the cause — then give the change you would make instead.
3. Row 11 of the matrix is accepted by `BACKWARD`, `FORWARD` and `FULL`, and rejected by all three transitive modes. Explain the mechanism in terms of bytes on the wire, and then explain why `reserved 7;` in v2 would have made even the cheap non-transitive check sufficient.
4. You need to add a required `currency` field, and you have eleven consumers across five teams. Write the expand-contract sequence with the compatibility mode active at each step — and identify the step you can never actually complete, and what that obliges you to maintain forever.
5. A consumer team says: "we validate strictly because it catches producer bugs early." They are not wrong. Design a validation policy that gets that benefit without turning every additive producer change into an outage, and say which specific messages should end up in the dead-letter queue.
6. Your registry has `FULL_TRANSITIVE` on and it just rejected a change the business genuinely needs. List the three legitimate ways forward, and say what each one costs — in engineering time, in storage, and in permanent maintenance burden.

## Key takeaways

- **An event schema is a public API with an unbounded lifetime and an unknown consumer set.** You cannot enumerate subscribers (that is what pub/sub bought you) and you cannot rewrite history, so **compatibility rules replace coordination**. This is strictly harder than REST versioning, where a breaking change stops hurting once every client upgrades.
- **The direction names the data, not the code.** **Backward** = new code reads old data → deploy consumers first, and it is what replay requires. **Forward** = old code reads new data → deploy producers first. **Full** = both. Reconstruct every row of the matrix from that one sentence.
- **Transitive is the mode that matters on a retained log.** A non-transitive check compares against the previous version only, and compatibility does not compose. Two measured changes — reusing retired tag 7, and re-adding `promo_code` with a new type — are ACCEPTED by `BACKWARD`, `FORWARD` and `FULL`, and REJECTED by all three transitive variants. **Default to `FULL_TRANSITIVE` for events on a retained, replayable log.**
- **Adding and removing are mirror images, and so are widening and narrowing.** Adding a required field breaks backward (`REJ`/`ACC` in the run); removing one breaks forward (`ACC`/`REJ`). Widening `int32→int64` is backward-only; narrowing is forward-only, because Avro's type promotion runs in exactly one direction. **A rename is a delete plus an add and therefore breaks both** — no mode accepts it.
- **The most dangerous change is the one no checker can see.** Redefining a field's units or meaning while keeping its name and type is `ACCEPT` in all six modes, because structurally nothing changed. The fix is a rule, not a tool: **never redefine an existing field — add a new one.**
- **Defaults are the entire mechanism.** Absent-plus-default is what lets a reader survive missing data, which is why Avro *requires* defaults for evolution and Protobuf gives every field an implicit zero. The trap: a zero default is indistinguishable from a legitimate zero — proto3's `optional` presence exists for exactly this, and the un-flagged version is how 5,000 orders worth **EUR 1,257,034.30** summed to **EUR 0.00** with zero exceptions raised.
- **Be tolerant about the message, strict about your slice.** Ignore unknown fields, never fail on extra data, always have a default arm on an enum match. A `additionalProperties: false` validator flipped **6 of 17** accepted verdicts to rejects in the measured run and is the direct cause of the Tuesday outage; the enum consumer without a default arm halted at **offset 3 of 4,000** and blocked 3,997 events behind it.
- **Registries put a schema id — not a schema — in the envelope.** 5 bytes for **3.8%** overhead instead of an embedded schema at **399%** (a 4.8× smaller wire, 212 GB/day at 5,000 events/s), and, far more importantly, the **writer's schema stays retrievable forever**, which is what makes old data readable. Deserialisation is writer's-schema-plus-reader's-schema resolution; the compatibility check belongs in CI, before registration.
- **Upcasters are what make replay across schema generations possible — and they are permanent.** A chain of small, pure `vN→vN+1` functions lifts every record to the newest shape at read time, so consumer code only ever knows one version: **9,000 of 9,000 records across three generations, aggregate matching exactly**, versus **0 of 9,000** without them. Expand-contract never truly completes on a retained log, so budget for the upcasters as production code, not migration scaffolding.

Next: [Capstone: An Event-Driven Order Pipeline, End to End](../13-capstone-event-driven-order-pipeline/) — every primitive in this phase, wired into one system: the envelope, the queue, the topic, the log, idempotent consumers, partition keys, dead-letter paths, the outbox, and the versioned contracts you just learned to keep.
