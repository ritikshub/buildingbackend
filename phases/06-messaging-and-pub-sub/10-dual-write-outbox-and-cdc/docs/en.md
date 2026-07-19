# The Dual-Write Problem: Transactional Outbox & CDC

> Four lines of code appear in almost every service you will ever read: insert the row, commit, publish the event. They are broken. Not subtly, not rarely — broken in a way that silently loses customer orders and is discovered weeks later by a support ticket. This lesson reproduces the bug with a real database and a real crash, then fixes it with the two patterns that actually work: a transactional outbox, and Change Data Capture — which turns out to be the realisation that your database has been writing exactly the event log you need since the day you installed it.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Backpressure, Consumer Lag & Flow Control](../09-backpressure-lag-and-flow-control/)
**Time:** ~85 minutes

## The Problem

Here is the code. You have written it, reviewed it, and approved it.

```python
def place_order(order):
    db.execute("INSERT INTO orders (id, customer, amount) VALUES (?, ?, ?)", order)
    db.commit()
    broker.publish("OrderPlaced", order)     # tell the rest of the company
```

It reads like one operation. It is two, against two different systems, with **no transaction spanning them**. The database knows nothing about the broker. The broker knows nothing about the database. Nothing anywhere guarantees that both happen or neither does — and the process running those three lines can stop existing between any two of them.

Enumerate what that costs.

**Interleaving one: the crash between commit and publish.** The `COMMIT` returns. The row is durable. Then the pod is `SIGKILL`ed — an out-of-memory kill, a node drain, a deploy rollout, a spot instance reclaimed — and `broker.publish` never runs. The order exists and **no event is ever emitted**. No confirmation email. No warehouse notification. No analytics row. No entry in the fraud queue.

Sit with how bad that is, because it is worse than an error. Nothing failed. No exception, no 500, no alert, nothing in the dead-letter queue ([Lesson 8](../08-retries-backoff-and-dead-letter-queues/)), and no retry will ever happen because nothing knows there is anything to retry. The customer sees "Order placed!" and then silence. The order sits in a permanent limbo that is **invisible to monitoring**, and you learn about it in three weeks when a human asks where their parcel is.

**Interleaving two: publish first, then the rollback.** Someone notices interleaving one and "fixes" it by publishing before the commit. The event goes out, then the transaction rolls back — a constraint violation, a deadlock, a lock timeout, or the same crash one instruction earlier. You have now published `OrderPlaced` for an order that **does not exist and never will**. Downstream services act on a phantom: an email for a nonexistent purchase, stock reserved and never released, and a foreign key lookup failing somewhere unrelated, in a service whose on-call engineer has never heard of an outbox. This is strictly worse, because the bad data has left your service and become other people's incident.

**Interleaving three: the lost ack.** The publish succeeds, the broker's acknowledgement is lost on the way back, the client retries, and the event is delivered twice. That is [Lesson 6](../06-delivery-semantics-and-idempotency/)'s territory and the one people already know about — named here only so you can see that the dual-write problem is a *different and larger* failure than duplicates.

Now the three escape hatches you are already reaching for.

**"Wrap it in try/except."** A `try` block catches *exceptions*. It does not catch the process ceasing to exist: `SIGKILL` runs no `except` block, no `finally`, no atexit handler, and neither does a kernel panic, a power loss, or a hypervisor evicting your VM. Even in the polite case where you *do* get an exception, the compensating code in your handler is two more instructions that can themselves be interrupted — you moved the window, you did not remove it. **There is no arrangement of two writes to two systems that makes them atomic, because atomicity cannot be built out of ordering.**

**"Publish first and delete the event if the commit fails."** Brokers have no un-publish, and a consumer may already have processed it.

**"It's a tiny window — milliseconds."** This is the argument that ends every review, so price it. Little's Law from [Lesson 1](../01-why-async-and-the-cost-of-coupling/), `L = λW`, holds for any stable system:

```text
order rate               lambda = 1,000 orders/second
danger window            W      = 0.05 s  (commit returns -> publish acked)
orders inside the window L      = lambda x W = 1,000 x 0.05 = 50 orders

every process death loses ~50 orders, permanently and silently.

pods restart for deploys, autoscaling, OOM kills, node drains, spot reclamation.
20 restarts/day  x  50 orders  =  1,000 lost events/day  =  365,000/year
```

**Fifty orders per restart.** Not "one in a million" — fifty, every single time, and a busy Kubernetes cluster reschedules pods dozens of times a day without anyone noticing, because rescheduling is supposed to be safe. That is the point: your infrastructure is behaving correctly and your data is being destroyed anyway. Even a modest service — 100 orders/second, a 10 ms window — has one order sitting in the danger zone at all times.

The program in this lesson does it with a real SQLite database and a real injected crash: 400 orders, killed on 45 of them, **45 orphaned orders and zero errors**.

## The Concept

### The dual-write problem, named and generalised

**The dual-write problem**: whenever a single logical operation must update **two systems that do not share a transaction**, atomicity is lost, and there exists a failure point that leaves the two permanently inconsistent.

Database plus broker is the version this phase cares about, but recognising the general shape is what makes the pattern portable, because you have already written all of these:

| The two writes | The inconsistency you get |
|---|---|
| Database + message broker | An order with no event, or an event with no order |
| Database + cache | A cache entry that is wrong until its TTL (time to live) expires — or forever |
| Database + search index | A product that is deleted but still appears in search results |
| Database + object storage | A row pointing at a file that was never uploaded, or an orphaned file nobody references |
| Two databases (microservice-to-microservice) | The classic distributed-transaction problem |

Every one of these is the same bug and every one of them takes the same fix. If you learn it once here, you will spot it in code review for the rest of your career — and the tell is always the same: **two `await`s, two clients, one function, no shared transaction.**

### Why two-phase commit is usually not the answer

There is a textbook solution and it deserves an honest hearing rather than a dismissal.

**Two-phase commit (2PC)** puts a **transaction coordinator** in charge of both systems. Phase one, *prepare*: the coordinator asks every participant "can you commit?" and each participant does all the work, makes it durable, takes the locks, and answers `yes` — promising it can commit later no matter what happens. Phase two, *commit*: if every participant voted yes, the coordinator tells them all to commit; if any voted no, it tells them all to abort. The standardised interface for this is **XA** (from the X/Open *Distributed Transaction Processing: The XA Specification*, 1991), and the theory is in Gray and Reuter's *Transaction Processing: Concepts and Techniques* (1993), which remains the reference for this material.

2PC genuinely solves the atomicity problem. It is also, in practice, almost never what you want between an application database and a message broker. Five reasons:

**The coordinator is a single point of failure, and its failure blocks.** If the coordinator dies after participants have voted `yes` but before it announces the outcome, those participants are **in doubt**: they cannot commit (the decision might have been abort) and cannot abort (it might have been commit). They must wait. This is not an implementation defect that a better engineer could fix — Skeen and Stonebraker's "A Formal Model of Crash Recovery in a Distributed System" (*IEEE Transactions on Software Engineering*, 1983) established that a blocking window is inherent to the protocol. Three-phase commit removes it only by assuming a synchronous network with bounded message delay and no partitions, which is not a network you have.

**Participants hold locks through the entire prepare phase.** Rows stay locked from `prepare` until the coordinator's verdict arrives — a round trip away, unbounded if the coordinator is unreachable. Under load that is a lock convoy across your hottest tables.

**It couples the availability of the database and the broker.** This is the one that should decide it for you. A transaction spanning both can only commit if **both** are healthy, so your write path's availability becomes the *product* of theirs — exactly the arithmetic from [Lesson 1](../01-why-async-and-the-cost-of-coupling/) that async messaging existed to escape. You adopted a broker so one component's failure would stop taking down another, then wired them back together with a distributed lock.

**Most modern brokers do not support it, and throughput is poor anyway.** Kafka has no XA resource manager; SQS and most cloud-native brokers have none; RabbitMQ and some JMS brokers range from partial to actively discouraged. And two coordinated round trips with forced log flushes at each participant, plus a coordinator log that must itself be durable and replicated, make order-of-magnitude slowdowns normal.

