# Structured Concurrency: Tasks, Cancellation & Timeouts

> `asyncio.create_task()` is the `goto` of concurrency: it starts a control flow that outlives the function that started it and returns to nobody. In this lesson's measured run, ten identical fire-and-forget tasks were garbage-collected mid-flight the instant the collector ran, a request that returned a 504 to the user kept three database writes running for 352 ms after it "ended", and a coroutine that swallowed `CancelledError` turned a 150 ms timeout into 456 ms with no error anywhere. Every one of those is the same bug — a task with no parent — and one ~70-line abstraction makes all three impossible.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Coroutines & Async/Await](../05-coroutines-and-async-await/)
**Time:** ~80 minutes

## The Problem

Three incidents, three different weeks, three different teams. Same root cause.

**Incident one.** A nightly reconciliation job was kicked off from a request handler with `asyncio.create_task(reconcile_ledger())`. It raised on its second row. Nobody found out for a week — not a log line, not an alert, not a metric. The dashboards were green because the work simply stopped happening, and "work that stopped happening" produces no errors. It surfaced when finance asked why the ledger had been drifting since last Tuesday.

**Incident two.** A payment webhook was fired with a one-liner: `asyncio.create_task(send_webhook(order.id))`. The return value went nowhere. In staging it worked every time. In production it worked *about 70% of the time*, and nobody could reproduce the failures because they had no pattern — no particular merchant, no particular payload, no particular hour. The task was being **garbage-collected while it was still running**.

**Incident three.** A search endpoint fanned out to three internal services. Under load the p99 blew past the 500 ms client timeout, so the handler returned a 504 and moved on. The three fan-out calls did not. They kept holding connections, kept waiting on their own sockets, and kept writing to the database twenty seconds after the request "ended". The failure mode was not the slow response — it was that under sustained load the server accumulated **more in-flight work than it was serving**, so every retry made the box slower, and the box never recovered without a restart.

One cause under all three. `create_task` starts something with **no defined lifetime and no parent**:

- Nobody holds the result, so when it raises, the exception has nowhere to go.
- Nobody holds a reference, so the runtime is free to collect it.
- Nobody owns its lifetime, so shutdown and timeouts have no way to reach it.

The equivalent in Go is a bare `go f()`; in Java before virtual threads it was `new Thread(...).start()`; in JavaScript it is a promise you never `await` and never `.catch()`. The syntax differs; the hole is identical.

## The Concept

### The unstructured `go` statement

In 1968 Edsger Dijkstra published *Go To Statement Considered Harmful* (CACM 11(3)). His argument was not that `goto` produced wrong answers. It was that `goto` destroyed your ability to **reason locally**: with arbitrary jumps, you cannot look at a block of code and say what is true when it finishes, because control might have entered or left it from anywhere. Structured programming's fix was a rule about shape — control flow may only nest. `if`, `while`, and function call/return all have exactly one way in and one way out. That rule is what makes a function call composable: you can use a function you have never read, because whatever it does internally, it either returns or raises, and then it is *done*.

Concurrency never got that fix. `create_task`, `go`, `Thread.start()`, and `setTimeout` are all the same primitive: **start a control flow that returns to nowhere**. The caller keeps going; the new flow keeps going; the two are now unrelated. Nathaniel J. Smith made the parallel explicit in *Notes on structured concurrency, or: Go statement considered harmful* (2018), which introduced the **nursery** in the Trio library; the term **structured concurrency** itself comes from Martin Sústrik's 2016 work on libdill. The idea has since been standardised almost everywhere:

| Runtime | The construct | Since |
|---|---|---|
| Python (Trio) | `async with trio.open_nursery() as n:` | 2017 |
| Kotlin | `coroutineScope { ... }`, structured `CoroutineScope` | kotlinx.coroutines 1.0 (2018) |
| Swift | `withTaskGroup`, `async let` | Swift 5.5, SE-0304 (2021) |
| Python (stdlib) | `async with asyncio.TaskGroup() as tg:` | 3.11 (2022) |
| Java | `StructuredTaskScope` | preview from JDK 21, JEP 453 (2023), refined by JEP 480 and later |

Four independent language communities converged on the same shape within five years. That is usually a sign the shape was forced by the problem rather than chosen by taste.

### The rule

**A task must not outlive the scope that created it.** That is the whole thing. On scope exit, every child has either completed, failed, or been cancelled — there is no fourth option and no way to opt out.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="On the left, an unstructured handler returns while three tasks it started trail off past the end of its lifetime with no owner, so their exceptions are never seen, one is garbage collected, and none can be cancelled. On the right, the same three tasks are nested inside a scope whose closing brace cannot be reached until every child has completed, failed, or been cancelled.">
  <defs>
    <marker id="l06-orphan" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l06-tick" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A task with no parent has no lifetime — and nothing to report to</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="416" height="346" rx="12" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
    <rect x="448" y="44" width="416" height="346" rx="12" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    <rect x="44" y="98" width="150" height="22" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="500" y="150" width="196" height="20" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="500" y="196" width="240" height="20" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="500" y="242" width="160" height="20" rx="5" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="476" y="126" width="356" height="158" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2.4"/>
  </g>
  <g fill="#d64545" fill-opacity="0.20" stroke="#d64545" stroke-width="1.6">
    <rect x="110" y="150" width="288" height="20" rx="5"/>
    <rect x="110" y="212" width="288" height="20" rx="5"/>
    <rect x="110" y="274" width="288" height="20" rx="5"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="2" marker-end="url(#l06-orphan)">
    <path d="M398 160 L 420 160"/><path d="M398 222 L 420 222"/><path d="M398 284 L 420 284"/>
  </g>
  <path d="M194 92 L 194 372" fill="none" stroke="#3553ff" stroke-width="1.8" stroke-dasharray="6 5"/>
  <path d="M832 126 L 832 284" fill="none" stroke="#0fa07f" stroke-width="3"/>
  <g fill="none" stroke="#0fa07f" stroke-width="1.6" marker-end="url(#l06-tick)">
    <path d="M700 160 L 818 160"/><path d="M744 206 L 818 206"/><path d="M664 252 L 818 252"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="224" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#d64545">UNSTRUCTURED — asyncio.create_task()</text>
    <text x="52" y="113" font-size="9.5" font-weight="700" fill="#3553ff">handle_request()</text>
    <text x="200" y="88" font-size="9" font-weight="700" fill="#3553ff">returns here</text>
    <text x="118" y="164" font-size="9" font-weight="700">reconcile_ledger()</text>
    <text x="112" y="186" font-size="8.5" opacity="0.9">raises → nobody awaited it → no log, no alert</text>
    <text x="118" y="226" font-size="9" font-weight="700">send_webhook()</text>
    <text x="112" y="248" font-size="8.5" opacity="0.9">no reference → gc took 10 of 10 mid-flight</text>
    <text x="118" y="288" font-size="9" font-weight="700">fetch(inventory, pricing, …)</text>
    <text x="112" y="310" font-size="8.5" opacity="0.9">no cancel path → 3 DB writes 352 ms after the 504</text>
    <text x="32" y="344" font-size="9.5" font-weight="700" fill="#d64545">The caller is gone. These have no parent to raise to,</text>
    <text x="32" y="362" font-size="9.5" font-weight="700" fill="#d64545">no owner to keep them alive, no scope to cancel them.</text>
    <text x="656" y="72" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">STRUCTURED — async with Nursery() as n:</text>
    <text x="484" y="144" font-size="9" font-weight="700" opacity="0.85">the scope</text>
    <text x="508" y="164" font-size="9" font-weight="700" fill="#3553ff">n.start_soon(a)</text>
    <text x="508" y="210" font-size="9" font-weight="700" fill="#3553ff">n.start_soon(b)</text>
    <text x="508" y="256" font-size="9" font-weight="700" fill="#3553ff">n.start_soon(c)</text>
    <text x="840" y="200" font-size="9" font-weight="700" fill="#0fa07f" writing-mode="tb" letter-spacing="1">closing brace</text>
    <text x="464" y="316" font-size="9.5" font-weight="700" fill="#0fa07f">The box closes only when everything inside it is done.</text>
    <text x="464" y="338" font-size="8.5" opacity="0.9">On exit each child has completed, failed, or been cancelled.</text>
    <text x="464" y="356" font-size="8.5" opacity="0.9">One failure cancels the siblings: measured 51.7 ms, not 500 ms.</text>
    <text x="464" y="374" font-size="8.5" opacity="0.9">A timeout on the scope reached all 3 children: 0 orphaned writes.</text>
    <text x="440" y="414" font-size="11" text-anchor="middle" opacity="0.9">Structured programming made control flow nest. Structured concurrency makes concurrency nest.</text>
  </g>
