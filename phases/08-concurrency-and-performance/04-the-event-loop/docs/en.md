# The Event Loop: Build a Reactor from Scratch

> Lesson 3's selector server handles a thousand connections on one thread, and its state lives in dictionaries keyed by file descriptor with every step of every request as a branch in one dispatch function. That is not a server; it is a runtime you wrote by accident. This lesson writes it deliberately — a real event loop with a timer heap, a ready queue and a cross-thread wakeup — and then measures the one rule the whole design rests on: a single handler calling `time.sleep(0.5)` moved the p99 of 23 *unrelated* connections from 11.36 ms to 485.00 ms, 43x worse, while p50 never budged.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Blocking vs Non-Blocking I/O](../03-blocking-vs-non-blocking-io/)
**Time:** ~85 minutes

## The Problem

The selector server from Lesson 3 works. One thread, one `select()` call, hundreds of concurrent connections, and none of the per-connection memory cost that made the thread-per-connection design fall over. It scales. Read the code again anyway.

The connection state lives in a dictionary keyed by **file descriptor** (fd — the small integer the kernel hands you for an open socket or file). Every logical step of a request — accept, read the headers, read the body, write the response, close — is another branch inside one giant dispatch function that everything funnels through. Adding a feature means adding a case to that function and another key to that dictionary.

Now try to add something completely ordinary: **"close this connection if it has been idle for 30 seconds."**

There is nowhere to put it. The only thing the program knows how to wait for is socket readiness, so the only thing that can ever wake it up is a socket. You could pass a timeout to `select()` and check every connection's last-activity timestamp on every wakeup, which is O(n) per iteration and fires at whatever resolution your busiest socket happens to give you. You could start a thread that sleeps and reaches into the connection table, and reintroduce every locking problem the single-threaded design existed to avoid. Neither is a design. Both are what people actually ship.

The same wall appears the moment you need a retry after 200 ms, a heartbeat every 5 seconds, a deadline on a slow upstream, or a result computed on a background thread delivered back into the server. Each one is a *different kind of thing to wait for*, and your program has exactly one.

You have accidentally started writing a runtime, badly. The fix is not to stop — it is to write it **deliberately**, and the design that does it is fifty years old: separate the **mechanism** (wait for events from any source, dispatch each to whoever registered for it) from the **application** (what to actually do when one fires). The mechanism is an **event loop**. Once you have built one, you will recognize the same five-step cycle inside asyncio, libuv, Netty, nginx and Redis — because there is only one shape here, and everybody built it.

## The Concept

### The reactor pattern

An event loop is a concrete instance of the **reactor pattern**: demultiplex a set of event sources and dispatch each event to a handler registered in advance for it. "Demultiplex" is the load-bearing word — many independent streams of events arrive on one thread, and something has to sort them out and route each to the right code. Four parts, and it is worth naming them separately because production bugs live in the seams:

- **The event sources.** Three of them, and you need all three. **File descriptors** becoming readable or writable. **Timers** — a deadline that expires. And **cross-thread wakeups** — some other thread wants a function run on the loop. A loop with only the first source is Lesson 3's server, which is where The Problem came from.
- **The demultiplexer.** The thing that blocks on all the fd sources at once and reports which are ready: `epoll` on Linux, `kqueue` on BSD/macOS, `select` anywhere. Python's `selectors.DefaultSelector` picks the best one available — this is exactly the object from Lesson 3, now demoted to a component.
- **The dispatcher.** The loop itself: computes how long it may sleep, calls the demultiplexer, converts readiness into a list of callbacks, and runs them. This is the part you are about to write.
- **The handlers.** Your application. Plain functions the loop calls back. The loop knows nothing about HTTP (HyperText Transfer Protocol) or your database; it knows "fd 7 is readable, and somebody left me a function for that."

The reactor is **readiness-based**: the kernel tells you *"you can read now"*, and you then perform the read yourself. Its sibling, the **proactor**, is **completion-based**: you hand the kernel a buffer and say *"perform this read and tell me when it is finished"*, and the completion event arrives with the data already in your buffer. Windows I/O Completion Ports (IOCP) and Linux's `io_uring` are completion-based; asyncio ships a `ProactorEventLoop` on Windows for exactly this reason. The distinction matters for one practical reason: a proactor can eliminate a syscall per operation and lets the kernel do the copy, which is why `io_uring` is where high-performance Linux I/O is heading. Everything else in this lesson — the timer heap, the ready queue, the never-block rule — is identical in both families.

### Anatomy of one iteration

