---
name: runbook-log-pipeline-and-cost
description: A step-by-step runbook for getting a runaway log bill under control without losing the lines you actually need during an incident
phase: 09
lesson: 04
---

# Runbook — Getting a Log Bill Under Control

Use this when the observability invoice has become a line item somebody wants explained, or
before it does. It is ordered by return on effort: every step is cheaper and safer than the
one below it. The constraint that governs the whole exercise, stated once:

> **Errors, slow requests, and audit events survive every lever at 100%.** If a change can
> lose one of those, it is the wrong change.

Budget half a day for steps 1–3 and a week of soak for the rest.

## Step 1 — Measure before you touch anything

You cannot manage what you cannot attribute. Do not change a single config until this table
exists.

- [ ] **GB/day ingested, total** — today's number and the one from 90 days ago, so you know
      the growth rate.
- [ ] **GB/day per service** (or namespace / team) and **per log level**. This is the whole
      game — cost is never evenly spread, and `DEBUG` in production is usually top-two.
- [ ] **Average bytes per event** (`GB/day ÷ events/day`). Above ~2 KB means someone is
      logging whole request or response bodies.
- [ ] **Query volume per service.** What fraction of what you store is ever read? Under 1% is
      normal, and it is what makes the rest of this runbook uncontroversial.
- [ ] **Cost split: ingest vs. storage vs. query.** Ingest usually dominates, so volume
      reduction beats retention reduction.
- [ ] Convert to money: `GB/day × 30 × $/GB`, and write the annual figure on the ticket.

## Step 2 — Find and fix the loudest lines (free money)

- [ ] Group log lines by **message template**, not by exact string, and rank by count × size.
- [ ] Expect the shape: **three lines produce more than half the volume**, and at least one
      is inside a hot loop, a retry, or a health check.
- [ ] For each of the top 3, decide: delete it, drop it to `DEBUG`, log it once per N
      occurrences, or replace it with a **metric** (Lesson 5) if it was only ever counted.
- [ ] Turn `DEBUG` **off in production**, and make the level runtime-configurable per service
      so you can turn it back on for ten minutes without a deploy.
- [ ] Stop logging whole request/response bodies. Re-measure: this step alone commonly removes
      15–30% with zero loss of debuggability.

## Step 3 — Apply error-biased sampling

Head-sampling everything at 1% is useless; the point is to keep what is rare.

- [ ] Write the policy explicitly, in code, in one place:
      - `ERROR` / `FATAL` → **100%**
      - `WARN` → **100%**
      - `status >= 400` → **100%**
      - `duration_ms >= <your p99>` → **100%**
      - `INFO` → **1–5%**
      - `DEBUG` → **1%**, or off
- [ ] **Record `sample_rate` on every kept event.** Non-negotiable — without it the data is
      no longer countable.
- [ ] Update every dashboard and saved query that counts log lines to sum the weight
      `1 / sample_rate` instead of counting rows, and sanity-check the reconstruction against
      a known-good metric (request count, Lesson 5) for a full day before trusting it.
- [ ] Add **per-tenant or per-service quotas** so one team's debug loop can't consume the
      budget or crowd out everyone else's errors.

## Step 4 — Fix label cardinality

- [ ] List your label set and count the streams it produces (product of distinct values per
      label). Target **tens to low thousands** per tenant, not millions.
- [ ] Any label whose value is an **identifier** — `trace_id`, `user_id`, `order_id`,
      `session_id`, a full URL, an IP — comes out and goes in the **body**, where a line
      filter still finds it.
- [ ] Confirm afterwards that stream count, index size, and compression ratio all improve
      together. One-line chunks do not compress, so a cardinality bug inflates *storage* as
      well as the index.

## Step 5 — Set retention deliberately, per stream class

- [ ] Define at least three classes with different policies:
      - **application logs** — sampled: hot 7d, warm 30d, archive 90d
      - **error logs** — never sampled: hot 30d, warm 90d, archive 365d
      - **audit / security logs** — separate pipeline, never sampled, never dropped,
        immutable, hot 90d, archive per your legal requirement (often years)
- [ ] Tier the tail into **object storage** rather than deleting it — roughly an order of
      magnitude cheaper per GB-month than indexed hot storage. Usually you can *extend*
      retention and still cut the bill.
- [ ] Verify a **restore-from-archive** works, and record how long it takes. An archive you
      have never read from is a backup you have never tested.
- [ ] Personal data has a storage-limitation obligation (GDPR Art. 5(1)(e)) and an erasure
      obligation (Art. 17). Pseudonymize at emit time — log a stable `user_ref` hash, not an
      email — so deletion means dropping a mapping, not rewriting immutable chunks.

## Step 6 — Harden the pipeline itself

- [ ] Agent buffer is **bounded** in memory (`Mem_Buf_Limit`, `memory_limiter`,
      `sending_queue.queue_size`) with **disk spill** configured and capped.
- [ ] Nothing in the log path can **block the application**. Verify by killing the log
      backend in staging and confirming request latency is unchanged.
- [ ] The drop policy sheds **lowest severity first** and ships highest severity first.
- [ ] **Dropped events are counted by level and exported as a metric.** Silent loss is worse
      than loud loss.
- [ ] **Agent-side redaction** exists as a backstop to app-side redaction: `authorization`,
      `password`, `token`, `set-cookie`, card-number patterns — applied to every service,
      including the ones you didn't write.

## Step 7 — Verify you didn't lose anything that mattered

Do this before closing the ticket, not after the next incident.

- [ ] Pick three real past incidents. Re-run the investigation against the **new** pipeline's
      data shape. Could you still have answered each question?
- [ ] Confirm error and warning volume is **unchanged** before and after — they were never
      sampled, so the graphs should overlay exactly — and that the audit stream's count is
      byte-for-byte identical.
- [ ] Confirm every alert that reads from logs still fires. Sampled data must never feed an
      alert threshold unless the query is weight-corrected.
- [ ] Set a **budget alert** on GB/day per service so the next regression pages you at 20%
      over, not at invoice time. Write old and new annual cost on the ticket. Close it.

## Traps

- [ ] **Cutting retention before cutting volume.** Ingest usually dominates the bill; you'll
      do the painful thing and save little.
- [ ] **Sampling errors.** Ever. They are the rare, cheap, valuable events — the entire
      reason the pipeline exists.
- [ ] **Counting rows in a sampled dataset.** Every count becomes silently wrong by the
      sampling factor, and nobody notices for months.
- [ ] **An identifier in the label set.** One label, and storage, index and compression all
      degrade at once.
- [ ] **Audit logs sharing the application pipeline.** If they share a bounded buffer with
      `DEBUG` chatter, you do not have an audit trail.
- [ ] **Un-monitored drops.** A pipeline that discards 10% of events without a counter lies
      to you during the next incident.

## Decision shortcut

> Measure per service, delete the top-3 loudest lines, then sample error-biased with
> `sample_rate` on every event — and only then talk about retention or price. Identifiers go
> in the body, never the label set. Errors, slow requests, and audit logs pass through every
> lever untouched, and every dropped event is counted by level. If you can't name your
> GB/day per service, you are not managing the bill — you are receiving it.