</svg>
```

The payoff is **composability**, and it is worth being precise about what that means. A function that internally fans out to five services is, from the caller's point of view, just a function call. It either returns a value or raises an exception, and when control comes back the function has left nothing running. You can call it from inside a `with` block that holds a lock, from inside a transaction, from inside a request handler with a deadline — and none of those enclosing scopes need to know it used concurrency at all. Without the rule, every function that internally calls `create_task` leaks that fact into every caller forever: the caller must now somehow know what to wait for, what to cancel, and where errors will appear.

### The three failures of an unowned task

Each of the three incidents is a different mechanism. It is worth knowing all three, because the fixes people reach for usually address only one.

**Failure 1: the exception has nowhere to go.** A `Task` stores the exception its coroutine raised and hands it over when you `await` the task or call `task.exception()`. If nobody ever does, the exception sits in the object. Python's only backstop is `Task.__del__`: when the task object is finally collected with an unretrieved exception, it calls the loop's exception handler with the message `"Task exception was never retrieved"`. That is a real safety net and it is a bad one, for three reasons. It fires at **garbage-collection time**, which may be minutes later or — if the task is in a reference cycle that never gets collected, or the process exits first — never. It arrives with **no request context**, so it lands in your logs detached from the trace ID that would let you find it ([Phase 9, Lesson 3](../../09-logging-monitoring-and-observability/03-correlation-and-request-context/)). And it is a *log line at whatever level your handler chose*, not a raised exception, so no caller can react to it.

**Failure 2: the loop keeps only weak references.** This is the one that surprises people, and it is stated plainly in the `asyncio` documentation: save a reference to the result of `create_task`, because the event loop only keeps a **weak** reference to it. `asyncio.all_tasks()` is backed by a `WeakSet`. A strong reference to a running task exists only in two places: the loop's ready queue, while the task is actually scheduled to run, and whatever the task is currently suspended *on* — the future it is awaiting holds a callback that points back at the task. So a task suspended on something that is itself only reachable *through that task* forms a **reference cycle with no external root**, and the cycle collector is entitled to take it. That is exactly the shape of `await connection.response_future` where the connection object lives only in the coroutine's own frame. In the Build It, forcing `gc.collect()` at that moment took **10 out of 10** unreferenced tasks and left **10 out of 10** referenced ones alive. In production the collector runs on its own schedule, which is why the webhook fired "about 70% of the time" and why nobody could reproduce it.

**Failure 3: there is no cancellation path.** To cancel something you need a handle on it. A task nobody stored cannot be cancelled by shutdown, cannot be cancelled by a timeout, and cannot be cancelled by the request that started it. `asyncio.all_tasks()` will list it while it survives, but "cancel everything currently running" is not a substitute for "cancel the work belonging to this request" — you cannot tell those apart from a flat list. This is the failure that turns into an outage, because it converts a latency problem into an unbounded-resource problem: connections, memory, and database writes all outlive the requests that justified them.

### Cancellation is an exception, not a kill

This is the single most misunderstood mechanism in async programming, and everything downstream — timeouts, deadlines, shutdown — is built on it.

`task.cancel()` **does not stop anything**. It sets a flag and arranges for `CancelledError` to be *raised inside the coroutine at its next await point*. If the task is currently suspended on a future, that future is cancelled and the error is delivered when the loop next runs the task. If the task is running code, nothing happens until it awaits.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="A timeline showing that task.cancel called at 100 milliseconds does not stop a coroutine: the coroutine keeps spinning on the CPU with no await points, CancelledError is finally raised at its next await at 800 milliseconds, the finally block then runs its cleanup, and the exception propagates to the enclosing timeout scope as a TimeoutError.">
  <defs>
    <marker id="l06-up" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">cancel() does not stop a coroutine. It arms an exception.</text>
  <g fill="none" stroke-linejoin="round">
    <rect x="130" y="76" width="702" height="22" rx="5" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.6"/>
    <rect x="130" y="136" width="312" height="30" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.8"/>
    <rect x="442" y="136" width="312" height="30" rx="5" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.8"/>
    <rect x="754" y="136" width="78" height="30" rx="5" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.8"/>
    <rect x="208" y="178" width="546" height="16" rx="4" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="1.4"/>
  </g>
  <path d="M208 72 L 208 210" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="6 5"/>
  <path d="M754 130 L 754 176" fill="none" stroke="#d64545" stroke-width="2.4"/>
  <path d="M442 128 L 442 136" fill="none" stroke="#0fa07f" stroke-width="1.6"/>
  <path d="M828 136 L 828 102" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#l06-up)"/>
  <g fill="none" stroke="currentColor" stroke-opacity="0.45" stroke-width="1.3">
    <path d="M130 218 L 832 218"/><path d="M130 218 L 130 226"/><path d="M208 218 L 208 226"/><path d="M442 218 L 442 226"/><path d="M754 218 L 754 226"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="122" y="92" font-size="9.5" font-weight="700" text-anchor="end" fill="#3553ff">timeout scope</text>
    <text x="122" y="150" font-size="9.5" font-weight="700" text-anchor="end" fill="#e0930f">coroutine</text>
    <text x="122" y="162" font-size="8" text-anchor="end" opacity="0.7">(on the CPU)</text>
    <text x="140" y="91" font-size="9" font-weight="700" fill="#3553ff">async with asyncio.timeout(0.100):</text>
    <text x="286" y="155" font-size="9.5" font-weight="700" text-anchor="middle">spin(400 ms) — no await inside</text>
    <text x="598" y="155" font-size="9.5" font-weight="700" text-anchor="middle">spin(400 ms) — no await inside</text>
    <text x="793" y="155" font-size="9" font-weight="700" text-anchor="middle" fill="#0fa07f">finally:</text>
    <text x="481" y="190" font-size="9" font-weight="700" text-anchor="middle" fill="#d64545">the cancellation gap: 700.4 ms measured</text>
    <text x="214" y="50" font-size="10" font-weight="700" fill="#d64545">t = 100 ms  the timer fires: task.cancel()</text>
    <text x="214" y="64" font-size="8.5" opacity="0.85">it marks the task and raises nothing</text>
    <text x="830" y="50" font-size="9" font-weight="700" text-anchor="end" fill="#3553ff">the scope catches it →</text>
    <text x="830" y="64" font-size="9" font-weight="700" text-anchor="end" fill="#3553ff">raises TimeoutError to the caller</text>
    <text x="442" y="126" font-size="8.5" text-anchor="middle" fill="#0fa07f">await ①</text>
    <text x="748" y="112" font-size="9.5" font-weight="700" text-anchor="end" fill="#d64545">await ② — CancelledError raised here</text>
    <text x="748" y="126" font-size="8.5" text-anchor="end" opacity="0.85">at 800.4 ms: 8x the 100 ms deadline</text>
    <text x="130" y="238" font-size="8.5" opacity="0.7">0</text><text x="208" y="238" font-size="8.5" text-anchor="middle" opacity="0.7">100 ms</text>
    <text x="442" y="238" font-size="8.5" text-anchor="middle" opacity="0.7">400 ms</text><text x="754" y="238" font-size="8.5" text-anchor="middle" opacity="0.7">800 ms</text>
    <text x="16" y="266" font-size="9.5" font-weight="700">Why await ① did not deliver it: the timer callback was already due, but it sits behind the task's own resumption</text>
    <text x="16" y="282" font-size="9.5" font-weight="700">in the loop's ready queue — so a spinning coroutine can cost you up to two chunks, not one.</text>
    <text x="16" y="308" font-size="9.5" opacity="0.95">Same 100 ms deadline, three gap sizes:</text>
    <text x="248" y="308" font-size="9.5" font-weight="700" fill="#0fa07f">1 ms → 101.9 ms</text><text x="368" y="308" font-size="9.5" opacity="0.6">·</text>
    <text x="384" y="308" font-size="9.5" font-weight="700" fill="#e0930f">30 ms → 150.3 ms</text><text x="512" y="308" font-size="9.5" opacity="0.6">·</text>
    <text x="528" y="308" font-size="9.5" font-weight="700" fill="#d64545">400 ms → 800.4 ms</text>
    <text x="16" y="332" font-size="9.5" opacity="0.95">CancelledError inherits from BaseException (3.8+) so `except Exception:` cannot swallow it. Catch it without</text>
    <text x="16" y="348" font-size="9.5" opacity="0.95">re-raising and every timeout above you silently stops: a 150 ms contract measured 456.3 ms — 3.0x — with no error.</text>
    <text x="440" y="384" font-size="11" text-anchor="middle" opacity="0.9">Cancellation is cooperative: a coroutine that never awaits cannot be cancelled at all.</text>
  </g>
</svg>
```

