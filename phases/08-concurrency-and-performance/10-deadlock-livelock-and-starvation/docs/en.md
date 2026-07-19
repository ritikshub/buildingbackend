# Deadlock, Livelock & Starvation

> Lesson 9 told you to make your locks finer-grained. Take that advice and you inherit the worst failure mode in this phase: two threads, two locks, opposite order, and both threads are gone — no exception, no error, no log line, and **0.1% of a core** of CPU while the health check still returns 200. This lesson reproduces that deadlock deterministically, dumps the stuck threads' stacks, builds the wait-for-graph detector that PostgreSQL uses to find it, and then shows that the fix — a total order on locks — costs **30 nanoseconds per transfer**. It also measures the two failure modes that look like deadlock and are not: livelock (37% of a core, 30 attempts, zero work finished) and starvation (18,233 acquisitions per second, one thread getting 224 of them, invisible to p50 and p99).

**Type:** Build
**Languages:** Python
**Prerequisites:** [Locks & Coordination Primitives](../09-locks-and-coordination-primitives/), [Race Conditions & Atomicity](../08-race-conditions-and-atomicity/), [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/)
**Time:** ~80 minutes

## The Problem

You have a bank. Accounts have balances, and money moves between them. In Lesson 8 you learned that `balance -= amount` is not atomic, so you put a lock around it. In Lesson 9 you learned that one global lock serialises your entire service, so you made the locks **finer-grained**: one lock per account. Two transfers touching four different accounts now run genuinely in parallel. This is the correct advice and you should follow it.

Here is the transfer function you wrote:

```python
def transfer(src, dst, amount):
    with src.lock:              # lock the account we're taking from
        with dst.lock:          # lock the account we're giving to
            src.balance -= amount
            dst.balance += amount
```

Read it carefully. It is correct: it never loses money, it never reads a half-updated balance, and every reviewer on your team will approve it. It is also the single most reproduced bug in concurrent programming, and it will take your service down. Two customers press "send" at the same moment. Alice sends 100 to Bob. Bob sends 100 to Alice. Thread 1 runs `transfer(A, B, 100)` and thread 2 runs `transfer(B, A, 100)`. Thread 1 acquires the lock on A. Thread 2 acquires the lock on B. Thread 1 asks for B — held. Thread 2 asks for A — held. Neither will ever release, because releasing requires finishing, and finishing requires the lock the other one is holding.

Now consider what you actually observe. There is no exception, because nothing failed. There is no error log, because no code path ran that logs errors. There is no CPU usage, because both threads are parked in the kernel waiting on a futex — they are not spinning, not retrying, not doing anything at all. Your process is alive. Its memory is stable. `GET /healthz` returns 200 because the health check handler does not touch accounts A or B.

And every subsequent request that needs either account joins the pile. Your thread pool has 32 workers; within a minute all 32 are blocked on the same two locks, and now *every* request stalls, including the health check. Your service did not crash. It **stopped** — which is strictly worse, because a crash gets restarted by your orchestrator in eight seconds and a stall does not.

This lesson is about the three distinct ways a concurrent system stops making progress, how to tell them apart when you are staring at a stalled process at 3am, and — more usefully — about the small number of disciplines that make each one **structurally impossible** rather than merely unlikely.

## The Concept

### The four Coffman conditions

In 1971, Coffman, Elphick and Shoshani published *System Deadlocks* (ACM Computing Surveys 3(2)) and proved something that turns this whole topic from folklore into a checklist. A deadlock requires **all four** of these conditions to hold simultaneously:

1. **Mutual exclusion.** At least one resource is held in a non-shareable mode — only one thread can hold it at a time. This is what a lock *is*.
2. **Hold and wait.** A thread that is already holding at least one resource requests another one, and keeps what it has while it waits.
3. **No preemption.** A resource cannot be taken away from the thread holding it; it is released only voluntarily, by that thread.
4. **Circular wait.** There is a cycle of threads T₁ → T₂ → … → Tₙ → T₁ where each is waiting for a resource held by the next.

All four. Every one of them. And because all four are *necessary*, the practical consequence is the whole reason this decomposition matters:

> **Breaking any single one of the four conditions makes deadlock impossible.** Not unlikely — impossible.

That is a remarkably good deal. You do not have to reason about every interleaving of every thread in your service. You have to pick one condition, remove it structurally, and write down which one you picked. Each of the four maps to a real engineering technique, and the rest of this lesson is organised around them.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="Deadlock drawn as a slab resting on four pillars, one for each Coffman condition: mutual exclusion, hold and wait, no preemption, and circular wait. Each pillar is labelled with the engineering technique that removes it, and the base states that knocking out any single pillar makes deadlock structurally impossible.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Deadlock needs all four. Remove any one and it cannot happen.</text><text x="440" y="42" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.75">Coffman, Elphick &amp; Shoshani, "System Deadlocks", ACM Computing Surveys 3(2), 1971</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="68" y="56" width="744" height="44" rx="8" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/><rect x="68" y="116" width="164" height="196" rx="9" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/><rect x="260" y="116" width="164" height="196" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="452" y="116" width="164" height="196" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/><rect x="644" y="116" width="164" height="196" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/><rect x="68" y="328" width="744" height="38" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.5"/>
    </g>
    <text x="440" y="77" text-anchor="middle" font-size="15" font-weight="700" fill="#d64545">DEADLOCK</text><text x="440" y="92" text-anchor="middle" font-size="9.5" fill="#d64545">holds only while all four pillars stand</text>

    <g text-anchor="middle" fill="currentColor">
      <text x="150" y="140" font-size="11.5" font-weight="700" fill="#7c5cff">MUTUAL EXCLUSION</text><text x="150" y="160" font-size="9" opacity="0.85">only one thread may hold</text><text x="150" y="173" font-size="9" opacity="0.85">the resource at a time</text>
      <text x="150" y="200" font-size="9" font-weight="700" fill="#7c5cff">REMOVE IT BY</text><text x="150" y="217" font-size="9.5">immutable data, single</text><text x="150" y="231" font-size="9.5">ownership, messages, or</text>
      <text x="150" y="245" font-size="9.5">atomic compare-and-swap</text><text x="150" y="272" font-size="8.5" opacity="0.75">the deepest fix: there is</text><text x="150" y="284" font-size="8.5" opacity="0.75">no lock left to contend for</text>
      <text x="150" y="302" font-size="8.5" opacity="0.6">often a redesign</text>

      <text x="342" y="140" font-size="11.5" font-weight="700" fill="#3553ff">HOLD AND WAIT</text><text x="342" y="160" font-size="9" opacity="0.85">keeps what it holds while</text><text x="342" y="173" font-size="9" opacity="0.85">asking for the next one</text>
      <text x="342" y="200" font-size="9" font-weight="700" fill="#3553ff">REMOVE IT BY</text><text x="342" y="217" font-size="9.5">take every lock in ONE</text><text x="342" y="231" font-size="9.5">atomic step, or release</text>
      <text x="342" y="245" font-size="9.5">all of them and restart</text><text x="342" y="272" font-size="8.5" opacity="0.75">the waiter/semaphore fix:</text><text x="342" y="284" font-size="8.5" opacity="0.75">admit at most N-1 claimants</text>
      <text x="342" y="302" font-size="8.5" opacity="0.6">needs the lock set up front</text>

      <text x="534" y="140" font-size="11.5" font-weight="700" fill="#e0930f">NO PREEMPTION</text><text x="534" y="160" font-size="9" opacity="0.85">only the holder may ever</text><text x="534" y="173" font-size="9" opacity="0.85">release a lock</text>
      <text x="534" y="200" font-size="9" font-weight="700" fill="#e0930f">REMOVE IT BY</text><text x="534" y="217" font-size="9.5">acquire(timeout=), then</text><text x="534" y="231" font-size="9.5">release what you hold</text>
      <text x="534" y="245" font-size="9.5">and back off before retry</text><text x="534" y="272" font-size="8.5" opacity="0.75">what a DB does when it</text><text x="534" y="284" font-size="8.5" opacity="0.75">aborts a deadlock victim</text>
      <text x="534" y="302" font-size="8.5" opacity="0.6">LIVELOCK if not randomised</text>

      <text x="726" y="140" font-size="11.5" font-weight="700" fill="#0fa07f">CIRCULAR WAIT</text><text x="726" y="160" font-size="9" opacity="0.85">T1 waits T2 waits ... T1:</text><text x="726" y="173" font-size="9" opacity="0.85">a cycle in the graph</text>
      <text x="726" y="200" font-size="9" font-weight="700" fill="#0fa07f">REMOVE IT BY</text><text x="726" y="217" font-size="9.5">impose a TOTAL ORDER on</text><text x="726" y="231" font-size="9.5">locks; always acquire in</text>
      <text x="726" y="245" font-size="9.5">ascending order, always</text><text x="726" y="272" font-size="8.5" opacity="0.75">the one that scales, and</text><text x="726" y="284" font-size="8.5" opacity="0.75">the one to reach for first</text>
      <text x="726" y="302" font-size="8.5" opacity="0.6">measured: +30 ns/transfer</text>
    </g>

    <text x="440" y="352" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">knock out ANY ONE pillar and deadlock becomes structurally impossible</text><text x="440" y="392" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">This is why deadlock is a checklist, not a mystery: four conditions, four techniques, and you only need one of them to hold.</text><text x="440" y="412" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.9">Pick the one you can enforce and write it down, because an undocumented lock order is not an order at all.</text>
  </g>
