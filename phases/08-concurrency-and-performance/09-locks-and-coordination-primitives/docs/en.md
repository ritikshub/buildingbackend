# Locks & Coordination Primitives

> Lesson 8 ended by wrapping the shared counter in one lock and finally getting the right answer. That is where most codebases stop, and it is why they stop scaling. In this lesson's measurement, eight threads sharing one global lock managed **11,004 writes per second** and spent **3.15 thread-seconds** of a 0.9-second run doing nothing but waiting; the identical work spread across 16 striped locks reached **59,931 writes per second** with a mean wait of 12.4 microseconds instead of 327.8. A lock is not one tool, it is seven — and "just use a lock" does not answer how you wait for work without spinning, how you admit twenty readers but one writer, or how you cap concurrent calls to a fragile dependency at eight.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Race Conditions, Atomicity & Critical Sections](../08-race-conditions-and-atomicity/)
**Time:** ~80 minutes

## The Problem

You fixed the race. The counter is correct, the tests pass, and the fix was one line: put a lock around the critical section. Ship it.

Then traffic doubles, you move the service onto a bigger machine with more cores, and throughput does not move. It may even get worse. You add four more cores and the p99 latency rises. Nothing in your code changed; you simply gave it more parallelism, and it converted that parallelism into queueing.

Here is the arithmetic, and it is the same arithmetic from Lesson 1. **Amdahl's Law** says the speedup available from N processors is capped by the fraction of the work that must run serially: `speedup = 1 / (f + (1 - f) / N)`, where `f` is the serial fraction. A lock's critical section *is* a serial fraction. It does not matter that you have sixteen cores if all sixteen threads must line up single-file to enter the same twenty lines of code. In this lesson's Build It, a workload with only **27.1% of its work inside one lock** is capped at **2.76x on eight cores** and can never exceed **3.7x** no matter how many cores you buy. That is not a tuning problem. It is a structural ceiling you chose when you drew the lock's boundary.

And the cost is not only theoretical throughput. A lock that nobody else wants is genuinely cheap — one atomic instruction, no kernel involvement. In the measurement below, an **uncontended acquire and release took 101.5 nanoseconds**. The same acquire under contention from eight threads took **11,923.9 nanoseconds — 118 times more** — because a thread that cannot have the lock does not spin forever; it is parked by the operating system and must be woken again later. Threads spent an average of **88.76 microseconds blocked** inside a single `acquire()` call, and the worst single acquire took **3.10 milliseconds**. Contention does not gently degrade the average. It detonates the tail.

That is the scaling half of the problem. The other half is that a mutex simply cannot express most of what real backend code needs to coordinate:

- A pool of consumer threads must **wait until work exists**. With only a lock, your options are to spin on a flag — burning a core to discover nothing has changed — or to sleep for an arbitrary interval and be wrong in both directions.
- A routing table is read thousands of times a second and written once a minute. A mutex forces every reader to take turns even though **readers do not conflict with each other at all**.
- A downstream service falls over above eight concurrent calls. You need to admit **at most eight at a time** — which is not mutual exclusion, it is a quota.
- Eight worker threads must all finish phase one before any starts phase two.

Each of those has a purpose-built primitive, and reaching for the wrong one is how you end up with a program that is perfectly correct and completely useless.

## The Concept