Four consequences follow, and every one of them shows up in production:

- **A coroutine that never awaits cannot be cancelled at all.** Not "slowly" — at all. A tight JSON parse, an image resize, a big list comprehension: the event loop cannot run the timer callback that would call `cancel()`, because the loop is not running. Your timeout is not a timeout, it is a suggestion. Measured: with a 400 ms CPU chunk between awaits, a 100 ms deadline fired at **800.4 ms** — 8x. CPU-bound work belongs in an executor ([Thread Pools, Work Queues & Executors](../07-thread-pools-and-work-queues/)).
- **Cancellation is cooperative and therefore not instantaneous.** The gap between your awaits *is* your cancellation latency. Measured with the same 100 ms deadline: 1 ms chunks → 101.9 ms, 30 ms chunks → 150.3 ms.
- **`CancelledError` inherits from `BaseException`**, not `Exception`, since Python 3.8. This was deliberate: a broad `except Exception:` — the single most common line in production Python — must not silently eat a cancellation. Any `except BaseException:` or bare `except:` still will.
- **Catching it without re-raising breaks cancellation for everyone above you.** A scope that requested cancellation is waiting to observe it. If you absorb it and return normally, the scope concludes the body finished on its own. Measured: the same coroutine under the same `asyncio.timeout(0.15)` returned `TimeoutError` at **150.6 ms** when it re-raised, and returned a cheerful `"completed"` at **456.3 ms** — 3.0x the contract, no error, no log — when it swallowed.

The rule is unconditional: **catch `CancelledError` only to clean up, and always re-raise.**

### Cleanup on cancellation

Because cancellation is an ordinary exception travelling up the stack, ordinary `try/finally` is exactly the right tool, and `async with` (an async context manager) is the same thing with a nicer face. A connection checked out before an `await` and released in a `finally` survives cancellation correctly. One without a `finally` does not: in the Build It, cancelling three tasks mid-flight leaked **3 of 3** connections without `try/finally` and **0 of 3** with it.

The subtlety is that cleanup often has to *await* — close a socket, send an abort, roll back a transaction, ack a message. And a `finally` block that awaits **can itself be cancelled**, because a second `cancel()` (from a shutdown loop that keeps cancelling until everything is done, or from an outer scope that also expired) lands wherever the coroutine currently is, which is now inside your cleanup. In the Build It, a bare `await release()` inside a `finally` released **nothing** when a second cancel arrived.

`asyncio.shield` is the tool, and its semantics are worth stating precisely because the name misleads: **shield does not make the wait uncancellable; it makes the work survive the wait being cancelled.** `await shield(t)` still raises `CancelledError` into *your* frame, but `t` keeps running. So the correct shape gives cleanup its own task and a bounded window:

```python
async def handle(conn):
    try:
        await do_work(conn)
    finally:
        release = asyncio.create_task(conn.close())      # owns its own lifetime
        try:
            await asyncio.wait_for(asyncio.shield(release), timeout=2.0)
        except (TimeoutError, asyncio.CancelledError):
            pass          # bounded: we tried for 2 s, we are not waiting forever
```

Two traps to name. First, **an unbounded `finally` blocks shutdown**: if cleanup awaits something that never completes, your grace period is gone and the orchestrator eventually sends `SIGKILL`, which runs no cleanup at all. Always bound it. Second, **`shield` is not a licence to ignore cancellation** — shielded work still needs its own timeout, or you have just reinvented the unowned task with extra steps.

### Timeouts and deadlines

`asyncio.timeout(delay)` (Python 3.11+) is an async context manager that cancels its block when the delay expires and converts the resulting `CancelledError` into a `TimeoutError`. It replaces `asyncio.wait_for(coro, timeout)` for almost everything, and it is strictly better in two ways: it wraps a *block* rather than a single awaitable, so several calls can share one budget, and it comes with `asyncio.timeout_at(when)`, which takes an **absolute** instant on the loop's clock.

That distinction is the whole rest of this section. **A timeout is a duration you restart. A deadline is an instant you pass down.** Note also that a timeout *is implemented as a cancellation*, so it inherits every rule above: a block that never awaits will not time out, and a block that swallows `CancelledError` deletes the timeout entirely.

Now the part most codebases get wrong. A request arrives at your gateway with 500 ms of budget. The gateway calls auth, auth calls profile. If each hop applies a "sensible" 500 ms timeout of its own, the worst case is **1500 ms** of server-side work behind a client that gave up at 500 ms.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 450" width="100%" style="max-width:840px" role="img" aria-label="Two three-hop call chains compared. Above, one absolute deadline is propagated and shrinks from 500 to 379 to 204 milliseconds, so every hop stops at the same instant and no work outlives the request. Below, each hop starts a fresh 500 millisecond timer, their windows overlap past the caller's own limit, and the last hop keeps working for 241 milliseconds after the client already returned a 504.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A deadline is an instant you pass down. A timeout is a duration you restart.</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="42" width="848" height="176" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f"/>
    <rect x="16" y="232" width="848" height="176" rx="12" fill="#d64545" fill-opacity="0.09" stroke="#d64545"/>
  </g>
  <g fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f" stroke-width="1.6">
    <rect x="130" y="84" width="101" height="22" rx="4"/>
    <rect x="231" y="114" width="143" height="22" rx="4"/>
  </g>
  <rect x="374" y="144" width="176" height="22" rx="4" fill="#e0930f" fill-opacity="0.24" stroke="#e0930f" stroke-width="1.6"/>
  <path d="M550 74 L 550 176" fill="none" stroke="#d64545" stroke-width="2.4" stroke-dasharray="7 4"/>
  <g fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.4" stroke-dasharray="5 4">
    <rect x="130" y="272" width="420" height="26" rx="4"/>
    <rect x="231" y="302" width="420" height="26" rx="4"/>
    <rect x="374" y="332" width="420" height="26" rx="4"/>
  </g>
  <g fill="#3553ff" fill-opacity="0.22" stroke="#3553ff" stroke-width="1.6">
    <rect x="130" y="274" width="101" height="22" rx="4"/>
    <rect x="231" y="304" width="143" height="22" rx="4"/>
    <rect x="374" y="334" width="384" height="22" rx="4"/>
  </g>
  <rect x="556" y="334" width="202" height="22" rx="4" fill="#d64545" fill-opacity="0.34" stroke="#d64545" stroke-width="1.8"/>
  <path d="M556 264 L 556 366" fill="none" stroke="#d64545" stroke-width="2.4" stroke-dasharray="7 4"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="32" y="66" font-size="12.5" font-weight="700" fill="#0fa07f">ONE ABSOLUTE DEADLINE, PROPAGATED — 500 ms → 379 ms → 204 ms</text>
    <text x="122" y="99" font-size="9.5" font-weight="700" text-anchor="end">gateway</text>
    <text x="122" y="129" font-size="9.5" font-weight="700" text-anchor="end">auth</text>
    <text x="122" y="159" font-size="9.5" font-weight="700" text-anchor="end">profile</text>
    <text x="566" y="99" font-size="9" opacity="0.95">handed 500 ms, used 120 ms</text>
    <text x="566" y="129" font-size="9" opacity="0.95">handed 379 ms, used 170 ms</text>
    <text x="566" y="159" font-size="9" font-weight="700" fill="#e0930f">handed 204 ms, needs 450 ms → aborts</text>
    <text x="558" y="70" font-size="9" font-weight="700" fill="#d64545">the deadline — one instant, shared by all three</text>
    <text x="32" y="192" font-size="9.5" opacity="0.95">Every hop enforces the SAME instant, so the chain stops exactly when the caller's budget ends. Nothing outlives it.</text>
    <text x="32" y="209" font-size="9.5" font-weight="700" fill="#0fa07f">DeadlineExceeded at 505.8 ms · orphaned work 0.0 ms · with a fast tail hop the same chain returns ok at 446.9 ms.</text>
    <text x="32" y="256" font-size="12.5" font-weight="700" fill="#d64545">A FRESH 500 ms TIMEOUT AT EVERY HOP — 500 + 500 + 500</text>
    <text x="122" y="289" font-size="9.5" font-weight="700" text-anchor="end">gateway</text>
    <text x="122" y="319" font-size="9.5" font-weight="700" text-anchor="end">auth</text>
    <text x="122" y="349" font-size="9.5" font-weight="700" text-anchor="end">profile</text>
    <text x="240" y="290" font-size="8.5" fill="#e0930f" font-weight="700">its own fresh 500 ms window</text>
    <text x="386" y="320" font-size="8.5" fill="#e0930f" font-weight="700">its own fresh 500 ms window</text>
    <text x="382" y="349" font-size="8.5" font-weight="700" fill="#3553ff">profile: 450 ms of work</text>
    <text x="657" y="349" font-size="8.5" font-weight="700" text-anchor="middle" fill="#d64545">orphaned: 241 ms</text>
    <text x="564" y="258" font-size="9" font-weight="700" fill="#d64545">the client gives up here — 504 at 507.3 ms</text>
    <text x="32" y="382" font-size="9.5" opacity="0.95">Each hop's timer looks reasonable alone; nested they sum to 1500 ms. The client's own limit fires first, and reaches nobody.</text>
    <text x="32" y="399" font-size="9.5" font-weight="700" fill="#d64545">profile returned a perfectly good response at 748.2 ms — 241 ms of held connections and DB writes for a dead request.</text>
    <text x="440" y="436" font-size="11" text-anchor="middle" opacity="0.9">Pass the remaining budget down (grpc-timeout, X-Request-Deadline). Never hand a downstream call a fresh one.</text>
  </g>
