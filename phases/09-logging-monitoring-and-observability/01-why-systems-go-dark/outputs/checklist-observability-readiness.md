---
name: checklist-observability-readiness
description: A pre-launch checklist for deciding whether a service is observable enough to run in production — the questions you must be able to answer at 3am, mapped to the signal that answers each one
phase: 09
lesson: 01
---

# Observability Readiness Checklist

Run this before a service takes production traffic, and again after any incident where you
couldn't answer a question fast enough. The test is not "do we have dashboards." The test is
**"can we answer a question nobody anticipated, from data we already emit, without shipping code?"**

## Step 0 — Write down the 3am questions first

Instrumentation designed backwards from real questions beats instrumentation designed from
"what's easy to emit." List the questions before you list the signals.

- [ ] **Is it broken?** — is the service serving traffic successfully right now?
- [ ] **Is it broken for everyone, or for a subset?** (one region, one client version, one tenant)
- [ ] **When did it start?** — to the minute, so you can line it up against deploys and config changes.
- [ ] **What changed then?** — deploys, feature flags, migrations, upstream incidents.
- [ ] **Where is the time going?** — which service, which dependency, which query.
- [ ] **Who was affected?** — enough identity to contact users or assess blast radius.
- [ ] **Is it getting better or worse?** — the derivative matters more than the value during an incident.

If a question on this list has no signal that answers it, that gap *is* your work item.

## Step 1 — Metrics (the "is it broken" layer)

- [ ] Every service exposes **request rate, error rate, and latency distribution** per route
      (the RED method — Lesson 11).
- [ ] Latency is recorded as a **histogram**, not an average, so p95/p99 are available (Lesson 5).
- [ ] Resource signals exist for every constrained thing: CPU, memory, disk, **connection pool
      saturation**, queue depth (the USE method — Lesson 11).
- [ ] Every metric label is **low cardinality** — a dimension you group by (`route`, `status`,
      `region`), never a unique identifier (`user_id`, `request_id`, raw URL). This is the
      single most common way teams destroy a metrics backend (Phase 4, Lesson 5).
- [ ] Business-level metrics exist too — checkouts completed, payments succeeded. Infrastructure
      can be perfectly green while the product is broken.

## Step 2 — Logs (the "what exactly happened" layer)

- [ ] Logs are **structured** (JSON or key-value), not prose — machine-queryable by field (Lesson 2).
- [ ] Every log line carries **service name, version, environment, timestamp, and level**.
- [ ] Every log line emitted during a request carries the **trace/request ID** (Lesson 3).
- [ ] Log **levels** are used with discipline: `ERROR` means a human should care, not "something
      unusual happened."
- [ ] Nothing logs **secrets or personal data**: no passwords, tokens, API keys, card numbers, or
      whole request/response bodies. A redaction path exists and is tested (Lesson 4).
- [ ] **Retention and volume** are set deliberately, with a known monthly cost, not left to default.
- [ ] The app writes to **stdout** and lets the platform ship it — no log rotation logic in the app.

## Step 3 — Traces (the "where did the time go" layer)

- [ ] Incoming requests **accept and propagate** the W3C `traceparent` header; if absent, one is
      generated at the edge (Lesson 3).
- [ ] The trace context is propagated across **every** boundary: HTTP calls, database queries,
      queue publishes and consumes (Phase 6 — async is where traces most often break).
- [ ] Spans exist for the expensive things: outbound HTTP, database queries, cache lookups, and any
      lock or queue wait.
- [ ] A **sampling strategy** is chosen deliberately (head vs. tail, what rate), and errors and slow
      requests are always kept (Lesson 7).

## Step 4 — Correlation (the part that makes the other three worth having)

- [ ] One trace ID appears in **logs, traces, and (via exemplars) metrics** for the same request.
- [ ] Given a trace ID from a user report, you can retrieve the **full request story** in under a
      minute — every service, every log line, every timing.
- [ ] Given a spike on a latency graph, you can reach **an example trace** from that spike.

## Step 5 — Health, SLOs and alerting

- [ ] **Liveness and readiness** endpoints exist and mean different things — readiness checks
      dependencies, liveness does not (Lesson 8).
- [ ] At least one **SLO** is defined with a numeric target and window, based on a user-visible
      symptom (Lesson 9).
- [ ] Alerts fire on **symptoms users feel** (error rate, latency, budget burn), not on causes like
      CPU (Lesson 10).
- [ ] Every alert that can page a human has a **runbook link** and a **named owner**.
- [ ] Alert volume is low enough that a page is believed by default. Alert fatigue is an outage
      waiting to happen.

## Step 6 — The tax, accounted for

- [ ] You know your **monthly observability cost** and what percentage of infra spend it is
      (10-30% is typical; above that, investigate).
- [ ] You know the **latency overhead** of instrumentation on a hot path, measured rather than assumed.
- [ ] Telemetry failure is **non-fatal**: if the log shipper or collector dies, the service keeps
      serving traffic.

## Traps to avoid

- [ ] **"We have 200 dashboards, so we're observable."** Dashboards answer questions someone already
      thought of. Novel failures need queryable raw data.
- [ ] **Averages on a dashboard.** A 120 ms mean can hide a tenth of users timing out. Use percentiles.
- [ ] **High-cardinality metric labels.** Identity belongs in logs and traces, never in a metric label.
- [ ] **Logging everything "just in case."** Maximum cost, maximum leak surface, and still no
      cross-service causality.
- [ ] **Telemetry that only exists in one environment.** If staging is instrumented and production
      isn't, you're blind exactly where it counts.

## Decision shortcut

> Metrics detect · traces localize · logs explain — and a shared trace ID is what lets one hand off
> to the next. Instrument backwards from the questions you'll be asked at 3am, keep identity out of
> metric labels and secrets out of logs, and treat every unanswerable incident question as the
> specification for the next signal you add.