A **lock** (or **mutex**, short for *mutual exclusion*) is an object with exactly one rule: at most one thread may hold it at a time. Everything else in this lesson is either a variation on that rule or an escape from it. Here is the whole family on one card; the rest of this section takes them one at a time.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 712" width="100%" style="max-width:840px" role="img" aria-label="A reference card for seven coordination primitives: mutex, reentrant lock, reader-writer lock, semaphore, condition variable, event and barrier. Each panel shows the primitive's access pattern as a small diagram, when to reach for it, and the production trap it carries.">
  <defs>
    <marker id="l09-ag" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker><marker id="l09-ab" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Seven primitives: what each one is for, and what each one will do to you</text><text x="440" y="44" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.75">blue = mutual exclusion &#183; purple = capacity &#183; green = waiting for a condition</text>
    <rect x="16" y="58" width="416" height="150" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="2"/>
    <g fill="#3553ff" stroke="#3553ff" stroke-width="1.6">
      <circle cx="286" cy="116" r="5" fill-opacity="0.55"/><circle cx="302" cy="116" r="5" fill-opacity="0.55"/><circle cx="318" cy="116" r="5" fill-opacity="0.55"/><rect x="350" y="98" width="70" height="36" rx="7" fill-opacity="0.16"/><circle cx="385" cy="116" r="5"/>
  </g><path d="M328 116 L 344 116" fill="none" stroke="#3553ff" stroke-width="1.8" marker-end="url(#l09-ab)"/>
      <g fill="currentColor">
        <text x="34" y="86" font-size="12.5" font-weight="700" fill="#3553ff">MUTEX &#183; Lock</text><text x="34" y="108" font-size="9.5" opacity="0.92">Exactly one thread inside at a time.</text><text x="34" y="124" font-size="9.5" opacity="0.92">The default. The cheapest primitive.</text><text x="34" y="140" font-size="9.5" opacity="0.7">~100 ns uncontended, ~12 us contended.</text>
        <text x="34" y="170" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="72" y="170" font-size="9.5" opacity="0.92">Always `with`. A raise between acquire and</text><text x="34" y="186" font-size="9.5" opacity="0.92">release holds it forever, and every later thread hangs.</text>
      </g>
      <rect x="448" y="58" width="416" height="150" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="2"/>
      <g fill="#3553ff" stroke="#3553ff" stroke-width="1.6">
        <rect x="726" y="98" width="112" height="36" rx="7" fill-opacity="0.16"/><circle cx="752" cy="116" r="5"/>
  </g><path d="M838 106 C 862 88, 730 78, 736 96" fill="none" stroke="#3553ff" stroke-width="1.6" stroke-dasharray="4 3" marker-end="url(#l09-ab)"/><text x="800" y="120" font-size="8.5" text-anchor="middle" fill="currentColor" opacity="0.85">depth = 2</text>
        <g fill="currentColor">
          <text x="466" y="86" font-size="12.5" font-weight="700" fill="#3553ff">REENTRANT &#183; RLock</text><text x="466" y="108" font-size="9.5" opacity="0.92">The same thread may re-enter; it</text><text x="466" y="124" font-size="9.5" opacity="0.92">tracks owner and recursion depth.</text>
          <text x="466" y="140" font-size="9.5" opacity="0.7">A plain Lock would deadlock on itself.</text><text x="466" y="170" font-size="8.5" font-weight="700" fill="#e0930f">SMELL</text><text x="512" y="170" font-size="9.5" opacity="0.92">Needing one usually means your locking</text>
          <text x="466" y="186" font-size="9.5" opacity="0.92">boundary is drawn in the wrong place. Fix that instead.</text>
        </g>
        <rect x="16" y="216" width="416" height="150" rx="11" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="2"/>
        <g stroke-width="1.6">
          <rect x="268" y="256" width="96" height="36" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
          <g fill="#0fa07f" stroke="#0fa07f">
            <circle cx="292" cy="274" r="5"/><circle cx="316" cy="274" r="5"/><circle cx="340" cy="274" r="5"/></g><circle cx="410" cy="274" r="5" fill="#d64545" stroke="#d64545"/>
  </g><path d="M382 254 L 382 294" fill="none" stroke="#d64545" stroke-width="2"/><text x="316" y="248" font-size="8" text-anchor="middle" fill="#0fa07f" font-weight="700">readers</text>
            <text x="410" y="248" font-size="8" text-anchor="middle" fill="#d64545" font-weight="700">writer</text>
            <g fill="currentColor">
              <text x="34" y="244" font-size="12.5" font-weight="700" fill="#3553ff">READ-WRITE &#183; RWLock</text><text x="34" y="266" font-size="9.5" opacity="0.92">Many readers OR one writer.</text><text x="34" y="282" font-size="9.5" opacity="0.92">Worth it only when reads dominate</text><text x="34" y="298" font-size="9.5" opacity="0.92">and the critical section is long.</text>
              <text x="34" y="328" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="72" y="328" font-size="9.5" opacity="0.92">Naive versions starve writers under a</text><text x="34" y="344" font-size="9.5" opacity="0.92">read storm, and cost MORE than a mutex for short sections.</text>
            </g>
            <rect x="448" y="216" width="416" height="150" rx="11" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
            <g fill="#7c5cff" stroke="#7c5cff" stroke-width="1.6">
              <circle cx="690" cy="274" r="5" fill-opacity="0.5"/><circle cx="706" cy="274" r="5" fill-opacity="0.5"/><circle cx="722" cy="274" r="5" fill-opacity="0.5"/><rect x="752" y="256" width="86" height="36" rx="7" fill-opacity="0.16"/><circle cx="774" cy="274" r="5"/><circle cx="795" cy="274" r="5"/><circle cx="816" cy="274" r="5"/>
  </g>
              <path d="M732 274 L 746 274" fill="none" stroke="#7c5cff" stroke-width="1.8"/><text x="795" y="248" font-size="8" text-anchor="middle" fill="#7c5cff" font-weight="700">3 permits</text>
              <g fill="currentColor">
                <text x="466" y="244" font-size="12.5" font-weight="700" fill="#7c5cff">SEMAPHORE(N)</text><text x="466" y="266" font-size="9.5" opacity="0.92">At most N at once. A counter of</text><text x="466" y="282" font-size="9.5" opacity="0.92">permits, not an owner. This is how</text><text x="466" y="298" font-size="9.5" opacity="0.92">you cap a fan-out or build a pool.</text>
                <text x="466" y="328" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="504" y="328" font-size="9.5" opacity="0.92">A stray release() on a plain Semaphore</text><text x="466" y="344" font-size="9.5" opacity="0.92">silently RAISES the limit. Use BoundedSemaphore; it raises.</text>
              </g>
              <rect x="16" y="374" width="416" height="150" rx="11" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/>
              <g fill="#0fa07f" stroke="#0fa07f" stroke-width="1.6">
                <circle cx="278" cy="432" r="6"/><circle cx="412" cy="432" r="6" fill-opacity="0.5"/>
  </g><text x="278" y="414" font-size="9" text-anchor="middle" fill="#0fa07f" font-weight="700">zZ</text><path d="M400 432 L 292 432" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l09-ag)"/>
                <text x="346" y="424" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.85">notify()</text><text x="346" y="450" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.7">then RE-CHECK</text>
                <g fill="currentColor">
                  <text x="34" y="402" font-size="12.5" font-weight="700" fill="#0fa07f">CONDITION</text><text x="34" y="424" font-size="9.5" opacity="0.92">Wait until a predicate is true,</text><text x="34" y="440" font-size="9.5" opacity="0.92">without burning a single CPU cycle.</text><text x="34" y="456" font-size="9.5" opacity="0.92">Owns a lock; wait() releases it.</text>
                  <text x="34" y="486" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="72" y="486" font-size="9.5" opacity="0.92">`while predicate`, NEVER `if`. Waking up</text><text x="34" y="502" font-size="9.5" opacity="0.92">is not a promise that the thing you waited for is still there.</text>
                </g>
                <rect x="448" y="374" width="416" height="150" rx="11" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/>
                <g stroke="#0fa07f" stroke-width="1.6">
                  <rect x="700" y="418" width="30" height="28" rx="5" fill="#0fa07f" fill-opacity="0.10"/><rect x="756" y="418" width="30" height="28" rx="5" fill="#0fa07f" fill-opacity="0.30"/>
  </g><text x="715" y="437" font-size="11" text-anchor="middle" fill="currentColor" font-weight="700">0</text>
                  <text x="771" y="437" font-size="11" text-anchor="middle" fill="currentColor" font-weight="700">1</text><path d="M734 432 L 750 432" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l09-ag)"/>
                  <g fill="#0fa07f" stroke="#0fa07f" stroke-width="1.4">
                    <circle cx="806" cy="422" r="4"/><circle cx="806" cy="432" r="4"/><circle cx="806" cy="442" r="4"/></g><path d="M790 432 L 800 432" fill="none" stroke="#0fa07f" stroke-width="1.4"/><text x="743" y="470" font-size="8" text-anchor="middle" fill="currentColor" opacity="0.7">latches: never resets</text>
                    <g fill="currentColor">
                      <text x="466" y="402" font-size="12.5" font-weight="700" fill="#0fa07f">EVENT</text><text x="466" y="424" font-size="9.5" opacity="0.92">A one-shot flag. set() releases</text><text x="466" y="440" font-size="9.5" opacity="0.92">every waiter, now and forever after.</text><text x="466" y="456" font-size="9.5" opacity="0.92">"The pool is warm"; "we are shutting down".</text>
                      <text x="466" y="486" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="504" y="486" font-size="9.5" opacity="0.92">It carries no data and it is not a queue.</text><text x="466" y="502" font-size="9.5" opacity="0.92">clear() re-arming it is a race with everyone still waiting.</text>
                    </g>
                    <rect x="16" y="532" width="416" height="150" rx="11" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/><path d="M352 566 L 352 634" fill="none" stroke="#0fa07f" stroke-width="2" stroke-dasharray="5 4"/>
                    <g fill="#0fa07f" stroke="#0fa07f" stroke-width="1.4" fill-opacity="0.5">
                      <circle cx="276" cy="578" r="4.5"/><circle cx="300" cy="594" r="4.5"/><circle cx="268" cy="610" r="4.5"/><circle cx="312" cy="626" r="4.5"/>
  </g>
                      <g fill="none" stroke="#0fa07f" stroke-width="1.3" opacity="0.75">
                        <path d="M284 578 L 346 578"/><path d="M308 594 L 346 594"/><path d="M276 610 L 346 610"/><path d="M320 626 L 346 626"/>
  </g>
                        <g fill="#0fa07f" stroke="#0fa07f" stroke-width="1.4">
                          <circle cx="372" cy="578" r="4.5"/><circle cx="372" cy="594" r="4.5"/><circle cx="372" cy="610" r="4.5"/><circle cx="372" cy="626" r="4.5"/>
  </g>
                          <g fill="currentColor">
                            <text x="34" y="560" font-size="12.5" font-weight="700" fill="#0fa07f">BARRIER(N)</text><text x="34" y="582" font-size="9.5" opacity="0.92">A rendezvous. N threads arrive,</text><text x="34" y="598" font-size="9.5" opacity="0.92">all block, all leave together.</text><text x="34" y="614" font-size="9.5" opacity="0.92">Phase 1 must finish before phase 2</text>
                            <text x="34" y="630" font-size="9.5" opacity="0.92">starts, for every worker.</text><text x="34" y="656" font-size="8.5" font-weight="700" fill="#d64545">TRAP</text><text x="72" y="656" font-size="9.5" opacity="0.92">One thread that dies or never arrives</text><text x="34" y="672" font-size="9.5" opacity="0.92">hangs all N. Always pass a timeout and handle BrokenBarrier.</text>
                          </g>
                          <rect x="448" y="532" width="416" height="150" rx="11" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f" stroke-width="2"/>
                          <g fill="currentColor">
                            <text x="466" y="560" font-size="12.5" font-weight="700" fill="#e0930f">CHOOSING BETWEEN THEM</text><text x="466" y="584" font-size="9.5" opacity="0.92">Protecting shared state? &#8594; Lock</text><text x="466" y="602" font-size="9.5" opacity="0.92">Limiting how many at once? &#8594; BoundedSemaphore</text>
                            <text x="466" y="620" font-size="9.5" opacity="0.92">Waiting for state to change? &#8594; Condition</text><text x="466" y="638" font-size="9.5" opacity="0.92">Waiting for a one-time fact? &#8594; Event</text><text x="466" y="656" font-size="9.5" opacity="0.92">Handing work over? &#8594; a Queue, and no lock at all</text>
                          </g>
                          <text x="440" y="702" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Using the wrong one is how you get a program that is perfectly correct and completely useless.</text>
                        </g>