</svg>
```

A **deadline** is absolute, and it must **propagate**. If the caller has 500 ms left, the downstream call gets *what remains*, not a fresh 500 ms. Every hop computes `remaining = deadline - now()` and enforces that. Then the whole chain stops at one instant, and — this is the property that matters — **no hop can do work that its caller will never read.**

How the instant crosses a process boundary is a small but important detail. You cannot send an absolute timestamp, because clocks on two machines disagree (distributed systems make a meal of this); you send the **remaining duration** and the receiver immediately converts it back to a local absolute instant. That is exactly what gRPC does: the `grpc-timeout` header carries a remaining duration with a unit suffix (`100m` = 100 ms, `1S` = 1 s), recomputed at every hop. HTTP has no standard equivalent, so teams use a convention — an `X-Request-Deadline`-style header, or Envoy's `x-envoy-expected-rq-timeout-ms` — plus a client library that reads it into request context and threads it into every outbound call. The pattern is called a **timeout budget**: one number, established at the edge, spent down as the request travels.

Measured in the Build It, on the same three-hop chain: fresh per-hop timeouts returned a 504 to the client at **507.3 ms** while the chain kept working until **748.2 ms** — **240.9 ms of orphaned work**, ending in a perfectly good response that nobody would ever read. The propagated deadline returned `DeadlineExceeded` at **505.8 ms** with **0.0 ms** of orphaned work. And when the tail hop was fast, the same propagated chain simply succeeded, at **446.9 ms**, inside budget.

### The timeout hierarchy

"Give it a timeout" is not one number. A single outbound HTTP call has at least four, and they are not interchangeable:

- **Connect timeout** — TCP handshake plus TLS. Should be short (a few hundred ms): a peer that cannot complete a handshake quickly is down, not slow.
- **Read / write timeout** (sometimes "socket" or "inactivity" timeout) — the maximum gap *between bytes*. This one does not bound the total: a server that dribbles one byte every second passes a 5 s read timeout forever.
- **Pool acquisition timeout** — how long you will wait for a free connection. Under saturation this is where all your latency actually is, and it is the one most often left unset.
- **Total request timeout** — the only one that bounds anything end to end, and the only one a deadline can be expressed in. If you set exactly one, set this.

Retries multiply all of it. A call with a 500 ms timeout and 3 attempts is a **1500 ms** call, and if you also add backoff it is more. So the rule from [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/) and [Retries, Backoff & Dead-Letter Queues](../../06-messaging-and-pub-sub/08-retries-backoff-and-dead-letter-queues/) gets an addendum here: **a retry must fit inside the remaining budget, or it is not a retry — it is load amplification.** Before attempt *n*, check `deadline - now()`; if the remaining time is less than a plausible attempt, fail immediately. A retry that starts with 40 ms left is guaranteed to fail *and* guaranteed to cost the downstream service a full unit of work.

### `ExceptionGroup` and `except*`

Structured concurrency makes multi-failure the normal case. Five children run; three of them fail; you have three exceptions and one place to raise them. Python's answer is PEP 654 (Python 3.11): `ExceptionGroup` wraps several exceptions into one, and `except*` matches *inside* a group.

```python
try:
    async with asyncio.TaskGroup() as tg:
        tg.create_task(charge_card())
        tg.create_task(reserve_stock())
        tg.create_task(notify_user())
except* PaymentError as eg:          # eg.exceptions: every PaymentError in the group
    for err in eg.exceptions:
        log.warning("payment failed", exc_info=err)
except* ConnectionError as eg:       # a SECOND handler can also run for the same group
    metrics.dependency_failures.inc(len(eg.exceptions))
```

Three semantics to get right. Each `except*` clause receives a **group containing only the matching exceptions**, and **more than one clause can run** for a single raised group — unlike ordinary `except`, where the first match wins. Anything unmatched propagates onward, still grouped. And `BaseExceptionGroup` is the parent type: a group containing only `Exception` subclasses is automatically an `ExceptionGroup`, while one containing a `BaseException` (such as `CancelledError`) stays a `BaseExceptionGroup` and cannot be caught by `except*` clauses naming `Exception` subclasses.

The behaviour that surprises people: **`TaskGroup` cancels its remaining children the moment the first one fails**, and it raises an `ExceptionGroup` even when only one child failed — so `except ValueError:` will not catch a `ValueError` raised inside a task group. You need `except* ValueError:`. Sibling cancellation is the right default (why keep four calls running for a response that can no longer be assembled?) but it means the group you get back usually contains the *first* failure plus whatever the cancelled siblings raised on their way out.

### Graceful shutdown

Here is where the whole model pays for itself. A deploy sends `SIGTERM`; the orchestrator will send `SIGKILL` after a grace period (Kubernetes defaults to 30 s). The correct sequence is:

1. **Stop accepting** new work — fail readiness probes, stop the listener, stop the consumer poll.
2. **Cancel the scope.**
3. **Await the children with a bounded grace period** so in-flight work can finish or roll back.
4. **Force** whatever is left, and exit.

Every step after the first requires knowing what is running. With unstructured tasks you do not have that list — `asyncio.all_tasks()` returns a bag with your workers, your health-check server, and your metrics flusher mixed together, in no particular order and with no ownership. With a scope, cancelling the scope *is* steps 2 through 4.

The measured version in the Build It: seven workers, one of which has a deliberately pathological 2-second cleanup, and a 350 ms grace period. Six workers ran their `finally` cleanly, the seventh was cancelled and abandoned, and the whole shutdown took **357.3 ms** — bounded by the grace period, not by the worst worker. That is the property you want: shutdown time is a number *you* choose, not a number your slowest handler chooses.

## Build It

Everything above is measured by [`code/structured_concurrency.py`](code/structured_concurrency.py) — standard library only. It reproduces the three bugs, builds the nursery that eliminates them, and then measures cancellation, deadlines, and shutdown.

Start with the bug nobody believes. To make garbage collection deterministic instead of lucky, the demo builds the exact reference shape that makes a running task collectable — a task suspended on a future that only the task's own frame can reach — takes a `weakref` to twenty identical tasks, keeps ten and drops ten, and then forces a collection:

```python
class Connection:
    """Stands in for an HTTP client connection: it owns the pending-response
    future. Nothing outside the task references it, which is what closes the
    cycle task -> frame -> connection -> future -> callback -> task."""
    def __init__(self) -> None:
        self.pending: asyncio.Future[None] = loop.create_future()

