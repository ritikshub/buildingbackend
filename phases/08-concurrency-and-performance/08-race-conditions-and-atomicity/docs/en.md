# Race Conditions, Atomicity & Critical Sections

> Eight threads increment a shared counter 100,000 times each. The answer is 800,000. Run it in this lesson and you get 214,734. Run it twenty more times and you get twenty distinct answers between 173,818 and 258,773 — not one of them correct, and not one exception raised. The same shape is a double-charged card and an oversold last seat. This lesson is about why that happens, what "atomic" actually means, and why the fix comes from finding the invariant rather than from testing until it stops.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/), [Thread Pools & Work Queues](../07-thread-pools-and-work-queues/)
**Time:** ~80 minutes

## The Problem

Here is a program a beginner could write on their second day of threading. A counter starts at zero. Eight threads each add one to it, a hundred thousand times. Then you print it.

```python
counter = 0

def work():
    global counter
    for _ in range(100_000):
        counter += 1

threads = [threading.Thread(target=work) for _ in range(8)]
for t in threads: t.start()
for t in threads: t.join()
print(counter)          # 800000, obviously
```

Eight hundred thousand increments happened. So the answer is 800,000. There is no other answer. Except that when you run the real version in this lesson's Build It, the number that comes out is **214,734**. Twenty more runs of identical code produce **twenty distinct answers and zero correct ones**, ranging from 173,818 to 258,773 — a spread of 84,955.

Sit with what did *not* happen. Nothing crashed. No exception propagated. Nothing was logged at `WARNING`. No thread died. Every one of those 800,000 increments executed, in full, without error. The program did exactly what you told it to and produced a number that is wrong by 73%, then returned it to whoever asked, with total confidence.

Now make it expensive, because in a backend that counter is never a counter:

- `balance -= amount` — and the customer is charged twice for one order, or the balance goes negative.
- `seats_left -= 1` — and two people are holding boarding passes for seat 14A.
- `coupon.uses += 1` — and a single-use 40%-off code is redeemed six hundred times in the four seconds after it is posted to a deals forum.
- `if not exists(username): create(username)` — and you have two rows with the same username, in a table where the rest of your code assumes there is one.

And now the property that makes this the hardest class of bug in backend engineering: **it will not reproduce on your laptop.** It needs two threads to be inside a few-instruction window at the same instant, which needs load. Attach a debugger and it goes away, because the debugger changes the schedule. Add a `print` to find it and it goes away, because the print changes the schedule. Your test suite passes. Your staging environment passes. It appears the first Friday you get real traffic, as a support ticket that says "my card was charged twice" and no stack trace anywhere. "I couldn't reproduce it" is not evidence of anything.

This lesson is about earning the ability to find these by reading code, because reading code is the only method that works.

## The Concept

### `counter += 1` is three operations

The line `counter += 1` looks like one thing because it is one line of source. The machine does not run source. Ask CPython what it actually emits — `dis` is the standard library's disassembler, which prints the bytecode instructions a function compiles to:

```python
>>> import dis
>>> def increment():
...     global counter
...     counter += 1
>>> dis.dis(increment)
  2   LOAD_GLOBAL     0 (counter)     # read the current value onto the stack
      LOAD_CONST      1 (1)
      BINARY_OP      13 (+=)          # add — in this thread's own frame
      STORE_GLOBAL    0 (counter)     # write the result back
```

Three operations that matter: **load**, **add**, **store**. Between the load and the store, the value lives in *this thread's* private working space. The shared variable still holds the old number, and nothing about it says "someone is in the middle of updating me."

So consider the schedule below. It is not exotic; it is any interleaving in which two threads load before either stores.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 430" width="100%" style="max-width:840px" role="img" aria-label="A six-step interleaving of two threads incrementing a shared counter. Thread A loads zero, thread B loads zero, both add one in their own frames, thread A stores one, then thread B stores one on top of it. Two increments happened and the counter ends at one instead of two, with no error raised.">
  <defs><marker id="l08-arr" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Two increments, one result: where the update is lost</text>
  <g fill="none" stroke-width="2" stroke-linejoin="round"><rect x="86" y="44" width="180" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="330" y="44" width="90" height="28" rx="8" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f"/><rect x="486" y="44" width="180" height="28" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/></g>
  <g text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor"><text x="176" y="63">Thread A</text><text x="375" y="63">counter</text><text x="576" y="63">Thread B</text></g>
  <text x="690" y="63" font-size="9.5" font-weight="700" fill="currentColor" opacity="0.65">what just happened</text>
  <g fill="none" stroke-width="1.8" stroke-linejoin="round"><rect x="86" y="91"  width="180" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="486" y="137" width="180" height="26" rx="7" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="86" y="183" width="180" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="486" y="229" width="180" height="26" rx="7" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="86" y="275" width="180" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="486" y="321" width="180" height="26" rx="7" fill="#d64545" fill-opacity="0.16" stroke="#d64545"/></g>
  <g fill="none" stroke="#7f7f7f" stroke-width="1.5"><rect x="330" y="91" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/><rect x="330" y="137" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/><rect x="330" y="183" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/><rect x="330" y="229" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/><rect x="330" y="275" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/><rect x="330" y="321" width="90" height="26" rx="7" fill="#7f7f7f" fill-opacity="0.08"/></g>
  <g fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l08-arr)"><line x1="326" y1="104" x2="274" y2="104"/><line x1="424" y1="150" x2="478" y2="150"/><line x1="270" y1="288" x2="322" y2="288"/><line x1="482" y1="334" x2="428" y2="334"/></g>
  <g font-size="10.5" text-anchor="middle" fill="currentColor"><text x="176" y="108">LOAD  -&gt;  0</text><text x="176" y="200">0 + 1 = 1</text><text x="176" y="292">STORE 1</text><text x="576" y="154">LOAD  -&gt;  0</text><text x="576" y="246">0 + 1 = 1</text><text x="576" y="338">STORE 1</text><text x="375" y="108">0</text><text x="375" y="154">0</text><text x="375" y="200">0</text><text x="375" y="246">0</text><text x="375" y="292">1</text><text x="375" y="338" font-weight="700" fill="#d64545">1</text></g>
  <g font-size="9.5" fill="currentColor" opacity="0.6"><text x="24" y="108">t1</text><text x="24" y="154">t2</text><text x="24" y="200">t3</text><text x="24" y="246">t4</text><text x="24" y="292">t5</text><text x="24" y="338">t6</text></g>
  <g font-size="9" fill="currentColor"><text x="690" y="108" opacity="0.85">A is holding 0</text><text x="690" y="147" font-weight="700" fill="#e0930f">BOTH threads hold 0.</text><text x="690" y="160" font-weight="700" fill="#e0930f">The loss is already certain.</text><text x="690" y="200" opacity="0.85">A adds inside its own frame</text><text x="690" y="246" opacity="0.85">B adds inside its own frame</text><text x="690" y="292" opacity="0.85">memory: 0 -&gt; 1</text><text x="690" y="331" font-weight="700" fill="#d64545">B writes 1 over A's 1.</text><text x="690" y="344" font-weight="700" fill="#d64545">A's increment is gone.</text></g>
  <rect x="86" y="366" width="580" height="30" rx="9" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="2"/><text x="376" y="385" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">counter == 1 · expected 2 · no exception, no log, no crash</text><text x="440" y="418" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The window is between LOAD and STORE. Any schedule where two threads load the same value loses one increment.</text></g>