</svg>
```

### The mutex: the acquire/release protocol

A mutex has two operations. `acquire()` blocks until the lock is free and then takes it. `release()` gives it back. The region between them is the **critical section** — the code that gets to assume nobody else is touching the shared state.

The protocol is easy to state and easy to break, because `release()` has to happen on *every* path out of the critical section — including the ones you did not plan. If an exception is raised between a manual `acquire()` and its `release()`, the lock is never released. It is not "released a bit late." It is held forever, by a thread that no longer exists, and every thread that ever wants it again blocks until the process is restarted. The Build It demonstrates exactly this: after a thread raises while holding a manually-acquired lock, the next thread's `acquire(timeout=0.5)` returns **`False` after waiting the full 0.5 seconds**. The same bug inside a `with` block leaves the lock free, and the next acquire succeeds in **0.0000 seconds**.

> **Always use `with lock:`.** Not as a style preference — as the thing that makes the release happen on the exception path you did not write a test for.

`acquire()` also takes a timeout: `lock.acquire(timeout=2.0)` returns `False` rather than blocking forever, turning a permanent hang into a handleable error. Use it at system boundaries where a hang would be invisible, not everywhere — a lock you failed to acquire leaves you holding a decision you probably have not thought through. Underneath, a mutex is not a spin loop. The uncontended path is a single atomic **compare-and-swap** instruction on a word in memory — no system call, no scheduler, hence ~100 ns. When the lock *is* held, the loser typically spins briefly (in case the holder is about to leave) and then asks the kernel to park it — on Linux via a **futex** (fast userspace mutex). Parking and waking a thread costs two context switches and a trip through the scheduler. That is the entire explanation for the 101.5 ns versus 11,923.9 ns gap: an uncontended lock is an instruction, and a contended lock is a scheduling event.

**The trap:** never do anything slow inside a critical section, because every microsecond you hold the lock is a microsecond multiplied by every thread waiting for it. Specifically: no network calls, no disk reads, no `time.sleep()`, no logging to a slow sink, and no acquiring a second lock (Lesson 10's material). Compute what you can *before* you acquire, take the lock, mutate, and get out.

### Reentrant locks: deadlocking against yourself

A plain mutex has no memory of who holds it. So if a method takes the lock and then calls another method that takes *the same* lock, the thread blocks waiting for a lock it is itself holding. It will wait forever. The Build It confirms it: a thread that acquires a `Lock` twice is **blocked forever: True**.

A **reentrant lock** (`RLock`) fixes this by tracking two extra things: which thread owns it, and how deep the recursion goes. The owner may acquire it again — the depth counter increments — and the lock is only actually released when the depth returns to zero. The same double-acquire that hangs a `Lock` **succeeds** on an `RLock`. Here is the honest part, and it matters more than the mechanism: **needing an `RLock` is usually a symptom, not a solution.** It means your public methods each take the lock and also call each other, so your locking boundary is drawn around the wrong thing. The conventional fix is to separate locked entry points from unlocked internals — a public `def update(self)` that takes the lock and calls a private `def _update_locked(self)` that assumes it is already held. That makes "who holds the lock here" a property you can read off the function name instead of a property you have to trace. Reach for `RLock` when you are wrapping code you do not control; reach for the refactor when you do.

### Read-write locks: many readers, or one writer

Two threads reading the same dictionary do not interfere. Only writes create the conflict. A **read-write lock** (RWLock) encodes that: any number of readers may hold it simultaneously, or exactly one writer, never both.

When reads dominate and the critical section is long, this is a large win. In the Build It, a pure-read workload of 2,400 operations across 8 threads — each read doing about 87 microseconds of real work — ran at **10,937 ops/s under a mutex and 43,768 ops/s under the RWLock: 4.0x faster**, because the mutex was forcing eight non-conflicting readers to take turns.

Now the two ways it goes wrong, both measured.

**Writer starvation.** The simplest RWLock is *reader-preferring*: a reader enters whenever no writer is currently writing. That means an arriving reader walks straight past a writer that is already queued. Under a continuous read load, the reader count never reaches zero, and the writer waits — potentially forever. With six threads looping on 0.4 ms reads, a writer trying to work for one full second completed **exactly 1 write, with a maximum wait of 1,387.8 milliseconds**. A *writer-preferring* variant, where arriving readers must queue behind any waiting writer, completed **9,714 writes with a maximum wait of 0.4 ms** over the same second. The starvation is not a rare scheduling accident; it is what the policy says to do.

Worse, starvation degrades throughput too. Add just **5% writes** to that pure-read workload and the reader-preferring RWLock drops to **9,228 ops/s — 0.8x, actually slower than the plain mutex at 10,938** — because writer threads pile up blocked instead of doing useful reads. The writer-preferring version delivered **27,670 ops/s, 2.5x the mutex**. If you build or choose an RWLock, its fairness policy is not a footnote.

**The bookkeeping is not free.** An RWLock has to maintain a reader count and a writer flag, under its own internal lock, on every acquire *and* every release. That is strictly more work than a mutex's single atomic operation. When the critical section is short, the overhead dominates the benefit. Same 95/5 workload, but with a critical section of one dictionary lookup: the mutex did **3,744,424 ops/s** and the RWLock **390,196 — the RWLock was 9.6x slower.** Below a few microseconds of hold time, an RWLock costs more than the mutex it replaced.

So the rule is narrow: use an RWLock when reads outnumber writes heavily *and* the critical section is long enough to matter. Python's standard library ships no RWLock, which is a reasonable hint about how often it is the right answer — so in the Build It you write one.

### Semaphores: a counter of permits

A **semaphore** holds a count of permits. `acquire()` takes one, blocking if none are left; `release()` puts one back. `Semaphore(1)` behaves roughly like a mutex, but that is the least interesting case. The point of a semaphore is `Semaphore(N)`: **at most N at once.**

This is the primitive backend engineers most consistently under-use, and it answers a question that comes up constantly: *how do I stop my service from overwhelming something downstream?* A database that thrashes above 20 connections, a third-party API that rate-limits you, an internal service whose thread pool is smaller than your fan-out. Note the difference from a mutex: a semaphore has no concept of an owner. One thread may acquire a permit and a different thread may release it — which is what makes it a resource counter, and what makes it easy to get wrong. Because a semaphore has no owner, a stray `release()` that never had a matching `acquire()` silently *increases* the number of permits. Your `Semaphore(8)` quietly becomes a `Semaphore(9)`, then a `Semaphore(12)`, and the limit you carefully tuned is now fiction, with nothing in any log to tell you. `BoundedSemaphore` remembers its initial value and raises `ValueError: Semaphore released too many times` the moment the count would exceed it. **Default to `BoundedSemaphore`.** The Build It shows both: the plain one grows to 3 permits without complaint; the bounded one raises.

The measured effect of capping concurrency is the counterintuitive part. Against a dependency that degrades quadratically past 8 concurrent calls and refuses past 32, driving 400 calls from 40 unbounded worker threads produced **33 successful calls per second and 367 failures out of 400**. The same 400 calls through a `BoundedSemaphore(8)` produced **1,894 successful calls per second and zero failures — 56.9x the successful throughput** — and the dependency's own p99 latency fell from 64.1 ms to 6.4 ms, a factor of **10.1**. Doing less at once finished sooner.

Note what did *not* improve: end-to-end p99 latency, measured from the moment a task wanted the dependency, went **up**, from 100.4 ms to 208.7 ms. That is not a flaw, it is the mechanism. A semaphore does not make the work faster; it **moves the queue** out of the fragile dependency, where queueing turns into timeouts and errors, and into your own process, where it is visible, boundable, and yours to shed. Lesson 12 turns this exact pattern into a connection pool.

### Condition variables: waiting for a predicate

The hardest coordination question is not "who may touch this" but "**when does this become true?**" A consumer needs to wait until the queue is non-empty. A pool needs to wait until a connection is returned. Spinning on the flag burns a core; sleeping for a fixed interval is either wasteful or slow.

A **condition variable** solves it. A `Condition` owns a lock and adds three operations:

- `wait()` — **atomically** releases the lock and puts the thread to sleep. Atomicity here is the whole design: if the release and the sleep were separate steps, a notification could arrive in the gap and be lost forever.
- `notify()` — moves one waiting thread to the ready state. `notify_all()` moves all of them.
- The waiter, once woken, must **reacquire the lock** before `wait()` returns.

That last step is where the famous bug lives, because between the notify and the reacquire, the world keeps moving.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="A timeline showing two consumer threads and a producer sharing one condition variable. Both consumers find the buffer empty, call wait which atomically releases the lock and sleeps, and the producer appends one item and calls notify_all under the lock. Both consumers wake and reacquire the lock in turn; the first takes the item, and the second finds the buffer empty again. A while loop sends it back to sleep, whereas an if statement lets it pop an empty buffer and crash.">
  <defs>
    <marker id="l09b-arw" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker><marker id="l09b-grn" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker><marker id="l09b-red" markerWidth="9" markerHeight="9" refX="6" refY="3" orient="auto">
    <path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One item, two waiters: why the predicate is rechecked in a `while`</text><rect x="40" y="42" width="150" height="30" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.8"/>
    <rect x="330" y="42" width="150" height="30" rx="7" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.8"/><rect x="620" y="42" width="150" height="30" rx="7" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff" stroke-width="1.8"/><text x="115" y="62" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">CONSUMER A</text>
    <text x="405" y="62" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">PRODUCER</text><text x="695" y="62" text-anchor="middle" font-size="11" font-weight="700" fill="#3553ff">CONSUMER B</text>
    <g stroke="currentColor" stroke-width="1.3" stroke-dasharray="4 5" opacity="0.45">
      <path d="M115 72 L 115 86"/><path d="M115 128 L 115 238"/><path d="M115 294 L 115 330"/><path d="M405 72 L 405 162"/><path d="M405 218 L 405 256"/><path d="M405 296 L 405 388"/><path d="M695 72 L 695 86"/><path d="M695 128 L 695 238"/><path d="M695 294 L 695 312"/><path d="M695 350 L 695 388"/>
  </g>
      <rect x="34" y="86" width="162" height="42" rx="6" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.5"/><text x="115" y="102" text-anchor="middle" font-size="9" fill="currentColor">with cond:  buffer empty</text><text x="115" y="118" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">cond.wait()</text>
      <rect x="614" y="86" width="162" height="42" rx="6" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.5"/><text x="695" y="102" text-anchor="middle" font-size="9" fill="currentColor">with cond:  buffer empty</text><text x="695" y="118" text-anchor="middle" font-size="9" font-weight="700" fill="#3553ff">cond.wait()</text>
      <text x="115" y="150" text-anchor="middle" font-size="8.5" fill="#e0930f" font-weight="700">releases the lock, sleeps</text><text x="695" y="150" text-anchor="middle" font-size="8.5" fill="#e0930f" font-weight="700">releases the lock, sleeps</text><text x="115" y="176" text-anchor="middle" font-size="13" fill="#7f7f7f" font-weight="700">zZ</text>
      <text x="695" y="176" text-anchor="middle" font-size="13" fill="#7f7f7f" font-weight="700">zZ</text><rect x="322" y="162" width="166" height="56" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.6"/><text x="405" y="180" text-anchor="middle" font-size="9" fill="currentColor">with cond:</text>
      <text x="405" y="195" text-anchor="middle" font-size="9" fill="currentColor">append(ONE item)</text><text x="405" y="211" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">cond.notify_all()</text><path d="M320 196 L 130 196" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#l09b-grn)"/>
      <path d="M490 196 L 680 196" fill="none" stroke="#0fa07f" stroke-width="1.7" marker-end="url(#l09b-grn)"/><text x="225" y="188" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">wake</text><text x="585" y="188" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">wake</text>
      <rect x="34" y="238" width="162" height="56" rx="6" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="1.6"/><text x="115" y="256" text-anchor="middle" font-size="9" fill="currentColor">reacquires the lock</text><text x="115" y="271" text-anchor="middle" font-size="9" fill="currentColor">recheck: 1 item</text>
      <text x="115" y="285" text-anchor="middle" font-size="9" font-weight="700" fill="#0fa07f">popleft()  OK</text><rect x="614" y="238" width="162" height="56" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.6"/><text x="695" y="255" text-anchor="middle" font-size="9" fill="currentColor">awake, but BLOCKED</text>
      <text x="695" y="270" text-anchor="middle" font-size="9" fill="currentColor">waiting to reacquire</text><text x="695" y="285" text-anchor="middle" font-size="8.5" font-weight="700" fill="#e0930f">A is consuming the item</text><text x="405" y="268" text-anchor="middle" font-size="9" fill="#d64545" font-weight="700">the world changed</text>
      <text x="405" y="283" text-anchor="middle" font-size="9" fill="#d64545" font-weight="700">between wake and lock</text><rect x="614" y="312" width="162" height="38" rx="6" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.5"/><text x="695" y="329" text-anchor="middle" font-size="9" fill="currentColor">B gets the lock.</text>
      <text x="695" y="344" text-anchor="middle" font-size="9" font-weight="700" fill="currentColor">buffer is EMPTY again</text><path d="M660 350 L 560 380" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l09b-grn)"/><path d="M730 350 L 800 380" fill="none" stroke="#d64545" stroke-width="1.8" marker-end="url(#l09b-red)"/>
      <rect x="330" y="388" width="248" height="76" rx="8" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f" stroke-width="2"/><text x="454" y="408" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">while not items: wait()</text><text x="454" y="428" text-anchor="middle" font-size="9" fill="currentColor">The predicate is false, so B loops</text>
      <text x="454" y="443" text-anchor="middle" font-size="9" fill="currentColor">and goes back to sleep. Correct.</text><text x="454" y="458" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.75">Costs one extra loop iteration.</text><rect x="604" y="388" width="248" height="76" rx="8" fill="#d64545" fill-opacity="0.12" stroke="#d64545" stroke-width="2"/>
      <text x="728" y="408" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">if not items: wait()</text><text x="728" y="428" text-anchor="middle" font-size="9" fill="currentColor">Checked once, never again. B falls</text><text x="728" y="443" text-anchor="middle" font-size="9" fill="currentColor">straight through to popleft().</text>
      <text x="728" y="458" text-anchor="middle" font-size="8.5" font-weight="700" fill="#d64545">IndexError: pop from an empty deque</text><rect x="30" y="330" width="256" height="134" rx="8" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4" stroke-width="1.5"/>
      <text x="46" y="350" font-size="9.5" font-weight="700" fill="currentColor">THREE REASONS TO RECHECK</text><text x="46" y="372" font-size="9" fill="currentColor" opacity="0.9">1. notify_all() woke N threads for</text><text x="46" y="386" font-size="9" fill="currentColor" opacity="0.9">   one item; N-1 must go back.</text>
      <text x="46" y="404" font-size="9" fill="currentColor" opacity="0.9">2. Another thread consumed it</text><text x="46" y="418" font-size="9" fill="currentColor" opacity="0.9">   before you got the lock back.</text><text x="46" y="436" font-size="9" fill="currentColor" opacity="0.9">3. Spurious wakeups are legal:</text>
      <text x="46" y="450" font-size="9" fill="currentColor" opacity="0.9">   waking is not a guarantee.</text><text x="440" y="506" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">wait() returning means "something may have changed" &#8212; never "the thing you wanted is here."</text>
      <text x="440" y="530" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">Measured: 2 waiters, 1 item, one notify_all &#8212; the `if` version popped an empty buffer 1 time out of 2.</text>
    </g>
</svg>
```