</svg>
```

### The wait-for graph

The fourth condition — circular wait — is worth making precise, because "cycle" here is not a metaphor but a graph you can construct at runtime. Build a directed graph in which **nodes are threads**, and draw an edge from T₁ to T₂ when T₁ is blocked waiting for a lock that T₂ currently holds. That is the **wait-for graph**, and the theorem about it is exact: *a cycle in the wait-for graph is a deadlock, and a deadlock is a cycle in the wait-for graph.* Not "suggests", not "usually indicates" — the two statements are equivalent for single-instance resources like mutexes. Which means detecting deadlock is not detective work at all; it is a depth-first search looking for a back-edge, and you will write one in the Build It.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="On the left, a wait-for graph drawn as a closed ring: thread T1 waits for lock acct-B, which is held by thread T2, which waits for lock acct-A, which is held by T1. The loop closes, and that closed loop is the deadlock. On the right, the same four nodes after a total lock order is imposed: T2 waits for acct-A which is held by T1, and T1 wants acct-B which is free, so the chain terminates instead of closing.">
  <defs>
    <marker id="l10-hold" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="l10-wait" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The wait-for graph: a cycle is not a symptom of deadlock, it IS deadlock</text>
    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="16" y="44" width="412" height="330" rx="12" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/><rect x="452" y="44" width="412" height="330" rx="12" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/>
    </g>
    <text x="222" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">BEFORE — each thread locks its own source first</text><text x="658" y="70" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">AFTER — every thread takes acct-A before acct-B</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="169" y="86" width="110" height="34" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/><rect x="293" y="174" width="110" height="34" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/><rect x="169" y="262" width="110" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="45" y="174" width="110" height="34" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/>
    </g>
    <text x="224" y="108" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">T1  A -&gt; B</text><text x="348" y="196" text-anchor="middle" font-size="11" fill="currentColor">lock acct-B</text><text x="224" y="284" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">T2  B -&gt; A</text>
    <text x="100" y="196" text-anchor="middle" font-size="11" fill="currentColor">lock acct-A</text>

    <g fill="none" stroke-width="2">
      <path d="M281 112 L 322 170" stroke="#d64545" stroke-dasharray="6 5" marker-end="url(#l10-wait)"/><path d="M330 212 L 279 260" stroke="#0fa07f" marker-end="url(#l10-hold)"/><path d="M167 270 L 122 212" stroke="#d64545" stroke-dasharray="6 5" marker-end="url(#l10-wait)"/>
      <path d="M118 170 L 167 116" stroke="#0fa07f" marker-end="url(#l10-hold)"/>
    </g>
    <text x="331" y="140" font-size="9.5" fill="#d64545" font-weight="700">waits for</text><text x="337" y="248" font-size="9.5" fill="#0fa07f" font-weight="700">held by</text><text x="112" y="252" font-size="9.5" fill="#d64545" font-weight="700" text-anchor="end">waits for</text>
    <text x="112" y="138" font-size="9.5" fill="#0fa07f" font-weight="700" text-anchor="end">held by</text><text x="224" y="188" text-anchor="middle" font-size="15" font-weight="700" fill="#d64545">CYCLE</text><text x="224" y="206" text-anchor="middle" font-size="10" fill="#d64545">the loop closes</text>
    <text x="222" y="326" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">T1 -&gt; [B] -&gt; T2 -&gt; [A] -&gt; T1</text><text x="222" y="348" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">CIRCULAR WAIT present · both threads 0.1% CPU, forever</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="470" y="122" width="104" height="34" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/><rect x="606" y="122" width="104" height="34" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.6"/><rect x="742" y="122" width="104" height="34" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff"/>
      <rect x="742" y="248" width="104" height="34" rx="8" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>
    <text x="522" y="144" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">T2  B -&gt; A</text><text x="658" y="144" text-anchor="middle" font-size="11" fill="currentColor">lock acct-A</text><text x="794" y="144" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">T1  A -&gt; B</text>
    <text x="794" y="264" text-anchor="middle" font-size="11" font-weight="700" fill="#0fa07f">lock acct-B</text><text x="794" y="278" text-anchor="middle" font-size="9" fill="#0fa07f">FREE</text>
    <g fill="none" stroke-width="2">
      <path d="M576 139 L 600 139" stroke="#d64545" stroke-dasharray="6 5" marker-end="url(#l10-wait)"/><path d="M712 139 L 736 139" stroke="#0fa07f" marker-end="url(#l10-hold)"/><path d="M794 158 L 794 242" stroke="#0fa07f" marker-end="url(#l10-hold)"/>
    </g>
    <text x="588" y="176" text-anchor="middle" font-size="9.5" fill="#d64545" font-weight="700">waits</text><text x="724" y="176" text-anchor="middle" font-size="9.5" fill="#0fa07f" font-weight="700">held by</text><text x="784" y="204" text-anchor="end" font-size="9.5" fill="#0fa07f" font-weight="700">takes next</text>
    <text x="556" y="216" font-size="10" fill="currentColor" opacity="0.9">The chain always ends at a</text><text x="556" y="232" font-size="10" fill="currentColor" opacity="0.9">lock nobody is queued on,</text><text x="556" y="248" font-size="10" fill="currentColor" opacity="0.9">because acct-A is always</text>
    <text x="556" y="264" font-size="10" fill="currentColor" opacity="0.9">taken before acct-B — so</text><text x="556" y="280" font-size="10" fill="currentColor" opacity="0.9">no edge can ever point back.</text><text x="658" y="326" text-anchor="middle" font-size="10.5" font-weight="700" fill="#0fa07f">T2 -&gt; [A] -&gt; T1 -&gt; [B] -&gt; done</text>
    <text x="658" y="348" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.9">CIRCULAR WAIT removed · measured cost +30 ns/transfer</text>

    <text x="440" y="400" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Solid = holds · dashed = waits for. Detecting deadlock is exactly: build this graph, run a DFS, look for a back-edge.</text>
  </g>
</svg>
```

### Lock ordering — the fix that scales

Look at the right-hand panel above and notice what makes the cycle impossible. Every thread takes `acct-A` before `acct-B`, so a thread holding `acct-B` has already got `acct-A` and therefore cannot be *waiting* for it. An edge pointing "backwards" in the ordering can never exist, so no cycle can exist, so no deadlock can exist — not a probabilistic improvement, a proof. Generalise it: **impose a total order on all locks in the program and always acquire them in ascending order.** The order can be anything as long as it is total and stable — an integer id, a name, the memory address, a documented layering of subsystems. In Python:

```python
def transfer(src, dst, amount):
    first, second = (src, dst) if src.id < dst.id else (dst, src)
    with first.lock:
        with second.lock:
            src.balance -= amount
            dst.balance += amount
```

Three practical notes, and the third is the one that bites.

**Order by comparison, not by `sorted()`.** `sorted((src, dst), key=lambda a: a.id)` is the idiom people reach for, and in the Build It it costs **251 ns per transfer, a 58% overhead**, because you pay for a list allocation, a lambda call per element, and Timsort's machinery to order two items. A plain comparison costs **30 ns, 6.9%**. Both are safe; only one belongs in a hot path.