</svg>
```

Look at **t2**. That is the instant the bug becomes inevitable — long before anything visibly goes wrong. Both threads now hold the value `0`, and both are going to write `1`. Steps t3 through t6 are just the paperwork. This is worth internalising, because it is how you will read code later: the damage is done at the *second load*, not at the second store.

### Atomicity, defined properly

An operation is **atomic with respect to other threads** if no other thread can ever observe it half-done. The word comes from the Greek for "indivisible": from the outside, it either has not happened or it has completely happened, and there is no third state anyone can see.

Three things atomicity is *not*, and each one is a mistake people actually make:

- **It is not about speed.** A slow operation can be atomic; a single fast machine instruction can fail to be. Duration and indivisibility are unrelated properties.
- **It is not about being one line of source.** `counter += 1` is one line and three operations. `balance = balance - amount` is one line and three operations. Source-level compactness tells you nothing.
- **It is not a property of the operation alone.** It is a property of the operation *relative to a set of observers*. `x = y` is atomic with respect to other threads in your process and is emphatically not atomic with respect to another process reading the same database row.

The only question that matters is: **which intermediate states can someone else see?** If the answer is "none", the operation is atomic. If the answer is "the state where the money has left A but not yet arrived at B", it isn't — and you now know exactly what window you have to close.

### The lost update

The failure in the diagram has a name that predates threads: the **lost update**. It is the canonical read-modify-write failure, and it appears wherever two actors read a value, compute a new one from it, and write it back:

1. Both read the same current value.
2. Both compute a new value from it, in isolation.
3. Both write. The second write silently erases the first.

Note what "silently" means here: the second writer is not doing anything wrong. It has no way to know that the value it read is now stale, because a plain variable has no memory of who read it. That is exactly why the database-world fix for this at the row level is a **version number** — it gives the value a way to notice.

The important and unintuitive property is the probability. It is a function of **how long the window between load and store is**, and of nothing you control in a test. Widen the window and the loss rate goes to 100%. Narrow it and the loss rate goes to something like one in ten thousand — which, at 3,000 requests per second, is one corrupted record every three seconds in production and zero in a ten-second test run. The Build It measures this directly by varying the window and holding everything else constant.

### Check-then-act, or TOCTOU

The second great family looks nothing like arithmetic, which is why it survives code review. It looks like ordinary business logic:

```python
if balance >= amount:            # the check
    balance -= amount            # the act

if key not in cache:             # the check
    cache[key] = fetch(key)      # the act

if not user_exists(username):    # the check
    create_user(username)        # the act

if not os.path.exists(path):     # the check
    open(path, "w")              # the act
```

Every one of these is a **TOCTOU** bug — **Time Of Check to Time Of Use**. You establish a fact, then you act on that fact. In between, the fact can stop being true, because between the two statements the world is free to move. The `if` did not lock anything. It read a value and forgot about it.

This family is worse than the lost update in one specific way: the code reads as intent. `if balance >= amount` looks like it is *preventing* an overdraft. It isn't. It is asking a question whose answer expires immediately.

And here is what makes it worth naming rather than just fixing: **it is the same bug at every scale.**

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="The same time-of-check-to-time-of-use window drawn at three scales: between two threads in one process, between two database sessions, and between two services over the network. In each case a check is followed by a gap in which another actor writes, and then the act runs on a fact that is no longer true. Each row lists the fix at that scale: a lock, a database constraint or row lock, and a compare-and-set on a version.">
  <defs><marker id="l08-up" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker></defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One pattern, three scales: the check was true, then it wasn't</text>
  <g font-size="9" fill="currentColor" opacity="0.6" text-anchor="middle"><text x="230" y="54">TIME OF CHECK</text><text x="374" y="54">the gap</text><text x="518" y="54">TIME OF USE</text></g>
  <g fill="none" stroke-width="2" stroke-linejoin="round"><rect x="180" y="62"  width="100" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="284" y="62"  width="180" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="468" y="62"  width="100" height="28" rx="8" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="180" y="172" width="100" height="28" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="284" y="172" width="180" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="468" y="172" width="100" height="28" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="180" y="282" width="100" height="28" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/><rect x="284" y="282" width="180" height="28" rx="8" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/><rect x="468" y="282" width="100" height="28" rx="8" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/></g>
  <g font-size="9.5" text-anchor="middle" fill="currentColor"><text x="230" y="81">seats &gt; 0 ?</text><text x="374" y="81" font-weight="700" fill="#e0930f">world can change</text><text x="518" y="81">seats -= 1</text><text x="230" y="191">SELECT seats</text><text x="374" y="191" font-weight="700" fill="#e0930f">world can change</text><text x="518" y="191">UPDATE seats</text><text x="230" y="301">GET /seats</text><text x="374" y="301" font-weight="700" fill="#e0930f">world can change</text><text x="518" y="301">POST /reserve</text></g>
  <g fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l08-up)"><path d="M374 128 L 374 96"/><path d="M374 238 L 374 206"/><path d="M374 348 L 374 316"/></g>
  <g font-size="9" text-anchor="middle" fill="#d64545" font-weight="700"><text x="374" y="142">another thread takes the seat</text><text x="374" y="252">another session commits</text><text x="374" y="362">another service reserves it</text></g>
  <g font-size="11" font-weight="700" fill="currentColor"><text x="16" y="81" fill="#3553ff">IN ONE PROCESS</text><text x="16" y="191" fill="#0fa07f">IN A DATABASE</text><text x="16" y="301" fill="#7c5cff">ACROSS SERVICES</text></g>
  <g font-size="8.5" fill="currentColor" opacity="0.7"><text x="16" y="96">two threads</text><text x="16" y="206">two sessions</text><text x="16" y="316">two callers</text></g>
  <g font-size="8.5" fill="currentColor"><text x="592" y="66" font-weight="700" opacity="0.65">THE FIX AT THIS SCALE</text><text x="592" y="82" font-weight="700" fill="#3553ff">one Lock around check + act</text><text x="592" y="96" opacity="0.8">or a queue, so nothing is shared</text><text x="592" y="192" font-weight="700" fill="#0fa07f">UNIQUE constraint · ON CONFLICT</text><text x="592" y="206" opacity="0.8">SELECT ... FOR UPDATE (pessimistic)</text><text x="592" y="220" opacity="0.8">UPDATE ... WHERE version = $1</text><text x="592" y="302" font-weight="700" fill="#7c5cff">compare-and-set on a version</text><text x="592" y="316" opacity="0.8">Redis SET NX · INCR · idempotency key</text><text x="592" y="330" opacity="0.8">reserve first, confirm second</text></g>
  <text x="440" y="390" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The fix is never "check harder". It is to make the check and the act one indivisible step.</text></g>
</svg>
```

