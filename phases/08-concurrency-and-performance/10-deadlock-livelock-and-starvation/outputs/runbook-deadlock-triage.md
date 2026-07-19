---
name: runbook-deadlock-triage
description: Incident runbook for a service that has stopped making progress — telling deadlock from livelock from starvation from an exhausted pool from a stalled event loop, the commands to capture stacks in each runtime, how to read a wait-for cycle out of a dump, and the immediate mitigations versus the permanent fixes
phase: 8
lesson: 10
---

# Runbook: a service that has stopped making progress

**Use when:** requests hang or time out, the process is alive, and there is nothing in the logs —
that silence is the diagnostic signal, since deadlock raises no exception. **Not for** crashes,
OOM kills, or 5xx storms with stack traces: those have errors, this class of failure does not.

## Step 0 — Stabilise (5 min)

- [ ] **Do not restart yet** if you can afford 3 minutes — a restart destroys the only evidence.
      Capture a dump (Step 2) from one instance, pull it out of the load balancer, restart the rest.
- [ ] One instance or all? All = shared dependency or bad deploy. One = local lock state. Note
      the exact start time and diff it against the deploy timeline.

## Step 1 — Classify in 60 seconds

```bash
top -H -p $PID                                          # per-THREAD CPU; -H matters
curl -s localhost:9090/metrics | grep _completed_total   # work COMPLETED, not received
```

| CPU | Throughput | Diagnosis | Step |
|---|---|---|---|
| ~0% | 0 | **Deadlock**, or blocked on a dependency | 2 |
| High, steady | 0 | **Livelock** / retry loop | 3 |
| Normal | Fine overall, one tenant stuck | **Starvation** / unfair lock | 4 |
| ~0% | 0, connections climbing | **Pool exhaustion** | 5 |
| Low, loop responsive | 0 for some tasks | **Async / event-loop deadlock** | 6 |

> Reference: a deadlocked pair burned **0.1% of a core**, a livelocked pair **37%** — both with zero throughput. CPU is the fastest discriminator you have.

## Step 2 — Deadlock

```bash
py-spy dump --pid $PID --locals        # Python, from outside; works on a wedged interpreter
                                       # (in-process fallback: PYTHONFAULTHANDLER=1 + kill -ABRT)
jstack -l $PID | grep -A40 'Found one Java-level deadlock'   # JVM detects the cycle for you
kill -QUIT $PID                        # Go: full goroutine dump (or /debug/pprof/goroutine?debug=2)
```

- [ ] Find threads whose innermost frame is a lock acquisition (`acquire`, `synchronized`,
      `sync.Mutex.Lock`, `futex_wait`). **Two threads stopped on the same acquisition line — or
      on two acquisition lines in the same function — is the ABBA signature.**
- [ ] Build the wait-for graph by hand: for each blocked thread write `T<n> waits for <lock>`,
      then find who holds each lock (the thread *past* that acquisition). A closed loop is it.
      Post it in the incident channel — it is the whole diagnosis:
      `T1 -> [acct-B] -> T2 -> [acct-A] -> T1`

**Mitigate:** restart (a mutex cycle cannot be broken from outside); block traffic for the
specific entity ids involved so it does not recur immediately; reduce worker concurrency.
**Fix:** impose a total lock order on the pair, acquiring in ascending order via a comparison, not
`sorted(key=...)` (30 ns vs 251 ns of overhead). Add the pair to the documented lock hierarchy, and
`acquire(timeout=)` on request-reachable paths returning 503. Then grep for the same shapes:
functions locking two arguments of the same type (`transfer`, `merge`, `swap`, `link`), locks held
across I/O, locks held across a callback into code you do not own.

## Step 3 — Livelock

- [ ] Confirm: CPU busy, completed-work counters flat, **retry/abort counters climbing**. Take
      two dumps 5 s apart — livelocked threads move between lines, deadlocked threads do not.
      Then find the backoff. **Any constant backoff is the bug.**

```python
time.sleep(0.05)                                        # WRONG: contenders re-collide forever
time.sleep(random.uniform(0, base * 2 ** attempt))      # RIGHT: full jitter
```

**Mitigate:** raise the backoff base or randomise it via config; reduce concurrency. **Fix:** jitter *every* backoff — lock retries, DB deadlock retries, HTTP retries, reconnects,
cache refreshes — and add a retry budget so a retry loop can never amplify load.

## Step 4 — Starvation

