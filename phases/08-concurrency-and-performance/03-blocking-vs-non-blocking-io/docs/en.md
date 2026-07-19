# Blocking vs Non-Blocking I/O: select, poll & epoll

> A parked thread costs zero CPU — that is the good news and the trap. It still costs 8 MiB of reserved address space and 16.2 µs every time the scheduler touches it, so 10,000 idle WebSocket connections cost you 78 GiB of address space and 162 ms of pure scheduler work per wakeup round to do *nothing*. This lesson traces one `recv()` into the kernel to show exactly where that bill comes from, then rebuilds the same server on one thread with `selectors` and measures it: 600 requests in 116.6 ms on a single thread against 235.6 ms on 150, and an `epoll_wait()` that costs 0.9 µs whether it watches 11 descriptors or 1,001 while `select()` climbs to 40.7 µs and then refuses to run at all.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Processes, Threads & the GIL](../02-processes-threads-and-the-gil/), [Transport Layer: TCP vs UDP](../../01-networking-and-protocols/05-transport-layer-tcp-vs-udp/)
**Time:** ~85 minutes

## The Problem

Lesson 2 ended with a clean result: threads are the wrong tool for CPU-bound work and the right tool for I/O-bound work. A thread that is waiting on the network releases the GIL (Global Interpreter Lock, the mutex that lets only one Python thread execute bytecode at a time), so while it waits, the others run. Waiting is what a backend does almost all of the time. So the obvious server design writes itself, and it is the design every tutorial ships:

```python
while True:
    conn, addr = listener.accept()
    threading.Thread(target=handle, args=(conn,)).start()   # one thread per connection
```

This is a genuinely good design and it will carry you a long way. Then you ship a feature that changes the *shape* of your traffic rather than its volume — a WebSocket for live updates, a long-poll endpoint, a mobile app that holds a keep-alive socket open so push notifications arrive instantly. Overnight your connection count stops tracking your request rate. You now have **10,000 connections** open and perhaps **50 requests per second** flowing through them. Every connection is almost always idle. Almost always, but not predictably: any one of them may speak at any moment, so you cannot close them, and you cannot know in advance which one it will be.

The thread-per-connection design says: 10,000 connections, 10,000 threads. Price that with the numbers this lesson's code measures on the machine you are reading this on.

**Memory.** A thread needs a stack, and the stack size is set by `RLIMIT_STACK` — **8.0 MiB** here, the near-universal Linux default. That is *reserved* address space, not resident memory: the kernel maps it lazily, so a thread that only ever runs a shallow `recv()` loop touches very little of it. Section 3 measures the difference. Resident cost is **15.8 KiB per thread**; reserved cost is the full 8 MiB. Ten thousand threads:

```text
reserved   10,000 × 8.0 MiB   =  78.1 GiB of virtual address space
resident   10,000 × 15.8 KiB  = 153.9 MiB of real RAM, before a single byte is served
```

The 154 MiB is survivable; the 78 GiB is what bites. On a 64-bit machine you have the address space, but you will hit `vm.max_map_count`, `/proc/sys/kernel/threads-max`, cgroup accounting that charges you for mappings, and a glibc allocator holding a per-thread arena. Servers rarely die of resident memory at 10,000 threads — they die of `pthread_create: Resource temporarily unavailable` somewhere between 5,000 and 30,000, and where exactly is a property of your container's limits, not your program.

**Scheduling.** This is the cost people miss. Lesson 2 measured the price of a context switch by ping-ponging a byte between two threads; section 3 of this lesson re-measures it the same way and gets **32.47 µs per round trip, so ~16.2 µs per wakeup** (confirmed by `ru_nvcsw`: 20,072 voluntary context switches for 10,000 round trips — exactly two per trip, as it must be). Now imagine a broadcast: one event that every connection cares about, so all 10,000 threads must be woken.

```text
10,000 wakeups × 16.2 µs = 162.3 ms of pure scheduler work
```

That is 162 ms during which your CPUs are executing the *scheduler*, not your handler. Spread across 10 cores it is still ~16 ms of overhead per broadcast, which caps you at a few tens of broadcasts per second before the machine is doing nothing but changing its mind about what to do. And the work each thread then performs is one `send()` of a few hundred bytes.

That is the whole shape of the problem. **The work per connection is nearly zero. The cost of having a thread standing by to do it is enormous.** This has a name — the **C10K problem**, from Dan Kegel's 1999 write-up of the same arithmetic on hardware 25 years slower — and the answer is not a bigger machine or a smaller stack size. The answer is to stop asking the kernel "wake me when *this one* socket has data" ten thousand separate times, and start asking it "wake me when *any* of these ten thousand sockets has data, and tell me which."

## The Concept

### What "blocking" means at the syscall level

Before we can replace blocking, we have to be precise about what it is, because almost everyone's mental model is subtly wrong. Follow one `recv()` all the way down.

Your code calls `data = sock.recv(4096)`. That becomes a **system call** — a controlled jump from your process into the kernel, which is the only piece of software allowed to touch the network card. The kernel looks in this socket's **receive buffer**, a chunk of kernel memory where bytes that have already arrived from the network sit waiting for you to collect them. Two things can happen.

