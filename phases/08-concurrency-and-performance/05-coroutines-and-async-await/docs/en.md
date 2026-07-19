# Coroutines & Async/Await from the Ground Up

> Ten I/O calls of 100 ms each, awaited one at a time in a loop, took **1,002.7 ms**. The identical ten coroutines handed to `asyncio.gather` took **100.6 ms** — a **9.96x** speedup with not one line changed inside the coroutine. That gap is the entire lesson: `async` buys you the *ability* to suspend, and scheduling is what actually overlaps the waiting. Then we measure the other side of the deal — one `time.sleep(0.3)` inside a coroutine dragged eight unrelated endpoints from 50.4 ms to a median of **325.8 ms**, because a coroutine that never awaits never yields.

**Type:** Build
**Languages:** Python
**Prerequisites:** [The Event Loop](../04-the-event-loop/)
**Time:** ~90 minutes

## The Problem

Lesson 4 ended in a strange place. You had a working event loop — a ready queue, a timer heap, one `select()` call watching every socket at once — and it was fast, and the code was unreadable.

Here is why. A request handler that does three things in order — read the request, query the database, write the response — is four lines when the calls block:

```python
def handle(conn):
    request = read_request(conn)          # waits
    row = db.query(request.user_id)       # waits
    conn.send(render(row))                # waits
```

On an event loop you cannot wait. Waiting is the one thing forbidden, because the thread that waits is the thread that was supposed to be serving the other 9,999 connections. So every call that *would* have waited has to be split in half: register interest, return immediately, and pass a function to be called when the answer arrives. The four lines become this:

```python
def handle(conn):
    def on_request(request):
        def on_row(row):
            def on_written(_):
                conn.close()
            loop.write(conn, render(row), on_written)
        loop.db_query(request.user_id, on_row)
    loop.read_request(conn, on_request)
```

Three sequential steps, three levels of nesting, and the order you *read* the code is now inside-out from the order it *runs*. That is annoying. What comes next is worse.

**A loop over ten items has no obvious shape at all.** You cannot write `for item in items: result = fetch(item)`, because `fetch` doesn't return a result — it takes a callback. The idiom becomes a function that calls itself from its own callback, carrying the index and the accumulated results forward by hand, and it looks nothing like a loop.

**And an exception in step three has nowhere to go.** `try/except` catches what is raised *below you on the stack*. But by the time `on_row` runs, `handle` has long since returned — its stack frame is gone, and `on_row` is being called directly by the event loop, from the top of a fresh stack. Wrap the whole of `handle` in `try/except` and it catches nothing. The traceback you get names the loop, not the request. In Lesson 4's callback server, every single step had to pass an error callback alongside its success callback, and forgetting one meant the failure vanished silently.

So you have a working machine and an unusable programming model. The state that used to live for free on the call stack — the local variables, the position in the loop, the exception handlers — now has to be written down by hand in closures and passed forward, because **the stack frame died at the first suspension point.**

What you actually want is to write the straight-line version — read, then query, then write — and have the runtime do the splitting. That is what `async`/`await` is. And the mechanism turns out to be almost embarrassingly simple: don't let the frame die.

## The Concept

### A function call is a stack frame

Start below the language. When you call a function, the runtime allocates a **stack frame**: a block holding that call's **local variables**, an **instruction pointer** saying which line is executing right now, and a **return address** saying where to resume the caller when it finishes. Calls nest, so frames stack — hence "the call stack."

A normal function's frame has exactly one lifetime rule: **it is destroyed at `return`.** That is why a local variable does not survive a call, and why `handle`'s frame was already gone by the time its callback ran.

Everything in this lesson follows from changing that one rule. If the frame is kept alive when the function stops — with its locals intact and its instruction pointer remembering the exact line — then you can come back later and continue from there. A function that can do that is a **coroutine**: a function that can pause in the middle, hand control back to whoever called it, and be resumed later exactly where it stopped.

That is the whole idea. Not a thread. Not a process. One heap-allocated frame that outlives its own suspension.

### Generators are resumable functions

Python has had exactly this since 2001, under a different name. A function containing `yield` is a **generator function**, and calling it returns a **generator object** without executing a single line of the body:

```python
def accumulator(start):
    total = start
    step = 1
    while total < 100:
        received = yield total     # suspend here, hand `total` out
        if received is not None:
            step = received        # ...and take a value back in
        total += step
    return total
```

`next(gen)` runs the body until it hits a `yield`, hands the yielded value out, and **freezes the frame right there.** `gen.gi_frame` is still a live frame object; `gen.gi_frame.f_locals` still holds `total` and `step`. Call `next(gen)` again and execution picks up on the line after the `yield` with those locals unchanged. The Build It prints exactly this: `total` goes 10, 11, 36, 61 across four resumptions, and the frame's locals are visible at every pause.