In one process the gap is microseconds and the fix is a lock. In a database the gap is however long your transaction takes, and the fix is a **transaction** with the right isolation level, a **`UNIQUE` constraint**, or `SELECT ... FOR UPDATE` — exactly the machinery of [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/) and [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/), where this same failure is called a *lost update* or *write skew*. Across services the gap is a network round trip, and the fix is compare-and-set on a version number, or an idempotency key — distributed-systems material.

Learning it once at the thread level means you recognise it in a SQL transaction and in a distributed protocol without relearning anything. It is one pattern.

### A race condition is a broken invariant, not a timing bug

Here is the reframing that turns race debugging from guesswork into analysis, and it is the most valuable idea in this lesson.

Calling these "timing bugs" suggests the cure is timing — retry, sleep, tune. It isn't, and that framing is why people flail. Instead:

> Your data has an **invariant**: a statement that is supposed to be true at all times. "The sum of the two accounts is constant." "Every reserved seat has exactly one owner." "`count` equals the number of items in the list." Your code temporarily makes that invariant **false** while it updates things. A race condition is another thread observing — or writing during — that window.

Concurrency does not *cause* the bug. The window was always there, in single-threaded code too; you just had no observer. Concurrency **exposes** it.

This gives you a mechanical procedure, which is the whole reason it matters:

1. **Name the invariant** in one sentence about the data. If you cannot state it, you cannot protect it, and that is itself the finding.
2. **Find the window** where it is false — from the first write that breaks it to the last write that restores it.
3. **Make the window unobservable**, by excluding other threads from it or by not having a window at all.

The Build It demonstrates the sharpest form of this. A single writer thread moves $1 between two accounts, 60,000 times. One writer means no update can possibly be lost — and indeed, the final total is exactly right, to the cent. But an auditor thread that simply sums the two balances sees a wrong total in **24.50%** of its samples. Nothing was lost. Something was *observed mid-flight*. Every report, balance check, nightly reconciliation and CSV export you have ever written is that auditor.

### The critical section

The **critical section** is the region of code during which the invariant is temporarily false — the window, expressed as code. Protecting it means guaranteeing that at most one thread is inside it at a time (a property called **mutual exclusion**), so the false state is never observable.

Three rules, and each one has a specific bug attached to it:

- **It must cover the whole read-modify-write.** Not the write. Not the "risky-looking" line. From the read whose value you are about to depend on, through the write that restores the invariant. Locking only the mutation is the single most common real bug in this area, because it *feels* like you locked the dangerous part.
- **As short as possible, but no shorter.** Every instruction inside is serialised across all threads, so a long critical section throws away your concurrency (Lesson 9 measures exactly this). But shortening it past the invariant's boundary does not make it faster — it makes it wrong, and wrong is not a point on the performance curve.
- **Never do I/O or call unknown code inside it.** A network call inside a lock holds it for a hundred milliseconds and turns a lock into a queue. Calling a callback, a plugin, or an overridden method inside a lock means you are holding a lock across code you have not read, which is how you acquire two locks in an order you did not choose — the deadlock of Lesson 10.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 410" width="100%" style="max-width:840px" role="img" aria-label="Two panels comparing lock scope over a read-modify-write. In the correct panel the lock spans read, modify and write, so the whole interval in which the invariant is false is protected. In the buggy panel the lock covers only the write, leaving the interval between the read and the write unprotected, which is where another thread reads a value that is about to become stale.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
  <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The critical section is the interval where the invariant is false</text><rect x="16" y="44" width="848" height="152" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="32" y="68" font-size="11.5" font-weight="700" fill="#0fa07f">CORRECT · the lock spans the whole read-modify-write</text><rect x="200" y="94" width="400" height="46" rx="8" fill="none" stroke="#0fa07f" stroke-width="1.8" stroke-dasharray="6 4"/><text x="204" y="90" font-size="8.5" font-weight="700" fill="#0fa07f">lock held</text>
  <g fill="none" stroke-width="1.8" stroke-linejoin="round"><rect x="210" y="104" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="340" y="104" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="470" y="104" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/></g>
  <g font-size="10" text-anchor="middle" fill="currentColor"><text x="270" y="121">READ</text><text x="400" y="121">MODIFY</text><text x="530" y="121">WRITE</text></g>
  <text x="612" y="121" font-size="9" fill="currentColor" opacity="0.5">other work · lock released</text>
  <g stroke-width="1.5"><rect x="200" y="156" width="130" height="16" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="330" y="156" width="260" height="16" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/><rect x="590" y="156" width="250" height="16" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/></g>
  <g font-size="8.5" text-anchor="middle" font-weight="700" fill="currentColor"><text x="265" y="168">INVARIANT TRUE</text><text x="460" y="168">FALSE</text><text x="715" y="168">INVARIANT TRUE</text></g>
  <text x="32" y="188" font-size="9.5" fill="currentColor" opacity="0.9">The false interval is entirely inside the lock, so no other thread can ever observe it.</text><rect x="16" y="212" width="848" height="160" rx="12" fill="#d64545" fill-opacity="0.10" stroke="#d64545" stroke-width="2"/><text x="32" y="236" font-size="11.5" font-weight="700" fill="#d64545">THE COMMON BUG · the lock covers only the write</text><rect x="460" y="262" width="140" height="46" rx="8" fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="6 4"/><text x="464" y="258" font-size="8.5" font-weight="700" fill="#d64545">lock held</text>
  <g fill="none" stroke-width="1.8" stroke-linejoin="round"><rect x="210" y="272" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="340" y="272" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/><rect x="470" y="272" width="120" height="26" rx="7" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/></g>
  <g font-size="10" text-anchor="middle" fill="currentColor"><text x="270" y="289">READ</text><text x="400" y="289">MODIFY</text><text x="530" y="289">WRITE</text></g>
  <text x="397" y="320" font-size="9" text-anchor="middle" font-weight="700" fill="#e0930f">this much of the window sticks out</text>
  <g stroke-width="1.5"><rect x="200" y="330" width="130" height="16" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/><rect x="330" y="330" width="135" height="16" fill="#e0930f" fill-opacity="0.30" stroke="#e0930f"/><rect x="465" y="330" width="125" height="16" fill="#d64545" fill-opacity="0.20" stroke="#d64545"/><rect x="590" y="330" width="250" height="16" fill="#0fa07f" fill-opacity="0.22" stroke="#0fa07f"/></g>
  <g font-size="8.5" text-anchor="middle" font-weight="700" fill="currentColor"><text x="265" y="342">INVARIANT TRUE</text><text x="397" y="342">FALSE · UNPROTECTED</text><text x="527" y="342">FALSE</text><text x="715" y="342">TRUE</text></g>
  <text x="32" y="364" font-size="9.5" fill="currentColor" opacity="0.9">Every field access is locked and the code still oversells: the DECISION was made outside the lock.</text><text x="440" y="396" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Find the invariant, find the interval where it is false, and make the lock cover exactly that interval.</text></g>