If there are bytes there, the kernel copies up to 4,096 of them into your buffer and returns immediately — roughly a microsecond. If the buffer is empty, the interesting case, the kernel does **not** spin waiting for a packet. It puts your thread on a **wait queue** attached to that socket, marks it `TASK_INTERRUPTIBLE` (Linux's term for "asleep, but wakeable"), and takes it **off the run queue** — the list the scheduler picks from. A thread that is not on it is not a candidate to run, ever, until something puts it back. The scheduler picks someone else, and your thread ceases to exist as far as the CPU is concerned.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 486" width="100%" style="max-width:840px" role="img" aria-label="A timeline of one blocking recv call across three lanes: the user thread, the kernel, and the network card. The thread issues recv, the socket receive buffer is empty, so the kernel takes the thread off the run queue and it consumes no CPU at all. A packet later arrives, the interrupt handler and softirq copy it into the socket buffer, the kernel marks the thread runnable, the scheduler takes about 17 microseconds to run it, and recv finally returns. Almost all the elapsed time is spent parked, not computing.">
  <defs>
    <marker id="l03-arr" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l03-arrp" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7c5cff"/></marker>
    <marker id="l03-arrb" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#3553ff"/></marker>
    <marker id="l03-arrg" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#7f7f7f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One blocking recv(): the thread is parked, not spinning</text>

    <rect x="120" y="44" width="180" height="32" rx="8" fill="#3553ff" fill-opacity="0.14" stroke="#3553ff" stroke-width="2"/>
    <rect x="390" y="44" width="180" height="32" rx="8" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff" stroke-width="2"/>
    <rect x="660" y="44" width="180" height="32" rx="8" fill="#7f7f7f" fill-opacity="0.14" stroke="#7f7f7f" stroke-width="2"/>
    <text x="210" y="65" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">USER THREAD</text><text x="480" y="65" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">KERNEL</text><text x="750" y="65" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7f7f7f">NIC / PEER</text>

    <g stroke-width="1.4" stroke-dasharray="5 6" opacity="0.55">
      <line x1="210" y1="76" x2="210" y2="408" stroke="#3553ff"/>
      <line x1="480" y1="76" x2="480" y2="408" stroke="#7c5cff"/>
      <line x1="750" y1="76" x2="750" y2="408" stroke="#7f7f7f"/>
    </g>

    <text x="14" y="98" font-size="9" font-weight="700" fill="currentColor" opacity="0.6">TIME SPENT</text>

    <line x1="215" y1="112" x2="472" y2="112" stroke="#3553ff" stroke-width="2" marker-end="url(#l03-arrb)"/>
    <text x="343" y="106" text-anchor="middle" font-size="10" fill="currentColor">recv(fd, buf, 4096)</text><text x="14" y="116" font-size="9.5" fill="currentColor" opacity="0.8">~1 us</text>

    <rect x="388" y="124" width="188" height="30" rx="6" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f" stroke-width="1.6"/>
    <text x="482" y="143" text-anchor="middle" font-size="9.5" fill="currentColor">receive buffer is EMPTY</text>

    <line x1="472" y1="168" x2="218" y2="168" stroke="#7c5cff" stroke-width="2" marker-end="url(#l03-arrp)"/>
    <text x="345" y="162" text-anchor="middle" font-size="10" fill="currentColor">off the run queue</text>

    <rect x="126" y="180" width="168" height="116" rx="8" fill="#d64545" fill-opacity="0.13" stroke="#d64545" stroke-width="2"/>
    <text x="210" y="204" text-anchor="middle" font-size="12" font-weight="700" fill="#d64545">PARKED</text><text x="210" y="224" text-anchor="middle" font-size="9.5" fill="currentColor">TASK_INTERRUPTIBLE</text><text x="210" y="242" text-anchor="middle" font-size="9.5" fill="currentColor">not runnable</text>
    <text x="210" y="264" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">0% CPU</text><text x="210" y="282" text-anchor="middle" font-size="9.5" font-weight="700" fill="currentColor">0 syscalls</text>

    <text x="14" y="212" font-size="9.5" font-weight="700" fill="#d64545">ALL of it</text><text x="14" y="228" font-size="9" fill="currentColor" opacity="0.8">ms to</text><text x="14" y="242" font-size="9" fill="currentColor" opacity="0.8">seconds</text>
    <text x="14" y="262" font-size="9" fill="currentColor" opacity="0.8">and it is</text><text x="14" y="276" font-size="9" fill="currentColor" opacity="0.8">FREE</text>

    <line x1="742" y1="252" x2="490" y2="252" stroke="#7f7f7f" stroke-width="2" marker-end="url(#l03-arrg)"/>
    <text x="616" y="246" text-anchor="middle" font-size="10" fill="currentColor">packet arrives -&gt; hardware IRQ</text>

    <rect x="374" y="266" width="216" height="46" rx="6" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff" stroke-width="1.6"/>
    <text x="482" y="284" text-anchor="middle" font-size="9.5" fill="currentColor">softirq: TCP stack copies</text><text x="482" y="300" text-anchor="middle" font-size="9.5" fill="currentColor">bytes into the socket buffer</text>

    <line x1="472" y1="330" x2="300" y2="330" stroke="#7c5cff" stroke-width="2" marker-end="url(#l03-arrp)"/>
    <text x="386" y="324" text-anchor="middle" font-size="10" font-weight="700" fill="#0fa07f">wake_up(): RUNNABLE</text>

    <rect x="126" y="342" width="168" height="30" rx="6" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f" stroke-width="1.6"/>
    <text x="210" y="361" text-anchor="middle" font-size="9.5" fill="currentColor">back on the run queue</text><text x="14" y="356" font-size="9.5" font-weight="700" fill="#0fa07f">16.2 us</text><text x="14" y="370" font-size="9" fill="currentColor" opacity="0.8">measured</text>

    <line x1="472" y1="396" x2="218" y2="396" stroke="#3553ff" stroke-width="2" marker-end="url(#l03-arrb)"/>
    <text x="345" y="390" text-anchor="middle" font-size="10" font-weight="700" fill="#3553ff">recv() returns 4096 bytes</text><text x="14" y="400" font-size="9.5" fill="currentColor" opacity="0.8">~1 us</text>

    <rect x="120" y="418" width="640" height="30" rx="7" fill="#3553ff" fill-opacity="0.09" stroke="#3553ff" stroke-width="1.4" stroke-opacity="0.5"/>
    <text x="440" y="437" text-anchor="middle" font-size="10" fill="currentColor">Blocking costs you a THREAD, not a CPU. 10,000 parked threads burn 0% CPU and 78 GiB of address space.</text>

    <text x="440" y="472" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The thread is not spinning — it is descheduled. That is why the bill is memory and scheduling, never cycles.</text>
  </g>
</svg>
```

Later, a packet arrives. The network card raises a **hardware interrupt**; the kernel's interrupt handler grabs the frame, and a deferred handler (a *softirq* on Linux) runs the TCP stack over it, checks the sequence numbers, and appends the payload to that socket's receive buffer. Having done so, it walks the socket's wait queue and calls `wake_up()` on everyone parked there — which marks your thread `TASK_RUNNING` and puts it back on the run queue. The scheduler gets to it when it gets to it (the **16.8 µs** measured above, on an unloaded machine — much worse on a busy one), your thread resumes inside the kernel exactly where it left off, copies the bytes out, and `recv()` returns.

Read that back and notice what did *not* happen: at no point did your thread execute a single instruction while waiting. **It was parked, not spinning.** This is the single most important fact in this lesson, and it explains the exact shape of the bill:

- Blocking wastes **memory** — every parked thread holds a stack.
- Blocking wastes **scheduling capacity** — every parked thread is an entry in kernel data structures, and waking it costs real microseconds.
- Blocking wastes **no CPU at all** while it is blocked.

So "blocking I/O is slow" is wrong as stated. Blocking I/O is *efficient per operation* and *unscalable per connection*. At 200 connections, thread-per-connection is a great design and you should probably use it. The problem is 10,000.

### Non-blocking mode alone is worse than useless

The obvious first move is to change the contract. Every file descriptor has an `O_NONBLOCK` flag (`sock.setblocking(False)` in Python sets it via `fcntl`), and it changes exactly one thing: **instead of parking, an operation that cannot proceed returns an error immediately.** That error is `EAGAIN`, also spelled `EWOULDBLOCK` — on Linux they are the same number, 11 — and Python raises it as `BlockingIOError`.

`EAGAIN` **is not a failure** and says nothing about the connection's health. It means exactly "nothing to do on this descriptor right now, ask again later" — treating it as an error and closing the socket is a bug people ship. So, having made your socket non-blocking, what do you do? The naive answer is to try again:

```python
while True:
    try:
        data = sock.recv(4096)
        break
    except BlockingIOError:
        pass          # nothing yet — go round again
```

This is a **busy loop** (or *spin loop*), and it is strictly worse than blocking. You have converted a free park into a paid spin. Section 2 of the Build It measures the exact price of receiving one message that arrives 250 ms in the future: the blocking version burns **0.0 ms of CPU** — it rounds to nothing — and the busy loop burns **249.5 ms of CPU**, 98.8% of one core saturated for a quarter of a second, issuing **238,776 failed `recv()` syscalls**, about **945,000 per second**, every one of which crosses into the kernel, checks an empty buffer, and comes back with "nothing." It is a machine working flat out to produce nothing, and it will do that for every idle connection you own.

Adding `time.sleep(0.001)` is the reflex fix and is also wrong: you have added a millisecond of latency to every message, you still wake 1,000 times a second per connection to ask a question whose answer is almost always no, and at 10,000 connections you are back to 10 million pointless syscalls a second.

**Non-blocking mode by itself solves nothing.** It is half a mechanism: it provides *"let me act without committing my thread"* and lacks *"tell me when acting would be worthwhile."*

### Readiness notification is the missing half

Here is the pivot the whole lesson turns on. What you actually want to ask the kernel is not "does *this* socket have data?" — you want to ask, once, about all of them:

> Here are 10,000 file descriptors. Park me. Wake me when **any** of them can be read or written without blocking, and tell me **which ones**.

That is **readiness notification**, and it is what `select`, `poll`, `epoll` (Linux) and `kqueue` (BSD and macOS) exist to provide. One thread, one blocking call, all of your connections. The blocking has not gone away — you still park, and parking is still free. What changed is that **one parked thread now covers every connection you have**: 10,000 stacks collapse into one stack plus 10,000 small dictionary entries. This design is the **event loop**, or **reactor pattern**; lesson 4 builds one properly, and this lesson builds the raw version so it is not magic when you meet it.

### select → poll → epoll: the same idea, three times

The interface has been reinvented twice, and knowing why is the difference between using `epoll` and understanding it.

**`select(2)`** is the original, from 4.2BSD (1983). You pass three `fd_set`s — read, write, exceptional — each a **bitmap** with one bit per descriptor number. It has three structural problems:

1. **`FD_SETSIZE`.** The bitmap is a fixed-size array, `1024` bits on glibc. A descriptor numbered ≥ 1024 cannot be represented *at all*. It is a compile-time constant in libc, not a tunable — raising `ulimit -n` does not help, because the limit is the width of the bitmap, not the number of open files. Section 4 hits this wall and it is a `ValueError`, not a slowdown.
2. **The set is destroyed on return.** `select()` overwrites your `fd_set`s with the results, so you must rebuild all three from scratch and copy them into the kernel on *every single call*.
3. **O(n) on both sides.** The kernel scans every descriptor you passed to check its state, and you scan every descriptor you passed to find out which ones came back. With 10,000 descriptors and one ready, both of you do 10,000 units of work to deliver one event.

**`poll(2)`** (System V, standardised in POSIX) fixes problem 1. Instead of a bitmap you pass an array of `struct pollfd`, so there is no `FD_SETSIZE` and no ceiling on descriptor numbers, and it separates the requested events from the returned events so you do not have to rebuild the array each time. Problem 3 remains untouched: the array still crosses the user/kernel boundary in full on every call, and both sides still scan all of it.

**`epoll(7)`** (Linux 2.5.44) and **`kqueue(2)`** (FreeBSD 4.1) fix problem 3, with the same key insight: **separate registration from waiting.**

```text
epoll_create1()          create a kernel object that holds an interest list
epoll_ctl(ADD/MOD/DEL)   register a descriptor ONCE — it stays registered
epoll_wait()             block; return ONLY the descriptors that are ready
```

Because the interest list lives in the kernel across calls, nothing is copied per call. And because the kernel registers a callback on each socket's wait queue at `epoll_ctl` time, a packet arriving does not just wake sleepers — it *appends that socket to a ready list*. `epoll_wait()` then hands you the ready list. Its cost is **O(number of ready descriptors)**, not O(number watched. Section 4 measures both curves: `select()` goes 1.0 → 4.6 → 20.7 → 40.7 µs as the watched set grows from 11 to 1,001 descriptors, while `epoll_wait()` stays flat at **0.8–0.9 µs** across the whole range, because exactly one descriptor is ready every time.

`kqueue` gets there by a more general route: a unified event queue for sockets, files, signals, timers and process events, where `kevent()` both registers and waits in one call. Python's `selectors` picks it automatically on macOS and the BSDs.

### Level-triggered vs edge-triggered

`epoll` and `kqueue` offer two notification modes, and choosing the wrong one produces a bug that is invisible under light load and catastrophic under real traffic.

**Level-triggered (LT)** is the default and the one `select` and `poll` have always used. It reports **a state**: "this descriptor is readable *right now*." As long as any unread byte remains in the receive buffer, every wait will report it again. Consequence: a partial read is completely safe. You read 1 KiB out of 8 KiB, return to the loop, and the next wait tells you again.

**Edge-triggered (ET)** (`EPOLLET`, or `EV_CLEAR` on kqueue) reports **a transition**: "something *arrived* since I last told you." You get one notification per arrival, whether you consume one byte or all of them. Consequence: **if you do not drain the descriptor until it returns `EAGAIN`, the remaining bytes become invisible.** No further event is coming, because no further arrival has occurred. The connection hangs — not with an error, just silently forever — while the peer waits for a reply to a request that is sitting complete in your kernel buffer.

Section 5 shows both against 8,192 buffered bytes read 1,024 at a time. Level-triggered reports ready on all four waits and lets you drain incrementally. Edge-triggered reports ready once, and after a single 1,024-byte read the other **7,168 bytes are stranded** — waits 2, 3 and 4 report nothing at all. Done correctly, the ET reader loops on `recv()` until it raises `BlockingIOError` (**8 calls, 8,192 bytes, then `EAGAIN`**), which is what re-arms the notification.

So why use ET at all? Fewer syscalls at very high event rates, and it composes better with multi-threaded loops (`EPOLLONESHOT` hands a descriptor to exactly one thread). The rule that keeps you honest: **edge-triggered requires non-blocking descriptors and a drain-until-`EAGAIN` loop on every read and write.** If you will not write that loop everywhere, use level-triggered — whose failure mode is far milder, a *busy* loop if you register `EVENT_WRITE` on a socket with nothing to send, since "writable" is almost always true. That is why the Build It asks for write-readiness only when the output queue is non-empty.

### Readiness vs completion — and why disk I/O is different

Everything above is **readiness-based**: the kernel tells you that an operation *would not block*, and you then perform it yourself. Your thread does the copy from kernel memory to your buffer, and your thread is busy while that happens. That is what makes `select`/`poll`/`epoll`/`kqueue` **synchronous** despite feeling asynchronous.

**Completion-based** interfaces invert this. You *submit* the operation up front — "read 4 KiB from this descriptor into that buffer" — and the kernel performs all of it, including the copy, then tells you it is **done**. Windows **IOCP** (I/O Completion Ports) has worked this way since NT 3.5; Linux **`io_uring`** (5.1, 2019) brought it over via a pair of shared memory ring buffers, and in `SQPOLL` mode a kernel thread polls your submission ring so a busy server can do I/O with **zero syscalls**.

Where this stops being an aesthetic preference is **disk I/O**, and the reason is the most useful non-obvious fact in this lesson:

> **A regular file is always "ready".** Ask `epoll` whether a file on disk is readable and it says yes — instantly, unconditionally, even if the data is on spinning rust and the read will park your thread for 10 ms. Readiness is meaningless for something that has no notion of "not yet arrived."

So `epoll` cannot do asynchronous disk I/O — not an oversight, just the wrong question for storage. This is why every readiness-based runtime (libuv, Node, Netty, older Go) implements file I/O by handing it to a **thread pool** and blocking real threads in it, why an event-loop server reading an uncached file can stall every connection it owns, and exactly the gap `io_uring` closes: being completion-based, `read()` on a regular file is a first-class async operation with no thread pool behind it.

### The four I/O models, precisely

This is where most engineers' mental model is muddled, so be exact. Two independent axes:

- **Blocking vs non-blocking** — does the *call* park your thread, or return immediately?
- **Synchronous vs asynchronous** — does *your thread* perform the data copy, or does the kernel perform it and notify you afterwards?

They are orthogonal, and the crucial consequence is that **non-blocking is not asynchronous**. `select`, `poll`, `epoll` and `kqueue` are all *synchronous* — you still call `recv()` yourself.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 516" width="100%" style="max-width:840px" role="img" aria-label="A two by two taxonomy of input and output models. The columns are blocking, where the call parks the calling thread, and non-blocking, where the call returns immediately. The rows are synchronous, where your thread performs the data copy, and asynchronous, where the kernel performs it and reports completion. Plain blocking recv and select, poll, epoll and kqueue multiplexing both sit in the synchronous blocking quadrant; O_NONBLOCK recv returning EAGAIN and signal driven SIGIO sit in synchronous non-blocking; Windows IOCP sits in asynchronous blocking; and io_uring sits in asynchronous non-blocking. Readiness is not completion.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">The 2×2: non-blocking is not the same thing as asynchronous</text>

    <rect x="196" y="46" width="322" height="34" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.6"/>
    <rect x="530" y="46" width="322" height="34" rx="8" fill="#7f7f7f" fill-opacity="0.10" stroke="#7f7f7f" stroke-width="1.6"/>
    <text x="357" y="61" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">BLOCKING</text><text x="357" y="75" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">the call parks your thread until it can act</text><text x="691" y="61" text-anchor="middle" font-size="11.5" font-weight="700" fill="currentColor">NON-BLOCKING</text>
    <text x="691" y="75" text-anchor="middle" font-size="9" fill="currentColor" opacity="0.85">the call returns right now, EAGAIN if idle</text>

    <rect x="16" y="92" width="170" height="170" rx="8" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.6"/>
    <text x="101" y="152" text-anchor="middle" font-size="11.5" font-weight="700" fill="#3553ff">SYNCHRONOUS</text><text x="101" y="176" text-anchor="middle" font-size="9" fill="currentColor">YOUR thread does</text><text x="101" y="190" text-anchor="middle" font-size="9" fill="currentColor">the kernel-to-user</text>
    <text x="101" y="204" text-anchor="middle" font-size="9" fill="currentColor">copy, and is busy</text><text x="101" y="218" text-anchor="middle" font-size="9" fill="currentColor">while it happens</text>

    <rect x="16" y="274" width="170" height="170" rx="8" fill="#7c5cff" fill-opacity="0.10" stroke="#7c5cff" stroke-width="1.6"/>
    <text x="101" y="334" text-anchor="middle" font-size="11.5" font-weight="700" fill="#7c5cff">ASYNCHRONOUS</text><text x="101" y="358" text-anchor="middle" font-size="9" fill="currentColor">the KERNEL does</text><text x="101" y="372" text-anchor="middle" font-size="9" fill="currentColor">the copy and tells</text>
    <text x="101" y="386" text-anchor="middle" font-size="9" fill="currentColor">you when the bytes</text><text x="101" y="400" text-anchor="middle" font-size="9" fill="currentColor">are ALREADY yours</text>

    <rect x="196" y="92" width="322" height="170" rx="10" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff" stroke-width="2"/>
    <text x="212" y="114" font-size="10.5" font-weight="700" fill="#3553ff">blocking I/O</text><text x="212" y="132" font-size="9.5" fill="currentColor">recv(fd) parks until one socket speaks.</text><text x="212" y="148" font-size="9.5" fill="currentColor">Simple; costs a thread per connection.</text>
    <line x1="212" y1="162" x2="502" y2="162" stroke="#3553ff" stroke-width="1.2" stroke-opacity="0.4"/>
    <text x="212" y="184" font-size="10.5" font-weight="700" fill="#3553ff">I/O multiplexing — READINESS</text><text x="212" y="202" font-size="9.5" fill="currentColor">select / poll / epoll / kqueue.</text><text x="212" y="218" font-size="9.5" fill="currentColor">One thread parks until ANY of 10,000</text>
    <text x="212" y="234" font-size="9.5" fill="currentColor">fds is ready — then YOU still call recv().</text><text x="212" y="252" font-size="9" font-weight="700" fill="#0fa07f">This lesson lives here.</text>

    <rect x="530" y="92" width="322" height="170" rx="10" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="2"/>
    <text x="546" y="114" font-size="10.5" font-weight="700" fill="#e0930f">non-blocking I/O</text><text x="546" y="132" font-size="9.5" fill="currentColor">O_NONBLOCK recv() → EAGAIN, retry.</text><text x="546" y="148" font-size="9.5" fill="currentColor">Alone it is a busy loop: measured</text>
    <text x="546" y="164" font-size="9.5" font-weight="700" fill="#d64545">238,776 failed syscalls in 250 ms.</text>
    <line x1="546" y1="178" x2="836" y2="178" stroke="#e0930f" stroke-width="1.2" stroke-opacity="0.4"/>
    <text x="546" y="200" font-size="10.5" font-weight="700" fill="#e0930f">signal-driven I/O</text><text x="546" y="218" font-size="9.5" fill="currentColor">SIGIO: the kernel raises a signal when</text><text x="546" y="234" font-size="9.5" fill="currentColor">the fd turns readable — then YOU read.</text>
    <text x="546" y="252" font-size="9" fill="currentColor" opacity="0.8">Rare: signals do not queue reliably.</text>

    <rect x="196" y="274" width="322" height="170" rx="10" fill="#7c5cff" fill-opacity="0.11" stroke="#7c5cff" stroke-width="2"/>
    <text x="212" y="296" font-size="10.5" font-weight="700" fill="#7c5cff">completion, waited on</text><text x="212" y="316" font-size="9.5" fill="currentColor">Windows IOCP:</text><text x="212" y="332" font-size="9.5" fill="currentColor">GetQueuedCompletionStatus() parks</text>
    <text x="212" y="348" font-size="9.5" fill="currentColor">until an operation you SUBMITTED</text><text x="212" y="364" font-size="9.5" fill="currentColor">has finished. It hands you bytes,</text><text x="212" y="380" font-size="9.5" fill="currentColor">not permission to go get bytes.</text>
    <text x="212" y="404" font-size="9.5" fill="currentColor">io_uring in IORING_ENTER_GETEVENTS</text><text x="212" y="420" font-size="9.5" fill="currentColor">mode behaves the same way.</text>

    <rect x="530" y="274" width="322" height="170" rx="10" fill="#0fa07f" fill-opacity="0.11" stroke="#0fa07f" stroke-width="2"/>
    <text x="546" y="296" font-size="10.5" font-weight="700" fill="#0fa07f">completion, polled</text><text x="546" y="316" font-size="9.5" fill="currentColor">Linux io_uring: push reads onto the</text><text x="546" y="332" font-size="9.5" fill="currentColor">submission ring, peek the completion</text>
    <text x="546" y="348" font-size="9.5" fill="currentColor">ring, never block, one syscall for many</text><text x="546" y="364" font-size="9.5" fill="currentColor">operations — or zero in SQPOLL mode.</text><text x="546" y="388" font-size="9.5" font-weight="700" fill="#0fa07f">Works for REGULAR FILES.</text>
    <text x="546" y="406" font-size="9.5" fill="currentColor">epoll cannot: a disk file is always</text><text x="546" y="422" font-size="9.5" fill="currentColor">"ready", so readiness says nothing.</text>

    <rect x="16" y="452" width="836" height="50" rx="7" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.6"/>
    <text x="434" y="472" text-anchor="middle" font-size="10.5" font-weight="700" fill="currentColor">READINESS ≠ COMPLETION.</text><text x="434" y="490" text-anchor="middle" font-size="10.5" fill="currentColor">Everything in the top row is synchronous: the kernel says the copy will not block — you still do the copy.</text>
  </g>
</svg>
```

The classic enumeration (Stevens, *UNIX Network Programming*, Vol. 1, ch. 6) lists five models, and all five fit the grid above: blocking I/O, non-blocking I/O, I/O multiplexing, signal-driven I/O, and asynchronous I/O. The first four are all synchronous — only the fifth moves the copy into the kernel. One line each:

- **Blocking** — `sock.recv(4096)` on a default socket. Parks. One thread per connection.
- **Non-blocking** — `sock.setblocking(False); sock.recv(4096)` → `EAGAIN`. You must poll. 238,776 wasted syscalls in 250 ms.
- **Multiplexed** — `sel.select()` parks on 10,000 descriptors at once and returns the ready ones; **you still call `recv()`**.
- **Signal-driven** — `fcntl(fd, F_SETFL, O_ASYNC)` and the kernel sends `SIGIO` when the descriptor turns readable; **you still call `recv()`**. Rare, because standard signals do not queue and can be lost.
- **Asynchronous** — `io_uring_prep_read()` / IOCP `ReadFile` with an `OVERLAPPED`. You are told when the bytes are already in your buffer.

### Partial reads and partial writes

This section is not optional theory; it is the number one source of bugs when people write their first non-blocking server, and it is a direct consequence of what TCP actually is.

TCP is a **byte stream**, not a message service. It preserves order and it preserves bytes; it preserves nothing else. It does not know where your messages begin or end, and it is free to split and merge as it likes.

- **`recv()` may return a fragment.** You sent 12 KiB in one `sendall()`; the receiver may see 4,096 bytes, then 4,096, then 3,000, then 1,096 — or one byte at a time. Code that assumes one `recv()` returns one message is broken and merely happens to pass tests where messages fit in one segment. You need a per-connection **input buffer**: append every fragment, then repeatedly extract whole messages using an explicit **framing** rule (a delimiter or a length prefix).
- **`send()` may accept fewer bytes than you gave it.** The send buffer is finite, and if the peer reads slowly, TCP flow control shrinks the window to zero and the kernel cannot take more. `send()` returns what it took, which may be less than you asked — or `EAGAIN` on a non-blocking socket with a full buffer. You need a per-connection **output queue**: keep the remainder, register `EVENT_WRITE`, and finish when the socket becomes writable.

The blocking API hides both of these behind `sendall()`, which loops internally, and behind the ability to just call `recv()` again on your own stack. Once you have one thread for everything, **you cannot loop — looping would block every other connection.** Both loops have to be turned inside out into state that persists across event-loop iterations. Section 3 measures how often this actually matters: in 600 requests, **2,995 partial writes** and **1,200 fragmented reads**. Not an edge case. The common case.

### What one thread for everything costs you

Be honest about the trade, because "epoll is faster" is not the whole story.

The price of thread-per-connection is **memory and scheduling**, and it buys you an enormous convenience: **the call stack is your per-connection state**. Local variables, the position in the protocol, what you were doing halfway through parsing a header — all of it is held for free by the fact that the thread is suspended mid-function.

The price of one thread for everything is that this convenience disappears:

1. **You keep per-connection state explicitly** — a `Connection` object with buffers and a protocol phase. Your handler becomes a state machine instead of a straight-line function.
2. **Nothing in the loop may ever block.** Not a DNS lookup, not a disk read, not `time.sleep()`, not a database driver that was written for threads. One blocking call stalls *every* connection the loop owns. Lesson 4 measures precisely how much.
3. **Partial reads and writes are now your problem**, as above.
4. **A slow handler is a latency spike for everyone.** With threads the scheduler preempts a hog; an event loop is cooperative, and a handler that runs for 50 ms adds 50 ms to every other connection's latency.

That list is why lessons 4, 5 and 6 exist. Lesson 4 turns the raw loop into a reactor with timers and callbacks; lessons 5 and 6 use coroutines to get the *call stack back*, letting a runtime suspend and resume straight-line code at each `await` — blocking-style code over non-blocking I/O. That is the destination; this lesson is the machine underneath it.

## Build It

[`code/nonblocking_io.py`](code/nonblocking_io.py) is five numbered arguments, standard library only. Start with the state that a blocking server keeps for free:

```python
class Connection:
    """Per-connection state. In a blocking server this lives on the call stack;
    with one thread for everything, you have to write it down yourself."""

    __slots__ = ("sock", "inbuf", "outq", "requests")

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.inbuf = bytearray()      # bytes received but not yet a whole message
        self.outq = bytearray()       # bytes owed to the peer but not yet accepted
        self.requests = 0
```

Two buffers per connection. That is the entire conceptual difference between the two designs, and everything else follows from it. The read half fills `inbuf` and drains whole messages out of it:

```python
chunk = conn.sock.recv(4096)
if not chunk:                                     # clean EOF: peer closed
    sel.unregister(conn.sock); conn.sock.close(); continue
conn.inbuf += chunk
if b"\n" not in conn.inbuf:
    partial_reads += 1                            # a fragment, not a message
while b"\n" in conn.inbuf:                        # framing: one message per line
    line, _, rest = conn.inbuf.partition(b"\n")
    conn.inbuf = bytearray(rest)
    conn.outq += line.upper().ljust(RESPONSE_BYTES - 1, b".") + b"\n"
    served += 1
if conn.outq:
    sel.modify(conn.sock, selectors.EVENT_READ | selectors.EVENT_WRITE, conn)
```

Note the `while`, not `if`: one `recv()` can deliver several complete messages plus half of another, and dropping the tail is a classic silent corruption. Note also that we ask for `EVENT_WRITE` **only when there is something to write** — a connected socket is nearly always writable, so a permanent write interest turns a level-triggered loop into a 100%-CPU spin, the busy loop from section 2 arrived at by a different route.

The write half is where partial writes get handled, and it is four lines:

```python
try:
    sent = conn.sock.send(conn.outq)
except BlockingIOError:
    sent = 0                                      # buffer full; try again next wakeup
if sent < len(conn.outq):
    partial_writes += 1                           # the kernel took only some
del conn.outq[:sent]
if not conn.outq:
    sel.modify(conn.sock, selectors.EVENT_READ, conn)   # drop write interest again
```

`send()` returns what the kernel accepted; delete that much from the front of the queue and leave the rest for the next writable event. Forget it and you truncate large responses under exactly the conditions that matter — a slow client, a congested link, a large payload.

Section 5 needs edge-triggered semantics, which Python's `selectors` does not expose, so it simulates them explicitly rather than pretending:

```python
class EdgeTriggeredSim:
    """Python's selectors are level-triggered only. This reproduces EPOLLET
    semantics faithfully: an fd is reported once per *transition* into
    readability, and is only re-armed when the reader hits EAGAIN and new data
    subsequently arrives."""

    def select(self, fds: list[int]) -> list[int]:
        ready = [fd for fd in fds if self.armed.get(fd)]
        for fd in ready:
            self.armed[fd] = False     # the edge is consumed by reporting it
        return ready

    def hit_eagain(self, fd: int) -> None:
        self.armed[fd] = False         # drained; the next arrival is a fresh edge
```

Run it:

```bash
docker compose exec -T app python phases/08-concurrency-and-performance/03-blocking-vs-non-blocking-io/code/nonblocking_io.py
```

```console
== 1 · A BLOCKING SERVER SERVES ONE CLIENT AT A TIME ==
  server work per request      =   300.0 ms
  fastest client saw           =   305.5 ms
  slowest client saw           =   607.1 ms
  measured stall (queueing)    =   301.6 ms   <- time spent waiting in line, not being served
  the second client paid 1.99x for identical work

== 2 · EAGAIN IN THE FLESH, AND WHAT A BUSY LOOP COSTS ==
  sock.setblocking(False); sock.recv() with an empty buffer
    -> BlockingIOError errno=11 (EAGAIN): Resource temporarily unavailable
       EAGAIN == EWOULDBLOCK: True

  receiving ONE message that arrives 250 ms from now:
    busy loop   wall=  252.6 ms   cpu=  249.5 ms   failed recv() syscalls = 238,776
    blocking    wall=  255.1 ms   cpu=    0.0 ms   failed recv() syscalls = 0
    CPU utilisation while waiting: busy loop  98.8%   vs blocking   0.0%
    the busy loop costs 0.99 CPU-seconds per idle second, PER CONNECTION
    -> 10,000 idle connections would need 9,876 cores to do nothing
    945k syscalls/sec returning 'nothing to do' -> a whole core, producing nothing

== 3 · ONE THREAD, MANY CONNECTIONS ==
  workload: 150 concurrent clients x 4 requests = 600 requests
            12 KiB request, 16 KiB response, small SO_SNDBUF/SO_RCVBUF
            so that fragmentation is guaranteed, not hoped for

  (each server is run 3x; the best wall time is reported, because
   background load can only ever make a timing worse, never better)

  selectors (EpollSelector), ONE thread:
    wall time            =    116.6 ms   (5,145 req/s)
    requests served      = 600
    peak concurrent conns= 150
    OS threads used      = 1
    partial writes hit   = 2,995   <- send() took less than we gave it, this often
    partial reads hit    = 1,200   <- recv() returned less than one message

  thread-per-connection, same workload:
    wall time            =    235.6 ms   (2,547 req/s)
    requests served      = 600
    OS threads created   = 150

  what one parked thread costs (measured over 200 threads):
    stack RESERVED (RLIMIT_STACK) = 8.0 MiB of address space
    virtual size per thread       = 7.9 MiB
    RESIDENT per thread           = 15.8 KiB
    thread ping-pong round trip   = 32.47 us  -> ~16.23 us per wakeup
    voluntary context switches    = 20,072 over 10,000 round trips (2.0 each)

  extrapolate to 10,000 mostly-idle connections:
    thread-per-connection, resident = 153.9 MiB
    thread-per-connection, reserved = 78.1 GiB  of virtual address space
    one wakeup each                 = 162.3 ms of pure scheduler work per round
    selector loop, resident         = 15.8 KiB  (1 thread) + ~3.8 MiB of connection state

== 4 · WHY EPOLL WON: SELECT() COSTS O(WATCHED), EPOLL COSTS O(READY) ==
   watched    select() us/call   EpollSelector us/call   ready
        11                 1.0                     0.8       1
       101                 4.6                     0.9       1
       501                20.7                     0.9       1
     1,001                40.7                     0.9       1
     2,001  FD_SETSIZE EXCEEDED                     0.9       1

  select() re-copies and re-scans the whole fd_set on EVERY call, in both
  directions, so its cost tracks the number of fds you are WATCHING.
  EpollSelector keeps the registration in the kernel and returns a ready
  list, so its cost tracks the number of fds that are READY -- here, always 1.
  select() on fd 2000 -> ValueError: filedescriptor out of range in select()
  That is FD_SETSIZE (1024 on glibc). It is a compile-time constant in libc,
  not a tunable: the fd_set bitmap has exactly that many bits. THAT is the wall.

== 5 · LEVEL-TRIGGERED VS EDGE-TRIGGERED ==
  8,192 bytes sitting in the receive buffer; we read only 1,024 per wakeup.

  LEVEL-TRIGGERED (what selectors/epoll-default/kqueue give you):
    wait 1: reported READY -> read 1,024 B   (drained 1,024/8,192, 7,168 still buffered)
    wait 2: reported READY -> read 1,024 B   (drained 2,048/8,192, 6,144 still buffered)
    wait 3: reported READY -> read 1,024 B   (drained 3,072/8,192, 5,120 still buffered)
    wait 4: reported READY -> read 1,024 B   (drained 4,096/8,192, 4,096 still buffered)
    -> readiness is re-reported for as long as data REMAINS. A partial read is safe.

  EDGE-TRIGGERED, done WRONG (one read per wakeup, as above):
    wait 1: reported READY -> read 1,024 B   (drained 1,024/8,192, 7,168 still buffered)
    wait 2: reported NOTHING -- 7,168 B are still there, and no event will ever come
    wait 3: reported NOTHING -- 7,168 B are still there, and no event will ever come
    wait 4: reported NOTHING -- 7,168 B are still there, and no event will ever come
    -> the connection is now hung forever: the peer waits for a reply,
       we wait for an event, and the bytes we needed sit in the buffer.

  EDGE-TRIGGERED, done RIGHT (drain until EAGAIN):
    wait 1: reported READY -> looped 8 recv() calls, drained 8,192 B, hit EAGAIN, re-armed
    wait 2: reported nothing -- correct, the buffer IS empty
    wait 3: reported READY -> looped 1 recv() call, drained 512 B, hit EAGAIN, re-armed

  Python's selectors module exposes level-triggered semantics only; the ET blocks
  above are a faithful simulation of EPOLLET (epoll(7)) / EV_CLEAR (kqueue(2)).

  total runtime 4.2s
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 502" width="100%" style="max-width:840px" role="img" aria-label="Side by side comparison of thread-per-connection and one thread with a selector, using measured numbers. Thread-per-connection used 150 operating system threads to serve 600 requests in 235.6 milliseconds, with 8 mebibytes of stack reserved and 15.8 kibibytes resident per thread, extrapolating to 78.1 gibibytes of address space and 162 milliseconds of scheduler wakeup work for 10,000 connections. The selector server used one thread to serve the same 600 requests in 116.6 milliseconds, with an epoll wait cost of 0.9 microseconds regardless of how many descriptors were watched, at the price of writing connection state down by hand.">
  <defs>
    <marker id="l03b-arrr" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#d64545"/></marker>
    <marker id="l03b-arrg" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
  </defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">150 connections, 600 requests, identical work — two designs, measured</text>

    <rect x="16" y="42" width="416" height="404" rx="12" fill="#d64545" fill-opacity="0.09" stroke="#d64545" stroke-width="2"/>
    <rect x="448" y="42" width="416" height="404" rx="12" fill="#0fa07f" fill-opacity="0.10" stroke="#0fa07f" stroke-width="2"/>
    <text x="224" y="66" text-anchor="middle" font-size="12.5" font-weight="700" fill="#d64545">THREAD-PER-CONNECTION</text><text x="656" y="66" text-anchor="middle" font-size="12.5" font-weight="700" fill="#0fa07f">ONE THREAD + SELECTOR</text>

    <g stroke-width="1.6">
      <circle cx="48" cy="98" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="48" cy="124" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="48" cy="150" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="48" cy="176" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="150" y="88" width="118" height="20" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="150" y="114" width="118" height="20" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="150" y="140" width="118" height="20" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="150" y="166" width="118" height="20" rx="5" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
    </g>
    <g stroke="#d64545" stroke-width="1.5" marker-end="url(#l03b-arrr)">
      <line x1="58" y1="98" x2="144" y2="98"/><line x1="58" y1="124" x2="144" y2="124"/>
      <line x1="58" y1="150" x2="144" y2="150"/><line x1="58" y1="176" x2="144" y2="176"/>
    </g>
    <g font-size="8.5" fill="currentColor" text-anchor="middle">
      <text x="209" y="102">thread 1 · parked</text><text x="209" y="128">thread 2 · parked</text><text x="209" y="154">thread 3 · parked</text><text x="209" y="180">thread 150 · parked</text>
    </g>
    <text x="350" y="120" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">1 conn</text><text x="350" y="136" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">= 1 thread</text><text x="350" y="158" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">state lives on</text>
    <text x="350" y="172" text-anchor="middle" font-size="8.5" fill="currentColor" opacity="0.85">the call stack</text>

    <g stroke-width="1.6">
      <circle cx="480" cy="98" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="480" cy="124" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="480" cy="150" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <circle cx="480" cy="176" r="7" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <rect x="586" y="88" width="112" height="98" rx="7" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="734" y="112" width="112" height="50" rx="7" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f"/>
    </g>
    <g stroke="#0fa07f" stroke-width="1.5" marker-end="url(#l03b-arrg)">
      <line x1="490" y1="98" x2="580" y2="112"/><line x1="490" y1="124" x2="580" y2="128"/>
      <line x1="490" y1="150" x2="580" y2="146"/><line x1="490" y1="176" x2="580" y2="162"/>
      <line x1="700" y1="137" x2="728" y2="137"/>
    </g>
    <text x="642" y="126" text-anchor="middle" font-size="9.5" font-weight="700" fill="#7c5cff">epoll_wait()</text><text x="642" y="144" text-anchor="middle" font-size="8.5" fill="currentColor">kernel ready list</text><text x="642" y="160" text-anchor="middle" font-size="8.5" fill="currentColor">returns only what</text>
    <text x="642" y="174" text-anchor="middle" font-size="8.5" fill="currentColor">is actually ready</text><text x="790" y="132" text-anchor="middle" font-size="9.5" font-weight="700" fill="#0fa07f">1 thread</text><text x="790" y="150" text-anchor="middle" font-size="8.5" fill="currentColor">for all 150</text>

    <line x1="32" y1="202" x2="416" y2="202" stroke="#d64545" stroke-width="1.2" stroke-opacity="0.45"/>
    <line x1="464" y1="202" x2="848" y2="202" stroke="#0fa07f" stroke-width="1.2" stroke-opacity="0.45"/>

    <g font-size="10" fill="currentColor">
      <text x="32" y="224" font-size="9" font-weight="700" opacity="0.7">MEASURED, 150 CONNECTIONS</text><text x="32" y="246">OS threads created</text><text x="416" y="246" text-anchor="end" font-weight="700" fill="#d64545">150</text><text x="32" y="266">600 requests took</text><text x="416" y="266" text-anchor="end" font-weight="700" fill="#d64545">235.6 ms</text>
      <text x="32" y="286">stack reserved / thread</text><text x="416" y="286" text-anchor="end">8.0 MiB</text><text x="32" y="306">resident / thread</text><text x="416" y="306" text-anchor="end">15.8 KiB</text><text x="32" y="326">one wakeup costs</text><text x="416" y="326" text-anchor="end">16.2 us</text>

      <text x="464" y="224" font-size="9" font-weight="700" opacity="0.7">MEASURED, 150 CONNECTIONS</text><text x="464" y="246">OS threads created</text><text x="848" y="246" text-anchor="end" font-weight="700" fill="#0fa07f">1</text><text x="464" y="266">600 requests took</text><text x="848" y="266" text-anchor="end" font-weight="700" fill="#0fa07f">116.6 ms</text>
      <text x="464" y="286">epoll_wait, 11 watched</text><text x="848" y="286" text-anchor="end">0.9 us</text><text x="464" y="306">epoll_wait, 1001 watched</text><text x="848" y="306" text-anchor="end">0.9 us</text><text x="464" y="326">select(), 1001 watched</text><text x="848" y="326" text-anchor="end" fill="#d64545">40.7 us</text>
    </g>

    <rect x="32" y="342" width="384" height="92" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.6"/>
    <rect x="464" y="342" width="384" height="92" rx="8" fill="#e0930f" fill-opacity="0.11" stroke="#e0930f" stroke-width="1.6"/>
    <g font-size="9.5" fill="currentColor">
      <text x="46" y="362" font-size="9" font-weight="700" fill="#e0930f">EXTRAPOLATED TO 10,000 IDLE CONNECTIONS</text><text x="46" y="380">10,000 threads · 78.1 GiB of address space</text><text x="46" y="398">153.9 MiB resident before a byte is served</text>
      <text x="46" y="416">162.3 ms of scheduler work to wake them once</text><text x="478" y="362" font-size="9" font-weight="700" fill="#e0930f">THE PRICE YOU PAY INSTEAD</text><text x="478" y="380">1 thread · ~3.8 MiB of connection state</text>
      <text x="478" y="398">you write the state down: inbuf + outq per conn</text><text x="478" y="416">600 requests hit 2,995 partial writes, 1,200 frags</text>
    </g>

    <text x="440" y="470" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The thread was never the work — it was the cost of being READY for the work.</text><text x="440" y="489" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">The selector deletes that cost and bills you in complexity instead.</text>
  </g>
</svg>
```

**Read the numbers — four of these five sections are arguments, not demos.**

**Section 1** is the baseline pain. The server does 300 ms of work per request. Client A gets its answer in **305.5 ms**, essentially perfect. Client B, which sent its request at the same instant, waits **607.1 ms** — a **301.6 ms stall** that is pure queueing. B's request sat complete in the kernel's receive buffer, ready to serve, for 302 ms during which the CPU was idle. Nothing was slow; there was one thread and it was busy. That is the whole argument for concurrency, and why a thread per connection is such an appealing fix.

**Section 2 is the argument that non-blocking mode alone is a trap**, and the gap is not subtle. Both approaches wait 250 ms for the same message. The blocking `recv()` spends **0.0 ms of CPU** — below the clock's resolution — at **0.0% utilisation**: the thread is parked and the machine is free to do anything else. The busy loop spends **249.5 ms of CPU**, **98.8% of a core**, issuing **238,776 failed syscalls** at about **945,000 per second**. Stated as a rate, the busy loop costs **0.99 CPU-seconds per idle second, per connection** — so 10,000 idle connections would need **9,876 cores to do nothing at all**. One busy-looping connection saturates a core; ten thousand of them are not a design, they are a thermal event. This single measurement is why readiness notification had to be invented — non-blocking descriptors are only useful if something *else* tells you when to touch them.

**Section 3 is the lesson's central result.** One thread, using `EpollSelector`, served **600 requests across 150 simultaneous connections in 116.6 ms (5,145 req/s)**. The thread-per-connection server did identical work in **235.6 ms (2,547 req/s)** using **150 OS threads** — the selector was **2.0× faster while using 1/150th of the threads**. Do not over-read the speed: at only 150 connections the thread version is perfectly viable, and its advantage would grow if the per-request work were CPU-heavy enough to use multiple cores. Read the *resource* columns instead, because those are what break. **8.0 MiB reserved and 15.8 KiB resident per thread**, and **16.23 µs per wakeup** (verified by the kernel's own counter: 20,072 voluntary context switches for 10,000 round trips, exactly 2.0 each). Extrapolated to 10,000 connections that is **78.1 GiB of address space, 153.9 MiB resident before serving a byte, and 162.3 ms of scheduler work to wake everyone once.** The selector's version of the same workload is one thread — **15.8 KiB** — plus roughly **3.8 MiB** of connection objects. Two orders of magnitude, and it is the *reserved* figure that actually kills processes in containers.

