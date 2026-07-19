---
name: runbook-event-loop-lag
description: Detecting, diagnosing and fixing event-loop lag in a production async service — the instrumentation, the thresholds, the usual culprits and the remediation for each
phase: 08
lesson: 04
---

# Runbook — Event-Loop Lag

Use this when an async service (asyncio, uvloop, Node, or anything else built on a reactor)
has a **flat p50 and a blown p99**, or when you want the instrumentation in place before that
happens. The symptom this runbook exists for:

> **p50 flat. Throughput flat. p99 and max spiking. No individual endpoint looks slow.**

That shape is almost never "a slow endpoint". It is the single loop thread being occupied by
something that does not yield, and the victims are whichever requests happened to be in flight
— which is why they are spread evenly across endpoints that have nothing in common. In the
lesson's measurement, one handler calling `time.sleep(0.5)` took the p99 of 23 *uninvolved*
connections from **11.36 ms to 485.00 ms** while p50 went **0.44 → 0.33 ms**.

## Step 1 — Instrument loop lag (do this before you need it)

Loop lag is the delay between when a callback was *due* and when it actually *ran*. It measures
the mechanism, not the symptom, and it moves before user-visible latency does.

- [ ] Schedule a probe every 100 ms and record `actual_delay - expected_delay` as a **histogram**
      (not a gauge — you need the tail; see Phase 9, Lesson 5).

```python
import asyncio, time
LAG = Histogram("event_loop_lag_seconds", "Loop lag.",
                buckets=(.001, .005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5))

async def lag_probe(interval: float = 0.1):
    loop = asyncio.get_running_loop()
    expected = loop.time() + interval          # monotonic, always
    while True:
        await asyncio.sleep(interval)
        now = loop.time()
        LAG.observe(max(0.0, now - expected))
        expected = now + interval
```

- [ ] Export **p50, p99 and max** of that histogram per process. Max matters: a single 2 s stall
      is invisible in p99 at high request rates and is exactly what you are hunting.
- [ ] Label by `pid`/`worker` — with N workers behind one port, one sick worker is averaged away.
- [ ] Node equivalent: `perf_hooks.monitorEventLoopDelay()` or the same `setTimeout` probe. Do
      **not** use CPU usage as a proxy; a loop blocked in a synchronous read shows near-zero CPU.
- [ ] Turn on the runtime's own detector in **staging and CI**: `PYTHONASYNCIODEBUG=1` or
      `loop.set_debug(True)` plus `loop.slow_callback_duration = 0.05`. It logs every callback
      that ran too long, with the source location. Too expensive for production; ideal everywhere else.

## Step 2 — Thresholds

Interpret against your latency SLO, not in the abstract. Loop lag is added to *every* concurrent
request, so it is a floor under your p99.

| p99 loop lag | Reading | Action |
|---|---|---|
| < 5 ms | Healthy | None |
| 5–20 ms | Loaded, or small blocking calls | Investigate at leisure; check headroom |
| 20–100 ms | Real blocking, or CPU saturation | Ticket it — your p99 already carries this |
| 100 ms – 1 s | Serious | Page during business hours; find the call |
| > 1 s | Outage-grade | Page. Health checks and heartbeats are being missed |

- [ ] Alert on **p99 lag > 100 ms for 5 minutes**, and separately on **max lag > 1 s**.
- [ ] Compare lag against CPU. **High lag + low CPU = a blocking syscall** (waiting on something).
      **High lag + pinned CPU = too much work**, either one slow callback or genuine overload.
- [ ] Check whether lag correlates with request rate. Lag that scales with load is saturation;
      lag that spikes independently of load is a specific call path.

## Step 3 — Find the culprit

- [ ] **Read the debug-mode logs first** if you have them. They name the file and line. Most
      incidents end here.
- [ ] Otherwise sample the stack of the loop thread *while it is lagging*: `py-spy dump --pid <pid>`
      (Python) or `--nodejs` / `node --prof` for Node. A blocked loop has a stack that is not
      `select`/`epoll_wait`, and whatever is on top is your answer.
- [ ] `strace -p <pid> -c -f` for a few seconds: a healthy loop is almost entirely
      `epoll_wait`. Any other syscall dominating (`recvfrom`, `read`, `poll` on a DB socket,
      `futex`) is the blocking call.
- [ ] Bisect by deployment: correlate the first lag spike with a deploy, a feature flag, a
      traffic-mix change, or a dependency that got slower. New blocking calls arrive with deploys.

## Step 4 — The usual culprits and their fixes

