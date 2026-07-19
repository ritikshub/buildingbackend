---
name: checklist-async-code-review
description: A code-review checklist for async Python — unawaited coroutines, blocking calls on the event loop, unbounded gather, missing timeouts, sync libraries sneaking in, CPU work on the loop, and fire-and-forget tasks, with the grep or command that finds each one
phase: 08
lesson: 05
---

# Async Python Code Review Checklist

Paste this into the PR template of any service that runs an event loop. Async bugs share one
nasty property: **almost none of them fail the tests.** An unawaited coroutine does not raise, a
sequential `gather` is merely slow, and a blocking call only hurts under concurrent traffic —
they all pass CI and surface as an incident where the *symptom appears on innocent endpoints*.

## 0 — Run these first, before reading the diff

```bash
# Blocking calls that should never appear inside `async def`
rg -n 'requests\.(get|post|put|delete)|urllib\.request|time\.sleep\(' -g '*.py'
rg -n 'psycopg2|pymysql|redis\.Redis\(|boto3\.client|\bopen\(' -g '*.py'

rg -n 'gather\(\*' -g '*.py'          # every hit needs a Semaphore or a chunk size
rg -n 'create_task\(' -g '*.py'       # every hit needs its handle stored (see section 6)
rg -n 'asyncio\.run\(' -g '*.py'      # should be exactly one, at the process edge

# then boot it in staging with debug mode: logs any callback holding the loop >100 ms,
# and turns "coroutine was never awaited" into a hard error
PYTHONASYNCIODEBUG=1 python -W error::RuntimeWarning -m yourservice
```

## 1 — Unawaited coroutines

- [ ] Every call to an `async def` function is `await`ed, passed to `gather`/`as_completed`, or
      wrapped in `create_task`. A bare call runs **zero** lines of the body.
- [ ] No coroutine is passed where a value is expected (`if check_permissions(user):` is always
      truthy) or into a sync callback slot (`signal.signal`, `atexit.register`, a non-async-aware
      `on_startup=` hook).
- [ ] Sync functions that internally call async ones are flagged. That function cannot `await`;
      it is either mis-typed or it is silently doing nothing.
- [ ] **In review:** search the diff for `async def` names and check every call site.
      `RuntimeWarning: coroutine 'x' was never awaited` only appears on stderr at GC time.

## 2 — Blocking calls on the loop

The rule: **a blocking call inside a coroutine freezes every concurrent request on that loop.**
Measured in Lesson 05: one `time.sleep(0.3)` moved eight unrelated 50 ms coroutines to a median
of **325.8 ms** — a 6.5x inflation on endpoints that called nothing slow.

- [ ] No `requests`, `urllib`, `http.client`, or any sync HTTP client inside `async def`.
      Use `httpx.AsyncClient` / `aiohttp`.
- [ ] No sync database driver: `psycopg2`, `pymysql`, `sqlite3`, sync SQLAlchemy `Session`.
      Use `asyncpg`, `aiomysql`, or SQLAlchemy's async engine.
- [ ] No sync Redis / S3 / cloud SDK client. Use `redis.asyncio`, `aioboto3`, or `to_thread`.
- [ ] No `time.sleep()` (use `await asyncio.sleep()`), no `subprocess.run` (use
      `asyncio.create_subprocess_exec`), no sync file I/O on a hot path.
- [ ] No `Thread.join()`, `queue.Queue.get()`, contended `threading.Lock`, or `multiprocessing`
      primitive awaited-on-in-name-only inside a coroutine.
- [ ] Anything that genuinely must be sync is wrapped: `await asyncio.to_thread(fn, *args)`
      or `await loop.run_in_executor(pool, fn)`.
- [ ] New third-party libraries checked for hidden blocking (DNS, credential refresh, lazy
      imports, `certifi` loads on first use).

## 3 — CPU work on the loop

- [ ] No password hashing (`bcrypt`, `argon2`, `scrypt`, `pbkdf2`) directly in a coroutine.
- [ ] No multi-megabyte `json.loads`/`dumps`, `pickle`, CSV parse, template render, image/PDF
      processing, compression, or crypto over large buffers on the loop.
- [ ] No unbounded pure-Python loop over a large collection between two `await`s.
- [ ] CPU work is offloaded to a **`ProcessPoolExecutor`** (real parallelism), or a
      **`ThreadPoolExecutor`** only if it releases the GIL. Gathering CPU-bound coroutines
      measured **1.07x** — async cannot help here.
