---
name: checklist-locking-review
description: A pre-merge review checklist for any diff that adds or changes a lock — whether the state is really shared and mutable, whether it could be immutable, confined or passed instead, whether the right primitive was chosen, whether the critical section is minimal and free of I/O, and the asyncio-versus-threading mixing checks
phase: 8
lesson: 09
---

# Locking Review Checklist

Run this on any diff that introduces or changes a lock, a semaphore, a condition variable, or
a shared mutable structure. Locking bugs pass review, pass tests, pass staging, and then appear
at peak traffic as a latency cliff or a hang nobody can reproduce. Paste the relevant sections
into the PR description with the boxes ticked.

## Step 0 — Is there anything to lock at all?

Work down this ladder **in order**. Every rung you can stay on deletes a class of bug.

- [ ] **Immutable?** Can the value be built once and never mutated, replacing the whole object
      instead of a field? Frozen dataclasses, tuples, a swapped reference. If yes, **stop here** —
      no lock, no wait, no deadlock, and concurrent readers cost nothing.
- [ ] **Confined?** Can exactly one thread own it — a thread-local accumulator merged after
      `join()`, per-connection state, or the event loop's single thread? Measured at **6.9x** the
      throughput of a global lock, with zero wait time.
- [ ] **Passed?** Can ownership be handed over a `queue.Queue` (or a channel) so that only one
      thread ever touches the structure? A bounded queue gives you backpressure for free.
- [ ] **Only then: locked.** State in the PR *why* the first three do not apply. "It was easier"
      is not a reason.

## Step 1 — Is the state actually shared and mutable?

- [ ] The data is genuinely reachable from more than one thread. Trace it: who else has a
      reference? A lock around thread-confined data is pure cost.
- [ ] The data is genuinely mutated after publication. Read-only-after-construction needs no lock.
- [ ] You are not relying on any interpreter or runtime accident for atomicity. In CPython,
      `d[k] = v` is atomic today; `d[k] += 1` is not, and neither is a check-then-act on two lines.
      **Never** design around the GIL — it is not a memory model and it does not exist in Go,
      Java, Rust, or free-threaded Python builds.
- [ ] Every field the invariant spans is covered by the **same** lock. Two locks protecting two
      halves of one invariant is a race with extra steps.

## Step 2 — Is it the right primitive?

- [ ] **`Lock`** — mutual exclusion over shared state. The default; pick this unless something
      below is clearly a better fit.
- [ ] **`RLock`** — only if the same thread must legitimately re-enter. If it is your own code,
      prefer the refactor: a public `foo()` that takes the lock and a private `_foo_locked()`
      that assumes it is held. Reentrancy is usually a misplaced locking boundary.
- [ ] **`BoundedSemaphore(N)`** — a *capacity limit*, not exclusion. Anywhere you are bounding
      how many things happen at once. Never plain `Semaphore`: a stray `release()` silently
      raises the limit and nothing logs it.
- [ ] **`Condition`** — waiting for a predicate to become true. If you wrote a polling loop with
      a `sleep()` in it, this is what you wanted.
- [ ] **`Event`** — a one-shot latch: "startup complete", "shutting down". It carries no data and
      it does not reset safely.
- [ ] **`Barrier(N)`** — phase synchronisation. Pass a timeout and handle `BrokenBarrierError`.
- [ ] **`queue.Queue`** — hand-off between threads. Set `maxsize`; an unbounded queue is an
      out-of-memory kill waiting for a traffic spike.
- [ ] **RWLock** — only if reads dominate heavily **and** the critical section is long. Measured:
      4.0x on pure reads with ~90 µs critical sections, but **9.6x slower than a mutex** when the
      critical section was one dictionary lookup.

## Step 3 — The critical section

- [ ] **`with lock:` everywhere.** No bare `acquire()` without `try/finally`. A raise between a
      manual acquire and its release holds the lock **forever** — verified: the next
      `acquire(timeout=0.5)` returns `False` permanently.
- [ ] **No I/O inside the lock.** No HTTP, no database call, no file read, no `time.sleep()`,
      no logging to a network or disk sink that can block.
- [ ] **No second lock acquired inside.** If unavoidable, Step 5 becomes mandatory.
- [ ] **No user-supplied callback invoked inside.** You do not control what it does; it may
      block, take its own lock, or re-enter your API. Invoke callbacks after releasing.