This is the heart of the lesson, and it must be exact. Every detail below is a bug that somebody shipped.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 436" width="100%" style="max-width:840px" role="img" aria-label="One iteration of an event loop drawn as five ordered steps — compute the timeout, call the selector, collect I O callbacks, collect expired timers, and drain a snapshot of the ready queue — with an arrow looping back to repeat, beside the two data structures the loop owns: a min-heap of timers keyed on deadline and a deque of ready callbacks whose snapshot boundary separates what runs this iteration from what a callback scheduled for the next one.">
  <defs><marker id="l04-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One iteration: five steps, two data structures, forever</text>

    <g fill="none" stroke-linejoin="round" stroke-width="2">
      <rect x="40" y="60" width="342" height="48" rx="9" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="40" y="124" width="342" height="48" rx="9" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="40" y="188" width="342" height="48" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="40" y="252" width="342" height="48" rx="9" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="40" y="316" width="342" height="48" rx="9" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
      <rect x="404" y="60" width="460" height="170" rx="10" fill="#e0930f" fill-opacity="0.09" stroke="#e0930f"/>
      <rect x="404" y="252" width="460" height="134" rx="10" fill="#0fa07f" fill-opacity="0.09" stroke="#0fa07f"/>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#l04-arrow)">
      <path d="M211 108 L 211 120"/><path d="M211 172 L 211 184"/><path d="M211 236 L 211 248"/><path d="M211 300 L 211 312"/>
      <path d="M211 364 L 211 382 L 26 382 L 26 78 L 34 78"/>
      <path d="M384 84 L 400 102"/>
      <path d="M384 340 L 400 318"/>
    </g>

    <g fill="currentColor">
      <text x="54" y="82" font-size="11.5" font-weight="700" fill="#3553ff">1 · compute the timeout</text>
      <text x="54" y="98" font-size="9" opacity="0.85">ready? 0.0 · else heap[0].when - now · else None (forever)</text>
      <text x="54" y="146" font-size="11.5" font-weight="700" fill="#7c5cff">2 · selector.select(timeout)</text>
      <text x="54" y="162" font-size="9" opacity="0.85">the ONE blocking call in the whole program</text>
      <text x="54" y="210" font-size="11.5" font-weight="700" fill="#0fa07f">3 · collect I/O callbacks</text>
      <text x="54" y="226" font-size="9" opacity="0.85">every ready fd -&gt; append its handler to the ready queue</text>
      <text x="54" y="274" font-size="11.5" font-weight="700" fill="#e0930f">4 · collect expired timers</text>
      <text x="54" y="290" font-size="9" opacity="0.85">pop the heap while heap[0].when &lt;= now</text>
      <text x="54" y="338" font-size="11.5" font-weight="700" fill="#0fa07f">5 · drain a SNAPSHOT of the queue</text>
      <text x="54" y="354" font-size="9" opacity="0.85">n = len(ready); run exactly n. Never the live queue.</text>
      <text x="66" y="398" font-size="9.5" font-weight="700" opacity="0.9">repeat until stop()</text>
    </g>

    <g fill="none" stroke="#e0930f" stroke-width="1.6" stroke-opacity="0.75">
      <path d="M634 124 L 556 140"/><path d="M634 124 L 712 140"/><path d="M556 164 L 500 180"/><path d="M556 164 L 612 180"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="1.6">
      <rect x="602" y="100" width="64" height="24" rx="5"/><rect x="524" y="140" width="64" height="24" rx="5"/>
      <rect x="680" y="140" width="64" height="24" rx="5"/><rect x="468" y="180" width="64" height="24" rx="5"/>
      <rect x="580" y="180" width="64" height="24" rx="5"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9.5">
      <text x="634" y="116">+12ms</text><text x="556" y="156">+35ms</text><text x="712" y="156">+90ms</text>
      <text x="500" y="196">+51ms</text><text x="612" y="196">+40ms</text>
    </g>
    <g fill="currentColor">
      <text x="420" y="82" font-size="10.5" font-weight="700" fill="#e0930f">TIMER HEAP — min-heap keyed on deadline</text>
      <text x="420" y="222" font-size="9" opacity="0.85">peek is O(1) and IS the sleep budget · pop is O(log n) once expired</text>
    </g>

    <g fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="1.6">
      <rect x="424" y="294" width="52" height="26" rx="5"/><rect x="482" y="294" width="52" height="26" rx="5"/>
      <rect x="540" y="294" width="52" height="26" rx="5"/><rect x="598" y="294" width="52" height="26" rx="5"/>
      <rect x="656" y="294" width="52" height="26" rx="5"/>
    </g>
    <g fill="#7f7f7f" fill-opacity="0.14" stroke="currentColor" stroke-width="1.4" stroke-opacity="0.6">
      <rect x="724" y="294" width="52" height="26" rx="5"/><rect x="782" y="294" width="52" height="26" rx="5"/>
    </g>
    <path d="M716 286 L 716 328" fill="none" stroke="#d64545" stroke-width="2" stroke-dasharray="5 4"/>
    <g fill="currentColor" text-anchor="middle" font-size="9">
      <text x="450" y="311">cb1</text><text x="508" y="311">cb2</text><text x="566" y="311">cb3</text>
      <text x="624" y="311">cb4</text><text x="682" y="311">cb5</text><text x="750" y="311">cb6</text><text x="808" y="311">cb7</text>
    </g>
    <g fill="currentColor">
      <text x="420" y="274" font-size="10.5" font-weight="700" fill="#0fa07f">READY QUEUE — a deque of Handles</text>
      <text x="420" y="344" font-size="9" opacity="0.85">snapshot n = 5: exactly cb1..cb5 run this iteration</text>
      <text x="420" y="358" font-size="9" opacity="0.85">cb6/cb7 were scheduled BY cb1..cb5, so they land behind the</text>
      <text x="420" y="372" font-size="9" opacity="0.85">red line and wait — that is what stops a callback starving I/O</text>
    </g>

    <text x="440" y="422" text-anchor="middle" font-size="11" fill="currentColor" opacity="0.9">Mechanism above, application below: the loop only knows "wait for something, then call the function registered for it".</text>
  </g>