- [ ] **Aggregate percentiles will look fine.** Measured: the starved thread's p50 and p99 were
      both 0.000 ms while the max was 460 ms, because it contributed 224 of ~14,500 samples. Never
      clear this incident on a healthy p99 — look at **per-actor** counts instead (acquisitions
      per thread, requests per tenant, jobs per queue).
- [ ] Known starvers: reader-preferring RW locks under continuous readers; priority queues where
      low-priority work never reaches the head; a barging mutex with one long critical section; a
      hot partition key. For priority inversion (a low-priority holder preempted by unrelated
      medium-priority work) enable **priority inheritance**.

**Mitigate:** move the starved actor to its own pool or queue (bulkhead). **Fix:** switch it to FIFO **only if a tail SLO exists** — a ticket lock bounded the
worst wait at 3.06 ms vs 460 ms but cost **60% of throughput**. Fairness is a purchase.

## Step 5 — Pool exhaustion

Symptom: everything waits, CPU near zero, in-use gauge pinned, wait-queue depth climbing. Cause
is usually **hold-and-wait on the pool itself** — a task holding one pooled resource waits for a
second from the same pool. Grep for a checkout inside a transaction, or a task submitted to the
pool it is already running on.

```sql
-- who blocks whom: this IS the wait-for graph, and it names the oldest transactions
SELECT blocked.pid, unnest(pg_blocking_pids(blocked.pid)) AS blocker,
       now() - blocked.xact_start AS age, left(blocked.query, 60)
FROM pg_stat_activity blocked WHERE cardinality(pg_blocking_pids(blocked.pid)) > 0;
```

**Mitigate:** raise pool size temporarily (delays, does not fix); kill the longest checkouts.
**Fix:** never acquire a second pooled resource while holding one — pass the connection down, or
give nested work its own pool.

## Step 6 — Async / event loop

Symptom: the loop is alive and some endpoints respond, but specific tasks are `pending` forever.
`asyncio.Lock` is **not reentrant**.

```python
for t in asyncio.all_tasks(loop):
    if not t.done(): print(t.get_name(), t.get_coro(), t.get_stack(limit=5))
```

Run with `PYTHONASYNCIODEBUG=1` / `loop.set_debug(True)`. Look for a lock held across an unrelated
`await`, a sync blocking call on the loop thread, or an `await` on a future only the current task
could complete. **Fix:** do the I/O first and hold the lock only over the state mutation; move
blocking calls to `run_in_executor`; timeout every await touching a lock.

## Step 7 — Database deadlocks

```sql
SHOW deadlock_timeout;              -- Postgres default 1s: a detection DELAY, not a wait cap
SELECT datname, deadlocks FROM pg_stat_database ORDER BY deadlocks DESC;
-- MySQL: SHOW ENGINE INNODB STATUS \G  -> "LATEST DETECTED DEADLOCK"
```

- [ ] A steady low rate of `deadlock detected` (SQLSTATE **40P01**, MySQL **1213**) is normal
      for concurrent writes. Alert on the *rate* and on step changes, never on one event. The
      `DETAIL` line prints the wait-for cycle and the statements — read it.
- [ ] Confirm the app retries the whole transaction with jitter — the victim was fully rolled
      back, so retry is safe.
- [ ] Order rows deterministically — `SELECT id FROM t WHERE id = ANY($1) ORDER BY id FOR UPDATE`
      before the bulk update, and sort the id list in the app so ordering never depends on a
      planner choice. Set `lock_timeout`/`statement_timeout` on user-facing connections.

## Step 8 — Prevent the next one

- [ ] **Progress heartbeat:** a counter incremented only on *completed* work, plus the alert
      `rate(completed) == 0 AND rate(received) > 0`. Catches deadlock, livelock and pool
      exhaustion with one rule.
- [ ] **Arm a canary:** `faulthandler.dump_traceback_later(30, repeat=True, exit=False)`, and a
      **lock wait-time histogram** per lock — a vertical p99 with a collapsing acquisition rate
      is a deadlock forming.
- [ ] **Ship `py-spy`/`jstack` in the production image** (you cannot install into a wedged
      container mid-incident), and **write the lock hierarchy down**; enforce it in review.
- [ ] **PR checklist for any change taking two locks:** order documented · no I/O in the
      critical section · no unknown code (callback, plugin, ORM hook) called under the lock ·
      timeout on every request-reachable acquisition · every backoff jittered.