The partial-I/O counters are the other half of section 3, and they are the honest price tag. Serving 600 requests required handling **2,995 partial writes** — nearly five per request — and **1,200 fragmented reads**, where a `recv()` returned less than one complete message. Every one of those is a case where naive code (`sock.send(response)` and assume it all went; `parse(sock.recv(4096))` and assume it is whole) would truncate a response or corrupt a request. The thread-per-connection version needed none of that logic, because `sendall()` loops and the call stack remembers. **That is what the 1/150th of the threads costs you.**

**Section 4 is why `epoll` replaced `select`.** With one ready descriptor throughout, `select()` costs **1.0 µs at 11 watched, 4.6 µs at 101, 20.7 µs at 501, and 40.7 µs at 1,001** — near-perfectly linear in the *watched* count, roughly 40 ns per idle descriptor per call, because the whole bitmap is copied into the kernel, scanned, and copied back on every single call. `epoll_wait()` over the same sets costs **0.8–0.9 µs at every size**, because the interest list already lives in the kernel and the call returns a ready list of length 1. At 1,001 descriptors that is **45× cheaper**, and the gap keeps widening. Then at 2,001 descriptors `select()` does not get slower — it **stops working**, raising `ValueError: filedescriptor out of range in select()`. That is `FD_SETSIZE`, the 1024-bit width of `fd_set`, and no `ulimit` will move it. An event loop built on `select()` has a hard ceiling of about a thousand connections; that limit, not the microseconds, is the reason C10K required a new syscall.