> **Always wait in a `while` loop on the predicate. Never an `if`.**

```python
with cond:
    while not predicate():   # while, not if
        cond.wait()
    # predicate() is true AND we hold the lock
```

There are three independent reasons, and any one of them is enough:

1. **`notify_all()` wakes everyone for one item.** Two consumers wait, the producer appends one item and calls `notify_all()`. Both wake. One reacquires the lock and takes the item. The other reacquires the lock and finds the buffer empty again. With `while`, it loops and sleeps. With `if`, it falls straight through to `popleft()` on an empty deque. The Build It reproduces this deterministically: **1 of 2 consumers popped an empty buffer**, raising `IndexError: pop from an empty deque`.
2. **Someone else consumed it first.** Even with `notify()`, a *third* thread that was not waiting at all can acquire the lock and take the item before the woken thread gets back in.
3. **Spurious wakeups are legal.** Both POSIX and the Java memory model explicitly permit `wait()` to return without any notification at all, because forbidding it would make the primitive slower on real hardware. Code that assumes a wakeup implies a notification is incorrect by specification, not merely unlucky.

The companion failure is the **lost wakeup**: a `notify()` that fires when nobody is waiting simply vanishes — it is not queued, not remembered. If a thread then checks the predicate and waits, it can sleep forever holding a condition that already came true. The fix is structural, and it is why the predicate check must happen *while holding the lock*: the notifier changes the state and notifies under the same lock the waiter uses to check, so there is no window between "the state changed" and "I decided to sleep." The Build It shows the raw version of this — an early `notify_all()` reaching **nobody**, and a later waiter never woken by it.

`notify()` versus `notify_all()`: use `notify()` when any single waiter can handle the event and all waiters are equivalent — waking N threads so that N-1 immediately go back to sleep is a **thundering herd**, and it costs N context switches plus N contended lock acquisitions for one unit of work. Use `notify_all()` when waiters are waiting on *different* predicates (some for "not empty", some for "not full"), because you cannot tell which one to wake. When in doubt, `notify_all()` is the safe default: it is slower, never wrong, and correctness first.

### Event and Barrier

An **`Event`** is a one-shot boolean flag with waiting built in. `wait()` blocks until it is set; `set()` releases every current and future waiter permanently. It is the right tool for a one-time fact: "configuration is loaded", "the connection pool is warm", "we are shutting down". A realistic shape is startup readiness — worker threads call `ready.wait()` before serving, and the initialization thread calls `ready.set()` once. It carries no data, and it is not a queue: it latches. Re-arming one with `clear()` is a race against every thread still in `wait()`, so treat an Event as write-once.

A **`Barrier(N)`** is a rendezvous: N threads each call `wait()`, all of them block, and when the Nth arrives they are all released together. Its use is phase synchronization — a parallel job where every worker must finish loading its shard before any worker starts querying, so that no worker reads a half-built structure. Its trap is severe: if one of the N threads dies or never arrives, **all N hang forever**. Always pass a timeout and handle `BrokenBarrierError`, which is raised in every participant once the barrier is broken.

### Lock granularity: one lock, N locks, or no lock

This is the decision that determines whether your service scales, and it is a spectrum.

**One global lock** is trivially correct and trivially serial. Every thread that touches any part of the structure queues behind every other thread, even when they are working on completely unrelated keys. It is the right choice for genuinely cold state — a config object read at startup — and the wrong choice for anything hot.