</svg>
```

**Step 1 — compute the timeout. How long may we sleep?** Three cases, in this order:

- If the ready queue is **not empty**, the timeout is **zero**. There is work to do right now; poll the selector without waiting and move on. Getting this wrong — sleeping while callbacks are pending — is a latency bug that only shows up under light load, when nothing else happens to wake you.
- Otherwise, if there are timers, the timeout is **`heap[0].when - now`**, the time until the *nearest* deadline. Not the nearest timer's full delay; the time remaining on it.
- Otherwise, **`None` — sleep forever.** This is safe only because the cross-thread wakeup (below) can always interrupt it. A loop with no wakeup mechanism must never pass `None`, and the usual botched fix is a fixed 50 ms poll, which burns CPU (Central Processing Unit) at idle and adds up to 50 ms of latency to everything.

**Step 2 — call the selector with that timeout.** This is the one blocking call in the entire program. While the process sits here it uses no CPU. A healthy event-loop server spends the overwhelming majority of its wall-clock time inside this call; in the Build It's first section the loop was asleep for **200.6 ms of 207.6 ms** of wall time.

**Step 3 — collect the I/O callbacks.** For each fd the selector reports ready, look up the handler registered for that direction (read or write) and **append it to the ready queue**. Do not call it here. Deferring makes every callback run from one place, which is what makes the next two steps possible.

**Step 4 — collect expired timers.** Pop the heap while its root deadline is `<= now`, appending each to the ready queue. Note the ordering: I/O first, then timers, then run everything together — so a timer that expired during the select and an fd that became readable during the same select are treated as having happened "at the same time", which they effectively did.

**Step 5 — drain a *snapshot* of the ready queue.** Take `n = len(ready)` first, then run exactly `n` callbacks. **Not `while ready: pop()`.** The difference is the whole ballgame: a callback that schedules another callback (`call_soon` from inside a callback) appends *behind* the snapshot boundary, so it runs on the **next** iteration. With the live-queue version, a callback that reschedules itself never lets the loop reach `select()` again — the socket buffers fill, the accept backlog overflows, and your server hangs with the CPU pinned at 100% while looking, in every profiler, perfectly busy.

Then repeat. That is the entire mechanism.

### Timers and the heap

The loop needs one question answered on every single iteration: *what is the nearest deadline?* Everything else about timers is secondary. That question is `peek-min`, and the data structure whose entire purpose is answering `peek-min` in O(1) with O(log n) insert and delete is a **binary min-heap** — `heapq` in Python.

A sorted list would give O(1) peek but O(n) insert, and inserts are frequent (every timeout you arm on every request). An unsorted list gives O(1) insert but O(n) peek, paid on every iteration forever. The heap is the right trade, and it is why every event loop in existence has one.

Two details that are not obvious:

**Cancellation is lazy.** `heapq` has no "remove this element" operation. So cancelling a timer sets a flag on the handle and leaves it in the heap; the loop skips flagged handles when it pops them. That is correct but leaks memory if you arm and cancel many timers without them expiring — the classic case is a per-request timeout on a fast endpoint, where 99.9% of the timers are cancelled. asyncio handles this by counting cancelled timers and rebuilding the heap once they exceed half of it. If your loop's memory grows under load while connection count stays flat, this is the first place to look.

**The clock must be monotonic.** Use `time.monotonic()`, never `time.time()`. `time.time()` is the **wall clock** — the human calendar time, which the Network Time Protocol (NTP) daemon can step forwards or backwards at any moment, which changes on a Daylight Saving Time (DST) transition in some configurations, and which an operator can set by hand. `time.monotonic()` only ever counts forward from an arbitrary origin, at a steady rate, and cannot be adjusted. If you compute deadlines from the wall clock, then an NTP step backwards of one hour makes every pending timer hang for an hour, and a step forwards fires all of them at once in a thundering herd. This is not hypothetical — it is the leap-second and DST outage that hits somebody every couple of years. **Wall clock for timestamps you show humans; monotonic clock for every duration and deadline you compute.**

### The cardinal rule: never block the loop

There is exactly **one thread**. Everything the loop does — accepting, parsing, your business logic, writing responses — happens in the single-file line of the ready-queue drain. Therefore:

> Any callback that blocks stops *everything*. Not the connection it belongs to — everything.

And the damage is invisible from where it originates. The slow request looks slow, which is expected. What is not expected is that hundreds of requests that touched none of the slow code get slow *at the same instant*, on endpoints with nothing in common, in a pattern no per-endpoint dashboard explains.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="A timeline showing five connections served smoothly by a single-threaded event loop until one handler calls time.sleep of 0.5 seconds. During that 500 millisecond window the loop thread is occupied by the one blocked handler and every other connection is frozen mid-request, resuming only when the handler returns. The measured effect was p99 latency rising from 11.36 milliseconds to 485 milliseconds for the connections that did nothing wrong.">
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">One blocking handler freezes every other connection</text>

    <g fill="none" stroke-width="1.6">
      <rect x="16" y="56" width="108" height="26" rx="6" fill="#7c5cff" fill-opacity="0.14" stroke="#7c5cff"/>
      <rect x="16" y="112" width="108" height="24" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="16" y="150" width="108" height="24" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="16" y="188" width="108" height="24" rx="6" fill="#d64545" fill-opacity="0.14" stroke="#d64545"/>
      <rect x="16" y="226" width="108" height="24" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
      <rect x="16" y="264" width="108" height="24" rx="6" fill="#3553ff" fill-opacity="0.12" stroke="#3553ff"/>
    </g>
    <g fill="currentColor" font-size="9.5">
      <text x="30" y="73" font-weight="700" fill="#7c5cff">loop thread</text>
      <text x="34" y="129">conn A</text><text x="34" y="167">conn B</text>
      <text x="30" y="205" font-weight="700" fill="#d64545">conn C</text>
      <text x="34" y="243">conn D</text><text x="34" y="281">conn E</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-opacity="0.28" stroke-width="1.2" stroke-dasharray="4 5">
      <line x1="130" y1="69" x2="306" y2="69"/><line x1="764" y1="69" x2="856" y2="69"/>
      <line x1="130" y1="124" x2="296" y2="124"/><line x1="762" y1="124" x2="856" y2="124"/>
      <line x1="130" y1="162" x2="314" y2="162"/><line x1="762" y1="162" x2="856" y2="162"/>
      <line x1="130" y1="200" x2="306" y2="200"/><line x1="764" y1="200" x2="856" y2="200"/>
      <line x1="130" y1="238" x2="304" y2="238"/><line x1="762" y1="238" x2="856" y2="238"/>
      <line x1="130" y1="276" x2="326" y2="276"/><line x1="762" y1="276" x2="856" y2="276"/>
    </g>

    <g fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.2">
      <rect x="132" y="61" width="16" height="16" rx="3"/><rect x="154" y="61" width="16" height="16" rx="3"/>
      <rect x="176" y="61" width="16" height="16" rx="3"/><rect x="198" y="61" width="16" height="16" rx="3"/>
      <rect x="220" y="61" width="16" height="16" rx="3"/><rect x="242" y="61" width="16" height="16" rx="3"/>
      <rect x="264" y="61" width="16" height="16" rx="3"/><rect x="286" y="61" width="16" height="16" rx="3"/>
      <rect x="768" y="61" width="16" height="16" rx="3"/><rect x="790" y="61" width="16" height="16" rx="3"/>
      <rect x="812" y="61" width="16" height="16" rx="3"/><rect x="834" y="61" width="16" height="16" rx="3"/>
    </g>
    <rect x="310" y="59" width="450" height="20" rx="4" fill="#d64545" fill-opacity="0.26" stroke="#d64545" stroke-width="1.8"/>
    <text x="535" y="73" text-anchor="middle" font-size="9.5" font-weight="700" fill="#d64545">time.sleep(0.5) inside ONE handler — the thread is gone</text>

    <g fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.2">
      <rect x="140" y="117" width="26" height="14" rx="3"/><rect x="188" y="117" width="26" height="14" rx="3"/><rect x="240" y="117" width="26" height="14" rx="3"/>
      <rect x="150" y="155" width="26" height="14" rx="3"/><rect x="205" y="155" width="26" height="14" rx="3"/><rect x="262" y="155" width="26" height="14" rx="3"/>
      <rect x="146" y="231" width="26" height="14" rx="3"/><rect x="196" y="231" width="26" height="14" rx="3"/><rect x="250" y="231" width="26" height="14" rx="3"/>
      <rect x="158" y="269" width="26" height="14" rx="3"/><rect x="212" y="269" width="26" height="14" rx="3"/><rect x="268" y="269" width="26" height="14" rx="3"/>
      <rect x="766" y="117" width="26" height="14" rx="3"/><rect x="766" y="155" width="26" height="14" rx="3"/>
      <rect x="766" y="231" width="26" height="14" rx="3"/><rect x="766" y="269" width="26" height="14" rx="3"/>
    </g>
    <g fill="#e0930f" fill-opacity="0.22" stroke="#e0930f" stroke-width="1.5" stroke-dasharray="6 4">
      <rect x="300" y="117" width="458" height="14" rx="3"/><rect x="318" y="155" width="440" height="14" rx="3"/>
      <rect x="308" y="231" width="450" height="14" rx="3"/><rect x="330" y="269" width="428" height="14" rx="3"/>
    </g>
    <rect x="310" y="193" width="450" height="14" rx="3" fill="#d64545" fill-opacity="0.26" stroke="#d64545" stroke-width="1.5"/>
    <g fill="currentColor" font-size="8.5" opacity="0.9">
      <text x="529" y="128" text-anchor="middle">request sent — no reply possible — frozen</text>
      <text x="538" y="166" text-anchor="middle">frozen</text>
      <text x="535" y="204" text-anchor="middle" font-weight="700" fill="#d64545">its own slow request (it asked for it)</text>
      <text x="533" y="242" text-anchor="middle">frozen</text>
      <text x="544" y="280" text-anchor="middle">frozen</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="1.8" stroke-dasharray="5 4">
      <line x1="310" y1="48" x2="310" y2="296"/><line x1="760" y1="48" x2="760" y2="296"/>
    </g>
    <g fill="currentColor" font-size="8.5" font-weight="700">
      <text x="314" y="44" fill="#d64545">handler blocks</text><text x="756" y="44" fill="#0fa07f" text-anchor="end">loop resumes</text>
    </g>

    <g fill="none" stroke="currentColor" stroke-width="1.4"><line x1="130" y1="306" x2="856" y2="306"/>
      <path d="M130 306 L 130 312"/><path d="M220 306 L 220 312"/><path d="M310 306 L 310 312"/><path d="M400 306 L 400 312"/>
      <path d="M490 306 L 490 312"/><path d="M580 306 L 580 312"/><path d="M670 306 L 670 312"/><path d="M760 306 L 760 312"/><path d="M850 306 L 850 312"/>
    </g>
    <g fill="currentColor" font-size="8.5" opacity="0.7" text-anchor="middle">
      <text x="130" y="324">0</text><text x="220" y="324">100</text><text x="310" y="324">200</text><text x="400" y="324">300</text>
      <text x="490" y="324">400</text><text x="580" y="324">500</text><text x="670" y="324">600</text><text x="760" y="324">700</text><text x="850" y="324">800 ms</text>
    </g>

    <rect x="16" y="340" width="848" height="64" rx="9" fill="#e0930f" fill-opacity="0.10" stroke="#e0930f" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="32" y="359" font-size="10" font-weight="700" fill="#e0930f">MEASURED (Build It, section 3) — for the 23 connections that never touched the slow route:</text>
      <text x="32" y="379" font-size="10.5" font-weight="700">p99  11.36 ms -&gt; 485.00 ms  (43x)</text>
      <text x="330" y="379" font-size="10.5" font-weight="700">max  22.52 ms -&gt; 500.13 ms</text>
      <text x="592" y="379" font-size="10.5" font-weight="700">over 100 ms:  0 -&gt; 23 of 959</text>
      <text x="32" y="396" font-size="9" opacity="0.85">p50 barely moved (0.44 -&gt; 0.33 ms) — blocking damage lands entirely in the tail, which is exactly where your SLO lives.</text>
    </g>
  </g>
</svg>
```