**Section 5** makes the trigger modes concrete. Level-triggered re-reports readiness on all four waits while bytes remain, so incremental draining is safe. Edge-triggered reports once; a single 1,024-byte read leaves **7,168 bytes stranded and no event will ever arrive for them**. The connection does not error — it *hangs*, with a complete request sitting in a kernel buffer and both sides waiting for the other. Under light load you may never see it, because messages arrive small enough to be drained in one read. Under load, when messages get fragmented and coalesced, it becomes a mystery outage. Done right, the ET reader loops until `BlockingIOError` — **8 `recv()` calls, 8,192 bytes, then `EAGAIN`** — which is exactly what re-arms the notification, proven by wait 3 correctly reporting the 512 bytes that arrived afterwards.

## Use It

Python ships the portable wrapper in the standard library: **`selectors`**. `DefaultSelector` picks the best available mechanism for the platform — `EpollSelector` on Linux, `KqueueSelector` on macOS and the BSDs, `PollSelector` or `SelectSelector` elsewhere — behind one API. Your code does not change; the syscall underneath does.

```python
import selectors, socket

sel = selectors.DefaultSelector()          # EpollSelector here, KqueueSelector on macOS

listener = socket.socket()
listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
listener.bind(("0.0.0.0", 8080))
listener.listen(512)
listener.setblocking(False)                # accept() must not park the loop either
sel.register(listener, selectors.EVENT_READ, data=None)

while True:
    for key, mask in sel.select(timeout=1.0):        # ONE park covers every connection
        if key.data is None:
            while True:                              # drain the accept queue
                try:
                    conn, addr = listener.accept()
                except BlockingIOError:
                    break
                conn.setblocking(False)
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                sel.register(conn, selectors.EVENT_READ, data=Connection(conn))
        else:
            handle_ready(sel, key.data, mask)        # your inbuf / outq state machine
```

