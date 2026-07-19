---
name: runbook-dlq-triage
description: Incident runbook for a filling dead-letter queue - triage the population, choose fix-and-redrive vs discard vs manual repair, and clear the pre-redrive safety checklist before touching anything
phase: 6
lesson: 08
---

# Runbook — The DLQ Is Filling

**Trigger:** a dead-letter queue alert fired, or someone noticed a non-zero DLQ depth.

**Golden rule for the whole incident:** messages in the DLQ are **safe and static**. They are not
being lost, they are not blocking the pipeline, and they are not getting worse. You have time to
be careful. The dangerous action is the redrive, not the waiting — so do not rush to it.

**Do not** clear, purge, or "just replay everything" before Step 4. A redrive is a deliberate,
concentrated burst of duplicates aimed at a system that may still be sick.

---

## Step 1 — The first three checks (target: 3 minutes)

- [ ] **Is the main queue still flowing?** Check consumer throughput and lag on the *source*
      queue. If it is flowing, the DLQ is doing its job and this is a **triage** task, not an
      outage. If it has stalled too, you have a live incident — head-of-line blocking or a
      crash-looping consumer — and that takes priority over the DLQ entirely.
- [ ] **What is the arrival rate, and when did it start?** Plot DLQ depth over time and find the
      inflection point. *Rate and start time matter far more than depth.* Write down the
      timestamp; it is the single most useful fact you have.
- [ ] **Does that timestamp line up with a deploy or a dependency incident?** Correlate against
      producer deploys, consumer deploys, schema-registry changes, and downstream error rates.
      Most DLQ incidents are explained entirely by this one correlation.

Record before moving on:

```text
started_at:        <timestamp of the inflection point>
arrival_rate:      <messages/min, and is it still climbing?>
depth:             <total messages now>
source_queue:      <flowing | stalled>
nearby_changes:    <deploys, incidents, schema changes within +/- 30 min>
```

---

## Step 2 — Classify the population, do not read messages one at a time

Sample 50–100 records and **aggregate**. You are identifying a shape, not debugging an instance.

```text
GROUP BY  failure_class          -> transient vs permanent
GROUP BY  last_error_code        -> one cause or many?
GROUP BY  producer/consumer_version -> does a version boundary exist?
GROUP BY  original_topic/partition  -> is it one partition or all of them?
HISTOGRAM delivery_count         -> all at max, or spread?
MIN/MAX   first_seen_at          -> a burst, or a slow drip?
```

Match against the three shapes that cover nearly everything:

| Shape | Fingerprint | Root cause lives in | Resolution |
|---|---|---|---|
| **Bad producer deploy** | abrupt start; one producer version; `failure_class` **permanent**; uniform `last_error_code` (validation / 400); payloads share a defect | the producer | roll back or fix producer → **fix-and-redrive** |
| **Downstream outage** | arrivals track a dependency's error rate; `failure_class` **transient**; `error_codes_seen` full of 503s and timeouts; `delivery_count` at max for *all* | the dependency | wait for recovery → **redrive unchanged** |
| **Schema change** | starts at a producer deploy; validation failures on *one specific field*; older messages still process fine | the contract | make consumer tolerant → **fix-and-redrive** |

Shapes that do not match any row, and what they usually mean:

- **`delivery_count` spread rather than all-at-max** → messages are dead-lettering for *different*
  reasons. Split the population and treat each group separately.
- **A single `partition_key` dominating** → a poison message plus head-of-line blocking on one
  key. Check whether that key's ordering is a correctness requirement before doing anything.
- **`consumer_version` split across the boundary** → a consumer deploy, not a producer one.
  Compare failure rates per version before rolling back.
- **Slow drip since forever, no inflection** → this is not an incident; it is an unmonitored
  defect that has been running for months. Fix the alerting (Step 6) as well as the bug.

---

## Step 3 — Decide the disposition

Choose **per group**, not for the whole queue. Write the decision and the reason somewhere durable.

| Disposition | Choose when | Watch out for |
|---|---|---|
| **Fix and redrive** | the payload is recoverable and the defect is in code or a dependency | the whole of Step 4 applies |
| **Repair and replay** | payload is malformed but reconstructable (a defaulted field, a corrected enum) | the repaired message needs a **new** `message_id` but the **same** `idempotency_key`, or you lose duplicate protection |
| **Discard** | the event is genuinely obsolete (a cancelled order, a superseded state change) or was never valid | requires explicit sign-off from the data owner; **archive before deleting**, always |
| **Escalate to the producer team** | the defect is upstream and you cannot repair the payload correctly | the DLQ keeps filling meanwhile — check retention (Step 5) |
| **Leave it and wait** | downstream still degraded | perfectly legitimate; set a reminder, do not forget it |

> **Never discard without archiving.** Copy to object storage first. "We deleted them and then
> found out they mattered" is unrecoverable; "we archived them and never looked" costs pennies.

---

## Step 4 — Pre-redrive safety checklist

**Every box must be ticked before the redrive.** This is the step that causes second incidents.

### Correctness

