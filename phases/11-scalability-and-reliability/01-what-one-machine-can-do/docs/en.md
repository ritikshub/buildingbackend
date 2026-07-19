# What One Machine Can Actually Do

> Before you distribute anything, you owe yourself one number: the honest ceiling of a single box, and how far below it you are. This lesson measures that ceiling on the machine it runs on — and then measures the gap. The same workload, byte-identical output, no new dependency and no new algorithm, ran **10.5x faster** after four ordinary habits were removed: **27 machines became 3**. Most "we need to scale out" moments are a constant factor wearing a purchase order.

**Type:** Build
**Languages:** Python
**Prerequisites:** [Why Concurrency? Latency, Throughput & Little's Law](../../08-concurrency-and-performance/01-why-concurrency/), [RAM & the Memory Hierarchy](../../00-foundations/06-ram-and-memory-hierarchy/)
**Time:** ~60 minutes

## The Problem

A team serves 12,000 requests per second. They run forty 8-vCPU instances behind a load balancer, and the bill for those instances is **$19,000 a month** — about $475 per instance, before the load balancer, before the cross-zone data transfer, before the two engineers whose week is now partly about keeping forty things identical.

Traffic grew 30% last quarter. The plan for next quarter is fifty-two instances.

Then somebody profiles a single box. Not the fleet — one box, under its real production traffic, for four minutes. Here is what comes back.

**Each instance is serving about 300 req/s.** That is 12,000 divided by 40, and it is the only number anyone had. **Each instance's measured capacity is about 380 req/s.** So the fleet is running at 79% of capacity, which is why nobody is panicking and also why the p99 has been creeping up for six weeks — 79% is almost exactly the knee that [Backpressure, Queueing & Load Shedding](../../08-concurrency-and-performance/11-backpressure-and-load-shedding/) measured for a service with variable response times.

So far this is a normal capacity story. Here is the part that is not.

**The box is not busy.** CPU sits at 34%. The disk is idle. The network interface is moving 40 Mbit/s on a 10 Gbit link — 0.4% of the wire. Memory is 22% used and the page cache is warm. Every dashboard says this machine is loafing, and it is serving 300 requests a second, and it falls over at 380.

Something is the ceiling. Nothing on the dashboard is the ceiling.

The engineer keeps going and finds three things, none of which are exotic. Each request calls `fsync()` once, because the audit log is written synchronously. Each request deep-copies its input record "to be safe". And a membership check against a 100-element allow-list rebuilds that list on every record it touches. None of these is a bug. Every one of them would pass code review. Together they are the entire reason the number is 380 instead of several thousand.

That is the shape of this problem, and it is remarkably common: **the fleet exists because of a constant factor nobody measured.** Once the fleet exists, it is very hard to argue away. It has monitoring, runbooks, a deploy pipeline and a headcount. It is now the architecture.

And the fleet was not free. It never is. Distribution buys you capacity by spending three things you had for nothing on one machine:

- **Correctness.** One machine has one clock, one memory, one view of the truth. Two machines have two of everything and a network in between, which is how "the write succeeded" becomes a question with more than one answer.
- **Latency.** A function call costs nanoseconds. The same call across a network costs half a millisecond in the same building and up to 150 ms across the planet — a factor of a million, and the speed of light does not negotiate.
- **Cash and attention.** Not just the instances. The load balancer, the cross-zone bytes, the service discovery, the extra observability, and the permanent tax on every engineer who from now on must think about partial failure.

That bill is what the next thirteen lessons itemise. This lesson makes sure you only pay it when you have to. The question to answer first is not "how do we scale?" It is: **what is the honest ceiling of one machine, and how far below it are we standing?**

## The Concept

### The four walls

A single machine can run out of exactly four things. Every scaling problem you will ever have is one of these four saturating before the others:

1. **CPU** — cycles to execute instructions. Includes the ones your runtime spends on your behalf: garbage collection, reference counting, JSON parsing, TLS handshakes.
2. **Memory** — and this is really three separate walls that people collapse into one. **Capacity** (how many bytes fit), **bandwidth** (how many bytes per second you can move between RAM and the CPU), and **latency** (how long one uncached read takes). You can be nowhere near capacity and completely out of bandwidth.
3. **I/O** — the disk, and the syscall boundary itself. Every `read`, `write`, `send` and `recv` is a transition into the kernel with a real, measurable price. Durability — `fsync()` — is a wall of its own, orders of magnitude slower than everything around it.
4. **The network interface** — the NIC (Network Interface Card). A 10 GbE (10 gigabit Ethernet, IEEE 802.3) link moves 1.25 gigabytes per second, and that is a hard ceiling shared by every request on the box.

The critical property, and the one that makes capacity planning counter-intuitive, is that **these four saturate at wildly different points, and the gaps between them are enormous.** Here are the four walls of the container this lesson's code ran in, priced per request against a modelled request that does 8,000 interpreter operations, touches 96 KiB of memory, makes 12 syscalls, writes 14 KiB to the wire, and calls `fsync()` once:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 560" width="100%" style="max-width:840px" role="img" aria-label="Four measured resource ceilings plotted as utilization against offered load. The durable write wall saturates at 1,985 requests per second while the CPU, network card, memory bandwidth and syscall walls are still almost idle; after group commit the binding wall moves to the CPU at 25,288 requests per second.">
  <defs>
    <marker id="p11-01-a1" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four walls, four wildly different ceilings — only one of them is yours</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M90 380 L 838 380"/><path d="M90 380 L 90 96"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.1" opacity="0.4">
      <path d="M232 380 L 232 385"/><path d="M374 380 L 374 385"/><path d="M516 380 L 516 385"/><path d="M658 380 L 658 385"/><path d="M800 380 L 800 385"/>
      <path d="M85 380 L 90 380"/><path d="M85 312.5 L 90 312.5"/><path d="M85 245 L 90 245"/><path d="M85 177.5 L 90 177.5"/><path d="M85 110 L 90 110"/>
    </g>
    <path d="M90 110 L 838 110" fill="none" stroke="currentColor" stroke-width="1.1" stroke-dasharray="4 5" opacity="0.45"/>

    <path d="M146.5 380 L 146.5 96" fill="none" stroke="#d64545" stroke-width="1.5" stroke-dasharray="5 5" opacity="0.85"/>
    <path d="M809.7 380 L 809.7 96" fill="none" stroke="#e0930f" stroke-width="1.5" stroke-dasharray="5 5" opacity="0.75"/>

    <path d="M90 380 L 146.5 110 L 838 110" fill="none" stroke="#d64545" stroke-width="2.8" stroke-linejoin="round"/>
    <path d="M90 380 L 809.7 110 L 838 110" fill="none" stroke="#e0930f" stroke-width="2.6" stroke-linejoin="round"/>
    <path d="M90 380 L 838 299.5" fill="none" stroke="#7c5cff" stroke-width="2.4"/>
    <path d="M90 380 L 838 358.1" fill="none" stroke="#0fa07f" stroke-width="2.4"/>
    <path d="M90 380 L 838 377.1" fill="none" stroke="#7f7f7f" stroke-width="2.4"/>

    <circle cx="146.5" cy="110" r="5.5" fill="#d64545" stroke="none"/>
    <circle cx="809.7" cy="110" r="5.5" fill="#e0930f" stroke="none"/>

    <g fill="currentColor">
      <text x="90" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">0</text><text x="232" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">5k</text><text x="374" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">10k</text><text x="516" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">15k</text><text x="658" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">20k</text><text x="800" y="399" font-size="9.5" text-anchor="middle" opacity="0.7">25k</text><text x="464" y="418" font-size="10.5" text-anchor="middle" opacity="0.85">offered load, requests per second</text>
      <text x="78" y="384" font-size="9.5" text-anchor="end" opacity="0.7">0%</text><text x="78" y="316" font-size="9.5" text-anchor="end" opacity="0.7">25%</text><text x="78" y="249" font-size="9.5" text-anchor="end" opacity="0.7">50%</text><text x="78" y="181" font-size="9.5" text-anchor="end" opacity="0.7">75%</text><text x="78" y="114" font-size="9.5" text-anchor="end" opacity="0.7">100%</text><text x="26" y="245" font-size="10.5" opacity="0.85" transform="rotate(-90 26 245)" text-anchor="middle">how saturated that wall is</text>
    </g>

    <g fill="currentColor">
      <text x="160" y="86" font-size="10.5" font-weight="700" fill="#d64545">1,985 req/s</text><text x="160" y="100" font-size="9" fill="#d64545">THE WALL YOU ACTUALLY HAVE</text>
      <text x="806" y="86" font-size="10.5" font-weight="700" fill="#e0930f" text-anchor="end">25,288 req/s</text><text x="806" y="100" font-size="9" fill="#e0930f" text-anchor="end">the wall after group commit</text>
    </g>

    <path d="M28 434 L 852 434" fill="none" stroke="currentColor" stroke-width="1" opacity="0.35"/>
    <g stroke-width="3" fill="none">
      <path d="M36 452 L 66 452" stroke="#d64545"/>
      <path d="M36 480 L 66 480" stroke="#e0930f"/>
      <path d="M36 508 L 66 508" stroke="#7c5cff"/>
      <path d="M460 452 L 490 452" stroke="#0fa07f"/>
      <path d="M460 480 L 490 480" stroke="#7f7f7f"/>
    </g>
    <g fill="currentColor">
      <text x="76" y="449" font-size="10.5" font-weight="700" fill="#d64545">I/O durable — 1 fsync per request</text><text x="76" y="463" font-size="9.5" opacity="0.85">503.87 us -&gt; 1,985 req/s. One disk queue, not one per core.</text>
      <text x="76" y="477" font-size="10.5" font-weight="700" fill="#e0930f">CPU — 8,000 interpreter ops per request</text><text x="76" y="491" font-size="9.5" opacity="0.85">49.43 ns/op x 10 cores -&gt; 25,288 req/s. Scales with workers.</text>
      <text x="76" y="505" font-size="10.5" font-weight="700" fill="#7c5cff">NIC — 14 KiB on the wire per request</text><text x="76" y="519" font-size="9.5" opacity="0.85">10 GbE line rate -&gt; 87,193 req/s. One link: 29% used at 26k.</text>
      <text x="500" y="449" font-size="10.5" font-weight="700" fill="#0fa07f">MEMORY bandwidth — 96 KiB per request</text><text x="500" y="463" font-size="9.5" opacity="0.85">31.56 GB/s measured -&gt; 321,085 req/s. 8% used.</text>
      <text x="500" y="477" font-size="10.5" font-weight="700" fill="#7f7f7f">I/O syscall — 12 syscalls per request</text><text x="500" y="491" font-size="9.5" opacity="0.85">342 ns each -&gt; 2,435,698 req/s. 1% used.</text>
    </g>

    <text x="440" y="542" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Your ceiling is the SMALLEST of the four, not the average. Here it sat 12.7x below the next wall,</text><text x="440" y="556" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">and moving it was a batching change, not a purchase order.</text>
  </g>
</svg>
```

Read the red line. The durable-write wall saturates at **1,985 req/s** while the CPU wall is 7% used, the NIC is 2% used, memory bandwidth is under 1% and the syscall wall is a rounding error. Your ceiling is **the smallest of the four, not the average of them** — and here the smallest sat **12.7x** below the next one up.

This is the first discipline of the phase: **name your wall.** "We need to scale" is not an engineering statement. "We are at 94% of memory bandwidth on a workload that copies 96 KiB per request" is. If you cannot name which of the four is saturating and quote its number, you have not measured, and every architectural decision you make next is a guess with a price tag.

Note also which walls multiply when you buy more cores and which do not. CPU does — if, and only if, you actually run one worker process per core, which a single CPython process does not do (see [Processes, Threads & the GIL](../../08-concurrency-and-performance/02-processes-threads-and-the-gil/)). Syscalls mostly do. **Memory bandwidth does not** — it is one bus shared by every core. **The disk does not** — it is one device with one queue. **The NIC does not** — it is one link. Half the walls on a machine are per-box, not per-core, which is exactly why a 64-core box does not serve 32x what a 2-core box serves.

### The numbers you should have memorised

You cannot do capacity arithmetic without a rough price list, and the prices span nine orders of magnitude. Jeff Dean popularised this list in *Software Engineering Advice from Building Large-Scale Distributed Systems* (Stanford CS295, 2007); the version below has this lesson's own measurements in it, taken on the container the code ran in.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="A logarithmic latency ladder from one nanosecond to one second, spanning nine decades, with measured points for an interpreter operation at 49 nanoseconds, a random RAM read at 190 nanoseconds, a syscall at 329 nanoseconds, a buffered write at 1.46 microseconds and an fsync at 504 microseconds, alongside published figures for L1 cache, NVMe reads, same-availability-zone round trips and cross-region round trips.">
  <defs>
    <marker id="p11-01-a2" markerWidth="9" markerHeight="9" refX="5" refY="3" orient="auto"><path d="M0,0 L6.5,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">The latency ladder — nine decades, drawn to scale</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <text x="440" y="46" text-anchor="middle" font-size="10" fill="currentColor" opacity="0.8">each tick is 10x the one before it — half this chart is invisible on a linear axis</text>

    <path d="M70 262 L 838 262" fill="none" stroke="currentColor" stroke-width="2"/>
    <g fill="none" stroke="currentColor" stroke-width="1.3" opacity="0.55">
      <path d="M70 254 L 70 270"/><path d="M154.4 254 L 154.4 270"/><path d="M238.9 254 L 238.9 270"/><path d="M323.3 254 L 323.3 270"/><path d="M407.8 254 L 407.8 270"/><path d="M492.2 254 L 492.2 270"/><path d="M576.7 254 L 576.7 270"/><path d="M661.1 254 L 661.1 270"/><path d="M745.6 254 L 745.6 270"/><path d="M830 254 L 830 270"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="middle" opacity="0.75">
      <text x="70" y="286">1 ns</text><text x="154.4" y="286">10 ns</text><text x="238.9" y="286">100 ns</text><text x="323.3" y="286">1 us</text><text x="407.8" y="286">10 us</text><text x="492.2" y="286">100 us</text><text x="576.7" y="286">1 ms</text><text x="661.1" y="286">10 ms</text><text x="745.6" y="286">100 ms</text><text x="830" y="286">1 s</text>
    </g>

    <rect x="466.8" y="256" width="25.4" height="12" fill="#7f7f7f" fill-opacity="0.30" stroke="none"/>
    <rect x="732.4" y="256" width="28" height="12" fill="#d64545" fill-opacity="0.30" stroke="none"/>

    <g stroke-width="1.3" fill="none">
      <path d="M70 254 L 70 196" stroke="#0fa07f"/>
      <path d="M213.1 254 L 213.1 152" stroke="#3553ff"/>
      <path d="M262.3 270 L 262.3 320" stroke="#3553ff"/>
      <path d="M282.5 254 L 282.5 108" stroke="#3553ff"/>
      <path d="M337.2 270 L 337.2 372" stroke="#3553ff"/>
      <path d="M479.5 254 L 479.5 196" stroke="#7f7f7f"/>
      <path d="M551.5 270 L 551.5 320" stroke="#3553ff"/>
      <path d="M551.5 254 L 551.5 152" stroke="#7c5cff"/>
      <path d="M746.4 270 L 746.4 372" stroke="#d64545"/>
    </g>
    <g stroke="none">
      <circle cx="70" cy="262" r="4.5" fill="#0fa07f"/><circle cx="213.1" cy="262" r="4.5" fill="#3553ff"/><circle cx="262.3" cy="262" r="4.5" fill="#3553ff"/><circle cx="282.5" cy="262" r="4.5" fill="#3553ff"/><circle cx="337.2" cy="262" r="4.5" fill="#3553ff"/><circle cx="551.5" cy="262" r="4.5" fill="#3553ff"/>
    </g>

    <g fill="currentColor">
      <text x="70" y="192" font-size="10" font-weight="700" fill="#0fa07f">L1 hit ~1 ns</text><text x="70" y="180" font-size="8.5" opacity="0.8">Phase 0 L06</text>

      <text x="213.1" y="148" font-size="10" font-weight="700" fill="#3553ff" text-anchor="middle">49.43 ns</text><text x="213.1" y="136" font-size="8.5" opacity="0.85" text-anchor="middle">one interpreter op</text>
      <text x="213.1" y="124" font-size="8.5" opacity="0.7" text-anchor="middle">MEASURED</text>

      <text x="262.3" y="334" font-size="10" font-weight="700" fill="#3553ff" text-anchor="middle">189.6 ns</text><text x="262.3" y="346" font-size="8.5" opacity="0.85" text-anchor="middle">random RAM read</text>
      <text x="262.3" y="358" font-size="8.5" opacity="0.7" text-anchor="middle">MEASURED · 4.8x sequential</text>

      <text x="282.5" y="104" font-size="10" font-weight="700" fill="#3553ff" text-anchor="middle">329 ns</text><text x="282.5" y="92" font-size="8.5" opacity="0.85" text-anchor="middle">one syscall</text>
      <text x="282.5" y="80" font-size="8.5" opacity="0.7" text-anchor="middle">MEASURED · 12 of these per request</text>

      <text x="337.2" y="386" font-size="10" font-weight="700" fill="#3553ff" text-anchor="middle">1.46 us</text><text x="337.2" y="398" font-size="8.5" opacity="0.85" text-anchor="middle">buffered 4 KiB write</text>
      <text x="337.2" y="410" font-size="8.5" opacity="0.7" text-anchor="middle">MEASURED · no durability</text>

      <text x="470" y="192" font-size="10" font-weight="700" fill="#7f7f7f" text-anchor="end">NVMe read 50-100 us</text><text x="470" y="180" font-size="8.5" opacity="0.8" text-anchor="end">published spec</text>

      <text x="551.5" y="334" font-size="10" font-weight="700" fill="#3553ff" text-anchor="middle">503.9 us</text><text x="551.5" y="346" font-size="8.5" opacity="0.85" text-anchor="middle">write + fsync</text>
      <text x="551.5" y="358" font-size="8.5" opacity="0.7" text-anchor="middle">MEASURED · 346x the buffered write</text>

      <text x="551.5" y="148" font-size="10" font-weight="700" fill="#7c5cff" text-anchor="middle">same-AZ RTT ~0.5 ms</text><text x="551.5" y="136" font-size="8.5" opacity="0.85" text-anchor="middle">a network hop costs what an fsync costs</text>

      <text x="746.4" y="386" font-size="10" font-weight="700" fill="#d64545" text-anchor="middle">cross-region RTT 70-150 ms</text><text x="746.4" y="398" font-size="8.5" opacity="0.85" text-anchor="middle">the speed of light, non-negotiable</text>
      <text x="746.4" y="410" font-size="8.5" opacity="0.7" text-anchor="middle">100 ms = 2.0 million interpreter ops</text>
    </g>

    <g fill="none" stroke="#d64545" stroke-width="1.4" opacity="0.75">
      <path d="M70 432 L 760.4 432"/><path d="M70 426 L 70 438"/><path d="M760.4 426 L 760.4 438"/>
    </g>
    <text x="415" y="450" font-size="9.5" text-anchor="middle" fill="#d64545" font-weight="700">150,000,000x — from the fastest thing you do to the slowest</text>

    <text x="440" y="474" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">One 100 ms cross-region round trip costs 2.0 million interpreter operations. Distribution is not free;</text><text x="440" y="490" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">it is paid for in the most expensive units on this ruler.</text>
  </g>
</svg>
```

Two things to take from the ruler.

**First, it is logarithmic, and your intuition is not.** The distance from an L1 cache hit to a cross-region round trip is a factor of **150,000,000**. No linear mental model survives that. When someone says "it's just one extra network call", the honest translation is: *this call costs what two million interpreter operations cost.* The Phase 0 lesson on the [memory hierarchy](../../00-foundations/06-ram-and-memory-hierarchy/) explains why RAM is a hundred times slower than L1 and why a cache miss is the most common invisible cost in a program; that mechanism is not re-taught here, but it is the reason the random-read point sits where it does.

**Second, the measured points are the interesting ones.** A random 8-byte read from a 192 MiB working set cost **189.55 ns** against **39.12 ns** for a sequential read of the same array by the same loop — **4.8x**, and the 150.43 ns difference is pure cache miss, with the interpreter's overhead cancelled out because both loops run identical Python. One syscall cost **342.13 ns**, of which about **329 ns** is the kernel transition once the 12.99 ns empty-loop baseline is subtracted. And `write()` + `fsync()` of 4 KiB cost **503.87 µs** — **346x** the same write without the flush.

That last number deserves a moment, because it is the single most common way an application ends up with an unnecessary fleet. Durability is not expensive because disks are slow; NVMe (Non-Volatile Memory Express) devices read in 50–100 µs. It is expensive because `fsync()` must wait for the device to confirm that the data is on stable media, and that wait cannot be overlapped with anything else in the same request. **An `fsync()` on this box cost roughly the same as a network round trip to another machine in the same availability zone.** The classical fix is not faster hardware — it is **group commit**: batch N transactions and pay for one flush (Gray & Reuter, *Transaction Processing: Concepts and Techniques*, Morgan Kaufmann 1993, ch. 12). Every serious database does this. Postgres calls it `commit_delay`; the arithmetic below shows why.

Turn the price list into capacity. That is the whole skill:

```text
one request costs      8,000 interpreter ops   at 49.43 ns  =  395.4 us of CPU
                       96 KiB of memory traffic at 31.56 GB/s =   3.1 us
                       12 syscalls              at 342.13 ns =    4.1 us
                       14 KiB on a 10 GbE wire  at 1.25 GB/s =   11.5 us
                       1 fsync                                 = 503.9 us

per-core CPU ceiling      1 / 395.4 us   =   2,529 req/s   x 10 cores = 25,288
durable-write ceiling     1 / 503.9 us   =   1,985 req/s   x 1 device =  1,985
```

Everything else has more than an order of magnitude of headroom. **The machine's answer is 1,985 req/s**, and it is set by one line of code, not by the hardware.

### C10K to C10M

In 1999 Dan Kegel wrote *The C10K Problem* (maintained through 2014), and the question in the title — can one server handle ten thousand concurrent clients? — was a genuinely hard research question. The answer at the time was mostly no, for a specific and now-obsolete reason: the APIs for waiting on many sockets were **O(n)**. `select()` and `poll()` require the kernel to walk every descriptor you handed it on every single call, so the cost of asking "is anything ready?" grew linearly with the number of connections, whether or not any of them were active. Ten thousand idle connections made the *idle* case expensive.

That was fixed by event notification interfaces that are **O(number of ready events)** rather than O(number of watched descriptors) — `epoll` on Linux (`epoll(7)`), `kqueue` on the BSDs. [Blocking vs Non-Blocking I/O: select, poll & epoll](../../08-concurrency-and-performance/03-blocking-vs-non-blocking-io/) builds both and measures the difference: an `epoll_wait()` that costs the same 0.9 µs whether it watches 11 descriptors or 1,001, against a `select()` that climbs to 40.7 µs and then refuses to run at all.

So C10K is solved, and the framing has moved on to C10M — ten *million* concurrent connections, a target Robert Graham put on the map at Shmoocon in 2013. What limits you now is not the kernel's notification API. It is **memory per connection**, and you can compute it yourself:

```text
per idle TCP connection, roughly:
   socket + inet_sock + tcp_sock structs      ~   2 KB kernel memory
   minimum send + receive buffer allocation   ~   4 KB and up (autotuned)
   your application's per-connection object   ~ 0.5 KB to several KB
                                              ---------------------------
                                              ~   4 KB to 10 KB, honestly

  1,000,000 connections  x  6 KB   =    6 GB      comfortable on a modern box
 10,000,000 connections  x  6 KB   =   60 GB      possible, and now it is a
                                                  memory-capacity decision
```

The consequences are worth stating plainly, because they invert the old advice. **Connection count is a memory question, not a concurrency question.** A million idle WebSocket connections on one machine is an ordinary engineering result today. If your per-connection cost is 200 KB instead of 6 KB — because each connection holds a buffer, a session object, a parsed cookie and a trace context — then a million connections is 200 GB and you have a problem that no amount of `epoll` will fix. The wall moved from the kernel to your own allocation habits, which is a theme of this entire lesson.

Two smaller ceilings do still bite, and both are configuration rather than physics: the per-process file descriptor limit (`ulimit -n`, still 1024 by default on many systems, which is a comedy of a number in 2026), and the ephemeral port range — an *outbound* limit of roughly 28,000 simultaneous connections to the same destination IP and port, because a TCP connection is identified by the 4-tuple (source IP, source port, destination IP, destination port) and only the source port is free to vary.

### Vertical scaling is real, and it has a price curve

"Just buy a bigger machine" is treated as embarrassing advice. It should not be. It is the only scaling strategy with a **distribution tax of exactly zero**: no consistency problem, no network hop between components that used to be a function call, no partial failure, no service discovery, no distributed trace to read at 3 a.m. That is worth a great deal, and it is never on the invoice, which is why it never wins the argument.

What it does have is a price curve. Two effects work against you as the machine grows:

**Price is roughly linear inside an instance family and then stops being linear.** Within a family, list price per vCPU is close to flat — that part of the folklore is out of date. The superlinearity appears at the top: whole-socket, metal and high-memory instances carry a premium, and above the largest instance the price is not high, it is *undefined*, because you cannot buy the machine at all.

**Delivered capacity is sublinear the whole way up.** This is the effect that actually matters, and it is the subject of the next lesson. Doubling the cores does not double the throughput, because the work does not perfectly parallelise and because the parts that coordinate get more expensive as there are more of them to coordinate. Lesson 2 derives the shape properly.

The code models both. Read the table as *shape*, not as prices — the factors are assumptions and the console says so:

```text
    vCPU    price(rel)   capacity(rel)   $ per unit capacity   vs 2 vCPU
        2         1.00            1.00                 1.000       1.00x
       16         8.00            6.33                 1.263       1.26x
       64        34.40           21.67                 1.587       1.59x
      128        89.44           40.09                 2.231       2.23x
```

At 128 vCPU you pay **2.23x more per unit of delivered capacity** than at 2 vCPU. And 40.09 units of capacity from 41 small boxes costs 41 price units against the big box's 89.44 — **2.18x cheaper**. On hardware price alone, scale-out wins at the *first* doubling and never stops winning.

So the honest conclusion is not "vertical scaling is cheaper". It usually is not. The honest conclusion is: **that table prices hardware and nothing else.** It does not price the load balancer, the cross-zone bytes, the consistency work, the partial failures, or the engineer-years. Vertical scaling's product is not price-performance. It is *simplicity*, and simplicity is the thing you are actually buying when you resist the fleet.

Two hard limits end the strategy regardless. You will eventually exceed the largest machine that exists. And a single machine cannot exceed its own availability — which is the next section, and the reason most teams end up distributed.

### Efficiency before architecture

Here is the comparison that should happen before any architecture discussion. One workload — filter 40,000 records by region, look up a rank, apply a tax, format a line — implemented twice. Byte-identical output, asserted in code. Same algorithm on paper. The difference is four ordinary habits:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 450" width="100%" style="max-width:840px" role="img" aria-label="Measured machines required to serve twelve thousand requests per second at four implementation quality levels. The naive version needs twenty-seven machines at 452 requests per second each; dropping a defensive deepcopy brings it to eleven machines; replacing two linear scans with hashed lookups brings it to three; and micro-optimizing string building changes nothing measurable.">
  <defs>
    <marker id="p11-01-a3" markerWidth="10" markerHeight="10" refX="6" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Machines required at 12,000 req/s — measured, same output, same algorithm</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <g fill="none" stroke="currentColor" stroke-width="1.5">
      <path d="M118 348 L 852 348"/><path d="M118 348 L 118 74"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1" opacity="0.35">
      <path d="M118 288 L 852 288"/><path d="M118 228 L 852 228"/><path d="M118 168 L 852 168"/><path d="M118 108 L 852 108"/>
    </g>
    <g fill="currentColor" font-size="9.5" text-anchor="end" opacity="0.7">
      <text x="110" y="352">0</text><text x="110" y="292">7</text><text x="110" y="232">14</text><text x="110" y="172">21</text><text x="110" y="112">28</text>
    </g>
    <text x="40" y="211" font-size="10.5" fill="currentColor" opacity="0.85" transform="rotate(-90 40 211)" text-anchor="middle">machines you must buy</text>

    <rect x="160" y="116" width="118" height="232" rx="4" fill="#d64545" fill-opacity="0.16" stroke="#d64545" stroke-width="2"/>
    <rect x="342" y="254" width="118" height="94" rx="4" fill="#e0930f" fill-opacity="0.16" stroke="#e0930f" stroke-width="2"/>
    <rect x="524" y="322" width="118" height="26" rx="4" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="2"/>
    <rect x="706" y="322" width="118" height="26" rx="4" fill="#0fa07f" fill-opacity="0.16" stroke="#0fa07f" stroke-width="2"/>

    <g fill="currentColor" text-anchor="middle" font-weight="700">
      <text x="219" y="106" font-size="20" fill="#d64545">27</text><text x="401" y="244" font-size="20" fill="#e0930f">11</text>
      <text x="583" y="312" font-size="20" fill="#0fa07f">3</text><text x="765" y="312" font-size="20" fill="#0fa07f">3</text>
    </g>

    <g fill="currentColor" text-anchor="middle">
      <text x="219" y="368" font-size="10.5" font-weight="700">v0 · as written</text><text x="219" y="383" font-size="9" opacity="0.85">452 req/s per box</text>
      <text x="219" y="396" font-size="9" opacity="0.7">221.46 ms / 40k records</text><text x="401" y="368" font-size="10.5" font-weight="700">v1 · no deepcopy</text>
      <text x="401" y="383" font-size="9" opacity="0.85">1,108 req/s per box</text><text x="401" y="396" font-size="9" opacity="0.7">2.45x from deleting 1 line</text>
      <text x="583" y="368" font-size="10.5" font-weight="700">v2 · hash, do not scan</text><text x="583" y="383" font-size="9" opacity="0.85">4,053 req/s per box</text>
      <text x="583" y="396" font-size="9" opacity="0.7">3.66x: set + dict, not O(n)</text><text x="765" y="368" font-size="10.5" font-weight="700">v3 · hoist + one join</text>
      <text x="765" y="383" font-size="9" opacity="0.85">4,745 req/s per box</text><text x="765" y="396" font-size="9" opacity="0.7">1.17x — nearly nothing</text>
    </g>

    <path d="M278 132 C 320 132, 320 200, 340 248" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.6" marker-end="url(#p11-01-a3)"/>
    <path d="M460 268 C 495 268, 500 300, 520 316" fill="none" stroke="currentColor" stroke-width="1.5" stroke-dasharray="4 4" opacity="0.6" marker-end="url(#p11-01-a3)"/>

    <g fill="none" stroke="#3553ff" stroke-width="1.6">
      <path d="M700 148 L 700 96 L 240 96" marker-end="url(#p11-01-a3)"/>
    </g>
    <g fill="currentColor">
      <text x="708" y="152" font-size="10.5" font-weight="700" fill="#3553ff">24 machines deleted</text><text x="708" y="167" font-size="9" opacity="0.85">by a 10.5x factor in</text>
      <text x="708" y="180" font-size="9" opacity="0.85">code, not in hardware</text>
    </g>

    <text x="440" y="424" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">The two fixes that mattered are the two nobody argues about in review. The one everyone argues</text><text x="440" y="440" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">about — string building — moved 3 machines to 3. Profile before you provision.</text>
  </g>
</svg>
```

**10.5x**, and the machine count at a fixed 12,000 req/s goes from **27 to 3**. Twenty-four machines that were never a capacity problem.

The attribution is the interesting part, and it is uncomfortable:

- **Deleting one `copy.deepcopy()` was worth 2.45x.** The copy existed so the function would not mutate its input. The function never mutated its input.
- **Replacing two linear scans with hashed lookups was worth 3.66x.** A `set` instead of rebuilding a list to test membership, and a `dict` instead of `list.index()`. Both are O(n) → O(1) changes on collections of 100 and 200 items — small enough that nobody thinks of them as algorithmic.
- **The string-building micro-optimisation was worth 1.17x**, and on a quieter run it measured inside the noise. Hoisting globals into locals and replacing eight `+` concatenations with one `"".join()` is the change that gets argued about in every code review, and CPython 3.12's specialising interpreter has largely already done it for you.

So the two fixes that mattered are the two nobody argues about, and the one everybody argues about moved three machines to three. That is not an argument against caring about performance. It is an argument for **measuring before you optimise, and measuring before you provision** — the same discipline, one lesson apart. [Profiling: Finding the Real Bottleneck](../../08-concurrency-and-performance/13-profiling/) is where the tooling lives; this lesson is about what the number *means* once you have it.

The asymmetry is the point:

> A 10x constant-factor win is one engineer-week, once. A distributed system is a permanent tax on every engineer who ever touches the codebase again.

The 10x is also strictly better than the fleet on every axis. It reduces cost, reduces latency (there is no coordination to pay for), reduces failure modes, and reduces the number of things that can be misconfigured at 3 a.m. Buying 24 more machines fixes throughput and worsens all four.

The trap on this road is real and should be named: **efficiency work has a floor, and distribution does not.** You cannot optimise your way past the largest machine, and you cannot optimise your way to two failure domains. When you have found and fixed your constant factor and the wall is still there — with a name and a number — the fleet is the right answer, and the rest of this phase is how to build one that works.

### What actually forces you off one machine

There are exactly four honest reasons. If your reason is not one of these, it is a preference.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 500" width="100%" style="max-width:840px" role="img" aria-label="The four honest reasons to leave one machine, ordered along an axis by which one arrives first for a typical team. Availability arrives first and is a reliability reason, followed by blast radius and deploy safety, then geography, and finally exceeding the largest available machine, which is the only reason that is actually about capacity.">
  <defs>
    <marker id="p11-01-a4" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto"><path d="M0,0 L7,3 L0,6 Z" fill="currentColor"/></marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-family="'JetBrains Mono', ui-monospace, monospace" font-size="14.5" font-weight="700" fill="currentColor">Four honest reasons to leave one machine — in the order they actually arrive</text>
  <g font-family="'JetBrains Mono', ui-monospace, monospace">
    <path d="M28 78 L 838 78" fill="none" stroke="currentColor" stroke-width="1.6" marker-end="url(#p11-01-a4)"/>
    <text x="28" y="66" font-size="9.5" fill="currentColor" opacity="0.8">arrives first — usually before you have a scale problem at all</text><text x="836" y="66" font-size="9.5" fill="currentColor" opacity="0.8" text-anchor="end">arrives last — most teams never get here</text>

    <g stroke="none">
      <circle cx="124" cy="78" r="6" fill="#d64545"/><circle cx="330" cy="78" r="6" fill="#e0930f"/><circle cx="536" cy="78" r="6" fill="#7c5cff"/><circle cx="742" cy="78" r="6" fill="#0fa07f"/>
    </g>
    <g fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.5">
      <path d="M124 84 L 124 108"/><path d="M330 84 L 330 108"/><path d="M536 84 L 536 108"/><path d="M742 84 L 742 108"/>
    </g>

    <g fill="none" stroke-width="2" stroke-linejoin="round">
      <rect x="24" y="108" width="200" height="252" rx="11" fill="#d64545" fill-opacity="0.13" stroke="#d64545"/>
      <rect x="230" y="108" width="200" height="252" rx="11" fill="#e0930f" fill-opacity="0.13" stroke="#e0930f"/>
      <rect x="436" y="108" width="200" height="252" rx="11" fill="#7c5cff" fill-opacity="0.12" stroke="#7c5cff"/>
      <rect x="642" y="108" width="200" height="252" rx="11" fill="#0fa07f" fill-opacity="0.12" stroke="#0fa07f"/>
    </g>

    <g fill="currentColor">
      <text x="40" y="132" font-size="11" font-weight="700" fill="#d64545">1 · AVAILABILITY</text><text x="40" y="150" font-size="9.5" opacity="0.9">One machine is one failure</text>
      <text x="40" y="164" font-size="9.5" opacity="0.9">domain. It cannot exceed its</text><text x="40" y="178" font-size="9.5" opacity="0.9">own uptime, ever.</text>
      <text x="40" y="200" font-size="9" font-weight="700" opacity="0.95">THE TEST</text><text x="40" y="215" font-size="9" opacity="0.85">Is your SLO tighter than one</text>
      <text x="40" y="228" font-size="9" opacity="0.85">box's measured uptime?</text><text x="40" y="250" font-size="9.5" font-weight="700" fill="#d64545">measured: 99.9% = 8.8 h/yr</text>
      <text x="40" y="265" font-size="9" opacity="0.85">a 64x bigger box is still</text><text x="40" y="278" font-size="9" opacity="0.85">down 8.8 h/yr. Vertical</text>
      <text x="40" y="291" font-size="9" opacity="0.85">scaling buys zero nines.</text><text x="40" y="313" font-size="9" opacity="0.85">2 replicas: 6.0 nines if</text>
      <text x="40" y="326" font-size="9" opacity="0.85">independent, 4.0 if 10% of</text><text x="40" y="339" font-size="9" opacity="0.85">failures are common-mode.</text>
      <text x="40" y="353" font-size="9" font-weight="700" fill="#d64545">RELIABILITY, not scale</text>

      <text x="246" y="132" font-size="11" font-weight="700" fill="#e0930f">2 · BLAST RADIUS</text><text x="246" y="150" font-size="9.5" opacity="0.9">One process means every</text>
      <text x="246" y="164" font-size="9.5" opacity="0.9">deploy is a full outage and</text><text x="246" y="178" font-size="9.5" opacity="0.9">every bug reaches everyone.</text>
      <text x="246" y="200" font-size="9" font-weight="700" opacity="0.95">THE TEST</text><text x="246" y="215" font-size="9" opacity="0.85">Can you ship a bad build to</text>
      <text x="246" y="228" font-size="9" opacity="0.85">1% of traffic and roll back?</text><text x="246" y="250" font-size="9.5" font-weight="700" fill="#e0930f">what it buys</text>
      <text x="246" y="265" font-size="9" opacity="0.85">canary, rolling restarts,</text><text x="246" y="278" font-size="9" opacity="0.85">a memory leak that kills one</text>
      <text x="246" y="291" font-size="9" opacity="0.85">replica instead of the site.</text><text x="246" y="313" font-size="9" opacity="0.85">Also the cheapest reason to</text>
      <text x="246" y="326" font-size="9" opacity="0.85">go from 1 machine to 2 —</text><text x="246" y="339" font-size="9" opacity="0.85">it needs no data split.</text>
      <text x="246" y="353" font-size="9" font-weight="700" fill="#e0930f">RELIABILITY, not scale</text>

      <text x="452" y="132" font-size="11" font-weight="700" fill="#7c5cff">3 · GEOGRAPHY</text><text x="452" y="150" font-size="9.5" opacity="0.9">Light is 300,000 km/s in</text>
      <text x="452" y="164" font-size="9.5" opacity="0.9">vacuum and ~200,000 km/s in</text><text x="452" y="178" font-size="9.5" opacity="0.9">fibre. That is the rule.</text>
      <text x="452" y="200" font-size="9" font-weight="700" opacity="0.95">THE TEST</text><text x="452" y="215" font-size="9" opacity="0.85">Do users 8,000 km away need</text>
      <text x="452" y="228" font-size="9" opacity="0.85">a response under 100 ms?</text><text x="452" y="250" font-size="9.5" font-weight="700" fill="#7c5cff">cross-region RTT 70-150 ms</text>
      <text x="452" y="265" font-size="9" opacity="0.85">No amount of CPU fixes this.</text><text x="452" y="278" font-size="9" opacity="0.85">No cache fixes the first</text>
      <text x="452" y="291" font-size="9" opacity="0.85">byte of an uncached write.</text><text x="452" y="313" font-size="9" opacity="0.85">This is the one reason that</text>
      <text x="452" y="326" font-size="9" opacity="0.85">no optimisation can ever</text><text x="452" y="339" font-size="9" opacity="0.85">retire. Lesson 10.</text>
      <text x="452" y="353" font-size="9" font-weight="700" fill="#7c5cff">PHYSICS, not scale</text>

      <text x="658" y="132" font-size="11" font-weight="700" fill="#0fa07f">4 · YOU RAN OUT</text><text x="658" y="150" font-size="9.5" opacity="0.9">You genuinely exceeded the</text>
      <text x="658" y="164" font-size="9.5" opacity="0.9">largest machine you can rent,</text><text x="658" y="178" font-size="9.5" opacity="0.9">on a wall you have measured.</text>
      <text x="658" y="200" font-size="9" font-weight="700" opacity="0.95">THE TEST</text><text x="658" y="215" font-size="9" opacity="0.85">Which of the four walls? Say</text>
      <text x="658" y="228" font-size="9" opacity="0.85">its name and its number.</text><text x="658" y="250" font-size="9.5" font-weight="700" fill="#0fa07f">measured here: 10.5x</text>
      <text x="658" y="265" font-size="9" opacity="0.85">of headroom sat in front of</text><text x="658" y="278" font-size="9" opacity="0.85">this answer — 27 machines</text>
      <text x="658" y="291" font-size="9" opacity="0.85">became 3 with no new deps.</text><text x="658" y="313" font-size="9" opacity="0.85">If you cannot name the wall,</text>
      <text x="658" y="326" font-size="9" opacity="0.85">you have not run out. You</text><text x="658" y="339" font-size="9" opacity="0.85">have not measured.</text>
      <text x="658" y="353" font-size="9" font-weight="700" fill="#0fa07f">the ONLY scale reason</text>
    </g>

    <rect x="24" y="382" width="818" height="46" rx="9" fill="#3553ff" fill-opacity="0.10" stroke="#3553ff" stroke-width="1.8"/>
    <g fill="currentColor">
      <text x="40" y="402" font-size="10.5" font-weight="700" fill="#3553ff">Three of the four are not scalability problems at all.</text><text x="40" y="418" font-size="9.5" opacity="0.9">Reason 1 arrives first for almost every team — which means most fleets exist for reliability, and are then blamed for being slow.</text>
    </g>
    <text x="440" y="454" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">If your answer is "we need to scale", the honest follow-up is: which of these four, and what did you measure?</text><text x="440" y="470" font-size="11" text-anchor="middle" fill="currentColor" opacity="0.9">Anything else is reason 5: it felt slow. Reason 5 costs the same as the other four and buys nothing.</text>
  </g>
</svg>
```

Three of those four are not scalability problems at all, and the ordering matters more than the list. **Availability arrives first for almost every team.** One machine is one failure domain: one kernel, one power supply, one deploy, one bad config push. It cannot exceed its own uptime, and no amount of vertical scaling changes that number by a single decimal place. A machine 64 times larger with the same 99.9% availability is down for exactly the same **8.8 hours a year**.

Redundancy is the only thing that buys nines, and the arithmetic has a large catch:

```text
one machine at 99.9%                        3.0 nines      8.8 h/year
two machines, failures independent          6.0 nines     31.5 s/year
two machines, 1% of failures common-mode    5.0 nines      5.8 min/year
two machines, 10% of failures common-mode   4.0 nines     53.0 min/year
```

**Independence is the assumption doing all the work.** If 10% of failures are common-mode — a shared power feed, a shared rack, a shared availability zone, a config push that reaches both, a deploy that ships the same bug to both — then two replicas buy you *one* extra nine instead of three. And a third and fourth replica buy you essentially nothing, because you are no longer bounded by the independent term at all. Lesson 9 measures correlated failure properly and shows what shuffle sharding does about it.

The tax runs in the other direction too, and it is the one nobody budgets for. Availability multiplies down a serial dependency chain:

```text
a request that must touch N services, each 99.95% available:
   N =  1     99.9500%     4.4 h/year
   N =  5     99.7502%    21.9 h/year
   N = 10     99.5011%    43.7 h/year
```

Split one 99.95% machine into ten services that must **all** answer for a request to succeed and you have built a 99.50% system. You spent 1.3 nines to buy scalability, and no invoice arrived. This is why the phase that follows spends so much time on things — replicas, health checks, outlier ejection, hedged requests, blast-radius containment — whose only purpose is to win back the availability that distribution took from you.

The setup for everything after this: **most fleets exist for reliability, and are then judged on speed.** Getting that backwards is how teams end up with 40 machines, a p99 that is worse than it was on one box, and no idea which of the four walls they were ever standing next to.

## Build It

[`code/one_machine.py`](code/one_machine.py) is five numbered arguments. Standard library only, seeded, no network, ~3 seconds. Sections 1–3 measure the box it runs on; sections 4 and 5 are arithmetic, and the console labels which is which.

**Your numbers will not match the ones quoted below, and that is the point.** This is the only lesson in the phase that measures real hardware rather than a seeded simulation, so the absolute figures belong to the machine that ran it — a laptop under load, a shared CI runner and a bare-metal server will disagree by multiples. Running this on a busy machine produced 315 req/s per box where an idle one produced 452. What survives that noise is the **shape**: which of the four walls binds first, how many multiples of headroom sit in front of the next one, and the ratio between the naive and careful implementations. Those held to within a few percent across every machine this was run on. Read the ratios, not the absolutes — and then run it on *your* box, because the whole argument of this lesson is that the only ceiling that matters is the one you measured yourself.

**Measuring a wall means isolating it.** The syscall measurement is the clearest example. A loop calling `os.write()` measures the syscall *plus* the interpreter's loop and call overhead, so the code measures an empty loop separately and subtracts:

```python
def measure_syscall(iters: int = 200_000, reps: int = 3) -> float:
    """Seconds per os.write() to /dev/null, interpreter overhead included."""
    fd = os.open(os.devnull, os.O_WRONLY)
    payload = b"x"
    best = math.inf
    try:
        for _ in range(reps):
            t0 = time.perf_counter()
            for _ in range(iters):
                os.write(fd, payload)
            best = min(best, (time.perf_counter() - t0) / iters)
    finally:
        os.close(fd)
    return best
```

Note `best = min(...)` rather than a mean. For a *ceiling* measurement the best observed run is the honest statistic: contention, scheduling and noisy neighbours can only ever make a measurement slower than the hardware is, never faster. The same trick isolates memory latency — two loops that execute identical Python, differing only in whether the index sequence is sequential or random, so the difference between them is the cache miss and nothing else:

```python
    seq = array.array("q", [(i * stride) % n for i in range(touches)])
    rnd = array.array("q", [RNG.randrange(n) for _ in range(touches)])
```

The working set is 192 MiB deliberately. Make it small enough to fit in the last-level cache and the "random" walk is just an L3 hit, and you will measure a memory latency of 40 ns and believe it.

**The efficiency ladder is an ablation, not a demo.** Five renderers, four habits removed one at a time, and an assertion that fails the run if any of them changes the output by a single byte:

```python
    for name, fn in ladder:
        dt, out = timed(fn, records)
        if reference is None:
            reference = out
        assert out == reference, f"{name} changed the output — not a fair comparison"
        results.append((name, dt, N_RECORDS / dt))
```

Ablation attributes cost to the *order* you remove things in, which is worth knowing when you read the per-step column: each step's factor is measured against the previous step, not against a clean baseline. The end-to-end factor is the only order-independent number in the table.

Run it:

```bash
docker compose exec -T app python \
  phases/11-scalability-and-reliability/01-what-one-machine-can-do/code/one_machine.py
```

```console
one machine — what it actually does, measured on the box this runs on
  python 3.12.13   os.cpu_count() = 10   page = 4096 B

== 1 · FIND YOUR WALLS — WHAT THIS BOX ACTUALLY DOES PER SECOND ==
  wall            what was measured                       cost/op        ceiling
  CPU             interpreter integer op                  49.43 ns      20.23 M/s
  MEMORY bw       64 MiB bytearray copy                   33.22 us/MiB   31.56 GB/s
  MEMORY lat      random 8 B read, 192 MiB working set   189.55 ns       5.28 M/s
  MEMORY lat      sequential 8 B read, same array         39.12 ns      25.56 M/s
  I/O syscall     os.write(1 B) to /dev/null             342.13 ns       2.92 M/s
  I/O buffered    os.write(4 KiB), no flush                1.46 us     685.87 k/s
  I/O durable     os.write(4 KiB) + os.fsync()           503.87 us       1.98 k/s
  NIC             10 GbE line rate (IEEE 802.3, spec)           --    1.25 GB/s
  the empty-loop baseline is   12.99 ns, so the syscall itself is ~ 329.14 ns.
  random reads cost 4.8x sequential ones (+ 150.43 ns of pure cache miss, 500 fsyncs sampled).
  durability costs      346x a buffered write. That factor is the whole
  reason group commit exists (Gray & Reuter 1993, ch. 12).

== 2 · ONE REQUEST, DECOMPOSED — WHICH WALL BINDS FIRST ==
  one request = 8,000 interpreter ops + 96 KiB of memory
  traffic + 12 syscalls + 1 fsync + 14 KiB on the wire.
  'per core' x10 only for the walls that actually replicate per core.
  (a) one fsync per request
    wall           cost per request           req/s 1 core   x cores?   req/s this box
    CPU            8,000 interpreter ops             2,529     yes            25,288
    MEMORY bw      96 KiB of traffic               321,085     NO            321,085
    I/O syscall    12 syscalls                     243,570     yes         2,435,698
    I/O durable    1 fsync                           1,985     NO              1,985  <-- BINDS
    NIC            14 KiB on the wire               87,193     NO             87,193
    ceiling 1,985 req/s, set by I/O durable; the next wall is 12.7x further out.
  (b) group commit, 1 fsync per 128 requests
    wall           cost per request           req/s 1 core   x cores?   req/s this box
    CPU            8,000 interpreter ops             2,529     yes            25,288  <-- BINDS
    MEMORY bw      96 KiB of traffic               321,085     NO            321,085
    I/O syscall    12 syscalls                     243,570     yes         2,435,698
    I/O durable    0.0078125 fsync                 254,031     NO            254,031
    NIC            14 KiB on the wire               87,193     NO             87,193
    ceiling 25,288 req/s, set by CPU; the next wall is 3.4x further out.
  the binding wall MOVED, and the box got 12.7x faster. No hardware changed.
  one fsync per request is a 1,985 Hz device pretending to be an architecture.
  note which walls do NOT multiply by cores: memory bandwidth is one bus, the
  disk is one queue, the NIC is one link. And CPU only multiplies if you run
  one worker process per core — a single CPython process does not (Phase 8 L02).

== 3 · THE EFFICIENCY GAP — THE MACHINES YOU DID NOT NEED TO BUY ==
  40,000 records -> 838,980 bytes of identical output, best of 5.
  one response renders 400 rows; the fleet must serve 12,000 req/s.
    step                       wall time    records/s     req/s   boxes   this fix alone
    v0 all five habits          221.46 ms      180,622       452      27        --
    v1 drop the deepcopy         90.25 ms      443,199     1,108      11     2.45x
    v2 hash, do not scan         24.67 ms    1,621,120     4,053       3     3.66x
    v3 hoist + one join          21.07 ms    1,898,017     4,745       3     1.17x
  the whole win is in: drop the deepcopy, hash, do not scan.
  10.5x end to end. No new dependency, no new algorithm, no C extension,
  and byte-identical output — the assert above fails the run if it is not.
  at 12,000 req/s that is 27 machines against 3: 24 boxes
  that were never a capacity problem. The v0 box serves 452 req/s
  and looks maxed out. It is not maxed out. It is wasteful, and buying machines
  makes the waste permanent, load-balanced, and somebody's monthly line item.

== 4 · THE VERTICAL PRICE CURVE (A MODEL, NOT AN INVOICE) ==
  MODELLED, not measured: price factors and the sublinear capacity factor
  are assumptions. Lesson 02 derives the capacity curve properly.
    vCPU    price(rel)   capacity(rel)   $ per unit capacity   vs 2 vCPU
        2         1.00            1.00                 1.000       1.00x
        4         2.00            1.85                 1.081       1.08x
        8         4.00            3.42                 1.169       1.17x
       16         8.00            6.33                 1.263       1.26x
       32        16.00           11.71                 1.366       1.37x
       64        34.40           21.67                 1.587       1.59x
      128        89.44           40.09                 2.231       2.23x
  scale-out alternative: 40.09 units of capacity needs 41 x 2-vCPU boxes
  = 41 price units against the big box's 89.44 — 2.18x cheaper per unit of capacity.
  scale-out already wins at the FIRST doubling (1.08x worse at 4 vCPU)
  and never stops winning. So why does anyone still buy the big machine?
  because this table prices hardware and nothing else.
  the small-box column omits the load balancer, the cross-AZ bytes, the
  consistency work, the partial failures and the engineer-years. Vertical
  scaling's real product is not price/performance — it is a distribution tax
  of exactly zero. That is the bill the next thirteen lessons itemise.

== 5 · ONE MACHINE IS ONE FAILURE DOMAIN ==
  a machine with 99.9% annual availability is down     8.8 h/year.
  a machine 64x larger, with the same availability, is down for exactly as long:
  vertical scaling buys throughput and buys ZERO nines. Redundancy buys nines.
    replicas | independent      | 1% common-mode   | 10% common-mode
             | nines   per year | nines   per year | nines   per year
       1     |   3.0      8.8 h |   3.0      8.8 h |   3.0      8.8 h
       2     |   6.0     31.5 s |   5.0      5.8 m |   4.0     53.0 m
       3     |   9.0       <1 s |   5.0      5.3 m |   4.0     52.6 m
       4     |  12.0       <1 s |   5.0      5.3 m |   4.0     52.6 m
  independence is the assumption doing all the work. A shared power feed, a
  shared deploy, a shared config push, a shared AZ: all of them make c > 0.
  at c = 10%, two replicas buy you ONE extra nine, not three, and the third and
  fourth replica buy you nothing at all. Lesson 09 measures correlated failure.
  and the tax in the other direction, which nobody budgets for:
    a request that must touch N services, each 99.95% available:
      N =  1   end-to-end  99.9500%   nines   3.3       4.4 h/year
      N =  2   end-to-end  99.9000%   nines   3.0       8.8 h/year
      N =  5   end-to-end  99.7502%   nines   2.6      21.9 h/year
      N = 10   end-to-end  99.5011%   nines   2.3      43.7 h/year
      N = 20   end-to-end  99.0047%   nines   2.0      87.2 h/year
  split one 99.95% machine into 10 services that must ALL answer and you have
  99.50% — you spent 1.3 nines to buy scalability, and nobody sent an email.

  (total wall time 3.1 s)
```

**Your numbers will differ, and that is the exercise.** This ran in a Docker container on a laptop; the fsync figure in particular reflects a virtualised disk, and bare-metal NVMe will be considerably faster. The absolute values are properties of one box. The *shape* is not: the four walls will still be orders of magnitude apart, the smallest will still be your ceiling, and it will still probably not be the one on your dashboard.

**Section 1** prices the box. The two numbers to internalise are the memory-latency delta and the durability tax. **189.55 ns random against 39.12 ns sequential** is the cache miss, measured with the interpreter overhead cancelled — a 4.8x penalty for touching memory in the wrong order, which no profiler will report as a line of code. And **503.87 µs for `write` + `fsync` against 1.46 µs for the same write buffered** is **346x** for the word "durable". Neither of these is a hardware defect. Both are prices, and both are payable in different amounts depending on how you write the program.

**Section 2 is the method the whole phase depends on.** It takes one modelled request, multiplies each cost by the measured per-operation price, and prints the req/s each wall permits. The binding wall is **I/O durable at 1,985 req/s**, and the next wall is **12.7x further out** — which means eleven-twelfths of this machine is not being used at the moment it stops responding. Then it changes exactly one thing: batch the flushes 128 at a time. The disk wall moves to **254,031 req/s**, the box's ceiling becomes **25,288 req/s** set by CPU, and the machine is **12.7x faster** with no hardware change and no new dependency. That is the argument in one table. A team that never ran it buys twelve machines.

**Section 3 is the argument about your codebase**, and its most valuable output is the attribution. `deepcopy` alone was **2.45x**. Hashed lookups instead of two linear scans were **3.66x**. The micro-optimisation everyone has opinions about was **1.17x**. Note also what the whole exercise is *not*: there is no C extension, no rewrite, no new library, and no algorithmic redesign. The output is asserted byte-identical. **10.5x** for four small edits, and **24 fewer machines** at the fixed target.

**Sections 4 and 5 are arithmetic, and the console says so on the banner.** The price factors in section 4 are a model — do not quote them as prices. What is not modelled is the conclusion: per unit of *delivered* capacity, scale-out is cheaper from the first doubling, so anyone buying a big machine is buying something other than price-performance. Section 5 has no model in it at all; it is probability. Two independent replicas at 99.9% give **six nines**. Two replicas that share a 10% common-mode failure give **four**. The third and fourth replicas move that number by **0.0 nines**, which is the whole reason Lesson 9 exists.

## Use It

Everything above is measurable on a production box in about ten minutes, with tools that are already installed. The goal is a sentence of the form *"we are at X% of <wall>, and the next wall is Y% used"*.

**Start with pressure, not utilization.** Linux exposes **PSI — Pressure Stall Information** (in the kernel since 4.20, documented in `Documentation/accounting/psi.rst`), and it is the single best signal on this list and the most underused. Utilization tells you a resource is busy. PSI tells you **how much time your tasks spent stalled waiting for it**, which is the thing you actually care about:

```bash
cat /proc/pressure/cpu /proc/pressure/io /proc/pressure/memory
# some avg10=27.14 avg60=22.06 avg300=9.11 total=1483920401
# full avg10=11.02 avg60=9.83  avg300=4.10 total=884521004
```

Read it like this. **`some`** is the percentage of wall time in which *at least one* runnable task was stalled on that resource; **`full`** is the percentage in which *every* task was stalled, meaning the whole box was doing nothing but waiting. `avg10/60/300` are those percentages over 10, 60 and 300 seconds, and `total` is cumulative microseconds of stall — the one to alert on, because it cannot be missed between scrapes the way an average can.

Why this beats a utilization graph: a disk at 100% utilization with one thread waiting on it is a healthy, well-fed disk. The same disk with `io full avg10=40` means 40% of your machine's time is *nobody making progress*. In cgroup v2 the same files exist per-container (`/sys/fs/cgroup/<slice>/io.pressure`), so you can attribute the stall to a service rather than to a host. Practical thresholds to start from and then tune: **`some avg60` above 10% deserves attention; `full avg60` above 5% is a live problem.**

Then confirm which wall with the specific tools:

```bash
vmstat 1 5          # r = runnable (CPU), b = blocked (I/O), si/so = swapping,
                    # wa = % time waiting on I/O. r > cores means CPU-bound.
iostat -x 1 5       # %util, await (ms per I/O), aqu-sz (queue depth).
                    # await climbing while %util is flat = the device is queueing.
sar -n DEV 1 5      # rxkB/s, txkB/s per interface. Compare against your link
                    # rate: 10 GbE = 1,250,000 kB/s. Are you at 1% or 80%?
ss -s               # socket totals. TCP: inuse/orphan/timewait. A large
                    # timewait count is a connection-churn problem, not load.
ss -tan state time-wait | wc -l
perf stat -a sleep 5
                    # IPC (instructions per cycle) and cache-miss rate for the
                    # whole box. IPC below ~0.5 with high cache-misses means
                    # you are memory-bound, not CPU-bound — a distinction no
                    # CPU-utilization graph can make.
numactl --hardware  # on multi-socket boxes: memory bandwidth is per-socket.
```

The `perf stat` line is the one that separates the two commonest walls. A box at 95% CPU with an IPC of 0.4 is not out of CPU — it is out of **memory bandwidth**, and its cores are stalled waiting for cache lines. Buying faster cores will do nothing; changing the data layout will do everything. [Profiling: Finding the Real Bottleneck](../../08-concurrency-and-performance/13-profiling/) covers finding the responsible code once you know which resource it is; do not re-derive that here.

For the durability wall specifically, the knobs are named in every database:

```sql
-- Postgres: group commit. Wait this long to batch concurrent commits into
-- one flush. Costs latency on a quiet system, buys throughput on a busy one.
SET commit_delay = 200;        -- microseconds; default 0
SET commit_siblings = 5;       -- only delay if >= 5 other transactions active

-- The nuclear option, and the one people reach for without understanding it:
SET synchronous_commit = off;  -- acknowledges before the WAL is flushed.
-- This does NOT risk corruption. It risks losing the last few hundred
-- milliseconds of committed transactions on a crash. That is a product
-- decision, not a performance setting, and it belongs to whoever owns the data.
```

Finally, the procedure. Before you add a machine, produce these five lines:

1. **The wall.** Which of CPU / memory capacity / memory bandwidth / disk / syscall / NIC is saturating, with a number and the command that produced it. If you cannot fill this in, stop — you are not ready to spend money.
2. **The gap to the next wall.** If the binding wall is 12x below the others, the machine is 90% idle at its own ceiling, and there is a batching or caching change worth more than a fleet.
3. **The per-request budget.** Requests/second, divided into the wall's units. "Each request costs 1 fsync and the device does 1,985/s" is a complete diagnosis in one sentence.
4. **The efficiency check.** Run a profiler for five minutes on one box under real traffic. A defensive copy, a linear scan in a hot loop, or an N+1 query is worth more than any instance-type change, and this lesson measured 10.5x sitting inside code that reviewed cleanly.
5. **The real reason.** Which of the four honest reasons is this? If the answer is availability or blast radius, say so — you are buying reliability, and you should size and design for reliability rather than pretending it is a throughput project.

Then multiply, with the arithmetic written down. **Measure before you multiply.** The fleet you avoid is the cheapest fleet you will ever run.

## Key takeaways

- **Every scaling problem is one of four walls saturating first: CPU, memory (capacity, bandwidth and latency are three different walls), I/O (disk and the syscall boundary), and the NIC.** They saturate at wildly different points — measured here, the binding wall sat **12.7x below the next one**, so the machine was 92% idle at the moment it hit its ceiling. Your ceiling is the smallest of the four, never the average, and half of them (memory bandwidth, disk, NIC) do not multiply when you add cores.
- **Durability is the most expensive ordinary operation on a machine.** `write` + `fsync` of 4 KiB measured **503.87 µs against 1.46 µs buffered — 346x**, roughly the cost of a network round trip to another host in the same zone. One `fsync` per request capped this box at **1,985 req/s**; batching 128 commits into one flush moved the ceiling to **25,288 req/s** and moved the binding wall from the disk to the CPU. Same hardware, 12.7x, one batching change.
- **Memorise the ladder, because it spans 150,000,000x.** Measured here: interpreter op **49.43 ns**, sequential RAM read **39.12 ns**, random RAM read **189.55 ns** (**4.8x** — that gap is pure cache miss), syscall **~329 ns**, buffered 4 KiB write **1.46 µs**, fsync **503.87 µs**; same-zone RTT ~0.5 ms and cross-region RTT 70–150 ms are physics. One 100 ms cross-region round trip costs what **2.0 million interpreter operations** cost.
- **C10K was a kernel problem and is solved; connection count is now a memory problem.** `epoll`/`kqueue` made waiting O(ready events) instead of O(watched descriptors), so a million concurrent connections is an ordinary result at roughly 4–10 KB of kernel and application memory each. If your per-connection footprint is 200 KB, no event loop will save you — the wall moved from the kernel into your allocation habits.
- **A 10.5x constant factor was hiding in code that passed review.** Same output asserted byte-for-byte, no new dependency, no new algorithm: deleting one defensive `deepcopy` was **2.45x**, replacing two linear scans with a set and a dict was **3.66x**, and the string-building micro-optimisation everyone argues about was **1.17x**. At 12,000 req/s that is **27 machines versus 3**. Profile before you provision.
- **Vertical scaling loses on hardware price and wins on everything not printed on the invoice.** Modelled, per unit of *delivered* capacity, a 128-vCPU box costs **2.23x** what a 2-vCPU box costs, and 41 small boxes are **2.18x cheaper** than the one big one. What the big box sells is a distribution tax of exactly zero: no consistency problem, no network hop, no partial failure. That is what you are giving up, and the rest of this phase is the price list.
- **Vertical scaling buys zero nines, and independence is the assumption doing all the work.** One machine at 99.9% is down **8.8 hours a year**, and a 64x larger machine at 99.9% is down for exactly as long. Two independent replicas give **six nines (31.5 s/year)**; if just **10% of failures are common-mode** they give **four (53 min/year)**, and the third and fourth replicas add nothing measurable.
- **Distribution spends availability to buy scalability.** Ten services at 99.95% that must all answer produce a **99.50%** request — **43.7 hours a year** against 4.4. Availability is the reason that arrives first for most teams, and it is a *reliability* reason, not a scalability one. Knowing which of the four honest reasons you are acting on is the difference between an architecture and an expense.

Next: [The Universal Scalability Law: Why 2× the Machines Isn't 2× the Throughput](../02-universal-scalability-law/) — having found the ceiling of one machine, the next lesson shows why N machines never give you N times that ceiling, and why past a certain N they give you less.
