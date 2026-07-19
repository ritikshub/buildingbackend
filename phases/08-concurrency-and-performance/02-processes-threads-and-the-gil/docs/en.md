# Processes, Threads & the GIL

> Four threads on a ten-core machine made a CPU-heavy workload exactly **1.00x** faster in this lesson's measurements — not a single percent of gain. The identical four threads on an I/O-heavy workload gave **3.95x**, and sixteen gave **14.73x**. Same language, same machine, same `threading.Thread`. The entire difference is one mutex inside CPython called the GIL, and until you know precisely what it locks, every concurrency decision you make is a coin flip. This lesson measures a process, a thread, a context switch and the GIL, and turns that coin flip into a rule you can apply in ten seconds.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Concurrency?](../01-why-concurrency/), [How a Computer Runs a Program](../../00-foundations/09-how-a-computer-runs-a-program/), [RAM & the Memory Hierarchy](../../00-foundations/06-ram-and-memory-hierarchy/)
**Time:** ~85 minutes

## The Problem

Lesson 1 left you with a machine that is mostly idle and a queue that is mostly full. The CPU sits at 8% while p99 latency climbs, because your code is standing in line: one request at a time, and most of that time spent waiting on a database that is not even breathing hard. The diagnosis was clean. The obvious fix is one word: **threads**.

So you add them. Your service has a report endpoint that grinds through a few million rows of arithmetic in Python — genuinely CPU-heavy — and the box has ten cores. You split the work across four threads, deploy, and measure.

It is **not faster**. Not "a bit disappointing" — the wall-clock time is the same to two decimal places. You try eight threads. Still the same. On a loaded host it comes back *slower* than one thread. You check that the threads really ran; they did. You check that the machine really has ten cores; it does. You watch `top` during the run and see one core at 100% and nine near zero, which is exactly what you would see if you had never written the threading code at all.

Now you try the same trick on a different endpoint — the one that makes sixteen sequential calls to an internal API, each taking about 50 ms. Four threads: **3.95x faster**. Eight: **7.91x**. Sixteen: **14.73x**, which is almost perfect. Same `threading.Thread`, same interpreter, same box, same afternoon.

Two experiments, one library, opposite results. Every explanation you find is either folklore ("Python can't do threads") or a shrug ("just use multiprocessing"), and both are wrong in ways that will cost you: the first would stop you from writing the threaded I/O code that just gave you a 14x win, and the second would have you pay for process isolation you did not need. Worse, neither tells you what to do next time, when the workload is a mix of the two — which is every real endpoint.

The two results are not a contradiction. They are the same mechanism, seen from two sides. To see it you need to know three things exactly: what the operating system means by a *process*, what it means by a *thread*, and what CPython adds on top of both. Then the rule falls out in one sentence, and it is a sentence you can apply without measuring anything.

## The Concept

### What a process actually is

A **process** is not "a running program." It is an **address space** plus the kernel bookkeeping wrapped around it.

When you run `python app.py`, the kernel creates a fresh, private map from *virtual addresses* (the numbers your program uses as pointers) to *physical pages* of RAM. That map is the **page table**, and it is the whole ballgame: address `0x7f3a1c00` in your process and address `0x7f3a1c00` in the process next to it point at completely different physical memory, because they are translated through different page tables. Neither can name the other's memory, because there is no number it could put in a pointer that would get there.

Around that address space the kernel keeps a small pile of per-process state:

- a **PID** (Process IDentifier), the number `kill` and `ps` use;
- the **page table** just described, which the CPU's memory-management unit consults on every single memory access;
- a **file descriptor table** — an array mapping small integers (`0` = stdin, `1` = stdout, `7` = the socket you just opened) to the kernel's open-file objects. Descriptors are per-process, which is why fd 7 in your process has nothing to do with fd 7 in mine;
- the process's **memory regions**: `text` (your compiled bytecode and the interpreter's machine code), `data` (globals, module objects, constants), the **heap** (every Python object you ever allocate, with its reference count), and at least one **stack**;
- ownership and permission bits: user, group, resource limits, working directory, environment.

The consequence that matters most is **isolation**. A process that corrupts its own heap, dereferences garbage, or exhausts its address space damages exactly one thing: itself. The kernel kills it and every other process on the machine continues, unaware. Nothing you can do in one process can corrupt another's objects, because the hardware refuses to translate the address. This is not a nicety; it is why a crashing worker in a `gunicorn` pool takes down one request instead of your service.

### What a thread actually is

A **thread** is an independent stream of instructions *inside* one address space.