- [ ] **A synchronous database driver** (`psycopg2`, `pymysql`, `sqlite3`, `redis-py` sync client)
      called from a coroutine. The single most common cause.
      → Use the async driver (`asyncpg`, `aiomysql`, `redis.asyncio`). If you cannot,
      `await loop.run_in_executor(pool, fn)` and size the pool deliberately.
- [ ] **`requests` / `urllib` instead of an async HTTP client.** A 2 s upstream timeout is a 2 s
      loop stall. → `httpx.AsyncClient` or `aiohttp`, with an explicit total timeout.
- [ ] **DNS resolution.** `socket.getaddrinfo` is blocking, so even async clients block on the
      *first* connection to a new host, and again whenever the cache expires.
      → `aiodns`/`c-ares`, a local caching resolver (`systemd-resolved`, `dnsmasq`), and a
      warmed connection pool. Watch for lag spikes at exactly your DNS TTL.
- [ ] **Disk I/O.** `open()`, `read()`, `os.stat`, logging to a slow or full volume, importing a
      module at request time. Readiness-based polling does not work on regular files — the kernel
      always reports them ready, then blocks in `read()`.
      → Thread pool, or `aiofiles`. Make logging non-blocking with a bounded queue handler.
- [ ] **Big JSON.** Parsing or serializing multi-megabyte payloads is pure CPU on the loop thread.
      → Cap request body size, stream large responses, push large parses to an executor, use a
      faster parser (`orjson`). A 4 MB parse is tens of milliseconds on every concurrent request.
- [ ] **Crypto and hashing.** `bcrypt`, `scrypt`, `argon2`, PBKDF2 are *designed* to be slow —
      often 100+ ms by policy. On the loop, that is 100 ms of lag per login.
      → Always in an executor or a dedicated process pool. Never inline. (Phase 7.)
- [ ] **Regex backtracking.** A catastrophic pattern on hostile input is unbounded CPU with no
      syscall and no I/O — invisible to every blocking-call detector.
      → Bound input length, avoid nested quantifiers, prefer `re2`-style engines, add timeouts
      where the engine supports them. Fuzz the patterns that touch user input.
- [ ] **Tight loops over large collections.** Sorting 100k rows, N+1 in-memory joins, building a
      giant response in a comprehension. → Paginate, push to the database, or chunk the work with
      an `await asyncio.sleep(0)` between slices so the loop can breathe.
- [ ] **`subprocess.run`, `os.system`, blocking `sleep`.** → `asyncio.create_subprocess_exec`,
      `await asyncio.sleep()`.
- [ ] **A stale writer registration.** A writable socket with nothing to write is ready on every
      iteration: 100% CPU that looks like legitimate load. → `remove_writer` once the buffer drains.
- [ ] **A cancelled-timer leak.** Arm-and-cancel-heavy workloads (a timeout per request on a fast
      endpoint) grow the timer heap. → Watch process memory against a flat connection count.

## Step 5 — Structural fixes

- [ ] **Run one loop per core** (N worker processes behind `SO_REUSEPORT` or a supervisor). One
      blocked worker then degrades 1/N of traffic instead of everything.
- [ ] **Move all CPU-bound work off the loop by policy**, not case by case: a documented executor
      for hashing, image work, compression and large parses.
- [ ] **Adopt uvloop** where applicable — a drop-in libuv-backed loop, same semantics, less
      per-callback overhead. It reduces baseline lag; it does not fix blocking calls.
- [ ] **Add a lint gate.** `flake8-async`, `ruff` ASYNC rules, or a custom check banning
      `requests`, `time.sleep` and sync drivers inside `async def` — the only fix that prevents
      recurrence. Keep debug mode on in CI with `slow_callback_duration = 0.05`.

## Step 6 — Verify and close

- [ ] p99 loop lag back under your threshold **and** p99 request latency down by a comparable
      amount. If lag improved but latency did not, you fixed a different problem.
- [ ] Max lag over a full day, including any batch or cron window — those are when the rare
      blocking path runs.
- [ ] Re-run the load test with the fix and record before/after p50, p99 and max in the ticket.
      p50 will barely move; that is expected and is not evidence the fix failed.
- [ ] Loop-lag alert exists, has fired at least once in staging, and routes somewhere a human reads.

## Decision shortcut

> Flat p50 + blown p99 + no slow endpoint = a blocked loop until proven otherwise. Measure loop
> lag as a histogram, alert at p99 > 100 ms and max > 1 s, and read high-lag-with-low-CPU as a
> blocking syscall and high-lag-with-pinned-CPU as too much work in one callback. The fix is
> always the same shape: make it async, or push it to an executor. Then add the lint rule, or
> you will be back.