The obvious offenders are easy to name: `time.sleep`, a synchronous database driver, `requests.get`, a blocking DNS (Domain Name System) lookup, reading a file from a slow disk, `subprocess.run`.

The subtler version is the one that actually gets you. A callback that never blocks on I/O at all but is merely **slow** does the same thing at smaller scale: parsing a 4 MB JSON (JavaScript Object Notation) payload, a tight loop over 100,000 rows, bcrypt hashing a password, a regular expression that backtracks. Each is "just CPU work", each is invisible to every "am I blocking?" linter, and each occupies the single thread for its whole duration. Ten milliseconds of CPU in a handler is a 10 ms floor added to the tail latency of every concurrent request. This is precisely why event-loop servers need a **thread or process pool** for CPU-bound work, which is Lesson 7 — and why getting the result *back* from that pool requires the cross-thread wakeup below.

### Fairness and starvation inside the loop

The snapshot in step 5 gives you one specific fairness guarantee, and it is worth being precise about what it does and does not buy.

**What it guarantees:** work scheduled *during* an iteration cannot extend that iteration. `call_soon` from inside a callback lands behind the snapshot boundary, so the loop always reaches `select()` again after a bounded amount of work, and I/O is never starved by a self-rescheduling chain of callbacks. This is why `call_soon` must never call the function inline — "inline for speed" turns a scheduling primitive into a recursive call and reintroduces unbounded stack depth along with the starvation.

**What it does not guarantee:** any kind of per-connection fairness. The loop is FIFO (first in, first out) across whatever the selector reported. A client that pipelines 500 requests into one connection gets 500 handler invocations from a single readability event, all inside one drain, while everyone else waits. Nothing in the loop pushes back. Fairness against a hot connection is an *application* concern — read a bounded number of bytes per readability event, cap requests handled per wakeup, and apply per-connection rate limits. The loop gives you a scheduling point; it does not give you a scheduler.

### Callback style and its limits

The loop's natural interface is "give me a function to run when this happens." That is genuinely all a reactor can offer, and it works fine for one step. Real requests have several. Here is a three-step flow — read the request, query a database, write the response, log it — in the only style the loop natively supports:

```python
def on_readable(fd):                                  # step 1
    loop.remove_reader(fd)
    request = sock.recv(4096)

    def on_query_done(rows):                          # step 2
        def on_written(nbytes):                       # step 3
            def on_logged():                          # step 4
                done.set_result(True)
            loop.call_soon(on_logged)
        sock.send(render(rows))
        loop.call_soon(on_written, len(body))

    db.query("SELECT …", callback=on_query_done)      # 50 ms later, from the loop
```

It works. It is also three named problems, and they are not aesthetic:

1. **The logic is inverted.** The steps execute top-to-bottom but are *written* inside-out, each one nested in the completion of the previous. Add error handling, a retry and a timeout to each step and the indentation exceeds the screen. The Build It measures this: five function definitions, 20 columns of indentation, five levels deep, for one linear request.
2. **Error handling has no natural place.** This is the deep one. Each callback is invoked *directly by the loop* — there is no caller between it and the dispatcher. The Build It measures that too: all four steps run at a Python stack depth of exactly **8 frames**. A `raise` in step 3 does not propagate to step 1, because step 1 already returned 50 ms ago and its stack frame is gone. It propagates to the *loop*, which knows nothing about your request, cannot roll back your transaction, cannot send a 500, and can only log it and carry on. The request is abandoned mid-flight with its socket still open.
3. **You cannot write a loop.** "Read rows until the cursor is exhausted" has no expression as a `for` or `while`, because each read is a separate callback with no way to suspend and resume in place. You hand-roll a state machine and a recursion, for what is a three-line loop in synchronous code.

None of this is fixable by writing tidier callbacks. It is fixed by adding the one thing the reactor lacks — a way for a function to **suspend in the middle and resume later** — which is what coroutines are, and what [Lesson 5](../05-coroutines-and-async-await/) builds on top of exactly this loop.

### Waking the loop from another thread