**Per-object or per-shard locks** let unrelated work proceed in parallel. They also introduce the possibility of holding two locks at once, which is where deadlock becomes possible — Lesson 10. **Lock striping** is the standard middle ground and the one you should default to for a hot shared map: allocate a fixed array of N locks, and map each key to one of them with `locks[hash(key) % N]`. You get most of the parallelism of per-key locking with a bounded, fixed amount of memory, and — critically — a thread still only ever needs *one* lock for a single-key operation, so the deadlock risk stays where it was.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="Left panel: eight threads all queue behind one global lock guarding one index, achieving eleven thousand operations per second with a mean wait of three hundred and twenty-eight microseconds. Right panel: the same eight threads hash each key to one of sixteen striped locks and spread across sixteen shards, achieving sixty thousand operations per second with a mean wait of twelve microseconds. A bottom strip shows thread-local accumulation with no lock at all reaching seventy-six thousand operations per second and zero wait.">
  <defs>
    <marker id="l09c-b" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#3553ff"/></marker><marker id="l09c-g" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Same 9,600 writes, same 8 threads: only the lock granularity changes</text><rect x="16" y="40" width="416" height="292" rx="11" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-width="2"/>
    <text x="224" y="64" text-anchor="middle" font-size="12" font-weight="700" fill="#d64545">ONE GLOBAL LOCK</text>
    <g stroke-width="1.5">
      <circle cx="52" cy="98" r="6.5" fill="#0fa07f" fill-opacity="0.9" stroke="#0fa07f"/>
      <g fill="#d64545" fill-opacity="0.35" stroke="#d64545">
        <circle cx="52" cy="124" r="6.5"/><circle cx="52" cy="150" r="6.5"/><circle cx="52" cy="176" r="6.5"/><circle cx="52" cy="202" r="6.5"/><circle cx="52" cy="228" r="6.5"/><circle cx="52" cy="254" r="6.5"/><circle cx="52" cy="280" r="6.5"/>
    </g>
      </g>
      <text x="52" y="84" text-anchor="middle" font-size="8" fill="#0fa07f" font-weight="700">running</text><text x="52" y="300" text-anchor="middle" font-size="8" fill="#d64545" font-weight="700">7 waiting</text>
      <g fill="none" stroke="#d64545" stroke-width="1.2" opacity="0.55">
        <path d="M62 124 L 172 180"/><path d="M62 150 L 172 184"/><path d="M62 176 L 172 188"/><path d="M62 202 L 172 192"/><path d="M62 228 L 172 196"/><path d="M62 254 L 172 200"/><path d="M62 280 L 172 204"/>
  </g><path d="M62 98 L 170 176" fill="none" stroke="#0fa07f" stroke-width="1.8" marker-end="url(#l09c-g)"/>
        <rect x="176" y="164" width="46" height="52" rx="8" fill="#d64545" fill-opacity="0.22" stroke="#d64545" stroke-width="2"/><text x="199" y="186" text-anchor="middle" font-size="9" font-weight="700" fill="#d64545">ONE</text><text x="199" y="199" text-anchor="middle" font-size="9" font-weight="700" fill="#d64545">LOCK</text>
        <path d="M226 190 L 256 190" fill="none" stroke="currentColor" stroke-width="1.6" opacity="0.7"/><rect x="260" y="150" width="152" height="80" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5" stroke-width="1.6"/><text x="336" y="176" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">one index</text>
        <text x="336" y="194" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">64 keys</text><text x="336" y="216" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.65">store[k] = hash(doc)</text><text x="224" y="256" text-anchor="middle" font-size="15" font-weight="700" fill="#d64545">11,004 ops/s</text>
        <text x="224" y="277" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">mean wait per write &#160;&#160;327.8 us</text><text x="224" y="294" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">total time blocked &#160;&#160;3.15 thread-s</text>
        <text x="224" y="316" text-anchor="middle" font-size="9" fill="#d64545" font-weight="700">Correct. Adding cores adds queue, not throughput.</text><rect x="448" y="40" width="416" height="292" rx="11" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
        <text x="656" y="64" text-anchor="middle" font-size="12" font-weight="700" fill="#0fa07f">16 STRIPED LOCKS &#183; lock[hash(key) % 16]</text>
        <g stroke-width="1.5" fill="#0fa07f" stroke="#0fa07f">
          <circle cx="484" cy="98" r="6.5"/><circle cx="484" cy="124" r="6.5"/><circle cx="484" cy="150" r="6.5"/><circle cx="484" cy="176" r="6.5"/><circle cx="484" cy="202" r="6.5"/><circle cx="484" cy="228" r="6.5"/><circle cx="484" cy="254" r="6.5"/><circle cx="484" cy="280" r="6.5"/>
  </g>
          <text x="484" y="84" text-anchor="middle" font-size="8" fill="#0fa07f" font-weight="700">8 running</text>
          <g fill="none" stroke="#0fa07f" stroke-width="1.3" opacity="0.7">
            <path d="M494 98 L 596 100" marker-end="url(#l09c-g)"/><path d="M494 124 L 596 128" marker-end="url(#l09c-g)"/><path d="M494 150 L 596 156" marker-end="url(#l09c-g)"/><path d="M494 176 L 596 184" marker-end="url(#l09c-g)"/><path d="M494 202 L 596 212" marker-end="url(#l09c-g)"/><path d="M494 228 L 596 240" marker-end="url(#l09c-g)"/>
            <path d="M494 254 L 596 268" marker-end="url(#l09c-g)"/><path d="M494 280 L 596 296" marker-end="url(#l09c-g)"/>
  </g>
            <g stroke="#0fa07f" stroke-width="1.6">
              <rect x="606" y="88" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="116" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="144" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="172" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/>
              <rect x="606" y="200" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="228" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="256" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/><rect x="606" y="284" width="34" height="24" rx="5" fill="#0fa07f" fill-opacity="0.22"/>
  </g>
              <g stroke="currentColor" stroke-opacity="0.5" stroke-width="1.4" fill="#7f7f7f" fill-opacity="0.10">
                <rect x="656" y="88" width="58" height="24" rx="5"/><rect x="656" y="116" width="58" height="24" rx="5"/><rect x="656" y="144" width="58" height="24" rx="5"/><rect x="656" y="172" width="58" height="24" rx="5"/><rect x="656" y="200" width="58" height="24" rx="5"/><rect x="656" y="228" width="58" height="24" rx="5"/><rect x="656" y="256" width="58" height="24" rx="5"/>
                <rect x="656" y="284" width="58" height="24" rx="5"/>
  </g><text x="623" y="80" text-anchor="middle" font-size="8" fill="#0fa07f" font-weight="700">locks</text><text x="685" y="80" text-anchor="middle" font-size="8" fill="currentColor" opacity="0.7" font-weight="700">shards</text><text x="746" y="196" font-size="9" fill="currentColor" opacity="0.75">...16 of</text>
                <text x="746" y="212" font-size="9" fill="currentColor" opacity="0.75">each pair</text><text x="592" y="325" text-anchor="middle" font-size="9" fill="#0fa07f" font-weight="700">Collisions only when keys share a stripe.</text><rect x="736" y="234" width="120" height="82" rx="8" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f" stroke-width="1.6"/>
                <text x="796" y="258" text-anchor="middle" font-size="14" font-weight="700" fill="#0fa07f">59,931</text><text x="796" y="273" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">ops/s &#160;&#8212; &#160;5.45x</text><text x="796" y="292" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">mean wait 12.4 us</text>
                <text x="796" y="307" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.9">blocked 0.12 thr-s</text><rect x="16" y="344" width="848" height="76" rx="11" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="2"/>
                <text x="40" y="368" font-size="12" font-weight="700" fill="#3553ff">NO LOCK AT ALL &#183; thread-local accumulation, merged once after join()</text><text x="40" y="390" font-size="9.5" fill="currentColor" opacity="0.92">Each thread writes only into a dict it alone owns. Nothing is shared until every thread has finished,</text>
                <text x="40" y="406" font-size="9.5" fill="currentColor" opacity="0.92">so the merge runs single-threaded on the main thread and needs no lock, no ordering, no wait.</text><text x="836" y="378" text-anchor="end" font-size="15" font-weight="700" fill="#3553ff">75,712 ops/s &#160;&#183;&#160; 6.88x</text>
                <text x="836" y="400" text-anchor="end" font-size="9.5" fill="#3553ff" font-weight="700">mean wait: 0.0 us</text><text x="440" y="452" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Wait time fell 327.8 &#8594; 12.4 &#8594; 0.0 microseconds. Throughput followed it, in that order.</text>
                <text x="440" y="476" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.85">CPython's GIL compresses the absolute numbers; the ordering is what transfers to Go, Java and Rust.</text>
              </g>
</svg>
```

The measurement is the argument. Eight threads, 9,600 writes into a 64-key index, each write doing real work inside the critical section:

| strategy | throughput | mean wait per write | total time blocked |
|---|---|---|---|
| one global lock | 11,004 ops/s | 327.8 µs | 3.15 thread-seconds |
| 16 striped locks | 59,931 ops/s | 12.4 µs | 0.12 thread-seconds |
| thread-local, merged at the end | 75,712 ops/s | 0.0 µs | 0.00 thread-seconds |

Striping bought **5.45x** the throughput and cut mean wait **26x**. Not sharing at all bought **6.88x** and eliminated waiting entirely.

Two honest caveats. First, CPython's **GIL** (Global Interpreter Lock — the interpreter's own rule that only one thread executes Python bytecode at a time, from Lesson 2) compresses all of these numbers; the work inside the critical section here is deliberately chosen to release the GIL so that the comparison means something. The *ordering* and the collapse in wait time are the results that transfer directly to Go, Java and Rust, where the absolute gaps are wider. Second, this workload deliberately holds the lock across expensive work; the cheapest fix of all is often not to change the granularity but to shrink the critical section — compute outside, mutate inside.

And the list of things to **never** do while holding a lock, each of which is a real incident: no I/O of any kind, no network calls, no acquiring a second lock, and no calling a **user-supplied callback**. That last one is subtle and vicious: you do not know what the callback does. It may block, it may take a lock of its own, it may re-enter your own API and try to take the lock you are already holding. Invoke callbacks after you release.

### Contention is measurable

You do not have to guess which lock is hot. Neither Python nor most languages give you lock wait time for free, but the instrumentation is about fifteen lines: wrap `acquire()`, record how long it blocked, and accumulate. Because the statistics are updated while the real lock is held, they need no lock of their own.

What you want out of it: **acquisitions**, **the fraction that were contended**, **mean and max wait**, and the ratio of **time waiting to time holding**. In the Build It, that instrumentation says the `hot_index` lock was contended on **63.0%** of its 12,000 acquisitions, with a mean wait of **370.5 µs** and a **wait/hold ratio of 36.78** — threads spent thirty-seven times longer waiting for that lock than using it — while the `cold_config` lock was contended **0.0%** of the time. One of those is worth sharding. The other is worth leaving alone forever.

Then apply Amdahl with real inputs instead of a guess. Measure the total time the lock was *held* (the strictly serial work) and the total time spent working outside any lock (the parallelisable work). In the Build It that is 0.12 s serial against 0.32 s parallel, a **serial fraction of 27.1%**, which caps the workload at **2.76x on eight cores** and at **3.7x on infinite cores**. Export lock wait time as a gauge — it belongs next to the four golden signals from [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) — and you will know which lock to shard before you touch any code.

### Beyond locks: compare-and-swap

Under every lock is a hardware instruction: **compare-and-swap** (CAS). CAS takes a memory location, an expected value, and a new value, and atomically sets the location to the new value *only if* it currently holds the expected one, reporting whether it succeeded. On x86 it is `LOCK CMPXCHG`; on ARM it is a load-exclusive/store-exclusive pair.

CAS lets you update shared state with no lock at all, using a retry loop:

```text
loop:
    old = read(cell)
    new = compute(old)
    if compare_and_swap(cell, old, new): done
    else: retry          # somebody changed it; our `new` is based on stale data
