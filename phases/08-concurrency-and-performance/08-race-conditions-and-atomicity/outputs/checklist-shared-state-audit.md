---
name: checklist-shared-state-audit
description: A shared-mutable-state audit for finding race conditions in an existing codebase by reading it — inventory the state, find every read-modify-write and check-then-act, name the invariant each one protects, verify the critical section actually covers it, check the cross-process and distributed equivalents, and the questions to ask on any PR that touches shared state
phase: 08
lesson: 08
---

# Shared State Audit

Races cannot be found by testing. A test can confirm a race exists; it can never confirm one
doesn't, because the bug depends on the schedule and every observation changes the schedule.
So this is a **reading** exercise. Work through it against one service, or against one PR.

Budget: half a day for a mid-sized service. Do it once and you will find things.

## Step 0 — Scope and threat model

- [ ] How many **threads** run application code? (Web server workers, `ThreadPoolExecutor`s,
      background schedulers, signal handlers, `atexit` hooks, ORM connection callbacks.)
- [ ] How many **processes** run this code at once? Gunicorn/uvicorn workers, pods, cron
      jobs, the admin console, the migration script, someone's `manage.py shell`.
- [ ] Are there **other services** that write the same rows? Anything a per-process lock
      cannot see is a different problem with a different fix (Step 5).
- [ ] Are you on, or moving to, a **free-threaded** build (PEP 703, Python 3.13+)? If so,
      every "it's fine, we have the GIL" assumption in the codebase is now void.

## Step 1 — Inventory the shared mutable state

Both words matter. State that is not shared, or not mutable, needs no protection.

- [ ] **Module-level mutable objects**: `dict`, `list`, `set`, counters, registries, caches.
      `grep -rnE '^[A-Z_]+ *[:=] *(\{|\[|set\(|dict\(|\[\])' --include='*.py'`
- [ ] **Class attributes** used as instance state (a mutable default shared by every instance).
- [ ] **Singletons and app-level objects**: config holders, feature-flag caches, connection
      pools, metrics registries, rate limiters, circuit breakers, in-memory LRU caches.
- [ ] **Mutable default arguments**: `def f(items=[])` — one list, shared by every caller.
- [ ] **Objects stored on the framework's app/request object** that outlive one request.
- [ ] **Lazily initialised globals**: `if _client is None: _client = build()` is a
      check-then-act, and a common one.
- [ ] For each item, write down **who writes it** and **when**. If the answer is "one thread,
      at import time, never again", mark it safe and move on — that is the cheap win.

## Step 2 — Find every read-modify-write

- [ ] `grep -rnE '\+=|-=|\*=|/=|\|=' --include='*.py' <src>` and keep only the hits on
      shared state. Every one is a load, an operation and a store.
- [ ] The disguised forms: `x = x + 1`, `d[k] = d[k] + 1`, `obj.n = obj.n + 1`,
      `cfg = {**cfg, "k": v}`, `items = items + [new]`, `total = sum(...)` then a write.
- [ ] Anything behind an **accessor**: a `@property`, a descriptor, an ORM column, a
      `__getitem__`. The accessor is a Python-level call, which is a thread-switch point
      sitting exactly between your load and your store.
- [ ] For each one: **is there a lock, and does it cover the read as well as the write?**
      A lock around only the assignment is the most common real bug in this area.

## Step 3 — Find every check-then-act (TOCTOU)

These do not look like concurrency code. They look like business logic, which is why they survive review.

- [ ] `grep -rnE 'if .*(not in|in) .*:' ` then a write to the same container on the next line.
- [ ] `grep -rnE 'if .*(exists|is None|== 0|> 0|>=|<=)' ` then a mutation of the same thing.
- [ ] The canonical shapes, all of which are bugs unless the check and the act share one lock
      or one transaction:
  - [ ] `if balance >= amount: balance -= amount`
  - [ ] `if seats > 0: seats -= 1`
  - [ ] `if key not in cache: cache[key] = fetch(key)`  ← this is also your cache stampede
  - [ ] `if not user_exists(u): create_user(u)`
  - [ ] `if not os.path.exists(p): open(p, "w")`
  - [ ] `if job.status == "pending": job.status = "running"`
  - [ ] `if _client is None: _client = build_client()`
- [ ] Measure the **width of each gap**. What runs between the check and the act? A log line?
      A metric? A fraud check? An ORM lazy-load? An HTTP call? Anything that touches the
      outside world releases the GIL and makes the race essentially certain under load.
- [ ] Flag any check-then-act where the gap contains **code you did not write**.