- [ ] **The consumer is idempotent.** Replay is duplicate delivery by construction. If processing
      the same message twice is not safe, **stop** — you cannot redrive at all until it is.
- [ ] **The dedup window still covers these messages.**
      `dedup_TTL > (now - oldest first_seen_at)`. Compute it, do not assume it.

      > This is the one that silently costs money. Messages partially applied before failing —
      > the charge landed, the ack timed out — are only suppressed while their idempotency keys
      > still exist. The lesson's measured redrive: 120 messages after 6.2 hours in the DLQ, 35 of
      > them already applied. With a 24 h dedup TTL, 35 suppressed and **zero** double charges.
      > With a 1 h TTL, **35 double charges worth EUR 4,622.09.** Same code, same button.

      If the window has already lapsed: extend the TTL and wait for it to warm, or reconcile
      against the downstream system of record to find what already applied, or redrive into a
      handler that checks the target state rather than the dedup store. Do not redrive blind.
- [ ] **The underlying defect is actually fixed and deployed**, and you can name the version.
      Redriving into the same broken consumer just refills the DLQ with a higher delivery count.
- [ ] **Ordering implications are understood.** Replayed messages arrive *after* everything
      published since. If ordering for the partition key is a correctness requirement, a redrive
      may apply a stale state transition on top of a newer one. Check before replaying.

### Blast radius

- [ ] **The downstream can survive the burst.** Compute `depth / intended replay rate` and compare
      against current headroom. A recovered dependency is still a fragile one.
- [ ] **The redrive is rate-limited.** Never replay at full speed.
      Start at ~10% of normal throughput and watch error rate for a full minute before increasing.
      SQS: `MaxNumberOfMessagesPerSecond` on `StartMessageMoveTask`. Otherwise, throttle the
      replay tool itself.
- [ ] **Redrive a canary batch first.** 10 messages. Confirm they succeed *and* that the side
      effects are correct downstream — not merely that the consumer stopped throwing.
- [ ] **You can stop it.** Know the command to halt a partial redrive before you start one.

### Repeat offenders

- [ ] **Messages that have already been redriven once are quarantined**, not replayed again.
      Track a `redrive_count` on the record; anything at 2 or more goes to a separate
      quarantine queue for manual handling. Otherwise you have rebuilt the infinite retry loop
      with extra steps.

---

## Step 5 — During and after the redrive

- [ ] Watch **three** graphs together: source-queue depth (going down), consumer error rate
      (staying flat), downstream latency and error rate (staying flat). Any one rising means stop.
- [ ] Confirm the DLQ depth actually reaches zero. A stubborn remainder is a *different* bug from
      the one you just fixed — re-run Step 2 on what is left.
- [ ] **Check DLQ retention against your triage SLA.** If retention is 4 days and the team triages
      weekly, messages are expiring silently before anyone sees them. Retention must be longer
      than your worst-case time-to-triage, and longer than your dedup TTL is *not* the same thing
      — you need both relationships to hold.
- [ ] Reconcile: pick 5 redriven messages and verify the side effect exists **exactly once** in
      the downstream system of record. This is how you find out your idempotency was theoretical.

---

## Step 6 — The alerts that should have caught this earlier

Add whichever of these was missing. Ordered by signal quality, best first.

- [ ] **First arrival after a quiet period.** DLQ was empty for N hours, now has ≥ 1 message.
      The highest-signal alert in this lesson — it usually means a deploy just broke something and
      you are ninety seconds into it, not ninety minutes.
- [ ] **Rate of arrival**, e.g. > 10 messages/minute sustained for 5 minutes. The derivative is
      what tells you this is happening *now*.
- [ ] **DLQ age** — oldest message older than your triage SLA, and separately, older than your
      dedup TTL. The second one is an alert that says *"a safe redrive is no longer possible"*,
      and almost nobody has it.
- [ ] **Depth**, last and least. It is the number everyone alerts on and the one that tells you
      least, because it conflates a six-month backlog with a four-minute incident.
- [ ] **Delivery-count distribution on the source queue.** Messages approaching `max_delivery_count`
      are a leading indicator: you can see the DLQ about to fill *before* it does.
- [ ] **Consumer-side counters**, exported and dashboarded: `retries_attempted`,
      `retries_denied_by_budget`, `circuit_breaker_state`, `messages_dead_lettered`,
      `permanent_failures_classified`. A retry mechanism you cannot observe is one you cannot tune.

---

## Post-incident: the three questions worth asking

1. **Was this failure classified correctly?** If permanent failures were being retried to the
   delivery limit, the fix is in the error path, not the DLQ. Measured cost of getting this wrong:
   ~28% of all consumer work spent on attempts that could never succeed.
2. **Was the retry window long enough for the outage that happened?** `base`, `cap` and
   `max_delivery_count` jointly decide how long a downstream outage your pipeline survives. If
   healthy messages dead-lettered, that window is your bug — not the dependency.
3. **Did the retries make the outage worse?** Check whether the dependency's recovery was delayed
   by your own retry waves. If there is no jitter, no retry budget, and no circuit breaker in the
   consumer, the answer is probably yes, and that is a code change rather than an ops change.