</svg>
```

Before you reach for a lock, though, ask the cheaper question: **what is the shared mutable state?** Both words carry weight. State that is not *shared* — a local variable, a value owned by exactly one thread — needs no protection at all. State that is not *mutable* — a frozen dataclass, a tuple, a string — needs no protection either, because there is no window to protect; readers cannot observe a half-written value that never exists.

That is why the two cheapest fixes in concurrent programming are not locks. They are **thread confinement** (this data belongs to one thread, full stop) and **immutability** (nobody modifies it; you build a new one). A lock is what you use when you have failed to arrange either.

### Data race vs race condition

These two terms are constantly used interchangeably and they are precisely different. The distinction is what lets you reason about a "thread-safe" library that still lets you corrupt your data.

A **data race** is a low-level, mechanical condition: two threads access the same memory location concurrently, at least one of them writes, and there is no synchronisation ordering the accesses. In C, C++, Java, Go and Rust this is defined in the language's memory model, and in C and C++ it is **undefined behaviour** — the compiler is allowed to assume it never happens, which is how you get miscompilations, not just wrong values. Tools like ThreadSanitizer and Go's `-race` detector find exactly this.

A **race condition** is a higher-level, semantic condition: the correctness of the program depends on the relative timing of events. It is about *outcomes*, not memory.

Now the sentence that matters:

> **You can have a race condition with zero data races.**

Take an inventory class where every single method holds a lock. `available()` is atomic. `take()` is atomic. There is not one unsynchronised memory access in the class; no race detector on earth will flag it. Then a caller writes:

```python
if inventory.available():     # atomic
    inventory.take()          # atomic