The loop is asleep inside `select()`. A background thread finishes a job and appends a callback to the ready queue. Nothing happens — the loop is blocked in a syscall and will not look at that queue until it returns, which could be when the next timer expires, or never.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 420" width="100%" style="max-width:840px" role="img" aria-label="A sequence diagram of the self-pipe wakeup. The event loop thread is blocked inside a single select call with no timeout, consuming no CPU. A worker thread finishes its computation and calls call_soon_threadsafe, which appends a handle to a queue under a lock and then writes one byte to the write end of a socketpair. The read end is registered with the selector, so select returns immediately, the loop drains the wakeup byte, moves the queued handle into its ready queue and runs it — measured at 0.111 milliseconds from the write to the callback.">
  <defs><marker id="l04c-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker></defs>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="26" text-anchor="middle" font-size="14.5" font-weight="700" fill="currentColor">Waking a sleeping loop: the self-pipe trick</text>

    <g fill="none" stroke-width="2">
      <rect x="40" y="48" width="240" height="30" rx="8" fill="#7c5cff" fill-opacity="0.13" stroke="#7c5cff"/>
      <rect x="340" y="48" width="200" height="30" rx="8" fill="#7f7f7f" fill-opacity="0.12" stroke="currentColor" stroke-opacity="0.6"/>
      <rect x="600" y="48" width="240" height="30" rx="8" fill="#0fa07f" fill-opacity="0.13" stroke="#0fa07f"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="10.5" font-weight="700">
      <text x="160" y="68" fill="#7c5cff">EVENT LOOP THREAD</text>
      <text x="440" y="68">socketpair (self-pipe)</text>
      <text x="720" y="68" fill="#0fa07f">WORKER THREAD</text>
    </g>
    <g fill="none" stroke="currentColor" stroke-opacity="0.30" stroke-width="1.3" stroke-dasharray="4 5">
      <line x1="160" y1="82" x2="160" y2="100"/><line x1="160" y1="260" x2="160" y2="272"/><line x1="160" y1="328" x2="160" y2="332"/>
      <line x1="440" y1="82" x2="440" y2="198"/><line x1="440" y1="276" x2="440" y2="332"/>
      <line x1="720" y1="82" x2="720" y2="100"/><line x1="720" y1="198" x2="720" y2="332"/>
    </g>

    <rect x="148" y="100" width="24" height="160" rx="4" fill="#7c5cff" fill-opacity="0.30" stroke="#7c5cff" stroke-width="1.8"/>
    <g fill="currentColor" font-size="9">
      <text x="184" y="118" font-weight="700" fill="#7c5cff">asleep in select(None)</text>
      <text x="184" y="133" opacity="0.9">no timers, no ready work,</text>
      <text x="184" y="147" opacity="0.9">so the timeout is "forever"</text>
      <text x="184" y="163" font-weight="700">0% CPU · 1 syscall</text>
      <text x="184" y="177" font-weight="700">310.6 ms in ONE call</text>
    </g>

    <rect x="708" y="100" width="24" height="98" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.8"/>
    <g fill="currentColor" font-size="9" text-anchor="end">
      <text x="698" y="120" font-weight="700" fill="#0fa07f">a thread-pool job</text>
      <text x="698" y="136" opacity="0.9">sleep(0.3), then</text>
      <text x="698" y="150" opacity="0.9">sum(i*i for i in</text>
      <text x="698" y="164" opacity="0.9">range(200_000))</text>
      <text x="698" y="182" opacity="0.9">= 2666646666700000</text>
    </g>

    <g fill="none" stroke-width="2">
      <rect x="376" y="198" width="128" height="28" rx="6" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f"/>
      <rect x="376" y="248" width="128" height="28" rx="6" fill="#3553ff" fill-opacity="0.16" stroke="#3553ff"/>
      <line x1="440" y1="226" x2="440" y2="248" stroke="currentColor" stroke-opacity="0.55"/>
    </g>
    <g fill="currentColor" text-anchor="middle" font-size="9" font-weight="700">
      <text x="440" y="216" fill="#e0930f">write end</text><text x="440" y="266" fill="#3553ff">read end</text>
    </g>
    <text x="518" y="266" font-size="8.5" fill="currentColor" opacity="0.9">registered with the selector</text>

    <path d="M704 212 L 510 212" fill="none" stroke="currentColor" stroke-width="1.7" marker-end="url(#l04c-arrow)"/>
    <g fill="currentColor" text-anchor="middle" font-size="9">
      <text x="607" y="204" font-weight="700">call_soon_threadsafe(deliver, total)</text>
      <text x="607" y="228" opacity="0.9">1. append Handle under a lock</text>
      <text x="607" y="241" opacity="0.9">2. send one byte: b"\x01"</text>
    </g>

    <path d="M370 262 L 178 262" fill="none" stroke="#d64545" stroke-width="2" marker-end="url(#l04c-arrow)"/>
    <text x="274" y="254" text-anchor="middle" font-size="9" font-weight="700" fill="#d64545">fd readable — select() returns NOW</text>

    <rect x="148" y="272" width="24" height="56" rx="4" fill="#0fa07f" fill-opacity="0.30" stroke="#0fa07f" stroke-width="1.8"/>
    <g fill="currentColor" font-size="9">
      <text x="184" y="288" font-weight="700" fill="#0fa07f">the loop is awake:</text>
      <text x="184" y="303" opacity="0.9">drain the wakeup byte, move the</text>
      <text x="184" y="317" opacity="0.9">queued Handle into ready, run it</text>
    </g>

    <rect x="16" y="344" width="848" height="64" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="32" y="363" font-size="10" font-weight="700" fill="#3553ff">MEASURED (Build It, section 4):</text>
      <text x="32" y="381" font-size="10.5" font-weight="700">select() calls in the whole run: 1 · time asleep: 310.6 ms · socketpair write -&gt; callback ran: 0.111 ms</text>
      <text x="32" y="399" font-size="9" opacity="0.85">Without the read end in the selector the loop would sleep on regardless — the result would sit in the queue, correct and unseen.</text>
    </g>
  </g>
</svg>
```

The fix is the **self-pipe trick**, and it is beautiful because it needs no new mechanism at all. The loop already knows how to wake up for one thing: a file descriptor becoming readable. So give it one whose only job is to be written to. Create a pipe or a `socket.socketpair()` at startup, register the **read end** with the selector, and hand the **write end** to anyone who needs to interrupt the loop. To wake it, write a single byte. The selector returns immediately, the loop drains the byte, moves anything queued into its ready queue, and runs it.

That is exactly what `loop.call_soon_threadsafe` does, and it is the *only* loop method another thread may legally call. Everything else — `call_soon`, `call_later`, `add_reader` — mutates loop state with no locking and must only be touched from the loop's own thread. Two consequences worth internalizing:

- **The race is handled for free.** If the worker thread queues its callback in the instant *between* the loop computing `timeout=None` and entering `select()`, the loop still blocks — but the byte is already sitting in the pipe, so `select()` returns immediately. The pipe holds the wakeup for you; a condition variable checked at the wrong moment would not.
- **This is the return path for every thread pool.** Any CPU-bound work you push to an executor (Lesson 7) comes back through this door. When you `await loop.run_in_executor(...)`, the pool thread finishing your function calls `call_soon_threadsafe` to hand the result back, and that is why the answer appears on the loop thread with no locking in your code.

### Where the loop lives in real systems

The point here is recognition, not tourism. You have built the thing these are.

**nginx** runs N single-threaded worker processes, each an `epoll` loop with the same anatomy, each accepting on the same listening socket (`SO_REUSEPORT`). Its "never block" rule is enforced architecturally: nginx does almost no application work, and the parts that must touch disk go through thread pools (`aio threads`) precisely because a blocking disk read would stall a worker.

**Redis** is the purest case: one thread, one event loop (`ae`), all commands executed serially. That is why every Redis command is atomic without locks — and why `KEYS *` or a big `SORT` on a production instance is a genuine outage, not a slow query. Redis 6 added I/O threads for reading and writing sockets, but command *execution* stayed on the one loop thread, on purpose.

**Node.js / libuv** is a loop with several ordered phases (timers, pending callbacks, poll, check, close) and a default four-thread pool for the things the OS cannot do readiness-style: file I/O, DNS resolution, some crypto. `process.nextTick` and `setImmediate` are two different positions relative to the ready-queue drain you built.

**asyncio** is this loop, in Python, with more edge cases handled — which is the subject of the next section.

## Build It

You will build the loop, then run real things on it. Start with the iteration, because everything else exists to serve it. This is `_run_once`, and it is the five steps from the diagram with nothing removed:

```python
def _run_once(self) -> None:
    # (1) How long may we sleep?
    if self._ready:
        timeout = 0.0
    elif self._timers:
        timeout = max(0.0, self._timers[0][0] - self.time())
    else:
        timeout = None                       # forever: the socketpair can wake us

    events = self._selector.select(timeout)  # (2) the one blocking call

    for key, mask in events:                 # (3) I/O callbacks
        for event in (selectors.EVENT_READ, selectors.EVENT_WRITE):
            if mask & event:
                entry = key.data.get(event)
                if entry is not None:
                    self._ready.append(Handle(entry[0], entry[1], self))

    if self._threadsafe:                     # (3b) cross-thread callbacks
        with self._ts_lock:
            pending, self._threadsafe = self._threadsafe, []
        self._ready.extend(pending)

    now = self.time()                        # (4) expired timers
    while self._timers and self._timers[0][0] <= now:
        _, _, handle = heapq.heappop(self._timers)
        if not handle.cancelled:
            self._ready.append(handle)

    n = len(self._ready)                     # (5) drain a SNAPSHOT, not the live queue
    for _ in range(n):
        handle = self._ready.popleft()
        if not handle.cancelled:
            handle._run()