- [ ] **No `await` while holding a `threading` lock**, and no blocking call inside an
      `async with asyncio.Lock()`.
- [ ] Expensive computation is hoisted **out** of the critical section: compute, then acquire,
      then mutate, then release.

## Step 4 — Condition variables specifically

- [ ] The predicate is checked in a **`while` loop**, never an `if`. Non-negotiable: `notify_all()`
      wakes N threads for one item, another thread may consume it before you reacquire, and
      spurious wakeups are permitted by specification.
- [ ] The state change **and** the `notify()` happen under the same lock the waiter uses to check
      the predicate — this is what closes the lost-wakeup race.
- [ ] `notify()` vs `notify_all()` is deliberate. `notify_all()` is the safe default; `notify()`
      only when all waiters are interchangeable.
- [ ] Every `wait()` that could block indefinitely has a timeout, or there is a documented
      shutdown path that guarantees a final notify.

## Step 5 — Granularity and ordering

- [ ] For a hot shared map, striping (`locks[hash(key) % N]`) was considered. Measured **5.45x**
      throughput over one global lock, with mean wait falling from 327.8 µs to 12.4 µs.
- [ ] A single logical operation needs only **one** lock. If it needs two, you have a deadlock
      risk (Lesson 10).
- [ ] If two or more locks are ever held simultaneously, the **global acquisition order is
      documented in a comment at the lock declarations**, and every call site obeys it.
- [ ] Lock ordering is not data-dependent (`lock(min(a,b))` before `lock(max(a,b))`, never
      `lock(a)` then `lock(b)` where a and b come from caller arguments).

## Step 6 — asyncio vs threading

The two families are **not** interchangeable, and mixing them is a common production bug.

- [ ] No `threading.Lock` is acquired inside a coroutine. It blocks the OS thread, which is
      every coroutine on that event loop.
- [ ] No `asyncio.Lock`/`Semaphore`/`Event`/`Queue` is touched from more than one thread — they
      are not thread-safe and assume a single loop on a single thread.
- [ ] Thread → loop handoff uses `asyncio.run_coroutine_threadsafe()`.
- [ ] Loop → blocking-code handoff uses `asyncio.to_thread()` (or a `ThreadPoolExecutor`), so
      blocking work never runs on the loop thread.

## Step 7 — Observability before optimisation

- [ ] Any lock suspected of being hot is wrapped in an instrumented lock reporting
      **acquisitions, contended fraction, mean wait, max wait, and wait/hold ratio**. The
      overhead is two `perf_counter()` calls per acquire.
- [ ] Lock wait time is exported as a metric (a gauge or a histogram) and is on a dashboard —
      it belongs beside saturation in the four golden signals.
- [ ] You have measured **before** changing granularity. A wait/hold ratio of ~37 means shard it;
      a contended fraction of 0.0% means leave it alone.
- [ ] Amdahl has been applied with real inputs: serial time (lock held) versus parallelisable
      time (outside any lock). A 27.1% serial fraction caps the workload at 2.76x on 8 cores —
      know the ceiling before you optimise toward it.

## Step 8 — Distributed locks (if applicable)

A lock over a network is a different, harder problem. If this diff uses Redis/etcd/ZooKeeper
for mutual exclusion:

- [ ] You have accepted that the lock is a **lease** and can expire while you still believe you
      hold it (a long GC pause, a slow disk, a VM migration).
- [ ] The protected resource validates a **fencing token** — a monotonically increasing number
      issued with each grant — and rejects any write carrying a stale one.
- [ ] Lease TTL exceeds the worst realistic pause, and the critical section finishes well inside it.
- [ ] There is a defined behaviour for "lock acquisition failed" and for "we finished but the
      lease had expired". Neither is "assume it worked".
- [ ] You have asked whether the operation could simply be made **idempotent** instead, which is
      almost always cheaper and more robust than distributed mutual exclusion.

## Red flags — stop and redesign

- A lock held across a network call, a database query, or a `sleep`.
- A `while True` loop polling a flag with a `sleep()` where a `Condition` belongs.
- `if not queue: cond.wait()` — an `if` instead of a `while`.
- A plain `Semaphore` used as a capacity limit.
- Two locks acquired in an order that depends on caller-supplied arguments.
- A comment reading "this is safe because of the GIL".
- An unbounded `queue.Queue()` between a fast producer and a slow consumer.
- A global lock protecting a structure that is on the hot path of every request.