```

and oversells the last seat, because the *decision* was made outside any lock. In the Build It, that composition oversells in **120 out of 120 rounds** and sells **1,173 seats that do not exist** — using a class in which every operation is individually thread-safe. Replace the two calls with one `take_if_available()` that makes the decision inside the lock, and it is **0 out of 120**.

The general law: **thread-safe parts do not compose into a thread-safe whole.** A `ConcurrentHashMap`, a `queue.Queue`, an `AtomicInteger` — each guarantees that *its own* operations are atomic. None of them can guarantee that *your sequence* of operations is atomic, because your invariant is not their invariant. Atomicity is a property of the operation your business logic actually needs, and only you know what that is.

### Memory visibility and reordering

Underneath all of this sits a layer that Python mostly hides from you, and that you must understand anyway, because the moment you write Go, Java, Rust or C++ it becomes load-bearing.

On real hardware, a write by one thread is not automatically visible to another. Each CPU core has its own store buffer and its own caches, so a write may sit in a core-local buffer for a while before it becomes globally visible. Compilers make it worse (or faster, depending on your point of view) by **reordering** instructions — a compiler is free to move a store earlier or later, or keep a variable in a register and never reload it, as long as *single-threaded* behaviour is unchanged. Nothing in that contract mentions other threads.

The consequence is genuinely startling the first time: without synchronisation, there is no guarantee that a write by one thread **ever** becomes visible to another, and no guarantee that two writes become visible in the order you wrote them. A loop like `while not flag: pass` can legally spin forever after another thread sets `flag = True`.

This is why every serious language defines a **memory model** — Java's JMM (Java Memory Model, JSR-133), C++11's, Go's — built on a relation called **happens-before**. It specifies exactly which synchronisation actions (acquiring and releasing a lock, a `volatile`/atomic access, starting or joining a thread, sending on a channel) force one thread's writes to be visible to another. Locks are not just mutual exclusion; **releasing a lock publishes your writes and acquiring it subscribes to them**, and that second job is why `volatile` exists in Java and why atomics in Go and Rust take an ordering parameter.

Now be scrupulous about Python. CPython's GIL (Global Interpreter Lock) means only one thread executes bytecode at a time, and the interpreter inserts the necessary barriers when it hands the GIL over. So **you will not reproduce a memory-visibility bug in CPython**, and this lesson does not pretend to — faking one would teach you a false mechanism. Three reasons to learn it anyway:

- The reasoning transfers exactly. "Which writes are visible to whom, and what establishes that?" is the same question in every language.
- The code you write in Go, Java, Rust or C++ depends on it *today*, and the bug it produces is a value that is stale rather than wrong-by-arithmetic — much harder to spot.
- The crutch is being removed. Free-threaded CPython (PEP 703, *Making the Global Interpreter Lock Optional in CPython*), introduced as an official experimental build in Python 3.13, runs threads truly in parallel. Every race in this lesson gets easier to hit, and the visibility questions become live in Python too.

### What is "atomic" in CPython, and why relying on it is a trap

There is a widely repeated piece of folklore: certain Python operations are atomic because they compile to a single bytecode and the interpreter does not switch threads mid-instruction. `list.append(x)`, `d[k] = v`, `x = y`, `list.pop()` — these are, in practice, atomic on CPython today.

It is even more true than the folklore claims, and the Build It shows it. On CPython 3.12, running eight threads that each do `box[0] += 1` in a tight loop a hundred thousand times loses **exactly zero** updates. Not "few" — zero, every time. The reason is that CPython only polls for a thread switch at specific points: a loop's back edge and function entry, among others. A bare read-modify-write inside a tight loop contains none of those, so the interpreter never interrupts it.

Now change one thing. Put the counter behind a `@property` — an accessor, which is to say *what real code looks like*: an ORM column, a model field, a validated setter, a config object. That inserts a Python-level function call between the load and the store, which is a switch point. Same eight threads, same hundred thousand increments each:

```text
box[0] += 1   (tight loop)        800,000 / 800,000    lost:       0
c.value += 1  (via a property)    214,734 / 800,000    lost: 585,266
```

**73.2% of the work vanished** because of an accessor. Nothing about the arithmetic changed.

That is the trap, stated precisely. What CPython gives you is not a language guarantee — it is an artefact of where one implementation happens to place its switch checks, and it is documented nowhere you can rely on. It does not cover `+=`. It does not cover any sequence of two operations. It evaporates the moment a function call, a property, a `__getitem__`, a descriptor, or a logging call appears in the window — and it evaporates entirely under free-threading or on any other interpreter.

The rule to carry:

> **If you cannot point at the lock (or the queue, or the immutability, or the confinement) that makes an operation safe, you do not have the guarantee. You have a coincidence.**

### Why races are heisenbugs

A **heisenbug** is a bug that changes or disappears when you try to observe it, and races are the purest example, for a mechanical reason: **the bug depends on the schedule, and every observation changes the schedule.**

- A `print` in the window adds I/O, which yields the GIL and *changes* which interleavings occur — sometimes hiding the bug, sometimes making it constant.
- A debugger breakpoint stops one thread entirely; the race needs two threads moving.
- A lighter load means fewer threads in the window at once, so a local test with two threads may never hit what eight threads under production traffic hit constantly.
- A faster machine can make it *more* likely, not less, by shortening everything except the window.

So "I ran it a thousand times and it never happened" tells you approximately nothing, and neither does "I added a log line and it went away" — that is not a fix, it is a Heisenberg apparatus. The Build It puts a number on it: the exact same oversell test, with the *only* difference being how long the code sits between the check and the act, goes from **0 failures in 120 rounds** to **120 out of 120**. Zero percent to one hundred percent, from a difference no test would think to control.

Which leaves exactly one reliable method: **reason about the invariant and the window, statically, by reading the code.** Testing can confirm a race exists. It can never confirm one doesn't.

## Build It

[`code/races.py`](code/races.py) is one file with five numbered demonstrations. It is stdlib-only and finishes in about fourteen seconds.

One thing it does deliberately, and you should know why. CPython hands the GIL between threads when the **switch interval** expires — 5 ms by default. Five milliseconds is an eternity in bytecode terms, so a race window a few instructions wide is almost never landed in during a short demo. The race demos therefore set the interval to 1 microsecond:

```python
DEFAULT_SWITCH_INTERVAL = sys.getswitchinterval()   # 0.005
FAST_SWITCH = 1e-6
sys.setswitchinterval(FAST_SWITCH)
```

This is legitimate, and being precise about it is part of the lesson: **it changes the frequency of the failure, never its existence.** Every race below is reachable at the default interval too — it just needs production traffic and a few weeks rather than 40 milliseconds. That asymmetry is precisely why races reach production: your test suite runs for seconds, your service runs for years. The timing benchmark in section 4 restores the default interval so its numbers describe normal operation.

The counter under test is deliberately an ordinary object, not a bare global, because that is what production code looks like:

```python
class Counter:
    """An ORM column, a model field, a @property wrapping validation, a config object:
    all of them put a Python-level function call between the load and the store."""
    def __init__(self, value: int = 0) -> None:
        self._value = value

    @property
    def value(self) -> int:
        return self._value

    @value.setter
    def value(self, new: int) -> None:
        self._value = new
```

The TOCTOU withdrawal is written the way the bug appears in a real codebase — with real work between the check and the act, because that is exactly what holds the window open:

```python
def write_audit_record(client: int, amount: int) -> str:
    """Building an audit row, calling a fraud service, emitting a metric. It takes
    ~200 microseconds because it touches something outside the process, and it
    holds the TOCTOU window open for exactly that long."""
    time.sleep(200e-6)
    return f"withdrawal client={client} amount={amount}"

def client(cid: int = 0) -> None:
    gate.wait()                            # release every thread at one instant
    if acct.balance >= amount:             # --- TIME OF CHECK: true
        write_audit_record(cid, amount)
        acct.balance -= amount             # --- TIME OF USE: no longer true
```

Section 3 isolates the invariant argument by using **one** writer thread, so no update can possibly be lost and any anomaly must be a torn read:

```python
def mover() -> None:
    for i in range(60_000):
        sign = 1 if i % 2 == 0 else -1
        ledger.set("a", ledger.get("a") - sign)   # invariant FALSE from here
        ledger.set("b", ledger.get("b") + sign)   # ...until here

def auditor() -> None:
    while not stop.is_set():
        total = ledger.get("a") + ledger.get("b")   # should always be 1000
```

And section 5 is the class where every method is individually atomic — the whole point being that this is not enough:

```python
class ThreadSafeInventory:
    def available(self) -> bool:
        with self._lock:                          # atomic
            return self._seats > 0

    def take(self) -> None:
        with self._lock:                          # atomic
            self._seats -= 1

    def take_if_available(self) -> bool:
        with self._lock:                          # atomic, and it covers the DECISION
            if self._seats > 0:
                self._seats -= 1
                return True
            return False
