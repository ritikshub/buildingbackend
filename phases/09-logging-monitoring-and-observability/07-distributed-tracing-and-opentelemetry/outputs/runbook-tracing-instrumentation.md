---
name: runbook-tracing-instrumentation
description: Roll out distributed tracing on an existing system — what to instrument first, propagation audit, span naming, attribute hygiene, sampling policy, and how to read a waterfall during an incident.
phase: 09
lesson: 07
---

# Runbook: rolling out tracing on a system that has none

Work top to bottom. Each stage is independently useful — stop after stage 3 and you already have
more than most teams. Do **not** start by writing manual spans.

## Stage 1 — Pick the path, not the service

- [ ] Choose **one user-visible request path** that matters (checkout, search, login), not one team's
      service. Tracing is only valuable end to end.
- [ ] List every hop on that path: edge/gateway → services → databases, caches, queues, third parties.
- [ ] Note which hops you **cannot** change (vendor SDK, legacy service, managed proxy). Those become
      gaps in the waterfall; know about them before they surprise you in an incident.
- [ ] Stand up a backend first (Jaeger or Tempo in a container is enough) so instrumented services
      have somewhere to send data on day one.

## Stage 2 — Auto-instrument every hop

- [ ] Add the language auto-instrumentation to every service on the path
      (`opentelemetry-instrument python app.py`, the Java agent, the Node `--require` loader).
- [ ] Set **`OTEL_SERVICE_NAME`** in every deployment. One unique, stable, lowercase name per
      service. This is the single field most likely to be wrong and hardest to fix later.
- [ ] Set `OTEL_EXPORTER_OTLP_ENDPOINT` to a collector, never directly to a vendor.
- [ ] Confirm `BatchSpanProcessor` (the default) is in use. `SimpleSpanProcessor` exports on the
      request path and will add latency.
- [ ] Deploy at 100% sampling to a low-traffic environment first and confirm spans arrive.

## Stage 3 — Propagation audit (the stage everyone skips)

A trace breaks at the first hop that drops the header, and the symptom is a *silently* truncated
waterfall, not an error.

- [ ] Send one request with a known `traceparent` and confirm every service logs the same
      `trace_id`. Broken propagation looks identical to a service that was never called.
- [ ] Check every place a request is **re-created** rather than forwarded: queue producers/consumers,
      cron and batch jobs, retries in a custom HTTP client, thread and process pools, `async` task
      spawns, third-party SDK callbacks.
- [ ] Confirm proxies, service meshes and CDNs pass `traceparent` and `tracestate` through — some
      strip unknown headers by default.
- [ ] For queue hops, verify the consumer uses a **link** to the producer, not a parent. A consumer
      that claims the producer as parent produces a trace lasting as long as your queue backlog.
- [ ] Record every confirmed gap in a list. That list is your instrumentation backlog.

## Stage 4 — Span naming and semantic conventions

- [ ] Span names must be **low cardinality**: `GET /orders/{id}`, never `GET /orders/8842`. Verify by
      counting distinct span names per service — if it grows with traffic, a name contains an id.
- [ ] Use the standard attribute names. Do not invent your own for things that already exist:
      `http.request.method`, `http.response.status_code`, `url.path`, `server.address`,
      `server.port`, `db.system.name`, `db.query.text`, `messaging.system`, `error.type`.
- [ ] Set **span kind** correctly. `CLIENT` only when you block on the reply; `PRODUCER` when you do
      not. This is what builds a correct service map.
- [ ] Set `status = ERROR` on genuine failures only. A handled 404 is not an error; a 500 is.

## Stage 5 — Manual spans, sparingly

- [ ] Add an `INTERNAL` span only where you would want a **bar in the waterfall**: expensive
      computation, third-party SDK call, cache fill, batch loop, anything you suspect.
- [ ] Aim for **5–15 manual spans per service**, not per function. A span per function makes the
      waterfall unreadable and costs real money.
- [ ] Attach a few business attributes that make traces searchable — `tenant.id`, `plan.tier`,
      `cart.item_count` — and record exceptions with `record_exception` plus `status = ERROR`.

## Stage 6 — Attribute hygiene (do this before you scale up)

- [ ] **No PII or secrets**: no passwords, tokens, API keys, card numbers, emails, addresses, full
      request or response bodies. Attributes are indexed and retained.
- [ ] **Bounded cardinality on names**; high-cardinality values belong in *attributes*, not names.
- [ ] Strip or hash query strings and URL path parameters that carry identifiers.
- [ ] Enforce it in the **Collector** with an `attributes` or `redaction` processor, so a bad deploy
      cannot leak past the boundary regardless of what the application sends.

## Stage 7 — Choose the sampling policy

| Situation | Policy |
|---|---|
| Low traffic (< ~50 req/s) | Keep 100%. Do not sample what you can afford. |
| Moderate traffic, simple ops | **Head**, `parentbased_traceidratio` at 5–20%. Cheap, uniform, blind. |
| You care about errors and the tail | **Tail** in the Collector: all errors + all slow + 5–10% of the rest. |
| Cost is the binding constraint | Tail with a lower base rate; never lower the error policy. |

- [ ] Whatever you choose, **keep 100% of errors**.
- [ ] If tail sampling: size `num_traces` against real memory, set `decision_wait` above your p99
      latency, and put a `loadbalancing` exporter keyed on `trace_id` in front of every replica.
- [ ] Set the sampler by environment variable, never in code, so you can change it without a deploy.

## Stage 8 — Verify end to end

- [ ] Fire one request and confirm the trace shows **every expected hop** with sane durations.
- [ ] Confirm a `CLIENT` span and its matching `SERVER` span differ by only network time. A large gap
      means queueing, TLS handshakes, or connection-pool wait.
- [ ] Confirm a log line emitted mid-request carries the same `trace_id` as the span.
- [ ] Deliberately break something (kill a dependency) and confirm the failed trace is kept and the
      error span is marked.
- [ ] Measure the overhead: p99 latency and CPU before versus after. Expect low single-digit percent.

## Reading a waterfall at 03:14

1. **Sort by duration, look at the root.** Total time is the top bar. Everything else is a fraction.
2. **Walk the critical path** — the longest chain of nested bars — from root to the deepest span.
   That chain, and only that chain, determines latency.
3. **Find the deepest long bar with no long children.** That leaf is where the time actually is.
4. **Then check the shapes**: long bar with short children means it is your code; staggered siblings
   means sequential calls that could be parallel; a gap before the first child means queueing or a
   lock; many identical siblings means N+1.
5. **Sum the siblings.** The biggest single bar is not always the biggest cost.
6. **Open the span's events and attributes.** A `retry` event or `exception` event usually is the
   answer; the duration only told you where to look.
7. **Jump to the logs** with that span's `trace_id` for the sentence that explains it.

> ## Decision shortcut
>
> Auto-instrument everything before you hand-write a single span. Audit propagation before you
> trust a waterfall. Keep 100% of errors before you optimize cost. And if you change only one thing
> today, set `OTEL_SERVICE_NAME` correctly in every deployment — everything downstream is built on it.
