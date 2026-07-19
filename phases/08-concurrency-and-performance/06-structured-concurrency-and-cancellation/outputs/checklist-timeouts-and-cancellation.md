---
name: checklist-timeouts-and-cancellation
description: An audit checklist for a service's timeout, deadline and cancellation behaviour — every outbound call bounded, the budget arithmetic adding up, deadlines propagated rather than refreshed, cleanup paths cancellation-safe, retries inside the budget, shutdown graceful and bounded, and the metrics that expose violations
phase: 8
lesson: 06
---

# Timeout & Cancellation Audit

Run this against one service. Budget 45–60 minutes. Anything unchecked is a resource
you hold without bound, which is an outage you have not scheduled yet.

```text
Service:                 ______________________
Inbound budget (SLO):    ______ ms   (what the caller/client actually waits)
Deadline source:         [ ] header  [ ] gateway default  [ ] none — we invent one
Orchestrator kill after: ______ s    (k8s terminationGracePeriodSeconds, default 30)
```

## 1 — Every outbound call has a timeout

Enumerate every egress first: HTTP, gRPC, database, cache, queue publish, object store,
DNS, auth provider, feature flags, and anything inside a `finally`.

```bash
rg -n "httpx|aiohttp|requests\." --glob '!tests' | rg -v "timeout="   # untimed egress
rg -n "asyncio\.create_task|ensure_future" --glob '!tests'            # unowned tasks
rg -n "except (BaseException|\s*:)" --glob '!tests'                   # swallows cancel
```

- [ ] Each has a **total request timeout**, not just a connect or read timeout.
      Most clients default to *no* total timeout — verify, do not assume.
- [ ] Each has a **connect timeout** (short: 100–500 ms; a peer that cannot handshake is down).
- [ ] Each has a **read/write (inactivity) timeout**, and you know it does *not* bound
      the total — a server dribbling one byte per second passes it forever.
- [ ] Each connection pool has an **acquisition timeout**. Under saturation this is where
      all your latency lives, and it is the one most often left unset.
- [ ] No unbounded `await` on a `Queue.get()`, `Event.wait()`, `Lock.acquire()`, or
## 2 — The budget arithmetic works out

- [ ] Write the chain down explicitly: `inbound budget = Σ(hop timeouts) + overhead`.
      If the right side exceeds the left, your own timeout fires first and reaches nobody.
- [ ] The **sum of the sequential path**, worst case, is **less than** the inbound budget.
- [ ] Parallel fan-out is budgeted by its **slowest** branch, not the sum — and that branch's
      timeout is still inside the inbound budget.

```text
Example that fails the audit:
  inbound 500 ms · auth 300 ms · profile 300 ms · search 300 ms  (sequential)
  Σ = 900 ms > 500 ms   ->  the client 504s at 500 ms and 400 ms of work is orphaned
```

## 3 — Deadlines propagate; they are never refreshed

- [ ] The inbound deadline is read from a header at the edge (`grpc-timeout`,
      `X-Request-Deadline`, `x-envoy-expected-rq-timeout-ms`) and converted **once**
      to an absolute instant on a **monotonic** clock.
- [ ] Every downstream timeout is derived as `remaining = deadline - now()`.
      **Grep for constants at call sites** — a literal timeout on an egress call is a refresh.
- [ ] The remaining budget is **sent on the wire** as a duration, and the receiver converts
      it to its own local instant (never send an absolute timestamp: clocks disagree).
- [ ] A hop that is about to hand out **more time than it has left** logs a warning.
      That bug is detectable in your own code; make it visible.
- [ ] There is a floor: if `remaining < minimum_useful`, fail fast with `DeadlineExceeded`
      instead of starting work that is guaranteed to be wasted.

## 4 — Cleanup paths are cancellation-safe

- [ ] Every resource acquired before an `await` is released in a `try/finally` or an
      `async with`. (Measured in the lesson: 3 of 3 connections leaked without it, 0 of 3 with it.)
- [ ] `CancelledError` is **re-raised** everywhere it is caught. Zero exceptions to this.
- [ ] No `except BaseException:` or bare `except:` in a request or worker path —
      `except Exception:` does not catch `CancelledError`, but those two do.