```

Nothing blocks. A thread that loses the race simply does its work again. This is **lock-free**, and the precise meaning of that term is narrower than people assume: it guarantees that *some* thread always makes progress, not that any particular thread does, and emphatically not that it is faster. Under contention you pay in wasted CPU rather than blocked threads. The Build It measures the trade directly — with a compute step long enough to lose the race, retries per successful update rose **0 → 0.69 → 2.26 → 6.01** at 1, 2, 4 and 8 threads. At 8 threads, **85.7% of all attempts were thrown away.** Every final value was still exactly correct: CAS never loses an update, it just repeats work.

Then there is the **ABA problem**, the classic CAS hazard. Thread 1 reads the value `A`. Before it can swap, thread 2 changes the value to `B` and then back to `A`. Thread 1's CAS compares against `A`, sees `A`, and succeeds — even though the world changed completely underneath it. This is devastating for pointer-based structures like a lock-free stack, where the `A` you are comparing against may be a node that was popped, freed, and reallocated. The standard fix is to CAS on a **(value, version)** pair and bump the version on every write, so `A` at version 0 is distinguishable from `A` at version 2. The Build It shows both: plain CAS after an A→B→A sequence **succeeded (wrongly)**; the versioned CAS **correctly failed** and forced a retry.

If that pattern looks familiar, it should. `UPDATE accounts SET balance = $1, version = version + 1 WHERE id = $2 AND version = $3`, checking that one row was affected and retrying if zero were, is **optimistic concurrency control** — the identical algorithm one layer up, with a database row as the cell and a version column as the tag ([Isolation Levels & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/)). CAS at the hardware layer and OCC at the database layer are the same idea: do not lock, detect the conflict and retry.

Should you write lock-free data structures? Almost never. They are extraordinarily difficult to get right, they need memory-reclamation schemes to be safe, and a well-placed mutex beats a subtly broken lock-free stack every day. Use the ones your standard library ships, and use the *idea* — optimistic retry — everywhere.

### The best lock is no lock

Every problem in this lesson comes from one root: two threads reaching for the same mutable thing. Remove that and the category disappears. Work down this ladder in order.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 470" width="100%" style="max-width:840px" role="img" aria-label="A four-rung ladder of strategies for shared state, ordered by preference. Rung one is immutability, where there is nothing to protect. Rung two is confinement, where one thread owns the data. Rung three is message passing, where ownership is handed over a queue. Rung four is locking, the only rung that can deadlock. Cost and risk rise with every rung.">
  <defs>
    <marker id="l09d-up" markerWidth="10" markerHeight="10" refX="5" refY="8" orient="auto"><path d="M5,0 L9,8 L1,8 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The best lock is no lock: try these in order, top to bottom</text><path d="M52 400 L 52 66" fill="none" stroke="#d64545" stroke-width="2" marker-end="url(#l09d-up)"/>
    <text x="30" y="330" font-size="9.5" font-weight="700" fill="#d64545" transform="rotate(-90 30 330)">cost and risk rise</text><rect x="76" y="52" width="788" height="76" rx="10" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="2"/><text x="96" y="76" font-size="12.5" font-weight="700" fill="#0fa07f">1 &#183; IMMUTABILITY</text>
    <text x="96" y="97" font-size="9.5" fill="currentColor" opacity="0.92">Nothing to protect. If the value never changes, every thread can read it at once, forever,</text><text x="96" y="112" font-size="9.5" fill="currentColor" opacity="0.92">with no coordination of any kind. Replace the whole object instead of mutating a field.</text>
    <text x="852" y="76" font-size="9" text-anchor="end" font-weight="700" fill="#0fa07f">zero wait &#183; cannot deadlock</text><text x="852" y="112" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.75">frozen config, tuples, a swapped-in snapshot</text>
    <rect x="76" y="140" width="788" height="76" rx="10" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/><text x="96" y="164" font-size="12.5" font-weight="700" fill="#0fa07f">2 &#183; CONFINEMENT</text>
    <text x="96" y="185" font-size="9.5" fill="currentColor" opacity="0.92">One thread owns the data, so there is no concurrent access to coordinate. Thread-local</text><text x="96" y="200" font-size="9.5" fill="currentColor" opacity="0.92">accumulators, per-connection state, or the event loop's single thread (Lessons 4-6).</text>
    <text x="852" y="164" font-size="9" text-anchor="end" font-weight="700" fill="#0fa07f">zero wait &#183; cannot deadlock</text><text x="852" y="200" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.75">measured: 6.9x the throughput of one global lock</text>
    <rect x="76" y="228" width="788" height="76" rx="10" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff" stroke-width="2"/><text x="96" y="252" font-size="12.5" font-weight="700" fill="#7c5cff">3 &#183; MESSAGE PASSING</text>
    <text x="96" y="273" font-size="9.5" fill="currentColor" opacity="0.92">Hand ownership over a queue instead of sharing it. Exactly one thread touches the state;</text><text x="96" y="288" font-size="9.5" fill="currentColor" opacity="0.92">the others send it work. The queue's lock is one you never write or reason about.</text>
    <text x="852" y="252" font-size="9" text-anchor="end" font-weight="700" fill="#7c5cff">bounded queue = backpressure</text><text x="852" y="288" font-size="8.5" text-anchor="end" fill="currentColor" opacity="0.75">queue.Queue, CSP channels, the actor model</text>
    <rect x="76" y="316" width="788" height="86" rx="10" fill="#d64545" fill-opacity="0.11" stroke="#d64545" stroke-width="2"/><text x="96" y="340" font-size="12.5" font-weight="700" fill="#d64545">4 &#183; LOCKING</text>
    <text x="96" y="361" font-size="9.5" fill="currentColor" opacity="0.92">Genuinely shared mutable state, and no way around it. Now you own lock ordering, lock</text><text x="96" y="376" font-size="9.5" fill="currentColor" opacity="0.92">granularity, hold times, and every failure mode in Lesson 10. Reach here last, not first.</text>
    <text x="96" y="393" font-size="9" font-weight="700" fill="#d64545">This is the only rung that can deadlock, livelock, starve, or convoy.</text><text x="852" y="340" font-size="9" text-anchor="end" font-weight="700" fill="#d64545">the only rung with a wait time</text>
    <text x="440" y="436" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">"Do not communicate by sharing memory; instead, share memory by communicating." &#8212; the Go proverb</text>
    <text x="440" y="458" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">Every rung you climb down deletes a class of bug you will never have to debug at 3am.</text>
  </g>
</svg>
```

**1. Immutability.** If a value never changes after construction, there is nothing to protect and every thread can read it at once, forever, with no coordination. Instead of mutating a config object under a lock, build a whole new one and swap the reference. Readers that grabbed the old object keep using a consistent snapshot; new readers get the new one; nobody blocks. Frozen dataclasses, tuples, and persistent data structures are all this idea. Cost: zero. Deadlocks possible: zero.

**2. Confinement.** If exactly one thread can reach the data, there is no concurrent access to coordinate. Thread-local accumulators that merge once at the end (**6.88x** the throughput of the global lock in the Build It, with zero wait), per-connection state owned by the thread handling that connection, or an event loop's single thread ([The Event Loop](../04-the-event-loop/), [Coroutines & async/await](../05-coroutines-and-async-await/)) — where async code needs no lock between `await` points because nothing else can be running. Confinement is often just a matter of *where you declare the variable*.

**3. Message passing.** When state must be shared, hand **ownership** over a queue instead of sharing access to it. One thread owns the structure; every other thread sends it a message and gets a reply. Exactly one thread ever touches the data, so there is nothing to lock — and the queue itself is a well-tested primitive whose locking you never have to reason about. A bounded queue gives you backpressure for free. This is the model behind CSP (Communicating Sequential Processes) channels, the actor model, and the Go proverb worth memorising:

> **"Do not communicate by sharing memory; instead, share memory by communicating."**

**4. Locking.** Only when the state is genuinely shared, genuinely mutable, and none of the above fits. Now you own lock ordering, granularity, hold times, fairness, and every failure mode in Lesson 10. This is the only rung that can deadlock, livelock, starve, or convoy — and the only one with a wait time to measure.

Reaching for the fourth rung first is the single most common concurrency mistake in backend code. Each rung you climb *down* deletes a class of bug you will never have to debug at three in the morning.

## Build It

[`code/locks.py`](code/locks.py) builds all of it with nothing but the standard library: the cost model, a bounded buffer on a `Condition` (correct and deliberately broken), two reader-writer locks, the three granularity strategies, a semaphore-based limiter, a CAS cell, and an instrumented lock. Four excerpts are worth reading inline. The bounded buffer is the canonical `Condition` exercise, and the `use_if_instead_of_while` flag exists purely so the same class can demonstrate the bug:

```python
def get(self) -> object:
    with self._cond:
        if self._buggy:
            if not self._items:            # THE BUG: checked once, never again
                self._cond.wait()
        else:
            while not self._items:         # correct: recheck after every wake
                self._cond.wait()
        item = self._items.popleft()       # IndexError if the predicate lied
        self._cond.notify_all()
        return item
```

The reader-writer lock is one `Condition` plus three integers, and a single boolean flag is the entire difference between a policy that starves writers and one that does not. Note that readers only consult `_waiting_writers` in the writer-preferring mode — that clause *is* the fairness policy:

```python
@contextmanager
def read_locked(self) -> Iterator[None]:
    with self._cond:
        while self._writer or (self._writer_preferring and self._waiting_writers):
            self._cond.wait()
        self._readers += 1
    try:
        yield
    finally:
        with self._cond:
            self._readers -= 1
            if self._readers == 0:
                self._cond.notify_all()
```

Striping is less clever than it sounds, which is the point — one modulo and an array:

```python
k = (i * 7 + tid) % keys
lock = locks[k % stripes]                  # hash the key to one of N locks
t0 = time.perf_counter()
lock.acquire()
mine.append(time.perf_counter() - t0)      # <- the wait time, measured
try:
    shards[k % stripes][k] = content_hash(k)
finally:
    lock.release()
```

And the instrumented lock, which is the piece most worth stealing. The `acquire(blocking=False)` probe is how it separates "was this contended" from "how long did it take", and the statistics need no lock of their own because they are only ever touched by the thread that holds the real one:

```python
def __enter__(self) -> "InstrumentedLock":
    start = time.perf_counter()
    if not self._lock.acquire(blocking=False):    # fast path: was it free?
        self._lock.acquire()
        waited = time.perf_counter() - start
        self.contended += 1
    else:
        waited = time.perf_counter() - start
    self.acquisitions += 1
    self.total_wait += waited
    self.max_wait = max(self.max_wait, waited)
    self._entered_at = time.perf_counter()
    return self
```

Run it:

```bash
python3 locks.py
```

```console
== 1 · WHAT A LOCK COSTS: UNCONTENDED VS CONTENDED ==
  uncontended acquire+release (1,000,000 ops, 1 thread)   =    101.5 ns/op
  contended   acquire+release (240,000 ops, 8 threads) =  11923.9 ns/op
  ratio: a contended acquire costs 118x an uncontended one
    mean time blocked inside acquire() =    88.76 us  (the kernel parked the thread)
    worst single acquire               =     3.10 ms  <- contention shows up in the tail first

  manual acquire + exception -> next thread's acquire(timeout=0.5): got=False after 0.50s  <- the lock is held FOREVER
  `with lock:` + the same exception    -> next thread's acquire(timeout=0.5): got=True after 0.0000s
  same thread acquires Lock twice  -> blocked forever: True
  same thread acquires RLock twice -> succeeded:       True (RLock tracks owner + depth)

== 2 · CONDITION VARIABLES: WAIT IN A `while`, NEVER AN `if` ==
  correct version: 4 producers x 400 items, 4 consumers, capacity 4
    delivered 1,600/1,600 items, no duplicates: True, in 25 ms

  broken version (`if`): 2 consumers waiting, 1 item produced, notify_all()
    consumers that woke and popped an EMPTY buffer: 1/2
    -> IndexError: pop from an empty deque
    (the schedule is forced with a 0.3 s sleep so both consumers are
     provably inside wait() before the single notify_all arrives)
  lost wakeup: notify_all() fired before anyone waited -> never woken: True

== 3 · READ-WRITE LOCKS: THE WIN, THE COST, AND WRITER STARVATION ==
  (a) 100% reads, 2,400 ops over 8 threads, 87 us of real work each
      plain mutex               10,937 ops/s  (0.22s)
      ReaderWriterLock          43,768 ops/s  (0.05s)   4.0x faster

  (b) the same workload with 5% writes mixed in:
      plain mutex               10,938 ops/s  (0.22s)
      RWLock, reader-pref        9,228 ops/s  (0.26s)   0.8x SLOWER than the mutex
      RWLock, writer-pref       27,670 ops/s  (0.09s)   2.5x faster
      ...
  (c) the same 95/5 mix, but the critical section is one dict lookup:
      plain mutex            3,744,424 ops/s  (0.03s)
      ReaderWriterLock         390,196 ops/s  (0.25s)   9.6x SLOWER
      an RWLock is two condition-variable transactions per acquire. Below a
      few microseconds of held time it costs more than the mutex it replaced.

  (d) writer starvation: 6 readers vs 1 writer, over a 1.0 s window:
      reader-preferring      1 writes   max wait   1387.8 ms   median 1387.81 ms
      writer-preferring   9714 writes   max wait      0.4 ms   median    0.00 ms
      fairness bought 9714x the write throughput and cut the worst wait 3661x

== 4 · LOCK GRANULARITY: ONE LOCK, N LOCKS, OR NO LOCK ==
  8 threads x 1,200 writes into a shared index of 64 keys. Each write computes
  a 64 KB content hash (87 us) inside the critical section.

    (a) one global lock          11,004 ops/s   mean wait    327.8 us   total waiting   3.15 thread-seconds
    (b) 16 striped locks         59,931 ops/s   mean wait     12.4 us   total waiting   0.12 thread-seconds
    (c) thread-local + merge     75,712 ops/s   mean wait      0.0 us   total waiting   0.00 thread-seconds

  striping vs one global lock : 5.45x throughput, mean wait cut 26x
  no sharing vs one global lock: 6.88x throughput, zero wait

== 5 · SEMAPHORES: A COUNTER OF PERMITS IS A CAPACITY LIMIT ==
  400 calls, 40 worker threads, dependency degrades past 8 concurrent and refuses past 32
    unbounded                 33 successful calls/s   errors 367/400   peak concurrency 40
                         end-to-end p99   100.4 ms   downstream's own p99   64.1 ms
    BoundedSemaphore(8)    1,894 successful calls/s   errors   0/400   peak concurrency  8
                         end-to-end p99   208.7 ms   downstream's own p99    6.4 ms
    capping concurrency at 8: 56.9x the successful throughput, and the
    downstream's own p99 fell 10.1x.
  release() without acquire():
    Semaphore(2)         -> permits silently grew to 3; nothing told you
    BoundedSemaphore(2)  -> ValueError: Semaphore released too many times

== 6 · LOCK-FREE: COMPARE-AND-SWAP, RETRIES AND ABA ==
  optimistic counter: read; compute (~200 us); CAS; retry. 80 updates/thread.
     threads   final value    retries   retries/update    wasted
           1            80          0             0.00      0.0%
           2           160        111             0.69     41.0%
           4           320        723             2.26     69.3%
           8           640      3,845             6.01     85.7%

  every final value is exact -- CAS never loses an update; it repeats work.
  ABA: thread 1 reads A, thread 2 does A->B->A, thread 1 then swaps
    plain CAS on the value       -> succeeded: True  <- it never saw the change
    CAS on (value, version) tag  -> succeeded: False  (version moved 0 -> 2, so it correctly retries)

== 7 · CONTENTION IS MEASURABLE: INSTRUMENT BEFORE YOU OPTIMIZE ==
  8 threads, 12,000 operations, 0.72s wall clock
  Each operation: ~20 us of lock-free work, then ~8 us inside `hot_index`.
    lock=hot_index  acquisitions= 12,000  contended= 63.0%  mean_wait=  370.5 us  max_wait=   4.57 ms  wait/hold=36.78
    lock=cold_config acquisitions=    233  contended=  0.0%  mean_wait=    0.9 us  max_wait=   0.00 ms  wait/hold= 1.58

  Amdahl, applied to a lock (Lesson 1's formula, now with real inputs):
    work inside hot_index (strictly serial) =   0.12s
    work outside any lock (parallelisable)  =   0.32s
    serial fraction f = 27.1%  ->  with 8 cores the best possible speedup is
    1/(f + (1-f)/8) = 2.76x, and no number of cores takes it past 3.7x.
  Threads spent 4.45s BLOCKED on that lock -- 77% of all thread time.
total runtime 14.9s
```

**Read the numbers — five of these sections are arguments, not demos.**

**Section 1** is the cost model, and the 118x ratio is the whole reason granularity matters. An uncontended acquire at 101.5 ns is genuinely free; you could do ten million of them a second and never notice. The same call under eight-way contention costs 11,923.9 ns because the thread stops being a computation and becomes a scheduling decision, and the tail proves it: a mean wait of 88.76 µs but a worst case of 3.10 ms, thirty-five times the mean. This is why lock contention shows up in your p99 long before it shows up in your average, and why "the average request is fine" is not evidence that a lock is healthy. Note also the honest caveat in the code: CPython's GIL means an *empty* critical section rarely collides at all, so the program lowers the interpreter's thread switch interval to force the interleaving that a genuinely parallel runtime produces for free.

**Section 3 is the argument against cargo-culting an RWLock**, and it is three results, not one. In isolation the RWLock is exactly what the textbook promises: 4.0x on a pure-read workload, because eight readers that never conflict are no longer taking turns. Add 5% writes and the reader-preferring version collapses to **0.8x — slower than the mutex** — which is the surprising one and worth sitting with. It is not that writes are expensive; it is that each writer must wait for the reader count to reach *zero*, new readers keep arriving and walking past it, so writer threads accumulate in a blocked state instead of doing the reads they would otherwise be doing. You lose parallelism to starvation. The writer-preferring variant makes arriving readers queue behind waiting writers and gets 2.5x. Then part (c) removes the last excuse: with a one-dictionary-lookup critical section, the RWLock is **9.6x slower** than the mutex, because two condition-variable transactions per acquire cost far more than the microsecond of work they protect. Part (d) quantifies the starvation directly — **1 write versus 9,714 writes** in the same one-second window, a worst-case wait of 1,387.8 ms versus 0.4 ms.