async def send_webhook(order: int) -> None:
    conn = Connection()
    await conn.pending                      # waiting on the response
```

Ten of those tasks are appended to a list; ten are created and the local name is deleted. Then `gc.collect()` runs and the weak references are counted. That is the whole experiment, and it is deterministic because the cycle has no external root.

The nursery itself is the centrepiece. Seventy statements, and each of the three failures is closed by exactly one of them:

```python
def start_soon(self, coro):
    if self._aborting:
        coro.close()
        raise RuntimeError("nursery is shutting down; cannot start new work")
    task = asyncio.create_task(coro)
    self._children.add(task)                 # a STRONG ref: bug (b) impossible
    task.add_done_callback(self._child_done)
    return task

def _child_done(self, task):
    self._children.discard(task)
    if task.cancelled():
        return
    exc = task.exception()                   # ALWAYS retrieved: bug (a) impossible
    if exc is not None:
        self._errors.append(exc)
        self._abort()

def _abort(self):
    if self._aborting:
        return
    self._aborting = True
    for child in self._children:
        child.cancel()                       # a cancellation path: bug (c) impossible
    if self._parent is not None and not self._exited and not self._parent.done():
        self._parent_cancelled = True
        self._parent.cancel()                # interrupt the body of the block
```

The last two lines of `_abort` are the subtle part and the reason a real `TaskGroup` is harder than it looks. If a child fails while the body of the `async with` is still running — say it is `await`ing something slow between two `start_soon` calls — cancelling the siblings is not enough; the *body* has to be interrupted too, or the scope will not reach its exit for as long as the body wants. So the nursery cancels its own parent task, and then `__aexit__` recognises that particular `CancelledError` as self-inflicted and swallows it (calling `uncancel()` to keep the task's cancellation bookkeeping balanced), rather than reporting it as a failure.

`__aexit__` is where the guarantee is actually enforced. It cannot return until `self._children` is empty:

```python
cancelled_from_outside = False
while self._children:
    pending = set(self._children)
    try:
        _, still = await asyncio.wait(pending, timeout=self._grace)
    except asyncio.CancelledError:
        cancelled_from_outside = True        # an outer timeout: forward it down
        self._abort()
        continue
    if still and self._grace is not None:
        for task in still:                   # grace expired: force and abandon
            task.cancel()
            self.abandoned.append(task)
            self._children.discard(task)
        break
if self._errors:
    raise BaseExceptionGroup("unhandled errors in nursery", errors)
```

The `except asyncio.CancelledError` arm is what makes an *outer* timeout work. `asyncio.wait` does not cancel the tasks it is waiting on when the waiter itself is cancelled — so without this, an outer `asyncio.timeout` would abandon exactly the children the scope promised to own. Catching it, cancelling every child, and looping is how cancellation propagates *down* the tree. And `BaseExceptionGroup(msg, errors)` automatically produces an `ExceptionGroup` when every error is an `Exception` subclass, which is what makes `except*` work on the result.

Finally, deadline propagation. Both chains use the identical simulator; the only difference is one argument:

```python
async def server(index: int) -> str:
    allowance = per_hop if per_hop is not None else deadline - loop.time()
    async with asyncio.timeout(allowance):
        await asyncio.sleep(work[index])
        if index + 1 < len(HOPS):
            downstream = asyncio.create_task(server(index + 1))
            return await asyncio.shield(downstream)     # a process boundary
        return "ok"
```

`asyncio.shield` here is doing something specific: it makes the simulation *honest*. Across a real network, a caller giving up does not cancel the callee — the server never learns the client hung up. Shielding the downstream task reproduces that, so the orphaned work the run reports is real orphaned work and not an artifact of everything sharing one event loop.

```bash
docker compose exec -T app python phases/08-concurrency-and-performance/06-structured-concurrency-and-cancellation/code/structured_concurrency.py
```

```console
== 1 · THE THREE FAILURES OF UNOWNED TASKS ==
 (a) an exception nobody retrieves
  fire-and-forget task done=True exception_seen_by_anyone=False
  the caller returned normally and logged nothing: True
  loop reported (only at GC time): 'Task exception was never retrieved'
                                   RuntimeError: ledger row 8812 has no matching charge
  the SAME task, awaited -> raises at the await point: RuntimeError: ledger row 8812 has no matching charge
 (b) a task nobody references
  20 identical webhook tasks: 10 stored in a list, 10 not stored
  live tasks before gc.collect() = 21, after = 11
  still alive:  stored 10/10        unstored 0/10
  ...
 (c) children nobody can cancel
  caller gave up and returned 504 after   125.5 ms
  work logged by then: 0
  work logged   351.5 ms AFTER the request ended: 3
    inventory wrote to the database at t=  371.2 ms
    pricing wrote to the database at t=  411.0 ms
    recommendations wrote to the database at t=  451.7 ms

== 2 · THE SAME THREE SCENARIOS INSIDE A NURSERY ==
 (a) failures are re-raised as a group at the block's closing brace
  the block RAISED after    51.7 ms: 2 sibling failures, none silent
    RuntimeError: ledger exploded
    RuntimeError: payouts exploded
  the slow sibling was cancelled at the first failure: log=[] (it needed 500 ms, the block took    51.8 ms)
 (b) children are strongly referenced for the life of the scope
  10 tasks started with start_soon(), gc.collect() forced: 10/10 still alive
 (c) a timeout on the scope reaches every child
  caller returned 504 after   120.6 ms
  work logged   351.7 ms AFTER the request ended: 0  (was 3)
  the timeout cancelled the SCOPE, and the scope owns the children.

== 3 · CANCELLATION IS AN EXCEPTION, NOT A KILL ==
  a 100 ms timeout over a loop that spins for `chunk` between awaits:
    chunk       requested   actual    overshoot
         1 ms      100.0 ms    101.9 ms      1.9 ms
        30 ms      100.0 ms    150.3 ms     50.3 ms
       400 ms      100.0 ms    800.4 ms    700.4 ms
 cleanup:
  no try/finally: connections still checked out after cancel = 3, released = 0
  try/finally  : connections still checked out after cancel = 0, released = 3
 swallowing CancelledError defeats every timeout above it:
  150 ms timeout, coroutine re-raises CancelledError: ->  TimeoutError after   150.6 ms
  150 ms timeout, coroutine swallows CancelledError: ->     completed after   456.3 ms
  contract silently became   456.3 ms (3.0x) and the caller was never told.
 a finally that awaits can itself be cancelled:
  cleanup with bare await        : released = []
  cleanup with await shield(task): released = ['connection returned to pool']

