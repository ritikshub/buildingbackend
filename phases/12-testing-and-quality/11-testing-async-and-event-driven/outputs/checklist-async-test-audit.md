---
name: checklist-async-test-audit
description: For the engineer auditing an asynchronous or event-driven test suite — the morning after a flaky async test wasted a build, when a CI job has quietly grown to six minutes of sleeping, or before a new consumer ships. Every threshold here was measured by this lesson's code/async_testing.py.
phase: 12
lesson: 11
---

# Checklist: Async & Event-Driven Test Audit

For the engineer auditing what an asynchronous suite actually proves. Use it when a `202`-shaped
test goes red on an unchanged commit, when someone proposes raising a sleep, and before a new
queue consumer merges.

Every number below came out of `code/async_testing.py` in this lesson. It needs no network and
exits in under a second — run it and you can check any figure here against real output.

**Scope:** tests that assert on work happening after the call returns — queue consumers, workers,
projections, webhooks, schedulers. Not load testing (Phase 8 Lesson 14). Not the clock itself
(Phase 12 Lesson 8), though everything here depends on it.

---

## 0. Triage: is this a wait problem or a bug? — 3 minutes

The signature of a wait problem is that **the test passes when you run it alone**.

- [ ] **It fails intermittently, not always.** A deterministic failure is a bug; stop here.
- [ ] **It passes under `-k <that test>` and fails in the full suite.** Points at wait time *or* at
      state left behind by an earlier test — the next two sections split those.
- [ ] **It started failing when CI moved to a different runner size.** That is a completion-time
      distribution shift, not a code change.
- [ ] **Somebody's proposed fix is a larger number.** That is the tell.

```bash
# every sleep in the test tree, with its magnitude — the audit starts here
grep -rn "sleep(" --include='*.py' tests/ | grep -v "asyncio.sleep(0)" | sort -t'(' -k2 -rn
# total seconds this suite spends asleep on purpose
grep -rhoP "sleep\(\s*\K[0-9.]+" --include='*.py' tests/ | paste -sd+ | bc
```

**If that second number is more than ~5 seconds, the suite has a policy problem, not a timing
problem.** Measured: 500 assertions at `sleep(2.0)` is 16.7 minutes.

---

## 1. Delete every fixed sleep

There is no correct value. Both failure modes are present at every setting.

| strategy | per-test flake | suite time (500 tests) | green builds, 200 measured |
|---|---|---|---|
| `sleep(p50)` = 41 ms | 49.754% | 20.3 s | **0.0%** |
| `sleep(p90)` = 81 ms | 9.907% | 40.4 s | **0.0%** |
| `sleep(p99)` = 404 ms | 1.020% | 3.4 min | 0.5% |
| `sleep(p99.9)` = 2.0 s | 0.129% | 16.3 min | 53.5% |
| **`eventually(10 ms, 10 s)`** | **0.000%** | **30.7 s** | **100.0%** |

- [ ] **No `time.sleep` or bare `asyncio.sleep` in any test body.** Replace with a polling helper
      against an observable state.
- [ ] **Interval 10–50 ms, not 1 ms.** Measured 5.6 polls per test at a 10 ms interval; a 1 ms
      interval multiplies your test database's query load by ten for no gain.
- [ ] **Timeout 10–30 s, deliberately generous.** It is not a wait — it is the point at which you
      give up, and a correct system never reaches it.
- [ ] **The predicate asserts the FINAL state, not the first observable one.** `eventually(lambda:
      db.get(id))` returns the moment the row appears, possibly before the projection filled it in.
- [ ] **Anyone proposing to raise a sleep is shown the p99.9/p50 ratio for their pipeline.** It was
      **48×** here. If nobody has measured it, that is the first task.

---

## 2. The failure message must name the system

Five different broken systems, one assertion, measured distinct messages:

| way of waiting | distinct messages |
|---|---|
| `sleep(2.0)` then `assert` | **1 / 5** |
| polling helper that swallows the exception | **1 / 5** |
| polling helper that keeps the last error + probe | **5 / 5** |