```

Timers are a heap of `(when, seq, handle)` tuples. The `seq` counter is not decoration — it breaks ties so two timers with an identical deadline run in scheduling order, and it stops `heapq` from ever comparing two `Handle` objects, which have no ordering:

```python
def call_at(self, when: float, fn, *args) -> Handle:
    h = Handle(fn, args, self, when=when)
    heapq.heappush(self._timers, (when, next(self._seq), h))
    return h

def call_later(self, delay: float, fn, *args) -> Handle:
    return self.call_at(self.time() + delay, fn, *args)   # self.time() is monotonic
```

The cross-thread door is four lines, and the ordering inside it matters: queue the work **first**, then write the byte. Do it the other way round and the loop can wake, find nothing, and go back to sleep before the append lands:

```python
def call_soon_threadsafe(self, fn, *args) -> Handle:
    """The ONLY loop method another thread may call."""
    h = Handle(fn, args, self)
    with self._ts_lock:
        self._threadsafe.append(h)
    try:
        self._wake_w.send(b"\x01")     # forces select() to return right now
    except (BlockingIOError, OSError):
        pass                           # pipe full == a wakeup is already pending
    return h
```

The exception handler is the whole of point 2 from *Callback style and its limits*, expressed in code. There is no caller to re-raise to, so the loop is the top of the stack and the buck stops here:

```python
def _run(self) -> None:
    try:
        self._fn(*self._args)
    except Exception as exc:
        # There is no caller to propagate to: the loop IS the stack.
        self._loop.handle_exception(exc, self._fn)
```

Finally, the server's write path, which is where non-blocking I/O bites people. `send()` is allowed to accept *part* of your buffer and return how much it took. The rule is: send what you can, and if anything is left, ask the loop to tell you when there is room — then **remove the writer as soon as you are done**, because a writable socket with nothing to write is ready on every single iteration, and the loop will spin at 100% CPU forever:

```python
if conn.outbuf:                       # PARTIAL WRITE: kernel buffer is full.
    self.partial_writes += 1          # Ask to be told when it drains.
    self.loop.add_writer(fd, self._flush, fd)
else:
    self.loop.remove_writer(fd)       # Nothing to send: stop asking, or the
                                      # loop spins at 100% CPU on writability.
```

The rest — `add_reader`/`remove_reader` and the selector mask bookkeeping, the HTTP server, the thread-based client harness, and the five demo sections — is in [`code/event_loop.py`](code/event_loop.py). Run it:

```bash
python3 event_loop.py
```

```console
== 1 · THE LOOP IS A CYCLE: READY QUEUE FIRST, THEN TIMERS ==
  clock: time.monotonic() -- 3310.652s since an arbitrary origin,
         immune to NTP steps, DST and someone running `date -s`
  firing order:
    1. soon-A
    2. soon-B
    3. soon-C (scheduled from a callback)
    4. t+50ms
    5. t+100ms
    6. t+150ms
  timer accuracy (fired - deadline):
    t+50ms     deadline   50.0 ms   fired  50.254 ms   drift +0.254 ms
    t+100ms    deadline  100.0 ms   fired 100.534 ms   drift +0.534 ms
    t+150ms    deadline  150.0 ms   fired 150.664 ms   drift +0.664 ms
  cancelled timer fired: False
  loop iterations: 7   callbacks run: 8   select() calls: 7
  time asleep in select(): 200.6 ms of 207.6 ms wall -- the loop is idle by design

== 2 · A REAL HTTP SERVER ON THE LOOP: ONE THREAD, 24 CONNECTIONS ==
  24 concurrent keep-alive clients x 40 requests, 16 KiB responses
  requests served      : 960  in 1.74 s (553 req/s, single-threaded)
  loop iterations      : 450   callbacks dispatched: 1000
  partial writes       : 0  (on loopback the kernel swallows a 16 KiB response whole)
  ...so prove the writer path separately: send 4 MiB down one socket
     first send() accepted 219,264 of 4,194,304 bytes (5.2%) -- a short write, not an error
     completed in 20 send() calls, parked on add_writer 19 times, 4,194,304 bytes received
  latency n=960        : p50   0.44 ms   p99   11.36 ms   max   22.52 ms
  longest ready-queue drain (loop lag): 9.45 ms

== 3 · THE MEASUREMENT: ONE HANDLER CALLS time.sleep(0.5) ==
  identical run, except request #21 on client 0 hits a handler that blocks 500 ms
  that one request took : 500.6 ms (it asked for it)
  longest ready-queue drain (loop lag): 500.21 ms

  latency of the OTHER 23 clients -- they did nothing wrong:
                        p50      p90       p99       max   >100ms
    no blocking       0.44ms    2.68ms    11.36ms    22.52ms        0
    500ms block       0.33ms    1.63ms   485.00ms   500.13ms       23
    p99 got 43x worse from ONE blocking call in ONE handler.
    p50 barely moved (0.44 -> 0.33 ms): the damage is entirely in the tail,
    spread across 23 innocent requests out of 959.

== 4 · WAKING A SLEEPING LOOP FROM ANOTHER THREAD ==
  worker thread slept 300 ms, then computed sum(i*i for i in range(200000))
  result delivered into the loop: 2666646666700000
  loop was asleep in a SINGLE select() call for 310.6 ms of 310.7 ms wall
  select() calls in the whole run: 1 (no polling, no spinning, 0% CPU while waiting)
  wakeup latency, socketpair write -> callback ran: 0.111 ms
  without the socketpair the loop would have slept until the 5 s safety timer