== 4 · DEADLINE PROPAGATION VS FRESH TIMEOUTS ==
 (a) a fresh 500 ms timeout at every hop
    hop budgets: gateway 500ms  auth 500ms  profile 500ms
    client result: 504 to the user at   507.3 ms
    downstream kept working until   748.2 ms ->   240.9 ms of orphaned work
 (b) one absolute 500 ms deadline, propagated and shrinking
    hop budgets: gateway 500ms  auth 379ms  profile 204ms
    client result: DeadlineExceeded at   505.8 ms
    downstream kept working until   505.8 ms ->     0.0 ms of orphaned work
 (c) the same propagated deadline, when the tail hop is fast (150 ms)
    hop budgets: gateway 500ms  auth 377ms  profile 206ms
    client result: ok at   446.9 ms -- inside budget

== 5 · BOUNDED GRACEFUL SHUTDOWN ==
  SIGTERM received at     0.7 ms (real signal handler: True)
  stopped accepting; cancelling the scope, grace = 350 ms
  workers that ran cleanup cleanly: 6/7  -> [0, 1, 2, 3, 4, 5]
  abandoned after the grace period : 1 (worker 99, whose cleanup needs 2000 ms)
  total shutdown time              :   357.3 ms (bounded by grace, not by the worst worker)

Total wall time:  6055.0 ms
```

**Read the numbers — sections 1, 3 and 4 are arguments, not demos.**

**Section 1 is three distinct mechanisms, not three symptoms of one.** In (a) the task is `done=True` and has an exception, yet the caller returned normally and *nothing was logged* — the loop only reported `'Task exception was never retrieved'` when `gc.collect()` finally ran `Task.__del__`. In production that delay is unbounded, and the message arrives stripped of the request context that would make it findable. In (b) the count is stark: `10/10` referenced tasks survived the collection and `0/10` unreferenced tasks did. There is no partial credit and no warning; the tasks simply cease. That `21 → 11` live-task count is the loop's own bookkeeping agreeing that ten units of committed work evaporated. In (c) the request returned a 504 at **125.5 ms** with zero work done, and then the three children wrote to the database at 371, 411 and 452 ms — **351.5 ms after the request ended.** Multiply that by your request rate during an incident and you have the third outage: a server whose in-flight work grows faster than its served work.

**Section 2 runs the identical three scenarios through the nursery.** The important detail in (a) is not that the failure was reported — it is *when*. The block raised at **51.7 ms** carrying **two** sibling failures, and the third child, which needed 500 ms, never completed: the first failure cancelled it. The scope did not wait for work whose result nobody could use. In (c), the same fan-out under the same 120 ms timeout produced **0** database writes instead of 3, because the timeout cancelled the *scope* and the scope owns the children. Compare the two `code/` fragments and note that the fan-out function's own body is unchanged. Structure, not vigilance, is what fixed it.

**Section 3 is the measurement that changes how you write async code.** Same 100 ms deadline, three different gaps between awaits: **101.9 ms**, **150.3 ms**, **800.4 ms**. The timeout did not get less accurate — the coroutine got less interruptible. Note the 400 ms row overshoots by *two* chunks rather than one: the timer callback was already due at 100 ms, but the event loop had queued it behind the task's own resumption, so the coroutine got one more full slice before the cancellation was delivered. Your worst-case cancellation latency is roughly twice your longest gap between awaits — which is the real reason "don't block the event loop" is not stylistic advice. Below that, the cleanup rows: **3 of 3** connections leaked without `try/finally`, **0 of 3** with it. And the swallow rows are the quietest catastrophe in the whole file: re-raising gave `TimeoutError` at **150.6 ms**; swallowing gave `completed` at **456.3 ms** — 3.0x over contract, reported as a *success*. Nothing in your logs, metrics, or traces distinguishes that from a slow dependency.

**Section 4 puts a number on the argument for deadlines.** Both rows are the same three services doing the same work; only the budget arithmetic differs. With fresh 500 ms timeouts, the client returned a 504 at **507.3 ms** and the chain kept running to **748.2 ms** — and note what happened at the end of it: `profile` *succeeded*, returning a perfectly good response 241 ms after the user was told the request failed. Every millisecond of that 240.9 ms held a connection, a socket, and a slot in a pool. With one propagated deadline, the budgets shrank 500 → 379 → 204 ms, `profile` was handed 204 ms for 450 ms of work and gave up immediately at the shared instant, and orphaned work was **0.0 ms**. Row (c) is the control: the same propagated chain with a fast tail hop returns `ok` at **446.9 ms**. Deadlines do not make you fail more — they make you fail *at the moment failure became certain*, and stop paying after that.

**Section 5** is the payoff in one number: **357.3 ms** to shut down seven workers, six of which completed their `finally` blocks, when the slowest worker's cleanup would have taken 2000 ms on its own. That number is set by the grace period. Without a scope you would have neither the list of children to cancel nor the bound.

## Use It

Everything you built has a stdlib counterpart in Python 3.11+. `Nursery` is `asyncio.TaskGroup`; `start_soon` is `tg.create_task`; the `while self._children` loop in `__aexit__` is `TaskGroup.__aexit__`; `BaseExceptionGroup(...)` is what `TaskGroup` raises; `asyncio.timeout_at` is your `deadline - loop.time()` arithmetic done for you.

```python
import asyncio, contextlib, signal
from dataclasses import dataclass

@dataclass
class Deadline:
    at: float                                   # absolute, on loop.time()
    def remaining(self) -> float:
        return max(0.0, self.at - asyncio.get_running_loop().time())

async def handle_search(request, conn_pool) -> dict:
    budget = request.headers.get("x-request-deadline-ms")
    loop = asyncio.get_running_loop()
    deadline = Deadline(loop.time() + (int(budget) / 1000 if budget else 0.5))

    conn = await conn_pool.acquire()
    try:
        results: dict[str, object] = {}

        async def call(name: str, coro_fn) -> None:
            # the SAME instant for every child -- never a fresh timeout
            async with asyncio.timeout_at(deadline.at):
                results[name] = await coro_fn(timeout_ms=int(deadline.remaining() * 1000))

        async with asyncio.TaskGroup() as tg:          # your Nursery
            tg.create_task(call("inventory", inventory_client.search))
            tg.create_task(call("pricing", pricing_client.quote))
            tg.create_task(call("recs", recs_client.suggest))
        return results
    except* TimeoutError as eg:                        # PEP 654
        log.warning("search partial timeout", n=len(eg.exceptions))
        raise HTTPGatewayTimeout from eg.exceptions[0]
    finally:
        # bounded, cancellation-safe cleanup
        release = asyncio.create_task(conn_pool.release(conn))
        with contextlib.suppress(TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(release), 2.0)