- [ ] **The helper keeps the last exception** and re-raises it with `from last`, rather than
      raising its own `TimeoutError`.
- [ ] **It reports attempts and elapsed time** — `last of 41 attempts over 2.000s`.
- [ ] **It runs a diagnostic probe on failure**: queue depth, DLQ contents, the rows that *do*
      exist, the consumer group's lag. Write this once, use it everywhere.
- [ ] **If you use `tenacity`, `reraise=True` is set.** Without it you get `RetryError` and the
      1-of-5 result, delivered by a library.

```python
@retry(stop=stop_after_delay(10), wait=wait_fixed(0.05),
       retry=retry_if_exception_type(AssertionError), reraise=True)   # <- reraise
def assert_order_settled(order_id): ...
```

---

## 3. Give the system a completion seam

Polling is the fallback for what you do not own. If you own it, publish completion.

- [ ] **An idempotent status endpoint** — `GET /orders/{id}` → `{"state": "settled"}`.
- [ ] **A completion event** the test can subscribe to.
- [ ] **An outbox row** — the effect and its notification in one transaction, so "processed?" is a
      `SELECT` (Phase 6 Lesson 10).
- [ ] **A test-only `await worker.drain()`** that blocks until the queue is empty and all in-flight
      handlers have returned. Ten lines, and it makes every async assertion in the suite synchronous.

---

## 4. Virtual time for waits that are part of the behaviour

Sleeps *inside* the system under test — backoff ladders, reconciliation windows, webhook delays —
cannot be polled away. Control the clock instead.

- [ ] **Every wait in the code under test goes through an injected sleep/clock port**, not a direct
      `asyncio.sleep`. A virtual clock only controls what routes through it: `time.sleep()` on a
      worker thread or an OS-level socket timeout is invisible to it and will block for real.
- [ ] **The virtual clock is controllable, not frozen.** A frozen clock cannot test a timeout.
- [ ] **Ties at the same instant are broken by a sequence number**, not by scheduler order — that
      is what makes the test reproducible rather than merely fast.
- [ ] **Timeout behaviour is asserted at an exact instant.** Measured: 40 tests × a 30-second
      workflow is **20.0 minutes** on a real loop and **160 scheduler steps with 0 real sleeps** on
      a virtual one, with the state at `t = 20.0 s` identical on every run.

---

## 5. Every consumer has these four tests

Not one of them is longer than a few lines. All four are usually missing.

- [ ] **Duplicate delivery.** Deliver the same event twice; assert the effect happened once.
      Measured: an 8% redelivery rate took a naive consumer to **32/400 balances wrong** and
      **$3,571.20 over-credited**; the idempotent version was **0/400**.
- [ ] **The idempotency key is derived from the business event**, not generated at send time. A
      producer-side key gives every redelivery a fresh value and defeats every dedup downstream.
- [ ] **Out-of-order arrival.** Shuffle the event set. Measured over all 720 permutations of a
      6-event order: **3 of 5 invariants were order-independent and 2 were not**, failing in 480
      (66.7%) and 360 (50.0%) of arrival orders.
- [ ] **You have written down which invariants are order-independent** and which need a guarantee
      (partition key, version check, state machine that rejects out-of-order transitions).
- [ ] **Shuffle count is computed, not guessed.** Some invariant failed in 600 of 720 orders here,
      so K=5 detects at 100%. A 2-in-720 dependence needs **1,656 shuffles** for 99% confidence:
      `K = ceil(ln(0.01) / ln(1 − p))`.
- [ ] **Topics in tests have ≥ 2 partitions.** A single-partition topic gives total ordering for
      free and hides every one of these bugs.

---

## 6. The retry path, asserted exactly

Vague assertions pass against broken policies. "It retried" also passes for a retry storm.