- [ ] Any `finally` that **awaits** is bounded. Give it its own task and
      `await asyncio.wait_for(asyncio.shield(cleanup_task), GRACE)`.
- [ ] CPU-heavy sections that run without awaiting are in an executor. Anything that spins
      longer than your tightest deadline cannot be cancelled at all — the lesson measured a
      100 ms deadline firing at 800.4 ms behind a 400 ms CPU chunk.

## 5 — Every task has an owner

- [ ] No bare `asyncio.create_task(...)` whose result is discarded.
      Prefer `async with asyncio.TaskGroup()` / `anyio.create_task_group()`.
- [ ] Genuinely long-lived background work is owned by an application-lifetime scope,
      is in a module-level set, has `add_done_callback` that removes it **and logs the
      exception**, and is cancelled at shutdown.
- [ ] Fan-outs use a task group, so one failure cancels the siblings and errors arrive
      as an `ExceptionGroup` at the block's exit.
- [ ] Handlers around task groups use `except*`, not `except` — `TaskGroup` raises an
      `ExceptionGroup` even when a single child failed.

## 6 — Retries fit inside the budget

- [ ] Total attempts × per-attempt timeout + total backoff **≤ remaining budget**.
- [ ] The remaining budget is re-checked **before every attempt**; if it cannot plausibly
      finish, do not start it. A retry with 40 ms left is guaranteed to fail and guaranteed
      to cost the dependency a full unit of work.
- [ ] Retries only on retryable conditions (connect failures, 429, 502/503/504, idempotent
      timeouts) — never on a 400 or a validation error.
- [ ] Non-idempotent operations carry an idempotency key, or are not retried.

## 7 — Shutdown is graceful and bounded

- [ ] `SIGTERM` and `SIGINT` are handled (`loop.add_signal_handler`), and the handler only
      sets an event — it does not do work.
- [ ] Step 1: **stop accepting**. Fail the readiness probe, stop the listener, stop the
      consumer poll. Keep serving what is already in flight.
- [ ] There is a **pre-stop delay** (or equivalent) long enough for load balancers and
      service meshes to notice the readiness change before the listener closes.
- [ ] Step 2: **cancel the scope**. Step 3: **await children with a bounded grace**.
      Step 4: **force and exit**.
- [ ] `grace + pre-stop delay < terminationGracePeriodSeconds`. A grace period you never
      reach is a `SIGKILL`, which runs no `finally` blocks at all.

```bash
# Measure it for real.
docker compose up -d app && sleep 2
time docker compose stop -t 30 app        # wall time should ≈ your grace period, not 30 s
docker compose logs app | rg -i "shutdown|SIGTERM|cancel"
```

## 8 — The metrics that reveal violations

Without these you cannot tell a healthy deploy from an outage.

- [ ] `requests_cancelled_total` is a **separate** counter from `requests_failed_total`.
      A deploy cancels hundreds of in-flight requests; if they land in your error rate,
      every deploy looks like an incident and the team learns to ignore the alert.
- [ ] `deadline_remaining_ms` histogram at ingress — how much budget you are *handed*.
      A mode near zero means an upstream is already burning the budget.
- [ ] Client-observed timeout rate **vs** server-observed completion rate per dependency.
      A persistent gap is orphaned work: the callee is finishing responses nobody reads.
- [ ] `tasks_in_flight` gauge, alerted when it grows while throughput does not.
      That divergence is the third incident in this lesson, in one graph.
- [ ] `shutdown_duration_seconds` and `shutdown_forced_tasks_total` on every deploy.
- [ ] An alert (not a dashboard) on `"Task exception was never retrieved"` appearing in logs.
      One occurrence means an unowned task failed silently somewhere.

## Sign-off

```text
Auditor:                  ______________________   Date: ____________
Unbounded egress calls:   ______  (target 0)
Refreshed deadlines:      ______  (target 0)
Unowned create_task:      ______  (target 0)
Measured shutdown time:   ______ ms   Grace period: ______ ms
Worst-case chain total:   ______ ms   Inbound budget: ______ ms
```