**Section 4 is the lesson's punchline.** Same threads, same writes, same data — only the lock granularity changes, and throughput goes 11,004 → 59,931 → 75,712. But the number to actually internalise is the wait: **327.8 µs → 12.4 µs → 0.0 µs** per operation, or 3.15 thread-seconds of pure blocking down to zero. That is the causal chain. Throughput did not improve because striping is clever; it improved because threads stopped waiting. Striping works here because 64 keys spread across 16 locks means two threads collide only when their keys land in the same stripe — a bounded, tunable probability rather than a certainty. And thread-local accumulation wins outright because it does not share at all until every thread has finished, at which point the merge runs single-threaded and needs no lock, no ordering, and no wait.

**Section 5 inverts an intuition.** Every instinct says that limiting yourself to 8 concurrent calls when you have 40 threads available must be slower. It was **56.9x faster** in successful throughput, with 367 failures becoming zero. The unbounded version drove peak concurrency to 40 against a dependency that degrades past 8, so it spent its time generating load the dependency converted into latency and then into refusals — work issued, paid for, and thrown away. The cap kept peak concurrency at exactly 8 and the dependency's own p99 at 6.4 ms instead of 64.1 ms. And note the number that got *worse*: end-to-end p99 rose from 100.4 ms to 208.7 ms, because the queue moved into your process. That is the trade, stated honestly — you accept visible, bounded, sheddable queueing in exchange for a dependency that stays alive.

**Section 6 prices lock-freedom.** Retries per update climb 0 → 0.69 → 2.26 → 6.01 as threads go 1 → 2 → 4 → 8, and at 8 threads **85.7% of all the work performed was discarded.** The counter was exact every single time — CAS cannot lose an update — but "lock-free" bought correctness-without-blocking, not speed. **Section 7** then closes the loop: instrumentation says `hot_index` was contended 63.0% of the time with a wait/hold ratio of 36.78, while `cold_config` was contended 0.0%. You now know exactly which lock to shard, and Amdahl tells you what it is worth: a 27.1% serial fraction caps this workload at 2.76x on eight cores.

## Use It

Python's `threading` module ships every primitive you just built:

```python
import threading, queue

lock       = threading.Lock()               # your mutex
rlock      = threading.RLock()              # owner + depth, as you built
sem        = threading.BoundedSemaphore(8)  # capacity limit; raises on over-release
cond       = threading.Condition()          # owns a lock; wait/notify/notify_all
ready      = threading.Event()              # one-shot latch
barrier    = threading.Barrier(8)           # rendezvous for N threads
work       = queue.Queue(maxsize=1000)      # the message-passing answer

def call_downstream(payload):
    with sem:                               # at most 8 in flight, ever
        return http_client.post("/charge", json=payload)

def consumer():
    while True:
        item = work.get()                   # blocks on an internal Condition
        try:
            handle(item)
        finally:
            work.task_done()
```

`queue.Queue` is the one to reach for most often, and it is exactly the bounded buffer from the Build It: an internal lock plus `not_empty` and `not_full` conditions, with the `while` predicate loops already written correctly. `maxsize` gives you backpressure — a full queue blocks producers instead of growing until the process runs out of memory.

**asyncio has twins for all of these** — `asyncio.Lock`, `Semaphore`, `Condition`, `Event`, `Queue` — and there is a bug here that is genuinely common and genuinely painful:

```python
# WRONG: a threading.Lock in async code blocks the whole event loop.
lock = threading.Lock()
async def handler():
    with lock:                       # every other coroutine stops. All of them.
        await db.fetch(...)

# WRONG: an asyncio.Lock is not thread-safe. It assumes one thread.
async_lock = asyncio.Lock()
threading.Thread(target=lambda: asyncio.run(uses(async_lock))).start()

# RIGHT: asyncio primitives in async code, threading primitives in threads.
async_lock = asyncio.Lock()
async def handler():
    async with async_lock:
        await db.fetch(...)          # other coroutines keep running
```

The two families are not interchangeable. `threading` primitives block the **operating system thread**, which in an event loop is every coroutine you have ([The Event Loop](../04-the-event-loop/)). `asyncio` primitives are not thread-safe at all — they coordinate coroutines on one thread and assume no other thread touches them. To hand work from a thread into a loop, use `asyncio.run_coroutine_threadsafe()`; to call blocking code from async, use `asyncio.to_thread()`.

Across processes, `multiprocessing.Lock` and `multiprocessing.Manager` work but cost far more — a manager routes every operation through a proxy over a socket to a server process, so what was 100 ns becomes tens of microseconds. Prefer passing messages over a `multiprocessing.Queue`.

Finally, the layer above: a **distributed lock** in Redis, etcd or ZooKeeper is a fundamentally harder problem, not the same problem over a network. A local mutex cannot be lost while you hold it; a distributed lock is a *lease* with an expiry, and if your process pauses — a long GC, a slow disk, a VM migration — the lease can expire while you still believe you hold it, and a second holder starts working. Correct designs therefore hand out a monotonically increasing **fencing token** with each lock grant, and the resource being protected rejects any write carrying a token older than the newest one it has seen. Distributed consensus takes this apart properly; for now, treat "we'll just use a Redis lock" as a design that needs the same scrutiny as a consensus protocol, because that is what it is.

Production rules that survive contact with a real service:

- **Always `with`.** A manual `acquire()` whose `release()` is skipped by an exception hangs every future thread — measured above as a permanent `False` from `acquire(timeout=0.5)`.
- **Never do I/O inside a lock, and never hold a lock across an `await`.** Both hand your critical section a duration you do not control. Compute outside, take the lock, mutate, release.
- **Prefer a semaphore for capacity and a queue for hand-offs.** If you are using a lock to limit *how many*, you want a `BoundedSemaphore`. If you are using one to hand work between threads, you want a `Queue`.
- **Instrument lock wait time before you change granularity.** Sharding the wrong lock is wasted work that also adds risk; a wait/hold ratio of 36.78 on one lock and 1.58 on another tells you which is which.
- **Default to striping for hot shared maps.** `locks[hash(key) % 16]` is the cheapest 5x you will find, and it keeps single-key operations to one lock, so the deadlock risk does not change.

## Think about it

1. Your service's `hot_index` lock shows a mean wait of 370 µs and a wait/hold ratio of 36. You shard it 16 ways and the ratio drops to 2, but end-to-end p99 barely moves. What are the possible explanations, and which measurement would distinguish them?
2. Section 5 made throughput 56.9x better while making end-to-end p99 twice as bad. Under what circumstances is that a bad trade, and what would you change about the system to avoid having to make it at all?
3. You inherit a class where every public method takes an `RLock`, and the recursion depth reaches 4 in normal operation. Describe the refactor that removes the need for reentrancy, and what you would need to verify about the callers before doing it.
4. A reader-preferring RWLock starved a writer for 1,387 ms; a writer-preferring one bounded the wait at 0.4 ms. Construct a realistic workload where writer-preference is the *wrong* default and reader-preference is correct.
5. CAS retries hit 85.7% waste at 8 threads. At what point does an optimistic retry loop become worse than simply taking a lock, and what would you measure to find that crossover in your own system?

## Key takeaways

- A **mutex** is one atomic instruction when uncontended (**101.5 ns**) and a scheduling event when contended (**11,923.9 ns, 118x**), so contention appears in the tail first — mean wait 88.76 µs, worst single acquire **3.10 ms**. Always use `with`: after a raise inside a manually-acquired lock, the next `acquire(timeout=0.5)` returned **`False`**, permanently.
- A **`Condition`** is the only correct way to wait for a predicate, and the predicate must be rechecked in a **`while` loop, never an `if`** — because `notify_all()` wakes N threads for one item, because another thread can consume it before you reacquire the lock, and because spurious wakeups are permitted by specification. The `if` version popped an empty buffer **1 time out of 2**.
- **Read-write locks are conditional wins, not free ones.** 4.0x on pure reads, but **0.8x — slower than a mutex** — once 5% writes let readers starve the writers, and **9.6x slower** when the critical section is a single dictionary lookup. Fairness policy is the difference between **1 write and 9,714 writes** in one second.
- A **`BoundedSemaphore`** caps concurrency, and capping it made a fragile dependency **56.9x faster in successful throughput with 367 errors becoming 0**, while its own p99 fell 10.1x. It does not speed up the work; it moves the queue out of the dependency and into your process, where end-to-end p99 rose from 100.4 ms to 208.7 ms — visible, bounded, and yours to shed.
- **Granularity is the scalability decision**: 11,004 → 59,931 → 75,712 ops/s for one global lock, 16 striped locks, and thread-local accumulation. The cause is the wait — **327.8 µs → 12.4 µs → 0.0 µs** per operation. Measure it with an instrumented lock (`hot_index`: 63.0% contended, wait/hold **36.78**) before you shard anything, and apply Amdahl to the result: a **27.1% serial fraction caps the workload at 2.76x on eight cores**.
- **Lock-free is not free**: CAS retries rose 0 → 0.69 → 2.26 → 6.01 per update from 1 to 8 threads, wasting **85.7%** of all attempts, and plain CAS is fooled by **ABA** unless you tag the value with a version — the same trick as `WHERE version = $1` in a database. Better still, climb the ladder: **immutability, confinement, message passing, and only then locking.**

Next: [Deadlock, Livelock & Starvation](../10-deadlock-livelock-and-starvation/) — what happens the moment a thread needs a second lock, why lock ordering is the fix, and how to detect the failure modes that a single lock could never produce.
