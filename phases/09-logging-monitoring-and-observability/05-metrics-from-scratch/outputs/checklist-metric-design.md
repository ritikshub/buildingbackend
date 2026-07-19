---
name: checklist-metric-design
description: A pre-merge checklist for designing a metric before you add it — the question it answers, the right type, the right name and unit, bucket boundaries around your SLO, bounded label cardinality, and the cost in time series
phase: 09
lesson: 05
---

# Metric Design Checklist

Run this before you merge a new metric. A metric is not free and it is not easy to remove:
once a dashboard, an alert, or a runbook references it, changing its name or its buckets is a
breaking change to something a human relies on at 3am. Five minutes here saves a migration later.

## Step 0 — Does it answer a real question?

- [ ] Write the **question** first, in plain language: *"Is checkout getting slower for EU users?"*
      If you can't state one, you're adding noise.
- [ ] The question is one you would actually be asked **during an incident**, on a **dashboard**,
      or by an **alert** — not "it might be interesting one day".
- [ ] No existing metric already answers it. Two metrics measuring the same thing will eventually
      disagree, and the incident will be about which one is right.
- [ ] The question is genuinely **aggregate**. If it is about a *specific* request, user, or order,
      it belongs in a log or a trace, not a metric.

## Step 1 — The right type

- [ ] **Counter** — a quantity that only accumulates: requests served, errors, bytes, retries,
      cache misses, messages published. You will always query it as `rate()`.
- [ ] **Gauge** — a level right now: queue depth, in-flight requests, pool utilisation, memory,
      goroutines/threads, last-successful-sync timestamp.
- [ ] **Histogram** — a distribution: latency, payload size, batch size, queue wait time.
      Anything you will ever describe with a percentile.
- [ ] **Summary** — only when there is genuinely one instance and no guessable bucket ladder.
      A summary can never be aggregated across instances or re-sliced later.
- [ ] If the thing is spiky and you chose a gauge, ask whether a **counter of events** would be
      better — a gauge cannot see anything that happens between two scrapes.

## Step 2 — Name and unit

- [ ] `snake_case`, with a **namespace prefix** for the service or subsystem.
- [ ] Counters end in **`_total`**.
- [ ] **Base units only**: seconds (not ms), bytes (not KB/MB), ratios in 0-1 (not percent).
- [ ] The **unit is in the name**: `_seconds`, `_bytes`, `_ratio`, `_celsius`.
- [ ] The name describes **what is measured**, not how it is used:
      `db_query_duration_seconds`, not `slow_query_dashboard_metric`.
- [ ] A `HELP` string a stranger can read: what it counts, and any caveat about when it fires.
- [ ] You are prepared to keep this name **forever**. Renaming breaks every query built on it.

## Step 3 — Buckets (histograms only)

- [ ] You know the **SLO or target** this histogram exists to measure (Lesson 9). Buckets are
      chosen around that number, not copied from a default.
- [ ] Boundaries include: **a few below** the target (to show headroom), **several tightly around**
      it (so the estimate is precise where it matters), **a couple well above** it (so a bad tail
      has somewhere to land).
- [ ] You checked your **actual** current distribution — p50, p90, p99 — before choosing.
- [ ] The `+Inf` bucket holds a **small** fraction of observations. If your p99 keeps reporting
      exactly your largest finite bound, the ladder is too short and your tail is invisible.
- [ ] Bucket count is roughly **10-20**, not 60. Every boundary is its own time series.
- [ ] The ladder **matches the one used by sibling services**, so their histograms can be summed.
- [ ] If your stack supports **native (exponential) histograms**, consider them instead — they
      remove the manual choice entirely and still aggregate.

## Step 4 — Labels and cardinality

- [ ] Every label is a dimension you will genuinely **group by or filter on**. If you would never
      write `by (x)`, drop `x`.
- [ ] Every label has a **bounded, known set of values**, and you can name the bound.
- [ ] **No identifiers**: no `user_id`, `request_id`, `trace_id`, `session_id`, `order_id`, email,
      IP, raw URL, raw SQL, or free-text error message.
- [ ] Routes are **templates** (`/users/{id}`), never raw paths. Errors are **classes**
      (`timeout`, `invalid_input`), never messages.
- [ ] Label values cannot be supplied by a **user or an upstream caller** — that is an unbounded
      set with an attacker attached.
- [ ] You have thought about what happens when a label's value set **grows**: a new region, a
      hundred new routes, a customer-per-tenant deployment.

## Step 5 — Cost, in series

Do the multiplication explicitly. `series = product of label value counts` — times
`(buckets + 3)` for a histogram, times the **number of instances** that expose it.

- [ ] Series per instance: `_____ × _____ × _____ (× buckets+3) = _____`
- [ ] Times instances (including autoscaled peak and both sides of a deploy): `= _____`
- [ ] That number is acceptable against your backend's series budget, and you know what the
      budget is.
- [ ] If it is not: drop a label, coarsen a label's values, or reduce buckets — in that order.

## Step 6 — Coverage

- [ ] Every **ingress** (inbound HTTP handler, queue consumer, gRPC method) has the RED shape:
      a request counter with a `status` label, a duration histogram, and where useful an
      in-flight gauge.
- [ ] Every **egress** (outbound HTTP, database query, cache lookup, queue publish) has the same
      three, labelled by dependency — this is what tells you "the payments API got slow" instead
      of "we got slow".
- [ ] The **four golden signals** are covered for the service as a whole: latency, traffic,
      errors, saturation.
- [ ] Latency for **successes and failures is separable** — a fast flood of 500s must not make
      the latency graph look healthier.

## Decision shortcut

> If you will ever ask for a percentile, or ever need the number across more than one instance,
> it is a **histogram** with buckets placed around your SLO — never a summary and never an
> average. Name it in base units with the unit in the name, put only dimensions you group by in
> the labels, and multiply out the series count before you merge. Identity — who, which request,
> which order — belongs in logs and traces, and the trace ID is what joins them back together.
