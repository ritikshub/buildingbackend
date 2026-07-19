---
name: checklist-pool-sizing
description: A worker-pool sizing and configuration checklist — classify the workload, compute a Little's Law starting point, sweep the curve and pick the knee rather than the formula, choose the queue bound and rejection policy, verify shutdown drains, and add the metrics and alerts that make saturation visible
phase: 08
lesson: 07
---

# Worker Pool Sizing & Configuration Checklist

Run this before you ship a pool, and again whenever the thing the pool *calls* changes. Every
default in every pooling library is wrong for your workload: `max_workers` is guessed from your
CPU count with no knowledge of your dependency, and the queue is unbounded. Both are your job.

The one sentence to keep in your head: **a pool size is a concurrency limit on whatever the pool
calls, not a speed dial.** `max_workers=200` is not "go faster", it is "allow 200 simultaneous
connections to the database".

## Step 0 — Classify the workload

- [ ] **CPU-bound** (pure-Python compute: parsing, hashing, serialising, maths)
      → **processes**. Threads measured 0.93x–1.01x — no gain at all. `ProcessPoolExecutor`.
- [ ] **Blocking I/O** (a sync driver, filesystem, a C extension, `requests`)
      → **threads**, `ThreadPoolExecutor` + a bound you add yourself.
- [ ] **Async-capable I/O** (an asyncio-native client end to end)
      → **no pool**. The event loop, with an `asyncio.Semaphore` per dependency.
- [ ] **Mixed** (an async service with one blocking call left)
      → `asyncio.to_thread` / `run_in_executor` onto an executor you sized *explicitly*.
- [ ] **Needs isolation, or outlives the request** (untrusted code, leaks, 10-minute jobs)
      → a separate process, or a broker + workers (Celery/RQ — Phase 6). Not a thread pool.
- [ ] If CPU-bound: confirm the work is *actually* Python bytecode. A C extension that releases
      the GIL (NumPy, `hashlib`, compression, most DB drivers) is I/O-shaped — threads work fine.

## Step 1 — Compute a starting point, do not stop there

- [ ] Measure the **unloaded** service time `W` of one call, with concurrency 1.
- [ ] Pick the arrival rate `λ` you must sustain (peak, not average — check your traffic graph).
- [ ] **Little's Law**: `L = λ × W`. That is your starting worker count.
      Example: 800 req/s × 10 ms = 8 workers.
- [ ] Equivalent form if you prefer it: `N_cores × target_utilisation × (1 + wait/service)`.
- [ ] Write down the **dependency's own limit** — DB `max_connections` and how many other
      services share it, the API's documented rate limit, the disk queue depth. Your pool
      must not exceed the share of it you are entitled to.
- [ ] Remember Little's Law is an **identity, not an optimiser**. It balanced perfectly at a
      measured-terrible 64 workers (`396/s × 166.4 ms = 65.8 in flight`). It narrows the
      search; it does not decide.

## Step 2 — Sweep the curve (this is the step people skip)

- [ ] Sweep worker counts **1, 2, 4, 8, 16, 32, 64** against a realistic dependency
      (staging with production-shaped data — not a mock that returns instantly).
- [ ] Record for each point: **throughput**, **p50**, **p99**, and the **queue time at the
      dependency** if you can get it.
- [ ] Plot it. You are looking for the **knee**: throughput flattens (or falls) while p99 keeps
      climbing. Reference shape from the lesson's measurement:

      | workers | thru/s | p50 ms | p99 ms | queued at dep |
      |--------:|-------:|-------:|-------:|--------------:|
      |       1 |    119 |    8.3 |    8.6 |         0.0   |
      |       4 |    445 |    8.9 |    9.3 |         0.0   |
      |   **8** |**813** |    9.7 |   10.3 |         0.0   |  ← knee
      |      16 |    713 |   22.4 |   22.8 |        10.8   |
      |      64 |    396 |  166.4 |  166.6 |       132.0   |  ← 49% of peak, 16x the p99

- [ ] **Pick from the curve, not the formula.** If a point has the same throughput as a smaller
      one, take the smaller one — you are buying latency for nothing.
- [ ] Sanity check: if throughput is still rising linearly at 64, your dependency is not the
      bottleneck and your test is probably not realistic.
- [ ] Re-run the sweep when the dependency changes (bigger connection pool, new index, region
      move, a new co-tenant service). Nothing will tell you your correct size moved.

## Step 3 — Bound the queue

- [ ] **The queue is bounded.** Not "large". Bounded. An unbounded queue is not a buffer; it is
      a delay line with an out-of-memory kill at the end — measured 9.3 MiB/s of growth and
      latency climbing 38 ms → 657 ms inside one second, still rising.