`sel.register()` is `epoll_ctl(EPOLL_CTL_ADD)`. `sel.modify()` is `EPOLL_CTL_MOD` — what you call to add and drop `EVENT_WRITE` interest as the output queue fills and empties. `sel.select()` is `epoll_wait()`, and the `SelectorKey.data` field is where you hang the `Connection` object you built by hand above. There is no magic left in it.

**What real servers do.** This pattern is not a teaching toy; it is the architecture of nearly everything fast.

- **nginx** runs a small number of single-threaded worker processes, each an event loop over `epoll`/`kqueue`, each handling thousands of connections. It is why nginx serves static files at high concurrency with a memory footprint that does not track connection count.
- **Redis** is famously "single-threaded" — meaning command execution is; the networking is an event loop over `epoll`/`kqueue` (Redis 6 added I/O threads for the read/write syscalls only, keeping execution serialised). Its speed comes from never blocking and never context-switching, which is also why one slow `KEYS *` stalls every client. Exactly the trap from *What one thread costs you*.
- **Node.js** is **libuv** wrapping `epoll`/`kqueue`/IOCP, with a thread pool bolted on for the things readiness cannot express — file I/O, DNS via `getaddrinfo`, and crypto — which is the practical consequence of "a regular file is always ready."
- **Go** is the important reframing. You write `conn.Read(buf)`, which *looks* blocking and *is* blocking from the goroutine's point of view. Underneath, the runtime set that socket non-blocking at creation; the read returns `EAGAIN`, and instead of parking an OS thread the runtime parks the **goroutine** (a few KiB of stack, not 8 MiB), registers the descriptor with the **netpoller** — `epoll` on Linux, `kqueue` on BSD — and runs another goroutine on the same OS thread. When the netpoller reports readiness, the goroutine is rescheduled and the read completes. **Blocking-style code over non-blocking I/O**, with the state machine generated for you. That is precisely where lessons 5 and 6 are heading with `async`/`await`: the same trick, made explicit at each `await`.
- **`io_uring`** is worth reaching for when you are syscall-bound rather than bandwidth-bound — very high request rates on small payloads, or when you need genuinely asynchronous *disk* I/O that `epoll` structurally cannot provide. The costs are real: it needs a recent kernel, the API is intricate, and it has been disabled by default in several hardened environments (Google and others restrict it in production containers) after a run of security issues. Reach for it deliberately, behind a library like `liburing` or `tokio-uring`, not as a default.

