---
name: runbook-trace-context-propagation
description: Step-by-step runbook for adding W3C Trace Context correlation to an existing service — audit inbound headers, wire ambient context, propagate on every boundary, verify end to end, and diagnose the breakages that actually happen
phase: 09
lesson: 03
---

# Runbook: Adding Trace Context to an Existing Service

Use this when a service already logs but its lines cannot be joined to anything. Work top to
bottom; each step is verifiable before you start the next. Budget half a day for one service, and
do the **edge service first** — it mints the ids everything else inherits.

## Step 1 — Audit what already arrives

Do not add an identifier before you know which ones are already on the wire. Log the raw inbound
headers for a handful of real requests in a staging environment.

- [ ] Does `traceparent` arrive? If yes, **you must reuse it** — the rest of this runbook is about
      not throwing it away.
- [ ] Does `tracestate` arrive? Pass it through untouched, even if you do not read it.
- [ ] Does a legacy format arrive — `X-B3-TraceId` / `X-B3-SpanId` / `X-B3-Sampled` (Zipkin),
      `uber-trace-id` (Jaeger), `X-Amzn-Trace-Id` (AWS ALB), `cf-ray` (Cloudflare)?
- [ ] Does a bare `X-Request-ID` or `x-request-id` arrive from Nginx or Envoy?
- [ ] Which component is the true entry point — CDN, load balancer, API gateway, or your process?
      That component owns generation; everything downstream only continues.

**Output of this step:** a one-line statement of "our trace originates at X and arrives as header Y."

## Step 2 — Choose the context mechanism

- [ ] Python: **`contextvars.ContextVar`**. Not `threading.local()` — it breaks silently under
      `asyncio` by sharing one slot across all coroutines on a thread.
- [ ] Go: `context.Context`, threaded explicitly. Node.js: `AsyncLocalStorage` from
      `node:async_hooks`. Java: `ThreadLocal` for thread-per-request, OTel `Context` for reactive
      or virtual-thread code.
- [ ] Confirm the mechanism survives **every** place your code hands work to another executor:
      thread pools, `run_in_executor`, `asyncio.create_task`, background schedulers.

## Step 3 — Wire one inbound middleware

One place, at the outermost layer, before any route handler.

- [ ] Extract `traceparent`. Validate it: 4 dash-separated fields, lowercase hex, 32-hex trace-id,
      16-hex parent-id, not all zeros, version not `ff`.
- [ ] **Valid → continue the trace**: reuse the trace-id, record their parent-id as your parent,
      mint a fresh 8-byte span-id, and inherit the sampled flag unchanged.
- [ ] **Absent or malformed → generate**: new 16-byte trace-id, new 8-byte span-id. Never propagate
      a malformed header.
- [ ] Bind the context for the whole request, and **unbind it in a `finally`** so a pooled thread
      does not leak one request's ids into the next.
- [ ] Echo the id back: set `traceparent` on the response, and include `trace_id` in every error
      body so a user can paste it into a support ticket.

## Step 4 — Enrich the logger once

- [ ] The log formatter reads the context variable itself and adds `trace_id`, `span_id`, and
      `parent_span_id`. **No call site passes an id by hand** — if any does, the design is wrong.
- [ ] Emit them as top-level fields with exactly these names; log backends and trace backends join
      on them, and a renamed field breaks the jump from log to trace.
- [ ] Verify a log line emitted from deep inside a library callback still carries the ids.

## Step 5 — Inject on every outbound boundary

Miss one and the trace ends there. Enumerate them explicitly:

- [ ] HTTP clients — every one of them. Wrap the client, do not rely on call sites.
- [ ] Queue publishes — put `traceparent` in **message headers**, never in the body. Kafka record
      headers, AMQP `basic_properties.headers`, SQS message attributes.
- [ ] RPC calls — gRPC metadata.
- [ ] Database and cache calls, if you want spans for them (Lesson 7).
- [ ] Webhooks and third-party callbacks — decide deliberately whether to send context outside your
      trust boundary.

## Step 6 — Cover the asynchronous boundaries

This is where correlation dies in practice.

- [ ] **Queue consumers** extract from message headers, then create a **linked** span sharing the
      trace-id — not a child. The producing request finished long ago; a child span would claim the
      parent was still running.
- [ ] **Background and scheduled jobs** have no inbound request: generate a fresh trace at job
      start. If a request enqueued the work, carry that request's trace-id as a link.
- [ ] **Retries** keep the trace-id and get a **new span-id** per attempt, so you can see three
      attempts rather than one.
- [ ] **Fan-out** gives each parallel call its own child span-id from the same parent — copy the
      context, never mutate a shared one.
- [ ] **Batch consumers** processing N messages get N links, or one span per message. Decide which,
      and document it.

## Step 7 — Verify end to end

Do not declare this done on code review alone.

- [ ] Send one request through the full path with a known `traceparent` you set by hand.
- [ ] Query logs for that trace-id. Confirm you get lines from **every** service, not just the first.
- [ ] Confirm the span-ids differ per service and the parent pointers chain correctly.
- [ ] Publish a message and confirm the consumer's line carries the same trace-id.
- [ ] Force an error and confirm the trace-id appears in the HTTP response body.
- [ ] Send a deliberately malformed `traceparent` (uppercase hex, all zeros, `ff` version) and
      confirm the service starts a clean new trace instead of crashing or propagating it.

## Common breakages, and what each looks like

| Symptom | Cause |
|---|---|
| Trace starts fresh at one service | That service mints instead of reusing, or its middleware runs after another that strips headers |
| Logs correlate, traces do not | Field names differ from `trace_id` / `span_id`, or the logger and tracer read different context objects |
| Correlation works under load tests, fails in production | Thread-local under `asyncio`, or context not copied into a thread pool |
| Trace ends at the queue | Context put in the message body, or the consumer never extracts |
| Roughly half of each trace missing | A downstream service re-decides sampling instead of honouring the inbound flag |
| Ids leak between requests | Context bound without a `finally` that unbinds it, on a pooled worker |
| Header rejected by a proxy | Uppercase hex, or a non-spec length — some proxies validate strictly |

## Decision shortcut

> Generate the trace-id **once**, at the true edge, and never overwrite one that already arrived.
> Keep it in `contextvars`, not thread-locals. Inject on **every** outbound call, HTTP and queue
> alike, with the context in message headers rather than the body. Honour the inbound sampled flag
> instead of re-rolling it. Then prove it with one real request that you follow across every hop —
> if you cannot paste a trace-id into your log search and get the whole story back, it is not done.