- [ ] `ThreadPoolExecutor`'s internal queue is **unbounded**. Add the bound yourself:
      ```python
      admission = threading.Semaphore(max_workers + queue_depth)
      if not admission.acquire(timeout=0.25):
          raise Saturated()                       # -> 503
      fut = pool.submit(fn, *args)
      fut.add_done_callback(lambda _f: admission.release())
      ```
- [ ] Size the bound from **time, not items**: `depth = service_rate × how_long_you_will_wait`.
      If you serve 800/s and your budget allows 100 ms of queueing, the bound is ~80.
- [ ] Sanity check the memory: `depth × bytes_pinned_per_item`. A queued item holds its
      arguments alive — request bodies, parsed payloads, result sets.
- [ ] **Every submit has a timeout.** Unbounded queue + blocking submit = a hang.

## Step 4 — Choose the rejection policy deliberately

| Policy | Behaviour | Right when | Measured (360 offered, capacity 333/s) |
|---|---|---|---|
| **Block** | submitter waits | loss unacceptable; producer can be slowed | 360 done, 0 lost, 1084 ms |
| **Reject** | raise / 503 | user-facing; upstream can retry or shed | 242 done, 118 rejected, 718 ms |
| **Discard oldest** | evict head | newest supersedes: prices, positions, metrics | 242 done, mean age **14.3 ms** |
| **Discard newest** | drop arrival | almost never — keeps the stale, drops the fresh | 242 done, mean age 22.2 ms |
| **Caller runs** | inline on submitter | backpressure to the accept loop, zero loss | 360 done, 112 inline, 757 ms |

- [ ] Policy chosen and **written down in the code with a comment saying why**.
- [ ] If BLOCK: confirm what the submitting thread is. If it is your HTTP accept loop, decide
      whether stalling it is backpressure (good) or a failed health check (bad).
- [ ] If DISCARD_*: confirm with the product owner that **losing items is acceptable**, in
      writing. "The queue was full" is not an answer you can give a customer six months later.
- [ ] Discarded/rejected futures are **cancelled**, so no submitter waits forever on work that
      will never run.

## Step 5 — Structure: bulkheads and the deadlock rule

- [ ] **No task blocks on the pool it is running inside.** Grep for `.result()` and
      `.get()` inside anything submitted to a pool. This is a guaranteed deadlock, not a race:
      4 workers, 4 nested tasks → 0 done, inner task never started, no error of any kind.
- [ ] **One pool per dependency.** A pool shared between payments and reporting means a slow
      report starves every payment. Separate pools turn an outage into a degraded feature.
- [ ] No two pools call into each other in a cycle (A waits on B, B waits on A).
- [ ] No task blocks on a lock that a *queued* task holds — same cycle, harder to see.
- [ ] Threads are **named** (`thread_name_prefix=`), so a stack dump during an incident tells
      you which pool is wedged.

## Step 6 — Shutdown

- [ ] Decided: **drain** (finish the queue — committed work) or **abandon**
      (`shutdown(cancel_futures=True)` — requests whose callers are already gone).
- [ ] Whichever you chose, the **in-flight task is allowed to finish**.
- [ ] Draining has a **timeout**. "Drain" without a bound is "hang", and your orchestrator's
      grace period will `SIGKILL` you mid-write.
- [ ] Workers are **not daemon threads**. A daemon thread killed halfway through a write leaves
      the file halfway through forever.
- [ ] Shutdown is wired to `SIGTERM`, and the drain timeout is shorter than the platform's
      termination grace period (`terminationGracePeriodSeconds`, ECS `stopTimeout`).
- [ ] Tested: send SIGTERM under load and confirm no partial writes and no lost committed work.

## Step 7 — Metrics and alerts

- [ ] `pool_queue_depth{pool}` — gauge.
- [ ] `pool_queue_time_seconds{pool}` — **histogram**, `now - submitted_at` recorded when a
      worker dequeues. This is the signal. Depth is a count with no meaning absent a service
      rate; queue time is directly comparable to your latency budget and it moves first.
- [ ] `pool_rejected_total{pool,policy}` — **counter** (a gauge can miss a spike between
      scrapes; a counter cannot).
- [ ] `pool_active_workers{pool}` (gauge) and `pool_task_duration_seconds{pool}` (histogram),
      so you can separate work time from wait time when the two diverge.
- [ ] End-to-end latency is measured **from submit**, not from start-of-work. A timer inside
      the task function cannot see queue time — that is how a dashboard stays green while
      users wait seconds.
- [ ] **Alert on queue TIME**, e.g. `histogram_quantile(0.99, pool_queue_time_seconds) > 0.1`
      for 5 minutes. Page on sustained rejections. Do not page on depth alone.
- [ ] Dashboard panel: queue time p99, rejection rate, active workers, and the dependency's own
      latency side by side — that combination distinguishes "we are too slow" from
      "our dependency is too slow", which is the first question in every incident.