The second half is the one that matters for scheduling, and it arrived later ([PEP 342](https://peps.python.org/pep-0342/), Python 2.5): **`gen.send(value)` resumes the generator *and* makes the paused `yield` expression evaluate to `value`.** That is what turns a generator from a one-way data producer into a two-way channel. The generator says "I need something"; whoever is driving it goes and gets it; the value is injected back into the frozen frame; the generator continues as if the call had returned normally.

Read that again, because it is the entire trick: **a two-way generator can be driven by a scheduler.** The generator yields "I'm waiting on socket 7"; the scheduler parks it, runs other generators, and later sends the bytes back in.

When the generator finally runs off the end or hits `return`, it raises **`StopIteration`**, and the return value rides on the exception as `StopIteration.value`. That is not a wart — it is how a resumable function reports "done, here is the answer" through a channel designed to carry suspensions.

One piece is still missing. If the work is split across helper functions, each helper needs to suspend too, and a plain `for x in helper(): yield x` forwards the yields but silently drops `send()`, thrown exceptions, and the return value. [PEP 380](https://peps.python.org/pep-0380/) (Python 3.3) added **`yield from`**, which delegates properly: every yield from the inner generator passes straight out to the driver, every `send()` and every exception from the driver passes straight in, and the inner generator's `return` value becomes the value of the `yield from` expression. The Build It sends one value through two nested generators and gets a return value back up through both.

`yield from` is the direct ancestor of `await`. If it makes sense to you, `await` will too, because they do the same job on different protocols.

### From generator to coroutine

The history is one paragraph and it explains the syntax. Once `yield from` existed, `asyncio` (Python 3.4) was built on generators: you wrote `@asyncio.coroutine def f(): ... yield from g()`, and a scheduler drove those generators. It worked, but a generator and a coroutine looked identical, `yield` inside one meant two different things depending on context, and a forgotten `@asyncio.coroutine` was a silent bug. So [PEP 492](https://peps.python.org/pep-0492/) (Python 3.5, 2015) gave coroutines their own syntax: `async def` and `await`. **`await` behaves exactly like `yield from`, restricted to objects that implement the awaitable protocol** — because underneath, it compiles to the same delegation machinery.

With that, four objects. People confuse them constantly, and the confusion is the source of most async bugs, so define them precisely:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 890 430" width="100%" style="max-width:840px" role="img" aria-label="The asyncio object model as a chain: a coroutine function becomes a coroutine object when you call it, which runs no code; wrapping that in a Task gives something that drives it with send; the coroutine yields a Future, a placeholder for a value that does not exist yet; and the event loop completes the Future and schedules the Task to resume.">
  <defs><marker id="l05-obj-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="445" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four objects everyone confuses — what makes each, and what completes each</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="52" width="196" height="188" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="236" y="52" width="196" height="188" rx="11" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
    <rect x="456" y="52" width="196" height="188" rx="11" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
    <rect x="676" y="52" width="196" height="188" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
    <rect x="16" y="300" width="856" height="70" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.8" marker-end="url(#l05-obj-arrow)">
    <path d="M214 146 L 232 146"/>
    <path d="M434 146 L 452 146"/>
    <path d="M654 146 L 672 146"/>
    <path d="M774 244 L 774 296"/>
    <path d="M554 296 L 554 244"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="114" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">coroutine function</text>
    <text x="30" y="102" font-size="9.5">async def fetch(u):</text>
    <text x="30" y="118" font-size="9.5">    row = await db(u)</text>
    <text x="30" y="134" font-size="9.5">    return row</text>
    <text x="30" y="162" font-size="9" font-weight="700" opacity="0.75">IT IS</text>
    <text x="30" y="178" font-size="9.5" opacity="0.9">a function object with</text>
    <text x="30" y="192" font-size="9.5" opacity="0.9">CO_COROUTINE set.</text>
    <text x="30" y="214" font-size="9" font-weight="700" fill="#3553ff">MADE BY</text>
    <text x="30" y="230" font-size="9.5" opacity="0.9">the `async def` keyword</text>

    <text x="334" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#3553ff">coroutine object</text>
    <text x="250" y="102" font-size="9.5">c = fetch(42)</text>
    <text x="250" y="126" font-size="9.5" font-weight="700" fill="#d64545">runs NOTHING.</text>
    <text x="250" y="142" font-size="9.5" opacity="0.9">Zero bytes of the body</text>
    <text x="250" y="156" font-size="9.5" opacity="0.9">have executed yet.</text>
    <text x="250" y="178" font-size="9" font-weight="700" opacity="0.75">IT IS</text>
    <text x="250" y="194" font-size="9.5" opacity="0.9">a suspended frame with</text>
    <text x="250" y="208" font-size="9.5" opacity="0.9">a .send() method</text>
    <text x="250" y="230" font-size="9" font-weight="700" fill="#3553ff">MADE BY calling it</text>

    <text x="554" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#e0930f">Task</text>
    <text x="470" y="102" font-size="9.5">t = create_task(c)</text>
    <text x="470" y="126" font-size="9.5" opacity="0.9">The driver. It calls</text>
    <text x="470" y="140" font-size="9.5" opacity="0.9">c.send(value), catches</text>
    <text x="470" y="154" font-size="9.5" opacity="0.9">StopIteration, repeats.</text>
    <text x="470" y="178" font-size="9" font-weight="700" opacity="0.75">IT IS</text>
    <text x="470" y="194" font-size="9.5" opacity="0.9">a Future that owns a</text>
    <text x="470" y="208" font-size="9.5" opacity="0.9">coroutine — SCHEDULED</text>
    <text x="470" y="230" font-size="9" font-weight="700" fill="#e0930f">MADE BY create_task/gather</text>

    <text x="774" y="76" font-size="12.5" font-weight="700" text-anchor="middle" fill="#7c5cff">Future</text>
    <text x="690" y="102" font-size="9.5">f = loop.create_future()</text>
    <text x="690" y="126" font-size="9.5" opacity="0.9">A box for a value that</text>
    <text x="690" y="140" font-size="9.5" opacity="0.9">does not exist yet, plus</text>
    <text x="690" y="154" font-size="9.5" opacity="0.9">a list of done-callbacks.</text>
    <text x="690" y="178" font-size="9" font-weight="700" opacity="0.75">IT IS</text>
    <text x="690" y="194" font-size="9.5" opacity="0.9">what `await` hands DOWN</text>
    <text x="690" y="208" font-size="9.5" opacity="0.9">to the loop</text>
    <text x="690" y="230" font-size="9" font-weight="700" fill="#7c5cff">COMPLETED BY the loop</text>

    <text x="445" y="326" font-size="12.5" font-weight="700" text-anchor="middle" fill="#0fa07f">THE EVENT LOOP — ready queue + timer heap + one selector call</text>
    <text x="445" y="346" font-size="9.5" text-anchor="middle" opacity="0.9">fd is readable / timer expires  →  fut.set_result(v)  →  done-callback  →  call_soon(task.__step)  →  coro.send(v)</text>
    <text x="445" y="362" font-size="9.5" text-anchor="middle" opacity="0.9">and the suspended frame continues at the line after its `await`</text>

    <text x="762" y="272" font-size="9" opacity="0.85" text-anchor="end">the Task awaits it,</text>
    <text x="762" y="286" font-size="9" opacity="0.85" text-anchor="end">the loop completes it</text>
    <text x="542" y="272" font-size="9" opacity="0.85" text-anchor="end">the loop resumes the Task,</text>
    <text x="542" y="286" font-size="9" opacity="0.85" text-anchor="end">which send()s into the frame</text>

    <text x="445" y="404" font-size="11" text-anchor="middle" opacity="0.9">`await c` on a bare coroutine just delegates into it — sequential. `create_task(c)` hands it to the loop — concurrent.</text>
  </g>
</svg>
```

- A **coroutine function** is what `async def` defines. It is a plain function object with a flag set.
- Calling it produces a **coroutine object** and **runs none of the body**. This surprises everyone once. `fetch(42)` executes zero bytes of `fetch`; it hands you a frame that has not started.
- **`__await__`** is the protocol. An object is *awaitable* if it has an `__await__` method returning an iterator. Coroutines have one built in; that is why you can `await` another coroutine directly.
- A **Future** is a placeholder for a value that does not exist yet, plus a list of callbacks to run when it does. It has `set_result()`, `set_exception()`, `add_done_callback()`. Nothing more.
- A **Task** is a Future that wraps a coroutine and **drives** it: it calls `coro.send(...)`, catches `StopIteration` to capture the return value, and reschedules itself whenever the coroutine suspends. A Task is the only one of the four that is *scheduled on the loop*.

### What `await` actually does

This is the step most explanations skip, and it is the one that makes everything else obvious. Walk `row = await db.fetch(user_id)` in slow motion:

1. `db.fetch(user_id)` returns an awaitable. `await` delegates into it, exactly like `yield from`.
2. Somewhere at the bottom of that delegation chain, a real I/O primitive creates a **Future**, registers the socket with the loop's selector, and **yields the Future outward**. It travels up through every `await` in the chain and lands in the Task that is driving them.
3. The Task sees a Future, attaches `add_done_callback(self.__wakeup)` to it, and **returns**. The frames of your coroutine and all its callers stay parked exactly where they were, locals intact.
4. **The loop is now free.** It goes back to its ready queue and its `select()` call and runs everything else that has work to do. This is the whole win.
5. Later the kernel says socket 7 is readable. The loop reads the bytes and calls `future.set_result(row)`.
6. The Future's done-callback fires and does `loop.call_soon(task.__step, row)` — put the Task back on the ready queue.
7. On the next turn, the Task calls `coro.send(row)`. The value is injected into the parked `await` expression, `row` gets bound, and **execution continues at the very next line**, in the same frame, with the same locals.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="A coroutine's stack frame shown at three moments: running with its locals, suspended at an await with the frame and its locals still alive while the event loop runs other tasks, and resumed at the very next line with those same locals intact plus the awaited result.">
  <defs><marker id="l05-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">A suspended coroutine is a live stack frame, not a dead one</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="30" y="60" width="360" height="104" rx="10" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff"/>
    <rect x="30" y="212" width="360" height="104" rx="10" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-dasharray="7 4"/>
    <rect x="30" y="364" width="360" height="104" rx="10" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="650" y="60" width="200" height="408" rx="10" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.7" marker-end="url(#l05-arrow)">
    <path d="M394 112 L 642 112"/>
    <path d="M646 300 L 398 300"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="44" y="82" font-size="11.5" font-weight="700" fill="#3553ff">1 · RUNNING</text>
    <text x="44" y="102" font-size="10">frame handle_request</text>
    <text x="60" y="120" font-size="10" opacity="0.9">user_id = 42</text>
    <text x="60" y="136" font-size="10" opacity="0.9">row     = None</text>
    <text x="60" y="154" font-size="10" font-weight="700">ip --&gt; line 3: await db.fetch(user_id)</text>

    <text x="44" y="234" font-size="11.5" font-weight="700" fill="#e0930f">2 · SUSPENDED — and still entirely alive</text>
    <text x="44" y="254" font-size="10">frame handle_request</text>
    <text x="60" y="272" font-size="10" opacity="0.9">user_id = 42       &lt;- untouched</text>
    <text x="60" y="288" font-size="10" opacity="0.9">row     = None</text>
    <text x="60" y="306" font-size="10" font-weight="700">ip --&gt; parked ON line 3</text>

    <text x="44" y="386" font-size="11.5" font-weight="700" fill="#0fa07f">3 · RESUMED at the very next line</text>
    <text x="44" y="406" font-size="10">frame handle_request</text>
    <text x="60" y="424" font-size="10" opacity="0.9">user_id = 42       &lt;- never left</text>
    <text x="60" y="440" font-size="10" opacity="0.9">row     = &lt;Row 42&gt; &lt;- send()ed in</text>
    <text x="60" y="458" font-size="10" font-weight="700">ip --&gt; line 4: return render(row)</text>

    <text x="518" y="98" font-size="9.5" text-anchor="middle" font-weight="700">await: yield a Future</text>
    <text x="518" y="132" font-size="9.5" text-anchor="middle" opacity="0.85">control leaves the frame,</text>
    <text x="518" y="146" font-size="9.5" text-anchor="middle" opacity="0.85">the frame does not die</text>

    <text x="522" y="286" font-size="9.5" text-anchor="middle" font-weight="700">Task.__step: coro.send(row)</text>
    <text x="522" y="320" font-size="9.5" text-anchor="middle" opacity="0.85">the result is injected</text>
    <text x="522" y="334" font-size="9.5" text-anchor="middle" opacity="0.85">straight into the await</text>

    <text x="750" y="84" font-size="11.5" font-weight="700" text-anchor="middle" fill="#7c5cff">EVENT LOOP</text>
    <text x="750" y="100" font-size="9" text-anchor="middle" opacity="0.8">one thread, one core</text>
    <text x="666" y="140" font-size="9.5" opacity="0.9">while the frame is</text>
    <text x="666" y="156" font-size="9.5" opacity="0.9">parked the loop runs</text>
    <text x="666" y="172" font-size="9.5" opacity="0.9">OTHER coroutines —</text>
    <text x="666" y="188" font-size="9.5" opacity="0.9">that is the whole win</text>
    <text x="666" y="222" font-size="9.5" font-weight="700" fill="#7c5cff">then, later:</text>
    <text x="666" y="240" font-size="9.5" opacity="0.9">selector: fd 7 readable</text>
    <text x="666" y="256" font-size="9.5" opacity="0.9">fut.set_result(&lt;Row&gt;)</text>
    <text x="666" y="272" font-size="9.5" opacity="0.9">done-callback fires</text>
    <text x="666" y="288" font-size="9.5" opacity="0.9">call_soon(task.__step)</text>
    <text x="666" y="410" font-size="9.5" opacity="0.9">The loop never held</text>
    <text x="666" y="426" font-size="9.5" opacity="0.9">your locals. The frame</text>
    <text x="666" y="442" font-size="9.5" opacity="0.9">did, the whole time.</text>

    <text x="440" y="492" font-size="11" text-anchor="middle" opacity="0.9">A thread parks a whole OS stack. A coroutine parks one heap-allocated frame — which is why 10,000 of them fit.</text>
  </g>
</svg>
```

Nothing in that list is mysterious, and every piece of it existed in Lesson 4's callback loop. The difference is *where the state lives*. In the callback version you wrote `user_id` down in a closure by hand. Here it stays in the frame, because the frame never died — and the compiler wrote the closure for you.

Which leads to the sentence to memorise:

> **`await` does not mean "wait here". It means "I may be suspended at this point — go run something else."**

Reading `await` as "block until done" is the single most common misunderstanding, and it produces exactly the wrong intuition about `gather`, about locks, and about why one blocking call takes the whole service down.

### Cooperative, not preemptive

The scheduler cannot interrupt you. There is no timer that stops a coroutine mid-line and gives the CPU (Central Processing Unit) to another one — that is **preemptive** scheduling, which is what the operating system does to threads. Coroutines are **cooperative**: control transfers only at `await` points, and only because your code chose to put one there.

Two consequences, both enormous.

**(a) Between two `await`s, your code is atomic.** No other coroutine on that loop can observe an intermediate state, because no other coroutine can run at all. `counter += 1` — read, add, store — cannot be interleaved the way it can between threads. This is why async code needs dramatically fewer locks than threaded code, and it is the deep reason async is easier to reason about. (Lessons 8 and 9 measure what happens when threads do *not* have this property.) The caveat matters just as much: the atomicity ends at the first `await`. `x = await read(); x += 1; await write(x)` is a textbook race, because the loop ran other coroutines in both gaps.

**(b) A coroutine that never awaits never yields.** It holds the loop until it returns. One coroutine spending 300 ms hashing a password stalls every other coroutine on that loop for 300 ms — the same cardinal sin as Lesson 4's blocking callback, and we measure it below for coroutines.

### Nothing runs until you schedule it

A coroutine object is **inert**. It is a frame that has not started. Three things can happen to it:

```python
c = fetch(42)                  # nothing runs. c is just an object.
row = await c                  # delegate into it: runs it to completion, sequentially
t = asyncio.create_task(c)     # hand it to the loop: it now runs CONCURRENTLY
                               # (nothing at all: RuntimeWarning at garbage-collection)
```

This is the source of the two most common beginner bugs, and they look nothing alike:

- **Forgetting to `await`.** The call appears to succeed, nothing happens, and much later you get `RuntimeWarning: coroutine 'fetch' was never awaited` on stderr — if anyone is reading stderr. No exception, no failed request, just a database write that silently didn't occur.
- **`await`ing immediately inside a loop** when you meant to run things concurrently. `for u in users: await fetch(u)` is *correct code that is N times too slow*. Nothing warns you, because it is exactly what you asked for. That is the next section.

### Concurrency comes from `gather`, not from `async`

Marking a function `async` buys you nothing on its own. It makes the function *capable* of suspending. Whether anything overlaps depends entirely on how you schedule the coroutines:

```python
for i in range(10):                       # 1,002.7 ms — each await waits for THAT call
    await fake_io(i)

await asyncio.gather(*(fake_io(i) for i in range(10)))    # 100.6 ms — all ten at once
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="Two timelines over the same ten 100-millisecond I/O calls. Awaiting them one at a time in a for loop lays ten blocks end to end and takes 1026 milliseconds. Handing the same ten to asyncio.gather stacks them all at time zero and takes 100.5 milliseconds, a 10.2 times speedup.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Same ten coroutines, same 100 ms of I/O each — only the scheduling differs</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.6">
    <g fill="#e0930f" fill-opacity="0.16" stroke="#e0930f">
      <rect x="110" y="82" width="64" height="26" rx="3"/><rect x="176" y="82" width="64" height="26" rx="3"/><rect x="242" y="82" width="64" height="26" rx="3"/><rect x="308" y="82" width="64" height="26" rx="3"/><rect x="374" y="82" width="64" height="26" rx="3"/>
      <rect x="440" y="82" width="64" height="26" rx="3"/><rect x="506" y="82" width="64" height="26" rx="3"/><rect x="572" y="82" width="64" height="26" rx="3"/><rect x="638" y="82" width="64" height="26" rx="3"/><rect x="704" y="82" width="64" height="26" rx="3"/>
    </g>
    <g fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f">
      <rect x="110" y="176" width="64" height="8" rx="2"/><rect x="110" y="187" width="64" height="8" rx="2"/><rect x="110" y="198" width="64" height="8" rx="2"/><rect x="110" y="209" width="64" height="8" rx="2"/><rect x="110" y="220" width="64" height="8" rx="2"/>
      <rect x="110" y="231" width="64" height="8" rx="2"/><rect x="110" y="242" width="64" height="8" rx="2"/><rect x="110" y="253" width="64" height="8" rx="2"/><rect x="110" y="264" width="64" height="8" rx="2"/><rect x="110" y="275" width="64" height="8" rx="2"/>
    </g>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.5" stroke-opacity="0.55">
    <path d="M110 306 L 790 306"/>
    <path d="M110 306 L 110 314"/><path d="M242 306 L 242 314"/><path d="M374 306 L 374 314"/><path d="M506 306 L 506 314"/><path d="M638 306 L 638 314"/><path d="M770 306 L 770 314"/>
  </g>
  <path d="M110 66 L 787 66" fill="none" stroke="#e0930f" stroke-width="1.4" stroke-dasharray="5 4"/>
  <path d="M110 160 L 176 160" fill="none" stroke="#0fa07f" stroke-width="1.4" stroke-dasharray="5 4"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="18" y="88" font-size="10" font-weight="700" fill="#e0930f">SEQUENTIAL</text>
    <text x="18" y="103" font-size="9" opacity="0.85">for i in ...:</text>
    <text x="18" y="116" font-size="9" opacity="0.85">  await io(i)</text>
    <text x="800" y="90" font-size="12" font-weight="700" fill="#e0930f">1002.7</text>
    <text x="800" y="106" font-size="12" font-weight="700" fill="#e0930f">ms</text>
    <text x="448" y="58" font-size="10" text-anchor="middle" opacity="0.9">each await genuinely waits for THAT one call before the next starts</text>
    <text x="18" y="182" font-size="10" font-weight="700" fill="#0fa07f">CONCURRENT</text>
    <text x="18" y="197" font-size="9" opacity="0.85">await gather(</text>
    <text x="18" y="210" font-size="9" opacity="0.85">  *coros)</text>
    <text x="196" y="224" font-size="12" font-weight="700" fill="#0fa07f">100.6 ms</text>
    <text x="196" y="244" font-size="9.5" opacity="0.9">ten Tasks suspended at once;</text>
    <text x="196" y="259" font-size="9.5" opacity="0.9">the loop waits on all ten fds</text>
    <text x="196" y="274" font-size="9.5" opacity="0.9">in ONE select() call</text>
    <text x="143" y="152" font-size="9.5" text-anchor="middle" opacity="0.9">100 ms</text>
    <text x="110" y="330" font-size="9" text-anchor="middle" opacity="0.65">0</text><text x="242" y="330" font-size="9" text-anchor="middle" opacity="0.65">200 ms</text><text x="374" y="330" font-size="9" text-anchor="middle" opacity="0.65">400 ms</text><text x="506" y="330" font-size="9" text-anchor="middle" opacity="0.65">600 ms</text><text x="638" y="330" font-size="9" text-anchor="middle" opacity="0.65">800 ms</text><text x="770" y="330" font-size="9" text-anchor="middle" opacity="0.65">1000 ms</text>
    <text x="440" y="362" font-size="12" text-anchor="middle" font-weight="700">9.96x — and not one line inside the coroutine changed</text>
    <text x="440" y="386" font-size="11" text-anchor="middle" opacity="0.9">`async` buys you the ABILITY to suspend. `gather` is what actually overlaps the waiting.</text>
  </g>
</svg>
```

`gather` wraps each coroutine in a **Task** and hands all ten to the loop before awaiting any of them. Ten Tasks start, ten Tasks suspend on their Futures, and the loop makes **one** `select()` call watching all ten at once. That is why the wall time is the duration of the *longest* operation rather than the *sum* of all of them.

The sequential version is not broken — it is a correct program that is 10x too slow, and it will never raise a warning. That combination is what makes it the most expensive mistake in async code.

### Async is not parallel

One loop, one thread, one core, interleaved. **Concurrency** means several things are in flight; **parallelism** means several things are executing at the same instant. Coroutines give you the first, never the second.

Ten thousand concurrent socket reads: yes, easily, because each one is a parked frame costing a few hundred bytes while the kernel does the waiting. Ten thousand concurrent SHA-256 hashes: no. There is one thread, and CPython's **GIL** (Global Interpreter Lock — one lock that permits only one thread to execute Python bytecode at a time) means even adding threads would not help for pure-Python work. The Build It gathers four CPU-bound coroutines and measures a **1.07x** speedup: nothing, to within noise. Parallelism needs separate processes (Lesson 2) or an executor around work that genuinely releases the GIL (Lesson 7).

### The colored-function problem

`async` is **viral**, and this is a real design cost, not a stylistic complaint. `await` is only legal inside `async def`. So the moment one function deep in your stack becomes async, every caller must become async, and every caller of *those* must too, all the way up to the entry point. Functions come in two colors and the boundary is not free to cross.

The practical consequences:

- **Two ecosystems of libraries.** `requests` and `httpx.AsyncClient`; `psycopg2` and `asyncpg`; `redis` and `redis.asyncio`. Nearly every mature sync library has an async twin, and choosing async means choosing the async half of the world.
- **`asyncio.run()` belongs at the edges only** — one call, at your process entry point. It creates a loop, runs one coroutine to completion, and closes the loop. **Never nest it**: calling `asyncio.run()` from inside a coroutine raises `RuntimeError: asyncio.run() cannot be called from a running event loop`, and reaching for it is a sign you actually wanted `await` or `create_task`.
- **Two bridges, one in each direction.** To call *sync* code from async without freezing the loop: `await asyncio.to_thread(fn, *args)` (or `loop.run_in_executor(pool, fn)`), which runs `fn` on a worker thread and gives you a Future to await. To call *async* code from a plain thread that has no loop of its own: `asyncio.run_coroutine_threadsafe(coro, loop)`, which schedules onto a loop running in another thread and hands back a `concurrent.futures.Future`.
- Other runtimes deliberately refuse the split. **Go's goroutines** and **Java's virtual threads** (JDK 21) look like ordinary blocking calls; the runtime parks the lightweight thread and switches, so there is no `await` keyword and no function coloring. The trade is that you cannot see the suspension points in the source — the property that makes Python's between-`await` atomicity so easy to reason about is exactly the property Go gives up.

### The one rule that causes most async production incidents

Here it is, and it is worth more than everything above put together:

> **A blocking call inside a coroutine freezes every concurrent request on that loop.**

`requests.get(...)`. A sync database driver. `time.sleep(...)`. `bcrypt.hashpw(...)`. A 30 MB `json.loads`. A file read on a slow disk. None of these yield, so the loop cannot run anything else until they return.

The reason this is so hard to diagnose is the **symptom**: it is never "the endpoint that made the blocking call is slow." That endpoint looks fine — it does its work and returns. What you see is that **unrelated endpoints got slow**, all at once, in a pattern with no obvious cause, and the latency histogram of your entire service develops a shoulder. Health checks time out. The service looks overloaded at 5% CPU.

The Build It measures it precisely: eight coroutines that each need only 50 ms of I/O, sharing a loop with one coroutine that calls `time.sleep(0.3)`.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="Two measured timelines. In the first, one coroutine calls the blocking time.sleep for 300 milliseconds and eight unrelated coroutines that each needed only 50 milliseconds of I/O finish at 301 to 351 milliseconds. In the second, the same coroutine awaits asyncio.sleep instead and every one of the eight finishes at 51 milliseconds.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One blocking call, eight unrelated endpoints — measured</text>
  <g fill="none" stroke-linejoin="round" stroke-width="1.7">
    <rect x="150" y="66" width="465" height="24" rx="4" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/>
    <rect x="150" y="104" width="77" height="18" rx="3" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <rect x="227" y="104" width="389" height="18" rx="3" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-dasharray="5 4"/>
    <rect x="616" y="140" width="77" height="18" rx="3" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
    <rect x="150" y="140" width="465" height="18" rx="3" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-dasharray="5 4"/>

    <rect x="150" y="252" width="465" height="24" rx="4" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-dasharray="6 4"/>
    <rect x="150" y="290" width="77" height="18" rx="3" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
    <rect x="150" y="312" width="77" height="18" rx="3" fill="#0fa07f" fill-opacity="0.20" stroke="#0fa07f"/>
  </g>
  <g fill="none" stroke="#d64545" stroke-width="1.6"><path d="M616 100 L 616 128"/><path d="M694 136 L 694 164"/></g>
  <g fill="none" stroke="#0fa07f" stroke-width="1.6"><path d="M228 286 L 228 334"/></g>
  <g fill="none" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.55">
    <path d="M150 356 L 770 356"/>
    <path d="M150 356 L 150 364"/><path d="M305 356 L 305 364"/><path d="M460 356 L 460 364"/><path d="M615 356 L 615 364"/><path d="M770 356 L 770 364"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="16" y="58" font-size="11.5" font-weight="700" fill="#d64545">time.sleep(0.3) inside a coroutine</text>
    <text x="16" y="82" font-size="9">offender</text>
    <text x="382" y="83" font-size="10" text-anchor="middle" font-weight="700" fill="#d64545">THE LOOP IS FROZEN — no coroutine can be resumed</text>
    <text x="16" y="112" font-size="9">4 that</text><text x="16" y="122" font-size="9">arrived</text><text x="16" y="132" font-size="9">first</text>
    <text x="421" y="117" font-size="9.5" text-anchor="middle" opacity="0.9">I/O finished at 50 ms — but nothing can run to notice</text>
    <text x="624" y="112" font-size="10.5" font-weight="700" fill="#d64545">301 ms</text>
    <text x="16" y="152" font-size="9">4 that</text><text x="16" y="162" font-size="9">arrived</text><text x="16" y="172" font-size="9">after</text>
    <text x="382" y="153" font-size="9.5" text-anchor="middle" opacity="0.9">not even started: their first line has not run</text>
    <text x="702" y="148" font-size="10.5" font-weight="700" fill="#d64545">351 ms</text>
    <text x="16" y="196" font-size="10" font-weight="700">median 325.8 ms   max 350.9 ms</text>
    <text x="16" y="212" font-size="9.5" opacity="0.9">Every one of them asked for 50 ms of I/O. None of them called anything slow.</text>

    <text x="16" y="244" font-size="11.5" font-weight="700" fill="#0fa07f">await asyncio.sleep(0.3) — the identical 300 ms wait</text>
    <text x="16" y="268" font-size="9">offender</text>
    <text x="382" y="269" font-size="10" text-anchor="middle" font-weight="700" fill="#0fa07f">suspended: the loop is free the entire time</text>
    <text x="16" y="298" font-size="9">4 first</text>
    <text x="16" y="326" font-size="9">4 after</text>
    <text x="244" y="304" font-size="10.5" font-weight="700" fill="#0fa07f">50.4 ms — all eight</text>
    <text x="244" y="324" font-size="9.5" opacity="0.9">6.5x lower median. Same wait, same thread, same code — one keyword.</text>
    <text x="150" y="380" font-size="9" text-anchor="middle" opacity="0.65">0</text><text x="305" y="380" font-size="9" text-anchor="middle" opacity="0.65">100 ms</text><text x="460" y="380" font-size="9" text-anchor="middle" opacity="0.65">200 ms</text><text x="615" y="380" font-size="9" text-anchor="middle" opacity="0.65">300 ms</text><text x="770" y="380" font-size="9" text-anchor="middle" opacity="0.65">400 ms</text>
    <text x="440" y="412" font-size="11" text-anchor="middle" opacity="0.9">The symptom in production is never "the slow endpoint is slow" — it is that every OTHER endpoint got slow.</text>
  </g>
</svg>
```

## Build It

Two halves: build the mechanism until it stops being magic, then measure the real thing. Everything is standard library and the whole file runs in about three seconds.

**Start with the frame that survives.** `accumulator` is an ordinary generator, but we inspect `gen.gi_frame.f_locals` at every suspension to prove the frame is alive between calls, and we use `send()` to push a value back into the paused `yield` expression:

```python
def accumulator(start):
    total = start
    step = 1
    while total < 100:
        received = yield total         # suspends; `total` goes out
        if received is not None:
            step = received            # ...and the resumer's value comes in
        total += step
    return total
```

Watch the output below: `total` survives across four resumptions, and `gen.send(25)` changes `step` from 1 to 25 *without disturbing `total`*. Then `outer_level` delegates to `inner_level` with `yield from`, and one `send(14)` crosses two frames while the inner function's `return` value propagates back up through both — the exact behaviour `await` inherits.

**Then the scheduler, in about forty lines.** This is the "asyncio is not magic" moment. A ready queue, a timer heap, and a loop that resumes one coroutine at a time:

```python
class MiniLoop:
    def run(self):
        while self.ready or self.timers:
            while self.timers and self.timers[0][0] <= self.now():   # timers that are due
                _, _, due = heapq.heappop(self.timers)
                self.ready.append(due)
            if not self.ready:                     # nothing runnable: the loop idles
                wake_at, _, coro = heapq.heappop(self.timers)
                if (delay := wake_at - self.now()) > 0:
                    time.sleep(delay)
                self.ready.append(coro)
                continue
            coro = self.ready.popleft()            # run ONE coroutine until it suspends
            try:
                request = coro.send(None)
            except StopIteration:
                continue                           # done: its frame dies here
            if isinstance(request, Sleep):
                self.seq += 1
                heapq.heappush(self.timers, (self.now() + request.seconds, self.seq, coro))
            else:
                self.ready.append(coro)            # a bare yield == "let someone else run"
```

That is the same shape as Lesson 4's loop, with one difference: instead of storing a callback and its captured state, it stores a *coroutine*, and resuming it is `coro.send(None)`. Three workers driven by this thing produce visibly interleaved output, and their 270 ms of combined "I/O" finishes in 100.7 ms of wall time.

**Then drive a real `async def` by hand.** `Suspend` implements the awaitable protocol in three lines, so we can see exactly what a coroutine hands to its driver:

```python
class Suspend:
    def __await__(self):
        handed_back = yield f"<{self.tag}: suspending, please resume me later>"
        return handed_back
```

Then we call a coroutine function (nothing runs), drop it un-awaited (a `RuntimeWarning`), and step a fresh one with `send(None)`, `send("RESULT-A")`, `send("RESULT-B")` — catching `StopIteration` to read the return value, and printing `coro.cr_frame.f_locals` between steps to show the locals accumulating in a frame that never died. **That send/catch loop is all a Task does.**

**Then the three measurements.** Sequential `await` against `gather` over ten 100 ms operations; `as_completed` to show results arriving in completion order; eight coroutines sharing a loop with an offender that blocks, then yields, then offloads to a thread; and four CPU-bound coroutines gathered, to show that gathering buys nothing when there is no waiting to overlap.

The full file is [`code/coroutines.py`](code/coroutines.py). Run it:

```bash
python3 coroutines.py
```

```console
== 1 · A FUNCTION CALL IS A FRAME -- A GENERATOR'S FRAME SURVIVES ==
  calling accumulator(10) ran no code at all. Object: generator
  its frame object already exists: True, but nothing has run, so its locals are empty: {}
  next(gen)        -> yielded  10   frame locals: {total=10, step=1}
  next(gen)        -> yielded  11   frame locals: {total=11, step=1, received=None}
  gen.send(25)     -> yielded  36   frame locals: {total=36, step=25, received=25}   <- step changed, total kept
  gen.send(None)   -> yielded  61   frame locals: {total=61, step=25, received=None}

  yield from, two levels deep:
    next(top)          -> 'inner: I am suspending'      (inner's yield came straight out)
    top.send(14)       -> StopIteration(value='outer saw: inner computed 42')
    one send() crossed two frames and one return value came back up.

== 2 · A 40-LINE SCHEDULER DRIVING THREE COROUTINES CONCURRENTLY ==
    t=   0.0ms  A runs step 1
    t=   0.0ms  B runs step 1
    t=   0.0ms  C runs step 1
    t=  20.5ms  C runs step 2
    t=  30.3ms  A runs step 2
    t=  40.7ms  C runs step 3
    t=  50.3ms  B runs step 2
    t=  60.4ms  A runs step 3
    t=  60.8ms  C runs step 4
    t=  81.1ms  C DONE (got 'C-payload')
    t=  90.5ms  A DONE (got 'A-payload')
    t= 100.6ms  B DONE (got 'B-payload')
  three coroutines, one thread, total wall time 100.7ms
  A+B+C sleep for 90+100+80 = 270ms of 'I/O' -- it overlapped, so the
  wall time is the LONGEST chain, not the sum.

== 3 · A REAL `async def`, STEPPED BY HAND WITH .send(None) ==
  three_steps(1) returned a coroutine and ran NOTHING (no output above).
  dropping it un-awaited: coroutine 'three_steps' was never awaited
    [coro] step 1 running, x=21
  coro.send(None)  -> loop receives <io-1: suspending, please resume me later>
                      frame alive? locals now {x=21}
    [coro] step 2 resumed with 'RESULT-A'
  coro.send('RESULT-A') -> loop receives <io-2: suspending, please resume me later>
                      frame alive? locals now {x=21, y=42, first='RESULT-A'}
    [coro] step 3 resumed with 'RESULT-B', locals x=21 y=42
  coro.send('RESULT-B') -> StopIteration(value=63)  <- the coroutine's return
  That loop of send / catch-StopIteration IS what an asyncio Task does.

== 4 · 10 x 100ms I/O CALLS: SEQUENTIAL await VS gather ==
  sequential `await` in a for-loop :  1002.7 ms
  asyncio.gather(*coros)           :   100.6 ms
  speedup                          :    9.96x   (ideal ceiling 10.00x)
  the 10 coroutines are identical. Only the SCHEDULING changed.

  as_completed: results arrive as they finish, not in submission order
  submitted in order: ['27ms', '48ms', '69ms', '67ms', '105ms', '110ms']
    +  27.3ms  job-0(27ms)
    +  48.5ms  job-1(48ms)
    +  67.8ms  job-3(67ms)
    +  70.0ms  job-2(69ms)
    + 107.2ms  job-4(105ms)
    + 110.4ms  job-5(110ms)
  gather(..., return_exceptions=True) -> ['ok', ValueError('this coroutine failed')]

== 5 · ONE BLOCKING CALL (300ms) VS 8 UNRELATED COROUTINES ==
  time.sleep(0.3)          BLOCKING
    victim latencies (ms):   301   301   301   301   351   351   351   351
    min  300.7   median  325.8   max  350.9   (each victim only ever asked for 50 ms)
  await asyncio.sleep(0.3) YIELDING
    victim latencies (ms):    50    50    50    50    50    50    50    50
    min   50.4   median   50.4   max   50.4   (each victim only ever asked for 50 ms)
  await to_thread(sleep)   OFFLOADED
    victim latencies (ms):    51    51    51    51    52    52    52    52
    min   50.9   median   51.5   max   52.1   (each victim only ever asked for 50 ms)
  The blocking call never touched those endpoints. It froze their loop.

== 6 · ASYNC IS NOT PARALLEL: CPU-BOUND WORK ON THE LOOP ==
  4 x 1,500,000-iteration hash loop, plain sequential calls :   484.8 ms
  the same 4 wrapped in `async def` and gathered           :   454.2 ms
  speedup from asyncio.gather                              :    1.07x   (best of 3)
  Call it 1x. Four cores were available and none of them helped: there is one
  thread and no await inside cpu_work, so the four coroutines run strictly one
  after another. Parallelism needs separate processes (Lesson 2), not async.

total wall time: 5.3s
```

**Read the numbers — four of these sections are arguments, not demos.**

**Section 1** is the foundation and it is easy to skim past. Look at the locals column: `total` goes 10 → 11 → 36 → 61 across four separate calls into the same generator, and `step` changes from 1 to 25 in the middle *without* resetting `total`. There is no closure here, no object holding state, no `self`. The state is in the function's own frame, and the frame outlived four suspensions. Then `gen.send(None)` on the exhausted generator raises `StopIteration` — the frame's actual death, carrying the return value out on the exception. The `yield from` block does the same thing across two levels: `send(14)` enters `outer_level`, is forwarded down to the paused `yield` in `inner_level`, `inner_level` computes `14 * 3` and returns, and that return value becomes the value of `outer_level`'s `yield from` expression. One `send`, two frames, one value back. Replace `yield from` with `await` and you have described asyncio.

**Section 2** is the honest version of "asyncio is not magic." Three coroutines with different sleep durations, one thread, a `deque` and a `heapq`, and the interleaving is right there in the timestamps: C runs at 0, 20.5, 40.7, 60.8; A at 0, 30.3, 60.4; B at 0, 50.3. Nobody is preempted — every one of those transitions happened because a coroutine yielded a `Sleep` request. The three of them ask for **270 ms of combined I/O and finish in 100.7 ms**, because the waiting overlapped. If you understand this forty-line loop, the only things real asyncio adds are a `select()` call instead of `time.sleep`, Futures instead of a bare `Sleep` marker, cancellation, and about fifteen years of edge cases.

**Section 3 is where the abstraction closes.** `three_steps(1)` produces a coroutine object and prints nothing — the `[coro] step 1` line does not appear until the *next* section drives a different instance. Dropping it un-awaited yields `coroutine 'three_steps' was never awaited`, which is the only warning Python will ever give you for the most common async bug. Then watch the locals grow across manual sends: `{x=21}`, then `{x=21, y=42, first='RESULT-A'}`. Those are the locals of a suspended `async def` function, inspected from outside, mid-flight. And the driving code is three `send()` calls and a `try/except StopIteration`. **That is a Task.** There is nothing else in there.

**Section 4 is the headline.** Ten identical coroutines, each doing 100 ms of simulated I/O. Awaited one at a time: **1,002.7 ms**. Gathered: **100.6 ms**. That is **9.96x**, within half a percent of the theoretical ceiling of 10.00x — the remaining loss is the per-Task scheduling overhead of creating ten Tasks instead of one. Nothing inside `fake_io` changed. No extra threads, no extra cores. The only difference is that `gather` created all ten Tasks *before* awaiting any of them, so ten Futures were pending simultaneously and the loop's single `select()` call covered all ten. This is the number to carry into code review: a `for` loop with an `await` in its body over N independent operations is a program that is N times slower than it needs to be, and it will never warn you. The `as_completed` block underneath shows the other half of the deal — jobs finish in duration order (27, 48, 67, 69, 105, 110 ms), not submission order, so you can start processing the first result at 27.3 ms instead of 110.4 ms.

**Section 5 is the one that will actually page you at 3am.** Eight coroutines, each needing exactly 50 ms of I/O, sharing a loop with one coroutine that sleeps for 300 ms. When the offender uses `await asyncio.sleep(0.3)`, all eight finish at **50.4 ms** — a perfectly flat distribution, exactly what they asked for. When the offender uses the blocking `time.sleep(0.3)` instead, the eight land at **301 ms and 351 ms**, median **325.8 ms**: a **6.5x** latency inflation. Look closely at the shape, because it is diagnostic. The four coroutines that were *already suspended* on their own I/O come back at 301 ms — their 50 ms of I/O completed on schedule at 50 ms, and then they sat in the ready queue for a quarter of a second because nothing could run to resume them. The four that hadn't started yet come back at 351 ms, because their first line didn't execute until the offender returned. Not one of those eight coroutines called anything slow. They were punished for sharing a loop. And the fix costs one line: `await asyncio.to_thread(time.sleep, 0.3)` moves the blocking call onto a worker thread and restores the flat distribution — **min 50.9, median 51.5, max 52.1 ms**, within noise of the ideal.

**Section 6** kills the last piece of wishful thinking. Four CPU-bound calls run sequentially took 484.8 ms; the same four wrapped in `async def` and handed to `gather` took 454.2 ms — a **1.07x** "speedup," which is noise. Of course it is: `cpu_work` contains no `await`, so once a coroutine starts it runs to completion, and four of them run strictly one after another no matter how you schedule them. `async` is a tool for overlapping *waiting*. When there is no waiting, there is nothing to overlap, and the answer is a separate process or an executor around work that releases the GIL (Lesson 7).

It is worth putting the three numbers side by side, because together they are the whole decision. On the same class of CPU-bound work, Lesson 2 measured **1.00x for threads** (the GIL serializes the bytecode) and **2.24x for four processes** — and this section measures **1.07x for coroutines**. Async and threads fail here for *different* reasons that produce the same number: threads are prevented from running in parallel by a lock, while coroutines never even try, because nothing yields. Only the separate address space actually gets you more than one core, which is why Lesson 2's answer and this lesson's answer are the same answer.

## Use It

Everything you hand-built has a direct counterpart in `asyncio`. Here is a realistic fan-out — the shape of most async service code, using `httpx` for HTTP (HyperText Transfer Protocol) calls:

```python
import asyncio
import httpx

async def fetch_one(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> dict:
    async with sem:                                    # bound the fan-out: at most N in flight
        r = await client.get(url, timeout=5.0)         # suspends; the loop serves others
        r.raise_for_status()
        return r.json()

async def fetch_all(urls: list[str]) -> list[dict | BaseException]:
    sem = asyncio.Semaphore(20)                        # never let 10,000 tasks hit one host
    async with httpx.AsyncClient(http2=True) as client:          # async context manager
        tasks = [fetch_one(client, sem, u) for u in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)

async def stream_rows(pool):                           # async iterator: __anext__ can suspend
    async with pool.acquire() as conn:
        async for row in conn.cursor("SELECT id, email FROM users"):
            yield row

def main() -> None:
    results = asyncio.run(fetch_all(URLS))             # ONE run(), at the process edge
    ok = [r for r in results if not isinstance(r, BaseException)]
    print(f"{len(ok)}/{len(results)} succeeded")
```

Mapped back to the Build It: **`asyncio.run()`** is your `MiniLoop.run()` plus loop creation and teardown. **`create_task()`** is your `loop.spawn()`. **`gather()`** is `spawn` for a whole list, then wait for all of them. **`asyncio.sleep()`** is your `Sleep` request, and the reason it must be awaited is that yielding is the *point* of it. **A Task** is your send/catch-`StopIteration` driver loop from Section 3. `as_completed()` and `asyncio.wait(..., return_when=FIRST_COMPLETED)` give you results in completion order rather than submission order.

Three pieces the Build It only gestured at:

- **`async with` and `async for`.** An async context manager defines `__aenter__`/`__aexit__` — both coroutines — so acquiring a connection from a pool can suspend instead of blocking. An async iterator defines `__anext__`, so each step of a `for` loop can suspend, which is how you stream a large query result or a chunked HTTP response without buffering it all.
- **`asyncio.to_thread(fn, *args)`** (3.9+) and the older `loop.run_in_executor(pool, fn)`: the escape hatch for sync code, measured in Section 5. Use it for a sync driver you cannot replace, for `bcrypt`, for a large `json.loads`, for filesystem work. `run_coroutine_threadsafe(coro, loop)` is the same bridge in reverse, from a non-async thread into a running loop.
- **`uvloop`** replaces asyncio's loop implementation with one built on libuv; a one-line swap (`asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())`) that typically buys a meaningful throughput improvement on socket-heavy services. It changes the loop, not the semantics — every rule below still applies.

Five rules that survive contact with production:

- **`asyncio.run()` exactly once, at the entry point.** Never inside a library, never inside a request handler, never nested — it raises `RuntimeError` from within a running loop. If you find yourself wanting it in the middle of a program, you wanted `await` or `create_task`.
- **Never call a sync-blocking library from a coroutine.** Use the async driver — `asyncpg` or SQLAlchemy's async engine for Postgres, `httpx` for HTTP, `redis.asyncio` for Redis — or wrap the call in `asyncio.to_thread`. The cost of getting this wrong is Section 5's number: a **6.5x** median latency inflation on endpoints that did nothing wrong. Grep your async code for `requests.`, `time.sleep(`, `psycopg2`, and `open(` before every release.
- **Always bound a fan-out with a `Semaphore`.** `gather` over 10,000 URLs creates 10,000 Tasks and opens as many sockets as your connection limits allow, instantly. That is a load problem, not a concurrency problem: you will exhaust file descriptors, blow through the connection pool ([Phase 3, Lesson 14](../../03-relational-databases/14-connection-pooling-and-n-plus-1/)), and DDoS the service you depend on. A `Semaphore(20)` costs one line. Lesson 11 covers the general form of this — backpressure — and so does [Phase 6, Lesson 09](../../06-messaging-and-pub-sub/09-backpressure-lag-and-flow-control/).
- **Every `await` on the network needs a timeout.** `asyncio.timeout()` (3.11+) or `asyncio.wait_for()`. A coroutine awaiting a Future that never completes is parked forever, holding its connection, its semaphore slot, and its memory, and it will not appear in any CPU graph. Lesson 6 makes this structural.
- **Turn on debug mode in staging**: `asyncio.run(main(), debug=True)` or `PYTHONASYNCIODEBUG=1`. It logs any callback that occupies the loop for more than 100 ms (`loop.slow_callback_duration`) and reports coroutines that were never awaited. That log line is Section 5's incident, caught before it ships.

## Think about it

1. `await` and `yield from` compile to nearly the same delegation machinery, yet Python added a whole new keyword and a new object type rather than reusing generators. What breaks if a single object can be both iterated and awaited, and what class of bug does the separation prevent?
2. Between two `await`s your code is atomic, so async services need far fewer locks than threaded ones. Write a two-line coroutine that still has a race condition despite this, and explain precisely which interleaving causes it.
3. Section 5's blocking coroutine inflated everyone else's latency 6.5x. If you only had access to your service's metrics — request rate, latency percentiles, CPU, memory — what pattern would identify this as the cause rather than genuine overload, and which single metric would be most diagnostic?
4. `asyncio.to_thread` fixed the stall by moving the blocking call to a worker thread. The default executor has a bounded number of threads. What happens under sustained load when every request needs `to_thread`, and how is that failure mode different from the one you just fixed?
5. Go and Java's virtual threads avoid function coloring by having the runtime park a blocking-looking call. You lose the ability to see suspension points in the source. Given the atomicity property from the "cooperative, not preemptive" section, what specific class of bug becomes *harder* to reason about in that model — and is the trade worth it?

## Key takeaways

- A normal function's **stack frame** — its locals, its instruction pointer — is destroyed at `return`, which is why callbacks had to write state into closures by hand. A **coroutine** changes exactly one thing: the frame stays alive while suspended. The Build It prints a suspended `async def`'s locals from outside mid-flight (`{x=21, y=42, first='RESULT-A'}`), which is the whole mechanism in one line of output.
- **Generators are the mechanism**: `yield` suspends and hands a value out, **`send()` resumes and injects a value in** ([PEP 342](https://peps.python.org/pep-0342/)), and **`yield from`** forwards sends, exceptions and return values through a chain ([PEP 380](https://peps.python.org/pep-0380/)). `async def`/`await` ([PEP 492](https://peps.python.org/pep-0492/)) is that machinery with its own syntax and its own awaitable protocol. A **Task** is nothing more than a loop calling `coro.send(v)` and catching `StopIteration` — which the Build It does by hand in three lines.
- **`await` does not mean "wait here" — it means "I may be suspended here, run something else."** Concurrency comes from *scheduling*, not from the keyword: the same ten 100 ms operations took **1,002.7 ms** awaited in a `for` loop and **100.6 ms** through `asyncio.gather` — a **9.96x** difference with no change inside the coroutine, and no warning on the slow version.
- Coroutines are **cooperative, not preemptive**. Between two `await`s nothing else runs, which is why async needs far fewer locks than threads — and why a coroutine that never awaits freezes everything. One `time.sleep(0.3)` dragged eight unrelated 50 ms coroutines to a median of **325.8 ms** (max 350.9) versus **50.4 ms** when the same wait was `await`ed: a **6.5x** inflation on endpoints that called nothing slow. `asyncio.to_thread` recovered it to a median of **51.5 ms**.
- **Async is concurrency, never parallelism.** One thread, one core, interleaved at `await` points. Four CPU-bound coroutines through `gather` measured **1.07x** — nothing. Ten thousand concurrent socket reads are easy; ten thousand hashes need processes (Lesson 2) or an executor (Lesson 7).
- **`async` is viral**: it propagates up the entire call chain, splitting libraries into two ecosystems. Keep `asyncio.run()` at the process edge and never nest it, cross the boundary deliberately with `to_thread` / `run_coroutine_threadsafe`, bound every fan-out with a `Semaphore`, and put a timeout on every network `await`.

Next: [Structured Concurrency: Tasks, Cancellation & Timeouts](../06-structured-concurrency-and-cancellation/) — what happens to the Tasks you started when one of them fails, how cancellation actually propagates into a suspended frame, and why fire-and-forget tasks disappear without a trace.