Everything a thread needs to be independent is small: its own **registers**, its own **program counter** (the register holding the address of the next instruction), and its own **stack** (the region holding call frames, return addresses and local variables). That is genuinely the entire private part. Everything else — the text, the globals, the heap, every Python object, the file descriptor table — is shared with every other thread in that process.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 440" width="100%" style="max-width:840px" role="img" aria-label="Two processes side by side. Each owns one address space containing its text, data, heap and file descriptor table, shared by every thread inside it. The left process has three threads, each with its own private stack, registers and program counter. The right process has one thread and cannot see the left process's memory at all, so sharing between the two requires serialising through a pipe.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">One address space per process · one stack per thread</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="470" height="310" rx="12" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    <rect x="506" y="44" width="358" height="310" rx="12" fill="#7c5cff" fill-opacity="0.08" stroke="#7c5cff"/>
    <rect x="32" y="80" width="438" height="112" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="522" y="80" width="326" height="112" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    <rect x="32" y="202" width="438" height="138" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="522" y="202" width="326" height="138" rx="9" fill="#3553ff" fill-opacity="0.11" stroke="#3553ff"/>
    <rect x="16" y="366" width="848" height="46" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.45"/>
  </g>
  <g fill="none" stroke="#0fa07f" stroke-width="1.5">
    <rect x="44" y="106" width="98" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="152" y="106" width="98" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="260" y="106" width="98" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="368" y="106" width="98" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="528" y="106" width="72" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="608" y="106" width="72" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="688" y="106" width="72" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
    <rect x="768" y="106" width="72" height="76" rx="6" fill="#0fa07f" fill-opacity="0.10"/>
  </g>
  <g fill="none" stroke="#3553ff" stroke-width="1.5">
    <rect x="46" y="230" width="132" height="100" rx="6" fill="#3553ff" fill-opacity="0.10"/>
    <rect x="190" y="230" width="132" height="100" rx="6" fill="#3553ff" fill-opacity="0.10"/>
    <rect x="334" y="230" width="132" height="100" rx="6" fill="#3553ff" fill-opacity="0.10"/>
    <rect x="536" y="230" width="132" height="100" rx="6" fill="#3553ff" fill-opacity="0.10"/>
  </g>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="32" y="68" font-size="12.5" font-weight="700" fill="#7c5cff">PROCESS 4711</text>
    <text x="522" y="68" font-size="12.5" font-weight="700" fill="#7c5cff">PROCESS 4712</text>
    <text x="251" y="98" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">SHARED — every thread below may read and write all of this</text>
    <text x="685" y="98" font-size="9.5" font-weight="700" text-anchor="middle" fill="#0fa07f">SHARED — but only inside 4712</text>
    <text x="93" y="126" font-size="10" font-weight="700" text-anchor="middle">TEXT</text><text x="93" y="146" font-size="8.5" text-anchor="middle" opacity="0.85">your .py, compiled</text><text x="93" y="162" font-size="8.5" text-anchor="middle" opacity="0.85">to bytecode</text>
    <text x="201" y="126" font-size="10" font-weight="700" text-anchor="middle">DATA</text><text x="201" y="146" font-size="8.5" text-anchor="middle" opacity="0.85">globals, module</text><text x="201" y="162" font-size="8.5" text-anchor="middle" opacity="0.85">objects</text>
    <text x="309" y="126" font-size="10" font-weight="700" text-anchor="middle">HEAP</text><text x="309" y="146" font-size="8.5" text-anchor="middle" opacity="0.85">every object and</text><text x="309" y="162" font-size="8.5" text-anchor="middle" opacity="0.85">its refcount</text>
    <text x="417" y="126" font-size="10" font-weight="700" text-anchor="middle">FD TABLE</text><text x="417" y="146" font-size="8.5" text-anchor="middle" opacity="0.85">sockets, files,</text><text x="417" y="162" font-size="8.5" text-anchor="middle" opacity="0.85">pipes by number</text>
    <text x="564" y="132" font-size="9.5" font-weight="700" text-anchor="middle">TEXT</text><text x="564" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">its own</text>
    <text x="644" y="132" font-size="9.5" font-weight="700" text-anchor="middle">DATA</text><text x="644" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">its own</text>
    <text x="724" y="132" font-size="9.5" font-weight="700" text-anchor="middle">HEAP</text><text x="724" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">its own</text>
    <text x="804" y="132" font-size="9.5" font-weight="700" text-anchor="middle">FDs</text><text x="804" y="152" font-size="8.5" text-anchor="middle" opacity="0.8">its own</text>
    <text x="251" y="220" font-size="9.5" font-weight="700" text-anchor="middle" fill="#3553ff">PRIVATE TO ONE THREAD — nobody else can reach it</text>
    <text x="685" y="220" font-size="9.5" font-weight="700" text-anchor="middle" fill="#3553ff">PRIVATE TO ONE THREAD</text>
    <text x="112" y="254" font-size="10.5" font-weight="700" text-anchor="middle">THREAD 1</text>
    <text x="256" y="254" font-size="10.5" font-weight="700" text-anchor="middle">THREAD 2</text>
    <text x="400" y="254" font-size="10.5" font-weight="700" text-anchor="middle">THREAD 3</text>
    <text x="602" y="254" font-size="10.5" font-weight="700" text-anchor="middle">THREAD 1</text>
    <g font-size="9" opacity="0.9" text-anchor="middle">
      <text x="112" y="278">stack (8 MiB reserved)</text><text x="112" y="296">registers + PC</text><text x="112" y="316">its own call frames</text>
      <text x="256" y="278">stack (8 MiB reserved)</text><text x="256" y="296">registers + PC</text><text x="256" y="316">its own call frames</text>
      <text x="400" y="278">stack (8 MiB reserved)</text><text x="400" y="296">registers + PC</text><text x="400" y="316">its own call frames</text>
      <text x="602" y="278">stack (8 MiB reserved)</text><text x="602" y="296">registers + PC</text><text x="602" y="316">its own call frames</text>
    </g>
    <text x="694" y="262" font-size="9" font-weight="700" fill="#e0930f">a segfault here</text>
    <text x="694" y="280" font-size="9" font-weight="700" fill="#e0930f">kills 4712 only.</text>
    <text x="694" y="302" font-size="9" opacity="0.85">4711 never notices,</text>
    <text x="694" y="318" font-size="9" opacity="0.85">and cannot be corrupted.</text>
    <text x="32" y="350" font-size="9" opacity="0.8">PID 4711 · 3 threads · one page table · 21 KB resident/thread (measured)</text>
    <text x="522" y="350" font-size="9" opacity="0.8">PID 4712 · its own page table</text>
    <text x="440" y="386" font-size="10.5" font-weight="700" text-anchor="middle">A pointer that means something in 4711 means nothing in 4712 — the page tables do not agree.</text>
    <text x="440" y="403" font-size="10" text-anchor="middle" opacity="0.9">To share, you must serialise: pickle → pipe → unpickle. That copy is the real price of a process.</text>
    <text x="440" y="430" font-size="11" text-anchor="middle" opacity="0.9">Threads are cheap because they share everything. That same sharing is every bug in lessons 08-10.</text>
  </g>
</svg>
```

That sharing is the whole story of threads, told twice.

Told optimistically: creating a thread means allocating a stack and a small kernel structure, and nothing else — no page table, no fd table, no copying. The Build It measures **81.9 µs** to create, start and join a thread versus **920.2 µs** for a `fork()`ed process: **11.2x**. Two threads communicate by assigning to a shared variable, at the speed of a memory write. That is why every language offers them.

Told pessimistically: *any* thread can write *any* object at *any* moment, including halfway through another thread's read. There is no boundary to cross, so there is nothing to check, so nothing warns you. Lessons 08 through 10 — races, locks, deadlock — exist entirely because of the green band in that diagram. Keep it in mind as you read the rest of this lesson: everything that makes threads fast is the same fact that makes them dangerous.

### The scheduler: runnable, running, blocked

You have more threads than cores. Somebody decides who runs. That somebody is the kernel's **scheduler**, and its model is smaller than you would guess.

Every thread is in exactly one of a few states. It is **runnable** — it has work to do and is sitting in a **run queue** waiting for a CPU. It is **running** — it owns a core right now. Or it is **blocked** — it has asked for something that has not arrived (bytes from a socket, a page from disk, a lock somebody else holds, the expiry of a sleep) and it cannot proceed.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="A thread's state machine. A new thread becomes runnable when started and joins the kernel run queue. The scheduler moves it to running; the five millisecond time slice expiring preempts it back to runnable. A blocking system call moves it to blocked, where it leaves the run queue entirely and consumes no CPU; when the I/O completes the kernel returns it to runnable. Returning or raising terminates it.">
  <defs>
    <marker id="l02-arr" markerWidth="9" markerHeight="9" refX="6.4" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
    <marker id="l02-arrg" markerWidth="9" markerHeight="9" refX="6.4" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#0fa07f"/></marker>
    <marker id="l02-arra" markerWidth="9" markerHeight="9" refX="6.4" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="#e0930f"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">What the scheduler does with a thread — and what "blocked" really costs</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="24" y="140" width="112" height="48" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="196" y="140" width="144" height="48" rx="9" fill="#3553ff" fill-opacity="0.13" stroke="#3553ff"/>
    <rect x="470" y="140" width="140" height="48" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
    <rect x="706" y="140" width="150" height="48" rx="9" fill="#7f7f7f" fill-opacity="0.10" stroke="currentColor" stroke-opacity="0.55"/>
    <rect x="470" y="280" width="140" height="48" rx="9" fill="#e0930f" fill-opacity="0.14" stroke="#e0930f"/>
    <rect x="636" y="272" width="228" height="90" rx="9" fill="#7f7f7f" fill-opacity="0.09" stroke="currentColor" stroke-opacity="0.4"/>
    <rect x="196" y="62" width="144" height="42" rx="7" fill="#3553ff" fill-opacity="0.07" stroke="#3553ff" stroke-opacity="0.6" stroke-dasharray="5 4"/>
  </g>
  <g fill="#3553ff" fill-opacity="0.22" stroke="#3553ff" stroke-width="1.2">
    <rect x="206" y="74" width="36" height="18" rx="3"/><rect x="248" y="74" width="36" height="18" rx="3"/><rect x="290" y="74" width="36" height="18" rx="3"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-width="1.8">
    <path d="M136 164 L 190 164" marker-end="url(#l02-arr)"/>
    <path d="M340 155 L 464 155" marker-end="url(#l02-arr)"/>
    <path d="M464 177 L 346 177" marker-end="url(#l02-arr)"/>
    <path d="M610 164 L 700 164" marker-end="url(#l02-arr)"/>
    <path d="M268 104 L 268 134" stroke-dasharray="4 4" stroke-opacity="0.6" marker-end="url(#l02-arr)"/>
  </g>
  <path d="M512 188 L 512 274" fill="none" stroke="#e0930f" stroke-width="2" marker-end="url(#l02-arra)"/>
  <path d="M466 300 C 380 300, 268 292, 268 194" fill="none" stroke="#0fa07f" stroke-width="2" marker-end="url(#l02-arrg)"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="80" y="170" font-size="11.5" font-weight="700" text-anchor="middle">NEW</text>
    <text x="268" y="164" font-size="11.5" font-weight="700" text-anchor="middle" fill="#3553ff">RUNNABLE</text>
    <text x="268" y="180" font-size="8.5" text-anchor="middle" opacity="0.85">wants a CPU</text>
    <text x="540" y="164" font-size="11.5" font-weight="700" text-anchor="middle" fill="#0fa07f">RUNNING</text>
    <text x="540" y="180" font-size="8.5" text-anchor="middle" opacity="0.85">owns a core right now</text>
    <text x="781" y="164" font-size="11.5" font-weight="700" text-anchor="middle">TERMINATED</text>
    <text x="781" y="180" font-size="8.5" text-anchor="middle" opacity="0.85">stack freed</text>
    <text x="540" y="304" font-size="11.5" font-weight="700" text-anchor="middle" fill="#e0930f">BLOCKED</text>
    <text x="540" y="320" font-size="8.5" text-anchor="middle" opacity="0.85">off the run queue</text>
    <text x="268" y="54" font-size="9.5" font-weight="700" text-anchor="middle" fill="#3553ff">kernel RUN QUEUE — one per CPU</text>
    <text x="163" y="152" font-size="9" text-anchor="middle">start()</text>
    <text x="402" y="143" font-size="9" text-anchor="middle">scheduler picks it</text>
    <text x="404" y="196" font-size="9" text-anchor="middle" opacity="0.9">preempted:</text>
    <text x="404" y="210" font-size="9" text-anchor="middle" opacity="0.9">time slice up</text>
    <text x="655" y="152" font-size="9" text-anchor="middle">returns</text>
    <text x="655" y="184" font-size="9" text-anchor="middle">or raises</text>
    <text x="524" y="214" font-size="9" font-weight="700" fill="#e0930f">blocking syscall:</text>
    <text x="524" y="230" font-size="9" fill="#e0930f" opacity="0.95">recv(), open(), lock.acquire()</text>
    <text x="524" y="246" font-size="9" fill="#e0930f" opacity="0.95">time.sleep() — and in CPython</text>
    <text x="524" y="262" font-size="9" fill="#e0930f" opacity="0.95">the GIL is released here</text>
    <text x="232" y="356" font-size="9.5" font-weight="700" fill="#0fa07f">I/O completes → the kernel puts it back on the run queue</text>
    <text x="648" y="294" font-size="8.5" opacity="0.9">A blocked thread burns zero</text>
    <text x="648" y="310" font-size="8.5" opacity="0.9">CPU — it costs only its own</text>
    <text x="648" y="326" font-size="8.5" opacity="0.9">stack. 10,000 of them is a</text>
    <text x="648" y="342" font-size="8.5" opacity="0.9">memory problem, not a slow one.</text>
    <text x="440" y="386" font-size="11" text-anchor="middle" opacity="0.9">Blocking wastes nothing but the thread's own memory. Spinning wastes a core. That distinction is the whole phase.</text>
    <text x="24" y="230" font-size="9" opacity="0.9">Only RUNNING consumes</text>
    <text x="24" y="246" font-size="9" opacity="0.9">a core. RUNNABLE means</text>
    <text x="24" y="262" font-size="9" opacity="0.9">"ready, but queued".</text>
    <text x="24" y="286" font-size="9" font-weight="700" opacity="0.95">Measured: one forced</text>
    <text x="24" y="302" font-size="9" font-weight="700" opacity="0.95">switch = 20.97 us,</text>
    <text x="24" y="318" font-size="9" opacity="0.9">≈ 210 DRAM accesses.</text>
  </g>
</svg>
```