== 5 · CALLBACK HELL, MEASURED ==
  step 1  read request  : 'GET /order/42'
  step 2  query returned: 3 rows (50 ms later)
  step 3  response sent : 13 bytes
  step 4  access log written
  source shape   : 5 `def`s, max indentation 20 columns (5 levels deep) -- for ONE linear request
  python stack depth when each step ran:
    read   8 frames
    query  8 frames
    write  8 frames
    log    8 frames
  all four are identical -> every step ran directly off the loop, with NO
    caller between it and _run_once. There is no stack to raise through.
  error path: caller's try/except around run_until_complete caught: None
              the loop's exception handler caught : [('ValueError', 'row 42 is corrupt', 'step_two')]
              -> the request is abandoned mid-flight; the socket stays open;
                 no `except` anywhere in the request's own logic can see it.
  Lesson 5 replaces all of this with `rows = await db.query(...)`: one stack,
    one try/except, and a real `for` loop over I/O.

(total runtime 4.6s)
```

**Read the numbers — three of these sections are arguments, not demos.**

**Section 1** establishes that the mechanism is real and cheap. The firing order is the design, visible: both `call_soon` callbacks run before any timer, and `soon-C` — scheduled *from inside* another callback — runs on the following iteration rather than being spliced into the current drain. That is the snapshot rule working. The timers then fire in deadline order with **+0.254 ms, +0.534 ms and +0.664 ms** of drift. Note the sign: drift is always positive. A timer fires *no earlier* than its deadline and some scheduler noise later, which is the only guarantee a timer can honestly make — the numbers move between runs (a busy machine has produced +5 ms here), but they never go negative. The cancelled timer never fired. And the whole 200 ms of wall time cost **7 iterations, 8 callbacks and 7 `select()` calls**, with **200.6 ms of 207.6 ms spent asleep**. The loop is not a spin loop; it is a thing that waits efficiently and does small amounts of work.

**Section 2** is the same server from Lesson 3, rebuilt as an application on top of a mechanism. One thread served **960 requests across 24 concurrent keep-alive connections in 1.74 s — 553 req/s** — at **p50 0.44 ms and p99 11.36 ms**, in **450 iterations** dispatching **1,000 callbacks**. Two details worth pausing on. First, the honest zero: on loopback the kernel accepted every 16 KiB response in a single `send()`, so the partial-write path never triggered — which is exactly the trap, because that path is *mandatory* in production and a loopback benchmark will never tell you it is broken. Forcing the issue with a 4 MiB write shows what really happens: the first `send()` accepted **219,264 of 4,194,304 bytes — 5.2%** — and the transfer needed **20 `send()` calls, parking on `add_writer` 19 times**. Code that assumes `send()` sends everything is code that silently truncates responses the day a client is slower than your test. Second, `longest ready-queue drain: 9.45 ms` is **loop lag**, measured — the longest the loop went without reaching `select()`. Remember that number.

**Section 3 is the point of the lesson.** Identical run, identical load, one difference: request #21 on client 0 hits a handler that calls `time.sleep(0.5)`. That request takes 500.6 ms, which is fair. The other 23 clients did not ask for anything:

| | p50 | p90 | p99 | max | over 100 ms |
|---|---|---|---|---|---|
| no blocking | 0.44 ms | 2.68 ms | **11.36 ms** | 22.52 ms | 0 |
| 500 ms block | 0.33 ms | 1.63 ms | **485.00 ms** | 500.13 ms | 23 of 959 |

**p99 went 43x worse. The max went from 22.52 ms to 500.13 ms.** Twenty-three requests crossed 100 ms where previously not one did, and every one of them belonged to a connection that never touched the slow route. Now look at what *didn't* move: **p50 went from 0.44 ms to 0.33 ms** — it got marginally faster, which is noise. p90 didn't move either. This is the single most important shape in the table, because it is what makes the bug so hard to find: the blocking damage is entirely in the tail. Your average latency graph is flat. Your p50 dashboard is green. Your throughput is unchanged, because the loop caught up afterwards. The only signals that show it are p99, max, and loop lag — where `longest ready-queue drain` went from **9.45 ms to 500.21 ms**, naming the culprit precisely: one drain of the ready queue took half a second. That is why loop lag belongs on a dashboard next to request rate, and why the runbook in `outputs/` starts with it.

Scale it up mentally. At 553 req/s, half a second of blocking is ~275 requests delayed by up to 500 ms. One blocking call, in one handler, on one endpoint, and your entire service breaches a 200 ms p99 SLO for half a second. Do it a few times a minute — say, a single synchronous DNS lookup on a cache miss — and your p99 is permanently broken with no slow endpoint anywhere in your traces.

**Section 4** proves the loop can be woken on demand rather than polled. The worker thread slept 300 ms, computed a sum, and called `call_soon_threadsafe`. The loop made **exactly one `select()` call for the whole run and spent 310.6 ms of 310.7 ms wall time inside it** — no polling, no timer ticks, no CPU. The result then crossed the thread boundary and ran on the loop **0.111 ms** after the byte was written. Both numbers matter: the 310.6 ms is what "sleep forever safely" buys (a loop polling at 50 ms would have burned six wakeups and still added latency), and the 0.111 ms is why a thread pool integrates with an event loop at all. Without the socketpair, this loop would have slept until its 5-second safety timer with the answer sitting in a queue, correct and unread.

**Section 5** makes callback style concrete rather than complaining about it. The flow works — four steps, in order, across a real socket and a real timer. It also takes **5 function definitions and 5 levels of indentation** to express one linear request. Then the measurement that actually explains why callbacks are a dead end: **all four steps ran at a Python stack depth of exactly 8 frames.** The nesting is *textual only*. There is no caller-callee relationship between step 1 and step 3 — each is invoked directly by `_run_once`. So when the error path runs, the caller's `try/except` around `run_until_complete` catches **`None`**, and the loop's own handler catches `('ValueError', 'row 42 is corrupt', 'step_two')`. Your request logic cannot see its own exception. There is no stack for it to travel up, no `finally` that fires, no transaction that rolls back, and the connection is left open with the client waiting. That is not a style problem. That is a correctness problem, and it is what Lesson 5 exists to fix.

## Use It

Everything you just wrote exists in the standard library as `asyncio`'s `BaseEventLoop`, method for method:

| yours | asyncio | notes |
|---|---|---|
| `loop.call_soon(fn, *args)` | `loop.call_soon(fn, *args)` | returns a cancellable `Handle`; runs next iteration |
| `loop.call_later(d, fn)` | `loop.call_later(d, fn)` | `TimerHandle`, on the same kind of heap |
| `loop.call_at(when, fn)` | `loop.call_at(when, fn)` | `when` is on `loop.time()`'s scale, not `time.time()`'s |
| `loop.time()` | `loop.time()` | `time.monotonic()`, for the reasons above |
| `loop.add_reader(fd, cb)` | `loop.add_reader(fd, cb)` | same selector, same mask bookkeeping |
| `loop.call_soon_threadsafe` | `loop.call_soon_threadsafe` | same self-pipe, same "only legal cross-thread call" rule |
| `loop.run_forever()` / `stop()` | `loop.run_forever()` / `stop()` | identical semantics, including "stop takes effect after the current iteration" |
| your `Completion` | `asyncio.Future` | the same one-shot result slot, with cancellation and exceptions |

The low-level API is still there, and occasionally the right tool:

```python
import asyncio

