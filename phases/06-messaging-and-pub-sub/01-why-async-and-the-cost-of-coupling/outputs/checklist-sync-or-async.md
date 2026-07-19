---
name: checklist-sync-or-async
description: A decision checklist for classifying a single service-to-service call as synchronous or asynchronous, with the arithmetic that justifies the answer
phase: 6
lesson: 01
---

# Checklist — Should This Call Be Synchronous or Asynchronous?

Run this per **call**, not per service. The same two services routinely have both kinds of
conversation, and "should `orders` be async?" is not a well-formed question.

The governing question, asked first and answered honestly:

> **Does the caller's very next step depend on the content of the result?**

Everything below either confirms that answer or prices it.

## Step 1 — Classify the call

- [ ] Write the call down as a sentence starting with a verb: *"charge the card"*, *"send the
      confirmation email"*, *"reserve seat 14C"*.
- [ ] **Is a human blocked on the answer, or is the caller's next line of code blocked on it?**
      Blocked on the *content* → synchronous. Blocked only on *acknowledgement* → asynchronous.
- [ ] Beware the near-miss: "a human is waiting" is **not** the same as "the caller needs the
      result." A user waiting on a slow report needs an acknowledgement and a way to collect the
      result later — that is `202 Accepted` + a job id, not a synchronous call.
- [ ] Apply the switch-off test: **if the receiving service is off for ten minutes, does the
      sender's work survive?** If no, you are looking at a synchronous call, whatever the
      transport is.

## Step 2 — Price the synchronous option

Do this even when synchronous is obviously right; the number belongs on the design doc.

- [ ] Count the **required** dependencies on the critical path (`n`).
- [ ] Combined availability = the product. `0.999^n`. Convert to annual downtime:
      `(1 - availability) x 8,760 hours`.

      | n | availability | downtime/year |
      |---|---|---|
      | 1 | 99.90% | 8.8 h |
      | 3 | 99.70% | 26.3 h |
      | 5 | 99.50% | 43.8 h |
      | 10 | 99.00% | 87.7 h |
      | 20 | 98.02% | 7.2 days |

- [ ] Sum the **p50** latencies. That is your typical response.
- [ ] Estimate the **tail**: with `n` dependencies each at a p99 of `T`, roughly `1 - 0.99^n` of
      requests hit at least one `T`-sized stall. At n=5 that is ~5% — your p95 is now somebody
      else's p99.
- [ ] Ask the slow-failure question: if this dependency stops returning errors and simply takes
      30 seconds, what exhausts first — the thread pool, the connection pool, or the event loop?

## Step 3 — If asynchronous, confirm you can pay the entry fee

Async is not free. Every unchecked box here is a production incident waiting for a date.

- [ ] **Idempotency is solved.** Delivery is at-least-once in practice, so the consumer *will*
      see duplicates. If processing the same message twice corrupts data, stop — fix this first.
      Async will damage your data faster than sync ever failed.
- [ ] **The failure path is designed.** The producer has already told the user "OK". How does a
      later failure get reported — status field the client polls, push notification, email, or a
      compensating action that undoes the earlier step?
- [ ] **Eventual consistency is acceptable to the product**, and someone non-technical has
      agreed to a UI that can say "processing" instead of "done".
- [ ] **No code assumes cross-service atomicity.** Search for logic shaped like "if the order row
      exists, the confirmation was sent." That is now false for a window of seconds to minutes.
- [ ] **Trace context propagates through the message envelope.** Without a `trace_id` carried in
      the message, "why didn't this send?" stops being answerable.
- [ ] **The broker's own availability is budgeted.** You did not remove a dependency; you swapped
      several specialised ones for a single shared critical one. Put it in the availability math.

## Step 4 — Size the queue before you ship it

Little's Law, `L = lambda * W`, holds for any stable queue regardless of distribution. Use it twice.

- [ ] **Forwards, to size the consumer pool.** `concurrency = arrival rate x processing time`.
      500 msg/s at 200 ms each → `500 x 0.2 = 100` in flight → 100 concurrent consumers.
- [ ] **Backwards, to set the alarm.** `seconds of backlog = depth / drain rate`. Alarm on
      *seconds*, not raw depth — a depth of 5,000 means nothing until you know it drains at 500/s
      and is therefore 10 seconds behind.
- [ ] **Check headroom against the utilisation knee.** `W = 1/(mu - lambda)` for M/M/1:

      | utilisation | wait (mu = 100/s) |
      |---|---|
      | 0.50 | 20 ms |
      | 0.80 | 50 ms |
      | 0.90 | 100 ms |
      | 0.95 | 200 ms |
      | 0.99 | 1,000 ms |

      Target ~70-80%. Latency degrades hyperbolically, not linearly; a consumer sized to exactly
      match average load falls over on any variance.
- [ ] **Bound the queue and decide the overflow behaviour now**, not during the incident. An
      unbounded buffer is a delayed out-of-memory kill.

## Step 5 — Sanity checks against the common mistakes

- [ ] **Not request-reply in disguise.** If the producer publishes and then blocks on a reply
      queue, you have kept temporal coupling and critical-path latency and *added* a broker. That
      is sometimes the right call — just do not record it as "decoupled".
- [ ] **Not confusing async communication with async programming.** `await`, goroutines and
      promises stop you blocking a *thread*; they do nothing about service coupling. A call made
      with `await` still multiplies into your availability chain.
- [ ] **Not async-by-default.** Reads want fresh answers. Hard invariants ("two people must not
      book the same seat") want a transaction at a single point. Two services and one deploy
      usually want a direct call with a timeout, a jittered retry, and a circuit breaker — which
      is a perfectly good architecture and far easier to debug at 3 a.m.
- [ ] **The broker earns its operational cost.** It is roughly fixed and non-trivial. Below a
      certain scale it exceeds the coupling it removes.

## The one-line record

For each call, write this into the design doc so the decision survives the people who made it:

```text
<verb the call>  ->  SYNC | ASYNC
  because: <caller needs the result | side effect, ack is enough>
  costs:   <+1 dependency on critical path, availability n -> m>  |  <duplicates possible, idempotency via X>
  failure: <timeout + retry policy>                               |  <how the user learns it failed later>
```