The upshot: 2PC is a reasonable tool between two databases you control inside one datacentre with a mature transaction manager. It is the wrong tool between your service's database and a message broker. What follows is the right one, and it is much simpler.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 452" width="100%" style="max-width:840px" role="img" aria-label="Two timelines of the dual-write bug. In commit-then-publish the process is killed after the durable commit and before the publish, leaving 45 orphaned orders out of 400 with no event and no error. In publish-then-commit the same 45 kills land after the publish and before the commit, so the transaction rolls back and 45 phantom events describe orders that do not exist.">
  <defs>
    <marker id="l10-arrow" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The same 45 injected kills, two orderings, two opposite corruptions</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="182" rx="13" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
    <rect x="16" y="238" width="848" height="182" rx="13" fill="#7c5cff" fill-opacity="0.07" stroke="#7c5cff"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="112" width="126" height="50" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="200" y="112" width="126" height="50" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="360" y="112" width="126" height="50" rx="9" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="520" y="112" width="126" height="50" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35" stroke-dasharray="5 4"/>
    <rect x="680" y="104" width="164" height="66" rx="10" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M166 137 L 194 137" marker-end="url(#l10-arrow)"/>
    <path d="M326 137 L 354 137" marker-end="url(#l10-arrow)"/>
    <path d="M486 137 L 514 137" stroke-opacity="0.35" stroke-dasharray="5 4" marker-end="url(#l10-arrow)"/>
    <path d="M646 137 L 674 137" stroke-opacity="0.35" stroke-dasharray="5 4" marker-end="url(#l10-arrow)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="40" y="308" width="126" height="50" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="200" y="308" width="126" height="50" rx="9" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    <rect x="360" y="308" width="126" height="50" rx="9" fill="#7c5cff" fill-opacity="0.22" stroke="#7c5cff"/>
    <rect x="520" y="308" width="126" height="50" rx="9" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.35" stroke-dasharray="5 4"/>
    <rect x="680" y="300" width="164" height="66" rx="10" fill="#7c5cff" fill-opacity="0.16" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M166 333 L 194 333" marker-end="url(#l10-arrow)"/>
    <path d="M326 333 L 354 333" marker-end="url(#l10-arrow)"/>
    <path d="M486 333 L 514 333" stroke-opacity="0.35" stroke-dasharray="5 4" marker-end="url(#l10-arrow)"/>
    <path d="M646 333 L 674 333" stroke-opacity="0.35" stroke-dasharray="5 4" marker-end="url(#l10-arrow)"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="36" y="70" font-size="12.5" font-weight="700" fill="#e0930f">COMMIT THEN PUBLISH  —  the orphan</text>
    <text x="36" y="90" font-size="9.5" opacity="0.85">the order is real and the world is never told</text>
    <text x="103" y="133" font-size="10" font-weight="700" text-anchor="middle">BEGIN</text>
    <text x="103" y="149" font-size="9" text-anchor="middle" opacity="0.85">INSERT order</text>
    <text x="263" y="133" font-size="10" font-weight="700" text-anchor="middle">COMMIT</text>
    <text x="263" y="149" font-size="9" text-anchor="middle" opacity="0.85">durable on disk</text>
    <text x="423" y="133" font-size="10" font-weight="700" text-anchor="middle" fill="#e0930f">SIGKILL</text>
    <text x="423" y="149" font-size="9" text-anchor="middle" opacity="0.85">no except block runs</text>
    <text x="583" y="133" font-size="10" font-weight="700" text-anchor="middle" opacity="0.45">publish()</text>
    <text x="583" y="149" font-size="9" text-anchor="middle" opacity="0.4">never runs</text>
    <text x="762" y="127" font-size="10.5" font-weight="700" text-anchor="middle" fill="#e0930f">ORPHANED ORDER</text>
    <text x="762" y="145" font-size="9" text-anchor="middle" opacity="0.9">row exists, no event</text>
    <text x="762" y="160" font-size="9" text-anchor="middle" opacity="0.9">nothing errored</text>
    <text x="36" y="198" font-size="10.5" font-weight="700">MEASURED — 400 orders, 45 kills:  orders in DB 400  ·  events published 355  ·  ORPHANS 45  ·  phantoms 0</text>
    <text x="36" y="215" font-size="9.5" opacity="0.8">no exception, no 500, no dead-letter entry, no retry — the loss is invisible to every alert you own</text>

    <text x="36" y="266" font-size="12.5" font-weight="700" fill="#7c5cff">PUBLISH THEN COMMIT  —  the phantom</text>
    <text x="36" y="286" font-size="9.5" opacity="0.85">the world is told about an order that never existed</text>
    <text x="103" y="329" font-size="10" font-weight="700" text-anchor="middle">BEGIN</text>
    <text x="103" y="345" font-size="9" text-anchor="middle" opacity="0.85">INSERT order</text>
    <text x="263" y="329" font-size="10" font-weight="700" text-anchor="middle">publish()</text>
    <text x="263" y="345" font-size="9" text-anchor="middle" opacity="0.85">event is gone, sent</text>
    <text x="423" y="329" font-size="10" font-weight="700" text-anchor="middle" fill="#7c5cff">SIGKILL</text>
    <text x="423" y="345" font-size="9" text-anchor="middle" opacity="0.85">restart rolls back</text>
    <text x="583" y="329" font-size="10" font-weight="700" text-anchor="middle" opacity="0.45">COMMIT</text>
    <text x="583" y="345" font-size="9" text-anchor="middle" opacity="0.4">never runs</text>
    <text x="762" y="323" font-size="10.5" font-weight="700" text-anchor="middle" fill="#7c5cff">PHANTOM EVENT</text>
    <text x="762" y="341" font-size="9" text-anchor="middle" opacity="0.9">event exists, no row</text>
    <text x="762" y="356" font-size="9" text-anchor="middle" opacity="0.9">and no un-publish</text>
    <text x="36" y="394" font-size="10.5" font-weight="700">MEASURED — same 45 kills:  orders in DB 355  ·  events published 400  ·  orphans 0  ·  PHANTOMS 45</text>
    <text x="36" y="411" font-size="9.5" opacity="0.8">strictly worse: the bad data has already left your service and is now other teams' incident</text>

    <text x="440" y="440" font-size="10.5" text-anchor="middle" opacity="0.95">Reordering the two writes only chooses which way the inconsistency points. There is no third ordering.</text>
  </g>
</svg>
```

### The transactional outbox: make it one write instead of two

The fix is not a cleverer protocol. It is a refusal to have two writes at all.

**The transactional outbox pattern**: insert the event you intend to publish as a **row in your own database**, in the **same transaction** as the business change. A separate process — the **relay**, sometimes called the message relay or publisher — reads unpublished rows from that table and publishes them to the broker, marking each row published afterwards.

```sql
BEGIN;
  INSERT INTO orders (id, customer, amount_cents, status)
       VALUES (1013, 'cust-07', 4299, 'placed');

  INSERT INTO outbox (aggregate_id, partition_key, seq, event_id, event_type, payload, created_at)
       VALUES (1013, 'cust-07', 4, 'e-1013', 'OrderPlaced', '{"order_id":1013, ...}', 1699999999.5);
COMMIT;                     -- ONE write. Both rows land, or neither does.
```

Read that again, because the whole lesson is in it. There is now **exactly one write to exactly one system**. The atomicity problem has been handed to the database, and the database solved atomicity decades ago — it is the A in ACID, built on the write-ahead log you implemented yourself in [Phase 3, Lesson 13](../../03-relational-databases/13-write-ahead-logging/). Crash anywhere and you get one of two states: both rows present, or neither. There is no interleaving that produces an order without its event, because *there is no second write to fail*.

Notice what else you got for free: the *intent to publish* is now durable, transactional, and queryable. You can `SELECT` the events that have not gone out yet. You can count them. You can alert on them. In the naive version the intent to publish lived only in the CPU registers of a process that no longer exists.

#### Be precise about the guarantee: this is at-least-once, never at-most-once

The outbox does not give you exactly-once, and any explanation that implies it is lying to you. Look at the relay:

```python
rows = SELECT ... FROM outbox WHERE published_at IS NULL ORDER BY id LIMIT 8
for row in rows:
    broker.publish(row.payload)          # <-- succeeds
                                         # <-- the relay is killed HERE
UPDATE outbox SET published_at = now WHERE id IN (...)
```

The relay has the **exact same dual-write problem** it was invented to solve: a publish to the broker and an update to the database, with a window between them. The difference — and it is the entire difference — is that the two failure modes are no longer symmetric. Publish-then-mark can only fail in one direction: **the event was sent and not recorded as sent, so it is sent again.** It can never fail in the direction that loses an event. The unmarked row is still sitting there, and the relay will pick it up again on the next poll.

The pattern has converted an **unrecoverable loss** into a **recoverable duplicate**. That trade is the reason it works, and it has a hard consequence:

> **The transactional outbox produces at-least-once delivery by construction. Idempotent consumers ([Lesson 6](../06-delivery-semantics-and-idempotency/)) are a prerequisite, not an enhancement.** If your consumer cannot process the same event twice safely, the outbox will duplicate charges and emails rather than lose orders — and you have chosen a different bug, not fewer bugs.

The measured run below produces 13 duplicates out of 413 deliveries from 6 relay crashes. The idempotent consumer reduces them to 400 correct effects.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 468" width="100%" style="max-width:840px" role="img" aria-label="The transactional outbox end to end. The application writes the order row and the outbox row in one database transaction, so both land or neither does. A relay selects unpublished rows, publishes them, then marks them published; a crash between publishing and marking causes redelivery, which is why the pattern is at-least-once. An idempotent consumer with an inbox table absorbs the duplicates, turning 413 deliveries into 400 correct effects.">
  <defs>
    <marker id="l10-arrow2" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One write instead of two — and where the duplicates come from</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="70" width="196" height="188" rx="12" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-dasharray="7 5"/>
    <rect x="42" y="118" width="160" height="44" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="42" y="174" width="160" height="44" rx="8" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="256" y="70" width="216" height="188" rx="12" fill="#7f7f7f" fill-opacity="0.08" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="272" y="112" width="184" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="272" y="150" width="184" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="272" y="212" width="184" height="30" rx="7" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="272" y="184" width="184" height="24" rx="6" fill="#e0930f" fill-opacity="0.22" stroke="#e0930f"/>
    <rect x="508" y="118" width="118" height="100" rx="11" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
    <rect x="662" y="70" width="194" height="188" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="680" y="140" width="158" height="72" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M220 164 L 250 164" marker-end="url(#l10-arrow2)"/>
    <path d="M472 164 L 502 164" marker-end="url(#l10-arrow2)"/>
    <path d="M626 164 L 656 164" marker-end="url(#l10-arrow2)"/>
    <path d="M464 226 L 486 226 L 486 100 L 350 100 L 350 106" marker-end="url(#l10-arrow2)" stroke-dasharray="5 4" stroke-opacity="0.75"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="290" width="832" height="80" rx="12" fill="#e0930f" fill-opacity="0.07" stroke="#e0930f"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="122" y="94" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">ONE TRANSACTION</text>
    <text x="122" y="110" font-size="8.5" text-anchor="middle" opacity="0.8">both rows, or neither</text>
    <text x="122" y="139" font-size="10" font-weight="700" text-anchor="middle">INSERT orders</text>
    <text x="122" y="153" font-size="8.5" text-anchor="middle" opacity="0.8">the business change</text>
    <text x="122" y="195" font-size="10" font-weight="700" text-anchor="middle">INSERT outbox</text>
    <text x="122" y="209" font-size="8.5" text-anchor="middle" opacity="0.8">the event to publish</text>
    <text x="122" y="240" font-size="10" font-weight="700" text-anchor="middle">COMMIT</text>
    <text x="122" y="253" font-size="8.5" text-anchor="middle" opacity="0.85">atomicity is the DB's job</text>

    <text x="364" y="94" font-size="11.5" font-weight="700" text-anchor="middle">RELAY — poll or tail</text>
    <text x="364" y="131" font-size="9.5" text-anchor="middle">1 · SELECT WHERE published_at IS NULL</text>
    <text x="364" y="169" font-size="9.5" text-anchor="middle">2 · publish to the broker</text>
    <text x="364" y="200" font-size="9" font-weight="700" text-anchor="middle" fill="#e0930f">CRASH WINDOW — sent, not marked</text>
    <text x="364" y="231" font-size="9.5" text-anchor="middle">3 · UPDATE SET published_at</text>
    <text x="486" y="278" font-size="9" text-anchor="middle" opacity="0.85">unmarked rows are re-read and REPUBLISHED</text>

    <text x="567" y="146" font-size="11" font-weight="700" text-anchor="middle" fill="#7c5cff">BROKER</text>
    <text x="567" y="168" font-size="9" text-anchor="middle" opacity="0.9">413 delivered</text>
    <text x="567" y="186" font-size="9" text-anchor="middle" opacity="0.9">for 400 orders</text>
    <text x="567" y="204" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">13 duplicates</text>

    <text x="759" y="94" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">IDEMPOTENT CONSUMER</text>
    <text x="759" y="112" font-size="8.5" text-anchor="middle" opacity="0.8">the inbox pattern — Lesson 6</text>
    <text x="759" y="132" font-size="9" text-anchor="middle" opacity="0.9">ONE transaction:</text>
    <text x="759" y="162" font-size="9.5" text-anchor="middle">INSERT inbox (event_id)</text>
    <text x="759" y="180" font-size="9.5" text-anchor="middle">+ apply the effect</text>
    <text x="759" y="200" font-size="8.5" text-anchor="middle" opacity="0.85">duplicate key -&gt; skip</text>
    <text x="759" y="234" font-size="10" font-weight="700" text-anchor="middle" fill="#0fa07f">400 effects · 13 suppressed</text>
    <text x="759" y="250" font-size="8.5" text-anchor="middle" opacity="0.85">400 distinct orders, each once</text>

    <text x="44" y="316" font-size="11" font-weight="700" fill="#e0930f">THE TRADE, MEASURED — same 400 orders, same 45 injected kills</text>
    <text x="44" y="338" font-size="9.5" opacity="0.95">naive commit-then-publish   400 orders   355 events    45 ORPHANS    0 phantoms     0 dup   ·  fast and wrong</text>
    <text x="44" y="356" font-size="9.5" opacity="0.95">outbox + relay              400 orders   413 events     0 orphans    0 phantoms    13 dup   ·  correct, and noisy by design</text>

    <text x="440" y="392" font-size="10.5" text-anchor="middle" opacity="0.95">The relay still has a publish-then-mark dual write — but it can only fail toward REDELIVERY, never toward LOSS.</text>
    <text x="440" y="412" font-size="10" text-anchor="middle" opacity="0.85">That asymmetry is the whole pattern: an unrecoverable loss is traded for a recoverable duplicate.</text>
    <text x="440" y="436" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">At-least-once by construction — idempotent consumers are a prerequisite, not an enhancement.</text>
  </g>
</svg>
```

#### The relay's design decisions

The relay is where all the engineering lives, and every one of these choices shows up in production.

**Polling versus streaming.** The simplest relay wakes on a timer and queries for unpublished rows. Easy to reason about, easy to operate, and it costs you two things: up to one poll interval of latency per event, and a query against your primary database forever, including when there is nothing to do. The program measures the whole curve — a 5 ms interval gives 6.0 ms mean latency and burns 4.99 queries per event with **79.9% of polls returning nothing**; a 2,000 ms interval costs 0.14 queries per event but 1,488.5 ms mean latency. Pick from the measured table rather than guessing — and if the trade-off is unacceptable in both directions, that is what CDC is for.

**Index the unpublished rows.** `WHERE published_at IS NULL ORDER BY id` is fast on a small outbox and catastrophic on a large one. A **partial index** — one that indexes only the rows matching a predicate — keeps it cheap at any table size:

```sql
CREATE INDEX ix_outbox_unpublished ON outbox (id) WHERE published_at IS NULL;
```

It contains only the pending rows, so it stays tiny even when the table holds a hundred million published ones. The program prints the planner's actual choice on a 50,040-row outbox with 40 pending: `SCAN outbox USING INDEX ix_outbox_unpublished` with the index, and a bare `SCAN outbox` — 50,040 rows examined to find 40 — without it.

**Prune the outbox, or it becomes your largest table.** Every event your system has ever emitted accumulates here: at 1,000 events/second with a 500-byte payload, 43 GB/day. Decide on day one between deleting rows immediately after publishing (simplest; you lose the audit trail and the ability to replay), marking them published and deleting anything older than *N* days in a nightly job, or partitioning by day and dropping whole partitions. Delete in **batches** — one `DELETE ... WHERE published_at < ...` over ten million rows takes a long lock and generates enormous WAL. An unpruned outbox is the most common way this pattern goes wrong six months in.

**Preserve ordering deliberately.** Publishing in insertion order (`ORDER BY id`) gives global ordering, but [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/) already showed that global ordering does not survive parallel consumers. What you need is **per-aggregate ordering**: store the `partition_key` and a per-aggregate `seq` on the outbox row and publish with that key, so one customer's events stay ordered while different customers proceed in parallel. One honest wrinkle the program measures: after a relay crash the replayed batch resends events the consumer has already seen, so the **raw** stream regresses — 13 backwards steps in the measured run. Deduplication at the consumer restores a monotonic view. At-least-once means ordered *modulo redelivery*, and code that assumes strict monotonicity without deduplicating is broken.

**Batch, but bound the batch.** One row per round trip wastes broker throughput; ten thousand means a crash replays ten thousand. Tens to low hundreds is the usual answer, and the batch size is also the ceiling on how many duplicates one crash can produce.

**Run more than one relay, safely.** A single relay is a single point of failure, and the naive fix — start two — is worse than the disease: if both `SELECT` the pending rows before either marks them, both publish everything. The program measures exactly that: two relays, 48 rows, **96 events published and 48 duplicates, a 100% duplication rate.** Two correct answers:

- **Leader election.** Exactly one relay is active and the others stand by. Simple, and the right answer when ordering matters, because a single publisher trivially preserves it.
- **Claim the rows atomically.** In Postgres this is `SELECT ... FOR UPDATE SKIP LOCKED`, which locks the rows this worker selected and makes concurrent workers *skip past them* rather than block — turning the outbox into a work queue many relays can drain in parallel. The program emulates it with an atomic claiming `UPDATE` (with an expiry, so a dead relay's claims become re-claimable): 48 rows, 48 events, **0 duplicates**.

The choice between them is ordering: `SKIP LOCKED` buys throughput and gives up cross-row ordering, so reach for it when events are keyed and order only matters per key.

### Outbox lag: the metric that catches a relay dying silently

Here is the failure mode that will actually page you, and the reason this pattern needs monitoring a naive publish does not.

The relay is a separate process, and when it dies **nothing else notices**. The database is healthy, the application is healthy, orders commit with perfect success rates, every dashboard is green — and no events are reaching the broker at all. Downstream, consumers see an idle topic, which looks exactly like a quiet period.

The metric that catches it is **outbox lag**: the age of the oldest unpublished row.

```sql
SELECT EXTRACT(EPOCH FROM (now() - MIN(created_at))) AS outbox_lag_seconds
  FROM outbox WHERE published_at IS NULL;
```

This is [Lesson 9](../09-backpressure-lag-and-flow-control/)'s consumer lag, pointed at the producer side, and it has the same virtue: it is measured in **seconds, not rows**. A pending count of 205 means nothing on its own; an oldest-row age of 10.25 seconds means every downstream system is ten seconds behind reality, and it means the same thing whether your traffic is 10/second or 10,000/second.

The measured timeline below shows a relay dying at t=10 s and returning at t=20 s. Outbox lag climbs in a straight line — 2.25, 4.25, 6.25, 8.25, 10.25 seconds — because a stalled relay's lag grows at exactly one second per second, then collapses to baseline once it drains. That linear ramp is the signature of a stopped consumer, and it is unmistakable on a graph.

Two details worth stealing:

- **The healthy baseline is not zero.** The measured steady state is 0.25 s of lag with 5 rows pending — which is Little's Law once more: `L = λW = 20 orders/s × 0.25 s = 5`. Your alert threshold must sit above the poll interval, or it will fire constantly.
- **Alert on relay liveness too.** Outbox lag only rises when there is traffic. A relay that dies at 3 a.m. during a quiet period shows lag near zero until the morning rush. Pair the lag alert with a heartbeat — a metric the relay increments every loop, alerted on *absence*.

### Change Data Capture: the database already wrote the log

The polling relay works, but it is wasteful: you keep asking a database "did anything change?" when the database *already knows*, in order, the instant it happens. And it does more than know — **it has already written it down**.

Every durable database maintains a **write-ahead log** (WAL): before a change is applied to the data pages, a record describing it is appended to a sequential log and flushed to disk. That is what makes crash recovery possible, it is what you built in [Phase 3, Lesson 13](../../03-relational-databases/13-write-ahead-logging/), and it is the technique formalised in Mohan et al.'s ARIES paper (*ACM TODS* 17(1), 1992). Postgres calls it the WAL, MySQL the binary log (**binlog**), Oracle the redo log. It is not optional. It is running right now in your production database, recording every insert, update and delete in **exact commit order**.

Now describe that log without the word "recovery":

> **An ordered, durable, replayable sequence of every change ever made to the database.**

That is the event log from [Lesson 5](../05-the-log-offsets-and-replay/). Your database has been maintaining a perfect topic of its own state, for its own purposes, for as long as you have owned it.

**Change Data Capture (CDC)** is the realisation that you can subscribe to it. Instead of polling a table, a CDC connector attaches to the replication stream — the same one a read replica consumes — and receives every committed change as it happens. Postgres exposes this as **logical decoding**: an output plugin (`pgoutput` for the built-in logical replication protocol, `test_decoding` for a readable form) turns physical WAL records into logical row changes, delivered through a **replication slot**. MySQL exposes it as the binlog with `binlog_format=ROW`. The database already pays the cost of writing this log; reading it is nearly free.

Two things follow. **The latency floor drops to the commit itself**, because there is no poll interval — measured, a 500 ms poller averages 307.3 ms end to end while the log tailer averages 3.3 ms, **93× lower mean and 135× lower p95**, issuing **zero queries against the primary** instead of 60. And **the ordering is the database's own commit order** — not the order rows happened to be read in, but the actual serialization order transactions committed in, which is the strongest ordering guarantee available anywhere in your system.

One subtlety the program implements because real decoders do: WAL records are written as changes happen, *before* the transaction commits, so a decoder must **buffer changes per transaction and emit them only on reading that transaction's COMMIT record**. Postgres calls this the reorder buffer, and its consequence matters — **an aborted transaction's changes sit in the log and never reach a CDC consumer.** Rolled-back work is invisible downstream, which is exactly what you want.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="The database's write-ahead log, written for crash recovery, is already an ordered replayable stream of every change. A polling relay repeatedly queries the tables, costing 60 queries and 307 milliseconds mean latency. A CDC relay tails the same log, costing zero queries and 3.3 milliseconds. Below, query-based polling on updated_at captured only 3 of 7 changes while log-based capture got all 7 including a delete.">
  <defs>
    <marker id="l10-arrow3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto">
      <path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Your database has been writing the event log all along</text>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="28" y="48" width="330" height="86" rx="11" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    <rect x="28" y="176" width="330" height="122" rx="11" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
    <rect x="44" y="228" width="56" height="30" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="104" y="228" width="56" height="30" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="164" y="228" width="56" height="30" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="224" y="228" width="56" height="30" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="284" y="228" width="56" height="30" rx="5" fill="#7c5cff" fill-opacity="0.18" stroke="#7c5cff"/>
    <rect x="424" y="48" width="428" height="98" rx="11" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f"/>
    <rect x="424" y="188" width="428" height="110" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.6">
    <path d="M193 134 L 193 170" marker-end="url(#l10-arrow3)"/>
    <path d="M418 92 L 364 92" marker-end="url(#l10-arrow3)" stroke-dasharray="6 4"/>
    <path d="M418 240 L 364 240" marker-end="url(#l10-arrow3)"/>
  </g>

  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="28" y="330" width="824" height="112" rx="12" fill="#7f7f7f" fill-opacity="0.06" stroke="currentColor" stroke-opacity="0.45" stroke-dasharray="7 6"/>
  </g>

  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="193" y="74" font-size="11.5" font-weight="700" text-anchor="middle" fill="#3553ff">PRIMARY DATABASE</text>
    <text x="193" y="95" font-size="9.5" text-anchor="middle" opacity="0.9">tables: orders · outbox · inbox</text>
    <text x="193" y="115" font-size="9" text-anchor="middle" opacity="0.8">the current state you query</text>
    <text x="205" y="158" font-size="9" opacity="0.9">writes every change here FIRST — for its own crash recovery</text>
    <text x="193" y="200" font-size="11.5" font-weight="700" text-anchor="middle" fill="#7c5cff">WRITE-AHEAD LOG — Phase 3 Lesson 13</text>
    <text x="193" y="218" font-size="9" text-anchor="middle" opacity="0.85">ordered · durable · replayable · already paid for</text>
    <text x="72" y="247" font-size="7.5" text-anchor="middle">INS ord</text>
    <text x="132" y="247" font-size="7.5" text-anchor="middle">INS outb</text>
    <text x="192" y="247" font-size="7.5" text-anchor="middle" font-weight="700">COMMIT</text>
    <text x="252" y="247" font-size="7.5" text-anchor="middle">UPD 901</text>
    <text x="312" y="247" font-size="7.5" text-anchor="middle">DEL 902</text>
    <text x="193" y="280" font-size="9" text-anchor="middle" opacity="0.9">a decoder buffers per txid and emits on COMMIT — aborts never escape</text>

    <text x="444" y="74" font-size="11.5" font-weight="700" fill="#e0930f">POLLING RELAY — ask the table, over and over</text>
    <text x="444" y="96" font-size="9.5" opacity="0.9">SELECT ... WHERE published_at IS NULL ORDER BY id LIMIT 8</text>
    <text x="444" y="116" font-size="9.5" opacity="0.95">@ 500 ms:  mean 307.3 ms  ·  p95 540.0 ms  ·  60 DB queries</text>
    <text x="444" y="134" font-size="9.5" opacity="0.95">@   5 ms:  mean   6.0 ms  ·  4.99 queries/event  ·  79.9% empty</text>

    <text x="444" y="214" font-size="11.5" font-weight="700" fill="#0fa07f">CDC RELAY — subscribe to the log the DB already wrote</text>
    <text x="444" y="236" font-size="9.5" opacity="0.9">Postgres logical decoding (pgoutput) · MySQL binlog ROW</text>
    <text x="444" y="256" font-size="9.5" opacity="0.95">mean 3.3 ms  ·  p95 4.0 ms  ·  0 DB queries  ·  401 B/event, read once</text>
    <text x="444" y="276" font-size="9.5" font-weight="700" fill="#0fa07f">93x lower mean latency, 135x lower p95, zero load on the primary</text>
    <text x="444" y="292" font-size="8.5" opacity="0.8">cost: a replication slot that retains WAL — and fills the disk if you stop reading</text>

    <text x="48" y="356" font-size="11" font-weight="700">AND THE POLL WINDOW LOSES DATA — 7 real changes, one 1-second window</text>
    <text x="48" y="380" font-size="9.5" fill="#e0930f" font-weight="700">query-based (WHERE updated_at &gt; watermark)  captured 3 of 7</text>
    <text x="48" y="398" font-size="9" opacity="0.9">901 seen only as 'shipped' — the 'paid' state never existed as far as the consumer knows</text>
    <text x="48" y="414" font-size="9" opacity="0.9">902 created and deleted between polls — never appears AT ALL. A SELECT cannot return a deleted row.</text>
    <text x="48" y="432" font-size="9.5" fill="#0fa07f" font-weight="700">log-based captured 7 of 7 — every INSERT, UPDATE and DELETE, in exact commit order</text>

    <text x="440" y="466" font-size="10.5" text-anchor="middle" opacity="0.95">CDC is not a new log. It is the realisation that the durability log was a subscribable event stream the whole time.</text>
  </g>
</svg>
```

### Log-based capture versus query-based capture

There is a cheaper-looking way to do CDC that people reach for first, and it is lossy in ways that are easy to miss and hard to debug.

**Query-based CDC** polls the business table for rows whose `updated_at` is newer than a watermark:

```sql
SELECT * FROM orders WHERE updated_at > :last_seen ORDER BY updated_at;
```

It needs no special database privileges and no connector, which is why it keeps getting built. It also has four defects that are structural, not fixable:

| | Query-based (`updated_at` polling) | Log-based (WAL / binlog) |
|---|---|---|
| **Deletes** | **Invisible.** A `SELECT` cannot return a row that is gone. You need soft deletes everywhere, forever. | Captured, with the deleted row's contents |
| **Intermediate states** | **Lost.** Two updates between polls collapse into the final value — you see `shipped` and never learn about `paid` | Every change, individually |
| **Ordering** | By `updated_at`, which is clock-based and can tie or go backwards | Exact commit order (LSN / binlog position) |
| **Cost** | Queries the primary forever, and needs an index on `updated_at` | Reads a sequential log; near-zero impact on the primary |
| **Setup** | Nothing. Any table with a timestamp | Replication privileges, a slot or binlog reader, an operational connector |

The program demonstrates the two data-loss cases directly. Order 901 goes `pending → paid → shipped` and order 902 is created and deleted, all inside one poll window. Query-based polling captures **3 of the 7 changes**: it sees 901 as `shipped` (never learning `paid` happened) and it never sees order 902 **at all** — neither its creation nor its deletion, because by poll time the row does not exist. Log-based capture gets all seven, in order, including the `DELETE` with the row's final contents.

If your downstream is an analytics warehouse counting state transitions, or a search index that must remove deleted products, or an audit trail, query-based capture is silently wrong. Those missing rows do not raise errors either.

### Outbox events or CDC on your business tables?

Once you have CDC you can skip the outbox table entirely and tail the `orders` table directly. This is a real option with a real trade-off, and getting it wrong is expensive.

**Tailing business tables makes your database schema a public API.** The events consumers receive are your table's columns. Rename `amount_cents` to `total_cents` and you have shipped a breaking change to every downstream team — via a migration, with no schema review, no version bump, no deprecation window. Your internal storage layout, which you should be free to refactor, is now a contract with strangers. That is what [Lesson 12](../12-schema-evolution-and-event-contracts/) is entirely about, and CDC-on-tables walks straight into it.

**Row diffs are not business events.** The log tells you `orders.status changed from 'paid' to 'cancelled'`. It cannot tell you *why*, because the reason was never a column. `OrderCancelled(reason="payment_failed", refund_required=true)` is a fact about your business; `status: paid → cancelled` is a fact about your storage. Consumers need the first and can only be given the second, so each of them reverse-engineers your domain logic from column diffs and each gets it slightly wrong.

**Multi-table operations arrive shredded.** One logical "order placed" touches `orders`, `order_lines`, and `payments`; CDC on tables delivers three streams of row changes that every consumer must reassemble correctly.

The **outbox sidesteps all three**, because the row you insert is a deliberately designed, explicitly versioned, self-contained event. Your tables stay yours. So:

- **Domain events for other services → outbox table.** You control the contract, version it, and decide what is public.
- **Replication, analytics, search-index sync, cache invalidation → CDC on tables.** Here you *want* raw row changes, the consumer is yours, and there is no external contract to break.

**Outbox plus CDC is the production-grade answer.** Write the event into the outbox table inside the business transaction — atomicity solved by the database — and let a CDC connector tail the WAL for inserts into that table instead of polling it. You get transactional correctness, a deliberate event contract, no polling load, near-zero latency, and exact commit ordering. This combination is common enough that Debezium ships a transformation specifically for it.

### The operational realities of CDC

CDC is not free, and these are the three things that cause incidents.

**Replication slots retain WAL, and will fill your disk.** A Postgres replication slot guarantees the server will not recycle WAL segments the consumer has not confirmed — the guarantee that makes CDC reliable, and the one that means a stopped connector (crash, deploy, a bug, someone disabling it "temporarily") leaves the database **keeping every WAL segment forever**, waiting. The disk fills, and when the WAL volume fills, Postgres stops accepting writes. **A stopped CDC consumer can take down the production database it was only reading from.** Monitor slot retention (`confirmed_flush_lsn` versus current LSN, or the `max_slot_wal_keep_size` guard) and alert on inactive slots. This is the most common serious CDC incident.

**Initial snapshot and handover.** A new connector must read the existing table contents as a consistent snapshot, then switch to streaming from the LSN that snapshot was taken at, with no gaps or duplicates. Connectors implement this; know it exists because snapshotting a large table is a long, heavy read you schedule deliberately.

**Schema changes mid-stream.** `ALTER TABLE` while a stream runs means the decoder must associate each change with the schema in force when it was written. Log-based connectors track schema history to do this — another reason an outbox row, whose payload is one opaque versioned blob, is easier to live with than raw columns.

### The inbox pattern: the consumer's mirror image

The outbox fixes the producer. The consumer has the same problem in reverse: it receives a message, applies an effect, and acknowledges — and a crash between the effect and the ack means the message is redelivered and the effect applied twice.

The **inbox pattern** (or *idempotent receiver*) is the mirror: record the processed message's id in a table **in the same transaction as the effect**.

```sql
BEGIN;
  INSERT INTO inbox (event_id, processed_at) VALUES ('e-1013', now());  -- fails if seen
  INSERT INTO notifications (order_id, sent_at)  VALUES (1013, now());  -- the effect
COMMIT;
```

If the event has already been processed the insert violates the primary key, the transaction aborts, and the effect does not happen a second time. Effect and deduplication record are atomic because they are one write to one database — the same insight as the outbox, applied at the other end. This is [Lesson 6](../06-delivery-semantics-and-idempotency/)'s idempotency made **transactional and durable** rather than best-effort in memory: it survives the consumer restarting, and it survives a different replica receiving the redelivery.

The inbox needs pruning too, and its retention is a real decision: keep ids for longer than the maximum possible redelivery delay (broker retention plus your worst replay window), and no longer.

### Two variants worth naming

**Listen to yourself.** Invert the order: publish the event *first*, and let your own service consume it and perform the database write. There is now only one write in the request path, so no dual write. The costs are real — your own state is eventually consistent with your own API (a read immediately after a write may not see it), you cannot enforce a constraint at write time because the write happens later, and a poison event blocks your own state machine. It suits systems that are already fully event-driven; it is a poor retrofit.

**Event sourcing** is the limit case. Stop storing current state and store the ordered sequence of events *as* the database; current state is a fold over that sequence. The dual-write problem does not get solved — **it ceases to exist**, because appending the event *is* the write, and there is nothing else to keep in sync. The costs are equally real: every query needs a projection, "just look at the row" is gone, and schema evolution applies to events you can never rewrite. [Lesson 11](../11-event-driven-architecture/) picks this up.

## Build It

[`code/outbox_and_cdc.py`](code/outbox_and_cdc.py) is the whole argument, measured. It uses real `sqlite3` transactions (standard library, and real ACID semantics), a virtual clock, a seeded RNG, and a crash injected at a controlled instruction. Every approach faces **the same 45 injected kills on the same 400 orders**, so the comparison isolates exactly one variable: where the writes go.

The naive version, with the kill in the one place that matters:

```python
conn.execute("BEGIN IMMEDIATE")
conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)", ...)
if publish_first:
    broker.publish(ev, o["t"] + PUBLISH_S)
    if o["oid"] in crashes:
        raise Crash                      # dies BEFORE the commit
    conn.execute("COMMIT")
else:
    conn.execute("COMMIT")               # durable: the order exists
    if o["oid"] in crashes:
        raise Crash                      # dies BEFORE the publish
    broker.publish(ev, o["t"] + PUBLISH_S)
```

The outbox version puts both inserts inside one transaction, and then raises `Crash` at *exactly the same point* — after the commit — to prove the kill is now harmless:

```python
def place_with_outbox(conn, o, seq):
    conn.execute("BEGIN IMMEDIATE")
    conn.execute("INSERT INTO orders VALUES (?,?,?,?,?,?)", ...)
    conn.execute("INSERT INTO outbox (aggregate_id, partition_key, seq, event_id, "
                 "event_type, payload, created_at) VALUES (?,?,?,?,?,?,?)", ...)
    conn.execute("COMMIT")          # ONE write. Both rows land, or neither does.
```

The relay's claiming query is the `SKIP LOCKED` emulation — one atomic statement stamps rows as this instance's, so a concurrent relay cannot see them:

```python
self.conn.execute("BEGIN IMMEDIATE")
self.conn.execute(
    "UPDATE outbox SET claimed_by=?, claim_expires=? WHERE id IN "
    "(SELECT id FROM outbox WHERE published_at IS NULL AND "
    " (claimed_by IS NULL OR claim_expires < ?) ORDER BY id LIMIT ?)",
    (self.name, t + CLAIM_TTL, t, self.batch))
```

The miniature CDC stack is three small pieces: a `Wal` that appends JSON change records, a `WalReader` that holds a byte offset (a replication slot), and the decoder — Postgres' reorder buffer in eight lines:

```python
class LogicalDecoder:
    """Buffer per transaction, emit on COMMIT in commit order, discard on ABORT."""
    def feed(self, recs):
        out = []
        for r in recs:
            if r["op"] == "COMMIT":
                out.extend(self.pending.pop(r["txid"], []))
            elif r["op"] == "ABORT":
                self.pending.pop(r["txid"], None)      # rolled back: never emitted
            else:
                self.pending[r["txid"]].append(r)
        return out
```

Run it:

```console
$ python outbox_and_cdc.py
== 1. THE BUG: two writes, two systems, no shared transaction ==
  400 orders at 40/s; the process is killed on 45 of them,
  at the one instruction between the database commit and broker.publish().
  commit-then-publish  orders in DB  400   events published  355   ORPHANS  45   PHANTOMS   0
  publish-then-commit  orders in DB  355   events published  400   ORPHANS   0   PHANTOMS  45
  orphaned orders (exist, no event ever emitted, nothing errored): [1013, 1033, 1037, 1040, 1080, 1081] ... +39
  phantom events (event for an order that does not exist): [1013, 1033, 1037, 1040, 1080, 1081] ... +39

== 2. THE FIX: one transaction, an outbox row, a relay ==
  outbox rows written inside the order transaction: 400
  outbox + polling relay orders in DB  400   events published  413   ORPHANS   0   PHANTOMS   0
  relay: 28 wakeups, 73 queries, 6 crashes between publish and mark -> 13 duplicate deliveries
  at-least-once is the guarantee, not a defect: mean end-to-end latency 477.3 ms
  per-partition ordering regressions in the RAW stream: 13 (redelivery replays backwards)
  idempotent consumer (inbox table, same transaction as the effect):
    delivered 413   applied 400   suppressed 13   effects 400 over 400 distinct orders
    final state correct: True  (every order notified exactly once)

== 3. RELAY MECHANICS: the poll interval trade-off ==
  interval   wakeups  DB queries   empty%   mean lat    p95 lat   queries/event
       5 ms     1,995       1,995    79.9%       6.0 ms       7.0 ms           4.99
      25 ms       399         399     0.5%      12.1 ms      27.0 ms           1.00
     100 ms       100         100     0.0%      60.5 ms     102.0 ms           0.25
     500 ms        20          60     0.0%     307.3 ms     540.0 ms           0.15
    2000 ms         5          55     9.1%    1488.5 ms    3540.0 ms           0.14
  the same query on an outbox of 50,040 rows, 40 of them unpublished:
    with partial index:    SCAN outbox USING INDEX ix_outbox_unpublished
    without:               SCAN outbox   <- 50,040 rows examined to find 40

== 4. TWO RELAY INSTANCES: claiming vs not ==
  no claim (both SELECT first) published  96   distinct  48   DUPLICATES  48   left unpublished 0
  SKIP LOCKED-style claim      published  48   distinct  48   DUPLICATES   0   left unpublished 0

== 5. OUTBOX LAG: age of the oldest unpublished row ==
  the relay is dead from t=10s to t=20s. The DB is healthy. The app is healthy.
     t (s)   lag (s)   pending
        0      0.00         0  
        2      0.25         5  
        4      0.25         5  
        6      0.25         5  
        8      0.25         5  
       10      0.25         5  
       12      2.25        45  ######
       14      4.25        85  ############
       16      6.25       125  ##################
       18      8.25       165  ########################
       20     10.25       205  ##############################
       22      0.25         5  
       24      0.25         5  
       26      0.25         5  
       28      0.25         5  
       30      0.25         5  

== 6. CDC: tail the log instead of polling the table ==
  relay               events    mean lat     p95 lat   DB queries   rows/records
  polling @  100 ms     400     60.5 ms     102.0 ms          100            400
  polling @  500 ms     400    307.3 ms     540.0 ms           60            400
  CDC log tail          400      3.3 ms       4.0 ms            0          1,200
  the 500 ms poller issues 0.15 queries per event against the primary database;
  CDC issues none: it reads 160,461 B of log (401 B/event), each byte exactly once.
  latency: 93x lower mean, 135x lower p95 -- and no poll interval to tune.

== 7. QUERY-BASED CDC vs LOG-BASED CDC on the same five changes ==
  workload: 901 pending->paid->shipped, then 902 created and deleted,
            all inside ONE 1-second poll window; then 903 changes slowly.
  query-based (SELECT ... WHERE updated_at > watermark)  captured 3:
    UPSERT order=901 status=shipped
    UPSERT order=903 status=pending
    UPSERT order=903 status=paid
  log-based (decode the WAL)                             captured 7:
    INSERT order=901 status=pending
    UPDATE order=901 status=paid
    UPDATE order=901 status=shipped
    INSERT order=902 status=pending
    DELETE order=902 status=pending
    INSERT order=903 status=pending
    UPDATE order=903 status=paid
  query-based missed 4 changes: the intermediate state 'paid' and BOTH of 902's changes.
  a deleted row cannot be returned by a query. Only the log remembers it.

== 8. SUMMARY ==
  approach                    orders  events  orphan  phantom  dup   mean lat  DB reads/ev
  naive commit-then-publish     400     355      45        0    0       2.0 ms         0.00
  naive publish-then-commit     355     400       0       45    0       2.0 ms         0.00
  outbox + polling relay        400     413       0        0   13     477.3 ms         0.18
    + idempotent consumer       400     400       0        0    0     477.3 ms         0.18
  outbox + CDC (log tail)       400     400       0        0    0       3.3 ms         0.00
```

### Reading the numbers

**The bug is not rare and it is not loud.** 45 kills out of 400 orders produced **45 orphaned orders** — every single kill destroyed an event — with zero exceptions raised anywhere. Flipping to publish-first produced **45 phantom events** from the *same* 45 kills, and the two lists of order ids are identical: `[1013, 1033, 1037, 1040, 1080, 1081] ...`. Reordering the writes does not reduce the damage; it chooses which direction the inconsistency points.

**The outbox removes both, and pays in duplicates exactly as predicted.** Same workload, same 45 kills, same instruction: **400 orders, 0 orphans, 0 phantoms** — because by the time the crash lands, the intent to publish is already durable inside the order's own commit. Then six relay crashes between publish and mark produced **13 duplicate deliveries**, 413 events for 400 orders, and the inbox table applied 400 and suppressed 13 for **400 effects across 400 distinct orders**. That is the three-way comparison in one line: the naive version is fast and wrong, the outbox is correct and noisy, and the noise is precisely what Lesson 6's consumer already absorbs. The raw stream really does go backwards, too — 13 per-partition regressions, one per duplicate.

**The poll interval is a genuine dial, and the curve is steep.** From 5 ms to 2,000 ms cuts database queries per event by 36× (4.99 → 0.14) and costs 248× the mean latency (6.0 ms → 1,488.5 ms). At 5 ms, **79.9% of polls return nothing** — four in five queries against production exist only to be told "no". That cost structure is what makes CDC attractive. The index is not optional either: on 50,040 rows with 40 pending the planner uses the partial index, and without it falls back to `SCAN outbox`, examining all 50,040 to find 40. Now imagine a year of unpruned history.

**Two naive relays double everything.** 48 rows became **96 published events, a 100% duplication rate**, because both instances read the pending set before either marked it. With atomic claiming: 48 published, 0 duplicates, nothing left behind. If you take one operational detail from this lesson, take that one.

**Outbox lag catches what nothing else does.** During the outage it climbs 2.25 → 4.25 → 6.25 → 8.25 → **10.25 seconds**, one second per second, while the database and application report perfect health throughout. The healthy baseline is 0.25 s and 5 pending rows — `L = λW = 20 × 0.25 = 5` — which is why the threshold belongs above the poll interval, not at zero.

**CDC wins on both axes at once, which is unusual.** 3.3 ms mean against 307.3 ms for a 500 ms poller (93×), 4.0 ms p95 against 540.0 ms (135×), and **zero queries against the primary** against 60. It reads 160,461 bytes of log — 401 per event — each byte exactly once. The 1,200 log records for 400 events are three per transaction: the `orders` insert, the `outbox` insert, and the `COMMIT` that makes them visible to the decoder.

**Query-based capture is silently lossy.** Of 7 real changes it captured **3**. It reported order 901 as `shipped` and never knew it passed through `paid`; order 902, created and deleted inside one poll window, does not appear in its output at all, in either direction. A `SELECT` cannot return a row that no longer exists, and each of those four missing changes is a silent divergence in whatever consumes the feed.

## Use It

You will almost never hand-roll a CDC connector. You will configure one — and the point of the last hour is that you now know exactly which primitive each setting controls.

**Debezium** is the log-based CDC connector most teams meet first: it reads the Postgres WAL via logical decoding, or the MySQL binlog, and emits one message per row change. Its **outbox event router** transformation is literally this lesson, productised — you write outbox rows, and it turns them into properly keyed, properly named events:

```json
{
  "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
  "plugin.name": "pgoutput",
  "slot.name": "orders_outbox_slot",
  "publication.autocreate.mode": "filtered",
  "table.include.list": "public.outbox",

  "transforms": "outbox",
  "transforms.outbox.type": "io.debezium.transforms.outbox.EventRouter",
  "transforms.outbox.route.by.field": "event_type",
  "transforms.outbox.table.field.event.key": "partition_key",
  "transforms.outbox.table.field.event.payload": "payload"
}
```

Read it against the concepts: `plugin.name: pgoutput` is the logical decoding output plugin; `slot.name` is the replication slot (**the thing that retains WAL and fills your disk if this connector stops**); `table.include.list` restricts capture to the outbox rather than your business tables; `route.by.field` sends each event type to its own topic; and `table.field.event.key` is [Lesson 7](../07-ordering-partition-keys-and-parallel-consumers/)'s partition key, which is what preserves per-aggregate ordering.

**Postgres logical replication**, underneath all of it. You can drive it by hand, which is the best way to see that there is no magic:

```sql
-- create a slot; from now on the server retains WAL until this slot confirms
SELECT * FROM pg_create_logical_replication_slot('demo_slot', 'test_decoding');

INSERT INTO outbox (event_type, payload) VALUES ('OrderPlaced', '{"order_id":1013}');

-- consume the changes; _peek_ leaves them, _get_ advances the slot
SELECT lsn, xid, data FROM pg_logical_slot_get_changes('demo_slot', NULL, NULL);
--  0/1A2B3C8 | 743 | BEGIN 743
--  0/1A2B3F0 | 743 | table public.outbox: INSERT: event_type[text]:'OrderPlaced' ...
--  0/1A2B4A0 | 743 | COMMIT 743

-- THE operational query. Alert on both columns.
SELECT slot_name, active, pg_size_pretty(
         pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) AS retained
  FROM pg_replication_slots;

SELECT pg_drop_replication_slot('demo_slot');   -- an abandoned slot WILL fill the disk
```

That last block is the runbook step that prevents the classic incident. An inactive slot with growing `retained` bytes is a countdown to a database that cannot accept writes. Set `max_slot_wal_keep_size` as a backstop — it drops slots that fall too far behind, choosing a broken connector over a dead database.

**MySQL** is the same idea with different nouns. Row-level binlog is mandatory; the default statement-based format is not usable for CDC because you receive the SQL text rather than the resulting rows:

```text
binlog_format  = ROW        # required: capture rows, not statements
binlog_row_image = FULL     # include the BEFORE image, so you get real diffs and deletes
expire_logs_days = 7        # binlog retention -- your connector's outage budget
```

**Databases with capture built in.** Several skip the connector entirely, which is worth recognising as the same primitive rather than a separate product: **DynamoDB Streams** delivers ordered per-partition-key change records with `NEW_AND_OLD_IMAGES`; **MongoDB change streams** (`db.collection.watch()`) expose the oplog with a resumable token that is exactly a replication slot's LSN; **CockroachDB changefeeds** and **SQL Server Change Tracking / CDC** do the same. Every one is: *the durability log, exposed as a subscribable stream.*

**Kafka Connect** is the usual transport — Debezium runs as a source connector inside it — but it is only the delivery mechanism. The pattern is broker-agnostic: the same outbox table can feed RabbitMQ, SNS, Pulsar, or a plain HTTP webhook fan-out.

**And check your framework before you build anything.** Outbox support ships with most serious messaging libraries — MassTransit and NServiceBus on .NET, Eventuate Tram on Java, and equivalents in the Python and Ruby ecosystems. Recognising the pattern and configuring it correctly — transaction boundary, index, pruning job, claiming strategy, lag alert, idempotent consumers — is worth far more than writing your own relay. Which is precisely the point of having built one by hand: you now know what every one of those settings is for.

## Think about it

1. Six months after shipping the outbox, the database is out of disk and the culprit is a 400 GB `outbox` table. Design the retention policy — what you delete, when, in what batch size — and say what capability you permanently give up by deleting rather than archiving. What would you need to have kept to replay a consumer from three weeks ago?

2. A colleague argues the outbox is pointless because "the relay has the same publish-then-mark dual write you just spent an hour condemning." They are factually correct about the structure. Explain why the relay's version is acceptable and the original is not, in terms of which direction each can fail.

3. You run two relays with `SKIP LOCKED` for throughput, and a downstream team reports that one customer's `OrderPlaced` and `OrderCancelled` sometimes arrive in the wrong order. Explain the mechanism, then give two fixes — one that keeps both relays running and one that does not — and what each costs.

4. Outbox lag is flat at 0.3 s all night, then jumps to 400 s within minutes at 09:00, with no deploy. List the three most likely causes in the order you would check them, and name the single additional metric that would distinguish "relay is dead" from "relay is alive but slow" from "broker is rejecting publishes".

5. Your CDC connector is stopped for two hours and the replication slot's retained WAL grows to 800 GB on a volume with 900 GB free. Drop the slot (losing the stream, requiring a fresh snapshot) or leave it and try to restart the connector? Argue for one, and say what you would have configured beforehand so this was never a judgement call.

6. Marketing wants a `user_signed_up` feed, and an engineer proposes pointing Debezium at the `users` table because the outbox would mean touching signup code. Give the three-year argument against it — then name the one situation where tailing the table *is* right.

## Key takeaways

- **The dual-write problem is the bug in `db.commit(); broker.publish()`.** Two writes to two systems with no shared transaction cannot be made atomic by ordering them: crash after the commit and you get an **orphaned order with no event** (measured: 45 of 400 kills, zero errors raised); publish first and you get a **phantom event for a rolled-back order** (the same 45). `try/except` cannot help — `SIGKILL` does not run except blocks.
- **"It's a small window" is arithmetic, not an argument.** Little's Law: at 1,000 orders/second with a 50 ms window, `L = λW = 50` orders sit inside the danger zone at all times, so **every process restart loses ~50 events** — and a normal cluster reschedules pods dozens of times a day.
- **Two-phase commit solves atomicity and is still usually wrong here**: the coordinator's blocking window is inherent, not an implementation flaw (Skeen & Stonebraker, 1983), participants hold locks through the prepare phase, most modern brokers have no XA support, and it makes your write path's availability the *product* of database and broker — undoing exactly what Lesson 1 bought you.
- **The transactional outbox turns two writes into one.** Insert the event as a row in the same transaction as the business change and atomicity becomes the database's problem, which it solved in Phase 3. A relay then reads unpublished rows, publishes, and marks them. Measured on the same 45 kills: **400 orders, 0 orphans, 0 phantoms.**
- **It is at-least-once by construction, so idempotent consumers are a prerequisite.** The relay can die after publishing and before marking — 6 crashes produced **13 duplicates in 413 deliveries**, and the raw stream regressed per-partition 13 times. An inbox table (the event id inserted in the same transaction as the effect — Lesson 6's idempotency made transactional) reduced that to **400 effects over 400 distinct orders**.
- **Relay operations are the real work**: a partial index on the unpublished rows (without it, 50,040 rows scanned to find 40), a pruning or partitioning policy before the outbox becomes your largest table, per-aggregate order via partition key and sequence, and **never a second relay without atomic claiming** — two naive relays published 96 events for 48 rows, a 100% duplication rate, against 48 and zero with `SKIP LOCKED`-style claiming.
- **Monitor outbox lag — the age of the oldest unpublished row.** A dead relay is invisible: database healthy, app healthy, events silently stopped. Lag climbed 2.25 → 10.25 s during a 10-second outage, one second per second. Alert above the poll interval (the healthy baseline is `L = λW`, measured at 0.25 s / 5 rows) and pair it with a relay heartbeat, because lag stays flat when traffic is quiet.
- **CDC is the realisation that the database already writes your event log.** The write-ahead log (Phase 3 Lesson 13) is an ordered, durable, replayable record of every change, kept for crash recovery; Postgres logical decoding, the MySQL binlog, DynamoDB Streams and MongoDB change streams all just let you subscribe to it — measured at **93× lower mean latency, 135× lower p95, and zero queries against the primary**. Query-based polling on `updated_at` is structurally lossy: of 7 changes it captured **3**, missing an intermediate state and both changes to a row created and deleted between polls, because a `SELECT` cannot return a deleted row.
- **Choose deliberately between outbox events and CDC on tables.** Tailing tables makes your schema a public API (every column rename breaks consumers — Lesson 12), delivers row diffs instead of business facts (`status: paid→cancelled` versus `OrderCancelled(reason=...)`), and shreds multi-table operations. Outbox for domain events; CDC on tables for replication, analytics and search-index sync; **CDC tailing the outbox** for the production-grade answer. Either way, watch **replication-slot retention** — a stopped consumer makes the database retain WAL until the disk fills and writes stop.

Next: [Event-Driven Architecture: Commands, Choreography & Sagas](../11-event-driven-architecture/) — you can now emit events that are guaranteed to match your database. The next question is what they should *say*, who should react, and how a business process that spans five services either completes or unwinds itself.