**Production rules.**

- **Always handle partial writes; never assume `send()` took everything.** Keep an output queue per connection, register `EVENT_WRITE` only when it is non-empty, and deregister it when it drains. In the Build It this fired **2,995 times in 600 requests** — the code path where you "hardly ever" need it is the code path that runs constantly under load.
- **Always frame your messages explicitly** — a length prefix or a delimiter — and drain your input buffer with a `while`, not an `if`. **1,200 of 600 requests** arrived fragmented. TCP gives you an ordered byte stream and nothing more.
- **Never make a blocking call inside an event loop.** Not DNS, not a disk read, not `time.sleep()`, not a thread-oriented database driver, not `bcrypt`, not a 50 ms JSON parse. One 200 ms stall in the loop adds 200 ms to *every* connection you own, and it will show up in your p99 with no obvious cause. Hand genuinely blocking work to a thread pool (lesson 4 measures the damage; lesson 7 builds the pool).
- **Set `TCP_NODELAY` wherever latency matters.** Nagle's algorithm (RFC 896) holds small writes back waiting for more data; combined with delayed ACKs it can add tens of milliseconds to a small request/response exchange. Interactive protocols want it off. Bulk transfer does not care.
- **Budget file descriptors deliberately.** One connection is one descriptor; `ulimit -n` is per-process and often 1024 by default. Raise `LimitNOFILE` in your systemd unit or the container's `nofile` rlimit *before* you need it, monitor `ls /proc/<pid>/fd | wc -l` against the limit, and remember that hitting the ceiling shows up as `accept()` failing with `EMFILE` — a level-triggered loop will then spin hot on the listener, because the listener stays readable and you cannot drain it. The runbook below covers the diagnosis.