Two transitions carry all the weight.

**Preemption.** A running thread does not get the CPU until it is finished; it gets a **time slice**. When the slice expires a timer interrupt fires, the kernel saves the thread's registers, puts it back on the run queue as *runnable*, and picks somebody else. This is why a single runaway loop cannot freeze your machine, and why "my thread ran" and "my thread ran to completion" are different claims. Priorities (`nice` on Linux) bias which runnable thread gets picked, but they never let a thread hold a core forever.

**Blocking.** When a thread makes a blocking system call, the kernel takes it **off the run queue entirely** and parks it on a wait queue attached to whatever it is waiting for. From that moment it is not considered for scheduling at all. It consumes no CPU, contributes nothing to load average, and costs only the memory of its own stack. When the data arrives, the kernel moves it back to runnable and the scheduler will get to it.

That is the sentence to remember from this section: **a blocked thread wastes nothing but its own memory.** This is why "one thread per connection" is not automatically absurd — 10,000 blocked threads burn zero CPU. What kills that design is memory and switching, both of which we are about to price, and it is what lesson 03 replaces with a single thread watching 10,000 sockets.

### What a context switch actually costs

Every time the scheduler swaps one thread for another, someone pays. The bill has two halves, and the second is invisible in every profiler you will ever open.

The **direct cost** is the work you can point at: enter the kernel, save the outgoing thread's register set into its kernel structure, pick the next thread, restore its registers, return to user mode. On a **process** switch you additionally reload the page-table base register, which invalidates cached address translations in the **TLB** (Translation Lookaside Buffer — the small cache of virtual-to-physical mappings the CPU consults on every memory access). Modern CPUs tag TLB entries by address space to soften this, but a process switch is still strictly more expensive than a thread switch, which keeps the same page table.

The **indirect cost** is worse and does not appear as switch time at all. The outgoing thread left the L1 and L2 caches full of *its* data. The incoming thread's first few thousand memory accesses miss, hitting L3 or DRAM, at roughly 100x the latency of an L1 hit. Its branch predictor history is wrong too. So the switch appears to cost a few microseconds, and then the *next* stretch of execution runs measurably slower for reasons nothing attributes to the switch. When people say a system is "thrashing", this is usually the mechanism: so much switching that no thread stays resident long enough to warm the cache it needs.

The Build It measures the direct cost with two threads ping-ponging on a pair of events: **20.97 µs per forced switch**. Put that next to the numbers from Phase 0's memory-hierarchy lesson — about 1 ns for an L1 hit, about 100 ns for main memory — and one switch costs roughly **20,970 L1 accesses**, or **210 trips to DRAM**. A switch is not "a little overhead". It is the price of thousands of loads, and that is before the cache pollution.

**The trap.** Nobody sets out to switch a lot. You get there by accident: a lock that everyone contends, a queue with too small a batch, a `sleep(0)` polling loop, a thread pool sized at 500 on an 8-core box. The symptom is CPU pegged at 100% with terrible throughput and a profiler that shows no single hot function, because the cost is spread thinly across every function.

### fork, copy-on-write, and why a process costs more

Creating a process on Unix is `fork()`: the kernel duplicates the calling process — page table, descriptors, everything — and returns twice, once in each. Copying gigabytes of heap would be absurd, so it does not. **Copy-on-write (COW)**: both processes' page tables point at the *same* physical pages, all marked read-only. The first time either one writes to a page, the CPU faults, the kernel copies that single 4 KB page, and lets the write proceed. Pages that are only read are never duplicated.

COW is why `fork()` is fast — the Build It measures **920.2 µs**, about **11.2x** a thread but still under a millisecond — and why a forked worker pool starts cheap even with a large loaded model in memory. It is also why the savings quietly evaporate in CPython: every time you *touch* a Python object, even just to read it, its reference count changes, which is a write, which faults in a copy of that page. A forked Python worker's memory converges toward a full copy as it runs.

There is a second way to start a process: **spawn**. Launch a fresh interpreter, re-import your module, and pickle the target function and arguments across a pipe. Nothing is inherited, which makes it predictable — and slow. The Build It measures **36.0 ms**, about **440x a thread and 39x a fork**.