**Documenting the hierarchy matters more than the code.** A total order that lives only in one function's head is not an order. Real systems write it down as a **lock hierarchy**: "cache locks are level 1, index locks level 2, page locks level 3; never acquire a lower level while holding a higher one." That statement can be reviewed, tested, and even asserted at runtime (a debug build can record the levels held by the current thread and blow up on a violation). Linux does exactly this with `lockdep`; it validates the ordering of every lock acquisition observed at runtime and reports a violation the *first* time an out-of-order pair is seen, without needing the deadlock to actually happen.

**The honest limit.** Lock ordering requires you to know the full set of locks you will need, and their relative order, *before* you start acquiring. That assumption fails wherever control leaves your code: a callback invoked under a lock, a plugin, an ORM lifecycle hook, a `__del__`, a logging handler that itself locks. You hand control to code you did not write while holding a lock, and it acquires locks you have never heard of, in an order nobody has documented. This is why the strongest version of the rule is not "order your locks" but **"never call unknown code while holding a lock."**

### The other three remedies

**Attack hold-and-wait.** A thread must never sit on lock A while queuing for lock B. Two ways: acquire the entire set in one atomic step (Python's `contextlib.ExitStack` over a pre-sorted list, or a "lock manager" that hands out all-or-nothing), or use *try-and-release*: attempt the second lock non-blockingly, and if it fails, drop the first one too and start the whole operation over. The dining philosophers' **waiter** — a semaphore that admits at most N−1 claimants — is the elegant version: with only four philosophers reaching for five forks, the pigeonhole principle guarantees someone gets both.

**Attack no-preemption.** You cannot forcibly take a lock from a thread, but the thread can give up. `lock.acquire(timeout=0.05)` returns `False` instead of blocking forever; on failure you release everything you hold, back off, and retry. This is what your database does when it aborts a deadlock victim: it preempts by *rolling back* the transaction, which is only possible because transactions have a defined undo. **Warning, and it is the big one:** naive timeout-and-retry converts a deadlock into a **livelock** — both threads time out at the same moment, both back off by the same constant, both retry at the same moment, and collide again forever. The backoff must be **randomised**. This is not optional; the Build It measures it.

**Attack mutual exclusion.** The deepest fix: arrange for there to be no exclusively-held resource at all. Immutable data needs no lock, because nothing can observe a partial write. Single-threaded ownership — one thread owns a shard of state and everyone else sends it messages — needs no lock, because there is no concurrency at that data. An atomic compare-and-swap needs no lock, because the hardware makes the read-modify-write indivisible. This is Lesson 9's ladder again: *don't share it → make it immutable → make it atomic → and only then reach for a lock.* Every rung removes a class of deadlock permanently rather than managing it.

### Prevention, detection, and avoidance

Three genuinely different strategies, often confused:

**Prevention** — design so a condition cannot hold. Lock ordering, all-at-once acquisition, immutability. Zero runtime cost, zero runtime machinery, and no deadlock can occur. **This is what you do in application code**, and it should be your default.

**Detection and recovery** — allow deadlocks to happen, notice them, and break them by killing someone. This is what **PostgreSQL and MySQL/InnoDB actually do**, because a database cannot impose a lock order on the SQL its users write. Postgres works like this: when a transaction blocks on a lock, it sets a timer of `deadlock_timeout` (default **1 second**). If the lock is still not available when the timer fires, Postgres builds the wait-for graph across all backends, searches it for a cycle, and if it finds one, aborts one transaction — the **victim** — with SQLSTATE `40P01`:

```console
ERROR:  deadlock detected
DETAIL:  Process 18542 waits for ShareLock on transaction 9931; blocked by process 18539.
         Process 18539 waits for ShareLock on transaction 9930; blocked by process 18542.
HINT:  See server log for query details.
```

Note the shape of the `DETAIL`: it is the wait-for cycle, printed. InnoDB does the same thing (`innodb_deadlock_detect`, on by default) and reports error 1213, plus a full dump in `SHOW ENGINE INNODB STATUS`. **The consequence for you** is that your application will receive a deadlock error as a normal, expected outcome of concurrent traffic, and **must retry the whole transaction** — with jitter. A deadlock error is not a bug report; it is the database doing its job. Phase 3's [Transactions & ACID](../../03-relational-databases/11-transactions-and-acid/) and [Isolation, Concurrency & MVCC](../../03-relational-databases/12-isolation-levels-and-mvcc/) are where those locks come from in the first place.

**Avoidance** — the Banker's algorithm (Dijkstra, EWD108/EWD123, 1965). Before granting a lock, the system simulates whether doing so could lead to an unsafe state, and refuses if so. It works, it is elegant, and it is essentially unused in practice because it requires every thread to declare its **maximum resource claim in advance** — and no web request knows which rows it will lock. Learn it for the vocabulary; do not plan to deploy it.

### Dining philosophers, used properly

Dijkstra's dining philosophers (EWD310, 1971) is usually taught as a puzzle. It is more useful as a **lens**: one fixed problem where you can watch three different Coffman conditions being broken and compare the results. Five philosophers sit around a table; between each pair is one fork; to eat, a philosopher needs both adjacent forks. Everyone follows the same rule — pick up the left fork, then the right — and the system stops: each philosopher holds exactly one fork, none can get a second, and there is not one fork left over.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="On the left, five philosophers around a circular table, each holding the fork on one side and waiting for the fork on the other, forming a five-node cycle in which every fork is held and none is free. On the right, three fixes, each breaking a different Coffman condition: asymmetric ordering breaks circular wait, a waiter semaphore breaks hold and wait, and timeout with random backoff breaks no preemption, with the measured meals completed for each.">
  <defs>
    <marker id="l10-pw" markerWidth="9" markerHeight="9" refX="6" refY="2.7" orient="auto"><path d="M0,0 L6.5,2.7 L0,5.4 Z" fill="#d64545"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Dining philosophers: one deadlock, three different conditions to break</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="42" width="380" height="350" rx="12" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/><rect x="412" y="48" width="452" height="104" rx="10" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f"/><rect x="412" y="168" width="452" height="104" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
      <rect x="412" y="288" width="452" height="104" rx="10" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    </g>
    <text x="206" y="68" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">NAIVE — everyone takes left, then right</text>

    <g fill="none" stroke-width="1.8" stroke-linecap="round">
      <path d="M194 124 L 174 154" stroke="#0fa07f"/><path d="M218 124 L 238 154" stroke="#d64545" stroke-dasharray="5 4" marker-end="url(#l10-pw)"/><path d="M293 178 L 258 168" stroke="#0fa07f"/>
      <path d="M300 199 L 277 228" stroke="#d64545" stroke-dasharray="5 4" marker-end="url(#l10-pw)"/><path d="M271 288 L 270 251" stroke="#0fa07f"/><path d="M252 302 L 218 289" stroke="#d64545" stroke-dasharray="5 4" marker-end="url(#l10-pw)"/>
      <path d="M160 302 L 194 289" stroke="#0fa07f"/><path d="M141 288 L 142 251" stroke="#d64545" stroke-dasharray="5 4" marker-end="url(#l10-pw)"/><path d="M113 200 L 135 228" stroke="#0fa07f"/>
      <path d="M120 178 L 154 168" stroke="#d64545" stroke-dasharray="5 4" marker-end="url(#l10-pw)"/>
    </g>

    <g fill="#3553ff" fill-opacity="0.16" stroke="#3553ff" stroke-width="1.8">
      <circle cx="206" cy="106" r="19"/><circle cx="313" cy="183" r="19"/><circle cx="272" cy="309" r="19"/>
      <circle cx="140" cy="309" r="19"/><circle cx="100" cy="183" r="19"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.20" stroke="#e0930f" stroke-width="1.8">
      <circle cx="245" cy="165" r="12"/><circle cx="269" cy="238" r="12"/><circle cx="206" cy="284" r="12"/>
      <circle cx="143" cy="238" r="12"/><circle cx="167" cy="165" r="12"/>
    </g>
    <g text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">
      <text x="206" y="110">P0</text><text x="313" y="187">P1</text><text x="272" y="313">P2</text>
      <text x="140" y="313">P3</text><text x="100" y="187">P4</text>
    </g>
    <g text-anchor="middle" font-size="8" font-weight="700" fill="#e0930f">
      <text x="245" y="168">f1</text><text x="269" y="241">f2</text><text x="206" y="287">f3</text>
      <text x="143" y="241">f4</text><text x="167" y="168">f0</text>
    </g>
    <g text-anchor="middle">
      <text x="206" y="206" font-size="13" font-weight="700" fill="#d64545">DEADLOCK</text><text x="206" y="222" font-size="9" fill="currentColor" opacity="0.9">5 forks, 5 held,</text><text x="206" y="235" font-size="9" fill="currentColor" opacity="0.9">0 left over</text>
    </g>
    <text x="206" y="352" text-anchor="middle" font-size="9.5" fill="currentColor" opacity="0.9">solid = holds · dashed = waits for</text><text x="206" y="372" text-anchor="middle" font-size="10.5" font-weight="700" fill="#d64545">measured: 4 meals, then 5/5 stuck forever</text>

    <g fill="none" stroke-width="1.8" stroke-linejoin="round">
      <rect x="432" y="78" width="46" height="44" rx="8" fill="#0fa07f" fill-opacity="0.18" stroke="#0fa07f"/><rect x="432" y="198" width="46" height="44" rx="8" fill="#3553ff" fill-opacity="0.18" stroke="#3553ff"/><rect x="432" y="318" width="46" height="44" rx="8" fill="#e0930f" fill-opacity="0.18" stroke="#e0930f"/>
    </g>
    <g text-anchor="middle" font-size="11" font-weight="700">
      <text x="455" y="106" fill="#0fa07f">CW</text><text x="455" y="226" fill="#3553ff">H+W</text><text x="455" y="346" fill="#e0930f">N-P</text>
    </g>

    <text x="500" y="78" font-size="11.5" font-weight="700" fill="#0fa07f">ASYMMETRY — P4 reaches right, then left</text><text x="500" y="99" font-size="9.5" fill="currentColor" opacity="0.9">breaks CIRCULAR WAIT: one reversed philosopher is enough</text><text x="500" y="113" font-size="9.5" fill="currentColor" opacity="0.9">to open the ring, so no cycle can ever form.</text>
    <text x="500" y="136" font-size="10" font-weight="700" fill="#0fa07f">measured: 566 meals in 0.6 s, 0 stalls</text>

    <text x="500" y="198" font-size="11.5" font-weight="700" fill="#3553ff">WAITER — a semaphore admits at most 4</text><text x="500" y="219" font-size="9.5" fill="currentColor" opacity="0.9">breaks HOLD-AND-WAIT: with only 4 claimants and 5 forks,</text><text x="500" y="233" font-size="9.5" fill="currentColor" opacity="0.9">someone always gets both. Pigeonhole, not luck.</text>
    <text x="500" y="256" font-size="10" font-weight="700" fill="#3553ff">measured: 827 meals in 0.6 s, 0 stalls</text>

    <text x="500" y="318" font-size="11.5" font-weight="700" fill="#e0930f">TIMEOUT + RANDOM BACKOFF</text><text x="500" y="339" font-size="9.5" fill="currentColor" opacity="0.9">breaks NO-PREEMPTION: acquire(timeout=), then put the fork</text><text x="500" y="353" font-size="9.5" fill="currentColor" opacity="0.9">back down. Without the RANDOM part this becomes livelock.</text>
    <text x="500" y="376" font-size="10" font-weight="700" fill="#e0930f">measured: 1,633 meals, 146 retries, 0 stalls</text>

    <text x="440" y="420" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Identical philosophers in all four runs. Only the acquisition discipline changes — and that alone decides whether anyone eats.</text>
  </g>
</svg>
```

Three fixes, three different conditions removed, and — this is the useful part — **three different performance profiles**. In the Build It, the asymmetric fix eats 566 meals, the waiter 827, and timeout-with-backoff 1,633. They are all correct. They are not all equal, and which one is right depends on your contention level, not on which one is prettiest.

### The shapes deadlock takes in real backend code

You will almost never meet philosophers. You will meet these:

- **ABBA in a transfer, merge, or swap.** Any function that takes two objects of the same type and locks both: `transfer(a, b)`, `merge_accounts(x, y)`, `swap(i, j)`, `link(parent, child)`. Two calls with the arguments reversed is all it takes. If you learn to spot one pattern in this lesson, make it "a function that acquires two locks of the same *kind*".
- **Database row-lock ordering.** Two transactions each update rows 1 and 2, one in ascending id order and one descending. Same ABBA, different substrate. The subtle version: a plain `UPDATE accounts SET ... WHERE id IN (7, 3, 9)` gives the planner no ordering obligation — it may lock rows in index order, in heap order, or in whatever order a parallel scan produces, and the *same statement* run twice can pick different orders under different plans. Force it (see Use It).
- **Thread-pool deadlock.** A task submitted to a pool blocks waiting for the result of another task submitted to the *same* pool. Lesson 7 showed this as a pool exhaustion; name it properly now — it is a **resource deadlock**, where the resource is a pool worker. The parent task holds a worker and waits for a worker; if all workers are parents, no child ever runs.
- **A lock held across a blocking network call.** `with cache_lock: value = http_get(url)`. Fine until that dependency degrades to 30 seconds, at which point one slow upstream becomes a global stall of everything touching `cache_lock`. Not technically a deadlock — it resolves eventually — but operationally identical, and it is how most "the whole service froze" incidents start.
- **`asyncio.Lock` held across an `await`.** `async with lock: await something()` where `something()` (or a task it awaits) needs the same lock. The event loop is alive, the process is responsive, other tasks run — and these two tasks are pending forever. `asyncio.Lock` is **not reentrant**, so a coroutine re-entering its own critical section deadlocks against itself.
- **Self-deadlock.** `threading.Lock` is not reentrant either. A function takes the lock, calls a helper, the helper takes the same lock, and one thread blocks on itself. This one is trivially reproducible and shows up beautifully in a thread dump as a single thread stuck on `acquire`. (`threading.RLock` allows re-entry by the same thread; it is a workaround for a structure problem, not a design goal.)
- **Connection-pool deadlock.** A request checks out a pooled DB connection, begins a transaction, and then — inside that transaction — calls a helper that checks out a *second* connection from the same pool. Under load, every connection is held by a request waiting for a connection. The pool is not broken and nothing is misconfigured; the pool is simply the resource, and hold-and-wait is the condition. Lesson 12 revisits this with numbers.

### Livelock

**Livelock is worse than deadlock in exactly one way: it looks healthier.** A livelocked thread is not blocked. It is running, burning CPU, changing state, taking and releasing locks, incrementing counters, writing log lines — and never finishing anything. The canonical image is two people meeting in a narrow corridor: each steps aside to let the other pass, and because they both step the same way at the same moment they block each other again, and again, politely and energetically, forever.

In code, livelock is almost always the consequence of the fix you applied to deadlock. You added `acquire(timeout=…)` and release-and-retry to break the no-preemption condition. Now both threads time out at the same instant (they started at the same instant and the timeout is a constant), both release, both back off by the same constant, both wake at the same instant, and collide again. Every iteration is real work, thrown away.

The fix is **jitter**: make the backoff random, so the two schedules drift apart and one of them wins. In the Build It, two threads with a fixed backoff make **30 attempts and complete zero work**, burning **37% of a core**. Adding a single `random.uniform(0, 2 * period)` resolves the same workload in **6 attempts**.

If that sounds familiar, it should. It is exactly the exponential-backoff-with-jitter rule from Phase 6's [Retries, Backoff, Dead-Letter Queues & Poison Messages](../../06-messaging-and-pub-sub/08-retries-backoff-and-dead-letter-queues/) and Phase 2's [Idempotency & Safe Retries](../../02-api-design/07-idempotency-safe-retries/). A retry storm is livelock at the scale of a fleet: a thousand clients back off by the same amount, wake together, and stampede a recovering service back down. Two threads or ten thousand clients, the mathematics is identical — **synchronised retries re-synchronise; randomised retries de-synchronise.** Jitter every backoff you ever write.

### Starvation, fairness and priority inversion

**Starvation** is different again: the system as a whole is making excellent progress, and one particular thread never gets to run. There is no cycle and nothing is blocked forever in the deadlock sense — throughput looks great, and one unit of work waits indefinitely. The commonest cause is that **most mutexes are unfair on purpose**. A "fair" lock hands ownership to whoever has waited longest. A "barging" lock hands it to whoever asks next — including a thread that just arrived and never queued at all. Barging is faster, and by a lot: waking the correct queued thread means a context switch and a cache-cold restart, whereas letting the currently-running thread take the lock again costs nothing. So `pthread_mutex`, Java's default `ReentrantLock`, Go's `sync.Mutex` (in normal mode) and Python's `threading.Lock` all permit barging. In the Build It, eight threads hammering one `threading.Lock` for 0.8 s gave **18,233 acquisitions/second** — and the luckiest thread got **5,164** of them while the unluckiest got **224**, whose worst single wait was **291 milliseconds**.

Two related causes worth naming:

- **Reader-preferring RWLocks starve writers.** If new readers may join while a writer waits, a steady stream of readers means the writer never runs. You measured this in Lesson 9. Writer-preferring or phase-fair variants exist precisely for this.
- **Priority inversion.** A low-priority thread L holds a lock that a high-priority thread H needs. H blocks. Then a *medium*-priority thread M — which needs no lock at all — preempts L, because it outranks it. Now H, the most important thread in the system, is effectively waiting on M, the least important. The priority ordering has inverted.

The canonical case is **Mars Pathfinder**, July 1997. The lander began experiencing repeated total system resets on the Martian surface. In the VxWorks real-time OS, a high-priority bus-management task and a low-priority meteorological data task shared a mutex-protected information bus. When the low-priority task held the mutex and was preempted by medium-priority communications work, the high-priority task blocked past its deadline; a watchdog concluded the system was wedged and reset it. The fix, uplinked to Mars, was to enable **priority inheritance** on that mutex — a flag that had been left off. Priority inheritance is the standard remedy: while a high-priority thread is blocked on a lock, the holder temporarily *inherits* the waiter's priority, so it cannot be preempted by medium-priority work and finishes fast. (Glenn Reeves, the JPL flight software lead, published the definitive account in 1997.)

And the honest trade-off in one sentence: **fairness costs throughput.** In the Build It, a hand-written FIFO ticket lock gave every thread within 1× of every other and capped the worst wait at **3.06 ms** instead of **460 ms** — while delivering **60% less throughput**. Fairness is a purchase, not a free upgrade. Buy it where a tail-latency SLO exists; skip it where raw throughput is the goal.

### How you actually find these in production

A deadlocked service produces no error to search for. Your entire toolkit is:

- **Thread and task dumps.** Python: `py-spy dump --pid <PID>` gets you every thread's Python stack from *outside* the process, with no cooperation from a hung interpreter — this is the single most valuable tool in this lesson. Inside the process, `faulthandler.dump_traceback_later(seconds, exit=False)` is a built-in deadlock canary: arm it, and if the timer expires it prints every thread's stack to stderr. JVM: `jstack <pid>`, which additionally runs the deadlock detector for you and prints `Found one Java-level deadlock`. Go: send `SIGQUIT`, or hit `/debug/pprof/goroutine?debug=2`.
- **A progress heartbeat.** The lesson from Phase 9: you cannot alert on the absence of an error. Export a counter that only increments when work *completes* (`orders_processed_total`), and alert on `rate(...) == 0` while `rate(orders_received_total) > 0`. That single alert catches deadlock, livelock, and pool exhaustion equally, because it measures the only thing that actually matters.
- **Lock wait-time instrumentation.** From Lesson 9: a histogram of time spent inside `acquire()`, and a gauge of lock holders. A lock whose wait-time p99 goes vertical while its acquisition rate goes to zero is a deadlock in progress.
- **CPU, read correctly.** This is the fastest discriminator you have and it takes five seconds. Idle process, no progress → deadlock. Busy process, no progress → livelock. Busy process, good aggregate throughput, one starving client → starvation.
- **Database deadlock counters** — `pg_stat_database.deadlocks` in Postgres, `SHOW ENGINE INNODB STATUS` in MySQL. A rising count is normal-ish; a step change means someone shipped a new ordering.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 456" width="100%" style="max-width:840px" role="img" aria-label="Deadlock, livelock and starvation compared side by side. Each panel shows a CPU trace and a progress trace over time, plus the detection signal. Deadlock: CPU falls to zero and progress stops. Livelock: CPU stays high but progress is flat. Starvation: CPU and total progress look healthy, but one thread's progress line never rises.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="24" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Three ways to stop making progress — and how to tell which one you have</text>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="16" y="42" width="276" height="348" rx="12" fill="#d64545" fill-opacity="0.10" stroke="#d64545"/><rect x="302" y="42" width="276" height="348" rx="12" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f"/><rect x="588" y="42" width="276" height="348" rx="12" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff"/>
    </g>
    <text x="154" y="68" text-anchor="middle" font-size="13.5" font-weight="700" fill="#d64545">DEADLOCK</text><text x="440" y="68" text-anchor="middle" font-size="13.5" font-weight="700" fill="#e0930f">LIVELOCK</text><text x="726" y="68" text-anchor="middle" font-size="13.5" font-weight="700" fill="#7c5cff">STARVATION</text>
    <text x="154" y="86" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">threads blocked forever</text><text x="440" y="86" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">threads running forever</text><text x="726" y="86" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">one thread never runs</text>

    <g font-size="8.5" fill="currentColor" opacity="0.7">
      <text x="34" y="106">CPU</text><text x="320" y="106">CPU</text><text x="606" y="106">CPU</text>
      <text x="34" y="196">PROGRESS</text><text x="320" y="196">PROGRESS</text><text x="606" y="196">PROGRESS</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2">
      <path d="M34 166 L 276 166"/><path d="M320 166 L 562 166"/><path d="M606 166 L 848 166"/>
      <path d="M34 258 L 276 258"/><path d="M320 258 L 562 258"/><path d="M606 258 L 848 258"/>
    </g>

    <g fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M36 132 L 70 126 L 96 134 L 112 128" stroke="#d64545"/><path d="M112 128 L 118 164 L 274 164" stroke="#d64545"/><path d="M36 254 L 70 238 L 96 226 L 112 220 L 274 220" stroke="#d64545"/>
      <path d="M322 132 L 350 124 L 378 134 L 406 122 L 434 132 L 462 122 L 490 134 L 518 124 L 546 132 L 560 126" stroke="#e0930f"/><path d="M322 254 L 350 238 L 378 228 L 396 224 L 560 224" stroke="#e0930f"/><path d="M608 130 L 636 122 L 664 132 L 692 122 L 720 132 L 748 122 L 776 132 L 804 122 L 832 130 L 846 126" stroke="#7c5cff"/>
      <path d="M608 254 L 650 232 L 700 208 L 760 182 L 846 156" stroke="#0fa07f"/><path d="M608 254 L 660 251 L 720 250 L 790 249 L 846 248" stroke="#d64545" stroke-dasharray="5 4"/>
    </g>
    <path d="M115 118 L 115 224" fill="none" stroke="currentColor" stroke-width="1.2" stroke-dasharray="4 4" opacity="0.6"/>
    <text x="122" y="116" font-size="8.5" fill="#d64545" font-weight="700">the lock cycle closes</text><text x="277" y="160" font-size="8.5" fill="#d64545" text-anchor="end" opacity="0.9">0%</text><text x="565" y="140" font-size="8.5" fill="#e0930f" text-anchor="end" opacity="0.9">stays busy</text>
    <text x="846" y="150" font-size="8.5" fill="#0fa07f" text-anchor="end" font-weight="700">7 lucky threads</text><text x="846" y="268" font-size="8.5" fill="#d64545" text-anchor="end" font-weight="700">the 8th thread</text>

    <g fill="none" stroke="currentColor" stroke-opacity="0.35" stroke-width="1.2">
      <path d="M34 274 L 276 274"/><path d="M320 274 L 562 274"/><path d="M606 274 L 848 274"/>
    </g>
    <g font-size="9" fill="currentColor">
      <text x="34" y="294" font-weight="700" fill="#d64545">MEASURED</text><text x="34" y="309" opacity="0.9">0.1% of a core, 1.06 s in</text><text x="34" y="322" opacity="0.9">0 transfers completed</text>
      <text x="34" y="341" font-weight="700" fill="#d64545">FIND IT WITH</text><text x="34" y="356" opacity="0.9">a thread dump: two threads</text><text x="34" y="369" opacity="0.9">stopped on an acquire line</text>

      <text x="320" y="294" font-weight="700" fill="#e0930f">MEASURED</text><text x="320" y="309" opacity="0.9">37% of a core, 30 attempts</text><text x="320" y="322" opacity="0.9">0 units of work finished</text>
      <text x="320" y="341" font-weight="700" fill="#e0930f">FIND IT WITH</text><text x="320" y="356" opacity="0.9">CPU high, throughput zero,</text><text x="320" y="369" opacity="0.9">retry counters climbing</text>

      <text x="606" y="294" font-weight="700" fill="#7c5cff">MEASURED</text><text x="606" y="309" opacity="0.9">18,233 acq/s — looks fine!</text><text x="606" y="322" opacity="0.9">one thread got 224 of them</text>
      <text x="606" y="341" font-weight="700" fill="#7c5cff">FIND IT WITH</text><text x="606" y="356" opacity="0.9">p50/p99 = 0.000 ms, max =</text><text x="606" y="369" opacity="0.9">460 ms. Per-thread counts.</text>
    </g>

    <text x="440" y="416" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">All three present as "the service stopped". Check CPU first: idle means deadlock, busy-with-no-throughput means livelock.</text><text x="440" y="436" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Starvation is the cruel one — every aggregate metric looks healthy, because the victim barely appears in the sample.</text>
  </g>
</svg>
```

## Build It

Six demonstrations, standard library only. The design constraint is unusual and worth stating: **this program deliberately creates hangs, and must never hang.** Every hanging demo runs in **daemon threads** behind a **watchdog** — a bounded `join(timeout=…)` or a progress poll — so the main thread always regains control, prints its diagnosis, and moves on. Daemon threads still deadlocked when `main()` returns are abandoned by the interpreter, which is why the process exits 0 in 9 seconds despite containing seven permanently blocked threads.

The ABBA reproduction is the naive transfer with a `sleep` between the two acquisitions. The sleep is not cheating — it guarantees the interleaving that in production happens by chance under load, making the failure deterministic instead of once-a-week:

```python
def transfer_naive(src, dst, amount, hold):
    with src.lock:
        time.sleep(hold)              # any real work here; the sleep just makes it certain
        with dst.lock:                # <- both threads park here, forever
            src.balance -= amount
            dst.balance += amount
```

The interesting part is the diagnosis, because in production that is all you get. `sys._current_frames()` maps every thread id to its current frame, and a thread blocked inside `lock.acquire()` is inside a C call — so its innermost *Python* frame is the exact line that asked for the lock:

```python
def dump_thread_stacks(threads, depth=2):
    frames = sys._current_frames()
    for th in threads:
        frame = frames.get(th.ident)
        print(f"    Thread {th.name!r} — alive={th.is_alive()}, using no CPU:")
        for fr in traceback.extract_stack(frame)[-depth:]:
            print(f"      {os.path.basename(fr.filename)}:{fr.lineno} in {fr.name}()")
            print(f"          {(fr.line or '').strip()}")
```

The wait-for graph detector is a `LockManager` that records two dictionaries — who holds each lock, and which lock each thread is currently blocked on — around a real acquisition. Recording the wait *before* blocking is the whole trick:

```python
def acquire(self, name):
    me = threading.current_thread().name
    with self._book:
        lk = self._locks.setdefault(name, threading.Lock())
        self.waiter[me] = name             # "I am about to block on `name`"
    lk.acquire()
    with self._book:
        self.waiter.pop(me, None)
        self.holder[name] = me
```

Cycle detection is then a walk. Each waiting thread has exactly one outgoing edge — to the holder of the lock it wants — so "DFS" degenerates to following the chain until you either run out of edges or step onto a node you have already visited:

```python
def find_cycle(self):
    edges = {}                              # thread -> (lock, thread holding it)
    for th, lk in waiting.items():
        owner = holder.get(lk)
        if owner is not None:
            edges[th] = (lk, owner)         # owner == th means self-deadlock
    for start in edges:
        path, seen, node = [], set(), start
        while node in edges and node not in seen:
            seen.add(node)
            lk, nxt = edges[node]
            path.append((node, lk))
            node = nxt
        if node in seen:                    # we walked back onto the path: a cycle
            head = next(i for i, (t, _) in enumerate(path) if t == node)
            return path[head:]
    return None
```

That is a miniature of what Postgres runs when `deadlock_timeout` fires, minus multi-granularity locks and the victim-selection heuristics.

The livelock demo needs one piece of care. Two threads must fail *at the same time* for the lockstep to be visible, so each thread holds its first lock for a moment before testing the second, and — critically — holds it for another moment after the test fails, before releasing. Without that second pause the losing thread releases before the other one looks, and one of them accidentally succeeds:

```python
first.acquire()
time.sleep(HOLD)                    # do a little work holding just one lock
if second.acquire(blocking=False):
    progress[idx] += 1              # got both: the whole task completes
    ...
time.sleep(HOLD)                    # decide to give up (still holding `first`)
first.release()                     # polite: release what I hold and retry
spin(WASTED_WORK)                   # redo the state we abandoned: real CPU burn
next_wake += PERIOD + (rng.uniform(0.0, 2 * PERIOD) if jitter else 0.0)
time.sleep(max(0.0, next_wake - time.monotonic()))
```

The last two lines are the entire experiment. With `jitter=False` both threads advance on the same absolute schedule and re-collide every round. With `jitter=True` their schedules perform independent random walks and separate almost immediately.

Finally, the fair lock. A ticket lock is the smallest correct FIFO mutex: take a number, wait until it is called:

```python
class TicketLock:
    def acquire(self):
        with self._cv:
            mine = self._next_ticket
            self._next_ticket += 1
            while self._now_serving != mine:
                self._cv.wait()

    def release(self):
        with self._cv:
            self._now_serving += 1
            self._cv.notify_all()               # O(waiters) wakeups: this is the cost
```

`notify_all()` is where the throughput goes. Every release wakes every waiter, each checks whether its ticket came up, and all but one go back to sleep. That is the price of the ordering guarantee, and the Build It puts a number on it.

The rest — the philosophers' four strategies, the ordering microbenchmark, the starvation harness — is in [`code/deadlock.py`](code/deadlock.py). Run it:

```bash
python3 deadlock.py
```

```console
Deadlock, livelock & starvation — Phase 8, Lesson 10
python 3.12.13  ·  seed 20260718  ·  every hang is watchdogged

== 1 · ABBA DEADLOCK: THE SAME CODE, TWO DIRECTIONS, NO ERROR ==
  watchdog fired: still blocked 1.06s after start — 2/2 threads never returned (they never will).
  No exception was raised. No log line was written. Nothing crashed.
  Balances are unchanged and both transfers are lost: acct-A=1000 acct-B=1000
  A thread dump is the only evidence that exists:
    Thread 'transfer-A->B' — alive=True, using no CPU:
      threading.py:1012 in run()
          self._target(*self._args, **self._kwargs)
      deadlock.py:82 in transfer_naive()
          with dst.lock:                # <- both threads park here, forever
    Thread 'transfer-B->A' — alive=True, using no CPU:
      threading.py:1012 in run()
          self._target(*self._args, **self._kwargs)
      deadlock.py:82 in transfer_naive()
          with dst.lock:                # <- both threads park here, forever
  Read it: both threads are on the SAME line — the second acquisition —
  and each one holds the lock the other is asking for. That is the cycle.

== 2 · LOCK ORDERING: THE FIX, AND WHAT IT COSTS ==
  SAFETY  8 threads x 25,000 attempts over 6 accounts, every direction:
    166,684 transfers in 0.70s = 237,496/s   deadlocks: 0   money conserved: 6000/6000 -> True
  COST    one thread, 250,000 two-lock transfers, best of 3:
    unordered (deadlocks!)     430 ns/transfer   baseline
    sorted(key=lambda)         681 ns/transfer    +251 ns/transfer (+58.3%)
    one comparison             460 ns/transfer     +30 ns/transfer (+6.9%)
  Ordering is nearly free. sorted() with a key lambda is not — order by comparison.

== 3 · THE WAIT-FOR GRAPH: FINDING THE CYCLE AUTOMATICALLY ==
  holders: {'acct-A': 'T1', 'acct-B': 'T2'}
  waiters: {'T1': 'acct-B', 'T2': 'acct-A'}
  DEADLOCK DETECTED — cycle of length 2:
    T2 -> [acct-A] -> T1 -> [acct-B] -> T2
  recovery: abort a victim (T1) and let it retry. That is precisely
  what Postgres reports as: ERROR  deadlock detected / DETAIL Process X waits...

== 4 · DINING PHILOSOPHERS: THREE FIXES, THREE COFFMAN CONDITIONS ==
  strategy      breaks               meals   retries  outcome
  naive         nothing                  4         0  STALLED: 0 meals for 0.25s, 5/5 threads never returned
  asymmetric    circular wait          566         0  943 meals/s, no stall
  waiter        hold-and-wait          827         0  1,378 meals/s, no stall
  backoff       no-preemption        1,633       146  2,722 meals/s, no stall
  the stalled table: 5/5 philosophers hold their left fork and wait
  for their right — one 5-node cycle in the wait-for graph, no fork left over.
  All four run identical philosophers. Only the acquisition discipline differs.

== 5 · LIVELOCK: RUNNING FLAT OUT, GOING NOWHERE — AND THE ONE-LINE CURE ==
  fixed backoff   :   30 attempts, 0/2 threads made progress,  184.0ms CPU /   501ms wall  =  37% of a core
  + random jitter :    6 attempts, 2/2 threads made progress,   24.8ms CPU /   208ms wall  =  12% of a core
  the fixed pair took and released locks 60 times and finished nothing;
  jitter finished the same work in 6 attempts. uniform(0, 2*period) is the whole fix.
  compare section 1's DEADLOCK: 0.7ms CPU over 1056ms wall = 0.1% of a core.
  Same symptom (no progress), opposite signal (busy vs idle). Check CPU first.

== 6 · STARVATION: MOST MUTEXES ARE UNFAIR ON PURPOSE ==
  8 threads hammering one lock, 50us critical section, 0.8s each
  threading.Lock (barging, the default):  18,233 acq/s
      acquisitions per thread : [224, 279, 549, 961, 1764, 1782, 3877, 5164]   (23x spread)
      unluckiest thread       : 224 acquisitions, its worst single wait 291.4 ms
      wait over ALL samples   : p50  0.000 ms   p99  0.000 ms   max  460.53 ms
  TicketLock (FIFO, hand-built):  7,217 acq/s
      acquisitions per thread : [707, 707, 707, 707, 707, 708, 708, 830]   (1x spread)
      unluckiest thread       : 707 acquisitions, its worst single wait 2.7 ms
      wait over ALL samples   : p50  1.018 ms   p99  1.631 ms   max    3.06 ms
  the trade: FIFO costs 60% of throughput and buys a 150x shorter worst-case wait.
  Note the barging lock's percentiles: the starved thread contributes almost
  no samples, so it is invisible to p50 and p99. Only the MAX and the
  per-thread counts show it. Aggregate latency metrics cannot see starvation.

All sections complete in 9.0s. Deadlocked daemon threads are abandoned; the process exits cleanly.
```

**Read the numbers — four of these sections are arguments, not demos.**

**Section 1 is the shape of the incident, not the bug.** The bug is boring; the *evidence* is the lesson. After 1.06 seconds the watchdog reports two threads that never returned, and everything you would normally debug with is absent: no exception, no log line, balances still `1000/1000` so not even a partial write to notice. The only artefact is the thread dump — and read what it says. Both threads are stopped at **`deadlock.py:82`**, the *same line*, `with dst.lock:`. That is the signature: when two threads in a real dump are parked on the same acquisition line, or on two acquisition lines in the same function, you are looking at a lock cycle and can stop investigating anything else. Note also the CPU figure from section 5 — **0.7 ms over 1,056 ms of wall time, 0.1% of a core.** A deadlocked process is the *least* busy process on the box.

**Section 2 prices the fix, and the price is the point.** The safety half runs 8 threads doing 166,684 transfers in every direction across 6 accounts — the exact workload that deadlocked in section 1 — with **zero deadlocks** and money conserved at **6000/6000**. It is not "less likely to deadlock"; the ordering makes the cycle unconstructible. The cost half isolates what the discipline costs, single-threaded so GIL scheduling noise cannot flip the result: an unordered two-lock transfer takes **430 ns**, and adding a comparison to order the pair takes it to **460 ns — 30 ns, or 6.9%.** That is the entire price of never deadlocking again.

Now look at the middle row, because it is the trap. The idiomatic `sorted((a, b), key=lambda x: x.id)` costs **681 ns — 251 ns of overhead, 58.3%**: same guarantee, eight times the cost, for two items. You pay for a list allocation, two lambda invocations, and a general-purpose sort to order a pair. On a path that runs a hundred thousand times a second that is real money. Write the comparison.

**Section 4 shows the fixes are not interchangeable.** Identical philosophers, identical forks, identical eating time; only the acquisition discipline changes. The naive table manages **4 meals** and then stops with **5/5 philosophers holding their left fork** — and the detail that makes the topology click is *no fork left over*. Five forks, five held, zero available: the cycle consumes exactly all of them, which is why adding a sixth fork (or removing one philosopher) fixes it too. Then the three correct disciplines: asymmetry **566 meals**, the waiter semaphore **827**, timeout-plus-backoff **1,633** with **146 retries**. All three are correct. The 2.9× spread between the slowest and fastest is a real engineering decision, not noise — the asymmetric fix serialises the two philosophers who now contend for the same first fork, the waiter caps concurrency at 4 by construction, and the backoff strategy lets everyone try freely and pays for collisions after the fact. High contention favours the waiter; low contention favours backoff.

**Section 5 is the discrimination test you will actually use at 3am.** Two threads, a fixed backoff, and a cap of 15 attempts each: **30 attempts, 0 units of progress, 60 lock acquire/release pairs, and 184 ms of CPU over 501 ms of wall time — 37% of a core.** Nothing is blocked. Everything is running. Nothing gets done. Change one expression — `uniform(0, 2 * period)` — and the same workload finishes in **6 attempts**. That is the entire fix for a failure mode that looks, on a dashboard, like healthy load.

Now put the two CPU numbers side by side, because this is the payoff: **deadlock 0.1% of a core, livelock 37% of a core, both with zero throughput.** Identical symptom, opposite signal. If your stalled service is idle you are looking for a lock cycle and you want a thread dump. If it is busy you are looking for a retry loop and you want to know what is being retried and whether the backoff is randomised. Five seconds of `top` picks the branch.

**Section 6 measures the cost of fairness and then delivers the sting.** Eight threads, one lock, 0.8 seconds. The default `threading.Lock` achieves **18,233 acquisitions/second** and distributes them `[224, 279, 549, 961, 1764, 1782, 3877, 5164]` — a **23× spread**, with the unluckiest thread waiting **291 ms** for a critical section that takes 50 microseconds. The hand-built ticket lock distributes them `[707, 707, 707, 707, 707, 708, 708, 830]` — perfectly even — and caps the worst wait at **3.06 ms**, a **150× improvement in the tail**, for **60% less throughput**. That is the fairness/throughput trade in numbers: you buy a bounded tail with two thirds of your throughput.

And now the sting, which is the most important line in the whole run. Look at the barging lock's percentiles: **p50 = 0.000 ms, p99 = 0.000 ms, max = 460.53 ms.** Your monitoring would report this lock as flawless. The starving thread is invisible to every percentile *because it barely appears in the sample* — a thread that acquires 224 times contributes 224 measurements out of 14,500, so it cannot move a p99 no matter how badly it suffers. Starvation is the one failure in this lesson that aggregate latency metrics structurally cannot see. To detect it you need **per-thread (or per-tenant, or per-client) counts**, not distributions over everything.

## Use It

In production most of this is a discipline rather than a library, but there are concrete tools.

**Python locks and the built-in deadlock canary.**

```python
import faulthandler, threading

# Arm a canary at startup: if this timer ever expires, dump every thread's stack
# to stderr and keep running. Re-arm it from your main loop on every healthy tick.
faulthandler.dump_traceback_later(30, repeat=True, exit=False)

lock = threading.Lock()
if not lock.acquire(timeout=0.25):          # never block forever on a user-facing path
    raise ResourceBusy("could not acquire account lock in 250ms")
try:
    ...
finally:
    lock.release()
```

`dump_traceback_later()` is your `dump_thread_stacks()` from the Build It, except it runs from a watchdog thread and works even when the interpreter is wedged. `PYTHONFAULTHANDLER=1` is related but different — it installs handlers for fatal signals, so `kill -ABRT <pid>` yields a traceback; keep it on everywhere. For a process you cannot modify, `py-spy dump --pid <PID>` reads the stacks from outside with no cooperation at all, and is the first command to run on a stalled Python service.

**Databases: expect deadlocks, retry them.**

```sql
-- Postgres knobs. deadlock_timeout is how long a lock wait must last before the
-- detector runs (it is a detection delay, NOT a limit on how long you may wait).
SHOW deadlock_timeout;    -- default 1s
SET lock_timeout = '3s';        -- give up waiting for a lock after 3s
SET statement_timeout = '10s';  -- give up on the whole statement after 10s

-- Bulk updates: never let the planner choose the row order.
BEGIN;
SELECT id FROM accounts WHERE id = ANY($1) ORDER BY id FOR UPDATE;
UPDATE accounts SET balance = balance + $2 WHERE id = ANY($1);
COMMIT;
```

The `ORDER BY id ... FOR UPDATE` is the same total-order fix as `transfer()`, applied to rows: every transaction locks the same set of rows in the same sequence, so no cycle can form. Belt and braces is to sort the id list in the application before you send it, so the ordering does not depend on a planner decision. And every write path needs a retry wrapper:

```python
from sqlalchemy.exc import DBAPIError
import random, time

def with_deadlock_retry(fn, attempts=4, base=0.05):
    for i in range(attempts):
        try:
            return fn()
        except DBAPIError as exc:
            if getattr(exc.orig, "pgcode", None) != "40P01" or i == attempts - 1:
                raise
            time.sleep(random.uniform(0, base * 2 ** i))   # JITTER, always
    raise AssertionError("unreachable")
```

SQLSTATE `40P01` is Postgres' `deadlock_detected`; MySQL raises error 1213. Treat both as **routine, expected outcomes** of concurrency — log them at INFO with a counter, alert only on the *rate*, and never page a human for one. **asyncio has its own version of all of this:**

```python
lock = asyncio.Lock()

async def bad():
    async with lock:
        await http_client.get(url)      # holds the lock across the network. Don't.

async def good():
    payload = await http_client.get(url)    # do the I/O first
    async with lock:
        state.update(payload)               # hold the lock only over the state change
```

An asyncio deadlock looks different from a threaded one: the loop is alive, other tasks run normally, the process is responsive — and two tasks are `pending` forever. Diagnose it with `asyncio.all_tasks()` plus `task.get_stack()`, or run with `loop.set_debug(True)` and `PYTHONASYNCIODEBUG=1`, which warns about coroutines that block the loop. Remember `asyncio.Lock` is not reentrant, and that `asyncio.timeout()` / `wait_for` are your `acquire(timeout=)`.

Production rules that survive contact with reality:

- **Define a global lock order and write it down.** In the module docstring, in `ARCHITECTURE.md`, in a comment above every lock. An order that only one engineer knows is not an order. Never acquire a second lock while holding one unless the pair appears in that document.
- **Never do I/O under a lock.** No HTTP, no database call, no file write, no logging to a slow handler, no `print` to a pipe nobody reads. Compute outside the lock, mutate inside it. This single rule prevents more production stalls than every other rule in this lesson combined.
- **Never call code you do not own while holding a lock** — no callbacks, no plugin hooks, no ORM lifecycle events, no user-supplied comparators. You cannot order locks you have never heard of.
- **Always use a timeout on lock acquisition in any code path reachable from a user request.** An unbounded `acquire()` in a request handler is a promise to hang forever. A `TimeoutError` you can return as a 503 is strictly better than a thread that never comes back.
- **Jitter every backoff, everywhere, without exception.** Lock retries, database deadlock retries, HTTP retries, reconnect loops, cache refreshes. A constant backoff is a synchronisation primitive you did not mean to build.
- **Expose a progress heartbeat.** A counter that increments only on completed work, and an alert on "received > 0 and completed == 0". It is the only signal that catches deadlock, livelock, and pool exhaustion with one rule.
- **Watch per-thread/per-tenant counts, not just percentiles.** As section 6 proved, starvation is invisible to p50 and p99 by construction. If fairness matters, measure the distribution across actors, not the distribution across requests.

## Think about it

1. Lock ordering requires knowing all your locks up front, which callbacks break. You maintain a plugin API where third-party code runs inside a callback that you invoke while holding a lock. You cannot see their locks and they cannot see yours. Which of the four Coffman conditions can you still attack, and what does the API have to look like?
2. Section 6 showed a barging lock with `p50 = p99 = 0.000 ms` and `max = 460 ms`. Suppose that lock guards a per-tenant rate limiter in a multi-tenant API. What does the starving thread correspond to in business terms, what would the affected customer report, and what would your dashboard show them while they reported it?
3. Your database is throwing 30 deadlock errors an hour and your retry wrapper handles them all; users see nothing. Your colleague wants to page on any deadlock. You want to page on none. Construct the alert you would both accept, and say what it measures.
4. The naive philosophers deadlocked with 5 forks and 5 philosophers, and no fork left over. Adding a sixth fork fixes it. Removing one philosopher fixes it. Explain both in terms of the wait-for graph, and then say what the general form of "add one more resource" is — and why it is usually a worse fix than lock ordering.
5. You convert every unbounded `lock.acquire()` in your service to `lock.acquire(timeout=0.1)` with a retry, and deploy. Deadlocks stop. Two weeks later, under peak load, the service becomes unresponsive with 100% CPU and no errors in the logs. What did you build, what is the smallest change that fixes it, and what would you have measured to predict this before deploying?

## Key takeaways

- **Deadlock requires all four Coffman conditions** — mutual exclusion, hold-and-wait, no preemption, circular wait — so **breaking any one of them makes it impossible**, not merely rare. That turns a scary topic into a four-item checklist, and each item maps to a real technique: don't share, acquire-all-at-once, timeout-and-back-off, or impose a total lock order.
- **A cycle in the wait-for graph is not evidence of deadlock; it is the definition.** The Build It's 40-line `LockManager` found `T2 -> [acct-A] -> T1 -> [acct-B] -> T2` by DFS — the same algorithm Postgres runs when `deadlock_timeout` (default 1 s) fires, before aborting a victim with SQLSTATE `40P01`. Your application must **retry database deadlocks with jitter** as a normal outcome, not treat them as bugs.
- **Lock ordering is the fix that scales, and it is nearly free**: 8 threads ran 166,684 bidirectional transfers with **zero deadlocks** and money conserved, and ordering by comparison cost **30 ns per transfer (+6.9%)** over the unsafe version. Order with a comparison, not `sorted(key=lambda …)`, which cost **251 ns (+58.3%)** for the identical guarantee. And document the hierarchy — an undocumented order is not an order.
- **Livelock is deadlock's fix gone wrong, and it looks healthier than the disease.** Two threads with a *constant* backoff made **30 attempts, 60 lock operations and zero progress while burning 37% of a core**; one `random.uniform(0, 2*period)` finished the same work in **6 attempts**. A deadlocked pair burned **0.1% of a core** over the same wall time — identical symptom, opposite signal, so **check CPU first**. It is the same mathematics as retry storms: constant backoff re-synchronises, jitter de-synchronises.
- **Most mutexes are unfair by design because fairness costs throughput.** A barging `threading.Lock` gave **18,233 acq/s** but split them `[224 … 5164]` across eight threads with a **291 ms** worst wait; a FIFO ticket lock gave a perfectly even split and a **3.06 ms** worst wait — a **150× better tail for 60% less throughput**. Priority inversion is the pathological case (Mars Pathfinder, 1997), and **priority inheritance** is its fix.
- **Starvation is structurally invisible to percentiles.** The starved thread's own p50 and p99 were **0.000 ms** because it contributed 224 samples out of 14,500. Only `max` and per-thread counts revealed it. Monitor deadlock with a **progress heartbeat** (`completed == 0 while received > 0`), livelock with **CPU-versus-throughput**, and starvation with **per-actor distributions** — no single metric catches all three.

Next: [Backpressure, Queueing & Load Shedding](../11-backpressure-and-load-shedding/) — what to do when the work arriving genuinely exceeds what you can complete, so that the queue in front of your now-deadlock-free locks does not become the next way your service stops.