- [ ] Rule of thumb: any single stretch between two `await`s should stay under **~10 ms**.
      Set `loop.slow_callback_duration = 0.05` in staging to find the violations.

## 4 — Unbounded fan-out

- [ ] Every `gather(*...)` over a variable-length collection has a **`Semaphore`** bound, is
      chunked, or is provably small with a stated maximum.
- [ ] The bound is smaller than the connection pool it draws from, and smaller than the
      downstream service's rate limit. `gather` on 10,000 items creates 10,000 Tasks at once.
- [ ] Fan-out size is not attacker-controlled (a list from a request body, a webhook payload),
      and 10,000 Tasks each holding a response body is 10,000 buffers of memory.
- [ ] Retries inside a fan-out are bounded and jittered, or a downstream blip becomes a
      synchronised retry storm.

```python
sem = asyncio.Semaphore(20)
async def bounded(coro_fn, *args):
    async with sem:
        return await coro_fn(*args)
results = await asyncio.gather(*(bounded(fetch, u) for u in urls), return_exceptions=True)
```

## 5 — Timeouts and cancellation

- [ ] Every network `await` has a timeout (`asyncio.timeout()` 3.11+, `wait_for()`, or the
      client's `timeout=`). A coroutine awaiting a Future that never completes is parked forever,
      holding its connection and semaphore slot, invisible in every CPU graph.
- [ ] Client-level defaults are set once (`httpx.AsyncClient(timeout=5.0)`), and the budget
      shrinks down the chain — an inner call cannot outlive the request containing it.
- [ ] `CancelledError` is not swallowed: it derives from `BaseException` in 3.8+, but
      `except BaseException:` and bare `except:` still catch it. Re-raise it.
- [ ] Cleanup on cancellation is in `finally:`/`async with`, and any `await` inside it is
      shielded or timeout-bounded.

## 6 — Task lifetime (fire-and-forget)

- [ ] Every `create_task()` result is **stored** — in a set, a `TaskGroup`, or an attribute. The
      loop holds only a weak reference, so an unreferenced Task can be GC'd mid-flight and vanish.
- [ ] Every stored Task is eventually awaited or has a done-callback, so its exception is
      retrieved — otherwise it surfaces only as `Task exception was never retrieved`.
- [ ] Background tasks are cancelled and awaited during shutdown, not killed mid-write.
- [ ] Prefer `asyncio.TaskGroup` (3.11+) so a child failure cancels its siblings and the
      scope cannot exit with tasks still running. See Lesson 06 for the full treatment.

```python
_background: set[asyncio.Task] = set()
def spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _background.add(t)                      # keep a strong reference
    t.add_done_callback(_background.discard)
    return t
```

## 7 — Correctness between awaits

- [ ] Any read-modify-write spanning an `await` is protected. Between two `await`s your code is
      atomic; across one, the loop ran everything else — `x = await get(); x += 1; await put(x)`.
- [ ] Shared mutable state touched across an `await` uses `asyncio.Lock` — never
      `threading.Lock`, which blocks the whole loop when contended.
- [ ] No `asyncio` primitive is shared across event loops or threads without
      `run_coroutine_threadsafe` / `loop.call_soon_threadsafe`.
- [ ] Sequential `await`s over independent operations are deliberate, not accidental. A `for`
      loop with an `await` over N independent calls is **N times too slow** and never warns:
      measured 1,002.7 ms sequential vs 100.6 ms gathered for ten 100 ms calls (**9.96x**).

## 8 — Structure and entry points

- [ ] Exactly one `asyncio.run()`, at the process entry point. Never inside a library, a
      request handler, or another coroutine — it raises `RuntimeError` from a running loop.
- [ ] No `loop.run_until_complete()` in application code called from an async context.
- [ ] Async generators used with `async for` are closed properly (`aclosing()` or an explicit
      `finally`), so their cleanup runs even on early exit.
- [ ] Any new dependency is genuinely async, not a sync library behind an async wrapper.

## Reviewer's one-minute version

> Is anything called without `await`? Does anything inside a coroutine block — HTTP, DB, sleep,
> hashing, big JSON? Is every `gather` bounded and every network `await` timed out? Is every
> `create_task` handle stored? Is any sequential `await` loop hiding a 10x speedup?