async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with asyncio.TaskGroup() as tg:
        tg.create_task(serve())
        tg.create_task(consume_queue())
        await stop.wait()
        raise SystemExit(0)     # leaving the block cancels and awaits both children
```

Three notes on the pieces. **`asyncio.shield`** is the stdlib version of "let the work outlive the wait" — the only correct use is bounded cleanup, as above. **`asyncio.timeout_at`** takes an instant on `loop.time()` (a monotonic clock), so it is immune to wall-clock jumps, which is exactly why deadlines cross process boundaries as *durations* and get converted locally. And **`anyio`** is worth knowing about: it implements Trio's structured-concurrency model — task groups, cancel scopes, `move_on_after`, `fail_after` — on top of either asyncio or Trio, so libraries written against it work under both. A great deal of production Python (including Starlette/FastAPI's internals and HTTPX) runs on anyio, and its **cancel scopes** are strictly more expressive than `asyncio.timeout`: you can cancel a scope explicitly rather than only on expiry, which is the `Nursery.cancel_scope()` method the Build It had to add by hand.

Production rules, in the order they will save you:

- **Never call `create_task` without either awaiting it or holding it.** Prefer a task group. When you genuinely need a background task that outlives the request — a cache warmer, a metrics flusher — own it explicitly: `background = set()`, then `t = asyncio.create_task(...); background.add(t); t.add_done_callback(background.discard)`, and attach a done-callback that *logs the exception*. A task in a set with no error handling is still bug (a); it only fixes bug (b).
- **Give every outbound call a timeout.** An untimed network call is an unbounded resource hold, and a resource you hold without bound is an outage you have not scheduled yet. Set the total request timeout even when the library defaults look reasonable — most HTTP clients default to *no* total timeout.
- **Propagate deadlines; never refresh them.** Read the incoming budget, convert to an absolute instant, and derive every downstream timeout from `deadline - now()`. If a hop is about to hand out more time than it has left, that is a bug your own code can detect and log.
- **Make retries fit the budget.** Before every attempt, check the remaining time and skip the attempt if it cannot plausibly finish. Retries plus a fresh per-attempt timeout is the exact recipe for the 748 ms chain in section 4, multiplied by your attempt count.
- **Always re-raise `CancelledError`.** Catch it only to clean up. Audit your codebase for `except BaseException` and bare `except:` — those two still swallow it, and `except Exception` protecting you is the reason nobody notices they are there.
- **Bound your shutdown grace period** and make it smaller than your orchestrator's kill timeout (`terminationGracePeriodSeconds` in Kubernetes, default 30 s). A grace period you never reach is a `SIGKILL`, which runs no `finally` blocks at all.
- **Log cancellations distinctly from failures.** A deploy cancels hundreds of in-flight requests, and if those land in your error rate as 500s, every deploy looks like an outage and your team learns to ignore the alert. Count them as their own metric — `requests_cancelled_total` next to `requests_failed_total` ([Phase 9, Lesson 5](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/)).

## Think about it

1. A background task must survive the request that started it — say, a cache refresh that takes 30 seconds. Structured concurrency says it cannot outlive its scope. What scope should own it, who cancels it at shutdown, and what happens to the guarantee "this function leaves nothing running" for the handler that triggers it?
2. Your service receives a request with 100 ms of budget remaining, and its cheapest possible path takes 80 ms. Should it start the work, or fail immediately with `DeadlineExceeded`? What does each choice do to your error rate, your latency percentiles, and the load on your dependencies during a partial outage?
3. `TaskGroup` cancels the remaining children when the first one fails. Describe a fan-out where that default is wrong, and how you would express "collect whatever succeeded, report what failed" without giving up the structural guarantee.
4. A `finally` block awaits a rollback that takes 5 seconds against a database that is currently unreachable. Your shutdown grace period is 2 seconds. Walk through what happens with, and without, `asyncio.shield`, and decide what the code should actually do.
5. You add deadline propagation to one service in a chain of five. Which failure modes does that fix, which does it not, and how would you tell from your dashboards which of the other four services is still refreshing the budget?

## Key takeaways

- **`create_task` is the `goto` of concurrency**: it starts a control flow with no parent and no defined lifetime. Three separate mechanisms follow — exceptions retrieved only on `await` (surfacing at GC time, if ever, as `'Task exception was never retrieved'`), the loop holding only **weak** references (measured: `gc.collect()` took **10 of 10** unreferenced tasks and **0 of 10** referenced ones), and no cancellation path (measured: 3 database writes landing **351.5 ms** after the request returned 504).
- **The rule is one sentence**: a task must not outlive the scope that created it, so on exit every child has completed, failed, or been cancelled. That is what makes concurrency composable — an internal fan-out becomes just a function call that returns or raises. Run through the nursery, the same fan-out raised an `ExceptionGroup` at **51.7 ms** instead of waiting 500 ms, and produced **0** orphaned writes instead of 3.
- **Cancellation is an exception delivered at the next await, not a kill.** It is cooperative and therefore not instantaneous: with a 100 ms deadline, 1 ms gaps between awaits finished at **101.9 ms** and 400 ms gaps at **800.4 ms** — 8x, because a coroutine that never awaits cannot be cancelled at all. `CancelledError` inherits from `BaseException` (3.8+) so `except Exception:` cannot eat it; catching it without re-raising turned a 150 ms contract into **456.3 ms** reported as success.
- **Clean up in `try/finally`** (3 of 3 connections leaked without it, 0 of 3 with it), and remember cleanup that awaits can itself be cancelled — give it its own task, `await asyncio.shield(...)`, and a bound. Shield does not make the wait uncancellable; it makes the work survive the wait being cancelled.
- **A timeout is a duration you restart; a deadline is an instant you propagate.** Fresh per-hop timeouts returned a 504 at **507.3 ms** while the chain worked on to **748.2 ms** — **240.9 ms of orphaned work** ending in a good response nobody would read. One propagated deadline (500 → 379 → 204 ms) gave `DeadlineExceeded` at **505.8 ms** with **0.0 ms** orphaned, and still returned `ok` at **446.9 ms** when the work fit. Carry the *remaining duration* on the wire (`grpc-timeout`), convert it to a local instant, and make every retry fit inside what is left.
- **Graceful shutdown is the payoff**: stop accepting, cancel the scope, await with a bounded grace, then force. Seven workers — one with a pathological 2000 ms cleanup — shut down in **357.3 ms** with 6 of 7 cleanups completed, because the bound is a number you choose rather than one your slowest handler chooses.

Next: [Thread Pools, Work Queues & Executors](../07-thread-pools-and-work-queues/) — where the CPU-bound work that cannot be cancelled goes, and how to give a blocking call a lifetime the event loop can actually manage.