async def main():
    loop = asyncio.get_running_loop()   # never asyncio.get_event_loop() in new code

    fut = loop.create_future()
    r, w = socket.socketpair()
    r.setblocking(False)

    def on_readable():                  # a raw reactor callback, inside asyncio
        loop.remove_reader(r.fileno())
        fut.set_result(r.recv(100))

    loop.add_reader(r.fileno(), on_readable)
    loop.call_later(0.05, w.send, b"hello from a timer")
    print(await fut, "at", loop.time())  # loop.time() is monotonic, like yours

asyncio.run(main())
```

Two things to know about the loop under you:

- **uvloop** replaces asyncio's loop with one built on **libuv** — the same C library under Node.js. It is a drop-in (`asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())`, or `uvicorn --loop uvloop`), it implements the identical interface, and it is meaningfully faster because the hot path is C rather than Python. Nothing you learned changes; the anatomy is the same.
- **Debug mode is the automated version of section 3.** Run with `PYTHONASYNCIODEBUG=1`, or `loop.set_debug(True)`, and asyncio **logs every callback that took longer than `loop.slow_callback_duration`** (0.1 s by default; set it to 0.05 or lower). It also warns about coroutines that were never awaited and non-threadsafe calls from the wrong thread. It costs real performance, so it is not a production setting — but it is the single best thing to turn on in staging and in your test suite, because it finds a blocking call at the moment somebody writes it instead of during an incident six months later.

Production rules that survive contact with reality:

- **Every deadline and duration comes from the monotonic clock** (`loop.time()`, `time.monotonic()`). Wall-clock time is for timestamps you show humans and nothing else. An NTP step must never be able to make a timer fire an hour early or hang for an hour.
- **Never block the loop, and treat "slow" as blocking.** No synchronous drivers, no `requests`, no blocking DNS, no `time.sleep`. Push CPU-bound work — big JSON parses, hashing, compression, image work — to an executor (Lesson 7) and let `call_soon_threadsafe` bring the result home. If it takes more than a few milliseconds and it isn't `await`ing, it belongs off the loop.
- **Instrument loop lag and alert on it.** Schedule a callback every 100 ms and record `actual_delay - expected_delay` as a histogram; that is the `longest ready-queue drain` number from section 3, in production. It is a leading indicator that fires before user-visible latency does, and it is the only metric that points at the loop rather than at whichever unlucky endpoint got caught behind the stall. Wire it up with the histogram you built in [Metrics from Scratch](../../09-logging-monitoring-and-observability/05-metrics-from-scratch/) and see `outputs/runbook-event-loop-lag.md`.
- **`call_soon_threadsafe` is the only thread-safe method on the loop.** Everything else — `call_soon`, `call_later`, `add_reader`, future resolution — mutates unsynchronized state and must run on the loop's thread. This is not a style guideline; violating it corrupts a heap or a deque and produces a crash days later with an incomprehensible traceback.
- **Never leave a writer registered with nothing to write.** A writable socket is ready every iteration; a stale `add_writer` is an instant 100% CPU spin that looks, in `top`, exactly like legitimate load.

## Think about it

1. Your loop's `longest ready-queue drain` metric shows a clean 200 ms spike every 30 seconds, but p99 request latency is unchanged and no endpoint is slow. What classes of cause fit that shape, and how would you distinguish them without a profiler?
2. Step 5 runs a snapshot of the ready queue. Suppose you instead ran the live queue until it drained. Construct the smallest program that turns your server into a hang, and explain what the CPU and the accept backlog look like while it happens.
3. You need per-connection fairness: no single client may consume more than its share of the loop, even if it pipelines 10,000 requests into one socket. The loop gives you no help. Where in the stack does this belong, what do you measure to know it's working, and what does the fix cost the well-behaved clients?
4. The cross-thread queue is drained *after* `select()` returns and *before* timers are collected. What would change if it were drained at the very end, after the ready-queue snapshot instead? Consider both latency and the "callback that schedules another callback" case.
5. Section 5 showed all four callbacks running at the same stack depth. Given that, describe precisely what a request-scoped `try/finally` — releasing a database connection, say — would and would not do in pure callback style, and what mechanism a runtime needs before it can work at all.

## Key takeaways

- An event loop is the **reactor pattern**: event sources (file descriptors, timers, cross-thread wakeups), a demultiplexer (`epoll`/`kqueue`/`select`), a dispatcher, and your handlers. It separates *mechanism* from *application*, which is what Lesson 3's server was missing when it had nowhere to put "close this connection in 30 seconds". Its sibling the **proactor** (IOCP, `io_uring`) is completion-based rather than readiness-based; everything else in this lesson is identical.
- **One iteration is five ordered steps**: compute the timeout (0 if work is queued, else time to the nearest deadline, else forever), `select()`, collect I/O callbacks, collect expired timers, then drain a **snapshot** of the ready queue. The snapshot is not an optimization — running the live queue lets a self-rescheduling callback prevent the loop from ever reaching `select()` again, hanging the server at 100% CPU. Measured: 960 requests cost **450 iterations and 1,000 callbacks**, with the loop asleep **200.6 of 207.6 ms** when idle.
- **Timers are a min-heap keyed on a monotonic deadline.** `peek` is O(1) and *is* the loop's sleep budget; cancellation is lazy, so heavy arm-and-cancel workloads need compaction. Measured drift was **+0.254 to +0.664 ms** and always positive — a timer fires no earlier than its deadline. Use `time.monotonic()`, never `time.time()`: an NTP step or DST change must not fire your timers an hour early or hang them for an hour.
- **Never block the loop, and "slow" counts as blocking.** One handler calling `time.sleep(0.5)` moved 23 uninvolved connections' **p99 from 11.36 ms to 485.00 ms (43x)** and max from 22.52 ms to 500.13 ms — while **p50 went 0.44 → 0.33 ms** and throughput held. The damage is entirely in the tail, which is why loop lag (`longest ready-queue drain`: **9.45 ms → 500.21 ms**) is the metric that names the culprit when no endpoint looks slow.
- **The self-pipe is how anything outside the loop gets in.** Register the read end of a `socketpair` with the selector; `call_soon_threadsafe` queues the work, then writes one byte. Measured: the loop slept **310.6 ms in a single `select()` call** and ran the delivered callback **0.111 ms** after the write. This is the only thread-safe loop method, and the return path for every thread-pool result (Lesson 7).
- **Callbacks are the loop's native API and its ceiling.** A three-step request took **5 `def`s and 5 levels of indentation**, and all four steps ran at a Python stack depth of **8 frames** — the nesting is textual, not on the stack. So an exception in step 3 reached the loop's handler, not the caller's `try/except`, leaving the request abandoned with its socket open. Inverted logic, no error path, and no way to write a plain loop over I/O: three problems that need suspension, not tidier callbacks.

Next: [Coroutines & Async/Await from the Ground Up](../05-coroutines-and-async-await/) — building the missing piece, a function that can suspend in the middle and resume later, and driving it with exactly the loop you just wrote.