```

Run it:

```bash
python3 races.py
```

```console
== 1 · `counter += 1` IS THREE OPERATIONS, AND ONE OF THEM CAN BE LOST ==
  CPython bytecode for the single line `counter += 1`:
     71           2 LOAD_GLOBAL              0 (counter)
                 12 LOAD_CONST               1 (1)
                 14 BINARY_OP               13 (+=)
                 18 STORE_GLOBAL             0 (counter)
    LOAD_GLOBAL = read it | BINARY_OP = add | STORE_GLOBAL = write it back.

  (a) bare `box[0] += 1` in a tight loop, 8 threads x 100,000
      expected   800,000   actual   800,000   lost         0
      Zero. CPython 3.12 only polls for a thread switch at a loop's back edge
      and at function entry, so this read-modify-write is never interrupted.

  (b) `c.value += 1` where value is a @property, same 8 x 100,000
      expected   800,000   actual   214,734   lost   585,266   (73.2% of all work)
      Nothing crashed. No exception. No log line. Just a wrong number,
      returned confidently, by a program that then carried on.

  (c) the identical program, 20 more times (expected 800,000 every time):
        173,818 -   182,313  #####
        182,314 -   190,809  ##
        190,810 -   199,305  ###
        199,306 -   207,801  ##
        207,802 -   216,297  ####
        216,298 -   224,793  #
        224,794 -   233,289  ##
        233,290 -   241,785  .
        241,786 -   250,281  .
        250,282 -   258,777  #
      distinct answers 20/20   correct 0/20   min 173,818   max 258,773   spread 84,955
      (a) took 80 ms and (b) took 191 ms: the bug is not on a slow path, it IS the fast path.

== 2 · CHECK-THEN-ACT: TRUE WHEN YOU CHECKED IT, FALSE WHEN YOU USED IT ==
  (a) withdrawal   if balance >= 100: audit(); balance -= 100
      120 rounds x 12 clients against a $500 balance (5 withdrawals are legal)
      rounds ending NEGATIVE      :   119/120   (99.2%)
      money withdrawn that did not exist : $   78,800   ($657 per round)
      withdrawals that should have been refused: 788

  (b) oversell     if seats > 0: <work>; seats -= 1   (120 rounds, 12 buyers, 1 seat)
      The window is the ONLY variable. Everything else is identical.
      window between check and act   oversold rounds      phantom seats sold
      none (a few bytecodes)            0/120 ( 0.0%)          0 / 1320 possible
      50 us                           119/120 (99.2%)        871 / 1320 possible
      500 us                          120/120 (100.0%)       1290 / 1320 possible
      Probability is a function of window width. Nothing else changed.

  (c) cache fill   if key not in cache: cache[key] = fetch()
      12 threads, 1 cold key, fetch() costs 20 ms
      expensive fetches: 12   (1 was needed)   -> 12x the load on the thing the cache exists to protect
      wall clock 22 ms, at the DEFAULT switch interval:
      I/O inside the window releases the GIL, so this race needs no help.

== 3 · A RACE IS A BROKEN INVARIANT, NOT A TIMING BUG ==
  ONE writer thread (so no update can possibly be lost) moving $1 back and
  forth 60,000 times, and one auditor thread summing the two accounts.

  no lock
      audits taken                :   60,937
      audits that did NOT see 1000:   14,931   (24.50%)
      largest discrepancy observed:        1
      final a + b                 :     1000   -- not one cent was lost

  with a lock around the transfer
      audits taken                :   56,226
      audits that did NOT see 1000:        0   (0.00%)
      largest discrepancy observed:        0
      final a + b                 :     1000   -- not one cent was lost

== 4 · THE FIX: A CRITICAL SECTION THAT COVERS THE WHOLE READ-MODIFY-WRITE ==
  (a) counter, locked   : 800,000 / 800,000   EXACT
  (b) withdrawal, locked: 0 negative rounds, $0 overdrawn, 0 illegal withdrawals
  (c) oversell, locked  : 0 oversold rounds, 0 phantom seats   (at the 500 us window that sold 11 seats per round)
  (d) cache fill, locked: 1 expensive fetch (1 was needed)

  what the lock costs (150,000 increments, best of 5, default 5 ms interval):
      1 thread,  no lock :    24.4 ms
      1 thread,  locked  :    67.3 ms   +175.7%  <- the lock itself
      8 threads, no lock :    56.3 ms   (and the answer is wrong)
      8 threads, locked  :   373.0 ms      6.6x  <- the lock PLUS contention

== 5 · A RACE CONDITION WITH ZERO DATA RACES ==
  Same class both times. Every field access is under a lock. No data race
  detector on earth flags either version. One of them oversells anyway.

  if inv.available(): inv.take()      two atomic calls
      oversold rounds :  120/120   (100.0%)
      phantom seats   : 1173 / 1320 possible

  inv.take_if_available()             one atomic call
      oversold rounds :    0/120   (0.0%)
      phantom seats   :    0 / 1320 possible