## Step 4 — For each finding, name the invariant

Do not propose a fix before you can complete this sentence. If you cannot state the invariant,
no lock you add will be correct, because you do not yet know what you are protecting.

- [ ] **Invariant** (one sentence about the data): _"__________ is always true."_
      Examples: "a seat has at most one owner"; "the sum of the two accounts is constant";
      "`count` equals `len(items)`"; "a coupon code is redeemed at most `max_uses` times".
- [ ] **Window**: the first write that makes it false → the last write that restores it.
- [ ] **Observers**: who else reads or writes this in that window? Include readers —
      a reporting job that sums two balances is an observer even though it writes nothing.
- [ ] **Critical section**: does the lock start at or before the first *read* whose value
      the write depends on, and end at or after the last write? Draw it.
- [ ] **Composition check**: is the invariant satisfiable by one call? If callers must do
      `check()` then `act()`, the API is the bug. Expose `reserve()` / `take_if_available()` /
      `INSERT ... ON CONFLICT` — one operation that makes the decision and performs it.
- [ ] **Cheaper fix available?** Before locking, ask whether the state can stop being shared
      (a `queue.Queue` hand-off, `threading.local`) or stop being mutable (a frozen dataclass
      and `dataclasses.replace`). Removing the window beats guarding it, and a caller cannot
      compose it wrongly six months from now.

## Step 5 — The cross-process and distributed equivalents

A `threading.Lock` is invisible to the process next door. For every invariant above, ask what
enforces it when two *processes* race.

- [ ] Uniqueness is a **`UNIQUE` constraint**, not an application check.
      `INSERT ... ON CONFLICT (col) DO NOTHING` / `DO UPDATE`.
- [ ] Counters and balances are **one statement**, not read-then-write:
      `UPDATE t SET n = n - 1 WHERE id = $1 AND n > 0` (and check `rowcount`).
- [ ] Optimistic concurrency: `UPDATE ... SET version = version + 1 WHERE id = $1 AND
      version = $2`. `rowcount = 0` means someone else won — re-read and retry.
- [ ] Pessimistic: `SELECT ... FOR UPDATE` inside a transaction, so the check and the act
      are in one unit. Know the isolation level you are actually running at.
- [ ] Cross-service or cross-process coordination: Redis `SET key val NX EX <ttl>` for a
      leader/lock (always with a TTL and a fencing token), `INCR` for counters — never
      `GET` then `SET`.
- [ ] Anything a client may retry needs an **idempotency key** with a uniqueness constraint
      behind it, or the retry is your race.
- [ ] Every constraint you rely on exists in a **migration**, not just in review comments.

## Step 6 — Verify the fix (without trusting a passing test)

- [ ] The critical section contains **no I/O and no unknown code** — no HTTP, no DB query,
      no callback, no overridden method, no logging handler you did not write.
- [ ] Locks are acquired in a **documented global order** wherever two can be held at once.
- [ ] `with lock:` everywhere — never a bare `acquire()`/`release()` pair that an early
      `return` or exception can skip.
- [ ] Stress test as **evidence of the bug, not proof of the fix**: run N threads through a
      `threading.Barrier`, assert an exact expected total, and temporarily set
      `sys.setswitchinterval(1e-6)` to widen the window. A failure here is real; a pass
      proves nothing.
- [ ] Add an **invariant assertion** that runs in production sampling (`assert a + b == total`)
      or a reconciliation job, so a future regression is detected rather than reported.
- [ ] Re-measure throughput. A lock around a hot path costs real money — in the lesson's run,
      an uncontended lock added **+175.7%** to a trivial operation and eight contending
      threads cost **6.6x**. If it is now too slow, shrink the critical section, shard the
      lock, or stop sharing — do not remove the lock.

## Review questions for any PR that touches shared state

Paste these into the PR template.

1. What state does this change **share between threads or processes**, and who writes it?
2. What **invariant** does that state have? State it in one sentence.
3. Where is the **window** in which the invariant is false, and what is the critical section
   that covers it? Does it cover the *read* the write depends on, or only the write?
4. Is there any **check-then-act** here? What runs in the gap, and is any of it I/O or code
   we do not own?
5. Could this be **not shared** or **immutable** instead of locked?
6. Does this API force callers to compose two operations to be correct? If so, why is it not
   one operation?
7. If two **processes** run this simultaneously, what enforces the invariant? Name the
   constraint, the row lock, or the version column — and the migration that creates it.
8. Nothing here holds a lock across I/O or across a call into code we did not write. True?