The reusable artifact for this lesson is [`outputs/runbook-diagnosing-io-stalls.md`](outputs/runbook-diagnosing-io-stalls.md) — a triage procedure for a server that has gone slow, distinguishing blocking-in-the-loop from CPU saturation from descriptor exhaustion, with the commands for each.

## Think about it

1. Your event-loop server's p99 latency is 400 ms while CPU sits at 12% and the p50 is 3 ms. Nothing is saturated. What single class of bug produces exactly this signature, and how would you find the offending call without a profiler?
2. Section 3 measured 15.8 KiB resident per thread but 8.0 MiB reserved. Which of those two numbers determines how many threads your container can actually create, and why does the answer change depending on whether you set `threading.stack_size()`, `ulimit -s`, or a cgroup memory limit?
3. You switch a working level-triggered loop to edge-triggered for performance and it passes every test, then hangs connections in production about once an hour. Which reads and writes must you audit, and what makes this bug so much more likely under high load than in a test?
4. `epoll` cannot do asynchronous disk I/O because a regular file is always "ready". Given that, how would you serve a 2 GB file from a single-threaded event loop without stalling other connections — and what does `sendfile(2)` change about the analysis?
5. Go lets you write blocking-looking code over a non-blocking netpoller by parking goroutines instead of threads. What must be true about a language's runtime for that trick to be possible, and what specific thing goes wrong if a goroutine calls into C code that blocks?