total runtime 13.6 s
```

**Read the numbers — most of these sections are arguments, not demos.**

**Section 1 contains the lesson's most uncomfortable result, and it is the pair, not either half.** The textbook demo — `box[0] += 1`, eight threads, 800,000 increments — loses **exactly zero** updates on CPython 3.12. If you had run only that, you would conclude Python protects you. Add a `@property` and the identical arithmetic loses **585,266 of 800,000, 73.2% of all the work**. The difference between "perfectly safe" and "three-quarters of your data destroyed" is an accessor, which is to say: it is nothing you would notice in review, and it is present in essentially every real codebase. This is what "implementation detail, not a guarantee" means when you cash it out.

The twenty-run histogram is the second half of the argument. **Twenty distinct answers out of twenty runs. Zero correct. A spread of 84,955** between best and worst execution of byte-identical code. There is no "usually right, occasionally off" here, and crucially no failure mode a test could assert on — you cannot write `assert counter == 800_000` and see it fail *consistently* enough to trust the test, nor can you write an assertion for "some number between 173,818 and 258,773". Note also the timings: the racy run took **191 ms** versus **80 ms**, so the bug is not lurking on some rare slow path. It is the normal path.

**Section 2 measures the thing everyone gets wrong about race probability.** The withdrawal is straightforward damage: 12 clients racing for a $500 balance where only 5 withdrawals of $100 are legal, and **119 of 120 rounds end with a negative balance**, **$78,800 withdrawn that never existed** — $657 per round — across **788 withdrawals that should have been refused**. But part (b) is the real finding. It is the same test three times, and the *only* variable is how long the code sits between the check and the act:

| gap between check and act | oversold rounds | phantom seats |
|---|---|---|
| none (a few bytecodes) | 0 / 120 (0.0%) | 0 |
| 50 µs | 119 / 120 (99.2%) | 871 |
| 500 µs | 120 / 120 (100.0%) | 1,290 of 1,320 possible |

Zero percent to one hundred percent, with no change to the logic. At the 500 µs window, **1,290 of a possible 1,320 phantom seats sold** means essentially all twelve buyers got the one remaining seat, in every round. And the top row is the one that ships: a window of a few bytecodes fails so rarely that a 120-round test finds nothing at all — and then meets a million requests a day. The bug did not get worse when the window widened. It was always there; it merely became *findable*. That is the entire epistemology of race debugging in one table.

Part (c) shows the family's cheapest disguise. Twelve threads, one cold cache key, `if key not in cache: cache[key] = fetch()`, and **12 expensive fetches happen where 1 was needed** — 12× the load landing on the database the cache exists to protect. This is the cache stampede from [Cache Stampede & the Thundering Herd](../../05-caching/06-cache-stampede/), seen from the concurrency side rather than the caching side: a stampede *is* a TOCTOU bug. Note it ran at the **default** 5 ms switch interval and still hit 12/12 — because the 20 ms of I/O inside the window releases the GIL. Any race whose window contains I/O needs no help at all to reproduce.

**Section 3 separates two failures that get conflated.** One writer thread, 60,000 transfers, so a lost update is *impossible* — and indeed the final total is exactly 1000, not one cent misplaced, in both runs. Yet the unlocked auditor saw a wrong total in **14,931 of 60,937 samples: 24.50%**. Nearly a quarter of all reads of that ledger were of a state that never legitimately existed, with the money debited from one account and not yet credited to the other. Nothing was corrupted; something was *observed*. If that auditor is your nightly reconciliation job, you get a pager alert for a discrepancy that does not exist by the time you look. If it is a balance endpoint, a customer sees a number that is wrong for a microsecond and screenshots it. And note the largest discrepancy is exactly **1** — the transfer amount — which is the signature telling you it is a torn read and not a leak.

**Section 4 shows the fix works completely, and that it is not free.** All four scenarios become exact: 800,000/800,000, zero negative rounds, zero phantom seats even at the 500 µs window that previously oversold eleven seats per round, one expensive fetch instead of twelve. The cost is the interesting half. **Uncontended, the lock costs +175.7%** — one thread doing 150,000 locked increments takes 67.3 ms against 24.4 ms unlocked. That is the lock's intrinsic cost, and on an operation this trivial it dominates, because you are adding two synchronisation operations around what is essentially one addition. **Contended, eight threads cost 6.6×** — 373.0 ms against 56.3 ms — and that second number is the one to remember, because it is not the lock's cost, it is *serialisation*: eight threads taking turns through a region only one may occupy, plus a wake-up on every handoff. That multiplier is unstable across runs precisely because it depends on scheduling, and it is the entire motivation for Lesson 9's discussion of granularity. Also read the third line honestly: **8 threads with no lock took 56.3 ms and produced a wrong answer.** Fast and wrong is not a point on the trade-off curve.

**Section 5 is the most important part of this lesson**, and the part most engineers have never seen stated. `ThreadSafeInventory` holds a lock on *every* access to `_seats`. There is not one data race in it; ThreadSanitizer would pass it, a code review would pass it, and the class is genuinely thread-safe by the usual definition. Compose two of its atomic operations — `if inv.available(): inv.take()` — and it oversells in **120 of 120 rounds**, selling **1,173 phantom seats**. Making each half thread-safe fixed *nothing*, because the invariant was never "`_seats` is read consistently"; it was "a seat is sold at most once", and that invariant spans two calls. Move the decision inside the lock with `take_if_available()` and it is **0 of 120**. The general form — thread-safe parts do not compose into a thread-safe whole — is why "we use a concurrent collection" is not an answer to "is this correct".

## Use It

Most of the time the right move is not to write a lock. It is to arrange for there to be no shared mutable state to protect.

```python
import queue, threading, itertools
from dataclasses import dataclass, replace

# 1. Don't share. A queue is a thread-safe hand-off: ownership moves with the item,
#    and the worker mutates only what it owns. Phase 8 Lesson 7 built this pattern.
work: queue.Queue[Job] = queue.Queue(maxsize=1000)

def worker() -> None:
    while (job := work.get()) is not SHUTDOWN:
        handle(job)          # `job` belongs to this thread alone: no lock needed
        work.task_done()

# 2. Don't share, per-thread edition. threading.local() gives each thread its own
#    value under one name — the standard way to hold a DB connection or a request id.
_ctx = threading.local()
def request_id() -> str:
    return _ctx.request_id

# 3. Don't mutate. A frozen dataclass has no window: readers cannot see a half-update
#    because there is never a half-update. `replace` builds a new one.
@dataclass(frozen=True, slots=True)
class Pricing:
    currency: str
    cents: int

updated = replace(pricing, cents=pricing.cents + 100)   # new object, old one untouched

# 4. When you genuinely must share, lock the whole read-modify-write — and expose
#    the *decision*, never a check and an act the caller has to compose correctly.
class SeatMap:
    def __init__(self, seats: int) -> None:
        self._seats = seats
        self._lock = threading.Lock()

    def reserve(self) -> bool:                 # ONE call: check and act are inseparable
        with self._lock:
            if self._seats == 0:
                return False
            self._seats -= 1
            return True

# 5. Know the limits of the "atomic-ish" idioms. itertools.count() advances in C
#    with no Python-level call in the middle, so next(c) does not interleave on
#    CPython today — but that is the same coincidence as `box[0] += 1`, not a
#    guarantee, and it says nothing about any sequence you build around it.
ids = itertools.count(1)
```

Then there are the versions of this identical bug that a lock cannot touch, because the racing parties are not threads. Two processes behind a load balancer, or two pods, do not share a `threading.Lock`. Push the atomicity down to something both of them talk to:

```sql
-- Uniqueness as a CONSTRAINT the database enforces, not a convention your code
-- remembers. This is the fix for `if not exists(username): create(username)`.
ALTER TABLE users ADD CONSTRAINT users_username_key UNIQUE (username);
INSERT INTO users (username, email) VALUES ($1, $2)
    ON CONFLICT (username) DO NOTHING;          -- the race now has a defined winner

-- Optimistic concurrency: the version number is what lets a stale write notice
-- it is stale. If rowcount is 0, somebody else won; re-read and retry.
UPDATE orders SET status = 'shipped', version = version + 1
    WHERE id = $1 AND version = $2;