- [ ] **Exact attempt count** — `assert worker.attempts == 5`, not `>= 2`.
- [ ] **Exact backoff schedule** — `[100, 200, 400, 800] ms`, 1,500 ms total to the DLQ.
- [ ] **DLQ contents**, not depth: event id, attempt count, last error string.
- [ ] **A row count after a forced retry.** This is the one everybody skips, and it is the only
      instrument that sees the worst bug in the list:

| | no idempotency key | key on the write |
|---|---|---|
| attempts | 4 | 4 |
| dead-letter queue | **0 messages** | **0 messages** |
| rows written for ONE order | **4** | **1** |
| amount charged | **16,800c** | **4,200c** |

**The DLQ is empty in both.** The retry succeeded, so no alert fires and no error rate moves.
At scale: 300 events with 20 failing after the write gave **340 rows and 389,902c over-charged**.

- [ ] **Every handler that writes before an outbound call has an idempotency key on the write** —
      or the write is moved after the call, or both are in one transaction with an outbox.

---

## 7. Python async hazards

- [ ] **No `assert` on an un-awaited coroutine.** A coroutine object has no `__bool__`, so it is
      unconditionally truthy. Measured: **6 of 6** assertions passed against a system where every
      answer was `False`. Add the guard to `conftest.py`:

```python
def strict_assert(value):
    if inspect.isawaitable(value):
        raise TypeError("assertion on an un-awaited coroutine — you meant `await`")
    assert value
```

- [ ] **`asyncio.TaskGroup` (3.11+) instead of bare `create_task`.** The `async with` block cannot
      exit with children still running. Measured: leaked tasks corrupted **3 of 3** innocent later
      tests; with cancel-on-teardown, **0 of 3**.
- [ ] **A global teardown asserts `asyncio.all_tasks()` is empty**, so a leak fails the test that
      caused it rather than the next one.
- [ ] **`asyncio_default_fixture_loop_scope` is set explicitly** in `pytest.ini`. The default has
      moved between `pytest-asyncio` releases and an unset value emits a deprecation warning.
- [ ] **`pytest-timeout` is configured as a backstop** — `timeout = 60`, `timeout_method = thread`
      — so a genuinely hung test fails the job instead of hanging the runner.
- [ ] **The adjacent linter rules are on** — Ruff's `ASYNC` family (blocking calls in a coroutine) and
      `RUF006` (dangling task), plus mypy's `truthy-bool`. None replaces the runtime guard above.

---

## 8. Broker doubles

- [ ] **In-memory broker fake in every build; the real broker on a schedule** via testcontainers,
      session-scoped container with function-scoped topics.
- [ ] **One shared contract suite runs against both** (Phase 12 Lesson 4's rule). Its clauses are
      exactly this checklist's section 5 and 6: redelivery, reordering, retry schedule, DLQ routing.
- [ ] **The fake actually redelivers and reorders.** A fake that delivers each message once, in
      order, is a fake of a broker that does not exist.

---

## 9. Before closing

1. How many seconds does this suite spend asleep on purpose, and what is that per build per day
   across the team?
2. What is the p99.9/p50 ratio of the pipeline these tests wait on? If nobody knows it, no sleep
   in the repository was chosen on evidence.
3. For each consumer: which of its assertions would still hold if every event arrived twice, in a
   random order? Name the ones that would not.
4. If a retry duplicated a write in production tonight, which alert fires? If the answer is "the
   monthly reconciliation", the row-count test in section 6 is the highest-value test you can write
   this week.

---

**Sources:** Fischer, Lynch & Paterson, *Impossibility of Distributed Consensus with One Faulty
Process*, JACM 32(2), 1985 · Lamport, *Time, Clocks, and the Ordering of Events in a Distributed
System*, CACM 21(7), 1978 · PEP 492, *Coroutines with async and await syntax*, 2015 · RFC 9110,
*HTTP Semantics*, 2022, §15.3.3 · RFC 6298, *Computing TCP's Retransmission Timer*, 2011, §5.