Which one you get is platform history, and it matters. `fork` is the default only on Linux; macOS and Windows default to `spawn` (macOS *has* `fork` but Python 3.8+ refuses to use it by default because Apple's system libraries crash in forked children). Python 3.14 changes the Linux default to `forkserver`, a hybrid that forks from a small, clean, pre-forked helper process. So the same `multiprocessing` code can be 40x cheaper to start on your CI box than on your laptop, and can *work* on one and deadlock on the other.

**The fork-plus-threads footgun.** `fork()` duplicates the address space but only **one thread** — the caller. If another thread happened to be holding a lock at the instant of the fork, that lock exists in the child, held forever by a thread that does not exist there. The child then deadlocks the first time it touches whatever that lock protected: `malloc`'s arena lock, a logging handler's lock, a connection pool. This is not exotic — it is why a Gunicorn worker that forks after starting a metrics thread hangs on its first log line. CPython 3.12 emits a `DeprecationWarning` when you `os.fork()` from a multi-threaded process for exactly this reason. Rule: **fork first, thread second**, or use `spawn`/`forkserver`.

And the structural cost that never goes away: separate address spaces mean **you cannot share an object**. Every value that crosses between processes must be serialised (pickled), pushed through a pipe or socket, and deserialised. That is a real CPU and latency cost proportional to your data, and it is why "just use multiprocessing" is a bad reflex for anything chatty.

### The GIL: what it is and why it exists

The **GIL** (Global Interpreter Lock) is a single mutex, one per interpreter, that a thread **must hold to execute CPython bytecode**. Not to exist, not to run C code, not to wait — to execute bytecode. One holder at a time, process-wide.

First, be precise about what it is not: **the GIL is not part of the Python language.** It is an implementation detail of **CPython**, the reference interpreter you almost certainly run. Jython (on the JVM) and IronPython (on .NET) have never had one. PyPy has one. And CPython itself now ships a build without one, which we will get to.

So why does the reference implementation have a global lock in it? Because of how CPython manages memory. Every object carries a **reference count** — an integer tracking how many things point at it — and the object is freed the instant that count hits zero. Every assignment, every argument pass, every list append, every loop iteration adjusts refcounts. It is the single most frequent operation in the interpreter.

An increment that two threads perform at once can lose an update: both read 5, both write 6, and the true count of 7 is gone forever. Undercount and you free an object somebody is still using — a use-after-free, in a language whose entire promise is that this cannot happen. The fix in principle is to make every refcount update an atomic hardware operation. The problem is that atomics are dramatically more expensive than plain increments, especially under contention, and they run on the hottest path in the interpreter. Historically, every serious attempt to remove the GIL this way made **single-threaded** Python substantially slower — and the overwhelming majority of Python programs are single-threaded. Guido van Rossum's long-standing condition, that no GIL removal may slow down single-threaded code, was not stubbornness; it was refusing to tax every user to benefit some.

One global lock made all of that go away, and bought two more things worth naming: C extension authors got to assume their code is not re-entered concurrently unless they say otherwise, which is a large part of why Python's C ecosystem exists at all; and CPython's own internal structures needed no locking. The GIL is a deliberate, coherent engineering trade. It just happens to be exactly the wrong trade for the workload in The Problem.

### What the GIL does and does not block

Here is the rule the whole lesson reduces to.

**The GIL is held while executing bytecode. It is released whenever a thread is not executing bytecode.**

Held, and therefore serialised:

- Your Python loops, arithmetic, attribute lookups, comprehensions, string building, JSON parsing in pure Python, any `for` over anything. Two threads doing this take turns. A thread holding the GIL is asked to drop it after **`sys.getswitchinterval()`**, which defaults to **5 ms** — a request, checked at bytecode boundaries, not a preemption.

Released, and therefore genuinely concurrent:

- **Blocking I/O syscalls.** Every socket read, file read, and `accept()` in the standard library wraps the syscall in `Py_BEGIN_ALLOW_THREADS` / `Py_END_ALLOW_THREADS`. The thread drops the GIL, blocks in the kernel, and reacquires it when the data arrives. This is *the* reason threaded I/O works in Python.
- **`time.sleep()`**, which is why the Build It can simulate I/O honestly.
- **Many C extensions**: NumPy on large arrays, `hashlib`, `zlib`/`gzip`, image codecs, most database drivers around their network calls. If the heavy loop is in C and does not touch Python objects, the author can and usually does release the GIL around it.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 400" width="100%" style="max-width:840px" role="img" aria-label="Two timelines. On the left, four CPU-bound threads on four cores take strict turns holding the GIL, so only one thread executes bytecode at any instant and three cores sit idle; the measured speedup from one to eight threads is 1.00x. On the right, four I O-bound threads each hold the GIL only for a brief sliver before releasing it for the duration of a blocking system call, so all four waits overlap and the measured speedup is 7.91x at eight threads.">
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The same four threads, twice: holding the GIL vs releasing it</text>
  <g fill="none" stroke-linejoin="round" stroke-width="2">
    <rect x="16" y="44" width="418" height="316" rx="12" fill="#d64545" fill-opacity="0.07" stroke="#d64545" stroke-opacity="0.75"/>
    <rect x="446" y="44" width="418" height="316" rx="12" fill="#0fa07f" fill-opacity="0.08" stroke="#0fa07f"/>
    <rect x="32" y="296" width="386" height="56" rx="9" fill="#e0930f" fill-opacity="0.12" stroke="#e0930f"/>
    <rect x="462" y="296" width="386" height="56" rx="9" fill="#0fa07f" fill-opacity="0.14" stroke="#0fa07f"/>
  </g>
  <g fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.35" stroke-width="1">
    <rect x="100" y="104" width="318" height="24" rx="3"/><rect x="100" y="138" width="318" height="24" rx="3"/>
    <rect x="100" y="172" width="318" height="24" rx="3"/><rect x="100" y="206" width="318" height="24" rx="3"/>
    <rect x="530" y="104" width="318" height="24" rx="3"/><rect x="530" y="138" width="318" height="24" rx="3"/>
    <rect x="530" y="172" width="318" height="24" rx="3"/><rect x="530" y="206" width="318" height="24" rx="3"/>
  </g>
  <g fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.2">
    <rect x="100" y="104" width="39" height="24" rx="3"/><rect x="256" y="104" width="39" height="24" rx="3"/>
    <rect x="139" y="138" width="39" height="24" rx="3"/><rect x="295" y="138" width="39" height="24" rx="3"/>
    <rect x="178" y="172" width="39" height="24" rx="3"/><rect x="334" y="172" width="39" height="24" rx="3"/>
    <rect x="217" y="206" width="39" height="24" rx="3"/><rect x="373" y="206" width="39" height="24" rx="3"/>
    <rect x="532" y="104" width="18" height="24" rx="3"/><rect x="760" y="104" width="18" height="24" rx="3"/>
    <rect x="552" y="138" width="18" height="24" rx="3"/><rect x="780" y="138" width="18" height="24" rx="3"/>
    <rect x="572" y="172" width="18" height="24" rx="3"/><rect x="800" y="172" width="18" height="24" rx="3"/>
    <rect x="592" y="206" width="18" height="24" rx="3"/><rect x="820" y="206" width="18" height="24" rx="3"/>
  </g>
  <g fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f" stroke-width="1.2">
    <rect x="550" y="104" width="210" height="24" rx="3"/><rect x="570" y="138" width="210" height="24" rx="3"/>
    <rect x="590" y="172" width="210" height="24" rx="3"/><rect x="610" y="206" width="210" height="24" rx="3"/>
  </g>
  <g fill="none" stroke="currentColor" stroke-opacity="0.55" stroke-width="1.3">
    <path d="M100 242 L 418 242"/><path d="M530 242 L 848 242"/>
    <path d="M139 242 L 139 248"/><path d="M178 242 L 178 248"/><path d="M217 242 L 217 248"/><path d="M256 242 L 256 248"/>
    <path d="M295 242 L 295 248"/><path d="M334 242 L 334 248"/><path d="M373 242 L 373 248"/>
  </g>
  <g fill="#e0930f" fill-opacity="0.55" stroke="#e0930f" stroke-width="1.2">
    <rect x="32" y="272" width="14" height="12" rx="2"/><rect x="462" y="272" width="14" height="12" rx="2"/>
  </g>
  <rect x="250" y="272" width="14" height="12" rx="2" fill="#7f7f7f" fill-opacity="0.16" stroke="currentColor" stroke-opacity="0.35" stroke-width="1"/>
  <rect x="576" y="272" width="14" height="12" rx="2" fill="#0fa07f" fill-opacity="0.34" stroke="#0fa07f" stroke-width="1.2"/>
  <g font-family="'JetBrains Mono', ui-monospace, monospace" fill="currentColor">
    <text x="225" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#d64545">4 CPU-BOUND THREADS · 4 CORES · 1 GIL</text>
    <text x="225" y="88" font-size="9" text-anchor="middle" opacity="0.9">they take strict turns; 3 cores idle the whole time</text>
    <text x="655" y="70" font-size="12" font-weight="700" text-anchor="middle" fill="#0fa07f">4 I/O-BOUND THREADS · THE GIL IS RELEASED</text>
    <text x="655" y="88" font-size="9" text-anchor="middle" opacity="0.9">each drops the GIL before it waits, so the waits overlap</text>
    <g font-size="8.5" opacity="0.9">
      <text x="30" y="121">thread 1</text><text x="30" y="155">thread 2</text><text x="30" y="189">thread 3</text><text x="30" y="223">thread 4</text>
      <text x="460" y="121">thread 1</text><text x="460" y="155">thread 2</text><text x="460" y="189">thread 3</text><text x="460" y="223">thread 4</text>
    </g>
    <g font-size="7" font-weight="700" text-anchor="middle" fill="currentColor" opacity="0.85">
      <text x="119.5" y="120">GIL</text><text x="275.5" y="120">GIL</text><text x="158.5" y="154">GIL</text><text x="314.5" y="154">GIL</text>
      <text x="197.5" y="188">GIL</text><text x="353.5" y="188">GIL</text><text x="236.5" y="222">GIL</text><text x="392.5" y="222">GIL</text>
    </g>
    <text x="197" y="121" font-size="7.5" text-anchor="middle" opacity="0.75">waiting for the GIL</text>
    <text x="715" y="222" font-size="7.5" text-anchor="middle" opacity="0.85">blocked in recv() — GIL released</text>
    <text x="100" y="262" font-size="8.5" opacity="0.85">one block ≈ one 5 ms switch interval</text>
    <text x="418" y="262" font-size="8.5" text-anchor="end" opacity="0.85">time →</text>
    <text x="530" y="262" font-size="8.5" opacity="0.85">the waiting overlaps — that IS the speedup</text>
    <text x="848" y="262" font-size="8.5" text-anchor="end" opacity="0.85">time →</text>
    <text x="52" y="282" font-size="8.5" opacity="0.9">holding the GIL (bytecode)</text>
    <text x="270" y="282" font-size="8.5" opacity="0.9">runnable, waiting</text>
    <text x="482" y="282" font-size="8.5" opacity="0.9">holds GIL</text>
    <text x="596" y="282" font-size="8.5" opacity="0.9">blocked in a syscall — GIL released</text>
    <text x="44" y="318" font-size="9" opacity="0.9">MEASURED, section 3 — pure-bytecode workload</text>
    <text x="44" y="340" font-size="11" font-weight="700">1 → 8 threads: 1.00x   ·   1 → 8 processes: 3.14x</text>
    <text x="474" y="318" font-size="9" opacity="0.9">MEASURED, section 4 — the identical threads on I/O</text>
    <text x="474" y="340" font-size="11" font-weight="700">1 → 8 threads: 7.91x   ·   16 threads: 14.73x</text>
    <text x="440" y="386" font-size="11" text-anchor="middle" opacity="0.9">The GIL serialises bytecode, not waiting. Everything in this lesson follows from that one sentence.</text>
  </g>
</svg>
```

Two footnotes on the left panel, because reality is slightly worse than "no gain".

The **convoy effect**: when a CPU-bound thread holds the GIL and an I/O-bound thread's data arrives, the I/O thread wakes, cannot get the GIL, and goes back to sleep for up to a full switch interval — repeatedly. Your latency-sensitive request queues behind a background job that is merely *busy*. This was much worse before CPython 3.2's GIL rewrite replaced "drop every 100 bytecodes" with the current timed handoff, but 5 ms is still an eternity for a request that should take 2 ms. If a background CPU task is hurting tail latency, move it to a process; do not reach for `sys.setswitchinterval()` first.

And the reason threaded CPU work can land *below* 1.0x: the threads do all the work of one thread, plus GIL acquisition, release, and handoff, plus a context switch every 5 ms, plus each thread's working set repeatedly evicting the others' from cache. You pay for concurrency and receive none.

### The escape hatches

Four ways out, in rough order of how often you should reach for them.

- **`multiprocessing` / `ProcessPoolExecutor`** — the boring, correct answer for CPU-bound Python. Each process has its own interpreter and its own GIL, so they are genuinely parallel: **3.14x on 8 processes** in the Build It against 1.00x for threads. The price is everything from the fork section: ~11x the startup, no shared objects, and serialisation on every argument and every result.
- **C extensions that release the GIL** — the answer you may already have. If your hot loop is NumPy, Pandas, Polars, `hashlib`, `zlib`, Pillow, or a compiled kernel from Cython/Numba/Rust with the GIL released, threads *already* give you parallelism. The Build It proves this: sha256 over the same total bytes scales **3.29x on 4 threads** while pure bytecode scales 1.00x. Before you re-architect around processes, check whether your bottleneck is bytecode at all.
- **Subinterpreters** — PEP 554 and PEP 734 give each interpreter inside one process its own GIL (the per-interpreter GIL landed in 3.12; the `concurrent.interpreters` standard-library module arrives in 3.14). You get parallelism with process-like isolation but without a new OS process, and communication is still by copying or by a narrow channel of shareable objects. Promising; not yet where most production code lives.
- **Free-threaded CPython** — PEP 703. A separate build (`--disable-gil`, shipped as an official experimental variant from 3.13 and formally supported-but-experimental in 3.14) with no GIL at all, using biased reference counting, deferred refcounting for hot immortal objects, and per-object locks. It is real and it works: CPU-bound threads scale.

Say plainly what changes and what does not. **Removing the GIL removes the serialisation of bytecode. It removes nothing else.** Your data races were always there; the GIL never made your code thread-safe, it only made the window narrow enough that you usually got away with it. A `counter += 1` from two threads was already a race under the GIL (it is multiple bytecodes with a switch point between them); without the GIL it is a race that actually fires. Everything in lessons 08, 09 and 10 — atomicity, critical sections, locks, deadlock — becomes **more** important on a free-threaded build, not less. There is also still a cost: single-threaded free-threaded builds have historically run several percent slower, and C extensions must be explicitly declared compatible or the interpreter re-enables the GIL at import.

### How other runtimes differ

Worth two minutes, because it tells you which ideas here transfer.

- **Go** — **goroutines** are user-space threads multiplexed onto a small pool of OS threads (an **M:N** model). A goroutine starts with a ~2 KB growable stack instead of an 8 MiB reservation, so a million of them is ordinary. The runtime scheduler moves them between OS threads, and when one blocks on a syscall it detaches the OS thread and keeps the others running. No GIL: CPU-bound goroutines use every core. Everything in this lesson about the *scheduler*, *context switches* and *shared memory* transfers exactly; goroutine switches are just much cheaper because they never enter the kernel.
- **Java** — **platform threads** are 1:1 OS threads with ~1 MB stacks, so pools are sized in the low hundreds. **Virtual threads** (Project Loom, final in Java 21) are the goroutine idea retrofitted: millions of cheap threads on a small carrier pool, where a blocking call parks the virtual thread instead of the OS thread. No GIL either way; Java has always required real locks, which is exactly the point about free-threaded Python.
- **Node.js** — one thread runs your JavaScript, period. Concurrency comes from the event loop (lesson 04's subject) plus a small `libuv` worker pool for file I/O and CPU-bound built-ins like crypto and compression. This is Python's async story with the choice removed: I/O concurrency is excellent, and CPU-bound work must go to `worker_threads` or a child process. Note the shape — Node's worker pool for crypto is precisely "a C extension that releases the GIL".

The pattern: everyone solves *waiting* with cheap user-space concurrency, and everyone solves *computing* with more OS-level parallelism. Only the defaults differ.

### Choosing: process, thread, or neither

A first pass that will be right most of the time. Lesson 07 turns it into a full matrix with pool sizing.

1. **Classify the work.** Run one unit and ask what it was doing. Mostly waiting on network, disk or another service → **I/O-bound**. Mostly executing your own Python → **CPU-bound**. Mostly inside NumPy/`hashlib`/a C driver → **C-bound**, which behaves like I/O-bound for our purposes because the GIL is released.
2. **I/O-bound → threads** (or, for very high connection counts, `asyncio` — lessons 03-05). Near-linear speedup up to the point where the *other* side becomes the bottleneck. Measured here: 14.73x on 16 threads.
3. **CPU-bound in pure Python → processes.** Threads will give you 1.00x. Size the pool to your *available* CPUs (see Use It — this is not `os.cpu_count()` in a container), and check that your data is cheap to pickle before you commit.
4. **C-bound → threads.** Check first, with a measurement, that the library actually releases the GIL. If it does, you get parallelism for the price of a thread.
5. **Isolation required → processes, always.** Untrusted or crash-prone code, a C library that segfaults, a per-tenant memory cap, a hard need to kill a runaway task: only a separate address space gives you these. A thread cannot be safely killed at all — Python has no API for it, because there is no way to unwind another thread's stack without leaving shared state broken.

## Build It

[`code/threads_and_gil.py`](code/threads_and_gil.py) is not a demo. It is six experiments, each of which prints a number that settles an argument. Standard library only.

The two workloads have to be chosen with care, because the entire result depends on which one releases the GIL. This is the CPU-bound one — deliberately dull, deliberately pure bytecode, touching no C library that might quietly let another thread through:

```python
def spin(n: int) -> int:
    """Pure CPython bytecode. Touches no C library that could release the GIL."""
    x = 0
    for i in range(n):
        x += i * i
    return x
```

And this is its mirror. `time.sleep()` is a syscall wrapped in `Py_BEGIN_ALLOW_THREADS`: the thread drops the GIL for the whole duration, which is exactly what a socket read does:

```python
def sleep_chunk(count: int) -> None:
    """Blocking I/O, faked. time.sleep() releases the GIL for its whole duration."""
    for _ in range(count):
        time.sleep(IO_SLEEP)
```

Every experiment keeps the *total work fixed* and varies only the number of workers, so the speedup column means what it says. The thread runner starts every thread before joining any — join-as-you-go would silently serialise the whole thing, which is the most common way a threading benchmark lies to its author:

```python
def run_threads(fn, args_list) -> float:
    """Wall time to run every task on its own thread, all started before any join."""
    threads = [threading.Thread(target=fn, args=(a,)) for a in args_list]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return time.perf_counter() - t0
```

The context-switch measurement forces the scheduler's hand. Two threads bounce a pair of `threading.Event`s back and forth; neither can proceed until the other has run, so every half-round-trip is a genuine block-and-wake:

```python
partner = threading.Thread(target=pong)      # pong(): a.wait(); a.clear(); b.set()
partner.start()
t0 = time.perf_counter()
for _ in range(PINGPONG_ROUNDS):
    a.set()
    b.wait()
    b.clear()
elapsed = time.perf_counter() - t0
per_switch_us = elapsed / (PINGPONG_ROUNDS * 2) * 1e6
```

Timings on a shared machine are noisy in one direction only — interference can make a run slower, never faster — so each measurement is the **fastest of several rounds**:

```python
def best_of(measure, rounds: int = ROUNDS) -> float:
    """Fastest of N timed rounds. Scheduler noise can only make a run slower."""
    return min(measure() for _ in range(rounds))
```

Run it:

```bash
docker compose exec -T app python phases/08-concurrency-and-performance/02-processes-threads-and-the-gil/code/threads_and_gil.py
```

```console
== 0 · THE MACHINE AND THE INTERPRETER (every number below is theirs) ==
  python           3.12.13  (cpython)
  os.cpu_count()   10
  schedulable CPUs 10   <- what this process may actually use
  GIL              enabled (build predates sys._is_gil_enabled, so it cannot be disabled)
  switch interval  5.0 ms   <- how long a thread may hold the GIL
  start method     fork

== 1 · A THREAD IS CHEAP, A PROCESS IS NOT — BY HOW MUCH? ==
  create+start+join a thread               81.9 us   (n=200)
  create+start+join a fork()ed proc       920.2 us   (n=50)    11.2x a thread
  create+start+join a spawn()ed proc    36005.4 us   (n=10)   439.7x a thread

  threading.stack_size()  0  (0 = platform default)
  RLIMIT_STACK soft       8388608 bytes = 8 MiB reserved per thread stack
  200 idle threads alive at once:
    virtual  +6758084 KB =    33790 KB/thread  <- address space RESERVED (stack + a malloc arena)
    resident +   4236 KB =       21 KB/thread  <- pages actually FAULTED IN
  extrapolate to 10,000 threads:
    stack reserve alone   8 MiB x 10,000 =      78 GiB of address space
    measured virtual              x 10,000 =     322 GiB of address space
    measured resident             x 10,000 =    0.20 GiB of real RAM
  -> the reservation is unaffordable, the residency is merely expensive. Lesson 03 needs this.

== 2 · ONE CONTEXT SWITCH COSTS THOUSANDS OF MEMORY ACCESSES ==
  20000 ping-pong round trips (2 switches each) in 0.839 s
  -> 20.97 us per forced context switch

  one switch buys you    20,970  x  L1 cache hit         (~1 ns, lesson 01)
  one switch buys you       210  x  main memory (DRAM)   (~100 ns, lesson 01)
  A switch is not 'a bit of overhead'. It is the price of thousands of loads,
  and that is before the cache pollution the next thread inherits.

== 3 · CPU-BOUND: THREADS BUY YOU NOTHING, PROCESSES BUY YOU CORES ==
  fixed total work: 12,000,000 integer ops of pure bytecode

  THREADS (threading.Thread)
     1 threads    0.502 s   speedup  1.00x  ##
     2 threads    0.501 s   speedup  1.00x  ##
     4 threads    0.509 s   speedup  0.99x  ##
     8 threads    0.504 s   speedup  1.00x  ##

  PROCESSES (multiprocessing.Pool, fork)
     1 procs      0.587 s   speedup  1.00x  ##
     2 procs      0.412 s   speedup  1.43x  ###
     4 procs      0.262 s   speedup  2.24x  #####
     8 procs      0.187 s   speedup  3.14x  ########

  workers   threads   processes
     1        1.00x      1.00x
     2        1.00x      1.43x
     4        0.99x      2.24x
     8        1.00x      3.14x

  Same machine, same cores, same total work. The threads took turns:
  a 0.50 s run has room for only ~100 forced GIL handoffs at a 5 ms switch interval,
  so the 8 threads were not interleaving finely — they were queueing for one lock.
  (Processes fall short of 8x because this sandbox's vCPUs are shared and
   not all equally fast. The point is the COLUMN GAP, not the absolute ceiling.)

== 4 · I/O-BOUND: THE SAME THREADS, THE SAME GIL, NEAR-LINEAR SPEEDUP ==
  fixed total work: 16 tasks x 50 ms of blocking wait = 0.80 s serial

     1 threads    0.807 s   speedup  1.00x  ##
     2 threads    0.401 s   speedup  2.01x  #####
     4 threads    0.204 s   speedup  3.95x  #########
     8 threads    0.102 s   speedup  7.91x  ###################
    16 threads    0.055 s   speedup 14.73x  ###################################

  Nothing about the GIL changed between section 3 and section 4.
  What changed is whether the thread was HOLDING it while it waited.

== 5 · PROOF IT IS THE BYTECODE LOCK: A C CALL THAT DROPS THE GIL SCALES ==
  fixed total work: 40 x sha256 over 24 MiB = 960 MiB

     1 threads    0.698 s   speedup  1.00x  ##
     2 threads    0.329 s   speedup  2.12x  #####
     4 threads    0.212 s   speedup  3.29x  ########

  hashlib on 4 threads: 3.29x
  Identical thread code, identical interpreter. The only difference is that
  sha256_update() wraps its C loop in Py_BEGIN_ALLOW_THREADS and spin() cannot.

== 6 · SHARED MEMORY IS THE WHOLE DIFFERENCE BETWEEN A THREAD AND A PROCESS ==
  parent sets COUNTER=42
    child/thread sees COUNTER=42, sets it to 99
  after the THREAD ran:  COUNTER=99   <- the write landed in OUR heap

    child/thread sees COUNTER=42, sets it to 777
  after the PROCESS ran: COUNTER=42   <- the child copied our page and wrote to the copy
  via mp.Value (real shared memory + a lock): 777   <- sharing across processes is opt-in and explicit

(total runtime 17.6 s)
```

**Read the numbers — five of these sections are arguments, not demos.**

**Section 1 prices the units.** A thread costs **81.9 µs** to create and reap; a `fork()`ed process **920.2 µs**, **11.2x** more; a `spawn()`ed process **36 ms**, **439.7x** more. That 440x is not academic: it is the difference between a `ProcessPoolExecutor` that starts in a blink on your Linux CI and one that takes 1.4 seconds to start 40 workers on a developer's Mac, where `spawn` is the default. Then the memory. `threading.stack_size()` returns `0`, meaning "platform default", and the platform default here is the **8 MiB** `RLIMIT_STACK`. Ten thousand threads would therefore *reserve* **78 GiB** of address space for stacks alone — and the measured reservation is worse, **322 GiB**, because glibc also hands each thread its own malloc arena. But the **resident** cost is only **21 KB per thread**, because stack pages are faulted in lazily and an idle thread touches almost none of them: 10,000 threads is **0.20 GiB** of real RAM. Both halves matter. Thread-per-connection does not die of RAM; it dies of address-space reservation, scheduler pressure, and the switching cost in section 2. That is the gap lesson 03 walks into.

**Section 2 prices the switch: 20.97 µs.** Against the memory hierarchy from Phase 0, that is **20,970 L1 cache hits** or **210 round trips to DRAM** — for the privilege of changing which thread is running, once. This is the number that makes "just add more threads" a bad instinct. Two hundred threads on ten cores, each getting preempted a few hundred times a second, spends whole cores on nothing but switching, and the profiler will show you a flat profile with no hot function to blame.

**Section 3 is the headline, and the two columns are the lesson.** Identical total work — 12 million integer operations — split across 1, 2, 4 and 8 workers. Threads: **1.00x, 1.00x, 0.99x, 1.00x.** Eight threads on a ten-core machine produced **zero** additional throughput, and the 4-thread run was actually a hair *slower* than one thread. Processes on the same work, same machine, same moment: **1.43x, 2.24x, 3.14x.** Nothing about the code changed except which unit of concurrency ran it. And note the honest caveat the program prints: the process column falls short of a clean 8x because this sandbox's ten vCPUs are shared with a hypervisor and not all equally fast. That is a property of the box, not of the argument — the argument is the **gap between the columns**, which is enormous and never disappears no matter how many times you run it. The handoff count is the mechanism in one line: a 0.50 s run at a 5 ms switch interval has room for only **~100 forced GIL handoffs**, so the eight threads were not finely interleaved. They were queueing.

**Section 4 is the same experiment with one thing changed, and it is not the GIL.** Sixteen tasks, 50 ms of blocking wait each, 0.80 s of work if you do it serially. On threads: **2.01x, 3.95x, 7.91x, 14.73x.** That 14.73x out of a theoretical 16x is 92% efficiency, and the missing 8% is thread creation and the scheduler. The GIL is present, enabled, and completely irrelevant, because a thread inside `time.sleep()` is not executing bytecode and has released it. Sections 3 and 4 use the same `threading.Thread`, the same interpreter and the same host. Only the workload differs. **That is the whole lesson: it was never "threads are slow in Python", it was always "bytecode is serialised in CPython".**

**Section 5 removes the last escape route for anyone still blaming threads.** `hashlib.sha256` over 960 MiB — a workload that is unambiguously CPU-bound, pegging a core, doing no I/O whatsoever — scales **2.12x on 2 threads and 3.29x on 4**. Pure bytecode over the same threads scaled 1.00x. The only difference is a pair of macros in C: `sha256_update()` wraps its inner loop in `Py_BEGIN_ALLOW_THREADS`, and `spin()` has no way to. So before you rewrite a CPU-bound service around `multiprocessing`, find out whether your hot loop is Python at all. If it is NumPy or a compression codec or a database driver's network call, threads already work.

**Section 6 is the shortest and hardest to argue with.** A global set to 42. A thread sets it to 99 and the parent reads **99** — same heap, one write, visible immediately. A forked process sets it to 777 and the parent reads **42** — the child *saw* 42 (COW gave it the inherited page), wrote to its own private copy, and exited with it. Same code, same variable name, opposite outcome. Then `mp.Value` returns **777**, because sharing across processes is opt-in, explicit, and comes with its own lock. That is process isolation stated as an experiment rather than a claim, and it is simultaneously the reason processes are safe and the reason they are expensive.

## Use It

Three modules, one question each.

**`threading` — I/O-bound work, or C libraries that release the GIL.**

```python
import threading, urllib.request

def fetch(url: str, out: dict) -> None:
    with urllib.request.urlopen(url, timeout=5) as r:
        out[url] = r.status                 # a plain dict: shared heap, no serialisation

results: dict[str, int] = {}
threads = [threading.Thread(target=fetch, args=(u, results)) for u in urls]
for t in threads: t.start()                 # start ALL of them before joining ANY
for t in threads: t.join(timeout=30)        # always bound the join
```

Note what you did *not* have to do: no pickling, no queue, no result plumbing. `results` is just a dict on the shared heap. (Writing to distinct keys of a dict happens to be safe under CPython's GIL. Do not build on that — lesson 08 shows the read-modify-write that is not, and a free-threaded build removes the accident entirely.)

**`multiprocessing` — CPU-bound pure-Python work, and anything needing isolation.**

```python
from multiprocessing import get_context

def score(batch: list[int]) -> int:         # MUST be importable at module level to pickle
    return sum(x * x for x in batch)

if __name__ == "__main__":                  # required: spawn re-imports this module
    ctx = get_context("spawn")              # explicit > platform default; portable > fast
    with ctx.Pool(processes=available_cpus()) as pool:
        totals = pool.map(score, batches, chunksize=16)
```

Two details that are not decoration. `get_context("spawn")` makes the start method explicit so your code behaves the same on Linux, macOS and Windows — the alternative is code that works everywhere except the one platform you did not test. And `chunksize` amortises the pickle-plus-pipe round trip: with the default of 1 and small tasks, you can spend more time serialising than computing, and your parallel version comes out slower than the loop it replaced.

**`concurrent.futures` — the same two things behind one interface.**

```python
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed

Executor = ThreadPoolExecutor if workload_is_io_bound else ProcessPoolExecutor
with Executor(max_workers=n) as pool:
    futures = {pool.submit(handle, item): item for item in items}
    for fut in as_completed(futures):
        try:
            use(fut.result())
        except Exception:
            log.exception("item %s failed", futures[fut])   # or it vanishes silently
```

`ThreadPoolExecutor` and `ProcessPoolExecutor` are API-compatible, so swapping one for the other is a one-word change — which is precisely the experiment you should run before arguing about which is faster. `run_threads()` in the Build It is a hand-rolled `ThreadPoolExecutor.map`. The `try` around `fut.result()` is not optional: an exception inside a worker is stored on the future and re-raised only when you ask for the result, so an un-inspected future is a silently swallowed error.

**Sizing a pool: `cpu_count()` is a lie in a container.**

This one causes real incidents. `os.cpu_count()` reports the **host's** cores. `len(os.sched_getaffinity(0))` reports the CPUs this process is *pinned* to, which catches `taskset` and cpuset pinning but **not** a CPU *quota*. And a quota is what Docker's `--cpus=2` and Kubernetes' `limits.cpu: "2"` actually set. So a pod limited to 2 CPUs on a 64-core node happily reports 64 — the Build It's own section 0 prints `os.cpu_count() 10` and `schedulable CPUs 10` because this sandbox has no quota set, which is exactly the case that lulls you. Size a pool from that number and you get 64 workers fighting over two cores' worth of quota: constant switching, cgroup throttling, and latency far worse than with 2 workers.

```python
import os

def available_cpus() -> int:
    """CPUs this process may actually use — not the host's core count."""
    try:                                              # cgroup v2: Docker --cpus, k8s limits.cpu
        quota, period = open("/sys/fs/cgroup/cpu.max").read().split()
        if quota != "max":
            return max(1, int(int(quota) / int(period)))
    except OSError:
        pass
    try:                                              # cgroup v1
        q = int(open("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read())
        p = int(open("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read())
        if q > 0:
            return max(1, q // p)
    except OSError:
        pass
    try:
        return len(os.sched_getaffinity(0))           # taskset / cpuset pinning
    except AttributeError:
        return os.cpu_count() or 1
```

Python 3.13 added `os.process_cpu_count()`, which honours affinity masks and the `PYTHON_CPU_COUNT` environment variable — better than `os.cpu_count()`, but still blind to cgroup quota. Read the quota, or let your orchestrator inject the right number as an environment variable and read that.

**`sys.setswitchinterval()`.** You can change how long a thread may hold the GIL (default 5 ms, printed in section 0). Lowering it makes CPU-bound threads yield sooner, which can help a latency-sensitive thread stuck behind one — at the cost of more switches, each of which section 2 priced at 20.97 µs. It is a knob for a measured, specific convoy problem, not a tuning default. The real fix is almost always to move the CPU work into a process.

Five rules that survive contact with production:

- **Never size a pool from `os.cpu_count()` inside a container.** Read the cgroup quota or take the number from an environment variable your orchestrator sets. This is the single most common Python-in-Kubernetes performance bug, and it looks like "the service is slow under load" rather than like a configuration error.
- **Processes for CPU work, threads for I/O — but measure which one you have.** "CPU-bound" in Python means *bytecode*-bound. Time one unit of work; if the hot part is NumPy, `hashlib`, `zlib`, an image codec, or a driver's network call, the GIL is already released and threads give you 3.29x while processes give you the same plus a pickling bill.
- **Fork before you thread, or use `spawn`/`forkserver`.** A `fork()` from a multi-threaded process inherits locks held by threads that do not exist in the child, and the child deadlocks the first time it allocates or logs. Set the start method explicitly with `get_context()` so your code does not silently change behaviour between Linux, macOS and CI.
- **Bound every wait and inspect every future.** `join(timeout=...)`, `result(timeout=...)`, and a `try` around every `future.result()`. A daemon thread that hangs is invisible; a future whose exception nobody reads is a bug that never gets logged.
- **On a free-threaded build, the CPU numbers change and the risk goes up.** Expect the section-3 thread column to start scaling — and expect every latent race in lessons 08-10 to start firing, because the GIL was never a correctness guarantee, only a very effective way of losing the lottery less often. Check `sys._is_gil_enabled()` at startup and log it, so you always know which interpreter you are debugging.

## Think about it

1. Section 4 got **14.73x from 16 threads** on a 10-core machine — more speedup than there are cores. Why is that not a violation of anything? What is the largest speedup you could get from threads on a workload that spends 90% of its time waiting, and what limits it?
2. A colleague benchmarks a threaded CPU-bound function, sees 0.98x, and concludes "threads have overhead". Design an experiment that distinguishes *GIL serialisation* from *context-switch overhead* as the cause. What would you expect each to look like at 2, 4, 8 and 64 threads?
3. Section 1 measured 8 MiB reserved per thread stack but only 21 KB resident. If you set `threading.stack_size(512 * 1024)` before creating threads, what improves, what does not, and what new failure mode do you introduce? How would you find the right number?
4. Your service does 30 ms of database I/O and 20 ms of pure-Python JSON transformation per request, and you must serve 200 requests/second. Sketch a design. Where do the threads go, where do the processes go, and which of the two numbers should you try hardest to shrink first?
5. Free-threaded CPython removes the GIL. Take a piece of code you have written that relies — perhaps without your knowing — on the GIL making an operation effectively atomic. What is the operation, how would you find others like it, and what would you change first?

## Key takeaways

- A **process** is an address space plus kernel bookkeeping (PID, page table, fd table); a **thread** is an instruction stream inside one, owning only its registers, program counter and stack while sharing text, data, heap and descriptors. That sharing is why a thread cost **81.9 µs** to create against **920.2 µs** for a `fork()` (**11.2x**) and **36 ms** for a `spawn()` (**439.7x**) — and it is why every bug in lessons 08-10 exists.
- The scheduler keeps threads **runnable, running or blocked**, and a **blocked** thread is off the run queue entirely: it burns no CPU and costs only its own stack. Measured, that stack is **8 MiB reserved but 21 KB resident**, so 10,000 threads is **78 GiB of address space and 0.20 GiB of real RAM**. Thread-per-connection dies of reservation and switching, not of memory.
- One **context switch** cost **20.97 µs** — about **20,970 L1 cache hits** or **210 DRAM round trips** — plus an invisible tail of cache misses the next thread inherits. Oversized pools do not fail loudly; they burn cores on switching and produce a flat profile with nothing to blame.
- **The GIL (Global Interpreter Lock) serialises bytecode, and nothing else.** The identical experiment gave **1.00x on 8 threads** for pure Python and **7.91x on 8 threads / 14.73x on 16** for blocking I/O, because `time.sleep()` and every socket call release it. `hashlib` over 960 MiB scaled **3.29x on 4 threads** for the same reason. Processes on the CPU-bound work gave **3.14x** where threads gave 1.00x.
- The GIL is a **CPython implementation detail**, not a property of Python, and it exists because non-atomic reference counting is the interpreter's hottest operation. The escape hatches are processes, GIL-releasing C extensions, subinterpreters (PEP 554/734), and free-threaded CPython (PEP 703, 3.13+). **Removing the GIL removes bytecode serialisation, not the need for locks** — lessons 08-10 matter more on a free-threaded build, not less.
- Classify first, then choose: **I/O-bound → threads; pure-Python CPU-bound → processes; C-bound → threads; isolation required → processes, always.** And size the pool from CPUs you can actually use — `os.cpu_count()` reports the host's cores, `sched_getaffinity` misses CPU quota, and a container limited to 2 CPUs on a 64-core node will cheerfully tell you it has 64.

Next: [Blocking vs Non-Blocking I/O](../03-blocking-vs-non-blocking-io/) — how one thread watches ten thousand sockets at once with `select`, `poll` and `epoll`, which is what you reach for when the 21 KB and 20.97 µs measured here stop being affordable.