-- Pessimistic: take the row lock first, so check and act are inside one transaction.
BEGIN;
  SELECT seats FROM flights WHERE id = $1 FOR UPDATE;   -- other sessions block here
  UPDATE flights SET seats = seats - 1 WHERE id = $1;
COMMIT;

-- And the one-statement version, which needs no lock at all because the read and
-- the write are one atomic statement — with the invariant as a CHECK constraint.
UPDATE flights SET seats = seats - 1 WHERE id = $1 AND seats > 0;
```

```python
# Redis: SET NX is an atomic check-then-act, INCR is an atomic read-modify-write.
# Both do in one round trip what your code cannot do in two.
if r.set(f"lock:{order_id}", worker_id, nx=True, ex=30):   # exactly one winner
    try:
        process(order_id)
    finally:
        r.delete(f"lock:{order_id}")

r.incr("coupon:SUMMER40:uses")     # never `get` then `set` — that is the lost update
```

`SeatMap.reserve()` is your `take_if_available()`. `INSERT ... ON CONFLICT` is your critical section, enforced by the database. `UPDATE ... WHERE version = $2` is the lost update made *detectable* — it is the same idea as giving a value a way to notice it went stale. These map back to [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/) and [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/), and the `SET NX` pattern is the lock behind the stampede fix in [Cache Stampede & the Thundering Herd](../../05-caching/06-cache-stampede/).

Five rules that survive contact with production:

- **Find the invariant before you reach for a lock.** Write it as one sentence about the data ("a seat has at most one owner"). If you cannot state it, no amount of locking will be correct, because you do not yet know what you are protecting. Then find the interval where it is false — that interval, exactly, is your critical section.
- **The critical section covers the whole read-modify-write, including the decision.** A lock around the mutation with the `if` outside it is the most common real bug in this area, and it is invisible in review because every field access looks protected. Section 5 measured it: 120 out of 120 rounds oversold with every access locked.
- **Prefer not sharing over locking.** A queue hand-off, thread confinement, or an immutable value removes the window instead of guarding it, and it cannot be composed incorrectly by a caller six months from now. Reach for a lock when you have failed to arrange one of those, not first.
- **Never let a check and its act be separated by anything you do not control.** Not a network call, not a log line, not a callback, not a method you did not write. Expose one operation that makes the decision and performs it (`reserve()`, `take_if_available()`, `INSERT ... ON CONFLICT`), and never a `check()` and a `take()` that a caller must remember to use together.
- **Push uniqueness and atomicity into the database, where it is a constraint the database enforces rather than a convention your code remembers.** A `UNIQUE` index is checked on every insert by every process forever, including the migration script, the admin console and the backfill job someone runs at 2am. Application-level "we always check first" is a convention, and conventions have a half-life.

## Think about it

1. Your service runs four processes, each with eight threads, behind a load balancer. Every read-modify-write in your code is wrapped in a `threading.Lock`. Which of the bugs in this lesson are you still exposed to, and what is the smallest change that closes them?
2. Section 3 showed a single-writer ledger where no money was ever lost but 24.50% of reads saw a wrong total. For your own system, which is more damaging: a rare lost update, or a frequently observable broken invariant? What does your answer imply about where you put the lock — around the writes, or around the reads as well?
3. A teammate fixes an intermittent failure by adding a `logger.debug()` inside the suspicious block, and it never recurs in a week of staging. Argue, from the mechanism, why this is not evidence the bug is fixed — and describe what would count as evidence.
4. `if key not in cache: cache[key] = fetch(key)` produced 12 fetches for 1 key. A colleague proposes locking the whole thing. Under what traffic does that fix become worse than the stampede, and what would you do instead? (Consider what the other eleven threads are doing while the first one holds the lock through a 20 ms query.)
5. Free-threaded CPython removes the GIL. Which numbers in this lesson would you expect to get worse, which would stay the same, and which new category of bug — invisible in this lesson's output — becomes possible? What would you audit first in an existing codebase before running it on a free-threaded build?

## Key takeaways

- **`counter += 1` is a load, an add, and a store**, and the update is already lost at the moment the *second* thread loads. Eight threads × 100,000 increments produced **214,734 instead of 800,000 — 73.2% of the work destroyed** — with no exception, no log and no crash, and **20 runs of identical code gave 20 distinct wrong answers** spanning 84,955.
- **Atomic means no other thread can observe the operation half-done** — not fast, not one line of source. In CPython a bare `box[0] += 1` in a tight loop loses **exactly 0** updates while the same arithmetic through a `@property` loses **585,266**: the safety is an artefact of where one interpreter places its switch checks, so **if you cannot point at the lock, you have a coincidence, not a guarantee.**
- **Check-then-act (TOCTOU) is the same bug at every scale** — `if seats > 0: seats -= 1` in a thread, `SELECT` then `UPDATE` in a database, `GET` then `POST` across services — and its probability is set by the window width and nothing you control in testing: the identical oversell test went from **0/120 rounds with a few-bytecode gap to 120/120 with a 500 µs gap**, selling 1,290 of 1,320 possible phantom seats.
- **A race condition is a broken invariant, not a timing bug.** With a single writer — so no update could possibly be lost, and the final total was exactly right — an auditor thread still saw a wrong balance in **24.50% of 60,937 samples**. Find the invariant, find the interval where it is false, make that interval unobservable.
- **A data race is not a race condition.** A class whose every method holds a lock, composed as `if inv.available(): inv.take()`, oversold **120/120 rounds and 1,173 seats** with zero data races; `take_if_available()` — the same lock, with the decision inside it — oversold **0/120**. Thread-safe parts do not compose into a thread-safe whole.
- **Correctness costs measurably**, which is why not-sharing beats locking: the lock cost **+175.7% uncontended** and **6.6× with eight threads contending** (373.0 ms vs 56.3 ms) on a hot counter. A queue hand-off, thread confinement, or an immutable value removes the window rather than guarding it — and beyond one process, a `UNIQUE` constraint, `INSERT ... ON CONFLICT`, `UPDATE ... WHERE version = $1` or Redis `SET NX` are the same fix at the scale where a `threading.Lock` means nothing.

Next: [Locks & Coordination Primitives](../09-locks-and-coordination-primitives/) — the toolbox behind `with lock:`, and how granularity turns the 6.6× penalty measured here back into throughput.