## Key takeaways

- **Blocking parks a thread; it does not spin one.** A `recv()` with an empty buffer takes the thread off the run queue until a packet's interrupt handler wakes it — measured at **0.0 ms of CPU for a 250 ms wait, versus 249.5 ms (98.8% of a core) for the naive busy loop** — 0.99 CPU-seconds burned per idle second, per connection. So blocking wastes memory and scheduling capacity, never cycles. That is why it fails at 10,000 connections and is perfectly fine at 200.
- **Non-blocking mode alone is half a mechanism and a net loss.** `O_NONBLOCK` converts a free park into `EAGAIN` and, without readiness notification, into **238,776 failed syscalls in 250 ms**. The missing half is the kernel telling you *which* descriptors can be acted on — `select`, `poll`, `epoll`, `kqueue` — so one parked thread covers every connection.
- **`select` costs O(watched); `epoll`/`kqueue` cost O(ready).** Measured with one ready descriptor: `select()` climbed **1.0 → 4.6 → 20.7 → 40.7 µs** from 11 to 1,001 watched, while `epoll_wait()` stayed flat at **0.8–0.9 µs** — **45× cheaper** at 1,001 — and at 2,001 `select()` failed outright on `FD_SETSIZE`, a compile-time 1024-bit bitmap that no `ulimit` can raise. Registration living in the kernel, plus a kernel-maintained ready list, is the whole difference.
- **Readiness is not completion, and neither is asynchrony.** `epoll` says "the copy will not block"; **you still do the copy**, which makes multiplexed I/O *synchronous*. Completion models (`io_uring`, IOCP) do the copy for you — the reason they matter most for disk, since a regular file is always "ready" and `epoll` therefore cannot do asynchronous file I/O at all.
- **One thread for everything replaces a memory bill with a complexity bill, and both are measurable.** 150 connections on one thread served 600 requests in **116.6 ms** versus **235.6 ms on 150 threads**, and extrapolating the per-thread cost (**8.0 MiB reserved, 15.8 KiB resident, 16.2 µs per wakeup**) to 10,000 connections gives **78.1 GiB of address space, 153.9 MiB resident, and 162.3 ms of scheduler work per wakeup round**. The price: per-connection state becomes an explicit state machine, and nothing in the loop may ever block.
- **Partial reads and writes are the common case, not an edge case.** Those 600 requests produced **2,995 partial writes and 1,200 fragmented reads**. Every non-blocking connection needs an input buffer with explicit framing and an output queue, and edge-triggered mode additionally demands draining until `EAGAIN` — a single 1,024-byte read of an 8,192-byte buffer stranded **7,168 bytes** with no further event ever arriving.

Next: [The Event Loop: Build a Reactor from Scratch](../04-the-event-loop/) — turning this raw `selectors` loop into a proper reactor with callbacks, timers, and a task queue, and measuring exactly how much one blocking call inside it costs every other connection.
